"""HTTP katmanı: yönlendirici, güvenlik başlıkları, tekrar koruması. Web çatısı kullanılmaz (KS GRC ile aynı).

App.dispatch saf bir işlevdir (yöntem, yol, başlıklar, gövde -> durum, yanıt); testler soket açmadan çalışır.
"""
import base64
import hashlib
import json
import logging
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlparse

from . import accounts, audit, auth as authz, crud, migrate  # noqa: F401 (accounts: kaynak kaydı)
from .db import Database, IntegrityError, one, utcnow
from .schema import RESOURCES, Resource

API = "/api/tdr"   # KS GRC ile birleşmede uç nokta çakışmasını önleyen ad alanı
MAX_BODY = 2 * 1024 * 1024
IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_.:-]{8,160}")   # KS GRC execution_service.record ile aynı
LOG = logging.getLogger("tedarik")

Resource("idempotency", "Tekrar Koruması", {
    "idem_key": "TEXT NOT NULL UNIQUE", "route": "TEXT NOT NULL", "body_hash": "TEXT NOT NULL",
    "response_json": "TEXT NOT NULL", "created_at": "TIMESTAMP NOT NULL",
}, module="core", api=(), search=(), immutable=True)

# Parola değişimi beklenirken yalnızca bu yollar açıktır (KS GRC `authorized`).
PASSWORD_CHANGE_ROUTES = {"/api/me", "/api/change-password", "/api/logout", "/change-password"}


class Raw:
    """JSON dışı yanıt (ör. CSV dışa aktarımı, HTML sayfa)."""

    def __init__(self, content, content_type, filename=None):
        self.content, self.content_type, self.filename = content, content_type, filename


class Reply:
    """Ek başlıklı yanıt (Set-Cookie, Location). `payload` bir sözlük veya Raw olabilir."""

    def __init__(self, payload, headers=None):
        self.payload, self.headers = payload, dict(headers or {})


def redirect(location, cookie=None):
    headers = {"Location": location}
    if cookie:
        headers["Set-Cookie"] = cookie
    return 303, Reply(Raw("", "text/plain; charset=utf-8"), headers)


class Ctx:
    def __init__(self, app, db, principal, params, query, body, headers=None, client="", raw_query=""):
        self.app, self.db, self.principal = app, db, principal
        self.params, self.query, self.body = params, query, body or {}
        self.headers, self.client, self.raw_query = headers if headers is not None else {}, client, raw_query


