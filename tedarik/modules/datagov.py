"""Veri yönetişimi (K-028) — Faz 1: veri sözlüğü ve katalog.

Kavramlar
- Veri alanı (domain): iş alanına göre gruplama; sorumlu birim (Birim Kullanıcısının yazma kapsamı), veri sahibi ve
  veri yöneticisi. Alt alanlar üst alanın sahipliğini devralır.
- Veri kaynağı: bir sistem (SAP HANA, ServiceNow, Dynamics 365, Power BI, veritabanı, dosya). İsteğe bağlı CMDB CI'ı ve
  tedarikçisi; teknik sorumlusu.
- Tablo (tablo, görünüm, varlık, anlamsal model) ve kolon: teknik meta veri içe aktarımla gelir; iş adı, açıklama, sınıf,
  kişisel veri ve kritik veri işaretleri burada yönetilir. Kaynaktaki açıklama `technical_description` alanında ayrı
  durur ve iş tanımı sayılmaz (istenirse tek tıkla benimsenir).
- Sahiplik devralma: tablo → (tablonun veya kaynağın) veri alanı → üst alan → kaynak. Teknik sorumlu tablo → kaynak.
- İş sözlüğü: taslak → onayda → onaylı → kullanım dışı. Öneren onaylayamaz (dört göz). Onaylı terim doğrudan
  değiştirilmez; değişiklik önerilir ve onaylanınca sürüm artar. Her onay değiştirilemez bir sürüm kaydı bırakır.
- Terim ↔ kolon ve terim ↔ tablo çoktan çoğa; "nerede kullanılıyor" ve "ne anlama geliyor" bu eşlemeden gelir.

İçe aktarım (yapı): dosya bir kaynağın anlık görüntüsüdür. Biçim içerikten tanınır: hazır sorguların CSV çıktısı
(SAP HANA, SAP ABAP sözlüğü, information_schema, Oracle, Power BI DAX), ServiceNow sys_dictionary JSON/CSV, Dynamics 365
EntityDefinitions JSON veya platformun kendi JSON sözleşmesi (`tedarik.catalog.v1`, Faz 3 toplayıcısı aynı sözleşmeyi
iter). Kapsam: yalnızca dosyadaki tablolar (varsayılan), dosyadaki şemaların tamamı veya kaynağın tamamı; kapsamda olup
dosyada bulunmayan tablo ve kolon "kaldırıldı" olur (silinmez). İlk yüklemeden sonraki eklenen, kaldırılan, geri gelen ve
tipi değişen nesneler değiştirilemez değişiklik geçmişine yazılır. Ön izleme (dry_run) veri yazmaz.

Ham veri platforma gelmez: içe aktarım yalnızca meta veri (ad, tip, açıklama, satır sayısı) taşır.
"""
import csv
import io
import json
import re
import zlib
from collections import Counter, OrderedDict
from datetime import date, timedelta

from .. import audit, auth as authz, crud
from ..db import fold, one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY, Raw
from ..labels import CHOICES
from ..schema import Resource, fk

M = "datagov"
REQUIRES = ("cmdb",)
PLATFORMS = ("sap_hana", "servicenow", "dynamics365", "power_bi", "postgresql", "sql_server", "oracle", "mysql",
             "snowflake", "bigquery", "redshift", "mongodb", "file", "other")
CLASSES = ("public", "internal", "confidential", "restricted")
PERSONAL = ("none", "personal", "special")
OBJECT_TYPES = ("table", "view", "entity", "semantic_model", "report", "file", "collection", "other")
CHANGE_KINDS = ("table_added", "table_removed", "table_restored", "column_added", "column_removed", "column_restored",
                "type_changed")
SCOPES = ("tables", "schemas", "full")
MAX_RAW = 120 * 1024 * 1024        # açılmış dosya üst sınırı (gzip ile gelen dosya dahil)
MAX_COLUMNS = 300_000
MAX_TABLES = 50_000

DOMAINS = Resource("data_domains", "Veri Alanları", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL UNIQUE", "description": "TEXT", "parent_id": fk("data_domains", False),
    "org_unit_id": fk("org_units", False), "owner": "TEXT", "steward": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="VA", write="manage", search=("code", "name", "description"))

SOURCES = Resource("data_sources", "Veri Kaynakları", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL UNIQUE", "platform": "TEXT NOT NULL DEFAULT 'other'",
    "environment": "TEXT NOT NULL DEFAULT 'production'", "description": "TEXT", "domain_id": fk("data_domains", False),
    "ci_id": fk("cmdb_cis", False), "supplier_id": fk("suppliers", False), "location": "TEXT", "owner": "TEXT",
    "steward": "TEXT", "custodian": "TEXT", "status": "TEXT NOT NULL DEFAULT 'active'", "last_import_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="VK", write="manage", readonly=("last_import_at",), search=("code", "name", "location"),
    enums={"platform": PLATFORMS, "environment": ("production", "test", "development"), "status": ("active", "retired")})

