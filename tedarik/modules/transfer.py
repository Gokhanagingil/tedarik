"""Veri aktarımı: içe aktarma hattı ve dışa aktarma.

Hat: oku -> başlıkları kanonik alanlara eşle -> her satırı mevcut kayıtla eşleştir -> uygula.
Eşleştirme sırası: (kaynak sistem, harici kimlik) -> VKN -> ad benzerliği (yalnızca uyarı, otomatik birleştirmez).
Kaynak sistem verisi portalda elle girilmiş dolu alanı ezmez; yalnızca boş alanları doldurur.
Excel dosyaları, MCP ve ileride konnektörler aynı hattı kullanır.
"""
import base64
import binascii
import csv
import io
import json
import re

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, Raw
from ..schema import RESOURCES, Resource, fk

M = "transfer"
SOURCES = ("sap", "crm", "outsourcing", "servicenow", "manual")
FOLD = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")

# Kanonik alan -> kabul edilen kaynak başlıkları (katlanmış: küçük harf, Türkçe karaktersiz).
# SAP (LFA1) ve Dynamics başlıkları varsayımdır; gerçek dışa aktarımlarla doğrulanacak.
ALIASES = {
    "external_id": ("external_id", "lifnr", "accountnumber", "tedarikci no", "satici no", "hesap no", "kod"),
    "name": ("name", "name1", "tedarikci adi", "tedarikci", "unvan", "firma adi", "firma"),
    "tax_id": ("tax_id", "stcd2", "vkn", "vergi no", "vergi numarasi"),
    "country": ("country", "land1", "ulke", "address1_country"),
    "city": ("city", "ort01", "sehir", "il", "address1_city"),
    "tier": ("tier", "kritiklik", "seviye"),
    "status": ("status", "durum"),
    "owner": ("owner", "sahip", "iliski sahibi", "sorumlu"),
    "website": ("website", "web", "websiteurl"),
}
LOOKUP = {alias: field for field, names in ALIASES.items() for alias in names}

BATCHES = Resource("import_batches", "İçe Aktarım Kayıtları", {
    "kind": "TEXT NOT NULL", "source_system": "TEXT NOT NULL", "filename": "TEXT NOT NULL",
    "status": "TEXT NOT NULL", "summary_json": "TEXT", "created_by": "TEXT NOT NULL", "created_at": "TEXT NOT NULL"},
    module=M, api=("list", "get"), search=("filename", "source_system"))

Resource("import_rows", "İçe Aktarım Satırları", {
    "batch_id": fk("import_batches", cascade=True), "row_no": "INTEGER NOT NULL", "payload_json": "TEXT NOT NULL",
    "action": "TEXT NOT NULL", "message": "TEXT", "target_id": "INTEGER"},
    module=M, api=("list",), search=("action", "message"))


def fold(text):
    return " ".join(str(text or "").translate(FOLD).lower().split())


def norm_name(name):
    """Ad benzerliği için: noktalama ve yaygın şirket eklerini atar ('ABC Bilişim A.Ş.' ~ 'abc bilisim')."""
    words = re.sub(r"[^a-z0-9 ]", " ", fold(name).replace(".", "")).split()
    return " ".join(w for w in words if w not in {"as", "ltd", "sti", "san", "tic", "ve", "inc", "llc", "gmbh"})


def read_table(filename, raw):
    """Dosyayı (başlıklar, satır sözlükleri) olarak okur. XLSX desteği KS GRC xlsx_io aktarılınca eklenecek."""
    if filename.lower().endswith(".xlsx"):
        raise crud.Invalid("XLSX içe aktarımı henüz açık değil; Excel'den 'CSV UTF-8' olarak kaydedip yükleyin")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise crud.Invalid("Dosya UTF-8 olmalı")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    if not reader.fieldnames:
        raise crud.Invalid("Dosyada başlık satırı yok")
    return reader.fieldnames, list(reader)


def _next_code(db):
    return f"TDR-{one(db, 'SELECT COALESCE(MAX(id), 0) + 1 AS n FROM tdr_suppliers')['n']:05d}"


