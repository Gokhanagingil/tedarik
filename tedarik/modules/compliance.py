"""Uyum (ikinci hat) — grc modülünün parçası (K-026).

- Yükümlülük envanteri: mevzuat (KVKK, BDDK, SPK, TCMB, BTK...) ve sözleşme yükümlülükleri madde bazında; yükümlülük →
  kontrol ve standart maddesi eşlemesi; uyum durumu kontrollerin son test sonucundan ve açık bulgulardan türetilir;
  "değişiklik incelemesi" etkilenen kontrol, süreç ve maddeleri gösterir.
- Politika istisnaları: gerekçe, telafi edici kontrol, kapsam ve süre; talep eden onaylayamaz (dört göz); süre politikayla
  sınırlı; süresi dolan istisna kendiliğinden "süresi doldu" olur, bitişten önce hatırlatılır.
- Okundu beyanı (attestation): yayımlanmış politikanın geçerli revizyonu için kampanya; hedef kişiler beyanı kendisi verir,
  verilen beyan değiştirilemez; kampanya kapanınca sonuç dosyası kanıt olarak politikaya eşli kontrollere bağlanır.
- Uygulanabilirlik bildirimi (SoA): maddenin uygulanabilirliği, gerekçesi, karşılayan kontroller ve son sonuçları,
  istisnalar, dokümanlar ve maddeyi etkileyen açık bulgular; yazdırılabilir ve CSV.
"""
import csv
import io
import json
from datetime import date, timedelta

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, Raw
from ..schema import RESOURCES, Resource, fk
from . import reminder
from .core import policy
from .grc import ASSURANCE, CONTRIBUTORS, _date, _ids, store_file

M = "grc"
REGULATORS = ("kvkk", "bddk", "spk", "tcmb", "btk", "epdk", "masak", "sgk", "customer", "other")

OBLIGATIONS = Resource("obligations", "Yükümlülükler", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "source_type": "TEXT NOT NULL DEFAULT 'law'",
    "source": "TEXT NOT NULL", "article": "TEXT", "regulator": "TEXT", "description": "TEXT",
    "company_id": fk("companies", False), "process_id": fk("processes", False), "owner": "TEXT",
    "applicability": "TEXT NOT NULL DEFAULT 'applicable'", "status": "TEXT NOT NULL DEFAULT 'active'",
    "criticality": "TEXT NOT NULL DEFAULT 'medium'", "effective_date": "DATE", "review_date": "DATE",
    "penalty": "TEXT", "reference_url": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="YKM", search=("code", "title", "source", "article"), write_roles={"ADMIN", "AUDITOR"},
    enums={"source_type": ("law", "regulation", "communique", "contract", "standard", "internal", "other"),
           "regulator": REGULATORS, "applicability": ("applicable", "not_applicable", "under_review"),
           "status": ("active", "retired"), "criticality": ("low", "medium", "high", "critical")})
OBLIGATION_LINKS = {"controls": ("obligation_controls", "control_id", "controls"),
                    "clauses": ("obligation_clauses", "clause_id", "clauses")}
for _name, (_table, _col, _target) in OBLIGATION_LINKS.items():
    Resource(_table, "Yükümlülük eşlemesi", {"obligation_id": fk("obligations", cascade=True), _col: fk(_target, cascade=True)},
             module=M, unique=(("obligation_id", _col),), api=(), search=())

EXCEPTIONS = Resource("policy_exceptions", "Politika İstisnaları", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "document_id": fk("documents", False),
    "control_id": fk("controls", False), "obligation_id": fk("obligations", False), "risk_id": fk("supplier_risks", False),
    "scope": "TEXT NOT NULL", "justification": "TEXT NOT NULL", "compensating_controls": "TEXT",
    "risk_level": "TEXT NOT NULL DEFAULT 'medium'", "owner": "TEXT NOT NULL", "org_unit_id": fk("org_units", False),
    "start_date": "DATE NOT NULL", "end_date": "DATE NOT NULL", "status": "TEXT NOT NULL DEFAULT 'requested'",
    "requested_by": "TEXT", "approver": "TEXT", "decided_at": "TIMESTAMP", "decision_note": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="IST", code_yearly=True, search=("code", "title", "scope"), write_roles=CONTRIBUTORS,
    readonly=("status", "requested_by", "approver", "decided_at", "decision_note"),
    enums={"risk_level": ("low", "medium", "high", "critical"),
           "status": ("requested", "approved", "rejected", "expired", "revoked")})

