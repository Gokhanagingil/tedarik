"""Güvence (üçüncü hat) — grc modülünün parçası (K-026).

- Kanıt talepleri (PBC): denetçi kontrol başına talep açar (entegre test planından toplu), talep kişiye atanır, kişi
  kanıtı yükler veya mevcut güncel kanıtı gösterir, denetçi kabul eder veya gerekçeyle iade eder. Kabul edilen kanıt
  denetime ve kontrole bağlanır; bir kanıt kontrolün eşlendiği tüm standart maddelerine sayılır.
- Çalışma kâğıtları: test adımı, örneklem, sonuç; hazırlayan "gözden geçirmeye gönder" der, hazırlayandan farklı bir
  denetçi onaylar veya iade eder (IIA 2340). Politika açıksa gözden geçirilmemiş kâğıt denetimin tamamlanmasını engeller.
- Yönetim yanıtı: bulguya yönetimin yanıtı (katılıyor / kısmen / katılmıyor, eylem planı, hedef tarih).
- Denetim raporu: kapsam, sonuç, bulgular (standartlar arası etki), yönetim yanıtları, test sonuçları; yazdırılabilir.
- Risk bazlı yıllık denetim planı: denetim evreni (süreç, şirket, tedarikçi, uygulama, standart, birim), öncelik puanı
  (doğal risk, açık riskler, açık bulgular, son denetimden geçen süre), plan kalemleri ve plan–gerçekleşme.
- Sertifikalar: belgelendirme ve gözetim denetimi takibi; süresi yaklaşınca hatırlatma.
- Dış denetçi: süreli hesap ve denetim kapsamı (auth.py, http.py).
"""
import json
from datetime import date, timedelta

from .. import audit, auth as authz, crud, files
from ..db import one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY
from ..schema import RESOURCES, Resource, fk
from . import reminder
from .core import policy
from .grc import (ASSURANCE, AUDIT_COMPLETION_CHECKS, AUDIT_CONTEXT_EXTRAS, AUDITS, CONTRIBUTORS, EVIDENCE, FINDINGS,
                  RESULTS, _date, _evidence_links, audit_scoped, evidence_filter, evidence_visible, store_file)

M = "grc"

REQUESTS = Resource("evidence_requests", "Kanıt Talepleri", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "description": "TEXT", "audit_id": fk("audits", False),
    "control_id": fk("controls", False), "clause_id": fk("clauses", False), "assignee": "TEXT NOT NULL",
    "org_unit_id": fk("org_units", False), "due_date": "DATE NOT NULL", "status": "TEXT NOT NULL DEFAULT 'requested'",
    "evidence_id": fk("evidence", False), "response_note": "TEXT", "review_note": "TEXT", "requested_by": "TEXT",
    "submitted_at": "TIMESTAMP", "reviewed_by": "TEXT", "reviewed_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="KTT", code_yearly=True, search=("code", "title", "assignee"), write_roles=ASSURANCE,
    readonly=("status", "evidence_id", "response_note", "review_note", "requested_by", "submitted_at", "reviewed_by",
              "reviewed_at"),
    enums={"status": ("requested", "submitted", "accepted", "rejected", "cancelled")})

