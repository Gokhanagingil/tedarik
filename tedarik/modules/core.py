"""Çekirdek: birimler, tedarikçi tipleri, ürün/hizmet kataloğu, tedarikçiler, angajmanlar, sahiplikler.

Temel ayrım: Tedarikçi tekil tüzel kişidir (VKN ile). "Hangi birim, hangi ürün/hizmeti, kimin için,
kimin sahipliğinde alıyor" bilgisi Angajman kaydında durur. Performans, anket ve risk angajmana bağlanır.
"""
import json

from .. import audit, auth as authz, crud
from ..db import one, rows
from ..http import API
from ..schema import RESOURCES, Resource, fk

M = "core"
ACTIVE = "INTEGER NOT NULL DEFAULT 1"

POLICIES = Resource("policies", "Politika Parametreleri", {
    "code": "TEXT NOT NULL UNIQUE", "value_json": "TEXT NOT NULL", "description": "TEXT"},
    module=M, write="admin", search=("code", "description"))


def policy(db, code, default=None):
    """Süreç kuralı parametresi (ör. gözden geçirme sıklığı). Kod değişmeden yönetici değiştirir."""
    row = one(db, "SELECT value_json FROM tdr_policies WHERE code=?", (code,))
    return json.loads(row["value_json"]) if row else default


def _policy_rules(db, data, current, principal):
    if "value_json" in data:
        try:
            json.loads(data["value_json"])
        except (TypeError, ValueError):
            raise crud.Invalid("Değer geçerli JSON olmalı (ör. 3 veya {\"critical\": 6})") from None


POLICIES.before_save = _policy_rules

Resource("org_units", "Birimler", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "parent_id": fk("org_units", False),
    "manager": "TEXT", "active": ACTIVE}, module=M, write="admin", machine="r")

Resource("supplier_types", "Tedarikçi Tipleri", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "description": "TEXT", "active": ACTIVE},
    module=M, write="admin", machine="r")

Resource("catalog_items", "Ürün ve Hizmetler", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "kind": "TEXT NOT NULL DEFAULT 'service'",
    "category": "TEXT", "description": "TEXT", "active": ACTIVE},
    module=M, enums={"kind": ("product", "service")}, machine="r")

SUPPLIERS = Resource("suppliers", "Tedarikçiler", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "tax_id": "TEXT UNIQUE", "country": "TEXT",
    "city": "TEXT", "website": "TEXT", "status": "TEXT NOT NULL DEFAULT 'active'",
    "tier": "TEXT NOT NULL DEFAULT 'standard'", "segment": "TEXT", "owner": "TEXT", "description": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, search=("code", "name", "tax_id"), machine="r",
    enums={"status": ("prospect", "active", "suspended", "offboarding", "terminated"),
           "tier": ("critical", "important", "standard"),
           "segment": ("strategic", "leverage", "bottleneck", "routine")},
    filters={"type_id": "id IN (SELECT supplier_id FROM tdr_supplier_type_map WHERE type_id=?)"})

Resource("supplier_type_map", "Tedarikçi-Tip Eşlemesi", {
    "supplier_id": fk("suppliers", cascade=True), "type_id": fk("supplier_types", cascade=True)},
    module=M, unique=(("supplier_id", "type_id"),), api=(), search=())

Resource("supplier_contacts", "Tedarikçi İlgili Kişileri", {
    "supplier_id": fk("suppliers"), "name": "TEXT NOT NULL", "role": "TEXT", "email": "TEXT", "phone": "TEXT",
    "is_primary": "INTEGER NOT NULL DEFAULT 0"}, module=M, search=("name", "email"))

Resource("source_refs", "Kaynak Sistem Eşlemeleri", {
    "supplier_id": fk("suppliers"), "source_system": "TEXT NOT NULL", "external_id": "TEXT NOT NULL",
    "external_name": "TEXT", "last_seen_at": "TIMESTAMP"},
    module=M, unique=(("source_system", "external_id"),), search=("external_id", "external_name"), machine="r",
    enums={"source_system": ("sap", "crm", "outsourcing", "servicenow", "manual")})

