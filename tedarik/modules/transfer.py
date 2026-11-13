"""Veri aktarımı: içe aktarma hattı, içe aktarma şablonları, dışa aktarma (K-007).

Hat: oku (XLSX veya CSV) -> başlıkları kanonik alanlara eşle -> her satırı mevcut kayıtla eşleştir -> uygula.
- Başlıklar: alan adı, Türkçe etiket (labels.py) veya kaynak sistem takma adı (ALIASES) kabul edilir;
  büyük/küçük harf ve Türkçe karakter farkı önemsizdir; şablondaki `*` (zorunlu) işareti yok sayılır.
- Seçim alanlarında kod (`critical`) veya Türkçe etiket (`Kritik`) kabul edilir.
- İlişkiler kodla verilir (ör. angajmanda tedarikçi kodu). Kimlik numarası veritabanına özgüdür, taşınmaz.
- Var olan kayıtta yalnızca boş alanlar doldurulur; portalda girilmiş değer ezilmez.
- Her satır kendi geri alma noktasında işlenir; hatalı satır diğerlerini bozmaz, sonuç satır bazında saklanır.
- `dry_run` ile önce sonuç görülür; deneme veri yazmaz ama kayıt bırakır.
Tedarikçilerde ek eşleştirme: (kaynak sistem, harici kimlik) -> kod -> VKN -> ad benzerliği (yalnızca
"inceleme", otomatik birleştirmez). Excel, MCP ve ileride konnektörler aynı hattı kullanır.

XLSX okuma ve yazma KS GRC `xlsx_io.py` kopyasıyla (defusedxml, formül ve makro reddi, boyut sınırları).
"""
import base64
import binascii
import csv
import io
import json
import re
from collections import OrderedDict
from datetime import date, timedelta

from .. import audit, auth as authz, crud
from ..db import IntegrityError, fold as fold_letters, one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY, Raw
from ..labels import CHOICES, choice, field
from ..schema import RESOURCES, Resource, fk

M = "transfer"
SOURCES = ("sap", "crm", "outsourcing", "servicenow", "manual")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ROWS = 5000

# Kaynak sistem başlıkları. SAP (LFA1) ve Dynamics başlıkları varsayımdır; gerçek dışa aktarımlarla
# doğrulanacak (DURUM.md, "Gökhan Bey'den beklenenler").
ALIASES = {
    "external_id": ("external_id", "lifnr", "accountnumber", "tedarikci no", "satici no", "hesap no",
                    "harici kimlik"),
    "name": ("name1", "tedarikci adi", "tedarikci", "unvan", "firma adi", "firma"),
    "tax_id": ("stcd2", "vkn", "vergi no", "vergi numarasi"),
    "country": ("land1", "ulke", "address1_country"),
    "city": ("ort01", "sehir", "il", "address1_city"),
    "tier": ("kritiklik", "seviye"),
    "owner": ("sahip", "iliski sahibi", "sorumlu"),
    "website": ("web", "websiteurl"),
}

# Genel içe aktarma: kaynak -> doğal anahtar alanları. İlişki alanları hedef kaydın koduyla verilir.
IMPORTABLE = OrderedDict([
    ("org_units", ("code",)),
    ("supplier_types", ("code",)),
    ("catalog_items", ("code",)),
    ("suppliers", ("name",)),
    ("engagements", ("code",)),
    ("contracts", ("code",)),
    ("sla_definitions", ("engagement_id", "code")),
])
EXPORT_ORDER = ("org_units", "supplier_types", "catalog_items", "suppliers", "supplier_contacts", "source_refs",
                "engagements", "responsibilities", "contracts", "sla_definitions", "sla_measurements",
                "performance_events", "supplier_risks", "risk_actions")

