"""Veri yönetişimi Faz 5 — veri kalitesi ve gözlenebilirlik (K-032). `datagov` modülünün parçasıdır.

- Kural: tablo[.kolon] üzerinde kodsuz şablon (zorunlu, benzersiz, aralık, desen, izin verilen değerler, referans
  bütünlüğü, tazelik, satır sayısı, biçim: T.C. kimlik/VKN/IBAN/e-posta/telefon/kart/IPv4) veya özel SQL. Boyut
  (tamlık, geçerlilik, benzersizlik, tutarlılık, güncellik), eşik (en düşük geçme oranı) ve önem taşır. Kural bir
  otomatik kontroldür: GRC kontrolüne bağlanırsa her çalıştırma kontrol sonucu olur.
- Çalıştırma verinin yanındadır: toplayıcı kuralı kurum ağında çalıştırır ve yalnızca sayıları (kontrol edilen, hatalı,
  ölçüm) gönderir; SQL'i platformdan almaz, kural tanımından `dq_sql` ile kendisi kurar. Özel SQL kuralı toplayıcının
  yerel ayarında açıkça izin verilmedikçe çalışmaz. Toplayıcısı olmayan kaynakta kuralın SQL'i ekranda gösterilir, sonuç
  elle girilir. Değerlendirme (eşik, tazelik, satır aralığı) her zaman platformda yapılır.
- Başarısız kural: bağlı kontrol varsa sistem kaynaklı başarısız kontrol sonucu (bulgu ve tekrar sayacı GRC'de); yoksa
  "veri kalitesi" kaynaklı bulgu. Yeni bulguda sahibine düzeltici faaliyet (DÖF) açılır; tekrar eden başarısızlık aynı
  bulgunun tekrar sayısını artırır. Kural sahibine ve veri yöneticisine bildirim gider.
- Profil: toplayıcı tablo başına sınırlı örnekte boş, farklı değer, uzunluk ve (hassas olmayan sayısal/tarih kolonlarda)
  en küçük/en büyük değeri hesaplar; değer listesi gönderilmez. Profilden kural önerilir.
- Hacim anomalisi: satır sayısı (katalog içe aktarımı, satır sayısı kuralı) geçmiş ortancadan politikadaki orandan fazla
  saparsa veya sıfıra düşerse anomali kaydı ve bildirim.
- Skor kartı: etkin kuralların son geçme oranlarının önem ağırlıklı ortalaması; boyut, kaynak, veri alanı ve tablo bazında.
"""
import json
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from .. import audit, auth as authz, crud, dq_sql
from ..auth import Principal
from ..db import one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY
from ..labels import CHOICES
from ..schema import Resource, fk
from .core import policy
from .datagov import COLUMNS, EFF_COLS, EFFECTIVE, M, TABLES, _notify, _qualified, _table_units, _writable

SEVERITY_WEIGHT = {"low": 1, "medium": 2, "high": 3, "critical": 4}
DUE_DAYS = {"critical": 15, "high": 30, "medium": 60, "low": 90}
DIMENSIONS = ("completeness", "validity", "uniqueness", "consistency", "timeliness")
SYSTEM = Principal("veri-kalitesi", "ADMIN", "system", "Veri kalitesi motoru")
DEFAULT_POLICIES = {
    "datagov.dq_volume_change_pct": (50, "Satır sayısı geçmiş ortancadan bu orandan (%) fazla saparsa hacim anomalisi."),
    "datagov.dq_stale_days": (7, "Bu kadar gündür çalışmayan etkin kalite kuralı sağlık kontrolünde listelenir."),
}