ENGAGEMENTS = Resource("engagements", "Angajmanlar", {
    "code": "TEXT NOT NULL UNIQUE", "supplier_id": fk("suppliers"), "catalog_item_id": fk("catalog_items"),
    "org_unit_id": fk("org_units"), "beneficiary": "TEXT NOT NULL DEFAULT 'internal'", "customer_name": "TEXT",
    "business_owner": "TEXT", "criticality": "TEXT NOT NULL DEFAULT 'medium'",
    "status": "TEXT NOT NULL DEFAULT 'active'", "start_date": "DATE", "end_date": "DATE", "description": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="write", search=("code", "description", "customer_name"), machine="r",
    enums={"beneficiary": ("internal", "customer"), "criticality": ("critical", "high", "medium", "low"),
           "status": ("planned", "active", "ending", "ended")})

Resource("engagement_users", "Angajmanı Kullanan Birimler", {
    "engagement_id": fk("engagements", cascade=True), "org_unit_id": fk("org_units", cascade=True)},
    module=M, unique=(("engagement_id", "org_unit_id"),), api=(), search=())

Resource("responsibilities", "Sorumluluklar", {
    "supplier_id": fk("suppliers", False), "engagement_id": fk("engagements", False), "role": "TEXT NOT NULL",
    "raci": "TEXT NOT NULL DEFAULT 'R'", "person": "TEXT NOT NULL", "org_unit_id": fk("org_units", False)},
    module=M, write="write", search=("person",),
    enums={"role": ("relationship_owner", "contract_owner", "service_owner", "technical_owner", "security",
                    "finance", "legal", "other"), "raci": ("R", "A", "C", "I")})

Resource("contracts", "Sözleşme Referansları", {
    "code": "TEXT NOT NULL UNIQUE", "supplier_id": fk("suppliers"), "engagement_id": fk("engagements", False),
    "title": "TEXT NOT NULL", "source_system": "TEXT", "external_id": "TEXT", "start_date": "DATE",
    "end_date": "DATE", "notice_days": "INTEGER", "status": "TEXT NOT NULL DEFAULT 'active'"},
    module=M, search=("code", "title"), machine="r",
    enums={"status": ("draft", "active", "expiring", "expired", "terminated")})


def _engagement_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if merged.get("beneficiary") == "customer" and not merged.get("customer_name"):
        raise crud.Invalid("Müşteriye sunulan hizmette customer_name zorunludur")


def _responsibility_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if (merged.get("supplier_id") is None) == (merged.get("engagement_id") is None):
        raise crud.Invalid("Sorumluluk ya tedarikçiye ya da angajmana bağlanır (yalnızca biri)")


ENGAGEMENTS.before_save = _engagement_rules


# ---- birim kapsamı: Birim Kullanıcısı yalnızca kendi biriminin angajmanına ve ona bağlı kayıtlara yazar.
# Angajmanın sahibi satın alan birimdir (org_unit_id). Angajmana bağlı olmayan tedarikçi düzeyindeki kayıt
# (olay, risk, değerlendirme), kullanıcının biriminin o tedarikçiyle angajmanı varsa yazılabilir.

def engagement_units(db, engagement_id):
    row = one(db, "SELECT org_unit_id FROM tdr_engagements WHERE id=?", (engagement_id,))
    return {row["org_unit_id"]} if row else set()


def supplier_units(db, supplier_id):
    return {r["org_unit_id"] for r in rows(db, "SELECT DISTINCT org_unit_id FROM tdr_engagements "
                                               "WHERE supplier_id=?", (supplier_id,))}


def engagement_or_supplier(db, record):
    if record.get("engagement_id"):
        return engagement_units(db, record["engagement_id"])
    return supplier_units(db, record.get("supplier_id"))


def via(resource_name, key):
    """Üst kayıt üzerinden kapsam: ör. SLA ölçümü -> SLA tanımı -> angajman."""
    def scope(db, record):
        parent = RESOURCES[resource_name]
        row = one(db, f"SELECT * FROM {parent.table} WHERE id=?", (record.get(key),))
        return parent.scope(db, row) if row else set()
    return scope


ENGAGEMENTS.scope = lambda db, record: {record.get("org_unit_id")}
RESOURCES["responsibilities"].before_save = _responsibility_rules
RESOURCES["responsibilities"].scope = engagement_or_supplier


def _ids(body, key):
    ids = body[key]
    if not isinstance(ids, list) or any(type(i) is not int for i in ids):
        raise crud.Invalid(f"{key} tamsayı listesi olmalı")
    return ids


def supplier_context(c):
    """Tedarikçi 360: tek istekte tipler, angajmanlar, kişiler, kaynak sistem kimlikleri, sorumluluklar."""
    authz.check(c.principal, SUPPLIERS, "read")
    sid = c.params["id"]
    result = crud.get(c.db, SUPPLIERS, sid)
    result["types"] = rows(c.db, "SELECT t.* FROM tdr_supplier_types t JOIN tdr_supplier_type_map m "
                                 "ON m.type_id=t.id WHERE m.supplier_id=? ORDER BY t.name", (sid,))
    result["engagements"] = rows(c.db, """SELECT e.*, i.name AS item_name, i.kind AS item_kind, u.name AS unit_name
        FROM tdr_engagements e JOIN tdr_catalog_items i ON i.id=e.catalog_item_id
        JOIN tdr_org_units u ON u.id=e.org_unit_id WHERE e.supplier_id=? ORDER BY e.id DESC""", (sid,))
    result["contacts"] = rows(c.db, "SELECT * FROM tdr_supplier_contacts WHERE supplier_id=?", (sid,))
    result["source_refs"] = rows(c.db, "SELECT * FROM tdr_source_refs WHERE supplier_id=?", (sid,))
    result["responsibilities"] = rows(c.db, """SELECT * FROM tdr_responsibilities WHERE supplier_id=?
        OR engagement_id IN (SELECT id FROM tdr_engagements WHERE supplier_id=?)""", (sid, sid))
    result["contracts"] = rows(c.db, "SELECT * FROM tdr_contracts WHERE supplier_id=? ORDER BY end_date", (sid,))
    return result


def _replace_map(c, res, table, parent_col, child_col, key):
    authz.check(c.principal, res, "write")
    parent = c.params["id"]
    crud.check_scope(c.db, res, c.principal, crud.get(c.db, res, parent))
    ids = _ids(c.body, key)
    c.db.execute(f"DELETE FROM {table} WHERE {parent_col}=?", (parent,))
    for item in ids:
        c.db.execute(f"INSERT INTO {table} ({parent_col}, {child_col}) VALUES (?,?) ON CONFLICT DO NOTHING", (parent, item))
    audit.log(c.db, c.principal, "MAP", res.name, parent, {key: ids})
    return {"id": parent, key: ids}


def usage_report(c):
    """Hangi ürün/hizmeti kimden alıyoruz, hangi birim alıyor, hangi birimler kullanıyor, kime sunuluyor."""
    authz.check(c.principal, ENGAGEMENTS, "read")
    return rows(c.db, f"""SELECT i.code AS item_code, i.name AS item_name, i.kind, s.code AS supplier_code,
        s.name AS supplier_name, s.tier, u.name AS buyer_unit, e.beneficiary, e.customer_name, e.criticality,
        e.business_owner, e.status,
        (SELECT {c.db.group_concat('x.name', '; ')} FROM tdr_engagement_users eu JOIN tdr_org_units x ON x.id=eu.org_unit_id
          WHERE eu.engagement_id=e.id) AS user_units
        FROM tdr_engagements e JOIN tdr_catalog_items i ON i.id=e.catalog_item_id
        JOIN tdr_suppliers s ON s.id=e.supplier_id JOIN tdr_org_units u ON u.id=e.org_unit_id
        ORDER BY i.name, s.name""")


def register(app):
    app.route("GET", API + "/suppliers/{id}/context", supplier_context)
    app.route("POST", API + "/suppliers/{id}/types", lambda c: _replace_map(
        c, SUPPLIERS, "tdr_supplier_type_map", "supplier_id", "type_id", "type_ids"))
    app.route("POST", API + "/engagements/{id}/users", lambda c: _replace_map(
        c, ENGAGEMENTS, "tdr_engagement_users", "engagement_id", "org_unit_id", "org_unit_ids"))
    app.route("GET", API + "/reports/usage", usage_report)


STARTER_TYPES = (("HW", "Donanım"), ("SW", "Yazılım ve Lisans"), ("CLOUD", "Bulut Hizmeti"),
                 ("CONSULT", "Danışmanlık"), ("OUTSOURCE", "Dış Kaynak Personel"), ("SUPPORT", "Bakım ve Destek"),
                 ("TELCO", "Telekom"), ("FACILITY", "Tesis ve Veri Merkezi"))


DEFAULT_POLICIES = (
    ("review.cadence_months", {"critical": 6, "important": 12, "standard": 24},
     "Kritiklik seviyesine göre performans değerlendirmesi sıklığı (ay)"),
    ("survey.cadence_months", {"critical": 12, "important": 12, "standard": 24},
     "Kritiklik seviyesine göre memnuniyet anketi sıklığı (ay)"),
    ("schedule.warning_days", 30, "Yaklaşan iş olarak gösterilecek gün sayısı"),
)


def seed(db):
    for code, value, description in DEFAULT_POLICIES:     # öneri; yönetici Politika Parametreleri'nden değiştirir
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))
    for code, name in STARTER_TYPES:   # başlangıç önerisi; kurumun gerçek tip listesiyle değiştirilecek
        db.execute("INSERT INTO tdr_supplier_types (code, name) VALUES (?,?) ON CONFLICT DO NOTHING", (code, name))
