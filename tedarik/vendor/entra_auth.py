# Kaynak: Gokhanagingil/control@7720f4b095a067dbf810dbc1cd25937d88a2ee5f entra_auth.py. Kopya; uyarlama tedarik/session.py içinde. Yamalar: tedarik/vendor/PATCHES.md
"""Single-tenant Microsoft Entra web sign-in. Tokens never leave the server."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt
from cryptography.fernet import Fernet, InvalidToken

FLOW_COOKIE = "__Host-ksgrc_flow"
FLOW_SECONDS = 300
CALLBACK = "/auth/entra/callback"
ADMIN = "KS.GRC.Admin"
AUDITOR = "KS.GRC.Auditor"
ROLES = (ADMIN, AUDITOR)  # [tedarik yaması K-012] kabul edilen roller, öncelik sırasıyla
AUTHORITY = "https://login.microsoftonline.com"
GUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class Denied(ValueError):
    """The exception message is a non-sensitive operational reason."""


class Unavailable(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


@dataclass(frozen=True)
class Config:
    tenant: str
    client: str
    secret: str = field(repr=False)
    redirect: str
    context: str

    @property
    def issuer(self):
        return f"{AUTHORITY}/{self.tenant}/v2.0"

    @property
    def endpoint(self):
        return f"{AUTHORITY}/{self.tenant}/oauth2/v2.0"

    @property
    def origin(self):
        return self.redirect[:-len(CALLBACK)]

    @property
    def session_scope(self):
        return f"entra:{self.tenant}:{self.client}:{self.context}"


def configure(env):
    mode = env.get("CONTROL_AUTH_MODE", "local")
    if mode == "local":
        if any(k.startswith("CONTROL_ENTRA_") and v for k, v in env.items()):
            raise ValueError("CONTROL_AUTH_MODE=entra is required for Entra configuration")
        return None
    if mode != "entra" or env.get("CONTROL_COOKIE_SECURE") != "1":
        raise ValueError("Invalid auth mode or insecure Entra cookie configuration")
    tenant = env.get("CONTROL_ENTRA_TENANT_ID", "").lower()
    client = env.get("CONTROL_ENTRA_CLIENT_ID", "").lower()
    if not GUID.fullmatch(tenant) or not GUID.fullmatch(client):
        raise ValueError("Invalid Entra tenant or client GUID")
    context = env.get("CONTROL_ENTRA_AUTH_CONTEXT", "")
    if not re.fullmatch(r"c[1-9][0-9]?", context):
        raise ValueError("Invalid Entra authentication context")
    redirect = env.get("CONTROL_ENTRA_REDIRECT_URI", "")
    uri = urlsplit(redirect)
    if (not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]{1,5})?/auth/entra/callback", redirect)
            or not uri.hostname or uri.port == 0):
        raise ValueError("An exact HTTPS Entra callback URI is required")
    secret = env.get("CONTROL_ENTRA_CLIENT_SECRET", "")
    filename = env.get("CONTROL_ENTRA_CLIENT_SECRET_FILE", "")
    if bool(secret) == bool(filename):
        raise ValueError("Configure exactly one Entra client credential")
    if filename:
        secret = Path(filename).read_text("utf-8").strip()
    if not 16 <= len(secret) <= 4096:
        raise ValueError("Invalid Entra client credential")
    return Entra(Config(tenant, client, secret, redirect, context))


class Entra:
    def __init__(self, config):
        self.config = config
        self.sealer = Fernet(Fernet.generate_key())
        self.used = {}
        self.inflight = set()
        self.lock = threading.Lock()
        self.jwks = jwt.PyJWKClient(
            f"{AUTHORITY}/{config.tenant}/discovery/v2.0/keys", timeout=5)

    def begin(self):
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        # No server-side allocation for unauthenticated visits. The PKCE verifier
        # and nonce are sealed for this process and bound to the initiating browser.
        browser = self.sealer.encrypt(json.dumps([state, nonce, verifier]).encode()).decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        claims = {"id_token": {"acrs": {"essential": True, "value": self.config.context}}}
        params = {"client_id": self.config.client, "redirect_uri": self.config.redirect,
                  "response_type": "code", "response_mode": "query", "scope": "openid profile",
                  "state": state, "nonce": nonce, "code_challenge": challenge,
                  "code_challenge_method": "S256", "claims": json.dumps(claims)}
        cookie = f"{FLOW_COOKIE}={browser}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={FLOW_SECONDS}"
        return f"{self.config.endpoint}/authorize?{urlencode(params)}", cookie

    def finish(self, query, cookie_header):
        try:
            data = parse_qs(query, max_num_fields=12)
            cookie = SimpleCookie()
            cookie.load(cookie_header)
            state, = data.get("state", [])
            browser = cookie[FLOW_COOKIE].value
            if not state.isascii() or len(browser) > 1024:
                raise Denied("invalid_flow")
            sealed_state, nonce, verifier = json.loads(
                self.sealer.decrypt(browser.encode("ascii"), ttl=FLOW_SECONDS))
            if not hmac.compare_digest(state, sealed_state):
                raise Denied("invalid_flow")
        except (KeyError, ValueError, CookieError, InvalidToken):
            raise Denied("invalid_flow") from None
        codes = data.get("code", [])
        if "error" in data or len(codes) != 1 or not 1 <= len(codes[0]) <= 16384:
            raise Denied("authorization_declined")
        now = time.monotonic()
        with self.lock:
            self.used = {k: expiry for k, expiry in self.used.items() if expiry > now}
            if state in self.used or state in self.inflight:
                raise Denied("replayed_flow")
            if len(self.inflight) >= 16 or len(self.used) >= 4096:
                raise Unavailable("flow_capacity")
            self.inflight.add(state)
        try:
            result = self.verify(self.exchange(codes[0], verifier), nonce)
            with self.lock:
                self.used[state] = time.monotonic() + FLOW_SECONDS
            return result
        finally:
            with self.lock:
                self.inflight.discard(state)

    def exchange(self, code, verifier):
        form = urlencode({"grant_type": "authorization_code", "code": code,
                          "client_id": self.config.client, "client_secret": self.config.secret,
                          "redirect_uri": self.config.redirect, "code_verifier": verifier}).encode()
        request = Request(f"{self.config.endpoint}/token", data=form,
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with build_opener(NoRedirect).open(request, timeout=6) as response:
                raw = response.read(131073)
                if len(raw) > 131072:
                    raise Denied("invalid_token_response")
                token = json.loads(raw)["id_token"]
        except HTTPError as exc:
            exc.close()
            raise Denied("code_exchange_rejected") from None
        except (URLError, TimeoutError, OSError):
            raise Unavailable("identity_provider_unavailable") from None
        except (ValueError, TypeError, KeyError):
            raise Denied("invalid_token_response") from None
        return token

    def verify(self, token, nonce):
        if not isinstance(token, str) or len(token) > 65536:
            raise Denied("invalid_id_token")
        try:
            header = jwt.get_unverified_header(token)
            if (header.get("alg") != "RS256" or not isinstance(header.get("kid"), str)
                    or not 1 <= len(header["kid"]) <= 256):
                raise Denied("invalid_token_header")
            key = self.jwks.get_signing_key(header["kid"])
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=self.config.client,
                                issuer=self.config.issuer, options={"strict_aud": True, "require": [
                                    "exp", "iat", "nbf", "iss", "aud", "sub", "nonce", "tid", "oid", "ver"]})
        except jwt.exceptions.PyJWKClientConnectionError:
            raise Unavailable("signing_keys_unavailable") from None
        except (jwt.PyJWTError, TypeError, OverflowError):
            raise Denied("invalid_id_token") from None
        if (claims["ver"] != "2.0" or claims["tid"] != self.config.tenant
                or not isinstance(claims["oid"], str) or not GUID.fullmatch(claims["oid"])
                or type(claims["exp"]) is not int or not claims["sub"]
                or not isinstance(claims["nonce"], str) or not claims["nonce"].isascii()
                or not hmac.compare_digest(claims["nonce"], nonce)
                or ("azp" in claims and claims["azp"] != self.config.client)):
            raise Denied("identity_mismatch")
        acrs, roles = claims.get("acrs"), claims.get("roles")
        if not isinstance(acrs, list) or self.config.context not in acrs:
            raise Denied("required_context_missing")
        if not isinstance(roles, list) or not any(r in roles for r in ROLES):  # [tedarik yaması K-012]
            raise Denied("role_missing")
        name = claims.get("name")
        display = name.strip()[:160] if isinstance(name, str) and name.strip() else claims["oid"]
        return claims["oid"], next(r for r in ROLES if r in roles), claims["exp"], display  # [tedarik yaması K-012]