RULES = Resource("dq_rules", "Veri Kalitesi Kuralları", {
    "code": "TEXT UNIQUE", "name": "TEXT", "table_id": fk("data_tables"), "column_id": fk("data_columns", False),
    "rule_type": "TEXT NOT NULL", "dimension": "TEXT", "params_json": "TEXT", "ref_column_id": fk("data_columns", False),
    "threshold_pct": "REAL NOT NULL DEFAULT 100", "severity": "TEXT NOT NULL DEFAULT 'medium'", "owner": "TEXT",
    "control_id": fk("controls", False), "auto_finding": "INTEGER NOT NULL DEFAULT 1",
    "status": "TEXT NOT NULL DEFAULT 'active'", "description": "TEXT", "last_run_at": "TIMESTAMP", "last_result": "TEXT",
    "last_pass_rate": "REAL", "last_message": "TEXT", "finding_id": fk("findings", False), "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="VKK", write="write", search=("code", "name"),
    readonly=("last_run_at", "last_result", "last_pass_rate", "last_message", "finding_id", "created_by"),
    enums={"rule_type": dq_sql.TYPES, "dimension": DIMENSIONS, "severity": tuple(SEVERITY_WEIGHT),
           "status": ("draft", "active", "retired"), "last_result": ("pass", "fail", "error")})
RESULTS = Resource("dq_results", "Kalite Kuralı Sonuçları", {
    "rule_id": fk("dq_rules"), "checked": "INTEGER", "failed": "INTEGER", "measured": "TEXT", "pass_rate": "REAL",
    "result": "TEXT NOT NULL", "message": "TEXT", "source": "TEXT NOT NULL", "collector_id": fk("data_collectors", False),
    "execution_id": fk("executions", False), "run_at": "TIMESTAMP NOT NULL", "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), immutable=True, search=("message",), indexes=(("rule_id", "run_at"),),
    enums={"result": ("pass", "fail", "error"), "source": ("collector", "manual")})
PROFILES = Resource("dq_profiles", "Kolon Profilleri", {
    "table_id": fk("data_tables"), "column_id": fk("data_columns"), "sample_size": "INTEGER NOT NULL",
    "null_count": "INTEGER", "distinct_count": "INTEGER", "min_length": "INTEGER", "max_length": "INTEGER",
    "min_value": "TEXT", "max_value": "TEXT", "collector_id": fk("data_collectors", False),
    "profiled_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), immutable=True, search=(), indexes=(("column_id", "profiled_at"),))
STATS = Resource("dq_table_stats", "Tablo Hacim Ölçümleri", {
    "table_id": fk("data_tables"), "row_count": "INTEGER NOT NULL", "source": "TEXT NOT NULL",
    "measured_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), immutable=True, search=(), indexes=(("table_id", "measured_at"),),
    enums={"source": ("catalog", "rule")})
ANOMALIES = Resource("dq_anomalies", "Veri Anomalileri", {
    "table_id": fk("data_tables"), "kind": "TEXT NOT NULL DEFAULT 'volume'", "measured": "REAL", "expected": "REAL",
    "deviation_pct": "REAL", "status": "TEXT NOT NULL DEFAULT 'open'", "detected_at": "TIMESTAMP NOT NULL",
    "acknowledged_by": "TEXT", "acknowledged_at": "TIMESTAMP", "note": "TEXT", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"},
    module=M, api=("list", "get"), search=("note",),
    readonly=("table_id", "kind", "measured", "expected", "deviation_pct", "status", "detected_at", "acknowledged_by",
              "acknowledged_at"),
    enums={"kind": ("volume",), "status": ("open", "acknowledged")})


# ------------------------------------------------------------------ kural tanımı

def _params(record):
    try:
        value = json.loads(record.get("params_json") or "{}")
    except (TypeError, ValueError):
        raise crud.Invalid("Kural parametreleri geçerli JSON olmalı") from None
    if not isinstance(value, dict):
        raise crud.Invalid("Kural parametreleri nesne olmalı")
    return value


def spec(db, rule):
    """Kural kaydı → dq_sql tanımı (şema, tablo, kolon adları katalogdan)."""
    t = one(db, "SELECT schema_name, name, source_id FROM tdr_data_tables WHERE id=?", (rule["table_id"],))
    col = one(db, "SELECT name FROM tdr_data_columns WHERE id=?", (rule["column_id"],)) if rule.get("column_id") else None
    ref = one(db, """SELECT c.name, t.name AS table_name, t.schema_name, t.source_id FROM tdr_data_columns c
        JOIN tdr_data_tables t ON t.id=c.table_id WHERE c.id=?""", (rule["ref_column_id"],)) if rule.get("ref_column_id") else None
    return {"code": rule.get("code"), "type": rule["rule_type"], "schema": t["schema_name"] if t else "",
            "table": t["name"] if t else "", "column": col["name"] if col else None, "params": _params(rule),
            "ref_schema": ref["schema_name"] if ref else None, "ref_table": ref["table_name"] if ref else None,
            "ref_column": ref["name"] if ref else None, "_source_id": t["source_id"] if t else None,
            "_ref_source_id": ref["source_id"] if ref else None}


AUTO_NAMES = {"not_null": "{c} boş olmamalı", "unique": "{c} benzersiz olmalı", "range": "{c} aralıkta olmalı",
              "pattern": "{c} desene uymalı", "allowed_values": "{c} izin verilen değerlerden olmalı",
              "reference": "{c} referans tabloda bulunmalı", "freshness": "{t} güncel olmalı ({c})",
              "row_count": "{t} satır sayısı beklenen aralıkta", "format": "{c} geçerli biçimde olmalı",
              "custom_sql": "{t} özel kural"}


def _rule_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    table = one(db, "SELECT * FROM tdr_data_tables WHERE id=?", (merged.get("table_id"),))
    if not table:
        raise crud.Invalid("Tablo bulunamadı")
    if merged.get("column_id") and not one(db, "SELECT 1 AS x FROM tdr_data_columns WHERE id=? AND table_id=?",
                                           (merged["column_id"], table["id"])):
        raise crud.Invalid("Kolon bu tabloya ait değil")
    if merged.get("rule_type") == "custom_sql" and principal and not principal.can("manage") and \
            ("params_json" in data or current is None):
        raise crud.Forbidden("Özel SQL kuralını yalnızca veri yönetişimi yöneticisi tanımlar")
    if not 0 <= float(merged.get("threshold_pct") if merged.get("threshold_pct") is not None else 100) <= 100:
        raise crud.Invalid("Eşik 0 ile 100 arasında olmalı")
    s = spec(db, merged)
    try:
        dq_sql.build(s, "ansi")
    except dq_sql.RuleError as exc:
        raise crud.Invalid(str(exc)) from None
    p = s["params"]
    if merged["rule_type"] == "reference" and s["_ref_source_id"] != table["source_id"]:
        raise crud.Invalid("Referans kolon aynı veri kaynağında olmalı (sorgu tek veritabanında çalışır)")
    if merged["rule_type"] == "freshness" and not float(p.get("max_age_hours") or 0) > 0:
        raise crud.Invalid("Tazelik için en çok kaç saatlik veri kabul edildiğini girin")
    if merged["rule_type"] == "row_count" and p.get("min_rows") in (None, "") and p.get("max_rows") in (None, ""):
        raise crud.Invalid("Satır sayısı için en az veya en çok değer girin")
    if not merged.get("dimension"):
        data["dimension"] = dq_sql.DIMENSIONS[merged["rule_type"]]
    if current is None:
        data["created_by"] = principal.username if principal else "system"
        if not merged.get("name"):
            data["name"] = AUTO_NAMES[merged["rule_type"]].format(c=s["column"] or "", t=table["name"])[:200]
        if not merged.get("owner"):
            eff = one(db, f"""SELECT {EFF_COLS} FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE}
                WHERE t.id=?""", (table["id"],))
            data["owner"] = eff["eff_steward"] or eff["eff_owner"] if eff else None


def _rule_units(db, record):
    table = one(db, "SELECT * FROM tdr_data_tables WHERE id=?", (record.get("table_id"),))
    return _table_units(db, table) if table else set()


RULES.before_save = _rule_rules
RULES.scope = _rule_units


# ------------------------------------------------------------------ değerlendirme ve sonuç

def _parse_time(value):
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text if "T" in text or " " in text else text + "T00:00:00")
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def evaluate(rule, checked, failed, measured, now=None):
    """Platformda değerlendirme. Dönüş: (sonuç, geçme oranı, ileti, checked, failed)."""
    now = now or datetime.now(timezone.utc)
    p = _params(rule)
    kind = rule["rule_type"]
    if kind == "freshness":
        stamp = _parse_time(measured)
        limit = float(p.get("max_age_hours") or 0)
        if stamp is None:
            return "fail", 0.0, "Kolonda tarih/zaman değeri yok veya okunamadı", 1, 1
        age = (now - stamp).total_seconds() / 3600
        ok = age <= limit
        return ("pass" if ok else "fail"), (100.0 if ok else 0.0), \
            f"En yeni kayıt {age:.1f} saat önce (sınır {limit:g} saat)", 1, 0 if ok else 1
    if kind == "row_count":
        try:
            n = int(float(measured))
        except (TypeError, ValueError):
            raise crud.Invalid("Satır sayısı ölçümü sayı olmalı") from None
        low = int(p["min_rows"]) if p.get("min_rows") not in (None, "") else None
        high = int(p["max_rows"]) if p.get("max_rows") not in (None, "") else None
        ok = (low is None or n >= low) and (high is None or n <= high)
        span = f"{low:,}–{high:,}" if low is not None and high is not None else f"en az {low:,}" if low is not None else f"en çok {high:,}"
        return ("pass" if ok else "fail"), (100.0 if ok else 0.0), f"{n:,} satır (beklenen {span})".replace(",", "."), 1, 0 if ok else 1
    try:
        checked, failed = int(checked or 0), int(failed or 0)
    except (TypeError, ValueError):
        raise crud.Invalid("Kontrol edilen ve hatalı satır sayısı tam sayı olmalı") from None
    if checked < 0 or failed < 0 or failed > checked:
        raise crud.Invalid("Hatalı satır sayısı 0 ile kontrol edilen satır sayısı arasında olmalı")
    if checked == 0:
        return "pass", 100.0, "Kontrol edilecek satır yok", 0, 0
    rate = round(100.0 * (checked - failed) / checked, 3)
    ok = rate >= float(rule["threshold_pct"] if rule["threshold_pct"] is not None else 100)
    return ("pass" if ok else "fail"), rate, \
        f"{failed:,} / {checked:,} satır kuralı sağlamıyor (geçme %{rate:g}, eşik %{float(rule['threshold_pct']):g})".replace(",", "."), \
        checked, failed


def _people(db, rule):
    eff = one(db, f"""SELECT {EFF_COLS} FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE}
        WHERE t.id=?""", (rule["table_id"],)) or {}
    return [u for u in dict.fromkeys((rule["owner"], eff.get("eff_steward"), eff.get("eff_owner"))) if u]


def _open_finding(db, rule, message, checked, failed, now):
    """Kontrole bağlı olmayan kural için bulgu ve (yeni bulguda) DÖF. Tekrar eden başarısızlık tekrar sayısını artırır."""
    from .grc import FINDINGS
    if rule["finding_id"]:
        f = one(db, "SELECT id, status FROM tdr_findings WHERE id=?", (rule["finding_id"],))
        if f and f["status"] in ("open", "in_progress"):
            db.execute("UPDATE tdr_findings SET recurrence=recurrence+1, last_seen_at=?, description=?, updated_at=? WHERE id=?",
                       (now, message, now, f["id"]))
            return f["id"], False
    table = one(db, "SELECT schema_name, name FROM tdr_data_tables WHERE id=?", (rule["table_id"],))
    due = (date.today() + timedelta(days=DUE_DAYS[rule["severity"]])).isoformat()
    fid = db.execute("""INSERT INTO tdr_findings (code, title, description, severity, status, owner, due_date, recurrence,
        last_seen_at, created_by, created_at, source) VALUES (?,?,?,?,'open',?,?,1,?,'system',?,'data_quality')""",
                     (crud.next_code(db, FINDINGS), f"Veri kalitesi: {rule['name']}"[:300],
                      f"{rule['code']} · {_qualified(table['schema_name'], table['name'])}\n{message}", rule["severity"],
                      rule["owner"], due, now, now)).lastrowid
    return fid, True


def _action(db, rule, finding_id, now):
    from .grc import ACTIONS
    owner = rule["owner"] or (rule["created_by"] if rule["created_by"] not in (None, "system") else None)
    if not owner:
        return None
    due = (date.today() + timedelta(days=DUE_DAYS[rule["severity"]])).isoformat()
    return db.execute("""INSERT INTO tdr_grc_actions (code, title, finding_id, control_id, description, owner, due_date, priority,
        status, created_at) VALUES (?,?,?,?,?,?,?,?,'open',?)""",
                      (crud.next_code(db, ACTIONS), f"Veri düzeltme: {rule['name']}"[:300], finding_id, rule["control_id"],
                       "Hatalı kayıtları kaynakta düzeltin ve hatanın kök nedenini (giriş doğrulaması, arayüz, dönüşüm) giderin; "
                       "kural yeniden çalışıp geçince faaliyeti doğrulamaya gönderin.", owner, due, rule["severity"],
                      now)).lastrowid


def record_result(db, rule, *, checked=None, failed=None, measured=None, source, principal, collector_id=None, error=None,
                  run_at=None):
    """Sonucu yazar; başarısızlıkta GRC bağlantısını ve bildirimi işletir. Dönüş: sonuç sözlüğü."""
    now = utcnow()
    run_at = run_at or now
    execution_id = finding_id = action_id = None
    if error:
        result, rate, message = "error", None, str(error)[:1000]
        checked = failed = None
    else:
        result, rate, message, checked, failed = evaluate(rule, checked, failed, measured)
    if result in ("pass", "fail") and rule["control_id"]:
        from .grc import record_execution
        control = one(db, "SELECT id, active FROM tdr_controls WHERE id=?", (rule["control_id"],))
        if control and control["active"]:
            r = record_execution(db, SYSTEM, {
                "control_id": rule["control_id"], "status": result, "details": f"{rule['code']} {rule['name']}: {message}",
                "sample_size": checked, "exceptions": failed,
                "provenance": {"source": "data_quality", "rule": rule["code"], "collection_status": "complete",
                               "measured": str(measured)[:100] if measured is not None else None}}, source="system")
            execution_id, finding_id = r["execution_id"], r["finding_id"]
            if finding_id and not r["finding_repeated"]:
                action_id = _action(db, rule, finding_id, now)
    if result == "fail" and not rule["control_id"] and rule["auto_finding"]:
        finding_id, new = _open_finding(db, rule, message, checked, failed, now)
        if new:
            action_id = _action(db, rule, finding_id, now)
    db.execute("""INSERT INTO tdr_dq_results (rule_id, checked, failed, measured, pass_rate, result, message, source, collector_id,
        execution_id, run_at, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (rule["id"], checked, failed, None if measured is None else str(measured)[:100], rate, result, message, source,
                collector_id, execution_id, run_at, principal.username if principal else "system", now))
    sets = {"last_run_at": run_at, "last_result": result, "last_pass_rate": rate, "last_message": message}
    if finding_id:
        sets["finding_id"] = finding_id
    db.execute(f"UPDATE tdr_dq_rules SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?",
               (*sets.values(), now, rule["id"]))
    if rule["rule_type"] == "row_count" and result != "error":
        try:
            add_volume(db, rule["table_id"], int(float(measured)), "rule", now)
        except (TypeError, ValueError):
            pass
    if result in ("fail", "error"):
        table = one(db, "SELECT schema_name, name FROM tdr_data_tables WHERE id=?", (rule["table_id"],))
        _notify(db, "dq.failed", f"Veri kalitesi kuralı {'başarısız' if result == 'fail' else 'çalışmadı'}: {rule['code']} {rule['name']}",
                f"{_qualified(table['schema_name'], table['name'])}: {message}" +
                ("\nBulgu ve düzeltici faaliyet açıldı." if action_id else "\nAçık bulgunun tekrar sayısı arttı." if finding_id else ""),
                users=_people(db, rule), link=f"#/dqrule/{rule['id']}", object_type="dq_rules", object_id=rule["id"],
                dedupe=f"dq:{rule['id']}:{result}:{now[:10]}")
    return {"rule": rule["code"], "result": result, "pass_rate": rate, "message": message, "finding_id": finding_id,
            "action_id": action_id, "execution_id": execution_id}


# ------------------------------------------------------------------ hacim ve anomali

def _median_check(db, table_id, row_count, now):
    previous = [r["row_count"] for r in rows(db, """SELECT row_count FROM tdr_dq_table_stats WHERE table_id=?
        ORDER BY measured_at DESC, id DESC LIMIT 11""", (table_id,))][1:]
    if len(previous) < 4:
        return None
    expected = statistics.median(previous)
    deviation = abs(row_count - expected) / max(expected, 1) * 100
    limit = float(policy(db, "datagov.dq_volume_change_pct", 50))
    if deviation <= limit and not (expected > 0 and row_count == 0):
        return None
    if one(db, "SELECT 1 AS x FROM tdr_dq_anomalies WHERE table_id=? AND kind='volume' AND status='open'", (table_id,)):
        return None
    aid = db.execute("""INSERT INTO tdr_dq_anomalies (table_id, kind, measured, expected, deviation_pct, status, detected_at,
        created_at) VALUES (?,?,?,?,?,?,?,?)""", (table_id, "volume", row_count, expected, round(deviation, 1), "open", now, now)).lastrowid
    t = one(db, f"""SELECT t.schema_name, t.name, {EFF_COLS} FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id
        {EFFECTIVE} WHERE t.id=?""", (table_id,))
    _notify(db, "dq.anomaly", f"Hacim anomalisi: {_qualified(t['schema_name'], t['name'])}",
            f"Satır sayısı {row_count:,}; son ölçümlerin ortancası {expected:,.0f} (sapma %{deviation:.0f}). Yükleme işini, kaynak "
            "sistemi ve filtreleri denetleyin.".replace(",", "."),
            users=[u for u in (t["eff_steward"], t["eff_owner"], t["eff_custodian"]) if u], link=f"#/catalog/table/{table_id}",
            object_type="dq_anomalies", object_id=aid, dedupe=f"dqa:{aid}")
    return aid


def add_volume(db, table_id, row_count, source, now=None):
    now = now or utcnow()
    db.execute("INSERT INTO tdr_dq_table_stats (table_id, row_count, source, measured_at) VALUES (?,?,?,?)",
               (table_id, int(row_count), source, now))
    return _median_check(db, table_id, int(row_count), now)


def record_volumes(db, source_id):
    """Katalog içe aktarımından sonra: izlenen tabloların (kuralı olan veya onaylı veri seti) satır sayısını kaydeder."""
    now = utcnow()
    for t in rows(db, """SELECT t.id, t.row_count FROM tdr_data_tables t WHERE t.source_id=? AND t.status<>'removed'
            AND t.row_count IS NOT NULL AND (t.certified=1 OR EXISTS (SELECT 1 FROM tdr_dq_rules r WHERE r.table_id=t.id
            AND r.status='active'))""", (source_id,)):
        add_volume(db, t["id"], t["row_count"], "catalog", now)


def acknowledge(c):
    a = crud.get(c.db, ANOMALIES, c.params["id"])
    table = crud.get(c.db, TABLES, a["table_id"])
    _writable(c, TABLES, table)
    if a["status"] != "open":
        raise crud.Conflict("Anomali zaten değerlendirilmiş")
    note = str(c.body.get("note") or "").strip()
    if len(note) < 5:
        raise crud.Invalid("Değerlendirme notu yazın (ör. dönem sonu temizliği, beklenen değişiklik)")
    now = utcnow()
    c.db.execute("UPDATE tdr_dq_anomalies SET status='acknowledged', acknowledged_by=?, acknowledged_at=?, note=?, updated_at=? "
                 "WHERE id=?", (c.principal.username, now, note[:1000], now, a["id"]))
    audit.log(c.db, c.principal, "ACKNOWLEDGE", "dq_anomalies", a["id"], {"note": note[:500]})
    return {"ok": True}


# ------------------------------------------------------------------ skor kartı

def score(items):
    """items: (boyut, önem, geçme oranı). Boyut skorları önem ağırlıklı; genel skor boyutların ortalaması."""
    dims = defaultdict(lambda: [0.0, 0])
    for dim, severity, rate in items:
        w = SEVERITY_WEIGHT.get(severity, 2)
        dims[dim][0] += w * rate
        dims[dim][1] += w
    out = {d: round(v[0] / v[1], 1) for d, v in dims.items() if v[1]}
    return {"overall": round(sum(out.values()) / len(out), 1) if out else None, "dimensions": out}


def scorecard(db, where="1=1", args=()):
    data = rows(db, f"""SELECT r.id, r.dimension, r.severity, r.last_pass_rate, r.last_result, t.id AS table_id,
        t.name AS table_name, t.schema_name, s.id AS source_id, s.name AS source_name, d.id AS domain_id, d.name AS domain_name
        FROM tdr_dq_rules r JOIN tdr_data_tables t ON t.id=r.table_id JOIN tdr_data_sources s ON s.id=t.source_id
        LEFT JOIN tdr_data_domains d ON d.id=COALESCE(t.domain_id, s.domain_id)
        WHERE r.status='active' AND r.last_result IN ('pass','fail') AND {where}""", args)
    total = score((r["dimension"], r["severity"], r["last_pass_rate"]) for r in data)

    def by(key, name):
        groups = defaultdict(list)
        names = {}
        for r in data:
            if r[key] is None:
                continue
            groups[r[key]].append((r["dimension"], r["severity"], r["last_pass_rate"]))
            names[r[key]] = r[name]
        out = []
        for gid, items in groups.items():
            s = score(items)
            out.append({"id": gid, "name": names[gid], "score": s["overall"], "dimensions": s["dimensions"], "rules": len(items),
                        "failing": sum(1 for x in data if x[key] == gid and x["last_result"] == "fail")})
        return sorted(out, key=lambda x: (x["score"] if x["score"] is not None else 101, x["name"]))
    return {**total, "rules": len(data), "failing": sum(1 for r in data if r["last_result"] == "fail"),
            "by_source": by("source_id", "source_name"), "by_domain": by("domain_id", "domain_name"),
            "by_table": by("table_id", "table_name")[:20]}


def _trend(db, days=30, where="1=1", args=()):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    buckets = defaultdict(list)
    for r in rows(db, f"""SELECT x.run_at, x.pass_rate FROM tdr_dq_results x JOIN tdr_dq_rules r ON r.id=x.rule_id
            JOIN tdr_data_tables t ON t.id=r.table_id WHERE x.result IN ('pass','fail') AND x.run_at >= ? AND {where}
            ORDER BY x.run_at LIMIT 50000""", (since, *args)):
        buckets[str(r["run_at"])[:10]].append(r["pass_rate"])
    return [{"day": d, "pass_rate": round(sum(v) / len(v), 1), "runs": len(v)} for d, v in sorted(buckets.items())]


# ------------------------------------------------------------------ uç noktalar (kullanıcı)

def _rule_rows(db, where, args):
    return rows(db, f"""SELECT r.*, t.name AS table_name, t.schema_name, s.id AS source_id, s.name AS source_name,
        s.platform, c.name AS column_name FROM tdr_dq_rules r JOIN tdr_data_tables t ON t.id=r.table_id
        JOIN tdr_data_sources s ON s.id=t.source_id LEFT JOIN tdr_data_columns c ON c.id=r.column_id
        WHERE {where} ORDER BY CASE r.last_result WHEN 'fail' THEN 0 WHEN 'error' THEN 1 ELSE 2 END, s.name, t.name, r.code
        LIMIT 2000""", args)


def overview(c):
    authz.check(c.principal, RULES, "read")
    db = c.db
    stale = (datetime.now(timezone.utc) - timedelta(days=int(policy(db, "datagov.dq_stale_days", 7)))).isoformat(timespec="seconds")
    counts = {r["status"]: r["n"] for r in rows(db, "SELECT status, COUNT(*) AS n FROM tdr_dq_rules GROUP BY status")}
    return {
        "scorecard": scorecard(db), "trend": _trend(db), "counts": counts,
        "failing": _rule_rows(db, "r.status='active' AND r.last_result IN ('fail','error')", ()),
        "stale": _rule_rows(db, "r.status='active' AND (r.last_run_at IS NULL OR r.last_run_at < ?)", (stale,))[:50],
        "anomalies": rows(db, """SELECT a.*, t.name AS table_name, t.schema_name, s.name AS source_name FROM tdr_dq_anomalies a
            JOIN tdr_data_tables t ON t.id=a.table_id JOIN tdr_data_sources s ON s.id=t.source_id WHERE a.status='open'
            ORDER BY a.detected_at DESC LIMIT 50"""),
        "recent": rows(db, """SELECT x.id, x.rule_id, x.result, x.pass_rate, x.message, x.source, x.run_at, r.code, r.name,
            t.name AS table_name FROM tdr_dq_results x JOIN tdr_dq_rules r ON r.id=x.rule_id JOIN tdr_data_tables t
            ON t.id=r.table_id ORDER BY x.run_at DESC, x.id DESC LIMIT 12"""),
        "can_edit": authz.can_write(c.principal, RULES) and c.principal.auth_type not in ("api_key", "collector"),
    }


def rule_list(c):
    authz.check(c.principal, RULES, "read")
    where, args = ["1=1"], []
    for key, col in (("source_id", "s.id"), ("table_id", "t.id"), ("status", "r.status"), ("result", "r.last_result")):
        if c.query.get(key):
            where.append(f"{col}=?")
            args.append(int(c.query[key]) if key.endswith("_id") else c.query[key])
    return {"items": _rule_rows(c.db, " AND ".join(where), args)}


def rule_context(c):
    authz.check(c.principal, RULES, "read")
    db = c.db
    r = crud.get(db, RULES, c.params["id"])
    s = spec(db, r)
    source = one(db, "SELECT id, code, name, platform FROM tdr_data_sources WHERE id=?", (s["_source_id"],))
    dialect = dq_sql.dialect_of(source["platform"])
    try:
        sql, mode = dq_sql.build(s, dialect)
    except dq_sql.RuleError as exc:
        sql, mode = None, str(exc)
    r["params"] = s["params"]
    r["table"] = one(db, "SELECT id, name, schema_name, row_count FROM tdr_data_tables WHERE id=?", (r["table_id"],))
    r["column"] = one(db, "SELECT id, name, data_type FROM tdr_data_columns WHERE id=?", (r["column_id"],)) if r["column_id"] else None
    r["ref"] = {"schema": s["ref_schema"], "table": s["ref_table"], "column": s["ref_column"]} if s["ref_table"] else None
    r["source"] = source
    r["sql"], r["mode"], r["dialect"] = sql, mode, dialect
    r["results"] = rows(db, "SELECT * FROM tdr_dq_results WHERE rule_id=? ORDER BY run_at DESC, id DESC LIMIT 60", (r["id"],))
    r["control"] = one(db, "SELECT id, code, name FROM tdr_controls WHERE id=?", (r["control_id"],)) if r["control_id"] else None
    r["finding"] = one(db, "SELECT id, code, title, status, recurrence FROM tdr_findings WHERE id=?", (r["finding_id"],)) \
        if r["finding_id"] else None
    r["actions"] = rows(db, "SELECT id, code, title, status, owner, due_date FROM tdr_grc_actions WHERE finding_id=? ORDER BY id",
                        (r["finding_id"],)) if r["finding_id"] else []
    r["collectors"] = rows(db, """SELECT id, code, name, last_push_at FROM tdr_data_collectors WHERE source_id=? AND status='active'
        AND connector<>'openlineage'""", (source["id"],))
    can = authz.can_write(c.principal, RULES) and c.principal.auth_type not in ("api_key", "collector")
    if can and c.principal.role == "UNIT_USER":
        can = bool(_rule_units(db, r) & c.principal.units)
    r["can_edit"] = can
    return r


def manual_result(c):
    rule = crud.get(c.db, RULES, c.params["id"])
    _writable(c, RULES, rule)
    if rule["status"] != "active":
        raise crud.Conflict("Yalnızca etkin kuralın sonucu girilir")
    b = c.body
    out = record_result(c.db, rule, checked=b.get("checked"), failed=b.get("failed"), measured=b.get("measured"),
                        source="manual", principal=c.principal)
    audit.log(c.db, c.principal, "DQ_RESULT", "dq_rules", rule["id"], {k: b.get(k) for k in ("checked", "failed", "measured")} | out)
    return out


def _latest_profiles(db, table_id):
    return {p["column_id"]: p for p in rows(db, """SELECT p.* FROM tdr_dq_profiles p WHERE p.table_id=? AND p.id IN
        (SELECT MAX(id) FROM tdr_dq_profiles WHERE table_id=? GROUP BY column_id)""", (table_id, table_id))}


FORMAT_HINTS = (("email", ("eposta", "e_posta", "email", "mail")), ("phone", ("telefon", "phone", "gsm", "cep", "telf")),
                ("tckn", ("tckn", "kimlik_no", "tc_no", "tcno")), ("iban", ("iban",)), ("vkn", ("vkn", "vergi_no", "stcd")))


def suggestions(db, table, rules, profiles, columns):
    have = {(r["rule_type"], r["column_id"]) for r in rules if r["status"] != "retired"}
    out = []

    def add(kind, col, params, reason):
        if (kind, col["id"] if col else None) not in have and len(out) < 30:
            out.append({"rule_type": kind, "column_id": col["id"] if col else None, "column": col["name"] if col else None,
                        "params": params, "reason": reason})
            have.add((kind, col["id"] if col else None))
    for col in columns:
        p = profiles.get(col["id"])
        lower = col["name"].lower()
        if col["is_primary_key"]:
            add("not_null", col, {}, "Birincil anahtar boş olamaz")
            add("unique", col, {}, "Birincil anahtar tekil olmalı")
        if p and p["sample_size"] >= 20:
            if p["null_count"] == 0:
                add("not_null", col, {}, f"Profilde {p['sample_size']} satırın hiçbirinde boş değil")
            if p["distinct_count"] == p["sample_size"] - (p["null_count"] or 0) and p["sample_size"] >= 50 and \
                    (lower.endswith(("_id", "id", "_no", "no", "kod", "code", "key"))):
                add("unique", col, {}, "Profilde tüm değerler farklı; anahtar adı taşıyor")
        for fmt, keys in FORMAT_HINTS:
            if any(k in lower for k in keys):
                add("format", col, {"format": fmt}, f"Kolon adı {CHOICES['dq_format'][fmt]} içeriyor")
                break
        if col["references_to"]:
            ref = str(col["references_to"]).split(",")[0].strip().split(".")
            if len(ref) >= 2:
                target = one(db, """SELECT c.id FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id
                    WHERE t.source_id=? AND LOWER(t.name)=? AND LOWER(c.name)=? AND c.status='active'""",
                             (table["source_id"], ref[-2].lower(), ref[-1].lower()))
                if target:
                    out_params = {}
                    if ("reference", col["id"]) not in have and len(out) < 30:
                        out.append({"rule_type": "reference", "column_id": col["id"], "column": col["name"], "params": out_params,
                                    "ref_column_id": target["id"], "reason": f"Yabancı anahtar: {col['references_to']}"})
                        have.add(("reference", col["id"]))
    if table["row_count"] and ("row_count", None) not in have:
        add("row_count", None, {"min_rows": max(1, int(table["row_count"] * 0.5))},
            f"Katalogdaki satır sayısı {table['row_count']:,}; yarısının altına düşerse uyarı".replace(",", "."))
    return out


def table_quality(c):
    authz.check(c.principal, RULES, "read")
    t = crud.get(c.db, TABLES, c.params["id"])
    rules = _rule_rows(c.db, "r.table_id=?", (t["id"],))
    profiles = _latest_profiles(c.db, t["id"])
    columns = rows(c.db, "SELECT id, name, is_primary_key, references_to, data_type FROM tdr_data_columns WHERE table_id=? "
                         "AND status='active' ORDER BY position, name", (t["id"],))
    names = {col["id"]: col["name"] for col in columns}
    can = authz.can_write(c.principal, RULES) and c.principal.auth_type not in ("api_key", "collector")
    if can and c.principal.role == "UNIT_USER":
        can = bool(_table_units(c.db, t) & c.principal.units)
    return {"rules": rules, "score": scorecard(c.db, "t.id=?", (t["id"],)),
            "profiles": [{**p, "column": names.get(p["column_id"])} for p in profiles.values() if p["column_id"] in names],
            "suggestions": suggestions(c.db, t, rules, profiles, columns) if can else [],
            "anomalies": rows(c.db, "SELECT * FROM tdr_dq_anomalies WHERE table_id=? ORDER BY id DESC LIMIT 10", (t["id"],)),
            "volumes": rows(c.db, "SELECT row_count, source, measured_at FROM tdr_dq_table_stats WHERE table_id=? "
                                  "ORDER BY measured_at DESC, id DESC LIMIT 30", (t["id"],)),
            "can_edit": can}


def column_quality(c):
    authz.check(c.principal, RULES, "read")
    col = crud.get(c.db, COLUMNS, c.params["id"])
    profile = one(c.db, "SELECT * FROM tdr_dq_profiles WHERE column_id=? ORDER BY id DESC LIMIT 1", (col["id"],))
    return {"profile": profile, "rules": _rule_rows(c.db, "r.column_id=?", (col["id"],))}


# ------------------------------------------------------------------ toplayıcı uç noktaları

def collector_plan(c):
    from .collection import _machine
    col = _machine(c)
    db = c.db
    source = one(db, "SELECT id, platform FROM tdr_data_sources WHERE id=?", (col["source_id"],))
    rules = []
    for r in rows(db, """SELECT r.* FROM tdr_dq_rules r JOIN tdr_data_tables t ON t.id=r.table_id WHERE t.source_id=?
            AND r.status='active' AND t.status<>'removed' ORDER BY r.code""", (source["id"],)):
        s = spec(db, r)
        rules.append({k: v for k, v in s.items() if not k.startswith("_")})
    sensitive = [f"{(r['schema_name'] or '').lower()}.{r['table_name'].lower()}.{r['name'].lower()}" for r in rows(db, """
        SELECT c.name, t.name AS table_name, t.schema_name FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id
        WHERE t.source_id=? AND c.status='active' AND (c.personal_data IN ('personal','special')
        OR COALESCE(c.classification, t.classification, '') IN ('confidential','restricted'))""", (source["id"],))]
    tables = []
    if col["profile_rows"]:
        tables = [{"schema": t["schema_name"], "table": t["name"]} for t in rows(db, """SELECT t.schema_name, t.name FROM
            tdr_data_tables t WHERE t.source_id=? AND t.status<>'removed' AND t.object_type<>'view' ORDER BY t.certified DESC,
            (SELECT COUNT(*) FROM tdr_dq_rules r WHERE r.table_id=t.id) DESC, t.name LIMIT 300""", (source["id"],))]
    return {"dialect": dq_sql.dialect_of(source["platform"]), "rules": rules,
            "profile": {"rows": col["profile_rows"], "tables": tables}, "sensitive": sensitive}


def collector_results(c):
    from .collection import _client, _machine
    col = _machine(c)
    db = c.db
    client = _client(c.body)
    out = Counter()
    by_code = {r["code"]: r for r in rows(db, """SELECT r.* FROM tdr_dq_rules r JOIN tdr_data_tables t ON t.id=r.table_id
        WHERE t.source_id=? AND r.status='active'""", (col["source_id"],))}
    for item in (c.body.get("results") or [])[:5000]:
        if not isinstance(item, dict) or item.get("rule") not in by_code:
            out["unknown"] += 1
            continue
        try:
            with db.savepoint():
                r = record_result(db, by_code[item["rule"]], checked=item.get("checked"), failed=item.get("failed"),
                                  measured=item.get("measured"), error=item.get("error"), source="collector",
                                  principal=c.principal, collector_id=col["id"])
            out[r["result"]] += 1
        except crud.Invalid as exc:
            with db.savepoint():
                record_result(db, by_code[item["rule"]], error=f"Geçersiz sonuç: {exc}", source="collector",
                              principal=c.principal, collector_id=col["id"])
            out["error"] += 1
    now = utcnow()
    for prof in (c.body.get("profiles") or [])[:1000]:
        if not isinstance(prof, dict) or not isinstance(prof.get("columns"), dict):
            continue
        t = one(db, "SELECT id FROM tdr_data_tables WHERE source_id=? AND LOWER(schema_name)=? AND LOWER(name)=? AND status<>'removed'",
                (col["source_id"], str(prof.get("schema") or "").lower(), str(prof.get("table") or "").lower()))
        if not t:
            continue
        cols = {r["name"].lower(): r["id"] for r in rows(db, "SELECT id, name FROM tdr_data_columns WHERE table_id=? AND status='active'",
                                                         (t["id"],))}
        size = int(prof.get("sample_size") or 0)
        for name, st in list(prof["columns"].items())[:2000]:
            cid = cols.get(str(name).lower())
            if not cid or not isinstance(st, dict) or size <= 0:
                continue

            def num(key):
                try:
                    return int(st[key]) if st.get(key) is not None else None
                except (TypeError, ValueError):
                    return None
            db.execute("""INSERT INTO tdr_dq_profiles (table_id, column_id, sample_size, null_count, distinct_count, min_length,
                max_length, min_value, max_value, collector_id, profiled_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                       (t["id"], cid, size, num("nulls"), num("distinct"), num("min_len"), num("max_len"),
                        None if st.get("min") is None else str(st["min"])[:100], None if st.get("max") is None else str(st["max"])[:100],
                        col["id"], now))
        out["profiles"] += 1
    db.execute("UPDATE tdr_data_collectors SET last_seen_at=?, client_version=COALESCE(?, client_version), updated_at=? WHERE id=?",
               (now, client.get("version"), now, col["id"]))
    audit.log(db, c.principal, "COLLECT_QUALITY", "data_sources", col["source_id"], {"collector": col["code"], **out})
    return dict(out)


# ------------------------------------------------------------------ İşlerim, sağlık kontrolü, hatırlatma

def my_work_items(db, principal, names):
    marks = ",".join("?" * len(names))
    return {"dq_failing": rows(db, f"""SELECT r.id, r.code, r.name AS title, r.last_result, r.last_message FROM tdr_dq_rules r
        WHERE r.status='active' AND r.last_result IN ('fail','error') AND r.owner IN ({marks}) ORDER BY r.code""", names)}


def health_checks(db, check, count, readable=lambda name: True):
    if not readable("dq_rules"):
        return []
    stale = (datetime.now(timezone.utc) - timedelta(days=int(policy(db, "datagov.dq_stale_days", 7)))).isoformat(timespec="seconds")
    population = count(db, "SELECT COUNT(*) AS n FROM tdr_dq_rules WHERE status='active'")
    return [
        check("dq_failing_high", "Başarısız yüksek ve kritik önemli veri kalitesi kuralları",
              "Kritik veride kalite hatası raporları, kararları ve düzenleyici bildirimleri yanıltır; kural bir otomatik kontroldür.",
              "high", rows(db, """SELECT id, code, name AS title FROM tdr_dq_rules WHERE status='active' AND last_result='fail'
              AND severity IN ('high','critical') ORDER BY code"""), "dq_rules", link="quality", population=population),
        check("dq_stale", "Uzun süredir çalışmayan veri kalitesi kuralları",
              "Çalışmayan kural güvence sağlamaz: toplayıcı kurulmamış, durmuş veya sonuç elle girilmiyor olabilir.",
              "low", rows(db, """SELECT id, code, name AS title FROM tdr_dq_rules WHERE status='active' AND (last_run_at IS NULL
              OR last_run_at < ?) ORDER BY code""", (stale,)), "dq_rules", link="quality", population=population),
    ]


def seed(db):
    for code, (value, description) in DEFAULT_POLICIES.items():
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))


def register(app):
    app.route("GET", API + "/collector/quality", collector_plan)
    app.route("POST", API + "/collector/quality", collector_results, max_body=MAX_UPLOAD_BODY)
    app.route("GET", API + "/datagov/quality", overview)
    app.route("GET", API + "/datagov/quality/rules", rule_list)
    app.route("GET", API + "/dq_rules/{id}/context", rule_context)
    app.route("POST", API + "/dq_rules/{id}/results", manual_result)
    app.route("POST", API + "/dq_anomalies/{id}/acknowledge", acknowledge)
    app.route("GET", API + "/data_tables/{id}/quality", table_quality)
    app.route("GET", API + "/data_columns/{id}/quality", column_quality)
