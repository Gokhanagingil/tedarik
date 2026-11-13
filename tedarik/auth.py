"""Kimlik ve yetki: kim (Principal), ne yapabilir (rol seviyesi), hangi birimin kaydına yazabilir (kapsam).

Kimlik kaynakları (öncelik sırasıyla):
1. `X-API-Key`: MCP makine kimliği; rol değildir, yalnızca kaynağın açıkça izin verdiği işlemi yapar.
2. `dev` modu: yalnızca yerel adreste, ortam değişkenindeki kullanıcı ve rol.
3. Oturum çerezi (`local` ve `entra` modları): KS GRC `identity.py` oturumu (session.py).
   `local` modunda rol `tdr_user_roles`, `entra` modunda Entra uygulama rolü (KS.TDR.*) belirler.
   Birim kapsamı iki modda da `tdr_user_units` tablosundadır.
"""
import hmac
from dataclasses import dataclass, field

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
# Entra uygulama rolü -> tedarik rolü; sıra önceliktir (birden çok rol atanmışsa en yetkili seçilir). K-012.
ENTRA_ROLES = {
    "KS.TDR.Admin": "ADMIN",
    "KS.TDR.SupplierManager": "SUPPLIER_MANAGER",
    "KS.TDR.UnitUser": "UNIT_USER",
    "KS.TDR.Auditor": "AUDITOR",
    "KS.TDR.Viewer": "VIEWER",
}


class Unauthenticated(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    username: str
    role: str
    auth_type: str  # session | api_key | dev
    display_name: str = ""
    user_id: int = None
    units: frozenset = field(default_factory=frozenset)   # Birim Kullanıcısının yazabildiği birimler
    must_change_password: bool = False

    def can(self, need):
        return LEVELS[self.role] >= NEEDED[need]

    def public(self):
        return {"username": self.username, "display_name": self.display_name, "role": self.role,
                "role_label": ROLES.get(self.role, "MCP"), "auth_type": self.auth_type,
                "units": sorted(self.units), "must_change_password": self.must_change_password}


class Auth:
    def __init__(self, config, database):
        self.config, self.database = config, database
        self.entra = None
        if config.dev_role not in ROLES:
            raise ValueError("Geçersiz TEDARIK_DEV_ROLE")
        if config.auth_mode == "entra":
            from . import session
            self.entra = session.entra_provider(config)

    @property
    def session_scope(self):
        return self.entra.config.session_scope if self.entra else "local"

    def resolve(self, headers):
        key = headers.get("X-API-Key", "")
        if key:
            if self.config.api_key and hmac.compare_digest(key.encode(), self.config.api_key.encode()):
                return Principal("mcp", "MACHINE", "api_key", "MCP")
            raise Unauthenticated()
        if self.config.auth_mode == "dev":
            return Principal(self.config.dev_user, self.config.dev_role, "dev", "Geliştirici",
                             units=frozenset(self.config.dev_units))
        from . import session
        with self.database.connect() as db:
            user = session.read(db, headers.get("Cookie", ""), self.session_scope)
            if not user:
                raise Unauthenticated()
            if self.entra:
                role = ENTRA_ROLES.get(user["app_role"])
            else:
                row = db.execute("SELECT role FROM tdr_user_roles WHERE user_id=?", (user["id"],)).fetchone()
                role = row["role"] if row else None
            if role not in ROLES:
                raise Unauthenticated()
            units = frozenset(r["org_unit_id"] for r in db.execute(
                "SELECT org_unit_id FROM tdr_user_units WHERE user_id=?", (user["id"],)).fetchall())
        return Principal(user["username"], role, "session", user["display_name"] or user["username"],
                         user_id=user["id"], units=units, must_change_password=bool(user["must_change_password"]))


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


def require_human(principal):
    if principal.auth_type == "api_key":
        raise Forbidden("Bu işlem yalnızca kullanıcı oturumuyla yapılabilir")
