"""Kimlik ve yetki: kim (Principal), ne yapabilir (rol seviyesi), hangi birimin kaydına yazabilir (kapsam).

Kimlik kaynakları (öncelik sırasıyla):
1. `X-API-Key`: MCP makine kimliği; rol değildir, yalnızca kaynağın açıkça izin verdiği işlemi yapar.
   `X-Collector-Key`: veri kataloğu toplayıcısı (K-030); tek bir veri kaynağına bağlıdır ve yalnızca /api/tdr/collector/
   uç noktalarını kullanır (http.py), hiçbir kaynağı okuyamaz veya yazamaz.
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
LEVELS = {"MACHINE": 0, "COLLECTOR": 0, "VIEWER": 1, "AUDITOR": 1, "UNIT_USER": 2, "SUPPLIER_MANAGER": 3, "ADMIN": 4}
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
    auth_type: str  # session | api_key | collector | dev
    display_name: str = ""
    user_id: int = None
    units: frozenset = field(default_factory=frozenset)   # Birim Kullanıcısının yazabildiği birimler
    must_change_password: bool = False
    external: bool = False                                # dış denetçi: salt okunur, yalnızca atanmış denetimler (K-026)
    audits: frozenset = field(default_factory=frozenset)
    expires_on: str = None
    collector_id: int = None                              # toplayıcı anahtarı: bağlı olduğu toplayıcı kaydı (K-030)

    def can(self, need):
        return LEVELS[self.role] >= NEEDED[need]

    def public(self):
        return {"username": self.username, "display_name": self.display_name, "role": self.role,
                "role_label": ("Dış denetçi" if self.external else "Toplayıcı" if self.role == "COLLECTOR"
                               else ROLES.get(self.role, "MCP")), "auth_type": self.auth_type,
                "units": sorted(self.units), "must_change_password": self.must_change_password,
                "external": self.external, "audits": sorted(self.audits), "expires_on": self.expires_on}


class Auth:
    def __init__(self, config, database):
        self.config, self.database = config, database
        self.entra = None
        if config.dev_role not in ROLES:
            raise ValueError("Geçersiz TEDARIK_DEV_ROLE")
        if config.auth_mode == "entra" and config.env.get("TEDARIK_ENTRA_TENANT_ID"):
            from . import session
            self.entra = session.entra_provider(config)     # yoksa ayarlar açılışta veritabanından okunur (K-024)

    @property
    def session_scope(self):
        return self.entra.config.session_scope if self.entra else "local"

    def resolve(self, headers):
        key = headers.get("X-API-Key", "")
        if key:
            if self.config.api_key and hmac.compare_digest(key.encode(), self.config.api_key.encode()):
                return Principal("mcp", "MACHINE", "api_key", "MCP")
            raise Unauthenticated()
        collector = headers.get("X-Collector-Key", "")
        bearer = headers.get("Authorization", "")
        if not collector and bearer.startswith("Bearer tdrc_"):     # OpenLineage HTTP aktarımı (api_key)
            collector = bearer[7:].strip()
        if collector:
            return self._collector(collector)
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
            access = access_of(db, user["id"])
            if access["expired"]:
                raise Unauthenticated()
            audits = frozenset(r["audit_id"] for r in db.execute(
                "SELECT audit_id FROM tdr_user_audits WHERE user_id=?", (user["id"],)).fetchall()) \
                if access["external"] else frozenset()
        return Principal(user["username"], role, "session", user["display_name"] or user["username"],
                         user_id=user["id"], units=units, must_change_password=bool(user["must_change_password"]),
                         external=access["external"], audits=audits, expires_on=access["expires_on"])


    def _collector(self, key):
        if "datagov" not in self.config.modules:
            raise Unauthenticated()
        from .modules.collection import resolve_key
        with self.database.connect() as db:
            row = resolve_key(db, key)
        if not row:
            raise Unauthenticated()
        return Principal(f"toplayici:{row['code']}", "COLLECTOR", "collector", row["name"], collector_id=row["id"])


def access_of(db, user_id):
    """Hesabın süresi ve dış denetçi durumu. Süresi geçmiş hesap oturum açamaz, açık oturumu geçersiz olur."""
    from datetime import date
    row = db.execute("SELECT expires_on, external FROM tdr_user_access WHERE user_id=?", (user_id,)).fetchone()
    expires = str(row["expires_on"])[:10] if row and row["expires_on"] else None
    return {"expires_on": expires, "external": bool(row and row["external"]),
            "expired": bool(expires and expires < date.today().isoformat())}


def audit_allowed(principal, audit_id):
    """Dış denetçi yalnızca kendisine atanmış denetimleri görür."""
    if principal is None or not principal.external:
        return True
    return int(audit_id) in principal.audits


def require_audit(principal, audit_id):
    if not audit_allowed(principal, audit_id):
        from .crud import NotFound
        raise NotFound("Denetim bulunamadı")


def check(principal, res, action):
    """action: read | write. MCP anahtarı yalnızca kaynağın açıkça izin verdiği işlemi yapar; toplayıcı hiçbirini."""
    if principal.role == "COLLECTOR":
        raise Forbidden("Toplayıcı anahtarı yalnızca katalog gönderebilir")
    if principal.role == "MACHINE":
        if ("r" if action == "read" else "w") not in res.machine:
            raise Forbidden("MCP anahtarı bu işleme yetkili değil")
        return
    if action == "read":
        if res.read_roles and principal.role not in res.read_roles:
            raise Forbidden("Bu kaydı görüntüleme yetkiniz yok")
        return
    if not can_write(principal, res):
        raise Forbidden("Bu işlem için yetkiniz yok")


def can_write(principal, res):
    """Rol listesi tanımlı kaynakta (ör. denetim kayıtları: Yönetici ve Denetçi) seviye yerine liste geçerlidir."""
    if principal.role in ("MACHINE", "COLLECTOR"):
        return False
    if res.write_roles is not None:
        return principal.role in res.write_roles
    return principal.can(res.write)


def require(principal, need):
    if not principal.can(need):
        raise Forbidden("Bu işlem için yetkiniz yok")


def require_human(principal):
    if principal.auth_type in ("api_key", "collector"):
        raise Forbidden("Bu işlem yalnızca kullanıcı oturumuyla yapılabilir")
