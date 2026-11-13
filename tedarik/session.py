"""KS GRC kimlik modülleri için ince sarmalayıcı (aktarım kuralı: kopya dosyalar değiştirilmez).

- `vendor/identity.py`: parola özeti (PBKDF2-SHA256, 600.000 tur), oturum, Entra hesabı eşleme.
- `vendor/entra_auth.py`: tek kiracılı Entra, PKCE, kimlik doğrulama bağlamı, uygulama rolleri (K-012 yaması).
Burada yalnızca adlar çevrilir: çerez adları, ortam değişkenleri, rol listesi, sayfalar.
"""
import secrets
import threading
import time

from .auth import ENTRA_ROLES
from .db import utcnow
from .vendor import identity

# Aynı alan adında KS GRC oturumunu ezmemek için tedarik kendi çerez adlarını kullanır.
identity.COOKIE_NAME = "tedarik_session"
identity.ENTERPRISE_COOKIE = "__Host-tdr_session"
FLOW_COOKIE = "__Host-tdr_flow"
CALLBACK = "/auth/entra/callback"

ENV_MAP = {   # TEDARIK_* -> KS GRC entra_auth.configure() adları
    "TEDARIK_ENTRA_TENANT_ID": "CONTROL_ENTRA_TENANT_ID",
    "TEDARIK_ENTRA_CLIENT_ID": "CONTROL_ENTRA_CLIENT_ID",
    "TEDARIK_ENTRA_CLIENT_SECRET": "CONTROL_ENTRA_CLIENT_SECRET",
    "TEDARIK_ENTRA_CLIENT_SECRET_FILE": "CONTROL_ENTRA_CLIENT_SECRET_FILE",
    "TEDARIK_ENTRA_REDIRECT_URI": "CONTROL_ENTRA_REDIRECT_URI",
    "TEDARIK_ENTRA_AUTH_CONTEXT": "CONTROL_ENTRA_AUTH_CONTEXT",
}


def entra_provider(config):
    from .vendor import entra_auth
    entra_auth.ROLES = tuple(ENTRA_ROLES)          # K-012: tedarik rolleri, öncelik sırasıyla
    entra_auth.FLOW_COOKIE = FLOW_COOKIE
    env = {"CONTROL_AUTH_MODE": "entra", "CONTROL_COOKIE_SECURE": "1" if config.cookie_secure else "0"}
    env.update({target: config.env[source] for source, target in ENV_MAP.items() if config.env.get(source)})
    return entra_auth.configure(env)


def read(db, cookie_header, scope):
    return identity.read_session(db, cookie_header, scope=scope)


def cookie(value, config, clear=False):
    return identity.session_cookie(value, secure=config.cookie_secure or config.auth_mode == "entra",
                                   clear=clear, enterprise=config.auth_mode == "entra")


def provision(db, username, display_name=None, reset=False):
    """Geçici parolalı yerel hesap; ilk girişte parola değişimi zorunlu. Parola yalnızca bir kez döner."""
    password = secrets.token_urlsafe(18)
    if not identity.provision(db, username, password, reset=reset):
        return None
    db.execute("UPDATE users SET display_name=?, updated_at=? WHERE username=?",
               (display_name or username, utcnow(), username))
    return password


class LoginLimiter:
    """KS GRC `handle_login` sınırı: (adres, kullanıcı) başına 5 dakikada 8 deneme, en çok 512 anahtar."""

    def __init__(self, attempts=8, window=300, keys=512):
        self.attempts, self.window, self.keys = attempts, window, keys
        self.failures, self.lock = {}, threading.Lock()

    def hit(self, key):
        with self.lock:
            now = time.monotonic()
            if len(self.failures) >= self.keys:
                for stale in [k for k, hits in self.failures.items() if not hits or hits[-1] <= now - self.window]:
                    del self.failures[stale]
            recent = [t for t in self.failures.get(key, []) if t > now - self.window]
            if len(recent) >= self.attempts or (key not in self.failures and len(self.failures) >= self.keys):
                return False
            self.failures[key] = recent + [now]
            return True

    def clear(self, key):
        with self.lock:
            self.failures.pop(key, None)