WORKPAPERS = Resource("workpapers", "Çalışma Kâğıtları", {
    "code": "TEXT UNIQUE", "audit_id": fk("audits"), "control_id": fk("controls", False), "title": "TEXT NOT NULL",
    "objective": "TEXT", "procedure": "TEXT", "sample": "TEXT", "sample_size": "INTEGER", "exceptions_found": "INTEGER",
    "result": "TEXT", "conclusion": "TEXT", "preparer": "TEXT", "prepared_at": "TIMESTAMP",
    "status": "TEXT NOT NULL DEFAULT 'draft'", "reviewer": "TEXT", "reviewed_at": "TIMESTAMP", "review_note": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="CKG", code_yearly=True, search=("code", "title"), write_roles=ASSURANCE,
    readonly=("status", "preparer", "prepared_at", "reviewer", "reviewed_at", "review_note"),
    enums={"result": RESULTS, "status": ("draft", "ready", "reviewed", "returned")})

UNIVERSE = Resource("audit_universe", "Denetim Evreni", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "entity_type": "TEXT NOT NULL DEFAULT 'process'",
    "process_id": fk("processes", False), "company_id": fk("companies", False), "supplier_id": fk("suppliers", False),
    "standard_id": fk("standards", False), "org_unit_id": fk("org_units", False), "owner": "TEXT",
    "inherent_rating": "INTEGER NOT NULL DEFAULT 3", "frequency_months": "INTEGER NOT NULL DEFAULT 12",
    "description": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"},
    module=M, code_prefix="DEV", write_roles=ASSURANCE,
    enums={"entity_type": ("process", "company", "supplier", "application", "standard", "org_unit", "other")})

PLANS = Resource("audit_plans", "Yıllık Denetim Planları", {
    "code": "TEXT UNIQUE", "year": "INTEGER NOT NULL UNIQUE", "title": "TEXT NOT NULL", "status": "TEXT NOT NULL DEFAULT 'draft'",
    "capacity_days": "INTEGER", "approved_by": "TEXT", "approved_at": "TIMESTAMP", "notes": "TEXT",
    "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="DPL", search=("code", "title"), write_roles=ASSURANCE,
    readonly=("approved_by", "approved_at", "created_by"), enums={"status": ("draft", "approved", "closed")})

PLAN_ITEMS = Resource("audit_plan_items", "Denetim Planı Kalemleri", {
    "plan_id": fk("audit_plans", cascade=True), "universe_id": fk("audit_universe"), "quarter": "TEXT NOT NULL DEFAULT 'Q1'",
    "audit_id": fk("audits", False), "status": "TEXT NOT NULL DEFAULT 'planned'", "priority_score": "REAL",
    "planned_days": "INTEGER", "rationale": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, unique=(("plan_id", "universe_id"),), search=("rationale",), write_roles=ASSURANCE,
    enums={"quarter": ("Q1", "Q2", "Q3", "Q4"), "status": ("planned", "deferred", "cancelled")})

CERTIFICATIONS = Resource("certifications", "Sertifikalar", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "standard_id": fk("standards", False),
    "company_id": fk("companies", False), "certification_body": "TEXT", "certificate_no": "TEXT", "scope": "TEXT",
    "issued_on": "DATE", "expires_on": "DATE NOT NULL", "next_surveillance": "DATE",
    "status": "TEXT NOT NULL DEFAULT 'active'", "evidence_id": fk("evidence", False), "last_audit_id": fk("audits", False),
    "owner": "TEXT", "notes": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="SRT", search=("code", "title", "certificate_no"), write_roles={"ADMIN", "AUDITOR"},
    enums={"status": ("active", "suspended", "expired", "withdrawn")})

DEFAULT_POLICIES = {
    "audit.require_workpaper_review": (True, "Gözden geçirilmemiş çalışma kâğıdı varken denetim tamamlanamaz (IIA 2340)."),
    "evidence_request.default_days": (10, "Kanıt talebinde varsayılan teslim süresi (gün)."),
    "certification.warning_days": (90, "Sertifika bitişinden bu kadar gün önce hatırlatma gönderilir."),
}


def _today():
    return date.today().isoformat()


def _notify(db, *args, **kw):
    from .. import notify
    return notify.enqueue(db, *args, **kw)


# ------------------------------------------------------------------ kanıt talepleri

def _request_scope(db, record):
    return [record.get("org_unit_id")]


def _request_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    _date(merged.get("due_date"), "Teslim tarihi")
    if current is None:
        data["requested_by"] = principal.username if principal else "system"
        data["status"] = "requested"
    elif current["status"] in ("accepted", "cancelled") and set(data) - {"updated_at"}:
        raise crud.Conflict("Kabul edilmiş veya iptal edilmiş talep değiştirilemez")
    if merged.get("audit_id"):
        a = one(db, "SELECT status FROM tdr_audits WHERE id=?", (merged["audit_id"],))
        if a and a["status"] in ("closed", "cancelled") and current is None:
            raise crud.Conflict("Kapalı denetime kanıt talebi açılamaz")


REQUESTS.row_filter, REQUESTS.can_read = audit_scoped()
REQUESTS.before_save = _request_rules
REQUESTS.scope = _request_scope


def _request_text(db, control, audit_id):
    clauses = rows(db, """SELECT cl.code, s.code AS std FROM tdr_control_clauses m JOIN tdr_clauses cl ON cl.id=m.clause_id
        JOIN tdr_standards s ON s.id=cl.standard_id WHERE m.control_id=? ORDER BY s.code, cl.code""", (control["id"],))
    by_std = {}
    for c in clauses:
        by_std.setdefault(c["std"], []).append(c["code"])
    lines = [f"Kontrol: {control['code']} · {control['name']}"]
    if control.get("method"):
        lines.append(f"İstenen: {control['method']}")
    if control.get("expected_result"):
        lines.append(f"Beklenen: {control['expected_result']}")
    if by_std:
        lines.append("Bu kanıt şu maddelerin hepsine sayılır: " + "; ".join(f"{k} {', '.join(v)}" for k, v in by_std.items()))
    return "\n".join(lines)


def bulk_requests(c):
    """{audit_id, due_date?, items: [{control_id, assignee}]}: kontrol başına tek talep (entegre denetim)."""
    authz.require_human(c.principal)
    authz.check(c.principal, REQUESTS, "write")
    audit_row = crud.get(c.db, AUDITS, c.body.get("audit_id"))
    items = c.body.get("items")
    if not isinstance(items, list) or not items or len(items) > 300:
        raise crud.Invalid("items: 1–300 kalem gerekli")
    due = c.body.get("due_date") or (date.today() + timedelta(days=int(policy(c.db, "evidence_request.default_days", 10)))).isoformat()
    created, skipped = [], []
    for item in items:
        control = crud.get(c.db, RESOURCES["controls"], item.get("control_id"))
        assignee = str(item.get("assignee") or control.get("owner") or "").strip()
        if not assignee:
            raise crud.Invalid(f"{control['code']}: talep edilen kişi gerekli (kontrol sahibi boş)")
        if one(c.db, "SELECT id FROM tdr_evidence_requests WHERE audit_id=? AND control_id=? AND status IN "
                     "('requested','submitted','rejected')", (audit_row["id"], control["id"])):
            skipped.append(control["code"])
            continue
        rid = crud.insert(c.db, REQUESTS, {
            "title": f"Kanıt: {control['name']}"[:300], "description": _request_text(c.db, control, audit_row["id"]),
            "audit_id": audit_row["id"], "control_id": control["id"], "assignee": assignee,
            "org_unit_id": control.get("org_unit_id"), "due_date": item.get("due_date") or due}, c.principal)
        created.append(rid)
        req = crud.get(c.db, REQUESTS, rid)
        _notify(c.db, "evidence_request.assigned", f"Kanıt talebi: {req['title']}",
                f"{audit_row['code']} {audit_row['name']} denetimi için kanıt bekleniyor. Teslim: {req['due_date']}.\n\n"
                f"{req['description']}", users=[assignee], link=f"#/r/evidence_requests/{rid}",
                object_type="evidence_requests", object_id=rid)
    audit.log(c.db, c.principal, "CREATE", "evidence_requests", None, {"audit_id": audit_row["id"],
                                                                       "created": len(created), "skipped": skipped})
    return 201, {"created": created, "skipped": skipped}


def _can_respond(principal, req):
    return principal.role in ASSURANCE or principal.username == req["assignee"]


def candidates(c):
    """Talebe gösterilebilecek mevcut güncel kanıtlar (aynı kontrol): aynı kanıtı yeniden yüklememek için."""
    req = crud.get(c.db, REQUESTS, c.params["id"])
    authz.check(c.principal, REQUESTS, "read")
    if not req["control_id"]:
        return []
    visible, args = evidence_filter(c.principal, "e")
    return rows(c.db, f"""SELECT e.id, e.code, e.title, e.current_version, e.expires_at, e.period_end FROM tdr_evidence e
        JOIN tdr_evidence_controls m ON m.evidence_id=e.id WHERE m.control_id=? AND e.status='current'
        AND (e.expires_at IS NULL OR e.expires_at >= ?) AND {visible} ORDER BY e.id DESC LIMIT 20""",
                (req["control_id"], _today(), *args))


def submit(c):
    """Talebi yanıtlar: mevcut kanıt (evidence_id) veya yeni dosya (file_name + content_base64) ve not."""
    authz.require_human(c.principal)
    req = crud.get(c.db, REQUESTS, c.params["id"])
    if not _can_respond(c.principal, req):
        raise crud.Forbidden("Talebi yalnızca atanan kişi veya denetçi yanıtlayabilir")
    if req["status"] not in ("requested", "rejected"):
        raise crud.Conflict("Bu talep yanıt beklemiyor")
    links = {"controls": [req["control_id"]] if req["control_id"] else [], "audits": [req["audit_id"]] if req["audit_id"] else [],
             "clauses": [req["clause_id"]] if req["clause_id"] else []}
    if c.body.get("evidence_id"):
        evidence = crud.get(c.db, EVIDENCE, c.body["evidence_id"])
        if not evidence_visible(c.principal, evidence, c.db):
            raise crud.NotFound("Kanıt bulunamadı")
        evidence_id = evidence["id"]
    else:
        binary = files.decode(dict(c.body))
        filename = c.body.get("file_name") or "kanit"
        files.valid_file(filename, binary)
        # yetki talep ataması üzerinden doğrulandı; birim kapsamı talebin birimidir (principal=None ile kapsam atlanır)
        evidence_id = crud.insert(c.db, EVIDENCE, {
            "title": (c.body.get("title") or req["title"])[:300], "description": c.body.get("note") or None,
            "confidentiality": c.body.get("confidentiality") or "internal", "org_unit_id": req["org_unit_id"],
            "period_start": c.body.get("period_start"), "period_end": c.body.get("period_end"),
            "expires_at": c.body.get("expires_at"), "created_by": c.principal.username}, None)
        store_file(c.db, evidence_id, filename, binary, c.principal.username)
    _evidence_links(c.db, evidence_id, links, replace=False)
    c.db.execute("UPDATE tdr_evidence_requests SET status='submitted', evidence_id=?, response_note=?, submitted_at=?, "
                 "updated_at=? WHERE id=?", (evidence_id, c.body.get("note"), utcnow(), utcnow(), req["id"]))
    audit.log(c.db, c.principal, "SUBMIT", "evidence_requests", req["id"], {"evidence_id": evidence_id})
    _notify(c.db, "evidence_request.reviewed", f"Kanıt teslim edildi: {req['title']}",
            f"{c.principal.display_name or c.principal.username} kanıtı teslim etti; incelemeniz bekleniyor.",
            users=[req["requested_by"]], link=f"#/r/evidence_requests/{req['id']}", object_type="evidence_requests",
            object_id=req["id"])
    return crud.get(c.db, REQUESTS, req["id"])


def review(c):
    authz.require_human(c.principal)
    req = crud.get(c.db, REQUESTS, c.params["id"])
    if c.principal.role not in ASSURANCE:
        raise crud.Forbidden("Kanıtı yalnızca denetçi veya yönetici inceler")
    if req["status"] != "submitted":
        raise crud.Conflict("İnceleme bekleyen bir yanıt yok")
    if c.principal.username == req["assignee"]:
        raise crud.Forbidden("Kendi teslim ettiğiniz kanıtı inceleyemezsiniz")
    decision, note = c.body.get("decision"), (c.body.get("note") or "").strip()
    if decision not in ("accept", "reject"):
        raise crud.Invalid("decision: accept veya reject")
    if decision == "reject" and not note:
        raise crud.Invalid("İade gerekçesi gerekli")
    status = "accepted" if decision == "accept" else "rejected"
    c.db.execute("UPDATE tdr_evidence_requests SET status=?, review_note=?, reviewed_by=?, reviewed_at=?, updated_at=? "
                 "WHERE id=?", (status, note or None, c.principal.username, utcnow(), utcnow(), req["id"]))
    audit.log(c.db, c.principal, "REVIEW", "evidence_requests", req["id"], {"decision": decision, "note": note})
    _notify(c.db, "evidence_request.reviewed", f"Kanıt {'kabul edildi' if status == 'accepted' else 'iade edildi'}: {req['title']}",
            note or "Kanıtınız kabul edildi.", users=[req["assignee"]], link=f"#/r/evidence_requests/{req['id']}",
            object_type="evidence_requests", object_id=req["id"])
    return crud.get(c.db, REQUESTS, req["id"])


def cancel(c):
    authz.require_human(c.principal)
    req = crud.get(c.db, REQUESTS, c.params["id"])
    authz.check(c.principal, REQUESTS, "write")
    if req["status"] in ("accepted", "cancelled"):
        raise crud.Conflict("Talep zaten sonuçlanmış")
    c.db.execute("UPDATE tdr_evidence_requests SET status='cancelled', review_note=?, updated_at=? WHERE id=?",
                 (c.body.get("note"), utcnow(), req["id"]))
    audit.log(c.db, c.principal, "CANCEL", "evidence_requests", req["id"], {"note": c.body.get("note")})
    return crud.get(c.db, REQUESTS, req["id"])


@reminder
def overdue_requests(db, app):
    if not app.enabled("grc"):
        return 0
    n = 0
    for r in rows(db, "SELECT id, title, assignee, due_date FROM tdr_evidence_requests WHERE status IN ('requested','rejected') "
                      "AND due_date < ?", (_today(),)):
        n += _notify(db, "evidence_request.overdue", f"Geciken kanıt talebi: {r['title']}",
                     f"Teslim tarihi {r['due_date']} idi.", users=[r["assignee"]], link=f"#/r/evidence_requests/{r['id']}",
                     object_type="evidence_requests", object_id=r["id"], dedupe=f"ktt-gecikme:{r['id']}:{_today()}")
    return n


# ------------------------------------------------------------------ çalışma kâğıtları

def _workpaper_rules(db, data, current, principal):
    if current is None:
        data["preparer"] = principal.username if principal else "system"
        data["status"] = "draft"
        audit_row = one(db, "SELECT status FROM tdr_audits WHERE id=?", (data.get("audit_id"),))
        if audit_row and audit_row["status"] in ("completed", "closed", "cancelled"):
            raise crud.Conflict("Sonuçlanmış denetime çalışma kâğıdı eklenemez")
    elif current["status"] == "reviewed":
        raise crud.Conflict("Gözden geçirilmiş çalışma kâğıdı değiştirilemez")
    merged = {**(current or {}), **data}
    for key in ("sample_size", "exceptions_found"):
        if merged.get(key) is not None and int(merged[key]) < 0:
            raise crud.Invalid("Sayılar negatif olamaz")
    if merged.get("sample_size") is not None and merged.get("exceptions_found") is not None and \
            int(merged["exceptions_found"]) > int(merged["sample_size"]):
        raise crud.Invalid("İstisna sayısı örneklemden büyük olamaz")


WORKPAPERS.row_filter, WORKPAPERS.can_read = audit_scoped()
WORKPAPERS.before_save = _workpaper_rules


def wp_submit(c):
    authz.require_human(c.principal)
    wp = crud.get(c.db, WORKPAPERS, c.params["id"])
    authz.check(c.principal, WORKPAPERS, "write")
    if wp["status"] not in ("draft", "returned"):
        raise crud.Conflict("Kâğıt zaten gözden geçirmede veya onaylı")
    if not (wp["procedure"] or "").strip() or not wp["result"] or not (wp["conclusion"] or "").strip():
        raise crud.Invalid("Gözden geçirmeye göndermeden önce test adımları, sonuç ve kanaat yazın")
    c.db.execute("UPDATE tdr_workpapers SET status='ready', prepared_at=?, updated_at=? WHERE id=?",
                 (utcnow(), utcnow(), wp["id"]))
    audit.log(c.db, c.principal, "SUBMIT", "workpapers", wp["id"], None)
    lead = one(c.db, "SELECT lead_auditor FROM tdr_audits WHERE id=?", (wp["audit_id"],))
    reviewers = [u["username"] for u in rows(c.db, "SELECT u.username FROM users u JOIN tdr_user_roles r ON r.user_id=u.id "
                                                   "WHERE r.role='AUDITOR' AND u.is_active=1 AND u.username<>?",
                                             (wp["preparer"],))][:5]
    _notify(c.db, "workpaper.review_requested", f"Gözden geçirme bekliyor: {wp['code']} {wp['title']}",
            f"Hazırlayan: {wp['preparer']}" + (f" · Baş denetçi: {lead['lead_auditor']}" if lead and lead["lead_auditor"] else ""),
            users=reviewers, link=f"#/r/workpapers/{wp['id']}", object_type="workpapers", object_id=wp["id"])
    return crud.get(c.db, WORKPAPERS, wp["id"])


def wp_review(c):
    authz.require_human(c.principal)
    wp = crud.get(c.db, WORKPAPERS, c.params["id"])
    if c.principal.role not in ASSURANCE:
        raise crud.Forbidden("Çalışma kâğıdını yalnızca denetçi gözden geçirir")
    if wp["status"] != "ready":
        raise crud.Conflict("Kâğıt gözden geçirmeye gönderilmemiş")
    if c.principal.username == wp["preparer"]:
        raise crud.Forbidden("Kendi hazırladığınız kâğıdı gözden geçiremezsiniz (IIA 2340)")
    decision, note = c.body.get("decision"), (c.body.get("note") or "").strip()
    if decision not in ("approve", "return"):
        raise crud.Invalid("decision: approve veya return")
    if decision == "return" and not note:
        raise crud.Invalid("İade gerekçesi gerekli")
    status = "reviewed" if decision == "approve" else "returned"
    c.db.execute("UPDATE tdr_workpapers SET status=?, reviewer=?, reviewed_at=?, review_note=?, updated_at=? WHERE id=?",
                 (status, c.principal.username, utcnow(), note or None, utcnow(), wp["id"]))
    audit.log(c.db, c.principal, "REVIEW", "workpapers", wp["id"], {"decision": decision, "note": note})
    return crud.get(c.db, WORKPAPERS, wp["id"])


def _workpaper_blockers(db, audit_id):
    if not policy(db, "audit.require_workpaper_review", True):
        return []
    n = one(db, "SELECT COUNT(*) AS n FROM tdr_workpapers WHERE audit_id=? AND status<>'reviewed'", (audit_id,))["n"]
    return [f"{n} çalışma kâğıdı gözden geçirilmedi"] if n else []


def _request_blockers(db, audit_id):
    n = one(db, "SELECT COUNT(*) AS n FROM tdr_evidence_requests WHERE audit_id=? AND status='submitted'", (audit_id,))["n"]
    return [f"{n} teslim edilmiş kanıt incelenmedi"] if n else []


AUDIT_COMPLETION_CHECKS.extend([_workpaper_blockers, _request_blockers])


def _context_extras(db, item, principal):
    item["requests"] = rows(db, """SELECT r.id, r.code, r.title, r.assignee, r.due_date, r.status, r.evidence_id,
        r.control_id, k.code AS control_code FROM tdr_evidence_requests r LEFT JOIN tdr_controls k ON k.id=r.control_id
        WHERE r.audit_id=? ORDER BY r.status, r.due_date""", (item["id"],))
    item["workpapers"] = rows(db, """SELECT w.id, w.code, w.title, w.status, w.result, w.preparer, w.reviewer,
        w.control_id, k.code AS control_code FROM tdr_workpapers w LEFT JOIN tdr_controls k ON k.id=w.control_id
        WHERE w.audit_id=? ORDER BY w.code""", (item["id"],))


AUDIT_CONTEXT_EXTRAS.append(_context_extras)


# ------------------------------------------------------------------ yönetim yanıtı

def request_response(c):
    authz.require_human(c.principal)
    finding = crud.get(c.db, FINDINGS, c.params["id"])
    if c.principal.role not in ASSURANCE:
        raise crud.Forbidden("Yönetim yanıtını denetçi ister")
    due = c.body.get("response_due") or (date.today() + timedelta(days=14)).isoformat()
    _date(due, "Yanıt tarihi")
    if not finding["owner"]:
        raise crud.Invalid("Bulgunun sahibi yok; önce sorumluyu atayın")
    c.db.execute("UPDATE tdr_findings SET response_status='pending', response_due=?, updated_at=? WHERE id=?",
                 (due, utcnow(), finding["id"]))
    audit.log(c.db, c.principal, "REQUEST_RESPONSE", "findings", finding["id"], {"response_due": due})
    _notify(c.db, "finding.response_requested", f"Yönetim yanıtı bekleniyor: {finding['code']} {finding['title']}",
            f"Bulguya {due} tarihine kadar yanıt verin: katılıyor musunuz, eylem planınız ve hedef tarih nedir?",
            users=[finding["owner"]], link=f"#/r/findings/{finding['id']}", object_type="findings", object_id=finding["id"])
    return crud.get(c.db, FINDINGS, finding["id"])


def respond(c):
    """Yönetim yanıtı: bulgu sahibi, Tedarikçi Yöneticisi veya Yönetici verir; değiştirilebilir, her değişiklik iz bırakır."""
    authz.require_human(c.principal)
    finding = crud.get(c.db, FINDINGS, c.params["id"])
    if not (c.principal.username == finding["owner"] or c.principal.can("manage")):
        raise crud.Forbidden("Yönetim yanıtını bulgu sahibi veya yönetici verir")
    status, text = c.body.get("response_status"), (c.body.get("management_response") or "").strip()
    if status not in ("agreed", "partially_agreed", "disagreed"):
        raise crud.Invalid("Yanıt: katılıyor, kısmen katılıyor veya katılmıyor")
    if len(text) < 10:
        raise crud.Invalid("Yanıtı ve eylem planını (veya katılmama gerekçesini) yazın")
    c.db.execute("UPDATE tdr_findings SET response_status=?, management_response=?, responded_by=?, responded_at=?, "
                 "updated_at=? WHERE id=?", (status, text, c.principal.username, utcnow(), utcnow(), finding["id"]))
    audit.log(c.db, c.principal, "RESPOND", "findings", finding["id"], {"response_status": status, "response": text})
    if finding["created_by"]:
        _notify(c.db, "finding.assigned", f"Yönetim yanıtı verildi: {finding['code']}", text[:500],
                users=[finding["created_by"]], link=f"#/r/findings/{finding['id']}", object_type="findings",
                object_id=finding["id"])
    return crud.get(c.db, FINDINGS, finding["id"])


# ------------------------------------------------------------------ denetim raporu

def report_data(db, audit_id, principal):
    from .grc import audit_context_data
    from .grc_library import finding_impact_data
    from ..labels import choice
    a = audit_context_data(db, audit_id, principal)
    findings = []
    for f in a["findings"]:
        impact = finding_impact_data(db, f)
        clauses = [f"{g['standard']} {c['code']}" for g in impact["groups"] for c in g["clauses"] if c["level"] in ("direct", "certain")]
        actions = rows(db, "SELECT code, title, status, due_date FROM tdr_grc_actions WHERE finding_id=? ORDER BY due_date", (f["id"],))
        findings.append({**{k: f.get(k) for k in ("id", "code", "title", "description", "severity", "status", "root_cause",
                                                  "owner", "due_date", "response_status", "management_response",
                                                  "responded_by", "responded_at", "control_code")},
                         "severity_label": choice("findings", "severity", f["severity"]),
                         "response_label": choice("findings", "response_status", f["response_status"]) if f.get("response_status") else None,
                         "clauses": clauses[:20], "actions": actions})
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["code"]))
    sev = {}
    for f in findings:
        sev[f["severity"]] = sev.get(f["severity"], 0) + 1
    tests = [{"code": k["code"], "name": k["name"], "result": k["result"],
              "result_label": choice("executions", "status", k["result"]) if k["result"] != "untested" else "Test edilmedi"}
             for k in a["controls"] if k["planned"]]
    standards = [{"code": s["code"], "version": s["version"], "name": s["name"],
                  "clauses": sum(1 for cl in a["clauses"] if cl["standard_id"] == s["id"])} for s in a["standards"]]
    summary = {"standards": len(a["standards"]), "clauses": len(a["clauses"]), "tests": a["progress"]["planned"],
               "pass": a["counts"]["pass"], "fail": a["counts"]["fail"], "untested": a["counts"]["untested"],
               "findings": len(findings), "findings_by_severity": sev,
               "responses_pending": sum(1 for f in findings if f["response_status"] in (None, "pending")),
               "workpapers": len(a.get("workpapers", [])),
               "workpapers_reviewed": sum(1 for w in a.get("workpapers", []) if w["status"] == "reviewed"),
               "requests": len(a.get("requests", [])),
               "requests_accepted": sum(1 for r in a.get("requests", []) if r["status"] == "accepted")}
    audit_info = {k: a.get(k) for k in ("id", "code", "name", "kind", "status", "audit_objective", "scope", "planned_start",
                                        "planned_end", "actual_start", "actual_end", "lead_auditor", "auditors", "auditees",
                                        "opinion", "conclusion", "executive_summary", "plan_captured_at")}
    audit_info["kind_label"] = choice("audits", "kind", a["kind"])
    audit_info["status_label"] = choice("audits", "status", a["status"])
    audit_info["opinion_label"] = choice("audits", "opinion", a["opinion"]) if a.get("opinion") else None
    return {"audit": audit_info, "standards": standards, "processes": [p["name"] for p in a.get("processes", [])],
            "summary": summary, "findings": findings, "tests": tests, "generated_at": utcnow(),
            "disclaimer": "Bu rapor platformdaki değiştirilemez test sonuçları ve kanıt kayıtlarından üretilmiştir."}


def report(c):
    authz.check(c.principal, AUDITS, "read")
    authz.require_audit(c.principal, c.params["id"])
    return report_data(c.db, c.params["id"], c.principal)


def report_draft(c):
    from .. import ai
    authz.require_human(c.principal)
    authz.check(c.principal, AUDITS, "write")
    data = report_data(c.db, c.params["id"], c.principal)
    return ai.report_draft(c.db, c.app.config, c.principal, c.params["id"], data)


# ------------------------------------------------------------------ denetim evreni ve yıllık plan

def _months_since(value):
    if not value:
        return None
    d = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return (date.today() - d).days / 30.4


def _last_audit(db, u):
    """Varlığın son tamamlanmış denetimi (türe göre)."""
    done = "a.status IN ('completed','closed')"
    queries = []
    if u["process_id"]:
        queries.append(("SELECT MAX(COALESCE(a.actual_end, a.planned_end)) AS d FROM tdr_audits a JOIN tdr_audit_processes m "
                        f"ON m.audit_id=a.id WHERE m.process_id=? AND {done}", (u["process_id"],)))
    if u["supplier_id"]:
        queries.append((f"SELECT MAX(COALESCE(a.actual_end, a.planned_end)) AS d FROM tdr_audits a WHERE a.supplier_id=? AND {done}",
                        (u["supplier_id"],)))
    if u["company_id"]:
        queries.append((f"SELECT MAX(COALESCE(a.actual_end, a.planned_end)) AS d FROM tdr_audits a WHERE a.company_id=? AND {done}",
                        (u["company_id"],)))
    if u["standard_id"]:
        queries.append(("SELECT MAX(COALESCE(a.actual_end, a.planned_end)) AS d FROM tdr_audits a JOIN tdr_audit_standards m "
                        f"ON m.audit_id=a.id WHERE m.standard_id=? AND {done}", (u["standard_id"],)))
    queries.append(("SELECT MAX(COALESCE(a.actual_end, a.planned_end)) AS d FROM tdr_audits a JOIN tdr_audit_plan_items i "
                    f"ON i.audit_id=a.id WHERE i.universe_id=? AND {done}", (u["id"],)))
    found = [one(db, sql, args)["d"] for sql, args in queries]
    found = [str(x)[:10] for x in found if x]
    return max(found) if found else None


def _risk_signal(db, u):
    """Bağlı açık risklerin en yüksek artık puanı (0-25) ve açık bulgu sayısı."""
    where, args = [], []
    for col in ("process_id", "company_id", "supplier_id"):
        if u[col]:
            where.append(f"{col}=?")
            args.append(u[col])
    if not where:
        return 0, 0
    cond = " OR ".join(where)
    risk = one(db, f"SELECT MAX(COALESCE(residual_score, inherent_score)) AS s FROM tdr_supplier_risks WHERE ({cond}) "
                   "AND status IN ('open','in_treatment')", args)["s"] or 0
    findings = one(db, f"SELECT COUNT(*) AS n FROM tdr_findings WHERE ({cond}) AND status IN ('open','in_progress')", args)["n"]
    return float(risk), findings


def priorities(db):
    out = []
    for u in rows(db, "SELECT * FROM tdr_audit_universe WHERE active=1"):
        last = _last_audit(db, u)
        months = _months_since(last)
        risk, findings = _risk_signal(db, u)
        freq = max(int(u["frequency_months"] or 12), 1)
        inherent = 8 * max(1, min(int(u["inherent_rating"] or 3), 5))                 # 8–40
        residual = 30 * min(risk, 25) / 25                                            # 0–30
        open_findings = min(findings * 3, 15)                                         # 0–15
        overdue = 15 if months is None else min(15, 15 * max(0.0, months / freq - 0.5))   # 0–15
        score = round(inherent + residual + open_findings + overdue, 1)
        reasons = [f"doğal risk {u['inherent_rating']}/5"]
        if risk:
            reasons.append(f"en yüksek açık risk {risk:g}")
        if findings:
            reasons.append(f"{findings} açık bulgu")
        reasons.append("hiç denetlenmedi" if months is None else f"son denetim {last} ({months:.0f} ay önce, sıklık {freq} ay)")
        out.append({"universe_id": u["id"], "code": u["code"], "name": u["name"], "entity_type": u["entity_type"],
                    "owner": u["owner"], "score": score, "last_audit": last, "due": months is None or months >= freq,
                    "reasons": reasons})
    out.sort(key=lambda x: -x["score"])
    return out


def priorities_route(c):
    authz.check(c.principal, UNIVERSE, "read")
    return priorities(c.db)


def generate_plan(c):
    """Plan taslağına öncelik sırasıyla kalem ekler: denetimi gelen veya puanı eşiği geçen varlıklar, çeyreklere dağıtılır."""
    authz.require_human(c.principal)
    authz.check(c.principal, PLAN_ITEMS, "write")
    plan = crud.get(c.db, PLANS, c.params["id"])
    if plan["status"] != "draft":
        raise crud.Conflict("Yalnızca taslak plana kalem eklenir")
    limit = int(c.body.get("limit") or 12)
    threshold = float(c.body.get("min_score") or 45)
    have = {r["universe_id"] for r in rows(c.db, "SELECT universe_id FROM tdr_audit_plan_items WHERE plan_id=?", (plan["id"],))}
    chosen = [p for p in priorities(c.db) if p["universe_id"] not in have and (p["due"] or p["score"] >= threshold)][:limit]
    quarters = ("Q1", "Q2", "Q3", "Q4")
    for i, p in enumerate(chosen):
        c.db.execute("INSERT INTO tdr_audit_plan_items (plan_id, universe_id, quarter, status, priority_score, planned_days, "
                     "rationale, created_at) VALUES (?,?,?,?,?,?,?,?)",
                     (plan["id"], p["universe_id"], quarters[min(i * 4 // max(len(chosen), 1), 3)], "planned", p["score"],
                      None, "; ".join(p["reasons"]), utcnow()))
    audit.log(c.db, c.principal, "GENERATE", "audit_plans", plan["id"], {"added": len(chosen)})
    return {"added": len(chosen), "items": plan_context_data(c.db, plan["id"])["items"]}


def plan_context_data(db, plan_id):
    plan = crud.get(db, PLANS, plan_id)
    items = rows(db, """SELECT i.*, u.code AS universe_code, u.name AS universe_name, u.entity_type, u.owner,
        a.code AS audit_code, a.name AS audit_name, a.status AS audit_status, a.planned_start, a.actual_end
        FROM tdr_audit_plan_items i JOIN tdr_audit_universe u ON u.id=i.universe_id
        LEFT JOIN tdr_audits a ON a.id=i.audit_id WHERE i.plan_id=? ORDER BY i.quarter, i.priority_score DESC""", (plan_id,))
    for i in items:
        i["progress"] = ("cancelled" if i["status"] == "cancelled" else "deferred" if i["status"] == "deferred" else
                         "done" if i["audit_status"] in ("completed", "closed") else "in_progress" if i["audit_status"] ==
                         "in_progress" else "scheduled" if i["audit_id"] else "not_started")
    counts = {}
    for i in items:
        counts[i["progress"]] = counts.get(i["progress"], 0) + 1
    active = [i for i in items if i["progress"] not in ("cancelled", "deferred")]
    plan["items"] = items
    plan["counts"] = counts
    plan["completion_pct"] = round(100 * counts.get("done", 0) / len(active), 1) if active else None
    plan["planned_days"] = sum(i["planned_days"] or 0 for i in active)
    return plan


def plan_context(c):
    authz.check(c.principal, PLANS, "read")
    return plan_context_data(c.db, c.params["id"])


def approve_plan(c):
    authz.require_human(c.principal)
    plan = crud.get(c.db, PLANS, c.params["id"])
    if c.principal.role != "ADMIN":
        raise crud.Forbidden("Yıllık denetim planını Yönetici onaylar (denetim komitesi kararı)")
    if plan["status"] != "draft":
        raise crud.Conflict("Plan taslak değil")
    if c.principal.username == plan["created_by"]:
        raise crud.Forbidden("Planı hazırlayan onaylayamaz (dört göz)")
    if not one(c.db, "SELECT id FROM tdr_audit_plan_items WHERE plan_id=? LIMIT 1", (plan["id"],)):
        raise crud.Invalid("Boş plan onaylanamaz")
    c.db.execute("UPDATE tdr_audit_plans SET status='approved', approved_by=?, approved_at=?, updated_at=? WHERE id=?",
                 (c.principal.username, utcnow(), utcnow(), plan["id"]))
    audit.log(c.db, c.principal, "APPROVE", "audit_plans", plan["id"], {"note": c.body.get("note")})
    return plan_context_data(c.db, plan["id"])


def _plan_rules(db, data, current, principal):
    if current is None:
        data["created_by"] = principal.username if principal else "system"
    elif current["status"] != "draft" and set(data) - {"status", "notes", "updated_at"}:
        raise crud.Conflict("Onaylı planın kapsamı değiştirilemez; kalem durumlarını güncelleyin")


PLANS.before_save = _plan_rules


def start_item(c):
    """Plan kaleminden denetim açar (kapsam sonra seçilir) ve kaleme bağlar."""
    authz.require_human(c.principal)
    authz.check(c.principal, AUDITS, "write")
    item = crud.get(c.db, PLAN_ITEMS, c.params["id"])
    if item["audit_id"]:
        raise crud.Conflict("Bu kalem için denetim zaten açılmış")
    u = crud.get(c.db, UNIVERSE, item["universe_id"])
    plan = crud.get(c.db, PLANS, item["plan_id"])
    q = int(item["quarter"][1])
    start = date(int(plan["year"]), 3 * (q - 1) + 1, 15)
    data = {"code": crud.next_code(c.db, AUDITS), "name": f"{u['name']} denetimi — {plan['year']} {item['quarter']}",
            "kind": "supplier" if u["supplier_id"] else "internal", "supplier_id": u["supplier_id"],
            "company_id": u["company_id"], "audit_objective": item["rationale"], "planned_start": start.isoformat(),
            "planned_end": (start + timedelta(days=max(int(item["planned_days"] or 10), 1) + 4)).isoformat(),
            "status": "planned", "revision": 0, "created_at": utcnow()}
    data = {k: v for k, v in data.items() if v is not None}
    audit_id = c.db.execute(f"INSERT INTO tdr_audits ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                            tuple(data.values())).lastrowid
    if u["process_id"]:
        c.db.execute("INSERT INTO tdr_audit_processes (audit_id, process_id) VALUES (?,?)", (audit_id, u["process_id"]))
    c.db.execute("UPDATE tdr_audit_plan_items SET audit_id=?, updated_at=? WHERE id=?", (audit_id, utcnow(), item["id"]))
    audit.log(c.db, c.principal, "CREATE", "audits", audit_id, {"plan_item": item["id"], "name": data["name"]})
    return 201, {"audit_id": audit_id}


# ------------------------------------------------------------------ sertifikalar

def _cert_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    for key, label in (("issued_on", "Veriliş tarihi"), ("expires_on", "Geçerlilik sonu"), ("next_surveillance", "Gözetim tarihi")):
        _date(merged.get(key), label)
    if merged.get("issued_on") and merged.get("expires_on") and str(merged["expires_on"]) <= str(merged["issued_on"]):
        raise crud.Invalid("Geçerlilik sonu veriliş tarihinden sonra olmalı")


CERTIFICATIONS.before_save = _cert_rules


@reminder
def certification_reminders(db, app):
    if not app.enabled("grc"):
        return 0
    days = int(policy(db, "certification.warning_days", 90))
    limit = (date.today() + timedelta(days=days)).isoformat()
    n = 0
    for r in rows(db, "SELECT id, code, title, owner, expires_on, next_surveillance FROM tdr_certifications WHERE status='active' "
                      "AND (expires_on <= ? OR next_surveillance <= ?)", (limit, limit)):
        when = min(str(x) for x in (r["expires_on"], r["next_surveillance"]) if x)
        n += _notify(db, "certification.expiring", f"Sertifika takvimi: {r['title']}", f"Yaklaşan tarih: {when}",
                     users=[r["owner"]] if r["owner"] else [], link=f"#/r/certifications/{r['id']}",
                     object_type="certifications", object_id=r["id"], dedupe=f"srt:{r['id']}:{when}:{date.today():%Y-%m}")
    return n


def register(app):
    app.route("POST", API + "/evidence_requests/bulk", bulk_requests)
    app.route("GET", API + "/evidence_requests/{id}/candidates", candidates)
    app.route("POST", API + "/evidence_requests/{id}/submit", submit, max_body=MAX_UPLOAD_BODY)
    app.route("POST", API + "/evidence_requests/{id}/review", review)
    app.route("POST", API + "/evidence_requests/{id}/cancel", cancel)
    app.route("POST", API + "/workpapers/{id}/submit", wp_submit)
    app.route("POST", API + "/workpapers/{id}/review", wp_review)
    app.route("POST", API + "/findings/{id}/request-response", request_response)
    app.route("POST", API + "/findings/{id}/response", respond)
    app.route("GET", API + "/audits/{id}/report", report)
    app.route("POST", API + "/audits/{id}/report-draft", report_draft)
    app.route("GET", API + "/audit_universe/priorities", priorities_route)
    app.route("GET", API + "/audit_plans/{id}/context", plan_context)
    app.route("POST", API + "/audit_plans/{id}/generate", generate_plan)
    app.route("POST", API + "/audit_plans/{id}/approve", approve_plan)
    app.route("POST", API + "/audit_plan_items/{id}/start", start_item)


def seed(db):
    for code, (value, description) in DEFAULT_POLICIES.items():
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))