CAMPAIGNS = Resource("attestation_campaigns", "Okundu Beyanı Kampanyaları", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "document_id": fk("documents"), "revision": "INTEGER",
    "statement": "TEXT NOT NULL", "audience": "TEXT NOT NULL DEFAULT 'all'", "due_date": "DATE NOT NULL",
    "status": "TEXT NOT NULL DEFAULT 'draft'", "launched_at": "TIMESTAMP", "closed_at": "TIMESTAMP",
    "evidence_id": fk("evidence", False), "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"},
    module=M, code_prefix="OKB", search=("code", "title"), write_roles={"ADMIN"},
    readonly=("revision", "status", "launched_at", "closed_at", "evidence_id", "created_by"),
    enums={"audience": ("all", "units"), "status": ("draft", "open", "closed")})
Resource("attestation_units", "Okundu beyanı hedef birimi", {
    "campaign_id": fk("attestation_campaigns", cascade=True), "org_unit_id": fk("org_units")},
    module=M, unique=(("campaign_id", "org_unit_id"),), api=(), search=())
ATTESTATIONS = Resource("attestations", "Okundu Beyanları", {
    "campaign_id": fk("attestation_campaigns"), "username": "TEXT NOT NULL", "display_name": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'pending'", "acknowledged_at": "TIMESTAMP", "revision": "INTEGER",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, unique=(("campaign_id", "username"),), api=("list", "get"), search=("username", "display_name"),
    write_roles={"ADMIN"}, enums={"status": ("pending", "acknowledged")})

ATTESTATIONS.row_filter = lambda p: ("1=1", ()) if p is None or p.role in ASSURANCE else ("username = ?", (p.username,))

DEFAULT_POLICIES = {
    "exceptions.max_days": (365, "Politika istisnasının en uzun süresi (gün); daha uzun süre yeniden onay ister."),
    "exceptions.warning_days": (14, "İstisna bitişinden bu kadar gün önce sahibine ve onaylayana hatırlatılır."),
}


def _today():
    return date.today().isoformat()


def _notify(db, *args, **kw):
    from .. import notify
    return notify.enqueue(db, *args, **kw)


# ------------------------------------------------------------------ yükümlülükler

def _obligation_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    for key, label in (("effective_date", "Yürürlük tarihi"), ("review_date", "Gözden geçirme tarihi")):
        _date(merged.get(key), label)
    if merged.get("reference_url") and not str(merged["reference_url"]).startswith("https://"):
        raise crud.Invalid("Kaynak bağlantısı https:// ile başlamalı")


OBLIGATIONS.before_save = _obligation_rules


def obligation_state(db, obligation_id):
    """Yükümlülüğün uyum durumu: kontrol yoksa değerlendirilmedi; başarısız sonuç veya açık bulgu uyumsuz; hepsi
    başarılıysa uyumlu; aksi kısmen. Etkin istisna varsa ayrıca belirtilir."""
    controls = rows(db, """SELECT k.id, k.code, k.name, k.active, (SELECT x.status FROM tdr_executions x WHERE
        x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC LIMIT 1) AS last_status FROM tdr_controls k
        JOIN tdr_obligation_controls m ON m.control_id=k.id WHERE m.obligation_id=? ORDER BY k.code""", (obligation_id,))
    ids = [k["id"] for k in controls] or [0]
    findings = rows(db, f"""SELECT id, code, title, severity, status FROM tdr_findings WHERE status IN ('open','in_progress')
        AND control_id IN ({','.join('?' * len(ids))}) ORDER BY id DESC""", ids)
    exceptions = rows(db, """SELECT id, code, title, end_date, status FROM tdr_policy_exceptions WHERE status='approved'
        AND end_date >= ? AND (obligation_id=? OR control_id IN (SELECT control_id FROM tdr_obligation_controls
        WHERE obligation_id=?))""", (_today(), obligation_id, obligation_id))
    statuses = [k["last_status"] for k in controls if k["active"]]
    if not controls:
        state = "not_assessed"
    elif "fail" in statuses or findings:
        state = "non_compliant"
    elif statuses and all(s == "pass" for s in statuses):
        state = "compliant"
    else:
        state = "partial"
    return {"state": state, "controls": controls, "findings": findings, "exceptions": exceptions}


def obligation_context(c):
    authz.check(c.principal, OBLIGATIONS, "read")
    item = crud.get(c.db, OBLIGATIONS, c.params["id"])
    item.update(obligation_state(c.db, item["id"]))
    item["clauses"] = rows(c.db, """SELECT cl.id, cl.code, cl.title, s.code AS standard FROM tdr_clauses cl
        JOIN tdr_obligation_clauses m ON m.clause_id=cl.id JOIN tdr_standards s ON s.id=cl.standard_id
        WHERE m.obligation_id=? ORDER BY s.code, cl.code""", (item["id"],))
    ids = [k["id"] for k in item["controls"]] or [0]
    marks = ",".join("?" * len(ids))
    item["processes"] = rows(c.db, f"""SELECT DISTINCT p.id, p.code, p.name FROM tdr_processes p JOIN tdr_control_processes m
        ON m.process_id=p.id WHERE m.control_id IN ({marks}) ORDER BY p.name""", ids)
    item["documents"] = rows(c.db, f"""SELECT DISTINCT d.id, d.code, d.title, d.status FROM tdr_documents d JOIN
        tdr_control_documents m ON m.document_id=d.id WHERE m.control_id IN ({marks}) ORDER BY d.code""", ids)
    return item


def obligation_links(c):
    obligation = crud.get(c.db, OBLIGATIONS, c.params["id"])
    authz.check(c.principal, OBLIGATIONS, "write")
    changed = {}
    for key, (table, col, target) in OBLIGATION_LINKS.items():
        if key not in c.body:
            continue
        ids = _ids(c.body[key], key)
        res = RESOURCES[target]
        if ids and len(rows(c.db, f"SELECT id FROM {res.table} WHERE id IN ({','.join('?' * len(ids))})", ids)) != len(ids):
            raise crud.Invalid(f"{res.label}: bulunamayan kayıt seçildi")
        c.db.execute(f"DELETE FROM tdr_{table} WHERE obligation_id=?", (obligation["id"],))
        for target_id in ids:
            c.db.execute(f"INSERT INTO tdr_{table} (obligation_id, {col}) VALUES (?,?)", (obligation["id"], target_id))
        changed[key] = ids
    audit.log(c.db, c.principal, "LINK", "obligations", obligation["id"], changed)
    return obligation_context(c)


def obligations_summary(c):
    authz.check(c.principal, OBLIGATIONS, "read")
    out, by_regulator = {"compliant": 0, "partial": 0, "non_compliant": 0, "not_assessed": 0}, {}
    items = []
    for o in rows(c.db, "SELECT id, code, title, regulator, source, article, criticality, owner, review_date FROM "
                        "tdr_obligations WHERE status='active' AND applicability='applicable' ORDER BY code"):
        st = obligation_state(c.db, o["id"])
        out[st["state"]] += 1
        reg = by_regulator.setdefault(o["regulator"] or "other", {"compliant": 0, "partial": 0, "non_compliant": 0,
                                                                  "not_assessed": 0})
        reg[st["state"]] += 1
        items.append({**o, "state": st["state"], "controls": len(st["controls"]), "findings": len(st["findings"]),
                      "exceptions": len(st["exceptions"])})
    return {"counts": out, "by_regulator": by_regulator, "items": items}


def change_review(c):
    """Mevzuat değişikliği: yükümlülüğü incelemeye alır, değişikliği kaydeder, etkilenenleri döndürür."""
    authz.require_human(c.principal)
    authz.check(c.principal, OBLIGATIONS, "write")
    o = crud.get(c.db, OBLIGATIONS, c.params["id"])
    note = (c.body.get("note") or "").strip()
    if len(note) < 10:
        raise crud.Invalid("Değişikliği kısaca açıklayın (ne değişti, yürürlük tarihi)")
    c.db.execute("UPDATE tdr_obligations SET applicability='under_review', updated_at=? WHERE id=?", (utcnow(), o["id"]))
    audit.log(c.db, c.principal, "CHANGE_REVIEW", "obligations", o["id"], {"note": note})
    if o["owner"]:
        _notify(c.db, "exception.requested", f"Mevzuat değişikliği incelemesi: {o['code']} {o['title']}", note,
                users=[o["owner"]], link=f"#/r/obligations/{o['id']}", object_type="obligations", object_id=o["id"])
    return obligation_context(c)


# ------------------------------------------------------------------ politika istisnaları

def _effective_status(row):
    if row["status"] == "approved" and str(row["end_date"]) < _today():
        return "expired"
    return row["status"]


def _exception_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    _date(merged.get("start_date"), "Başlangıç")
    _date(merged.get("end_date"), "Bitiş")
    if str(merged["end_date"]) < str(merged["start_date"]):
        raise crud.Invalid("Bitiş başlangıçtan önce olamaz")
    days = (date.fromisoformat(str(merged["end_date"])[:10]) - date.fromisoformat(str(merged["start_date"])[:10])).days
    limit = int(policy(db, "exceptions.max_days", 365))
    if days > limit:
        raise crud.Invalid(f"İstisna en çok {limit} gün olabilir; daha uzun ihtiyaç yeniden onay ister")
    if not any(merged.get(k) for k in ("document_id", "control_id", "obligation_id")):
        raise crud.Invalid("İstisnanın hangi politika, kontrol veya yükümlülük için istendiğini seçin")
    if merged.get("risk_level") in ("high", "critical") and not (merged.get("compensating_controls") or "").strip():
        raise crud.Invalid("Yüksek ve kritik istisnada telafi edici kontrol zorunlu")
    if current is None:
        data["requested_by"] = principal.username if principal else "system"
        data["status"] = "requested"
    elif current["status"] != "requested":
        raise crud.Conflict("Karar verilmiş istisna değiştirilemez; yeni talep açın")


EXCEPTIONS.before_save = _exception_rules


def _exception_scope(db, record):
    return [record.get("org_unit_id")]


EXCEPTIONS.scope = _exception_scope


def decide_exception(c):
    authz.require_human(c.principal)
    ex = crud.get(c.db, EXCEPTIONS, c.params["id"])
    if c.principal.role != "ADMIN":
        raise crud.Forbidden("İstisnayı Yönetici onaylar")
    if ex["status"] != "requested":
        raise crud.Conflict("İstisna karar beklemiyor")
    if c.principal.username in (ex["requested_by"], ex["owner"]):
        raise crud.Forbidden("Talep eden veya istisna sahibi onaylayamaz (dört göz)")
    decision, note = c.body.get("decision"), (c.body.get("note") or "").strip()
    if decision not in ("approve", "reject"):
        raise crud.Invalid("decision: approve veya reject")
    if not note:
        raise crud.Invalid("Karar gerekçesi gerekli")
    status = "approved" if decision == "approve" else "rejected"
    c.db.execute("UPDATE tdr_policy_exceptions SET status=?, approver=?, decided_at=?, decision_note=?, updated_at=? "
                 "WHERE id=?", (status, c.principal.username, utcnow(), note, utcnow(), ex["id"]))
    audit.log(c.db, c.principal, "DECIDE", "policy_exceptions", ex["id"], {"decision": decision, "note": note})
    _notify(c.db, "exception.requested", f"İstisna {'onaylandı' if status == 'approved' else 'reddedildi'}: {ex['title']}",
            note, users=[ex["owner"], ex["requested_by"]], link=f"#/r/policy_exceptions/{ex['id']}",
            object_type="policy_exceptions", object_id=ex["id"])
    return crud.get(c.db, EXCEPTIONS, ex["id"])


def revoke_exception(c):
    authz.require_human(c.principal)
    ex = crud.get(c.db, EXCEPTIONS, c.params["id"])
    if c.principal.role != "ADMIN":
        raise crud.Forbidden("İstisnayı Yönetici geri alır")
    if _effective_status(ex) != "approved":
        raise crud.Conflict("Yalnızca geçerli istisna geri alınır")
    note = (c.body.get("note") or "").strip()
    if not note:
        raise crud.Invalid("Geri alma gerekçesi gerekli")
    c.db.execute("UPDATE tdr_policy_exceptions SET status='revoked', decision_note=?, updated_at=? WHERE id=?",
                 ((ex["decision_note"] or "") + f"\nGeri alındı: {note}", utcnow(), ex["id"]))
    audit.log(c.db, c.principal, "REVOKE", "policy_exceptions", ex["id"], {"note": note})
    return crud.get(c.db, EXCEPTIONS, ex["id"])


def expire_exceptions(db):
    expired = rows(db, "SELECT id FROM tdr_policy_exceptions WHERE status='approved' AND end_date < ?", (_today(),))
    for r in expired:
        db.execute("UPDATE tdr_policy_exceptions SET status='expired', updated_at=? WHERE id=?", (utcnow(), r["id"]))
    return len(expired)


@reminder
def exception_reminders(db, app):
    if not app.enabled("grc"):
        return 0
    from .. import audit as audit_log
    from ..notify import _Principal
    n_expired = expire_exceptions(db)
    if n_expired:
        audit_log.log(db, _Principal(), "EXPIRE", "policy_exceptions", None, {"expired": n_expired})
    days = int(policy(db, "exceptions.warning_days", 14))
    n = 0
    for r in rows(db, "SELECT id, code, title, owner, approver, end_date FROM tdr_policy_exceptions WHERE status='approved' "
                      "AND end_date <= ?", ((date.today() + timedelta(days=days)).isoformat(),)):
        n += _notify(db, "exception.expiring", f"İstisna sona eriyor: {r['code']} {r['title']}",
                     f"Bitiş: {r['end_date']}. Gerekirse yenileme talebi açın veya telafi edici kontrolü kalıcılaştırın.",
                     users=[r["owner"], r["approver"]], link=f"#/r/policy_exceptions/{r['id']}",
                     object_type="policy_exceptions", object_id=r["id"], dedupe=f"ist:{r['id']}:{r['end_date']}")
    return n


def active_exceptions(db, control_ids=None, document_ids=None):
    sql = "SELECT * FROM tdr_policy_exceptions WHERE status='approved' AND end_date >= ?"
    args = [_today()]
    if control_ids is not None:
        ids = list(control_ids) or [0]
        sql += f" AND control_id IN ({','.join('?' * len(ids))})"
        args += ids
    return rows(db, sql, args)


# ------------------------------------------------------------------ okundu beyanı

def _campaign_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    _date(merged.get("due_date"), "Son tarih")
    if current is None:
        data["created_by"] = principal.username if principal else "system"
        data["status"] = "draft"
        doc = crud.get(db, RESOURCES["documents"], merged["document_id"])
        if doc["status"] not in ("published", "active"):
            raise crud.Invalid("Yalnızca yayımlanmış doküman için okundu beyanı istenir")
    elif current["status"] != "draft" and set(data) - {"due_date", "updated_at"}:
        raise crud.Conflict("Başlamış kampanyada yalnızca son tarih değiştirilebilir")


CAMPAIGNS.before_save = _campaign_rules


def _audience(db, campaign):
    if campaign["audience"] == "units":
        return rows(db, """SELECT DISTINCT u.username, u.display_name FROM users u JOIN tdr_user_units m ON m.user_id=u.id
            JOIN tdr_attestation_units t ON t.org_unit_id=m.org_unit_id WHERE t.campaign_id=? AND u.is_active=1""",
                    (campaign["id"],))
    return rows(db, "SELECT username, display_name FROM users WHERE is_active=1")


def campaign_units(c):
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    authz.check(c.principal, CAMPAIGNS, "write")
    if campaign["status"] != "draft":
        raise crud.Conflict("Başlamış kampanyanın hedefi değişmez")
    ids = _ids(c.body.get("org_unit_ids", []), "Birimler")
    c.db.execute("DELETE FROM tdr_attestation_units WHERE campaign_id=?", (campaign["id"],))
    for uid in ids:
        c.db.execute("INSERT INTO tdr_attestation_units (campaign_id, org_unit_id) VALUES (?,?)", (campaign["id"], uid))
    audit.log(c.db, c.principal, "LINK", "attestation_campaigns", campaign["id"], {"org_unit_ids": ids})
    return campaign_context_data(c.db, campaign["id"])


def launch(c):
    authz.require_human(c.principal)
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    authz.check(c.principal, CAMPAIGNS, "write")
    if campaign["status"] != "draft":
        raise crud.Conflict("Kampanya zaten başlamış")
    doc = crud.get(c.db, RESOURCES["documents"], campaign["document_id"])
    people = _audience(c.db, campaign)
    if not people:
        raise crud.Invalid("Hedef kitlede etkin kullanıcı yok")
    now = utcnow()
    revision = doc.get("current_revision")
    for p in people:
        c.db.execute("INSERT INTO tdr_attestations (campaign_id, username, display_name, status, revision, created_at) "
                     "VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                     (campaign["id"], p["username"], p["display_name"], "pending", revision, now))
    c.db.execute("UPDATE tdr_attestation_campaigns SET status='open', revision=?, launched_at=?, updated_at=? WHERE id=?",
                 (revision, now, now, campaign["id"]))
    audit.log(c.db, c.principal, "LAUNCH", "attestation_campaigns", campaign["id"], {"people": len(people)})
    _notify(c.db, "attestation.assigned", f"Okundu beyanı: {doc['title']}",
            f"{campaign['title']}\n{campaign['statement']}\nSon tarih: {campaign['due_date']}",
            users=[p["username"] for p in people], link="#/my-work", object_type="attestation_campaigns",
            object_id=campaign["id"])
    return campaign_context_data(c.db, campaign["id"])


def acknowledge(c):
    """Kişi yalnızca kendi beyanını verir; verilen beyan değişmez."""
    authz.require_human(c.principal)
    a = crud.get(c.db, ATTESTATIONS, c.params["id"])
    if a["username"] != c.principal.username:
        raise crud.Forbidden("Beyanı yalnızca kişinin kendisi verir")
    campaign = crud.get(c.db, CAMPAIGNS, a["campaign_id"])
    if campaign["status"] != "open":
        raise crud.Conflict("Kampanya açık değil")
    if a["status"] == "acknowledged":
        raise crud.Conflict("Beyan zaten verildi")
    if c.body.get("confirm") is not True:
        raise crud.Invalid("Beyan onayı gerekli")
    c.db.execute("UPDATE tdr_attestations SET status='acknowledged', acknowledged_at=? WHERE id=?", (utcnow(), a["id"]))
    audit.log(c.db, c.principal, "ACKNOWLEDGE", "attestations", a["id"],
              {"campaign": campaign["code"], "revision": a["revision"]})
    return crud.get(c.db, ATTESTATIONS, a["id"])


def close_campaign(c):
    """Kampanyayı kapatır; sonuç dosyası kanıt olarak kaydedilir ve politikaya eşli kontrollere bağlanır."""
    authz.require_human(c.principal)
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    authz.check(c.principal, CAMPAIGNS, "write")
    if campaign["status"] != "open":
        raise crud.Conflict("Yalnızca açık kampanya kapatılır")
    doc = crud.get(c.db, RESOURCES["documents"], campaign["document_id"])
    people = rows(c.db, "SELECT username, display_name, status, acknowledged_at, revision FROM tdr_attestations "
                        "WHERE campaign_id=? ORDER BY username", (campaign["id"],))
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Kullanıcı", "Ad", "Durum", "Beyan zamanı", "Doküman revizyonu"])
    for p in people:
        writer.writerow([p["username"], p["display_name"] or "", "Okudu, kabul etti" if p["status"] == "acknowledged" else
                         "Beyan vermedi", p["acknowledged_at"] or "", p["revision"] or ""])
    done = sum(1 for p in people if p["status"] == "acknowledged")
    evidence_id = crud.insert(c.db, RESOURCES["evidence"], {
        "title": f"Okundu beyanı sonuçları — {doc['title']} ({campaign['code']})",
        "description": f"{len(people)} kişiden {done} beyan ({round(100 * done / len(people)) if people else 0}%).",
        "source": "system", "period_start": str(campaign["launched_at"])[:10], "period_end": _today()}, c.principal)
    store_file(c.db, evidence_id, f"okundu-beyani-{campaign['code']}.csv", ("﻿" + buffer.getvalue()).encode("utf-8"),
               c.principal.username)
    for r in rows(c.db, "SELECT control_id FROM tdr_control_documents WHERE document_id=?", (doc["id"],)):
        c.db.execute("INSERT INTO tdr_evidence_controls (evidence_id, control_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                     (evidence_id, r["control_id"]))
    c.db.execute("UPDATE tdr_attestation_campaigns SET status='closed', closed_at=?, evidence_id=?, updated_at=? WHERE id=?",
                 (utcnow(), evidence_id, utcnow(), campaign["id"]))
    audit.log(c.db, c.principal, "CLOSE", "attestation_campaigns", campaign["id"], {"acknowledged": done,
                                                                                    "people": len(people)})
    return campaign_context_data(c.db, campaign["id"])


def campaign_context_data(db, campaign_id):
    item = crud.get(db, CAMPAIGNS, campaign_id)
    item["document"] = one(db, "SELECT id, code, title, status FROM tdr_documents WHERE id=?", (item["document_id"],))
    item["units"] = rows(db, "SELECT o.id, o.name FROM tdr_org_units o JOIN tdr_attestation_units t ON t.org_unit_id=o.id "
                             "WHERE t.campaign_id=? ORDER BY o.name", (campaign_id,))
    item["people"] = rows(db, "SELECT id, username, display_name, status, acknowledged_at FROM tdr_attestations "
                              "WHERE campaign_id=? ORDER BY status DESC, display_name", (campaign_id,))
    total = len(item["people"])
    done = sum(1 for p in item["people"] if p["status"] == "acknowledged")
    item["progress"] = {"total": total, "acknowledged": done, "pct": round(100 * done / total, 1) if total else None}
    return item


def campaign_context(c):
    authz.check(c.principal, CAMPAIGNS, "read")
    return campaign_context_data(c.db, c.params["id"])


def my_attestations(c):
    authz.require_human(c.principal)
    return rows(c.db, """SELECT a.id, a.status, a.acknowledged_at, k.code, k.title, k.statement, k.due_date,
        d.id AS document_id, d.code AS document_code, d.title AS document_title FROM tdr_attestations a
        JOIN tdr_attestation_campaigns k ON k.id=a.campaign_id JOIN tdr_documents d ON d.id=k.document_id
        WHERE a.username=? AND k.status='open' ORDER BY a.status DESC, k.due_date""", (c.principal.username,))


# ------------------------------------------------------------------ uygulanabilirlik bildirimi (SoA)

def soa_data(db, standard_id):
    from .grc_library import findings_for_clause
    std = crud.get(db, RESOURCES["standards"], standard_id)
    clauses = rows(db, """SELECT cl.id, cl.code, cl.title, cl.clause_type, cl.applicable, cl.justification, cl.parent_id,
        (SELECT COUNT(*) FROM tdr_clauses ch WHERE ch.parent_id=cl.id) AS children FROM tdr_clauses cl
        WHERE cl.standard_id=? ORDER BY COALESCE(cl.position, 0), cl.code""", (standard_id,))
    controls = {}
    for r in rows(db, """SELECT m.clause_id, k.id, k.code, k.name, k.active, (SELECT x.status FROM tdr_executions x
            WHERE x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC LIMIT 1) AS last_status,
            (SELECT x.executed_at FROM tdr_executions x WHERE x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC
             LIMIT 1) AS last_at FROM tdr_control_clauses m JOIN tdr_controls k ON k.id=m.control_id
            JOIN tdr_clauses cl ON cl.id=m.clause_id WHERE cl.standard_id=?""", (standard_id,)):
        controls.setdefault(r["clause_id"], []).append(r)
    documents = {}
    for r in rows(db, """SELECT m.clause_id, d.code, d.title FROM tdr_document_clauses m JOIN tdr_documents d
            ON d.id=m.document_id JOIN tdr_clauses cl ON cl.id=m.clause_id WHERE cl.standard_id=?""", (standard_id,)):
        documents.setdefault(r["clause_id"], []).append(f"{r['code']} {r['title']}")
    exceptions = {}
    for e in active_exceptions(db):
        if e["control_id"]:
            exceptions.setdefault(e["control_id"], []).append(e["code"])
    out, counts = [], {"implemented": 0, "partial": 0, "not_implemented": 0, "not_applicable": 0}
    findings_cache = {}
    for cl in clauses:
        if cl["children"] and cl["clause_type"] in (None, "family", "function", "category", "clause") and not controls.get(cl["id"]):
            continue                                      # başlık maddeleri SoA satırı değildir
        ks = [k for k in controls.get(cl["id"], []) if k["active"]]
        statuses = [k["last_status"] for k in ks]
        if not cl["applicable"]:
            state = "not_applicable"
        elif not ks:
            state = "not_implemented"
        elif statuses and all(s == "pass" for s in statuses):
            state = "implemented"
        else:
            state = "partial"
        if state in ("implemented", "partial"):
            if cl["id"] not in findings_cache:
                findings_cache[cl["id"]] = findings_for_clause(db, cl["id"])
            if any(f["level"] in ("direct", "certain") for f in findings_cache[cl["id"]]):
                state = "partial"
        counts[state] += 1
        exc = sorted({x for k in ks for x in exceptions.get(k["id"], [])})
        out.append({"id": cl["id"], "code": cl["code"], "title": cl["title"], "applicable": cl["applicable"],
                    "justification": cl["justification"], "state": state,
                    "controls": [{"code": k["code"], "name": k["name"], "last_status": k["last_status"],
                                  "last_at": k["last_at"]} for k in ks],
                    "documents": documents.get(cl["id"], []), "exceptions": exc,
                    "open_findings": len(findings_cache.get(cl["id"], []))})
    return {"standard": std, "rows": out, "counts": counts, "generated_at": utcnow(),
            "note": "Uygulama durumu kontrollerin en son test sonucundan ve maddeyi etkileyen açık bulgulardan türetilir; "
                    "sertifikasyon kararı değildir."}


def soa(c):
    authz.check(c.principal, RESOURCES["clauses"], "read")
    data = soa_data(c.db, c.params["id"])
    if c.query.get("format") != "csv":
        return data
    labels = {"implemented": "Uygulanıyor", "partial": "Kısmen", "not_implemented": "Uygulanmıyor",
              "not_applicable": "Kapsam dışı"}
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Madde", "Başlık", "Uygulanabilir", "Gerekçe", "Durum", "Kontroller", "Son sonuçlar", "Dokümanlar",
                     "İstisnalar", "Açık bulgu"])
    for r in data["rows"]:
        writer.writerow([r["code"], r["title"], "Evet" if r["applicable"] else "Hayır", r["justification"] or "",
                         labels[r["state"]], ", ".join(k["code"] for k in r["controls"]),
                         ", ".join(f"{k['code']}:{k['last_status'] or '-'}" for k in r["controls"]),
                         " | ".join(r["documents"]), ", ".join(r["exceptions"]), r["open_findings"]])
    name = f"SoA-{data['standard']['code']}-{data['standard']['version'] or ''}.csv".replace("/", "-").replace(" ", "_")
    return Raw(("﻿" + buffer.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", name)


def register(app):
    app.route("GET", API + "/obligations/summary", obligations_summary)
    app.route("GET", API + "/obligations/{id}/context", obligation_context)
    app.route("POST", API + "/obligations/{id}/links", obligation_links)
    app.route("POST", API + "/obligations/{id}/change-review", change_review)
    app.route("POST", API + "/policy_exceptions/{id}/decide", decide_exception)
    app.route("POST", API + "/policy_exceptions/{id}/revoke", revoke_exception)
    app.route("POST", API + "/attestation_campaigns/{id}/units", campaign_units)
    app.route("POST", API + "/attestation_campaigns/{id}/launch", launch)
    app.route("POST", API + "/attestation_campaigns/{id}/close", close_campaign)
    app.route("GET", API + "/attestation_campaigns/{id}/context", campaign_context)
    app.route("POST", API + "/attestations/{id}/acknowledge", acknowledge)
    app.route("GET", API + "/my/attestations", my_attestations)
    app.route("GET", API + "/standards/{id}/soa", soa)


def seed(db):
    for code, (value, description) in DEFAULT_POLICIES.items():
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))