TABLES = Resource("data_tables", "Veri Tabloları", {
    "source_id": fk("data_sources"), "schema_name": "TEXT NOT NULL DEFAULT ''", "name": "TEXT NOT NULL",
    "object_type": "TEXT NOT NULL DEFAULT 'table'", "technical_description": "TEXT", "business_name": "TEXT",
    "description": "TEXT", "domain_id": fk("data_domains", False), "owner": "TEXT", "steward": "TEXT", "custodian": "TEXT",
    "classification": "TEXT", "certified": "INTEGER NOT NULL DEFAULT 0", "status": "TEXT NOT NULL DEFAULT 'active'",
    "row_count": "INTEGER", "first_seen_at": "TIMESTAMP", "last_seen_at": "TIMESTAMP", "removed_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="write", unique=(("source_id", "schema_name", "name"),), search=("name", "business_name"),
    readonly=("technical_description", "first_seen_at", "last_seen_at", "removed_at"),
    enums={"object_type": OBJECT_TYPES, "classification": CLASSES, "status": ("active", "deprecated", "removed")})

COLUMNS = Resource("data_columns", "Veri Kolonları", {
    "table_id": fk("data_tables"), "name": "TEXT NOT NULL", "position": "INTEGER", "data_type": "TEXT",
    "data_length": "TEXT", "nullable": "INTEGER", "is_primary_key": "INTEGER NOT NULL DEFAULT 0", "references_to": "TEXT",
    "technical_description": "TEXT", "business_name": "TEXT", "description": "TEXT", "classification": "TEXT",
    "personal_data": "TEXT", "is_critical": "INTEGER NOT NULL DEFAULT 0", "status": "TEXT NOT NULL DEFAULT 'active'",
    "previous_type": "TEXT", "first_seen_at": "TIMESTAMP", "removed_at": "TIMESTAMP", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"},
    module=M, write="write", unique=(("table_id", "name"),), search=("name", "business_name"),
    readonly=("technical_description", "status", "previous_type", "first_seen_at", "removed_at"),
    enums={"classification": CLASSES, "personal_data": PERSONAL, "status": ("active", "removed")})

TERMS = Resource("glossary_terms", "İş Sözlüğü", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "abbreviation": "TEXT", "synonyms": "TEXT",
    "definition": "TEXT NOT NULL", "domain_id": fk("data_domains", False), "parent_id": fk("glossary_terms", False),
    "owner": "TEXT", "steward": "TEXT", "example": "TEXT", "format_rule": "TEXT", "calculation": "TEXT",
    "source_reference": "TEXT", "classification": "TEXT", "personal_data": "TEXT", "is_critical": "INTEGER NOT NULL DEFAULT 0",
    "review_date": "DATE", "status": "TEXT NOT NULL DEFAULT 'draft'", "version": "INTEGER NOT NULL DEFAULT 0",
    "submitted_by": "TEXT", "submitted_at": "TIMESTAMP", "approved_by": "TEXT", "approved_at": "TIMESTAMP",
    "pending_json": "TEXT", "pending_by": "TEXT", "pending_note": "TEXT", "pending_at": "TIMESTAMP", "review_note": "TEXT",
    "replaced_by_id": fk("glossary_terms", False), "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"},
    module=M, code_prefix="TRM", write="write", search=("code", "name", "abbreviation", "synonyms"),
    readonly=("status", "version", "submitted_by", "submitted_at", "approved_by", "approved_at", "pending_json",
              "pending_by", "pending_note", "pending_at", "review_note", "replaced_by_id", "created_by"),
    enums={"classification": CLASSES, "personal_data": PERSONAL,
           "status": ("draft", "in_review", "approved", "retired")})

VERSIONS = Resource("glossary_term_versions", "Terim Sürümleri", {
    "term_id": fk("glossary_terms"), "version": "INTEGER NOT NULL", "snapshot_json": "TEXT NOT NULL",
    "change_note": "TEXT", "proposed_by": "TEXT", "approved_by": "TEXT NOT NULL", "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list", "get"), immutable=True, unique=(("term_id", "version"),), search=())
Resource("term_columns", "Terim–kolon eşlemesi", {
    "term_id": fk("glossary_terms"), "column_id": fk("data_columns"), "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL"}, module=M, unique=(("term_id", "column_id"),), api=(), search=())
Resource("term_tables", "Terim–tablo eşlemesi", {
    "term_id": fk("glossary_terms"), "table_id": fk("data_tables"), "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL"}, module=M, unique=(("term_id", "table_id"),), api=(), search=())
Resource("term_relations", "İlişkili terimler", {
    "term_id": fk("glossary_terms"), "related_id": fk("glossary_terms")},
    module=M, unique=(("term_id", "related_id"),), api=(), search=())

IMPORTS = Resource("catalog_imports", "Katalog İçe Aktarımları", {
    "source_id": fk("data_sources"), "kind": "TEXT NOT NULL", "format": "TEXT NOT NULL", "filename": "TEXT NOT NULL",
    "scope": "TEXT", "summary_json": "TEXT NOT NULL", "created_by": "TEXT NOT NULL", "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list", "get"), immutable=True, search=("filename",),
    enums={"kind": ("structure", "descriptions"), "scope": SCOPES})
CHANGES = Resource("catalog_changes", "Şema Değişiklikleri", {
    "source_id": fk("data_sources"), "import_id": fk("catalog_imports", False), "table_id": fk("data_tables", False),
    "column_id": fk("data_columns", False), "change": "TEXT NOT NULL", "object_name": "TEXT NOT NULL", "detail": "TEXT",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), immutable=True, search=("object_name",), enums={"change": CHANGE_KINDS})

MATERIAL = ("name", "abbreviation", "synonyms", "definition", "domain_id", "parent_id", "example", "format_rule",
            "calculation", "source_reference", "classification", "personal_data", "is_critical")
SNAPSHOT = MATERIAL + ("owner", "steward", "review_date")
DOC = "(COALESCE(c.business_name,'')<>'' OR COALESCE(c.description,'')<>'' OR m.column_id IS NOT NULL)"
DOC_X = ("(COALESCE(c.business_name,'')<>'' OR COALESCE(c.description,'')<>'' OR EXISTS (SELECT 1 FROM tdr_term_columns mm "
         "WHERE mm.column_id=c.id))")
LINKED = "LEFT JOIN (SELECT DISTINCT column_id FROM tdr_term_columns) m ON m.column_id=c.id"
EFFECTIVE = """LEFT JOIN tdr_data_domains d ON d.id=COALESCE(t.domain_id, s.domain_id)
    LEFT JOIN tdr_data_domains pd ON pd.id=d.parent_id"""
EFF_COLS = """COALESCE(t.owner, d.owner, pd.owner, s.owner) AS eff_owner,
    COALESCE(t.steward, d.steward, pd.steward, s.steward) AS eff_steward, COALESCE(t.custodian, s.custodian) AS eff_custodian"""


def _me(principal):
    return {principal.username, principal.display_name or principal.username} - {None, ""}


def _same(a, b):
    a = None if a in (None, "") else str(a)
    b = None if b in (None, "") else str(b)
    return a == b


def _today():
    return date.today().isoformat()


def _notify(db, *args, **kw):
    from .. import notify
    return notify.enqueue(db, *args, **kw)


# ------------------------------------------------------------------ kapsam ve kurallar

def _domain_units(db, domain_id):
    """Veri alanının ve üst alanlarının sorumlu birimleri (Birim Kullanıcısının yazma kapsamı)."""
    units, seen = set(), set()
    while domain_id and domain_id not in seen and len(seen) < 10:
        seen.add(domain_id)
        d = one(db, "SELECT parent_id, org_unit_id FROM tdr_data_domains WHERE id=?", (domain_id,))
        if not d:
            break
        if d["org_unit_id"]:
            units.add(d["org_unit_id"])
        domain_id = d["parent_id"]
    return units


def _table_units(db, record):
    domain = record.get("domain_id")
    if not domain and record.get("source_id"):
        s = one(db, "SELECT domain_id FROM tdr_data_sources WHERE id=?", (record["source_id"],))
        domain = s["domain_id"] if s else None
    return _domain_units(db, domain)


def _column_units(db, record):
    table = one(db, "SELECT source_id, domain_id FROM tdr_data_tables WHERE id=?", (record.get("table_id"),))
    return _table_units(db, table) if table else set()


TABLES.scope = _table_units
COLUMNS.scope = _column_units
TERMS.scope = lambda db, r: _domain_units(db, r.get("domain_id"))


def _no_cycle(db, table, record_id, parent_id, label):
    seen = set()
    while parent_id:
        if parent_id == record_id or parent_id in seen or len(seen) > 20:
            raise crud.Invalid(f"{label} kendisinin altına bağlanamaz")
        seen.add(parent_id)
        row = one(db, f"SELECT parent_id FROM {table} WHERE id=?", (parent_id,))
        parent_id = row["parent_id"] if row else None


def _domain_rules(db, data, current, principal):
    if current and "parent_id" in data:
        _no_cycle(db, "tdr_data_domains", current["id"], data["parent_id"], "Veri alanı")


def _source_rules(db, data, current, principal):
    location = data.get("location")
    if location and re.search(r"(password|parola|secret|token)\s*=", location, re.I):
        raise crud.Invalid("Konum alanına parola veya belirteç yazmayın; yalnızca sunucu veya örnek adı")


def _term_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if current is None:
        if principal is not None:
            data["created_by"] = principal.username
        data.setdefault("status", "draft")
    elif principal is not None:
        changed = {k for k, v in data.items() if k != "updated_at" and not _same(v, current.get(k))}
        if current["status"] in ("approved", "retired") and changed & set(MATERIAL):
            raise crud.Invalid("Onaylı terim doğrudan değiştirilemez; 'Değişiklik öner' ile önerin, onaylanınca yeni sürüm olur")
        if current["status"] == "in_review" and changed:
            raise crud.Invalid("Onaydaki terim düzenlenemez; önce onaydan geri çekin")
        if current["status"] == "approved" and changed and not (
                principal.can("manage") or _me(principal) & {current["owner"], current["steward"]}):
            raise crud.Invalid("Onaylı terimde sahip, veri yöneticisi ve gözden geçirme tarihini terimin sahibi, veri "
                               "yöneticisi veya veri yönetişimi yöneticisi değiştirebilir")
    if merged.get("parent_id"):
        if current and merged["parent_id"] == current["id"]:
            raise crud.Invalid("Terim kendisinin üst terimi olamaz")
        if current:
            _no_cycle(db, "tdr_glossary_terms", current["id"], merged["parent_id"], "Terim")
    if "name" in data or "domain_id" in data:
        same = one(db, """SELECT code FROM tdr_glossary_terms WHERE tdr_fold(name)=tdr_fold(?) AND
            COALESCE(domain_id, 0)=COALESCE(?, 0) AND status<>'retired' AND id<>?""",
                   (merged["name"], merged.get("domain_id"), (current or {}).get("id", 0)))
        if same:
            raise crud.Invalid(f"Bu veri alanında aynı adlı terim var: {same['code']}")


def _table_rules(db, data, current, principal):
    if current and principal is not None:
        if "source_id" in data and data["source_id"] != current["source_id"]:
            raise crud.Invalid("Tablonun kaynağı değiştirilemez")
        if data.get("status") == "removed" and current["status"] != "removed":
            raise crud.Invalid("'Kaldırıldı' durumunu içe aktarım belirler; kullanılmayan tablo için 'Kullanım dışı' seçin")


DOMAINS.before_save = _domain_rules
TABLES.before_save = _table_rules
SOURCES.before_save = _source_rules
TERMS.before_save = _term_rules


def _writable(c, res, record):
    """Genel yazma yetkisi ve Birim Kullanıcısı kapsamı (özel uç noktalar için)."""
    authz.require_human(c.principal)
    authz.check(c.principal, res, "write")
    crud.check_scope(c.db, res, c.principal, record)


# ------------------------------------------------------------------ dosya okuma ve biçim tanıma

def _payload(c):
    filename = c.body.get("filename")
    if not isinstance(filename, str) or not filename.strip() or len(filename) > 200:
        raise crud.Invalid("Dosya adı gerekli")
    import base64
    import binascii
    try:
        raw = base64.b64decode(c.body.get("content_base64") or "", validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise crud.Invalid("Dosya içeriği okunamadı (base64)") from None
    if not raw:
        raise crud.Invalid("Dosya boş")
    if c.body.get("compressed") == "gzip" or raw[:2] == b"\x1f\x8b":
        try:
            inflater = zlib.decompressobj(wbits=31)
            out = inflater.decompress(raw, MAX_RAW + 1)
        except zlib.error:
            raise crud.Invalid("Sıkıştırılmış dosya açılamadı") from None
        if len(out) > MAX_RAW or inflater.unconsumed_tail:
            raise crud.Invalid(f"Dosya {MAX_RAW // (1024 * 1024)} MB sınırını aşıyor; kaynağı şemalara bölün")
        raw = out
    return filename.strip(), raw


def _text(raw):
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return raw.decode("cp1254")
        except UnicodeDecodeError:
            raise crud.Invalid("Dosya UTF-8 olmalı (Excel'de 'CSV UTF-8' olarak kaydedin)") from None


def norm_header(text):
    text = fold(str(text or "")).strip().strip("[]\"'")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


HEADERS = {
    "schema": ("schema name", "schema", "table schema", "owner", "sema", "sema adi", "table catalog schema"),
    "table": ("table name", "table", "tabname", "view name", "tablo", "tablo adi", "entity", "object name",
              "entity logical name", "logicalname table"),
    "object_type": ("object type", "table type", "nesne turu", "tablo turu"),
    "table_comment": ("table comment", "table comments", "table text", "ddtext", "tablo aciklamasi",
                      "kaynak tablo aciklamasi", "table description"),
    "column": ("column name", "column", "fieldname", "field name", "kolon", "kolon adi", "alan", "alan adi",
               "attribute", "element"),
    "position": ("position", "ordinal position", "column id", "sira", "column position", "table detail position",
                 "tabledetailposition"),
    "data_type": ("data type", "data type name", "datatype", "type", "veri tipi", "tip", "internal type",
                  "attribute type", "explicit data type", "explicitdatatype"),
    "length": ("data length", "length", "leng", "character maximum length", "max length", "uzunluk", "char length"),
    "scale": ("scale", "numeric scale", "decimals", "data scale"),
    "nullable": ("nullable", "is nullable", "bos olabilir", "null", "isnullable"),
    "not_null": ("not null", "notnull", "mandatory", "required", "zorunlu"),
    "primary_key": ("primary key", "is primary key", "keyflag", "pk", "birincil anahtar", "is key", "key", "iskey"),
    "column_key": ("column key",),
    "references": ("references", "references to", "checktable", "referenced", "foreign key", "referans", "reference"),
    "column_comment": ("column comment", "comments", "column text", "scrtext l", "remarks", "kolon aciklamasi",
                       "kaynak aciklamasi", "column label", "label", "column description", "description"),
    "row_count": ("row count", "record count", "num rows", "satir sayisi", "table rows"),
}
_ALIAS = {alias: key for key, names in HEADERS.items() for alias in names}
TRUE = {"1", "y", "yes", "true", "x", "evet", "e", "pri", "doğru", "dogru"}
FALSE = {"0", "n", "no", "false", "hayir", "hayır", "h", ""}


def _flag(value):
    text = str(value if value is not None else "").strip().lower()
    if text in TRUE:
        return 1
    if text in FALSE:
        return 0
    return None


def _object_type(value):
    text = fold(str(value or "")).upper().strip()
    if not text or text in ("BASE TABLE", "TABLE", "ROW", "COLUMN", "TRANSP", "CLUSTER", "POOL", "INTTAB", "TEMPORARY",
                            "EXTERNAL TABLE", "FOREIGN", "LOCAL TEMPORARY", "BASE"):
        return "table"
    if "VIEW" in text:
        return "view"
    for key in OBJECT_TYPES:
        if text == key.upper():
            return key
    if text in ("DATASET", "SEMANTIC MODEL"):
        return "semantic_model"
    return "other"


def _length(length, scale=None):
    text = str(length if length is not None else "").strip()
    if text.isdigit():
        text = str(int(text))
    if not text or text == "0":
        text = ""
    sc = str(scale if scale is not None else "").strip()
    if sc.isdigit() and int(sc) > 0 and text:
        text = f"{text},{int(sc)}"
    return text or None


def _int(value):
    text = str(value if value is not None else "").strip().replace(".", "")
    return int(text) if text.lstrip("-").isdigit() else None


class Catalog:
    """Dosyadan okunan anlık görüntü: (şema, tablo) -> tablo; tablo içinde kolon adına göre kolonlar."""

    def __init__(self, fmt, default_schema=""):
        self.format, self.default_schema = fmt, default_schema or ""
        self.tables = OrderedDict()
        self.columns = 0

    def table(self, schema, name, object_type=None, comment=None, row_count=None):
        schema = (str(schema).strip() if schema not in (None, "") else self.default_schema)[:128]
        name = str(name or "").strip()[:256]
        if not name:
            return None
        key = (schema.lower(), name.lower())
        t = self.tables.get(key)
        if t is None:
            if len(self.tables) >= MAX_TABLES:
                raise crud.Invalid(f"Tek dosyada en çok {MAX_TABLES} tablo olabilir; kaynağı şemalara bölün")
            t = self.tables[key] = {"schema": schema, "name": name, "object_type": object_type or "table",
                                    "comment": None, "row_count": None, "columns": OrderedDict()}
        if object_type and t["object_type"] == "table":
            t["object_type"] = object_type
        if comment and not t["comment"]:
            t["comment"] = str(comment).strip()[:2000]
        if row_count is not None:
            t["row_count"] = row_count
        return t

    def column(self, t, name, **values):
        name = str(name or "").strip()[:256]
        if not name or t is None or name.startswith("."):       # SAP .INCLUDE/.APPEND satırları
            return
        key = name.lower()
        col = t["columns"].get(key)
        if col is None:
            if self.columns >= MAX_COLUMNS:
                raise crud.Invalid(f"Tek dosyada en çok {MAX_COLUMNS} kolon olabilir; kaynağı şemalara bölün")
            self.columns += 1
            col = t["columns"][key] = {"name": name, "position": None, "data_type": None, "data_length": None,
                                       "nullable": None, "is_primary_key": 0, "references_to": None, "comment": None}
        for k, v in values.items():
            if v in (None, ""):
                continue
            if k == "is_primary_key":
                col[k] = max(col[k] or 0, v)
            elif k == "references_to" and col[k] and v not in col[k].split(", "):
                col[k] = f"{col[k]}, {v}"[:500]
            elif col.get(k) in (None, ""):
                col[k] = str(v)[:2000] if k in ("comment", "references_to", "data_type", "data_length") else v


def parse_catalog(filename, raw, default_schema=""):
    lower = filename.lower()
    head = raw[:64].lstrip()
    if lower.endswith(".json") or head[:1] == b"{" or re.match(rb"\[\s*[\{\]]", head):
        try:
            data = json.loads(_text(raw))
        except ValueError:
            raise crud.Invalid("JSON dosyası okunamadı") from None
        return _parse_json(data, default_schema)
    if lower.endswith(".xlsx"):
        from .transfer import read_table
        headers, records = read_table(filename, raw)
        return _parse_rows(headers, ([r.get(h, "") for h in headers] for r in records), default_schema, "excel")
    if not lower.endswith((".csv", ".txt", ".tsv")):
        raise crud.Invalid("Dosya türü .csv, .xlsx veya .json olmalı")
    text = _text(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    headers = next(reader, None)
    if not headers:
        raise crud.Invalid("Dosyada başlık satırı yok")
    return _parse_rows(headers, reader, default_schema, "csv")


def _parse_rows(headers, records, default_schema, kind):
    normalized = [norm_header(h) for h in headers]
    servicenow = "element" in normalized and "name" in normalized
    index = {}
    for i, h in enumerate(normalized):
        key = _ALIAS.get(h)
        if servicenow:
            key = {"name": "table", "element": "column", "column label": "column_comment", "internal type": "data_type",
                   "max length": "length", "mandatory": "not_null", "reference": "references", "primary": "primary_key",
                   "comments": "column_note"}.get(h, key)
        if key and key not in index:
            index[key] = i
    if "column" not in index and "name" in normalized and "table" in index:      # Power BI INFO.VIEW.COLUMNS()
        index["column"] = normalized.index("name")
    if "table" not in index or "column" not in index:
        raise crud.Invalid("Dosyada tablo ve kolon adı sütunları bulunamadı (ör. TABLE_NAME, COLUMN_NAME). Uygulamadaki "
                           "hazır sorguyu kullanın veya şablondaki başlıkları koruyun")
    fmt = "servicenow" if servicenow else ("sap_ddic" if normalized[index["table"]] == "tabname" else kind)
    catalog = Catalog(fmt, default_schema)

    def get(row, key):
        i = index.get(key)
        return row[i] if i is not None and i < len(row) else None
    for row in records:
        if not any(str(v).strip() for v in row):
            continue
        t = catalog.table(get(row, "schema"), get(row, "table"), _object_type(get(row, "object_type")),
                          get(row, "table_comment"), _int(get(row, "row_count")))
        column = get(row, "column")
        if servicenow and not str(column or "").strip():        # koleksiyon satırı: tablonun etiketi
            if t is not None and get(row, "column_comment"):
                t["comment"] = str(get(row, "column_comment")).strip()[:2000]
            continue
        nullable = _flag(get(row, "nullable"))
        not_null = _flag(get(row, "not_null"))
        if nullable is None and not_null is not None:
            nullable = 0 if not_null else 1
        pk = _flag(get(row, "primary_key")) or (1 if str(get(row, "column_key") or "").upper() == "PRI" else 0)
        if servicenow and str(column).strip() == "sys_id":
            pk = 1
        comment = get(row, "column_comment")
        note = get(row, "column_note")
        if note and str(note).strip() and comment:
            comment = f"{comment} — {str(note).strip()}"
        refs = str(get(row, "references") or "").strip()
        catalog.column(t, column, position=_int(get(row, "position")), data_type=str(get(row, "data_type") or "").strip() or None,
                       data_length=_length(get(row, "length"), get(row, "scale")), nullable=nullable,
                       is_primary_key=pk, references_to=refs if refs and refs not in (".", "..") else None,
                       comment=str(comment).strip() if comment else None)
    if not catalog.tables:
        raise crud.Invalid("Dosyada tablo bulunamadı")
    return catalog


def _value(v, prefer="value"):
    """ServiceNow alanı: düz değer veya {"value", "display_value"} / {"link", "value"}."""
    if isinstance(v, dict):
        out = v.get(prefer) if v.get(prefer) not in (None, "") else v.get("display_value", v.get("value"))
        if prefer == "value" and isinstance(out, str) and re.fullmatch(r"[0-9a-f]{32}", out) and v.get("display_value"):
            out = v["display_value"]
        return out
    return v


def _label(obj):
    """Dynamics etiket nesnesi: Türkçe (1055) etiket, yoksa kullanıcı dilindeki etiket."""
    if not isinstance(obj, dict):
        return None
    for item in obj.get("LocalizedLabels") or []:
        if item.get("LanguageCode") == 1055 and item.get("Label"):
            return item["Label"]
    user = obj.get("UserLocalizedLabel") or {}
    return user.get("Label")


def _parse_json(data, default_schema):
    if isinstance(data, dict) and data.get("format") == "tedarik.catalog.v1":
        catalog = Catalog("tedarik.catalog.v1", default_schema)
        for t in data.get("tables") or []:
            table = catalog.table(t.get("schema"), t.get("name"), _object_type(t.get("object_type")), t.get("description"),
                                  _int(t.get("row_count")))
            for col in t.get("columns") or []:
                catalog.column(table, col.get("name"), position=_int(col.get("position")), data_type=col.get("data_type"),
                               data_length=_length(col.get("length"), col.get("scale")),
                               nullable=_flag(col.get("nullable")) if col.get("nullable") is not None else None,
                               is_primary_key=_flag(col.get("primary_key")) or 0, references_to=col.get("references"),
                               comment=col.get("description"))
        return catalog
    items = data.get("result") if isinstance(data, dict) else None
    if isinstance(items, list) and items and isinstance(items[0], dict) and "element" in items[0]:
        catalog = Catalog("servicenow", default_schema)
        for r in items:
            table = catalog.table(None, _value(r.get("name")), "table")
            element = _value(r.get("element"))
            if not element:
                if table is not None and _value(r.get("column_label"), "display_value"):
                    table["comment"] = str(_value(r.get("column_label"), "display_value"))[:2000]
                continue
            mandatory = _flag(_value(r.get("mandatory")))
            comment = _value(r.get("column_label"), "display_value")
            if _value(r.get("comments"), "display_value"):
                comment = f"{comment} — {_value(r.get('comments'), 'display_value')}"
            catalog.column(table, element, data_type=_value(r.get("internal_type")),
                           data_length=_length(_value(r.get("max_length"))),
                           nullable=None if mandatory is None else (0 if mandatory else 1),
                           is_primary_key=1 if element == "sys_id" or _flag(_value(r.get("primary"))) else 0,
                           references_to=_value(r.get("reference"), "value") or None, comment=comment)
        return catalog
    entities = data.get("value") if isinstance(data, dict) and "value" in data else (
        [data] if isinstance(data, dict) and "LogicalName" in data else None)
    if isinstance(entities, list) and (not entities or "LogicalName" in entities[0]):
        catalog = Catalog("dynamics365", default_schema)
        for e in entities:
            comment = _label(e.get("DisplayName"))
            desc = _label(e.get("Description"))
            table = catalog.table(None, e.get("LogicalName"), "entity", f"{comment} — {desc}" if comment and desc else comment or desc)
            primary = e.get("PrimaryIdAttribute")
            for i, a in enumerate(e.get("Attributes") or [], start=1):
                if a.get("AttributeOf"):                          # sanal ad alanları (ör. createdbyname)
                    continue
                label, adesc = _label(a.get("DisplayName")), _label(a.get("Description"))
                level = (a.get("RequiredLevel") or {}).get("Value")
                kind = a.get("AttributeType") or (a.get("AttributeTypeName") or {}).get("Value")
                catalog.column(table, a.get("LogicalName"), position=i, data_type=kind,
                               data_length=_length(a.get("MaxLength")),
                               nullable=None if level is None else (1 if level == "None" else 0),
                               is_primary_key=1 if a.get("IsPrimaryId") or a.get("LogicalName") == primary else 0,
                               references_to=", ".join(a.get("Targets") or []) or None,
                               comment=f"{label} — {adesc}" if label and adesc else label or adesc)
        if not catalog.tables:
            raise crud.Invalid("Dosyada varlık bulunamadı")
        return catalog
    raise crud.Invalid("JSON biçimi tanınmadı: ServiceNow (sys_dictionary), Dynamics 365 (EntityDefinitions) veya "
                       "tedarik.catalog.v1 bekleniyor")


# ------------------------------------------------------------------ yapı içe aktarımı

def _qualified(schema, name, column=None):
    return ".".join(p for p in (schema, name, column) if p)


def _type_sig(data_type, length):
    return f"{(data_type or '').upper()}({length})" if length else (data_type or "").upper()


def apply_structure(db, source, catalog, *, scope="tables", dry_run=False, principal=None, filename=""):
    if scope not in SCOPES:
        raise crud.Invalid("Kapsam tables, schemas veya full olmalı")
    sid, now = source["id"], utcnow()
    existing = {(t["schema_name"].lower(), t["name"].lower()): t for t in rows(
        db, "SELECT id, schema_name, name, object_type, technical_description, status, row_count FROM tdr_data_tables "
            "WHERE source_id=?", (sid,))}
    columns = {}
    for col in rows(db, """SELECT c.id, c.table_id, c.name, c.position, c.data_type, c.data_length, c.nullable,
            c.is_primary_key, c.references_to, c.technical_description, c.status FROM tdr_data_columns c
            JOIN tdr_data_tables t ON t.id=c.table_id WHERE t.source_id=?""", (sid,)):
        columns.setdefault(col["table_id"], {})[col["name"].lower()] = col
    initial = not existing
    counts, samples, changes = Counter(), {}, []

    def note(kind, obj, detail=None, table_id=None, column_id=None, n=1):
        counts[kind] += n
        bucket = samples.setdefault(kind, [])
        if len(bucket) < 25:
            bucket.append({"object": obj, "detail": detail})
        if not initial:
            changes.append((kind, obj, detail, table_id, column_id))

    def insert_columns(table_id, table, cols):
        values = [(table_id, c["name"], c["position"], c["data_type"], c["data_length"], c["nullable"],
                   c["is_primary_key"] or 0, c["references_to"], c["comment"], "active", now, now) for c in cols]
        if values and not dry_run:
            db.executemany("""INSERT INTO tdr_data_columns (table_id, name, position, data_type, data_length, nullable,
                is_primary_key, references_to, technical_description, status, first_seen_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", values)

    for key, t in catalog.tables.items():
        cur = existing.get(key)
        obj = _qualified(t["schema"], t["name"])
        if cur is None:
            table_id = None
            if not dry_run:
                table_id = db.execute("""INSERT INTO tdr_data_tables (source_id, schema_name, name, object_type,
                    technical_description, row_count, status, first_seen_at, last_seen_at, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""", (sid, t["schema"], t["name"], t["object_type"], t["comment"],
                                                      t["row_count"], "active", now, now, now)).lastrowid
            note("table_added", obj, f"{len(t['columns'])} kolon", table_id)
            counts["column_added"] += len(t["columns"])
            insert_columns(table_id, t, t["columns"].values())
            continue
        sets = {"last_seen_at": now}
        if cur["status"] == "removed":
            sets.update(status="active", removed_at=None)
            note("table_restored", obj, None, cur["id"])
        if t["comment"] and not _same(t["comment"], cur["technical_description"]):
            sets["technical_description"] = t["comment"]
        if t["object_type"] != cur["object_type"] and t["object_type"] != "table":
            sets["object_type"] = t["object_type"]
        if t["row_count"] is not None and t["row_count"] != cur["row_count"]:
            sets["row_count"] = t["row_count"]
        if not dry_run:
            db.execute(f"UPDATE tdr_data_tables SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                       (*sets.values(), cur["id"]))
        known = columns.get(cur["id"], {})
        added = []
        for ckey, col in t["columns"].items():
            e = known.get(ckey)
            name = _qualified(t["schema"], t["name"], col["name"])
            if e is None:
                added.append(col)
                if dry_run or initial:
                    note("column_added", name, _type_sig(col["data_type"], col["data_length"]), cur["id"])
                continue
            cs = {}
            if e["status"] == "removed":
                cs.update(status="active", removed_at=None)
                note("column_restored", name, None, cur["id"], e["id"])
            old, new = _type_sig(e["data_type"], e["data_length"]), _type_sig(col["data_type"], col["data_length"])
            if col["data_type"] and old != new:
                cs.update(data_type=col["data_type"], data_length=col["data_length"], previous_type=old)
                note("type_changed", name, f"{old} → {new}", cur["id"], e["id"])
            for field, value in (("position", col["position"]), ("nullable", col["nullable"]),
                                 ("is_primary_key", col["is_primary_key"]), ("references_to", col["references_to"]),
                                 ("technical_description", col["comment"])):
                if value is not None and not _same(value, e[field]):
                    cs[field] = value
            if cs and not dry_run:
                db.execute(f"UPDATE tdr_data_columns SET {', '.join(f'{k}=?' for k in cs)}, updated_at=? WHERE id=?",
                           (*cs.values(), now, e["id"]))
        if added:
            if dry_run or initial:
                insert_columns(cur["id"], t, added)
            else:
                for col in added:
                    column_id = db.execute("""INSERT INTO tdr_data_columns (table_id, name, position, data_type,
                        data_length, nullable, is_primary_key, references_to, technical_description, status,
                        first_seen_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (cur["id"], col["name"], col["position"], col["data_type"], col["data_length"], col["nullable"],
                         col["is_primary_key"] or 0, col["references_to"], col["comment"], "active", now, now)).lastrowid
                    note("column_added", _qualified(t["schema"], t["name"], col["name"]),
                         _type_sig(col["data_type"], col["data_length"]), cur["id"], column_id)
        for ckey, e in known.items():
            if ckey not in t["columns"] and e["status"] == "active":
                note("column_removed", _qualified(t["schema"], t["name"], e["name"]), None, cur["id"], e["id"])
                if not dry_run:
                    db.execute("UPDATE tdr_data_columns SET status='removed', removed_at=?, updated_at=? WHERE id=?",
                               (now, now, e["id"]))
    schemas = {k[0] for k in catalog.tables}
    for key, cur in existing.items():
        if key in catalog.tables or cur["status"] == "removed":
            continue
        if scope == "full" or (scope == "schemas" and key[0] in schemas):
            note("table_removed", _qualified(cur["schema_name"], cur["name"]), None, cur["id"])
            if not dry_run:
                db.execute("UPDATE tdr_data_tables SET status='removed', removed_at=?, updated_at=? WHERE id=?",
                           (now, now, cur["id"]))
    summary = {"format": catalog.format, "tables_in_file": len(catalog.tables), "columns_in_file": catalog.columns,
               "counts": dict(counts), "samples": samples, "initial": initial, "scope": scope, "dry_run": dry_run}
    if dry_run:
        return summary
    import_id = db.execute("""INSERT INTO tdr_catalog_imports (source_id, kind, format, filename, scope, summary_json,
        created_by, created_at) VALUES (?,?,?,?,?,?,?,?)""",
        (sid, "structure", catalog.format, filename[:200], scope,
         json.dumps({k: v for k, v in summary.items() if k != "samples"}, ensure_ascii=False),
         principal.username if principal else "system", now)).lastrowid
    if changes:
        db.executemany("""INSERT INTO tdr_catalog_changes (source_id, import_id, table_id, column_id, change, object_name,
            detail, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                       [(sid, import_id, tid, cid, kind, obj[:500], detail, now) for kind, obj, detail, tid, cid in changes])
    db.execute("UPDATE tdr_data_sources SET last_import_at=?, updated_at=? WHERE id=?", (now, now, sid))
    summary["import_id"] = import_id
    return summary


def import_structure(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "manage")
    source = crud.get(c.db, SOURCES, c.params["id"])
    filename, raw = _payload(c)
    default_schema = str(c.body.get("default_schema") or "").strip()[:128]
    catalog = parse_catalog(filename, raw, default_schema)
    dry_run = bool(c.body.get("dry_run"))
    summary = apply_structure(c.db, source, catalog, scope=c.body.get("scope") or "tables", dry_run=dry_run,
                              principal=c.principal, filename=filename)
    if not dry_run:
        audit.log(c.db, c.principal, "IMPORT", "data_sources", source["id"],
                  {"filename": filename, "format": catalog.format, "counts": summary["counts"], "scope": summary["scope"]})
    return summary


# ------------------------------------------------------------------ iş açıklamaları içe/dışa aktarımı

DESC_HEADERS = OrderedDict([
    ("schema", "Şema"), ("table", "Tablo"), ("column", "Kolon"), ("object_type", "Nesne türü"),
    ("data_type", "Veri tipi"), ("data_length", "Uzunluk"), ("is_primary_key", "Birincil anahtar"),
    ("technical_description", "Kaynak açıklaması"), ("business_name", "İş adı"), ("description", "Açıklama"),
    ("classification", "Sınıf"), ("personal_data", "Kişisel veri"), ("is_critical", "Kritik veri"),
    ("terms", "Terimler"), ("domain", "Veri alanı"), ("owner", "Sahip"), ("steward", "Veri yöneticisi"),
    ("custodian", "Teknik sorumlu"), ("certified", "Onaylı veri seti"),
])
_DESC_ALIAS = {norm_header(label): key for key, label in DESC_HEADERS.items()}
_DESC_ALIAS.update({norm_header(k): k for k in DESC_HEADERS})
_DESC_ALIAS.update({"schema name": "schema", "table name": "table", "column name": "column", "is adi": "business_name",
                    "terim": "terms", "sinif": "classification", "kritik": "is_critical"})
TABLE_FIELDS = ("business_name", "description", "classification", "owner", "steward", "custodian", "certified", "domain")
COLUMN_FIELDS = ("business_name", "description", "classification", "personal_data", "is_critical")


def _choice_value(name, value, allowed, resource):
    text = str(value or "").strip()
    if not text:
        return None
    if text in allowed:
        return text
    labels = CHOICES.get(f"{resource}.{name}") or CHOICES.get(name) or {}
    for code, label in labels.items():
        if fold(label) == fold(text) and code in allowed:
            return code
    raise crud.Invalid(f"'{text}' geçerli bir değer değil")


def _flag_value(value):
    text = str(value or "").strip()
    if not text:
        return None
    flag = _flag(text)
    if flag is None:
        raise crud.Invalid(f"'{text}' için Evet veya Hayır yazın")
    return flag


def apply_descriptions(db, source, headers, records, *, dry_run=False, principal=None, filename=""):
    index = {}
    for i, h in enumerate(headers):
        key = _DESC_ALIAS.get(norm_header(h))
        if key and key not in index:
            index[key] = i
    if "table" not in index:
        raise crud.Invalid("Dosyada 'Tablo' sütunu yok; kataloğu dışa aktarıp aynı şablonu kullanın")
    tables = {}
    by_name = {}
    for t in rows(db, "SELECT * FROM tdr_data_tables WHERE source_id=?", (source["id"],)):
        tables[(t["schema_name"].lower(), t["name"].lower())] = t
        by_name.setdefault(t["name"].lower(), []).append(t)
    terms = {}
    for t in rows(db, "SELECT id, code, name FROM tdr_glossary_terms WHERE status<>'retired'"):
        terms[fold(t["code"])] = t["id"]
        terms.setdefault(fold(t["name"]), t["id"])
    domains = {}
    for d in rows(db, "SELECT id, code, name FROM tdr_data_domains"):
        domains[fold(d["code"])] = d["id"]
        domains[fold(d["name"])] = d["id"]
    column_cache = {}
    counts, errors = Counter(), []
    now = utcnow()
    for row_no, row in enumerate(records, start=2):
        def get(key):
            i = index.get(key)
            return row[i] if i is not None and i < len(row) else None
        if not any(str(v).strip() for v in row):
            continue
        try:
            schema, name = str(get("schema") or "").strip(), str(get("table") or "").strip()
            if not name:
                raise crud.Invalid("Tablo adı boş")
            table = tables.get((schema.lower(), name.lower()))
            if table is None and not schema and len(by_name.get(name.lower(), [])) == 1:
                table = by_name[name.lower()][0]
            if table is None:
                raise crud.Invalid(f"Tablo katalogda yok: {_qualified(schema, name)}")
            column_name = str(get("column") or "").strip()
            changes = {}
            if column_name:
                if table["id"] not in column_cache:
                    column_cache[table["id"]] = {c["name"].lower(): c for c in rows(
                        db, "SELECT * FROM tdr_data_columns WHERE table_id=?", (table["id"],))}
                target = column_cache[table["id"]].get(column_name.lower())
                if target is None:
                    raise crud.Invalid(f"Kolon katalogda yok: {_qualified(schema, name, column_name)}")
                res, fields = COLUMNS, COLUMN_FIELDS
            else:
                target, res, fields = table, TABLES, TABLE_FIELDS
            for field in fields:
                raw_value = get(field)
                if raw_value is None or not str(raw_value).strip():
                    continue
                if field in ("classification", "personal_data"):
                    value = _choice_value(field, raw_value, CLASSES if field == "classification" else PERSONAL, res.name)
                elif field in ("is_critical", "certified"):
                    value = _flag_value(raw_value)
                elif field == "domain":
                    value = domains.get(fold(str(raw_value).strip()))
                    if value is None:
                        raise crud.Invalid(f"Veri alanı bulunamadı: {raw_value}")
                    field = "domain_id"
                else:
                    value = str(raw_value).strip()[:4000]
                if not _same(value, target.get(field)):
                    changes[field] = value
            linked = []
            if column_name and get("terms") and str(get("terms")).strip():
                for part in re.split(r"[;,\n]", str(get("terms"))):
                    if not part.strip():
                        continue
                    term_id = terms.get(fold(part.strip()))
                    if term_id is None:
                        raise crud.Invalid(f"Terim bulunamadı: {part.strip()}")
                    linked.append(term_id)
            if changes:
                counts["columns_updated" if column_name else "tables_updated"] += 1
                if not dry_run:
                    crud.update(db, res, target["id"], changes, principal)
                    target.update(changes)
            for term_id in linked:
                exists = one(db, "SELECT 1 AS x FROM tdr_term_columns WHERE term_id=? AND column_id=?", (term_id, target["id"]))
                if not exists:
                    counts["terms_linked"] += 1
                    if not dry_run:
                        db.execute("INSERT INTO tdr_term_columns (term_id, column_id, created_by, created_at) VALUES "
                                   "(?,?,?,?) ON CONFLICT DO NOTHING",
                                   (term_id, target["id"], principal.username if principal else "system", now))
            if not changes and not linked:
                counts["unchanged"] += 1
        except (crud.Invalid, crud.Forbidden) as exc:
            counts["errors"] += 1
            if len(errors) < 100:
                errors.append({"row": row_no, "message": str(exc)})
    summary = {"counts": dict(counts), "errors": errors, "dry_run": dry_run}
    if not dry_run and (counts["tables_updated"] or counts["columns_updated"] or counts["terms_linked"]):
        summary["import_id"] = db.execute("""INSERT INTO tdr_catalog_imports (source_id, kind, format, filename,
            summary_json, created_by, created_at) VALUES (?,?,?,?,?,?,?)""",
            (source["id"], "descriptions", "descriptions", filename[:200], json.dumps(summary, ensure_ascii=False),
             principal.username if principal else "system", now)).lastrowid
    return summary


def _read_any(filename, raw):
    if filename.lower().endswith(".xlsx"):
        from .transfer import read_table
        headers, records = read_table(filename, raw)
        return headers, [[r.get(h, "") for h in headers] for r in records]
    if not filename.lower().endswith((".csv", ".txt")):
        raise crud.Invalid("Dosya türü .xlsx veya .csv olmalı")
    text = _text(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    headers = next(reader, None)
    if not headers:
        raise crud.Invalid("Dosyada başlık satırı yok")
    return headers, reader


def import_descriptions(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "manage")
    source = crud.get(c.db, SOURCES, c.params["id"])
    filename, raw = _payload(c)
    headers, records = _read_any(filename, raw)
    dry_run = bool(c.body.get("dry_run"))
    summary = apply_descriptions(c.db, source, headers, records, dry_run=dry_run, principal=c.principal, filename=filename)
    if not dry_run:
        audit.log(c.db, c.principal, "IMPORT_DESCRIPTIONS", "data_sources", source["id"],
                  {"filename": filename, "counts": summary["counts"]})
    return summary


def _choice_label(resource, name, value):
    if value in (None, ""):
        return ""
    labels = CHOICES.get(f"{resource}.{name}") or CHOICES.get(name) or {}
    return labels.get(value, value)


def export_rows(db, source_id, schema=None, only_undocumented=False):
    where, args = ["t.source_id=?", "t.status<>'removed'"], [source_id]
    if schema is not None:
        where.append("t.schema_name=?")
        args.append(schema)
    tables = rows(db, f"""SELECT t.*, d.name AS domain_name FROM tdr_data_tables t LEFT JOIN tdr_data_domains d
        ON d.id=t.domain_id WHERE {' AND '.join(where)} ORDER BY t.schema_name, t.name""", args)
    out = [list(DESC_HEADERS.values())]
    if not tables:
        return out
    ids = [t["id"] for t in tables]
    cols = {}
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        for col in rows(db, f"""SELECT c.*, (SELECT {db.group_concat('g.name', '; ')} FROM tdr_term_columns tc
                JOIN tdr_glossary_terms g ON g.id=tc.term_id WHERE tc.column_id=c.id) AS term_names
                FROM tdr_data_columns c WHERE c.table_id IN ({','.join('?' * len(part))}) AND c.status='active'
                ORDER BY c.table_id, COALESCE(c.position, 100000), c.name""", part):
            cols.setdefault(col["table_id"], []).append(col)
    yes = lambda v: "Evet" if v else ""       # noqa: E731
    for t in tables:
        tcols = cols.get(t["id"], [])
        if only_undocumented:
            tcols = [c for c in tcols if not (c["business_name"] or c["description"] or c["term_names"])]
            if not tcols and (t["business_name"] or t["description"]):
                continue
        out.append([t["schema_name"], t["name"], "", _choice_label("data_tables", "object_type", t["object_type"]), "", "", "",
                    t["technical_description"] or "", t["business_name"] or "", t["description"] or "",
                    _choice_label("data_tables", "classification", t["classification"]), "", "", "", t["domain_name"] or "",
                    t["owner"] or "", t["steward"] or "", t["custodian"] or "", yes(t["certified"])])
        for col in tcols:
            out.append([t["schema_name"], t["name"], col["name"], "", col["data_type"] or "", col["data_length"] or "",
                        yes(col["is_primary_key"]), col["technical_description"] or "", col["business_name"] or "",
                        col["description"] or "", _choice_label("data_columns", "classification", col["classification"]),
                        _choice_label("data_columns", "personal_data", col["personal_data"]), yes(col["is_critical"]),
                        col["term_names"] or "", "", "", "", "", ""])
    return out


def export_catalog(c):
    authz.check(c.principal, TABLES, "read")
    source = crud.get(c.db, SOURCES, c.params["id"])
    schema = c.query.get("schema")
    data = export_rows(c.db, source["id"], schema, c.query.get("only") == "undocumented")
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{source['code']}-{schema or 'katalog'}").strip("-")
    if c.query.get("format") == "xlsx":
        from .transfer import _xlsx
        xlsx_io = _xlsx()           # defusedxml yoksa anlaşılır hata (CSV kullanılabilir)
        if len(data) > xlsx_io.MAX_ROWS:
            raise crud.Invalid(f"Excel en çok {xlsx_io.MAX_ROWS} satır alır ({len(data) - 1} satır var); bir şema seçin, "
                               "yalnızca tanımsızları alın veya CSV indirin")
        guide = [["Nasıl doldurulur?"], ["Her satır bir tablo (Kolon boş) veya bir kolondur."],
                 ["İş adı, Açıklama, Sınıf, Kişisel veri, Kritik veri, Terimler, Veri alanı, Sahip, Veri yöneticisi, "
                  "Teknik sorumlu ve Onaylı veri seti sütunlarını doldurun; teknik sütunlar yok sayılır."],
                 ["Boş hücre mevcut değeri değiştirmez. Terimleri ad veya kodla, noktalı virgülle ayırarak yazın."],
                 ["Sınıf: Genel, İç, Gizli, Çok gizli. Kişisel veri: Yok, Kişisel veri, Özel nitelikli. Evet/Hayır alanları: Evet."],
                 ["Dosyayı Veri Kaynağı → İş açıklamalarını içe aktar ile yükleyin; önce ön izleme gösterilir."]]
        return 200, Raw(xlsx_io.make_xlsx(OrderedDict([("Katalog", data), ("Açıklama", guide)])),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", base + ".xlsx")
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    for row in data:
        writer.writerow([("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in row])
    return 200, Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", base + ".csv")


# ------------------------------------------------------------------ hazır sorgular

QUERIES = {
    "sap_hana": [
        {"key": "hana_catalog", "title": "SAP HANA veritabanı kataloğu (tablolar ve görünümler)", "kind": "sql",
         "note": "HANA Studio, DBeaver veya hdbsql ile çalıştırıp sonucu CSV olarak kaydedin. Şema listesini daraltın; "
                 "S/4HANA uygulama şemasında 100 binden fazla tablo vardır, onun için SAP ABAP sözlüğü sorgusunu kullanın.",
         "text": """SELECT c.SCHEMA_NAME AS schema_name, c.TABLE_NAME AS table_name, 'TABLE' AS object_type,
       t.COMMENTS AS table_comment, c.COLUMN_NAME AS column_name, c.POSITION AS position,
       c.DATA_TYPE_NAME AS data_type, c.LENGTH AS data_length, c.SCALE AS scale, c.IS_NULLABLE AS nullable,
       CASE WHEN k.COLUMN_NAME IS NULL THEN 'NO' ELSE 'YES' END AS primary_key,
       r.REFERENCED_SCHEMA_NAME || '.' || r.REFERENCED_TABLE_NAME || '.' || r.REFERENCED_COLUMN_NAME AS references_to,
       c.COMMENTS AS column_comment
FROM SYS.TABLE_COLUMNS c
JOIN SYS.TABLES t ON t.SCHEMA_NAME = c.SCHEMA_NAME AND t.TABLE_NAME = c.TABLE_NAME
LEFT JOIN SYS.CONSTRAINTS k ON k.SCHEMA_NAME = c.SCHEMA_NAME AND k.TABLE_NAME = c.TABLE_NAME
     AND k.COLUMN_NAME = c.COLUMN_NAME AND k.IS_PRIMARY_KEY = 'TRUE'
LEFT JOIN SYS.REFERENTIAL_CONSTRAINTS r ON r.SCHEMA_NAME = c.SCHEMA_NAME AND r.TABLE_NAME = c.TABLE_NAME
     AND r.COLUMN_NAME = c.COLUMN_NAME
WHERE c.SCHEMA_NAME IN ('<ŞEMA_1>', '<ŞEMA_2>')
UNION ALL
SELECT v.SCHEMA_NAME, v.VIEW_NAME, 'VIEW', w.COMMENTS, v.COLUMN_NAME, v.POSITION, v.DATA_TYPE_NAME, v.LENGTH,
       v.SCALE, v.IS_NULLABLE, 'NO', NULL, v.COMMENTS
FROM SYS.VIEW_COLUMNS v
JOIN SYS.VIEWS w ON w.SCHEMA_NAME = v.SCHEMA_NAME AND w.VIEW_NAME = v.VIEW_NAME
WHERE v.SCHEMA_NAME IN ('<ŞEMA_1>', '<ŞEMA_2>')
ORDER BY 1, 2, 6;"""},
        {"key": "sap_ddic", "title": "SAP ABAP sözlüğü (S/4HANA, ECC): tablo ve alan açıklamalarıyla", "kind": "sql",
         "note": "SAP uygulama tablolarının iş açıklamaları DD02T/DD04T tablolarındadır. <SAP_ŞEMASI> yerine ABAP şemasını "
                 "(ör. SAPHANADB, SAPABAP1) yazın. Dil: 'T' Türkçe, Türkçe metin yoksa 'E'. İlgilendiğiniz tabloları "
                 "listeleyin (özel tablolar için TABNAME LIKE 'Z%'). İçe aktarırken varsayılan şemaya ABAP şemasını yazabilirsiniz.",
         "text": """SELECT l.TABNAME AS table_name, l.FIELDNAME AS column_name, l.POSITION AS position,
       l.DATATYPE AS data_type, l.LENG AS data_length, l.DECIMALS AS scale, l.KEYFLAG AS primary_key,
       l.NOTNULL AS not_null, l.CHECKTABLE AS references_to, t.DDTEXT AS table_comment, e.SCRTEXT_L AS column_comment
FROM <SAP_ŞEMASI>.DD03L l
LEFT JOIN <SAP_ŞEMASI>.DD02T t ON t.TABNAME = l.TABNAME AND t.DDLANGUAGE = 'T' AND t.AS4LOCAL = 'A'
LEFT JOIN <SAP_ŞEMASI>.DD04T e ON e.ROLLNAME = l.ROLLNAME AND e.DDLANGUAGE = 'T' AND e.AS4LOCAL = 'A'
WHERE l.AS4LOCAL = 'A' AND l.FIELDNAME NOT LIKE '.%'
  AND l.TABNAME IN ('KNA1', 'KNVV', 'VBAK', 'VBAP', 'MARA', 'MAKT', 'LFA1', 'BKPF')
ORDER BY l.TABNAME, l.POSITION;"""}],
    "servicenow": [
        {"key": "sn_dictionary", "title": "ServiceNow sözlüğü (sys_dictionary) — tarayıcıdan JSON", "kind": "url",
         "note": "ServiceNow'da oturum açıkken adresi tarayıcıda açın, sayfayı .json olarak kaydedin. Tablo listesini "
                 "nameIN ile daraltın; 10 binden fazla satır için sysparm_offset ile sayfalayın. Faz 3'te bu adım "
                 "Entegrasyonlar'daki ServiceNow bağlantısıyla otomatik olacak.",
         "text": "https://<ornek>.service-now.com/api/now/table/sys_dictionary?sysparm_query=active=true^nameINincident,"
                 "problem,change_request,sc_req_item,cmdb_ci,cmdb_ci_server,sys_user,core_company&sysparm_fields=name,"
                 "element,column_label,internal_type,max_length,mandatory,reference,primary,comments"
                 "&sysparm_display_value=all&sysparm_exclude_reference_link=true&sysparm_limit=10000"}],
    "dynamics365": [
        {"key": "d365_entities", "title": "Dynamics 365 / Dataverse varlıkları — tarayıcıdan JSON", "kind": "url",
         "note": "Dynamics'te oturum açıkken adresi tarayıcıda açın ve sonucu .json olarak kaydedin. Tüm kuruluş büyük "
                 "olabilir; tek varlık için EntityDefinitions(LogicalName='account') biçimini kullanıp dosyaları ayrı ayrı "
                 "yükleyebilirsiniz (kapsam: yalnızca dosyadaki tablolar).",
         "text": "https://<kurulus>.crm4.dynamics.com/api/data/v9.2/EntityDefinitions?$select=LogicalName,SchemaName,"
                 "DisplayName,Description,PrimaryIdAttribute&$expand=Attributes($select=LogicalName,AttributeType,"
                 "DisplayName,Description,RequiredLevel,IsPrimaryId,AttributeOf)"}],
    "power_bi": [
        {"key": "pbi_columns", "title": "Power BI anlamsal modeli — DAX sorgusu", "kind": "dax",
         "note": "Power BI Desktop'taki DAX sorgu görünümünde veya DAX Studio'da modele bağlanıp çalıştırın, sonucu CSV "
                 "olarak dışa aktarın. Varsayılan şemaya model adını yazın. Çalışma alanı ve rapor eşlemesi Faz 3'te "
                 "Power BI tarayıcısıyla gelecek.",
         "text": "EVALUATE INFO.VIEW.COLUMNS()"}],
    "postgresql": [
        {"key": "pg_columns", "title": "PostgreSQL (information_schema)", "kind": "sql", "note": "psql: \\copy (...) TO 'katalog.csv' CSV HEADER",
         "text": """SELECT c.table_schema AS schema_name, c.table_name, t.table_type AS object_type,
       obj_description(format('%I.%I', c.table_schema, c.table_name)::regclass, 'pg_class') AS table_comment,
       c.column_name, c.ordinal_position AS position, c.data_type,
       COALESCE(c.character_maximum_length, c.numeric_precision) AS data_length, c.numeric_scale AS scale,
       c.is_nullable AS nullable, CASE WHEN k.column_name IS NULL THEN 'NO' ELSE 'YES' END AS primary_key,
       col_description(format('%I.%I', c.table_schema, c.table_name)::regclass, c.ordinal_position) AS column_comment
FROM information_schema.columns c
JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name
LEFT JOIN (SELECT ku.table_schema, ku.table_name, ku.column_name FROM information_schema.table_constraints tc
           JOIN information_schema.key_column_usage ku ON ku.constraint_name = tc.constraint_name
            AND ku.table_schema = tc.table_schema WHERE tc.constraint_type = 'PRIMARY KEY') k
  ON k.table_schema = c.table_schema AND k.table_name = c.table_name AND k.column_name = c.column_name
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2, 6;"""}],
    "sql_server": [
        {"key": "mssql_columns", "title": "SQL Server (INFORMATION_SCHEMA ve MS_Description)", "kind": "sql",
         "note": "SSMS'te sonucu 'Results to File' veya sağ tık → 'Save Results As' ile CSV kaydedin.",
         "text": """SELECT c.TABLE_SCHEMA AS schema_name, c.TABLE_NAME AS table_name, t.TABLE_TYPE AS object_type,
       c.COLUMN_NAME AS column_name, c.ORDINAL_POSITION AS position, c.DATA_TYPE AS data_type,
       COALESCE(CAST(c.CHARACTER_MAXIMUM_LENGTH AS varchar(20)), CAST(c.NUMERIC_PRECISION AS varchar(20))) AS data_length,
       c.NUMERIC_SCALE AS scale, c.IS_NULLABLE AS nullable,
       CASE WHEN k.COLUMN_NAME IS NULL THEN 'NO' ELSE 'YES' END AS primary_key,
       CAST(ep.value AS nvarchar(4000)) AS column_comment
FROM INFORMATION_SCHEMA.COLUMNS c
JOIN INFORMATION_SCHEMA.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
LEFT JOIN (SELECT ku.TABLE_SCHEMA, ku.TABLE_NAME, ku.COLUMN_NAME FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
           JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku ON ku.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
            AND ku.TABLE_SCHEMA = tc.TABLE_SCHEMA WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY') k
  ON k.TABLE_SCHEMA = c.TABLE_SCHEMA AND k.TABLE_NAME = c.TABLE_NAME AND k.COLUMN_NAME = c.COLUMN_NAME
LEFT JOIN sys.extended_properties ep ON ep.class = 1 AND ep.name = 'MS_Description'
  AND ep.major_id = OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA) + '.' + QUOTENAME(c.TABLE_NAME))
  AND ep.minor_id = COLUMNPROPERTY(ep.major_id, c.COLUMN_NAME, 'ColumnId')
ORDER BY 1, 2, 5;"""}],
    "oracle": [
        {"key": "oracle_columns", "title": "Oracle (ALL_TAB_COLUMNS ve yorumlar)", "kind": "sql", "note": "SQL Developer'da sonucu CSV olarak dışa aktarın.",
         "text": """SELECT c.OWNER AS schema_name, c.TABLE_NAME AS table_name, o.OBJECT_TYPE AS object_type,
       tc.COMMENTS AS table_comment, c.COLUMN_NAME AS column_name, c.COLUMN_ID AS position, c.DATA_TYPE AS data_type,
       NVL(TO_CHAR(c.DATA_PRECISION), TO_CHAR(c.CHAR_LENGTH)) AS data_length, c.DATA_SCALE AS scale,
       c.NULLABLE AS nullable, cc.COMMENTS AS column_comment
FROM ALL_TAB_COLUMNS c
JOIN ALL_OBJECTS o ON o.OWNER = c.OWNER AND o.OBJECT_NAME = c.TABLE_NAME AND o.OBJECT_TYPE IN ('TABLE', 'VIEW')
LEFT JOIN ALL_TAB_COMMENTS tc ON tc.OWNER = c.OWNER AND tc.TABLE_NAME = c.TABLE_NAME
LEFT JOIN ALL_COL_COMMENTS cc ON cc.OWNER = c.OWNER AND cc.TABLE_NAME = c.TABLE_NAME AND cc.COLUMN_NAME = c.COLUMN_NAME
WHERE c.OWNER IN ('<ŞEMA_1>', '<ŞEMA_2>')
ORDER BY 1, 2, 6;"""}],
    "mysql": [
        {"key": "mysql_columns", "title": "MySQL / MariaDB (information_schema)", "kind": "sql", "note": "",
         "text": """SELECT c.TABLE_SCHEMA AS schema_name, c.TABLE_NAME AS table_name, t.TABLE_TYPE AS object_type,
       t.TABLE_COMMENT AS table_comment, c.COLUMN_NAME AS column_name, c.ORDINAL_POSITION AS position,
       c.DATA_TYPE AS data_type, COALESCE(c.CHARACTER_MAXIMUM_LENGTH, c.NUMERIC_PRECISION) AS data_length,
       c.NUMERIC_SCALE AS scale, c.IS_NULLABLE AS nullable, c.COLUMN_KEY AS column_key,
       c.COLUMN_COMMENT AS column_comment, t.TABLE_ROWS AS row_count
FROM information_schema.COLUMNS c
JOIN information_schema.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE c.TABLE_SCHEMA NOT IN ('mysql', 'sys', 'information_schema', 'performance_schema')
ORDER BY 1, 2, 6;"""}],
    "snowflake": [
        {"key": "snowflake_columns", "title": "Snowflake (INFORMATION_SCHEMA)", "kind": "sql", "note": "<VERITABANI> yerine veritabanı adını yazın.",
         "text": """SELECT c.TABLE_SCHEMA AS schema_name, c.TABLE_NAME AS table_name, t.TABLE_TYPE AS object_type,
       t.COMMENT AS table_comment, c.COLUMN_NAME AS column_name, c.ORDINAL_POSITION AS position,
       c.DATA_TYPE AS data_type, COALESCE(c.CHARACTER_MAXIMUM_LENGTH, c.NUMERIC_PRECISION) AS data_length,
       c.NUMERIC_SCALE AS scale, c.IS_NULLABLE AS nullable, c.COMMENT AS column_comment, t.ROW_COUNT AS row_count
FROM <VERITABANI>.INFORMATION_SCHEMA.COLUMNS c
JOIN <VERITABANI>.INFORMATION_SCHEMA.TABLES t ON t.TABLE_SCHEMA = c.TABLE_SCHEMA AND t.TABLE_NAME = c.TABLE_NAME
WHERE c.TABLE_SCHEMA <> 'INFORMATION_SCHEMA'
ORDER BY 1, 2, 6;"""}],
    "bigquery": [
        {"key": "bigquery_columns", "title": "BigQuery (bölge düzeyinde INFORMATION_SCHEMA)", "kind": "sql",
         "note": "<proje> ve <bolge> (ör. eu) değerlerini yazın; sonucu CSV olarak kaydedin.",
         "text": """SELECT c.table_schema AS schema_name, c.table_name, t.table_type AS object_type, c.column_name,
       c.ordinal_position AS position, c.data_type, c.is_nullable AS nullable, p.description AS column_comment
FROM `<proje>`.`region-<bolge>`.INFORMATION_SCHEMA.COLUMNS c
JOIN `<proje>`.`region-<bolge>`.INFORMATION_SCHEMA.TABLES t
  ON t.table_schema = c.table_schema AND t.table_name = c.table_name
LEFT JOIN `<proje>`.`region-<bolge>`.INFORMATION_SCHEMA.COLUMN_FIELD_PATHS p
  ON p.table_schema = c.table_schema AND p.table_name = c.table_name AND p.field_path = c.column_name
ORDER BY 1, 2, 5;"""}],
    "redshift": [
        {"key": "redshift_columns", "title": "Amazon Redshift (SVV_COLUMNS)", "kind": "sql", "note": "",
         "text": """SELECT table_schema AS schema_name, table_name, column_name, ordinal_position AS position, data_type,
       COALESCE(character_maximum_length, numeric_precision) AS data_length, numeric_scale AS scale,
       is_nullable AS nullable, remarks AS column_comment
FROM svv_columns
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY 1, 2, 4;"""}],
}
GENERIC_QUERY = {"key": "template", "title": "Elle doldurulan şablon", "kind": "template",
                 "note": "Kaynak sistemden sorgu çalıştıramıyorsanız aşağıdaki başlıklarla bir CSV veya Excel hazırlayın.",
                 "text": "schema_name;table_name;object_type;table_comment;column_name;position;data_type;data_length;"
                         "nullable;primary_key;references_to;column_comment"}


def queries(c):
    authz.check(c.principal, SOURCES, "read")
    platform = c.query.get("platform")
    items = QUERIES.get(platform, []) if platform else [q for qs in QUERIES.values() for q in qs]
    return {"queries": items + [GENERIC_QUERY]}


# ------------------------------------------------------------------ iş sözlüğü iş akışı

def _snapshot(term):
    return {k: (str(term[k]) if k == "review_date" and term.get(k) else term.get(k)) for k in SNAPSHOT}


def _approvers(db, term):
    names = {term["owner"]} if term.get("owner") else set()
    domain_id = term.get("domain_id")
    while not names and domain_id:
        d = one(db, "SELECT owner, parent_id FROM tdr_data_domains WHERE id=?", (domain_id,))
        if not d:
            break
        if d["owner"]:
            names.add(d["owner"])
        domain_id = d["parent_id"]
    return names


def can_approve(db, principal, term, proposer):
    if principal is None or principal.auth_type == "api_key":
        return False
    me = _me(principal)
    if proposer and proposer in me:
        return False
    return principal.can("manage") or bool(_approvers(db, term) & me)


def _term_action(c, statuses):
    term = crud.get(c.db, TERMS, c.params["id"])
    if term["status"] not in statuses:
        raise crud.Conflict("Terim bu işlem için uygun durumda değil")
    return term


def _version(db, term, note, proposer, approver):
    db.execute("""INSERT INTO tdr_glossary_term_versions (term_id, version, snapshot_json, change_note, proposed_by,
        approved_by, created_at) VALUES (?,?,?,?,?,?,?)""",
               (term["id"], term["version"], json.dumps(_snapshot(term), ensure_ascii=False, default=str), note,
                proposer, approver, utcnow()))


def term_submit(c):
    term = _term_action(c, ("draft",))
    _writable(c, TERMS, term)
    now = utcnow()
    c.db.execute("UPDATE tdr_glossary_terms SET status='in_review', submitted_by=?, submitted_at=?, review_note=NULL, "
                 "updated_at=? WHERE id=?", (c.principal.username, now, now, term["id"]))
    audit.log(c.db, c.principal, "SUBMIT", "glossary_terms", term["id"], {})
    approvers = _approvers(c.db, term) - _me(c.principal)
    if approvers:
        _notify(c.db, "glossary.review", f"Sözlük terimi onay bekliyor: {term['code']} {term['name']}",
                term["definition"][:500], users=sorted(approvers), link=f"#/glossary/{term['id']}",
                object_type="glossary_terms", object_id=term["id"])
    return term_context(c)


def term_withdraw(c):
    term = crud.get(c.db, TERMS, c.params["id"])
    proposer = term["submitted_by"] if term["status"] == "in_review" else term["pending_by"]
    if not (term["status"] == "in_review" or term["pending_json"]):
        raise crud.Conflict("Geri çekilecek bir onay talebi yok")
    if proposer not in _me(c.principal) and not c.principal.can("manage"):
        raise crud.Forbidden("Talebi yalnızca gönderen veya veri yönetişimi yöneticisi geri çekebilir")
    now = utcnow()
    if term["status"] == "in_review":
        c.db.execute("UPDATE tdr_glossary_terms SET status='draft', updated_at=? WHERE id=?", (now, term["id"]))
    else:
        c.db.execute("UPDATE tdr_glossary_terms SET pending_json=NULL, pending_by=NULL, pending_note=NULL, pending_at=NULL, "
                     "updated_at=? WHERE id=?", (now, term["id"]))
    audit.log(c.db, c.principal, "WITHDRAW", "glossary_terms", term["id"], {})
    return term_context(c)


def term_approve(c):
    authz.require_human(c.principal)
    term = crud.get(c.db, TERMS, c.params["id"])
    note = (c.body.get("note") or "").strip()[:2000] or None
    now = utcnow()
    if term["status"] == "in_review":
        if not can_approve(c.db, c.principal, term, term["submitted_by"]):
            raise crud.Forbidden("Bu terimi onaylayamazsınız: onaylayan, öneren dışında terimin (veya veri alanının) sahibi "
                                 "ya da veri yönetişimi yöneticisi olmalı")
        c.db.execute("""UPDATE tdr_glossary_terms SET status='approved', version=version+1, approved_by=?, approved_at=?,
            review_note=NULL, updated_at=? WHERE id=?""", (c.principal.username, now, now, term["id"]))
        fresh = crud.get(c.db, TERMS, term["id"])
        _version(c.db, fresh, note or "İlk onay", term["submitted_by"], c.principal.username)
        action = "APPROVE"
    elif term["status"] == "approved" and term["pending_json"]:
        if not can_approve(c.db, c.principal, term, term["pending_by"]):
            raise crud.Forbidden("Bu değişikliği onaylayamazsınız: onaylayan, öneren dışında terimin sahibi ya da veri "
                                 "yönetişimi yöneticisi olmalı")
        changes = json.loads(term["pending_json"])
        crud.validate(TERMS, dict(changes), partial=True)
        _term_rules(c.db, dict(changes), {**term, "status": "draft"}, None)
        sets = {**changes, "version": term["version"] + 1, "approved_by": c.principal.username, "approved_at": now,
                "pending_json": None, "pending_by": None, "pending_note": None, "pending_at": None, "review_note": None,
                "updated_at": now}
        c.db.execute(f"UPDATE tdr_glossary_terms SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                     (*sets.values(), term["id"]))
        fresh = crud.get(c.db, TERMS, term["id"])
        _version(c.db, fresh, term["pending_note"] or note, term["pending_by"], c.principal.username)
        action = "APPROVE_CHANGE"
    else:
        raise crud.Conflict("Onay bekleyen bir terim veya değişiklik yok")
    audit.log(c.db, c.principal, action, "glossary_terms", term["id"], {"note": note})
    return term_context(c)


def term_reject(c):
    authz.require_human(c.principal)
    term = crud.get(c.db, TERMS, c.params["id"])
    note = (c.body.get("note") or "").strip()
    if len(note) < 5:
        raise crud.Invalid("İade gerekçesini yazın")
    proposer = term["submitted_by"] if term["status"] == "in_review" else term["pending_by"]
    if not (term["status"] == "in_review" or term["pending_json"]):
        raise crud.Conflict("İade edilecek bir onay talebi yok")
    if not can_approve(c.db, c.principal, term, proposer):
        raise crud.Forbidden("Bu talebi yalnızca onaylayabilecek kişi iade edebilir")
    now = utcnow()
    if term["status"] == "in_review":
        c.db.execute("UPDATE tdr_glossary_terms SET status='draft', review_note=?, updated_at=? WHERE id=?",
                     (note[:2000], now, term["id"]))
    else:
        c.db.execute("""UPDATE tdr_glossary_terms SET pending_json=NULL, pending_by=NULL, pending_note=NULL,
            pending_at=NULL, review_note=?, updated_at=? WHERE id=?""", (note[:2000], now, term["id"]))
    audit.log(c.db, c.principal, "REJECT", "glossary_terms", term["id"], {"note": note})
    if proposer:
        _notify(c.db, "glossary.review", f"Sözlük terimi iade edildi: {term['code']} {term['name']}", note,
                users=[proposer], link=f"#/glossary/{term['id']}", object_type="glossary_terms", object_id=term["id"])
    return term_context(c)


def term_propose(c):
    term = _term_action(c, ("approved",))
    _writable(c, TERMS, term)
    if term["pending_json"]:
        raise crud.Conflict("Bu terim için onay bekleyen bir değişiklik var; önce o sonuçlanmalı")
    changes = c.body.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise crud.Invalid("Değişiklikleri gönderin")
    unknown = set(changes) - set(MATERIAL)
    if unknown:
        raise crud.Invalid("Önerilemeyen alan: " + ", ".join(sorted(unknown)))
    data = crud.validate(TERMS, crud.clean(changes), partial=True)
    data = {k: v for k, v in data.items() if not _same(v, term.get(k))}
    if not data:
        raise crud.Invalid("Önerilen değerler mevcut tanımla aynı")
    _term_rules(c.db, dict(data), {**term, "status": "draft"}, None)
    crud.check_scope(c.db, TERMS, c.principal, {**term, **data})
    note = (c.body.get("note") or "").strip()
    if len(note) < 5:
        raise crud.Invalid("Değişikliğin gerekçesini yazın")
    now = utcnow()
    c.db.execute("""UPDATE tdr_glossary_terms SET pending_json=?, pending_by=?, pending_note=?, pending_at=?, review_note=NULL,
        updated_at=? WHERE id=?""", (json.dumps(data, ensure_ascii=False, default=str), c.principal.username, note[:2000],
                                     now, now, term["id"]))
    audit.log(c.db, c.principal, "PROPOSE", "glossary_terms", term["id"], {"changes": data, "note": note})
    approvers = _approvers(c.db, term) - _me(c.principal)
    if approvers:
        _notify(c.db, "glossary.review", f"Sözlük teriminde değişiklik önerildi: {term['code']} {term['name']}", note,
                users=sorted(approvers), link=f"#/glossary/{term['id']}", object_type="glossary_terms", object_id=term["id"])
    return term_context(c)


def term_retire(c):
    term = _term_action(c, ("approved", "draft"))
    authz.require_human(c.principal)
    if not (c.principal.can("manage") or _me(c.principal) & _approvers(c.db, term)):
        raise crud.Forbidden("Terimi sahibi veya veri yönetişimi yöneticisi kullanım dışı bırakabilir")
    note = (c.body.get("note") or "").strip()
    if len(note) < 5:
        raise crud.Invalid("Kullanım dışı bırakma gerekçesini yazın")
    replaced = c.body.get("replaced_by_id")
    if replaced:
        target = crud.get(c.db, TERMS, int(replaced))
        if target["id"] == term["id"] or target["status"] != "approved":
            raise crud.Invalid("Yerine geçen terim onaylı başka bir terim olmalı")
    c.db.execute("UPDATE tdr_glossary_terms SET status='retired', replaced_by_id=?, review_note=?, pending_json=NULL, "
                 "pending_by=NULL, pending_note=NULL, pending_at=NULL, updated_at=? WHERE id=?",
                 (replaced or None, note[:2000], utcnow(), term["id"]))
    audit.log(c.db, c.principal, "RETIRE", "glossary_terms", term["id"], {"note": note, "replaced_by_id": replaced})
    return term_context(c)


def _ids(value, label):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 2000 or not all(isinstance(i, int) and i > 0 for i in value):
        raise crud.Invalid(f"{label} kimlik listesi olmalı")
    return list(dict.fromkeys(value))


def term_links(c):
    """Terimi kolon ve tablolara bağlar veya bağı kaldırır. Bağ kurmak terimin tanımını değiştirmez; hedef kaydın
    yazma kapsamı gerekir (Birim Kullanıcısı yalnızca kendi biriminin veri alanındaki kolonu bağlar)."""
    term = crud.get(c.db, TERMS, c.params["id"])
    authz.require_human(c.principal)
    if term["status"] == "retired" and (c.body.get("add_columns") or c.body.get("add_tables")):
        raise crud.Invalid("Kullanım dışı terim yeni kolona bağlanamaz")
    now, changed = utcnow(), {}
    for key, table, col, res in (("columns", "tdr_term_columns", "column_id", COLUMNS),
                                 ("tables", "tdr_term_tables", "table_id", TABLES)):
        for verb in ("add", "remove"):
            ids = _ids(c.body.get(f"{verb}_{key}"), key)
            for target_id in ids:
                _writable(c, res, crud.get(c.db, res, target_id))
                if verb == "add":
                    c.db.execute(f"INSERT INTO {table} (term_id, {col}, created_by, created_at) VALUES (?,?,?,?) "
                                 "ON CONFLICT DO NOTHING", (term["id"], target_id, c.principal.username, now))
                else:
                    c.db.execute(f"DELETE FROM {table} WHERE term_id=? AND {col}=?", (term["id"], target_id))
            if ids:
                changed[f"{verb}_{key}"] = ids
    if not changed:
        raise crud.Invalid("Eklenecek veya kaldırılacak kayıt yok")
    audit.log(c.db, c.principal, "LINK", "glossary_terms", term["id"], changed)
    return term_context(c)


def term_related(c):
    term = crud.get(c.db, TERMS, c.params["id"])
    _writable(c, TERMS, term)
    ids = [i for i in _ids(c.body.get("term_ids"), "Terim") if i != term["id"]]
    if ids and len(rows(c.db, f"SELECT id FROM tdr_glossary_terms WHERE id IN ({','.join('?' * len(ids))})", ids)) != len(ids):
        raise crud.Invalid("Bulunamayan terim seçildi")
    c.db.execute("DELETE FROM tdr_term_relations WHERE term_id=? OR related_id=?", (term["id"], term["id"]))
    for other in ids:
        a, b = sorted((term["id"], other))
        c.db.execute("INSERT INTO tdr_term_relations (term_id, related_id) VALUES (?,?) ON CONFLICT DO NOTHING", (a, b))
    audit.log(c.db, c.principal, "LINK", "glossary_terms", term["id"], {"related": ids})
    return term_context(c)


def column_terms(c):
    """Kolon ayrıntısından terim seçimi: kolonun terim kümesini verilenle değiştirir."""
    column = crud.get(c.db, COLUMNS, c.params["id"])
    _writable(c, COLUMNS, column)
    ids = _ids(c.body.get("term_ids"), "Terim")
    if ids:
        found = rows(c.db, f"SELECT id, status FROM tdr_glossary_terms WHERE id IN ({','.join('?' * len(ids))})", ids)
        if len(found) != len(ids):
            raise crud.Invalid("Bulunamayan terim seçildi")
        current = {r["term_id"] for r in rows(c.db, "SELECT term_id FROM tdr_term_columns WHERE column_id=?", (column["id"],))}
        if any(f["status"] == "retired" and f["id"] not in current for f in found):
            raise crud.Invalid("Kullanım dışı terim yeni kolona bağlanamaz")
    c.db.execute("DELETE FROM tdr_term_columns WHERE column_id=?", (column["id"],))
    for term_id in ids:
        c.db.execute("INSERT INTO tdr_term_columns (term_id, column_id, created_by, created_at) VALUES (?,?,?,?)",
                     (term_id, column["id"], c.principal.username, utcnow()))
    audit.log(c.db, c.principal, "LINK", "data_columns", column["id"], {"terms": ids})
    return column_context(c)


# ------------------------------------------------------------------ bağlam ekranları

def _pending_diff(term):
    if not term.get("pending_json"):
        return None
    changes = json.loads(term["pending_json"])
    return {"by": term["pending_by"], "at": term["pending_at"], "note": term["pending_note"],
            "fields": [{"field": k, "old": term.get(k), "new": v} for k, v in changes.items()]}


def term_context(c):
    authz.check(c.principal, TERMS, "read")
    db = c.db
    term = crud.get(db, TERMS, c.params["id"])
    term["domain"] = one(db, "SELECT id, code, name FROM tdr_data_domains WHERE id=?", (term["domain_id"],)) \
        if term["domain_id"] else None
    term["parent"] = one(db, "SELECT id, code, name, status FROM tdr_glossary_terms WHERE id=?", (term["parent_id"],)) \
        if term["parent_id"] else None
    term["replaced_by"] = one(db, "SELECT id, code, name FROM tdr_glossary_terms WHERE id=?", (term["replaced_by_id"],)) \
        if term["replaced_by_id"] else None
    term["children"] = rows(db, "SELECT id, code, name, status FROM tdr_glossary_terms WHERE parent_id=? ORDER BY name",
                            (term["id"],))
    term["related"] = rows(db, """SELECT g.id, g.code, g.name, g.status FROM tdr_term_relations r JOIN tdr_glossary_terms g
        ON g.id = CASE WHEN r.term_id=? THEN r.related_id ELSE r.term_id END WHERE r.term_id=? OR r.related_id=?
        ORDER BY g.name""", (term["id"], term["id"], term["id"]))
    term["versions"] = rows(db, "SELECT * FROM tdr_glossary_term_versions WHERE term_id=? ORDER BY version DESC", (term["id"],))
    term["columns"] = rows(db, """SELECT c.id, c.name, c.business_name, c.data_type, c.data_length, c.status,
        c.personal_data, t.id AS table_id, t.schema_name, t.name AS table_name, s.id AS source_id, s.code AS source_code,
        s.name AS source_name, s.platform FROM tdr_term_columns m JOIN tdr_data_columns c ON c.id=m.column_id
        JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources s ON s.id=t.source_id WHERE m.term_id=?
        ORDER BY s.name, t.schema_name, t.name, c.name""", (term["id"],))
    term["tables"] = rows(db, """SELECT t.id, t.schema_name, t.name, t.business_name, t.object_type, t.status,
        s.id AS source_id, s.code AS source_code, s.name AS source_name FROM tdr_term_tables m
        JOIN tdr_data_tables t ON t.id=m.table_id JOIN tdr_data_sources s ON s.id=t.source_id WHERE m.term_id=?
        ORDER BY s.name, t.schema_name, t.name""", (term["id"],))
    sources = {}
    for r in term["columns"] + term["tables"]:
        sources.setdefault(r["source_id"], {"id": r["source_id"], "code": r["source_code"], "name": r["source_name"],
                                            "count": 0})["count"] += 1
    term["used_in"] = list(sources.values())
    term["pending"] = _pending_diff(term)
    p = c.principal
    writable = authz.can_write(p, TERMS) and p.auth_type != "api_key"
    in_scope = True
    try:
        crud.check_scope(db, TERMS, p, term)
    except crud.Forbidden:
        in_scope = False
    proposer = term["submitted_by"] if term["status"] == "in_review" else term["pending_by"]
    term["can"] = {
        "edit": writable and in_scope and term["status"] == "draft",
        "submit": writable and in_scope and term["status"] == "draft",
        "propose": writable and in_scope and term["status"] == "approved" and not term["pending_json"],
        "approve": (term["status"] == "in_review" or bool(term["pending_json"])) and can_approve(db, p, term, proposer),
        "withdraw": (term["status"] == "in_review" or bool(term["pending_json"])) and (
            proposer in _me(p) or p.can("manage")),
        "retire": term["status"] in ("approved", "draft") and p.auth_type != "api_key" and (
            p.can("manage") or bool(_me(p) & _approvers(db, term))),
        "link": writable and term["status"] != "retired",
        "manage_people": term["status"] == "approved" and (p.can("manage") or bool(_me(p) & {term["owner"], term["steward"]})),
    }
    term["approvers"] = sorted(_approvers(db, term)) or ["Veri yönetişimi yöneticisi"]
    return term


def _effective(db, table):
    s = one(db, "SELECT * FROM tdr_data_sources WHERE id=?", (table["source_id"],))
    chain = []
    domain_id = table["domain_id"] or s["domain_id"]
    seen = set()
    while domain_id and domain_id not in seen and len(seen) < 10:
        seen.add(domain_id)
        d = one(db, "SELECT id, code, name, owner, steward, parent_id, org_unit_id FROM tdr_data_domains WHERE id=?", (domain_id,))
        if not d:
            break
        chain.append(d)
        domain_id = d["parent_id"]

    def pick(field, with_source=True):
        if table.get(field):
            return table[field], "table"
        for d in chain:
            if d.get(field):
                return d[field], "domain"
        if with_source and s.get(field):
            return s[field], "source"
        return None, None
    out = {}
    for field in ("owner", "steward"):
        out[field], out[field + "_from"] = pick(field)
    out["custodian"], out["custodian_from"] = (table["custodian"], "table") if table.get("custodian") else (
        (s["custodian"], "source") if s.get("custodian") else (None, None))
    out["domain"] = chain[0] if chain else None
    out["domain_from"] = "table" if table["domain_id"] else ("source" if chain else None)
    return s, out


def _processes(c, ci_id):
    if not ci_id or not c.app.enabled("continuity"):
        return []
    return rows(c.db, """SELECT DISTINCT p.id, p.code, p.name, b.id AS bia_id, b.code AS bia_code
        FROM tdr_bia_applications a JOIN tdr_bias b ON b.id=a.bia_id JOIN tdr_processes p ON p.id=b.process_id
        WHERE a.ci_id=? ORDER BY p.name""", (ci_id,))


def table_context(c):
    authz.check(c.principal, TABLES, "read")
    db = c.db
    t = crud.get(db, TABLES, c.params["id"])
    source, eff = _effective(db, t)
    t["source"] = {k: source[k] for k in ("id", "code", "name", "platform", "environment", "ci_id", "last_import_at")}
    t["effective"] = eff
    t["ci"] = one(db, "SELECT id, code, name, ci_class FROM tdr_cmdb_cis WHERE id=?", (source["ci_id"],)) if source["ci_id"] else None
    t["processes"] = _processes(c, source["ci_id"])
    cols = rows(db, """SELECT * FROM tdr_data_columns WHERE table_id=? ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END,
        COALESCE(position, 100000), name""", (t["id"],))
    terms = {}
    for r in rows(db, """SELECT m.column_id, g.id, g.code, g.name, g.status FROM tdr_term_columns m
            JOIN tdr_glossary_terms g ON g.id=m.term_id JOIN tdr_data_columns c ON c.id=m.column_id WHERE c.table_id=?
            ORDER BY g.name""", (t["id"],)):
        terms.setdefault(r["column_id"], []).append({k: r[k] for k in ("id", "code", "name", "status")})
    for col in cols:
        col["terms"] = terms.get(col["id"], [])
        col["documented"] = bool(col["business_name"] or col["description"] or col["terms"])
        col["effective_classification"] = col["classification"] or t["classification"]
    t["columns"] = cols
    active = [x for x in cols if x["status"] == "active"]
    t["stats"] = {"columns": len(active), "documented": sum(1 for x in active if x["documented"]),
                  "personal": sum(1 for x in active if x["personal_data"] in ("personal", "special")),
                  "critical": sum(1 for x in active if x["is_critical"]),
                  "technical_only": sum(1 for x in active if not x["documented"] and x["technical_description"])}
    t["terms"] = rows(db, """SELECT g.id, g.code, g.name, g.status, g.definition FROM tdr_term_tables m
        JOIN tdr_glossary_terms g ON g.id=m.term_id WHERE m.table_id=? ORDER BY g.name""", (t["id"],))
    t["changes"] = rows(db, "SELECT * FROM tdr_catalog_changes WHERE table_id=? ORDER BY id DESC LIMIT 100", (t["id"],))
    t["referenced_by"] = _referenced_by(db, source["id"], t["schema_name"], t["name"])
    try:
        crud.check_scope(db, TABLES, c.principal, t)
        t["can_edit"] = authz.can_write(c.principal, TABLES)
    except crud.Forbidden:
        t["can_edit"] = False
    return t


def _referenced_by(db, source_id, schema, table, column=None):
    """Aynı kaynakta bu tabloya/kolona referans veren kolonlar (FK, SAP CHECKTABLE, ServiceNow reference)."""
    targets = {table.lower(), _qualified(schema, table).lower()}
    if column:
        targets = {f"{x}.{column.lower()}" for x in targets} | targets
    pattern_rows = rows(db, """SELECT c.id, c.name, c.references_to, t.id AS table_id, t.schema_name, t.name AS table_name
        FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id WHERE t.source_id=? AND c.status='active'
        AND c.references_to IS NOT NULL AND tdr_fold(c.references_to) LIKE ? ESCAPE '\\' LIMIT 500""",
                        (source_id, "%" + re.sub(r"([\\%_])", r"\\\1", fold(table)) + "%"))
    out = []
    for r in pattern_rows:
        refs = {x.strip().lower() for x in str(r["references_to"]).split(",")}
        if refs & targets or (not column and any(ref.startswith(t + ".") for ref in refs for t in targets)):
            out.append(r)
    return out[:100]


def _resolve_reference(db, source_id, ref):
    """references_to metnini aynı kaynaktaki tablo/kolona çözer (şema.tablo.kolon, tablo.kolon veya tablo)."""
    out = []
    for part in [x.strip() for x in str(ref or "").split(",") if x.strip()][:5]:
        bits = part.split(".")
        table = column = schema = None
        if len(bits) >= 3:
            schema, table, column = bits[-3], bits[-2], bits[-1]
        elif len(bits) == 2:
            table, column = bits
        else:
            table = bits[0]
        candidates = rows(db, """SELECT id, schema_name, name FROM tdr_data_tables WHERE source_id=? AND
            tdr_fold(name)=tdr_fold(?)""", (source_id, table))
        if schema:
            candidates = [x for x in candidates if x["schema_name"].lower() == schema.lower()] or candidates
        if not candidates:
            continue
        hit = {"text": part, "table_id": candidates[0]["id"], "table": _qualified(candidates[0]["schema_name"], candidates[0]["name"])}
        if column:
            col = one(db, "SELECT id, name FROM tdr_data_columns WHERE table_id=? AND tdr_fold(name)=tdr_fold(?)",
                      (candidates[0]["id"], column))
            if col:
                hit.update(column_id=col["id"], column=col["name"])
        out.append(hit)
    return out


def column_context(c):
    authz.check(c.principal, COLUMNS, "read")
    db = c.db
    col = crud.get(db, COLUMNS, c.params["id"])
    t = crud.get(db, TABLES, col["table_id"])
    source, eff = _effective(db, t)
    col["table"] = {k: t[k] for k in ("id", "schema_name", "name", "business_name", "description", "object_type",
                                      "classification", "status")}
    col["source"] = {k: source[k] for k in ("id", "code", "name", "platform")}
    col["effective"] = {**eff, "classification": col["classification"] or t["classification"],
                        "classification_from": "column" if col["classification"] else ("table" if t["classification"] else None)}
    col["terms"] = rows(db, """SELECT g.id, g.code, g.name, g.status, g.definition, g.format_rule, g.example,
        g.classification, g.personal_data FROM tdr_term_columns m JOIN tdr_glossary_terms g ON g.id=m.term_id
        WHERE m.column_id=? ORDER BY g.name""", (col["id"],))
    approved = [g for g in col["terms"] if g["status"] == "approved"] or col["terms"]
    col["meaning"] = {"name": col["business_name"] or (approved[0]["name"] if approved else None),
                      "text": col["description"] or (approved[0]["definition"] if approved else None) or col["technical_description"],
                      "from": "column" if col["description"] else ("term" if approved else (
                          "source" if col["technical_description"] else None))}
    col["references"] = _resolve_reference(db, source["id"], col["references_to"]) if col["references_to"] else []
    col["referenced_by"] = _referenced_by(db, source["id"], t["schema_name"], t["name"], col["name"])
    col["changes"] = rows(db, "SELECT * FROM tdr_catalog_changes WHERE column_id=? ORDER BY id DESC LIMIT 50", (col["id"],))
    try:
        crud.check_scope(db, COLUMNS, c.principal, col)
        col["can_edit"] = authz.can_write(c.principal, COLUMNS)
    except crud.Forbidden:
        col["can_edit"] = False
    return col


def source_context(c):
    authz.check(c.principal, SOURCES, "read")
    db = c.db
    s = crud.get(db, SOURCES, c.params["id"])
    s["domain"] = one(db, "SELECT id, code, name, owner, steward FROM tdr_data_domains WHERE id=?", (s["domain_id"],)) \
        if s["domain_id"] else None
    s["ci"] = one(db, "SELECT id, code, name, ci_class FROM tdr_cmdb_cis WHERE id=?", (s["ci_id"],)) if s["ci_id"] else None
    s["supplier"] = one(db, "SELECT id, code, name FROM tdr_suppliers WHERE id=?", (s["supplier_id"],)) if s["supplier_id"] else None
    s["processes"] = _processes(c, s["ci_id"])
    s["schemas"] = rows(db, f"""SELECT t.schema_name, COUNT(DISTINCT t.id) AS tables, COUNT(c.id) AS columns,
        SUM(CASE WHEN c.id IS NOT NULL AND {DOC} THEN 1 ELSE 0 END) AS documented,
        SUM(CASE WHEN c.personal_data IN ('personal','special') THEN 1 ELSE 0 END) AS personal
        FROM tdr_data_tables t LEFT JOIN tdr_data_columns c ON c.table_id=t.id AND c.status='active' {LINKED}
        WHERE t.source_id=? AND t.status<>'removed' GROUP BY t.schema_name ORDER BY t.schema_name""", (s["id"],))
    s["totals"] = {"tables": sum(x["tables"] for x in s["schemas"]), "columns": sum(x["columns"] for x in s["schemas"]),
                   "documented": sum(x["documented"] or 0 for x in s["schemas"]),
                   "personal": sum(x["personal"] or 0 for x in s["schemas"]),
                   "removed": one(db, "SELECT COUNT(*) AS n FROM tdr_data_tables WHERE source_id=? AND status='removed'",
                                  (s["id"],))["n"]}
    s["imports"] = rows(db, "SELECT * FROM tdr_catalog_imports WHERE source_id=? ORDER BY id DESC LIMIT 20", (s["id"],))
    for imp in s["imports"]:
        imp["summary"] = json.loads(imp.pop("summary_json") or "{}")
    s["changes"] = rows(db, "SELECT * FROM tdr_catalog_changes WHERE source_id=? ORDER BY id DESC LIMIT 50", (s["id"],))
    s["queries"] = QUERIES.get(s["platform"], []) + [GENERIC_QUERY]
    s["can_import"] = c.principal.can("manage") and c.principal.auth_type != "api_key"
    return s


# ------------------------------------------------------------------ listeler, arama, panolar

FILTERS = {
    "undocumented": f"""(EXISTS (SELECT 1 FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active'
        AND NOT {DOC_X}) OR (COALESCE(t.business_name,'')='' AND COALESCE(t.description,'')=''))""",
    "unowned": "COALESCE(t.owner, d.owner, pd.owner, s.owner) IS NULL",
    "personal": "EXISTS (SELECT 1 FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active' AND "
                "c.personal_data IN ('personal','special'))",
    "critical": "EXISTS (SELECT 1 FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active' AND c.is_critical=1)",
    "certified": "t.certified=1",
    "changed": "EXISTS (SELECT 1 FROM tdr_catalog_changes x WHERE x.table_id=t.id)",
}


def table_list(c):
    authz.check(c.principal, TABLES, "read")
    q = c.query
    where, args = [], []
    if q.get("source_id"):
        where.append("t.source_id=?")
        args.append(int(q["source_id"]))
    if "schema" in q:
        where.append("t.schema_name=?")
        args.append(q["schema"])
    if q.get("domain_id"):
        where.append("COALESCE(t.domain_id, s.domain_id)=?")
        args.append(int(q["domain_id"]))
    flt = q.get("filter") or ""
    if flt == "removed":
        where.append("t.status='removed'")
    else:
        where.append("t.status<>'removed'")
        if flt:
            if flt not in FILTERS:
                raise crud.Invalid("Bilinmeyen süzgeç")
            where.append(FILTERS[flt])
    if q.get("q"):
        pattern = "%" + re.sub(r"([\\%_])", r"\\\1", fold(q["q"])) + "%"
        where.append("(tdr_fold(t.name) LIKE ? ESCAPE '\\' OR tdr_fold(COALESCE(t.business_name,'')) LIKE ? ESCAPE '\\' "
                     "OR EXISTS (SELECT 1 FROM tdr_data_columns c WHERE c.table_id=t.id AND (tdr_fold(c.name) LIKE ? "
                     "ESCAPE '\\' OR tdr_fold(COALESCE(c.business_name,'')) LIKE ? ESCAPE '\\')))")
        args += [pattern] * 4
    base = f"FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE} WHERE " + " AND ".join(where)
    try:
        limit = max(1, min(int(q.get("limit", 50)), 200))
        offset = max(int(q.get("offset", 0)), 0)
    except ValueError:
        raise crud.Invalid("limit ve offset tamsayı olmalı") from None
    total = one(c.db, "SELECT COUNT(*) AS n " + base, args)["n"]
    items = rows(c.db, f"""SELECT t.id, t.source_id, t.schema_name, t.name, t.object_type, t.business_name, t.description,
        t.status, t.classification, t.certified, t.row_count, t.technical_description, s.code AS source_code,
        s.name AS source_name, s.platform, d.name AS domain_name, {EFF_COLS},
        (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active') AS column_count,
        (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active' AND {DOC_X}) AS documented_count,
        (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active'
         AND c.personal_data IN ('personal','special')) AS personal_count
        {base} ORDER BY s.name, t.schema_name, t.name LIMIT ? OFFSET ?""", (*args, limit, offset))
    return {"total": total, "items": items, "limit": limit, "offset": offset}


def search(c):
    """Katalog araması: terim, tablo ve kolon; kolon araması kaynağa veya şemaya göre daraltılabilir."""
    authz.check(c.principal, TABLES, "read")
    text = (c.query.get("q") or "").strip()
    if len(text) < 2:
        return {"terms": [], "tables": [], "columns": []}
    pattern = "%" + re.sub(r"([\\%_])", r"\\\1", fold(text)) + "%"
    kind = c.query.get("kind") or "all"
    out = {"terms": [], "tables": [], "columns": []}
    if kind in ("all", "terms"):
        out["terms"] = rows(c.db, """SELECT id, code, name, abbreviation, status, definition FROM tdr_glossary_terms WHERE
            tdr_fold(name) LIKE ? ESCAPE '\\' OR tdr_fold(COALESCE(abbreviation,'')) LIKE ? ESCAPE '\\' OR
            tdr_fold(COALESCE(synonyms,'')) LIKE ? ESCAPE '\\' OR tdr_fold(code) LIKE ? ESCAPE '\\'
            ORDER BY CASE status WHEN 'approved' THEN 0 WHEN 'in_review' THEN 1 WHEN 'draft' THEN 2 ELSE 3 END, name LIMIT 20""",
                            [pattern] * 4)
    extra, args = "", []
    if c.query.get("source_id"):
        extra, args = " AND t.source_id=?", [int(c.query["source_id"])]
    if kind in ("all", "tables"):
        out["tables"] = rows(c.db, f"""SELECT t.id, t.schema_name, t.name, t.business_name, t.object_type, s.code AS source_code,
            s.name AS source_name FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id WHERE t.status<>'removed'
            AND (tdr_fold(t.name) LIKE ? ESCAPE '\\' OR tdr_fold(COALESCE(t.business_name,'')) LIKE ? ESCAPE '\\'){extra}
            ORDER BY t.name LIMIT 20""", [pattern, pattern, *args])
    if kind in ("all", "columns"):
        out["columns"] = rows(c.db, f"""SELECT c.id, c.name, c.business_name, c.data_type, c.personal_data, t.id AS table_id,
            t.schema_name, t.name AS table_name, s.code AS source_code, s.name AS source_name FROM tdr_data_columns c
            JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources s ON s.id=t.source_id
            WHERE c.status='active' AND (tdr_fold(c.name) LIKE ? ESCAPE '\\' OR tdr_fold(COALESCE(c.business_name,''))
            LIKE ? ESCAPE '\\'){extra} ORDER BY c.name LIMIT {50 if kind == 'columns' else 20}""", [pattern, pattern, *args])
    return out


TR_ORDER = "abcçdefgğhıijklmnoöprsştuüvyz"


def tr_key(text):
    """Türkçe alfabe sırası (Ç, Ğ, I/İ, Ö, Ş, Ü yerinde)."""
    low = str(text or "").replace("I", "ı").replace("İ", "i").lower()
    return [0 if ch == " " else (TR_ORDER.index(ch) + 10 if ch in TR_ORDER else ord(ch) + 100) for ch in low]


def tr_initial(text):
    ch = str(text or " ").strip()[:1]
    return {"i": "İ", "ı": "I"}.get(ch, ch.upper())


def glossary_list(c):
    """Sözlük ekranı: durum, veri alanı, baş harf ve metinle süzme; kullanım sayıları ve bekleyen değişiklik."""
    authz.check(c.principal, TERMS, "read")
    q = c.query
    where, args = [], []
    status = q.get("status") or ""
    if status == "pending":
        where.append("g.pending_json IS NOT NULL")
    elif status:
        if status not in TERMS.enums["status"]:
            raise crud.Invalid("Bilinmeyen durum")
        where.append("g.status=?")
        args.append(status)
    else:
        where.append("g.status<>'retired'")
    if q.get("domain_id"):
        where.append("g.domain_id=?")
        args.append(int(q["domain_id"]))
    if q.get("q"):
        pattern = "%" + re.sub(r"([\\%_])", r"\\\1", fold(q["q"])) + "%"
        where.append("(tdr_fold(g.name) LIKE ? ESCAPE '\\' OR tdr_fold(COALESCE(g.abbreviation,'')) LIKE ? ESCAPE '\\' OR "
                     "tdr_fold(COALESCE(g.synonyms,'')) LIKE ? ESCAPE '\\' OR tdr_fold(g.definition) LIKE ? ESCAPE '\\' OR "
                     "tdr_fold(g.code) LIKE ? ESCAPE '\\')")
        args += [pattern] * 5
    items = rows(c.db, f"""SELECT g.id, g.code, g.name, g.abbreviation, g.synonyms, g.definition, g.status, g.version,
        g.owner, g.steward, g.domain_id, g.review_date, g.personal_data, g.is_critical, d.name AS domain_name,
        CASE WHEN g.pending_json IS NULL THEN 0 ELSE 1 END AS has_pending,
        (SELECT COUNT(*) FROM tdr_term_columns m WHERE m.term_id=g.id) AS column_count,
        (SELECT COUNT(*) FROM tdr_term_tables m WHERE m.term_id=g.id) AS table_count
        FROM tdr_glossary_terms g LEFT JOIN tdr_data_domains d ON d.id=g.domain_id
        {('WHERE ' + ' AND '.join(where)) if where else ''} LIMIT 5000""", args)
    letters = sorted({tr_initial(r["name"]) for r in items}, key=tr_key)
    if q.get("letter"):
        items = [r for r in items if tr_initial(r["name"]) == q["letter"][:1]]
    items.sort(key=lambda r: tr_key(r["name"]))
    counts = {r["status"]: r["n"] for r in rows(c.db, "SELECT status, COUNT(*) AS n FROM tdr_glossary_terms GROUP BY status")}
    counts["pending"] = one(c.db, "SELECT COUNT(*) AS n FROM tdr_glossary_terms WHERE pending_json IS NOT NULL")["n"]
    return {"items": items[:1000], "counts": counts, "letters": letters}


def overview(c):
    authz.check(c.principal, TABLES, "read")
    db = c.db
    col = one(db, f"""SELECT COUNT(*) AS columns, SUM(CASE WHEN {DOC} THEN 1 ELSE 0 END) AS documented,
        SUM(CASE WHEN c.personal_data IN ('personal','special') THEN 1 ELSE 0 END) AS personal,
        SUM(CASE WHEN c.personal_data='special' THEN 1 ELSE 0 END) AS special,
        SUM(CASE WHEN c.is_critical=1 THEN 1 ELSE 0 END) AS critical,
        SUM(CASE WHEN c.personal_data IS NULL THEN 1 ELSE 0 END) AS unassessed
        FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id {LINKED}
        WHERE c.status='active' AND t.status<>'removed'""")
    tab = one(db, f"""SELECT COUNT(*) AS tables, SUM(CASE WHEN COALESCE(t.owner, d.owner, pd.owner, s.owner) IS NOT NULL
        THEN 1 ELSE 0 END) AS owned, SUM(CASE WHEN COALESCE(t.steward, d.steward, pd.steward, s.steward) IS NOT NULL
        THEN 1 ELSE 0 END) AS stewarded, SUM(CASE WHEN t.certified=1 THEN 1 ELSE 0 END) AS certified
        FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE} WHERE t.status<>'removed'""")
    terms = {r["status"]: r["n"] for r in rows(db, "SELECT status, COUNT(*) AS n FROM tdr_glossary_terms GROUP BY status")}
    pending = one(db, "SELECT COUNT(*) AS n FROM tdr_glossary_terms WHERE pending_json IS NOT NULL")["n"]
    sources = rows(db, f"""SELECT s.id, s.code, s.name, s.platform, s.environment, s.last_import_at,
        COUNT(DISTINCT t.id) AS tables, COUNT(c.id) AS columns, SUM(CASE WHEN c.id IS NOT NULL AND {DOC} THEN 1 ELSE 0 END)
        AS documented FROM tdr_data_sources s LEFT JOIN tdr_data_tables t ON t.source_id=s.id AND t.status<>'removed'
        LEFT JOIN tdr_data_columns c ON c.table_id=t.id AND c.status='active' {LINKED} WHERE s.status='active'
        GROUP BY s.id, s.code, s.name, s.platform, s.environment, s.last_import_at ORDER BY s.name""")
    domains = rows(db, f"""SELECT d.id, d.code, d.name, d.owner, d.steward,
        (SELECT COUNT(*) FROM tdr_glossary_terms g WHERE g.domain_id=d.id AND g.status='approved') AS terms,
        (SELECT COUNT(*) FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id WHERE t.status<>'removed'
         AND COALESCE(t.domain_id, s.domain_id)=d.id) AS tables FROM tdr_data_domains d WHERE d.active=1 ORDER BY d.name""")
    attention = {
        "terms_to_review": rows(db, """SELECT id, code, name, status, submitted_by, submitted_at, pending_by, pending_at
            FROM tdr_glossary_terms WHERE status='in_review' OR pending_json IS NOT NULL ORDER BY
            COALESCE(pending_at, submitted_at) LIMIT 10"""),
        "unowned_tables": rows(db, f"""SELECT t.id, t.schema_name, t.name, s.name AS source_name,
            (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active') AS column_count
            FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE} WHERE t.status<>'removed'
            AND {FILTERS['unowned']} ORDER BY column_count DESC, t.name LIMIT 10"""),
        "personal_unclassified": rows(db, """SELECT c.id, c.name, t.id AS table_id, t.schema_name, t.name AS table_name,
            s.name AS source_name FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources s
            ON s.id=t.source_id WHERE c.status='active' AND t.status<>'removed' AND c.personal_data IN ('personal','special')
            AND COALESCE(c.classification, t.classification, 'public') IN ('public','internal') ORDER BY t.name, c.name LIMIT 10"""),
        "review_overdue": rows(db, """SELECT id, code, name, owner, review_date FROM tdr_glossary_terms WHERE
            status='approved' AND review_date < ? ORDER BY review_date LIMIT 10""", (_today(),)),
    }
    return {
        "totals": {"sources": len(sources), "domains": len(domains), "tables": tab["tables"] or 0,
                   "columns": col["columns"] or 0, "terms": sum(terms.values()), "approved_terms": terms.get("approved", 0)},
        "coverage": {"documented": col["documented"] or 0, "columns": col["columns"] or 0, "owned": tab["owned"] or 0,
                     "stewarded": tab["stewarded"] or 0, "tables": tab["tables"] or 0, "certified": tab["certified"] or 0,
                     "personal": col["personal"] or 0, "special": col["special"] or 0, "critical": col["critical"] or 0,
                     "unassessed": col["unassessed"] or 0},
        "terms": {"draft": terms.get("draft", 0), "in_review": terms.get("in_review", 0), "approved": terms.get("approved", 0),
                  "retired": terms.get("retired", 0), "pending_changes": pending},
        "sources": sources, "domains": domains, "attention": attention,
        "changes": rows(db, """SELECT x.*, s.name AS source_name FROM tdr_catalog_changes x JOIN tdr_data_sources s
            ON s.id=x.source_id ORDER BY x.id DESC LIMIT 15"""),
        "imports": rows(db, """SELECT i.id, i.source_id, i.kind, i.format, i.filename, i.created_by, i.created_at,
            s.name AS source_name FROM tdr_catalog_imports i JOIN tdr_data_sources s ON s.id=i.source_id
            ORDER BY i.id DESC LIMIT 8"""),
    }


def stewardship(c):
    """Sahiplik matrisi: kişi bazında doğrudan atamalar (veri alanı, kaynak, tablo, terim) ve sahipsiz varlıklar."""
    authz.check(c.principal, TABLES, "read")
    db = c.db
    people = {}

    def add(person, role, kind, n=1):
        if not person:
            return
        p = people.setdefault(person, {"person": person, "owner": Counter(), "steward": Counter(), "custodian": Counter()})
        p[role][kind] += n
    for d in rows(db, "SELECT owner, steward FROM tdr_data_domains WHERE active=1"):
        add(d["owner"], "owner", "domains")
        add(d["steward"], "steward", "domains")
    for s in rows(db, "SELECT owner, steward, custodian FROM tdr_data_sources WHERE status='active'"):
        add(s["owner"], "owner", "sources")
        add(s["steward"], "steward", "sources")
        add(s["custodian"], "custodian", "sources")
    for role in ("owner", "steward", "custodian"):
        for r in rows(db, f"SELECT {role} AS person, COUNT(*) AS n FROM tdr_data_tables WHERE status<>'removed' AND "
                          f"{role} IS NOT NULL GROUP BY {role}"):
            add(r["person"], role, "tables", r["n"])
    for role in ("owner", "steward"):
        for r in rows(db, f"SELECT {role} AS person, COUNT(*) AS n FROM tdr_glossary_terms WHERE status<>'retired' AND "
                          f"{role} IS NOT NULL GROUP BY {role}"):
            add(r["person"], role, "terms", r["n"])
    matrix = sorted(({**p, **{k: dict(p[k]) for k in ("owner", "steward", "custodian")}} for p in people.values()),
                    key=lambda p: fold(p["person"]))
    domains = rows(db, """SELECT d.id, d.code, d.name, d.owner, d.steward, d.parent_id, u.name AS org_unit,
        (SELECT name FROM tdr_data_domains x WHERE x.id=d.parent_id) AS parent_name FROM tdr_data_domains d
        LEFT JOIN tdr_org_units u ON u.id=d.org_unit_id WHERE d.active=1 ORDER BY d.name""")
    sources = rows(db, """SELECT s.id, s.code, s.name, s.platform, s.owner, s.steward, s.custodian, d.name AS domain_name
        FROM tdr_data_sources s LEFT JOIN tdr_data_domains d ON d.id=s.domain_id WHERE s.status='active' ORDER BY s.name""")
    unowned = one(db, f"""SELECT COUNT(*) AS n FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE}
        WHERE t.status<>'removed' AND {FILTERS['unowned']}""")["n"]
    no_steward = one(db, f"""SELECT COUNT(*) AS n FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id
        {EFFECTIVE} WHERE t.status<>'removed' AND COALESCE(t.steward, d.steward, pd.steward, s.steward) IS NULL""")["n"]
    return {"people": matrix, "domains": domains, "sources": sources, "unowned_tables": unowned,
            "tables_without_steward": no_steward}


BULK_TABLE = {"owner", "steward", "custodian", "classification", "domain_id", "certified", "status"}
BULK_COLUMN = {"classification", "personal_data", "is_critical"}


def bulk_update(c):
    """Seçilen tablolara veya kolonlara aynı değeri yazar (ör. sahip ataması, sınıf, kişisel veri). Her kayıt kendi
    yazma kurallarından ve kapsamından geçer; hata veren kayıt atlanır ve bildirilir."""
    authz.require_human(c.principal)
    values = c.body.get("set")
    if not isinstance(values, dict) or not values:
        raise crud.Invalid("Yazılacak değerleri seçin")
    out = {"updated": 0, "errors": []}
    for key, res, allowed in (("table_ids", TABLES, BULK_TABLE), ("column_ids", COLUMNS, BULK_COLUMN)):
        ids = _ids(c.body.get(key), key)
        if not ids:
            continue
        if set(values) - allowed:
            raise crud.Invalid("Toplu güncellenemeyen alan: " + ", ".join(sorted(set(values) - allowed)))
        authz.check(c.principal, res, "write")
        for record_id in ids[:1000]:
            try:
                with c.db.savepoint():
                    crud.update(c.db, res, record_id, dict(values), c.principal)
                    audit.log(c.db, c.principal, "UPDATE", res.name, record_id, {**values, "bulk": True})
                out["updated"] += 1
            except (crud.Invalid, crud.Forbidden, crud.NotFound) as exc:
                if len(out["errors"]) < 50:
                    out["errors"].append({"id": record_id, "message": str(exc)})
    if not out["updated"] and not out["errors"]:
        raise crud.Invalid("Kayıt seçilmedi")
    return out


def adopt_descriptions(c):
    """Kaynaktaki açıklamayı (SAP metni, yorum, Dynamics etiketi) iş açıklaması olarak benimser; yalnızca boş olanlar."""
    t = crud.get(c.db, TABLES, c.params["id"])
    _writable(c, TABLES, t)
    now, n = utcnow(), 0
    for col in rows(c.db, """SELECT id, technical_description FROM tdr_data_columns WHERE table_id=? AND status='active'
            AND COALESCE(description,'')='' AND COALESCE(technical_description,'')<>''""", (t["id"],)):
        c.db.execute("UPDATE tdr_data_columns SET description=?, updated_at=? WHERE id=?",
                     (col["technical_description"], now, col["id"]))
        n += 1
    if not t["description"] and t["technical_description"]:
        c.db.execute("UPDATE tdr_data_tables SET description=?, updated_at=? WHERE id=?", (t["technical_description"], now, t["id"]))
        n += 1
    audit.log(c.db, c.principal, "ADOPT_DESCRIPTIONS", "data_tables", t["id"], {"count": n})
    return {"adopted": n}


# ------------------------------------------------------------------ İşlerim, takvim, sağlık kontrolü

def my_work_items(db, principal):
    me = _me(principal)
    names = sorted(me)
    marks = ",".join("?" * len(names))
    out = {}
    candidates = rows(db, """SELECT id, code, name, owner, domain_id, status, submitted_by, pending_by, submitted_at,
        pending_at FROM tdr_glossary_terms WHERE status='in_review' OR pending_json IS NOT NULL ORDER BY id""")
    out["glossary_to_approve"] = [
        {"id": t["id"], "code": t["code"], "title": t["name"], "kind": "change" if t["status"] == "approved" else "new",
         "proposer": t["pending_by"] if t["status"] == "approved" else t["submitted_by"]}
        for t in candidates if can_approve(db, principal, t, t["pending_by"] if t["status"] == "approved" else t["submitted_by"])]
    out["glossary_returned"] = rows(db, f"""SELECT id, code, name AS title, review_note FROM tdr_glossary_terms WHERE
        status='draft' AND review_note IS NOT NULL AND (created_by IN ({marks}) OR submitted_by IN ({marks}))""", (*names, *names))
    soon = (date.today() + timedelta(days=30)).isoformat()
    out["glossary_review"] = rows(db, f"""SELECT id, code, name AS title, review_date FROM tdr_glossary_terms WHERE
        status='approved' AND owner IN ({marks}) AND review_date <= ? ORDER BY review_date""", (*names, soon))
    return out


def calendar_events(db):
    return rows(db, "SELECT id, code, name, review_date FROM tdr_glossary_terms WHERE status='approved' AND review_date IS NOT NULL")


def health_checks(db, check, count):
    population = count(db, "SELECT COUNT(*) AS n FROM tdr_data_tables WHERE status<>'removed'")
    personal = count(db, "SELECT COUNT(*) AS n FROM tdr_data_columns WHERE status='active' AND personal_data IN ('personal','special')")
    stale = (date.today() - timedelta(days=14)).isoformat()
    return [
        check("data_tables_no_owner", "Sahibi olmayan veri tabloları",
              "Veri sahibi olmayan tabloda tanım, sınıf ve erişim kararını verecek kişi belirsizdir (DAMA-DMBOK: veri sahipliği).",
              "medium", rows(db, f"""SELECT t.id, s.code, CASE WHEN t.schema_name='' THEN t.name ELSE t.schema_name || '.' || t.name END AS title
              FROM tdr_data_tables t
              JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE} WHERE t.status<>'removed' AND {FILTERS['unowned']}
              ORDER BY t.name LIMIT 200"""), "data_tables", link="stewardship", population=population),
        check("personal_low_class", "'Gizli' sınıfın altında kalan kişisel veri kolonları",
              "Kişisel veri en az 'Gizli' sınıfında korunmalı; sınıf erişim ve maskeleme kararlarını belirler (KVKK md. 12).",
              "high", rows(db, """SELECT c.id, t.name AS code, c.name AS title FROM tdr_data_columns c JOIN tdr_data_tables t
              ON t.id=c.table_id WHERE c.status='active' AND t.status<>'removed' AND c.personal_data IN ('personal','special')
              AND COALESCE(c.classification, t.classification, 'public') IN ('public','internal') ORDER BY t.name, c.name
              LIMIT 200"""), "data_columns", population=personal),
        check("glossary_review_stale", "14 günden uzun süredir onay bekleyen sözlük terimleri",
              "Bekleyen terimler kullanıcıları tanımsız bırakır; onaylayan kişi atanmamış olabilir.", "low",
              rows(db, """SELECT id, code, name AS title FROM tdr_glossary_terms WHERE (status='in_review' AND submitted_at < ?)
              OR (pending_json IS NOT NULL AND pending_at < ?) ORDER BY code""", (stale, stale)), "glossary_terms",
              population=count(db, "SELECT COUNT(*) AS n FROM tdr_glossary_terms WHERE status<>'retired'")),
    ]


# ------------------------------------------------------------------ kayıt

def register(app):
    app.route("GET", API + "/datagov/overview", overview)
    app.route("GET", API + "/datagov/search", search)
    app.route("GET", API + "/datagov/glossary", glossary_list)
    app.route("GET", API + "/datagov/tables", table_list)
    app.route("GET", API + "/datagov/stewardship", stewardship)
    app.route("GET", API + "/datagov/queries", queries)
    app.route("POST", API + "/datagov/bulk", bulk_update)
    app.route("GET", API + "/data_sources/{id}/context", source_context)
    app.route("POST", API + "/data_sources/{id}/import", import_structure, max_body=MAX_UPLOAD_BODY)
    app.route("POST", API + "/data_sources/{id}/import-descriptions", import_descriptions, max_body=MAX_UPLOAD_BODY)
    app.route("GET", API + "/data_sources/{id}/export", export_catalog)
    app.route("GET", API + "/data_tables/{id}/context", table_context)
    app.route("POST", API + "/data_tables/{id}/adopt-descriptions", adopt_descriptions)
    app.route("GET", API + "/data_columns/{id}/context", column_context)
    app.route("POST", API + "/data_columns/{id}/terms", column_terms)
    app.route("GET", API + "/glossary_terms/{id}/context", term_context)
    app.route("POST", API + "/glossary_terms/{id}/submit", term_submit)
    app.route("POST", API + "/glossary_terms/{id}/withdraw", term_withdraw)
    app.route("POST", API + "/glossary_terms/{id}/approve", term_approve)
    app.route("POST", API + "/glossary_terms/{id}/reject", term_reject)
    app.route("POST", API + "/glossary_terms/{id}/propose", term_propose)
    app.route("POST", API + "/glossary_terms/{id}/retire", term_retire)
    app.route("POST", API + "/glossary_terms/{id}/links", term_links)
    app.route("POST", API + "/glossary_terms/{id}/related", term_related)