def import_suppliers(c):
    authz.require(c.principal, "manage")
    source, filename = c.body["source_system"], str(c.body["filename"])
    if source not in SOURCES:
        raise crud.Invalid("source_system: " + " | ".join(SOURCES))
    try:
        raw = base64.b64decode(c.body["content_base64"], validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise crud.Invalid("content_base64 geçerli base64 olmalı")
    dry_run = bool(c.body.get("dry_run", False))
    headers, records = read_table(filename, raw)
    mapping = {h: LOOKUP[fold(h)] for h in headers if fold(h) in LOOKUP}
    if "name" not in mapping.values():
        raise crud.Invalid("Tedarikçi adı sütunu bulunamadı. Tanınan başlıklar: " + ", ".join(ALIASES["name"]))
    if len(records) > 5000:
        raise crud.Invalid("Tek seferde en fazla 5000 satır aktarılabilir")
    suppliers = RESOURCES["suppliers"]
    known = {norm_name(s["name"]): s["id"] for s in rows(c.db, "SELECT id, name FROM tdr_suppliers")}
    batch_id = crud.insert(c.db, BATCHES, {"kind": "suppliers", "source_system": source, "filename": filename,
                                           "status": "dry_run" if dry_run else "applied",
                                           "created_by": c.principal.username})
    summary = {"total": 0, "create": 0, "update": 0, "review": 0, "error": 0}
    for row_no, record in enumerate(records, start=2):
        row = {mapping[h]: (v or "").strip() for h, v in record.items() if h in mapping and (v or "").strip()}
        if not row:
            continue
        summary["total"] += 1
        action, target, message = "create", None, None
        try:
            if not row.get("name"):
                raise crud.Invalid("Tedarikçi adı boş")
            ref = one(c.db, "SELECT supplier_id FROM tdr_source_refs WHERE source_system=? AND external_id=?",
                      (source, row["external_id"])) if row.get("external_id") else None
            by_tax = one(c.db, "SELECT id FROM tdr_suppliers WHERE tax_id=?", (row["tax_id"],)) \
                if row.get("tax_id") else None
            if ref or by_tax:
                action, target = "update", (ref["supplier_id"] if ref else by_tax["id"])
            elif norm_name(row["name"]) in known:
                action, target = "review", known[norm_name(row["name"])]
                message = "Aynı ada sahip tedarikçi var; VKN veya harici kimlikle doğrulayın"
            if not dry_run and action != "review":
                fields = {k: v for k, v in row.items() if k != "external_id"}
                if action == "create":
                    target = crud.insert(c.db, suppliers, {"code": _next_code(c.db), **fields})
                    known[norm_name(row["name"])] = target
                else:
                    current = crud.get(c.db, suppliers, target)
                    fill = {k: v for k, v in fields.items() if current.get(k) is None}
                    if fill:
                        crud.update(c.db, suppliers, target, fill)
                if row.get("external_id"):
                    c.db.execute("""INSERT INTO tdr_source_refs (supplier_id, source_system, external_id,
                        external_name, last_seen_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(source_system, external_id) DO UPDATE SET
                        external_name=excluded.external_name, last_seen_at=excluded.last_seen_at""",
                                 (target, source, row["external_id"], row["name"], utcnow()))
        except (ValueError, LookupError) as exc:
            action, message = "error", str(exc)
        summary[action] += 1
        c.db.execute("INSERT INTO tdr_import_rows (batch_id, row_no, payload_json, action, message, target_id) "
                     "VALUES (?,?,?,?,?,?)",
                     (batch_id, row_no, json.dumps(row, ensure_ascii=False), action, message, target))
    summary["unmapped_columns"] = [h for h in headers if h not in mapping]
    c.db.execute("UPDATE tdr_import_batches SET summary_json=? WHERE id=?",
                 (json.dumps(summary, ensure_ascii=False), batch_id))
    audit.log(c.db, c.principal, "IMPORT", "suppliers", batch_id, {**summary, "dry_run": dry_run})
    return 201, {"batch_id": batch_id, "dry_run": dry_run, **summary}


def _safe_cell(value):
    """Elektronik tablo formül enjeksiyonuna karşı: =, +, -, @ ile başlayan metin tırnakla etkisizleştirilir."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not isinstance(value, (int, float)) else text


def exporter(res):
    def export(c):
        authz.require(c.principal, "manage")
        authz.check(c.principal, res, "read")
        records = rows(c.db, f"SELECT * FROM {res.table} ORDER BY id")
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
        writer.writerow(["id", *res.fields])
        for record in records:
            writer.writerow([_safe_cell(record.get(col)) for col in ["id", *res.fields]])
        audit.log(c.db, c.principal, "EXPORT", res.name, None, {"rows": len(records)})
        return 200, Raw("\ufeff" + out.getvalue(), "text/csv; charset=utf-8", f"{res.name}.csv")
    return export


def register(app):
    app.route("POST", API + "/import/suppliers", import_suppliers)
    for res in RESOURCES.values():
        if app.enabled(res.module) and "list" in res.api and res.name not in ("audit_log", "import_rows"):
            app.route("GET", f"{API}/export/{res.name}", exporter(res))
