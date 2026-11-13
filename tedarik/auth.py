"""Kimlik ve yetki. Oturum sağlayıcıları (yerel parola, Entra) KS GRC'den aktarılacaktır.

Bu dosya yalnızca dikişi tanımlar: Principal, rol seviyeleri ve en az yetkili MCP anahtarı.
"""
import hmac
from dataclasses import dataclass

from .crud import Forbidden

ROLES = {
    "ADMIN": "Yönetici",
    "SUPPLIER_MANAGER": "Tedarikçi Yöneticisi",
    "UNIT_USER": "Birim Kullanıcısı",
    "AUDITOR": "Denetçi",
    "VIEWER": "Görüntüleyici",
}
LEVELS = {"MACHINE": 0, "VIEWER": 1, "AUDITOR": 1, "UNIT_USER": 2, "SUPPLIER_MANAGER": 3, "ADMIN": 4}
NEEDED = {"read": 1, "write": 2, "manage": 3, "admin": 4}


class Unauthenticated(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    auth_type: str  # session | api_key | dev
    display_name: str = ""

    def can(self, need):
        return LEVELS[self.role] >= NEEDED[need]


class Auth:
    def __init__(self, config):
        self.config = config
        if config.auth_mode in ("local", "entra"):
            raise RuntimeError(
                "Oturum sağlayıcısı henüz aktarılmadı: KS GRC identity.py ve entra_auth.py modülleri "
                "tedarik/vendor altına alınmalı (bkz. DURUM.md, adım 1). Şimdilik TEDARIK_AUTH_MODE=dev.")
        if config.dev_role not in ROLES:
            raise ValueError("Geçersiz TEDARIK_DEV_ROLE")

    def resolve(self, headers):
        key = headers.get("X-API-Key", "")
        if key:
            if self.config.api_key and hmac.compare_digest(key.encode(), self.config.api_key.encode()):
                return Principal("mcp", "MACHINE", "api_key", "MCP")
            raise Unauthenticated()
        if self.config.auth_mode == "dev":
            return Principal(self.config.dev_user, self.config.dev_role, "dev", "Geliştirici")
        raise Unauthenticated()


def check(principal, res, action):
    """action: read | write. MCP anahtarı yalnızca kaynağın açıkça izin verdiği işlemi yapar."""
    if principal.role == "MACHINE":
        if ("r" if action == "read" else "w") not in res.machine:
            raise Forbidden("MCP anahtarı bu işleme yetkili değil")
        return
    if action == "read":
        if res.read_roles and principal.role not in res.read_roles:
            raise Forbidden("Bu kaydı görüntüleme yetkiniz yok")
        return
    if not principal.can(res.write):
        raise Forbidden("Bu işlem için yetkiniz yok")


def require(principal, need):
    if not principal.can(need):
        raise Forbidden("Bu işlem için yetkiniz yok")