BATCHES = Resource("import_batches", "İçe Aktarım Kayıtları", {
    "kind": "TEXT NOT NULL", "source_system": "TEXT NOT NULL", "filename": "TEXT NOT NULL",
    "status": "TEXT NOT NULL", "summary_json": "TEXT", "created_by": "TEXT NOT NULL",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list", "get"), search=("filename", "source_system"), write="manage")

Resource("import_rows", "İçe Aktarım Satırları", {
    "batch_id": fk("import_batches", cascade=True), "row_no": "INTEGER NOT NULL", "payload_json": "TEXT NOT NULL",
    "action": "TEXT NOT NULL", "message": "TEXT", "target_id": "INTEGER"},
    module=M, api=("list",), search=("action", "message"), immutable=True, write="manage")


def fold(text):
    return " ".join(fold_letters(text).split())


def norm_name(name):
    """Ad benzerliği için: noktalama ve yaygın şirket eklerini atar ('ABC Bilişim A.Ş.' ~ 'abc bilisim')."""
    words = re.sub(r"[^a-z0-9 ]", " ", fold(name).replace(".", "")).split()
    return " ".join(w for w in words if w not in {"as", "ltd", "sti", "san", "tic", "ve", "inc", "llc", "gmbh"})


def _xlsx():
    try:
        from ..vendor import xlsx_io
    except ImportError:          # pragma: no cover - paketsiz kurulum
        raise crud.Invalid("XLSX için defusedxml kurulmalı (requirements.txt); CSV kullanabilirsiniz") from None
    return xlsx_io


def read_table(filename, raw):
    """Dosyayı (başlıklar, satır sözlükleri) olarak okur. XLSX'te 'Açıklama' sayfası atlanır, ilk veri sayfası alınır."""
    if filename.lower().endswith(".xlsx"):
        sheets = _xlsx().read_xlsx(raw)
        data = [table for name, table in sheets.items() if fold(name) not in ("aciklama", "alanlar")]
        if not data or not data[0]:
            raise crud.Invalid("Excel dosyasında veri sayfası yok")
        table = [[str(v) for v in r] for r in data[0]]
        headers = [h.strip() for h in table[0]]
        records = [{h: (r[i] if i < len(r) else "") for i, h in enumerate(headers) if h}
                   for r in table[1:] if any(str(v).strip() for v in r)]
        return [h for h in headers if h], records
    if not filename.lower().endswith((".csv", ".txt")):
        raise crud.Invalid("Dosya türü .xlsx veya .csv olmalı")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise crud.Invalid("CSV dosyası UTF-8 olmalı (Excel'de 'CSV UTF-8' olarak kaydedin)") from None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text, newline=""), dialect=dialect)
    if not reader.fieldnames:
        raise crud.Invalid("Dosyada başlık satırı yok")
    return reader.fieldnames, list(reader)


