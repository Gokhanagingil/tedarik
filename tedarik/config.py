"""Ortam yapılandırması. KS GRC'deki CONTROL_* değişkenlerinin TEDARIK_* karşılıkları."""
import os
from pathlib import Path

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
KNOWN_MODULES = ("core", "performance", "surveys", "risks", "transfer", "dashboard", "workflow", "sourcing")
DEFAULT_MODULES = "core,performance,surveys,risks,transfer,dashboard"
AUTH_MODES = {"dev", "local", "entra"}


class Config:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.db = env.get("TEDARIK_DB", "tedarik.db")                 # SQLite dosyası (geliştirme, test)
        self.database_url = self._database_url(env)                    # PostgreSQL (üretim) — K-011
        self.db_schema = env.get("TEDARIK_DB_SCHEMA", "")
        self.db_pool_size = int(env.get("TEDARIK_DB_POOL_SIZE", "10"))
        self.host = env.get("TEDARIK_HOST", "127.0.0.1")
        self.port = int(env.get("PORT", "8090"))
        self.auth_mode = env.get("TEDARIK_AUTH_MODE", "")
        self.dev_user = env.get("TEDARIK_DEV_USER", "dev")
        self.dev_role = env.get("TEDARIK_DEV_ROLE", "ADMIN")
        self.cookie_secure = env.get("TEDARIK_COOKIE_SECURE", "0") == "1"
        names = [m.strip() for m in env.get("TEDARIK_MODULES", DEFAULT_MODULES).split(",") if m.strip()]
        self.modules = ["core"] + [m for m in names if m != "core"]
        self.api_key = self._secret(env)
        self._validate()

    @staticmethod
    def _database_url(env):
        """Bağlantı adresi parola içerebilir: üretimde dosyadan okunur (TEDARIK_DATABASE_URL_FILE)."""
        url, url_file = env.get("TEDARIK_DATABASE_URL", ""), env.get("TEDARIK_DATABASE_URL_FILE")
        if url_file:
            if url:
                raise ValueError("Tek bir veritabanı adresi kaynağı yapılandırın")
            url = Path(url_file).read_text(encoding="utf-8").strip()
        if url and not url.startswith(("postgresql://", "postgres://")):
            raise ValueError("TEDARIK_DATABASE_URL postgresql:// ile başlamalı")
        return url

    @staticmethod
    def _secret(env):
        key, secret_file = env.get("TEDARIK_API_KEY", ""), env.get("TEDARIK_API_KEY_FILE")
        if secret_file:
            if key:
                raise ValueError("Tek bir MCP anahtar kaynağı yapılandırın")
            key = Path(secret_file).read_text(encoding="utf-8").strip()
        if key and len(key) < 32:
            raise ValueError("MCP anahtarı en az 32 karakter olmalı")
        return key

    def _validate(self):
        if self.auth_mode not in AUTH_MODES:
            raise ValueError("TEDARIK_AUTH_MODE gerekli (dev | local | entra); anonim erişim açılmaz")
        if self.auth_mode == "dev" and self.host not in LOOPBACK:
            raise ValueError("dev kimlik modu yalnızca yerel adreste (127.0.0.1) çalışır")
        if not 1 <= self.db_pool_size <= 100:
            raise ValueError("TEDARIK_DB_POOL_SIZE 1-100 arasında olmalı")
        unknown = set(self.modules) - set(KNOWN_MODULES)
        if unknown:
            raise ValueError("Bilinmeyen modül: " + ", ".join(sorted(unknown)))