class App:
    def __init__(self, config):
        self.config = config
        self.database = Database(config)
        self.auth = authz.Auth(config, self.database)
        self.routes = []
        self.public = []      # kimlik gerektirmeyen yollar: giriş sayfası, parola girişi, Entra dönüşü

    def close(self):
        self.database.close()

    def enabled(self, module):
        return module in self.config.modules

    def route(self, method, pattern, fn, public=False):
        """pattern örneği: /api/tdr/suppliers/{id}/context (süslü parantezli parçalar tamsayıdır)."""
        regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>\\d+)", pattern) + "$")
        (self.public if public else self.routes).append((method, regex, fn))

    @staticmethod
    def _find(routes, method, path):
        for verb, regex, candidate in routes:
            match = regex.match(path) if verb == method else None
            if match:
                return candidate, match
        return None, None

    def dispatch(self, method, target, headers=None, raw=b"", client=""):
        headers = headers if headers is not None else {}
        url = urlparse(target)
        fn, match = self._find(self.public, method, url.path)
        if fn:
            return self._execute(fn, match, method, url, headers, raw, None, client)
        try:
            principal = self.auth.resolve(headers)
        except authz.Unauthenticated:
            if url.path.startswith("/api/"):
                return 401, {"error": "Oturum açılması gerekiyor"}
            return redirect("/login")
        if principal.must_change_password and url.path not in PASSWORD_CHANGE_ROUTES:
            if url.path.startswith("/api/"):
                return 403, {"error": "Parolanızı değiştirmeniz gerekiyor"}
            return redirect("/change-password")
        if url.path == "/api/health":      # KS GRC gibi kimlik ister; anonim istek 401 alır
            return 200, {"status": "ok"}
        fn, match = self._find(self.routes, method, url.path)
        if not fn:
            return 404, {"error": "Bulunamadı"}
        return self._execute(fn, match, method, url, headers, raw, principal, client)

    def _execute(self, fn, match, method, url, headers, raw, principal, client):
        if len(raw) > MAX_BODY:
            return 413, {"error": "Gövde 2 MB sınırını aşıyor"}
        try:
            body, idem = self._body(method, raw)
            if principal and method != "GET" and not self.same_origin(principal, headers):
                return 403, {"error": "Güvenlik doğrulaması başarısız"}
            with self.database.connect() as db:
                if idem:
                    # KS GRC gibi: alındıyı okumadan önce yazıcıları sırala; eşzamanlı tekrar ikinci kayıt üretmez.
                    db.lock("idempotency:" + idem[0])
                    seen = one(db, "SELECT * FROM tdr_idempotency WHERE idem_key=?", (idem[0],))
                    if seen:
                        if seen["route"] != url.path or seen["body_hash"] != idem[1]:
                            raise crud.Conflict("Bu işlem anahtarı farklı bir istek için zaten kullanılmış")
                        return 200, {**json.loads(seen["response_json"]), "replayed": True}
                params = {k: int(v) for k, v in match.groupdict().items()}
                result = fn(Ctx(self, db, principal, params, dict(parse_qsl(url.query)), body,
                                headers, client, url.query))
                status, payload = result if isinstance(result, tuple) else (200, result)
                if idem and isinstance(payload, dict):
                    db.execute("INSERT INTO tdr_idempotency (idem_key, route, body_hash, response_json, created_at) "
                               "VALUES (?,?,?,?,?)",
                               (idem[0], url.path, idem[1], json.dumps(payload, ensure_ascii=False), utcnow()))
                return status, payload
        except crud.NotFound as exc:
            return 404, {"error": str(exc) or "Kayıt bulunamadı"}
        except crud.Forbidden as exc:
            return 403, {"error": str(exc)}
        except crud.Conflict as exc:
            return 409, {"error": str(exc)}
        except IntegrityError:
            return 409, {"error": "Kayıt çakışması veya geçersiz ilişki"}
        except KeyError as exc:
            return 400, {"error": f"Eksik veya geçersiz alan: {exc.args[0]}"}
        except (ValueError, TypeError) as exc:
            return 400, {"error": str(exc)[:350]}
        except Exception:   # noqa: BLE001 — SQL, dosya yolu veya gizli bilgi sızdırılmaz (KS GRC _error)
            LOG.exception("Beklenmeyen hata: %s %s", method, url.path)
            return 500, {"error": "Beklenmeyen işlem hatası"}

    @staticmethod
    def _body(method, raw):
        if method == "GET":
            return None, None
        if not raw:
            raise crud.Invalid("JSON gövdesi gerekli")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise crud.Invalid("JSON nesnesi gerekli")
        idem = None
        if method == "POST" and "idempotency_key" in body:
            key = body.pop("idempotency_key")
            if not isinstance(key, str) or not IDEMPOTENCY_KEY.fullmatch(key):
                raise crud.Invalid("idempotency_key 8–160 güvenli karakter olmalı")
            canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            idem = (key, hashlib.sha256(canonical.encode()).hexdigest())
        return body, idem

    def expected_origin(self, headers):
        """Entra'da köken yapılandırılmış dönüş adresinden gelir; yerel modda istekteki Host'tan (KS GRC)."""
        if self.auth.entra:
            return self.auth.entra.config.origin
        scheme = "https" if self.config.cookie_secure else "http"
        return f"{scheme}://{headers.get('Host')}"

    def same_origin(self, principal, headers):
        """Tarayıcı oturumuyla yapılan değişiklikler yalnızca aynı kökenden kabul edilir."""
        if principal.auth_type == "api_key":
            return True
        getter = getattr(headers, "get_all", None)
        if getter and len(getter("Origin", [])) > 1:      # KS GRC: tek Origin başlığı
            return False
        origin = headers.get("Origin")
        if origin is None:
            return principal.auth_type == "dev"   # yerel geliştirmede curl ve testler
        if self.auth.entra and (headers.get("Host") or "").lower() != urlparse(
                self.auth.entra.config.redirect).netloc.lower():
            return False
        return origin == self.expected_origin(headers)