def _decode(c):
    filename = c.body.get("filename")
    if not isinstance(filename, str) or not filename.strip() or len(filename) > 200:
        raise crud.Invalid("filename gerekli")
    try:
        raw = base64.b64decode(c.body["content_base64"], validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise crud.Invalid("content_base64 geçerli base64 olmalı") from None
    if not raw:
        raise crud.Invalid("Dosya boş")
    return filename.strip(), raw


# ------------------------------------------------------------------ başlık ve değer eşleme

def _ref_target(res, name):
    column = res.columns.get(name)
    ref = column.ref if column else None
    return next((r for r in RESOURCES.values() if r.table == ref), None) if ref else None


def header_label(res, name):
    """Şablon ve dışa aktarım başlığı. İlişki alanında hedef kod beklendiği belirtilir."""
    label = field(name)
    target = _ref_target(res, name)
    if target is not None and "code" in target.fields:
        label += " (kod)"
    return label


def map_headers(res, headers, extra=None):
    lookup = {}
    for name in res.fields:
        for alias in (name, field(name), header_label(res, name)):
            lookup[fold(alias)] = name
    for name, aliases in (extra or {}).items():
        for alias in aliases:
            lookup.setdefault(fold(alias), name)
    mapping = {}
    for header in headers:
        key = fold(str(header).rstrip("*").strip())
        if key in lookup and lookup[key] not in mapping.values():
            mapping[header] = lookup[key]
    return mapping


def convert(db, res, name, text):
    """Hücre metnini alan tipine çevirir. Seçimde Türkçe etiket, ilişkide kod kabul edilir."""
    column = res.columns[name]
    target = _ref_target(res, name)
    if target is not None:
        row = one(db, f"SELECT id FROM {target.table} WHERE code=?", (text,)) if "code" in target.fields else None
        if not row and text.isdigit():
            row = one(db, f"SELECT id FROM {target.table} WHERE id=?", (int(text),))
        if not row:
            raise crud.Invalid(f"{field(name)}: '{text}' kodlu kayıt bulunamadı ({target.label})")
        return row["id"]
    if name in res.enums:
        allowed = res.enums[name]
        if text in allowed:
            return text
        labels = {fold(choice(res.name, name, v)): v for v in allowed}
        if fold(text) in labels:
            return labels[fold(text)]
        raise crud.Invalid(f"{field(name)}: '{text}' geçersiz; izin verilenler: "
                           + ", ".join(choice(res.name, name, v) for v in allowed))
    kind = column.kind
    if kind == "INTEGER":
        if fold(text) in ("evet", "var", "true", "aktif"):
            return 1
        if fold(text) in ("hayir", "yok", "false", "pasif"):
            return 0
        if re.fullmatch(r"-?\d+([.,]0+)?", text):
            return int(re.split(r"[.,]", text)[0])
        raise crud.Invalid(f"{field(name)} tamsayı olmalı")
    if kind in ("REAL", "DECIMAL"):
        number = text.replace(" ", "")
        if "," in number and "." in number:
            number = number.replace(".", "").replace(",", ".")      # 1.234,56
        elif "," in number:
            number = number.replace(",", ".")
        try:
            return float(number)
        except ValueError:
            raise crud.Invalid(f"{field(name)} sayı olmalı") from None
    if kind == "DATE":
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", text):
            day, month, year = text.split(".")                       # Türkçe Excel: 13.11.2026
            return f"{year}-{int(month):02d}-{int(day):02d}"
        if re.fullmatch(r"\d{5}(\.0+)?", text):                       # Excel tarih seri numarası
            return (date(1899, 12, 30) + timedelta(days=int(float(text)))).isoformat()
        return text[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]00:00(:00)?", text) else text
    return text


def _row_values(db, res, mapping, record):
    values, problems = {}, []
    for header, name in mapping.items():
        text = str(record.get(header) or "").strip()
        if not text or name in res.readonly:
            continue
        try:
            values[name] = convert(db, res, name, text)
        except crud.Invalid as exc:
            problems.append(str(exc))
    if problems:
        raise crud.Invalid("; ".join(problems))
    return values


# ------------------------------------------------------------------ hat

def _batch(c, kind, source, filename, dry_run):
    return crud.insert(c.db, BATCHES, {"kind": kind, "source_system": source, "filename": filename,
                                       "status": "dry_run" if dry_run else "applied",
                                       "created_by": c.principal.username})


def _finish(c, batch_id, kind, summary, results, dry_run):
    for row_no, payload, action, message, target in results:
        c.db.execute("INSERT INTO tdr_import_rows (batch_id, row_no, payload_json, action, message, target_id) "
                     "VALUES (?,?,?,?,?,?)",
                     (batch_id, row_no, json.dumps(payload, ensure_ascii=False, default=str), action, message,
                      target))
    c.db.execute("UPDATE tdr_import_batches SET summary_json=? WHERE id=?",
                 (json.dumps(summary, ensure_ascii=False), batch_id))
    audit.log(c.db, c.principal, "IMPORT", kind, batch_id, {**summary, "dry_run": dry_run})
    preview = [{"row_no": r[0], "action": r[2], "message": r[3], "target_id": r[4], "values": r[1]}
               for r in results[:500]]
    return 201, {"batch_id": batch_id, "dry_run": dry_run, **summary, "rows": preview}


def _apply(c, res, values, current, dry_run):
    """Yeni kayıt açar veya yalnızca boş alanları doldurur. Dönüş: (işlem, kimlik, mesaj)."""
    if current is None:
        if dry_run:
            crud.validate(res, crud.clean(dict(values)))
            if res.before_save:
                res.before_save(c.db, crud.clean(dict(values)), None, c.principal)
            return "create", None, None
        return "create", crud.insert(c.db, res, values, c.principal), None
    fill = {k: v for k, v in values.items() if current.get(k) in (None, "") and k not in res.readonly}
    kept = sorted(field(k) for k, v in values.items() if current.get(k) not in (None, "") and current.get(k) != v)
    message = ("Portaldaki değer korundu: " + ", ".join(kept)) if kept else None
    if not fill:
        return "skip", current["id"], message
    if not dry_run:
        crud.update(c.db, res, current["id"], fill, c.principal)
    return "update", current["id"], message


def _run_rows(c, records, handle):
    summary = {"total": 0, "create": 0, "update": 0, "skip": 0, "review": 0, "error": 0}
    results = []
    for row_no, record in enumerate(records, start=2):
        summary["total"] += 1
        state = {"values": {}}
        try:
            with c.db.savepoint():
                action, target, message = handle(record, state)
        except (crud.Invalid, crud.Conflict, crud.Forbidden, crud.NotFound) as exc:
            action, target, message = "error", None, str(exc)
        except IntegrityError:
            action, target, message = "error", None, "Kayıt çakışması veya geçersiz ilişki"
        summary[action] += 1
        results.append((row_no, state["values"], action, message, target))
    return summary, results


def _prepare(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "manage")
    filename, raw = _decode(c)
    headers, records = read_table(filename, raw)
    if len(records) > MAX_ROWS:
        raise crud.Invalid(f"Tek seferde en fazla {MAX_ROWS} satır aktarılabilir")
    return filename, headers, records, bool(c.body.get("dry_run", False))


def import_generic(c, res, key):
    filename, headers, records, dry_run = _prepare(c)
    mapping = map_headers(res, headers)
    missing = [field(k) for k in key if k not in mapping.values()]
    if missing:
        raise crud.Invalid("Zorunlu sütun bulunamadı: " + ", ".join(missing)
                           + ". Şablonu indirip kullanın (Aktarım → Şablon).")
    c.db.lock("import:" + res.name)
    seen = set()

    def handle(record, state):
        state["values"] = values = _row_values(c.db, res, mapping, record)
        natural = tuple(values.get(k) for k in key)
        if any(v in (None, "") for v in natural):
            raise crud.Invalid("Anahtar alan boş: " + ", ".join(field(k) for k in key))
        if natural in seen:
            raise crud.Invalid("Bu anahtar dosyada daha önce geçti")
        seen.add(natural)
        current = one(c.db, f"SELECT * FROM {res.table} WHERE " + " AND ".join(f"{k}=?" for k in key), natural)
        return _apply(c, res, values, current, dry_run)

    batch_id = _batch(c, res.name, "manual", filename, dry_run)
    summary, results = _run_rows(c, records, handle)
    summary["unmapped_columns"] = [h for h in headers if h not in mapping]
    return _finish(c, batch_id, res.name, summary, results, dry_run)


def _next_code(db):
    return f"TDR-{one(db, 'SELECT COALESCE(MAX(id), 0) + 1 AS n FROM tdr_suppliers')['n']:05d}"


def import_suppliers(c):
    """Tedarikçi ana verisi: kaynak sistem kimliği, kod, VKN ve ad benzerliğiyle eşleştirme."""
    source = c.body.get("source_system", "manual")
    if source not in SOURCES:
        raise crud.Invalid("source_system: " + " | ".join(SOURCES))
    filename, headers, records, dry_run = _prepare(c)
    suppliers = RESOURCES["suppliers"]
    mapping = map_headers(suppliers, headers, {k: v for k, v in ALIASES.items() if k != "external_id"})
    external_header = next((h for h in headers if h not in mapping
                            and fold(str(h).rstrip("*")) in {fold(a) for a in ALIASES["external_id"]}), None)
    if "name" not in mapping.values():
        raise crud.Invalid("Tedarikçi adı sütunu bulunamadı. Tanınan başlıklar: Ad, " + ", ".join(ALIASES["name"]))
    c.db.lock("import:suppliers")
    known = {norm_name(s["name"]): s["id"] for s in rows(c.db, "SELECT id, name FROM tdr_suppliers")}

    def handle(record, state):
        external = str(record.get(external_header) or "").strip() or None if external_header else None
        state["values"] = values = _row_values(c.db, suppliers, mapping, record)
        if external:
            state["values"] = {**values, "external_id": external}
        if not values.get("name"):
            raise crud.Invalid("Tedarikçi adı boş")
        ref = one(c.db, "SELECT supplier_id FROM tdr_source_refs WHERE source_system=? AND external_id=?",
                  (source, external)) if external else None
        match = ref["supplier_id"] if ref else None
        for key in ("code", "tax_id"):
            if match is None and values.get(key):
                found = one(c.db, f"SELECT id FROM tdr_suppliers WHERE {key}=?", (values[key],))
                match = found["id"] if found else None
        if match is None and norm_name(values["name"]) in known:
            return "review", known[norm_name(values["name"])], \
                "Aynı ada sahip tedarikçi var; VKN veya harici kimlikle doğrulayın"
        current = crud.get(c.db, suppliers, match) if match else None
        if current is None and not dry_run:
            values.setdefault("code", _next_code(c.db))
        action, target, message = _apply(c, suppliers, values if current or not dry_run
                                         else {**values, "code": values.get("code") or "TDR-YENI"}, current, dry_run)
        if action == "create" and target:
            known[norm_name(values["name"])] = target
        if external and target and not dry_run:
            c.db.execute("""INSERT INTO tdr_source_refs (supplier_id, source_system, external_id, external_name,
                last_seen_at) VALUES (?,?,?,?,?) ON CONFLICT(source_system, external_id) DO UPDATE SET
                external_name=excluded.external_name, last_seen_at=excluded.last_seen_at""",
                         (target, source, external, values["name"], utcnow()))
        if action == "skip" and external and not ref:
            action = "update"            # yeni kaynak kimliği bağlandı
        return action, target, message

    batch_id = _batch(c, "suppliers", source, filename, dry_run)
    summary, results = _run_rows(c, records, handle)
    summary["unmapped_columns"] = [h for h in headers if h not in mapping and h != external_header]
    return _finish(c, batch_id, "suppliers", summary, results, dry_run)


# ------------------------------------------------------------------ şablon ve dışa aktarma

def _display(db, res, name, value, codes):
    if value is None or name == "id":
        return value
    target = _ref_target(res, name)
    if target is not None and "code" in target.fields:
        if target.table not in codes:
            codes[target.table] = {r["id"]: r["code"] for r in rows(db, f"SELECT id, code FROM {target.table}")}
        return codes[target.table].get(value, value)
    if name in res.enums:
        return choice(res.name, name, value)
    return value


def sheet(db, res):
    columns = ["id", *res.fields]
    data = [["Kayıt No" if c == "id" else header_label(res, c) for c in columns]]
    codes = {}
    for record in rows(db, f"SELECT * FROM {res.table} ORDER BY id LIMIT {MAX_ROWS}"):
        data.append([_display(db, res, c, record.get(c), codes) for c in columns])
    return data


def _safe_cell(value):
    """Elektronik tablo formül enjeksiyonuna karşı: =, +, -, @ ile başlayan metin tırnakla etkisizleştirilir."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") and not isinstance(value, (int, float)) else text


def _xlsx_reply(sheets, filename):
    return 200, Raw(_xlsx().make_xlsx(sheets), XLSX, filename)


def exporter(res):
    def export(c):
        authz.require_human(c.principal)
        authz.require(c.principal, "manage")
        authz.check(c.principal, res, "read")
        data = sheet(c.db, res)
        audit.log(c.db, c.principal, "EXPORT", res.name, None, {"rows": len(data) - 1})
        if c.query.get("format", "csv") == "xlsx":
            return _xlsx_reply(OrderedDict([(res.label, data)]), f"{res.name}.xlsx")
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";", lineterminator="\r\n")
        for row in data:
            writer.writerow([_safe_cell(v) for v in row])
        return 200, Raw("﻿" + out.getvalue(), "text/csv; charset=utf-8", f"{res.name}.csv")
    return export


def export_all(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "manage")
    sheets = OrderedDict()
    for name in EXPORT_ORDER:
        res = RESOURCES.get(name)
        if res is not None and c.app.enabled(res.module):
            sheets[res.label] = sheet(c.db, res)
    audit.log(c.db, c.principal, "EXPORT", "all", None, {"sheets": list(sheets)})
    return _xlsx_reply(sheets, "tedarik-portali.xlsx")


def template_columns(name):
    res = RESOURCES[name]
    columns = [f for f in res.fields if f not in res.readonly]
    if name == "suppliers":
        columns.insert(columns.index("name") + 1, "external_id")
    return columns


def template(name):
    res = RESOURCES[name]
    key = IMPORTABLE[name]

    def build(c):
        authz.require_human(c.principal)
        authz.require(c.principal, "manage")
        header, notes = [], [["Sütun", "Zorunlu", "Açıklama"]]
        for f in template_columns(name):
            needed = f in key or (f in res.required and f != "code")
            if f == "external_id":
                label, hint = "Harici kimlik", "Kaynak sistemdeki tedarikçi numarası (SAP LIFNR vb.); tekrar " \
                                               "aktarımda eşleştirme için"
            else:
                label = header_label(res, f)
                column = res.columns[f]
                hint = {"DATE": "Tarih: YYYY-AA-GG veya GG.AA.YYYY", "TIMESTAMP": "Zaman: ISO 8601",
                        "INTEGER": "Tamsayı", "REAL": "Sayı", "DECIMAL": "Tutar"}.get(column.kind, "Metin")
                if f in res.enums:
                    hint = "Şunlardan biri: " + ", ".join(choice(name, f, v) for v in res.enums[f])
                elif _ref_target(res, f) is not None:
                    hint = f"{_ref_target(res, f).label} kaydının kodu"
                if name == "suppliers" and f == "code":
                    hint = "Boş bırakılırsa TDR-00001 biçiminde üretilir"
            header.append(label + (" *" if needed else ""))
            notes.append([label, "Evet" if needed else "Hayır", hint])
        notes += [[], ["Var olan kayıtta yalnızca boş alanlar doldurulur; portalda girilmiş değer korunur.", "", ""],
                  ["Önce 'Deneme' ile sonucu görün; sonra uygulayın.", "", ""]]
        return _xlsx_reply(OrderedDict([("Veri", [header]), ("Açıklama", notes)]), f"sablon-{name}.xlsx")
    return build


def transfer_catalog(c):
    """Aktarım ekranı için: hangi kayıt türleri içe ve dışa aktarılabilir."""
    authz.require(c.principal, "manage")
    return {"imports": [{"resource": n, "label": RESOURCES[n].label, "key": [field(k) for k in IMPORTABLE[n]]}
                        for n in IMPORTABLE if c.app.enabled(RESOURCES[n].module)],
            "exports": [{"resource": n, "label": RESOURCES[n].label} for n in EXPORT_ORDER
                        if n in RESOURCES and c.app.enabled(RESOURCES[n].module)],
            "sources": [{"value": s, "label": CHOICES["source_system"][s]} for s in SOURCES]}


def register(app):
    app.route("GET", API + "/transfer/catalog", transfer_catalog)
    app.route("POST", API + "/import/suppliers", import_suppliers, max_body=MAX_UPLOAD_BODY)
    for name, key in IMPORTABLE.items():
        res = RESOURCES[name]
        if not app.enabled(res.module):
            continue
        if name != "suppliers":
            handler = (lambda r, k: lambda c: import_generic(c, r, k))(res, key)
            app.route("POST", f"{API}/import/{name}", handler, max_body=MAX_UPLOAD_BODY)
        app.route("GET", f"{API}/import/templates/{name}", template(name))
    app.route("GET", API + "/export", export_all)
    for res in RESOURCES.values():
        if app.enabled(res.module) and "list" in res.api and res.name not in ("audit_log", "import_rows"):
            app.route("GET", f"{API}/export/{res.name}", exporter(res))
