"""Bildirimsel kaynak kaydı: KS GRC'deki TABLES sözlüğünün modüler karşılığı.

Her kaynak bir tabloya (tdr_ önekli) ve /api/tdr/<ad> uç noktasına karşılık gelir.
Yeni bir alan eklemek için yalnızca ilgili Resource tanımına satır eklenir; tablo açılışta genişler.
"""
PREFIX = "tdr_"
RESOURCES = {}
AUTO = {"created_at", "updated_at"}


def fk(resource, required=True, cascade=False):
    sql = "INTEGER" + (" NOT NULL" if required else "") + f" REFERENCES {PREFIX}{resource}(id)"
    return sql + (" ON DELETE CASCADE" if cascade else "")


class Resource:
    def __init__(self, name, label, fields, *, module, enums=None, unique=(), search=("code", "name"),
                 write="manage", api=("list", "get", "create", "update"), readonly=(), filters=None,
                 read_roles=None, machine=""):
        self.name, self.label, self.fields, self.module = name, label, fields, module
        self.table = PREFIX + name
        self.enums = enums or {}
        self.unique = unique
        self.search = tuple(f for f in search if f in fields)
        self.write = write              # yazma için gereken en düşük seviye: write | manage | admin
        self.api = api                  # otomatik açılan uç noktalar
        self.readonly = set(readonly) | AUTO   # yalnızca sunucunun yazdığı alanlar
        self.filters = filters or {}    # ek liste filtreleri: ad -> SQL parçası (tek parametre)
        self.read_roles = read_roles    # None: tüm roller okur
        self.machine = machine          # MCP anahtarının erişimi: "", "r" veya "rw"
        self.before_save = None         # kanca: (db, data, mevcut_kayıt, principal)
        self.required = [f for f, d in fields.items()
                         if "NOT NULL" in d and "DEFAULT" not in d and f not in self.readonly]
        RESOURCES[name] = self

    def ddl(self):
        cols = ", ".join(f"{f} {d}" for f, d in self.fields.items())
        uniq = "".join(f", UNIQUE({', '.join(u)})" for u in self.unique)
        return f"CREATE TABLE IF NOT EXISTS {self.table} (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols}{uniq})"