def guard_readonly(res, body):
    blocked = set(body) & res.readonly
    if blocked:
        raise crud.Invalid("Bu alanlar sunucu tarafından yazılır: " + ", ".join(sorted(blocked)))


def resource_routes(app, res):
    base = f"{API}/{res.name}"

    def listing(c):
        authz.check(c.principal, res, "read")
        return crud.listing(c.db, res, c.query)

    def get(c):
        authz.check(c.principal, res, "read")
        return crud.get(c.db, res, c.params["id"])

    def create(c):
        authz.check(c.principal, res, "write")
        guard_readonly(res, c.body)
        record_id = crud.insert(c.db, res, c.body, c.principal)
        audit.log(c.db, c.principal, "CREATE", res.name, record_id, c.body)
        return 201, {"id": record_id}

    def update(c):
        authz.check(c.principal, res, "write")
        guard_readonly(res, c.body)
        record = crud.update(c.db, res, c.params["id"], c.body, c.principal)
        audit.log(c.db, c.principal, "UPDATE", res.name, c.params["id"], c.body)
        return record

    for action, method, pattern, fn in (("list", "GET", base, listing), ("get", "GET", base + "/{id}", get),
                                        ("create", "POST", base, create), ("update", "PATCH", base + "/{id}", update)):
        if action in res.api:
            app.route(method, pattern, fn)


def build(config):
    """Uygulamayı kurar: modülleri yükler, tabloları açar, uç noktaları kaydeder, başlangıç verisini ekler."""
    from . import modules
    app = App(config)
    loaded = modules.load(config)
    migrate.sync(app.database, config.modules)
    for res in RESOURCES.values():
        if res.module in config.modules:
            resource_routes(app, res)
    for mod in loaded:
        if hasattr(mod, "register"):
            mod.register(app)
    from . import login
    login.register(app)
    with app.database.connect() as db:
        for mod in loaded:
            if hasattr(mod, "seed"):
                mod.seed(db)
    return app


def handler_class(app):
    class Handler(BaseHTTPRequestHandler):
        def version_string(self):
            return "Tedarik"

        def log_request(self, code="-", size="-"):
            self.log_message("%s %s %s", self.command, self.path.partition("?")[0], code)   # sorgu dizgisi yazılmaz

        def _run(self):
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "Geçersiz Content-Length"})
            if length > MAX_BODY:
                return self._send(413, {"error": "Gövde 2 MB sınırını aşıyor"})
            raw = self.rfile.read(length) if length > 0 else b""
            self._send(*app.dispatch(self.command, self.path, self.headers, raw, self.client_address[0]))

        do_GET = do_POST = do_PATCH = _run

        def _send(self, status, payload):
            extra = {}
            if isinstance(payload, Reply):
                payload, extra = payload.payload, payload.headers
            content_type = "application/json; charset=utf-8"
            if isinstance(payload, Raw):
                content_type, text = payload.content_type, payload.content
            else:
                text = json.dumps(payload, ensure_ascii=False)
            raw = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if app.config.cookie_secure:
                self.send_header("Strict-Transport-Security", "max-age=31536000")
            if isinstance(payload, Raw) and payload.filename:
                self.send_header("Content-Disposition", f'attachment; filename="{payload.filename}"')
            if content_type.startswith("text/html"):
                def hashes(tag):
                    blocks = re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL | re.IGNORECASE)
                    return " ".join("'sha256-" + base64.b64encode(hashlib.sha256(b.encode()).digest()).decode() + "'"
                                    for b in blocks)
                self.send_header("Content-Security-Policy", (
                    "default-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; "
                    "connect-src 'self'; img-src 'self' data:; style-src 'self' " + hashes("style") + "; "
                    "style-src-attr 'none'; script-src 'self' " + hashes("script") + "; object-src 'none'"))
            for name, value in extra.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(raw)

    return Handler
