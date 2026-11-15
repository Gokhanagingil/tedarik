"""Bağlam ve içgörü uçları: kayıt bağlamları (kontrol hedefi, madde, süreç), GRC takvimi, İşlerim, GRC sağlık
kontrolü (ilişki bütünlüğü), genel arama, şemadan üretilen ilişki modeli ve ISO 9001 süreç haritası.

Bu dosya yalnızca okur; yazma işlemi yoktur. Her uç yetki denetimi yapar ve kapalı modülün verisini döndürmez.
"""
from datetime import date, timedelta

from .. import auth as authz, crud
from ..db import fold, one, rows
from ..schema import RESOURCES
from .core import policy

API = "/api/tdr"


def _enabled(c, *modules):
    return all(c.app.enabled(m) for m in modules)


def _readable(c, name):
    res = RESOURCES.get(name)
    if res is None or not c.app.enabled(res.module) or not res.api:
        return False
    if c.principal.role == "MACHINE":
        return "r" in res.machine
    return not res.read_roles or c.principal.role in res.read_roles


# ------------------------------------------------------------------ kayıt bağlamları

def objective_context(c):
    authz.check(c.principal, RESOURCES["objectives"], "read")
    item = crud.get(c.db, RESOURCES["objectives"], c.params["id"])
    item["process"] = one(c.db, "SELECT id, code, name FROM tdr_processes WHERE id=?", (item["process_id"],)) \
        if item["process_id"] else None
    item["controls"] = rows(c.db, """SELECT k.id, k.code, k.name, k.execution_mode, k.frequency, k.active,
        (SELECT x.status FROM tdr_executions x WHERE x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC LIMIT 1)
        AS last_status FROM tdr_controls k JOIN tdr_control_objectives m ON m.control_id=k.id WHERE m.objective_id=?
        ORDER BY k.code""", (item["id"],))
    item["risks"] = rows(c.db, """SELECT r.id, r.code, r.title, r.risk_level, r.status FROM tdr_supplier_risks r
        JOIN tdr_objective_risks m ON m.risk_id=r.id WHERE m.objective_id=? ORDER BY r.code""", (item["id"],))
    tested = [k for k in item["controls"] if k["last_status"]]
    item["effectiveness"] = {"controls": len(item["controls"]), "tested": len(tested),
                             "passed": sum(1 for k in tested if k["last_status"] == "pass")}
    return item


def document_clauses(c):
    """Dokümanın karşıladığı standart maddeleri (küme olarak). Yayımlanmış dokümanda da değişebilir: üst veridir."""
    documents = RESOURCES["documents"]
    document = crud.get(c.db, documents, c.params["id"])
    authz.check(c.principal, documents, "write")
    crud.check_scope(c.db, documents, c.principal, document)
    if document["status"] in ("obsolete", "retired"):
        raise crud.Conflict("Geçersiz kılınmış doküman değiştirilmez")
    ids = c.body.get("clause_ids")
    if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(ids) > 500:
        raise crud.Invalid("clause_ids tam sayı listesi olmalı")
    if ids and len(rows(c.db, f"SELECT id FROM tdr_clauses WHERE id IN ({','.join('?' * len(set(ids)))})",
                        sorted(set(ids)))) != len(set(ids)):
        raise crud.Invalid("Bulunamayan madde seçildi")
    c.db.execute("DELETE FROM tdr_document_clauses WHERE document_id=?", (document["id"],))
    for clause_id in sorted(set(ids)):
        c.db.execute("INSERT INTO tdr_document_clauses (document_id, clause_id) VALUES (?,?)", (document["id"], clause_id))
    from .. import audit
    audit.log(c.db, c.principal, "LINK", "documents", document["id"], {"clause_ids": sorted(set(ids))})
    from .documents import context_data
    return context_data(c.db, c.app, document["id"])


def objective_risks(c):
    objective = crud.get(c.db, RESOURCES["objectives"], c.params["id"])
    authz.check(c.principal, RESOURCES["objectives"], "write")
    ids = c.body.get("risk_ids")
    if not isinstance(ids, list) or any(type(i) is not int for i in ids):
        raise crud.Invalid("risk_ids tam sayı listesi olmalı")
    if ids and len(rows(c.db, f"SELECT id FROM tdr_supplier_risks WHERE id IN ({','.join('?' * len(set(ids)))})",
                        sorted(set(ids)))) != len(set(ids)):
        raise crud.Invalid("Bulunamayan risk seçildi")
    c.db.execute("DELETE FROM tdr_objective_risks WHERE objective_id=?", (objective["id"],))
    for risk_id in sorted(set(ids)):
        c.db.execute("INSERT INTO tdr_objective_risks (objective_id, risk_id) VALUES (?,?)", (objective["id"], risk_id))
    from .. import audit
    audit.log(c.db, c.principal, "LINK", "objectives", objective["id"], {"risk_ids": sorted(set(ids))})
    return objective_context(c)


def clause_context(c):
    authz.check(c.principal, RESOURCES["clauses"], "read")
    item = crud.get(c.db, RESOURCES["clauses"], c.params["id"])
    item["standard"] = one(c.db, "SELECT id, code, name, version FROM tdr_standards WHERE id=?", (item["standard_id"],))
    item["children"] = rows(c.db, "SELECT id, code, title, applicable FROM tdr_clauses WHERE parent_id=? "
                                  "ORDER BY COALESCE(position, 0), code", (item["id"],))
    item["controls"] = rows(c.db, """SELECT k.id, k.code, k.name, (SELECT x.status FROM tdr_executions x
        WHERE x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC LIMIT 1) AS last_status FROM tdr_controls k
        JOIN tdr_control_clauses m ON m.control_id=k.id WHERE m.clause_id=? ORDER BY k.code""", (item["id"],))
    item["documents"] = rows(c.db, """SELECT d.id, d.code, d.title, d.status FROM tdr_documents d
        JOIN tdr_document_clauses m ON m.document_id=d.id WHERE m.clause_id=? ORDER BY d.code""", (item["id"],))
    item["findings"] = rows(c.db, "SELECT id, code, title, severity, status FROM tdr_findings WHERE clause_id=? "
                                  "ORDER BY id DESC", (item["id"],))
    from .grc import evidence_filter
    visible, args = evidence_filter(c.principal, "e")
    item["evidence"] = rows(c.db, f"""SELECT e.id, e.code, e.title, e.status FROM tdr_evidence e
        JOIN tdr_evidence_clauses m ON m.evidence_id=e.id WHERE m.clause_id=? AND {visible} ORDER BY e.id DESC""",
                            (item["id"], *args))
    from .grc_library import clause_relations
    item["relations"] = clause_relations(c.db, item["id"])
    return item


def process_context(c):
    authz.check(c.principal, RESOURCES["processes"], "read")
    item = crud.get(c.db, RESOURCES["processes"], c.params["id"])
    pid = item["id"]
    item["parent"] = one(c.db, "SELECT id, code, name FROM tdr_processes WHERE id=?", (item["parent_id"],)) \
        if item["parent_id"] else None
    item["children"] = rows(c.db, "SELECT id, code, name, process_type FROM tdr_processes WHERE parent_id=? ORDER BY "
                                  "position, name", (pid,))
    item["risks"] = rows(c.db, "SELECT id, code, title, risk_level, status FROM tdr_supplier_risks WHERE process_id=? "
                               "ORDER BY code", (pid,))
    item["engagements"] = rows(c.db, """SELECT e.id, e.code, s.name AS supplier, s.tier FROM tdr_engagements e
        JOIN tdr_suppliers s ON s.id=e.supplier_id WHERE e.process_id=? ORDER BY s.name""", (pid,))
    item["controls"] = item["objectives"] = item["bias"] = item["documents"] = item["audits"] = item["findings"] = []
    if _enabled(c, "grc"):
        item["controls"] = rows(c.db, """SELECT k.id, k.code, k.name, (SELECT x.status FROM tdr_executions x
            WHERE x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC LIMIT 1) AS last_status FROM tdr_controls k
            JOIN tdr_control_processes m ON m.control_id=k.id WHERE m.process_id=? ORDER BY k.code""", (pid,))
        item["objectives"] = rows(c.db, "SELECT id, code, name FROM tdr_objectives WHERE process_id=? ORDER BY code", (pid,))
        item["audits"] = rows(c.db, """SELECT a.id, a.code, a.name, a.status, a.planned_start FROM tdr_audits a
            JOIN tdr_audit_processes m ON m.audit_id=a.id WHERE m.process_id=? ORDER BY a.planned_start DESC""", (pid,))
        item["findings"] = rows(c.db, "SELECT id, code, title, severity, status FROM tdr_findings WHERE process_id=? "
                                      "ORDER BY id DESC", (pid,))
    if _enabled(c, "documents"):
        item["documents"] = rows(c.db, "SELECT id, code, title, category, status, version FROM tdr_documents WHERE "
                                       "process_id=? ORDER BY code", (pid,))
    if _enabled(c, "continuity"):
        item["bias"] = rows(c.db, "SELECT id, code, title, status, criticality, rto_hours, mtpd_hours FROM tdr_bias "
                                  "WHERE process_id=? ORDER BY code", (pid,))
    return item


def process_map(c):
    """ISO 9001 4.4 süreç haritası: yönetim, ana ve destek süreçleri; her süreç için GRC özet sayıları."""
    authz.check(c.principal, RESOURCES["processes"], "read")
    processes = rows(c.db, "SELECT * FROM tdr_processes WHERE active=1 ORDER BY COALESCE(position, 999), name")
    for p in processes:
        pid = p["id"]
        p["risks"] = one(c.db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE process_id=? AND status IN "
                               "('open','in_treatment')", (pid,))["n"]
        p["high_risks"] = one(c.db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE process_id=? AND status IN "
                                    "('open','in_treatment') AND risk_level IN ('high','critical')", (pid,))["n"]
        p["suppliers"] = one(c.db, "SELECT COUNT(DISTINCT supplier_id) AS n FROM tdr_engagements WHERE process_id=?",
                             (pid,))["n"]
        p["controls"] = p["failing_controls"] = p["documents"] = 0
        p["bia"] = None
        if _enabled(c, "grc"):
            p["controls"] = one(c.db, "SELECT COUNT(*) AS n FROM tdr_control_processes WHERE process_id=?", (pid,))["n"]
            p["failing_controls"] = one(c.db, """SELECT COUNT(*) AS n FROM tdr_control_processes m WHERE m.process_id=?
                AND (SELECT x.status FROM tdr_executions x WHERE x.control_id=m.control_id ORDER BY x.executed_at DESC,
                x.id DESC LIMIT 1)='fail'""", (pid,))["n"]
        if _enabled(c, "documents"):
            p["documents"] = one(c.db, "SELECT COUNT(*) AS n FROM tdr_documents WHERE process_id=? AND status IN "
                                       "('published','active')", (pid,))["n"]
        if _enabled(c, "continuity"):
            p["bia"] = one(c.db, "SELECT id, code, status, criticality, rto_hours, mtpd_hours FROM tdr_bias WHERE "
                                 "process_id=? AND status<>'archived' ORDER BY id DESC LIMIT 1", (pid,))
    return {"processes": processes}


# ------------------------------------------------------------------ GRC takvimi

EVENT_TYPES = {
    "audit": ("Denetim", "grc"), "exercise": ("Tatbikat", "continuity"), "risk_cycle": ("Risk değerlendirme dönemi", "risks"),
    "risk_review": ("Risk gözden geçirme", "risks"), "risk_action": ("Risk faaliyeti", "risks"),
    "control_test": ("Kontrol testi", "grc"), "capa": ("DÖF hedef tarihi", "grc"), "finding": ("Bulgu hedef tarihi", "grc"),
    "document_review": ("Doküman gözden geçirme", "documents"), "bia_review": ("BİA gözden geçirme", "continuity"),
    "plan_review": ("Plan gözden geçirme", "continuity"), "evidence_expiry": ("Kanıt geçerlilik sonu", "grc"),
    "contract_end": ("Sözleşme bitişi", "core"), "survey": ("Anket kampanyası", "surveys"),
    "supplier_review": ("Tedarikçi değerlendirmesi", "performance"),
    "evidence_request": ("Kanıt talebi", "grc"), "certification": ("Sertifika / gözetim denetimi", "grc"),
    "exception_end": ("İstisna bitişi", "grc"), "attestation": ("Okundu beyanı", "grc"),
    "access_review": ("Erişim gözden geçirme", "grc"), "obligation_review": ("Yükümlülük gözden geçirme", "grc"),
    "rcsa": ("Öz değerlendirme", "risks"), "breach_deadline": ("KVKK bildirim süresi", "risks"),
}


def _day(value):
    return str(value)[:10] if value else None


def calendar(c):
    """Belirli bir aralıktaki tüm GRC olayları. ?from=YYYY-AA-GG&to=YYYY-AA-GG&types=audit,exercise"""
    authz.require(c.principal, "read")
    try:
        start = date.fromisoformat(c.query.get("from") or date.today().replace(day=1).isoformat())
        end = date.fromisoformat(c.query.get("to") or (start + timedelta(days=41)).isoformat())
    except ValueError:
        raise crud.Invalid("from ve to YYYY-AA-GG olmalı") from None
    if end < start or (end - start).days > 400:
        raise crud.Invalid("Aralık en çok 400 gün olmalı")
    wanted = set((c.query.get("types") or ",".join(EVENT_TYPES)).split(","))
    lo, hi, db, events = start.isoformat(), end.isoformat(), c.db, []

    def add(kind, title, first, last, res, record_id, status=None, extra=None):
        if kind in wanted and first and _day(first) <= hi and _day(last or first) >= lo:
            events.append({"type": kind, "type_label": EVENT_TYPES[kind][0], "title": title, "start": _day(first),
                           "end": _day(last or first), "resource": res, "id": record_id, "status": status, **(extra or {})})

    def on(kind):
        return kind in wanted and c.app.enabled(EVENT_TYPES[kind][1])
    if on("audit") and _readable(c, "audits"):
        for a in rows(db, "SELECT id, code, name, status, planned_start, planned_end FROM tdr_audits WHERE status<>'cancelled'"):
            add("audit", f"{a['code']} {a['name']}", a["planned_start"], a["planned_end"], "audits", a["id"], a["status"])
    if on("exercise") and _readable(c, "bc_exercises"):
        for x in rows(db, "SELECT id, code, title, status, planned_date, actual_date FROM tdr_bc_exercises WHERE status<>'cancelled'"):
            add("exercise", f"{x['code']} {x['title']}", x["actual_date"] or x["planned_date"], None, "bc_exercises", x["id"],
                x["status"])
    if on("risk_cycle") and _readable(c, "risk_cycles"):
        for r in rows(db, "SELECT id, code, name, status, period_start, period_end FROM tdr_risk_cycles"):
            add("risk_cycle", r["name"], r["period_start"], r["period_end"], "risk_cycles", r["id"], r["status"])
    if on("risk_review") and _readable(c, "supplier_risks"):
        for r in rows(db, "SELECT id, code, title, status, review_date, risk_level FROM tdr_supplier_risks WHERE "
                          "status IN ('open','in_treatment','accepted') AND review_date BETWEEN ? AND ?", (lo, hi)):
            add("risk_review", f"{r['code']} {r['title']}", r["review_date"], None, "supplier_risks", r["id"], r["status"],
                {"level": r["risk_level"]})
    if on("risk_action") and _readable(c, "risk_actions"):
        for r in rows(db, "SELECT id, code, title, status, due_date FROM tdr_risk_actions WHERE status IN ('open','in_progress',"
                          "'validation') AND due_date BETWEEN ? AND ?", (lo, hi)):
            add("risk_action", f"{r['code']} {r['title']}", r["due_date"], None, "risk_actions", r["id"], r["status"])
    if on("capa") and _readable(c, "grc_actions"):
        for r in rows(db, "SELECT id, code, title, status, due_date FROM tdr_grc_actions WHERE status IN ('open','in_progress',"
                          "'validation') AND due_date BETWEEN ? AND ?", (lo, hi)):
            add("capa", f"{r['code']} {r['title']}", r["due_date"], None, "grc_actions", r["id"], r["status"])
    if on("finding") and _readable(c, "findings"):
        for r in rows(db, "SELECT id, code, title, status, due_date, severity FROM tdr_findings WHERE status IN "
                          "('open','in_progress') AND due_date BETWEEN ? AND ?", (lo, hi)):
            add("finding", f"{r['code']} {r['title']}", r["due_date"], None, "findings", r["id"], r["status"],
                {"level": r["severity"]})
    if on("control_test") and _readable(c, "controls"):
        from .grc import compliance_data
        for k in compliance_data(db)["controls"]:
            due = k["test"].get("due_on")
            if due and lo <= due <= hi:
                add("control_test", f"{k['code']} {k['name']}", due, None, "controls", k["id"], k["test"]["state"])
    if on("evidence_expiry") and _readable(c, "evidence"):
        from .grc import evidence_filter
        visible, args = evidence_filter(c.principal)
        for e in rows(db, "SELECT id, code, title, status, expires_at FROM tdr_evidence WHERE status='current' AND "
                          f"expires_at BETWEEN ? AND ? AND {visible}", (lo, hi, *args)):
            add("evidence_expiry", f"{e['code']} {e['title']}", e["expires_at"], None, "evidence", e["id"], e["status"])
    if on("document_review") and _readable(c, "documents"):
        for d in rows(db, "SELECT id, code, title, status, review_date FROM tdr_documents WHERE status IN "
                          "('published','active') AND review_date BETWEEN ? AND ?", (lo, hi)):
            add("document_review", f"{d['code']} {d['title']}", d["review_date"], None, "documents", d["id"], d["status"])
    if on("bia_review") and _readable(c, "bias"):
        for b in rows(db, "SELECT id, code, title, status, review_date FROM tdr_bias WHERE status='approved' AND "
                          "review_date BETWEEN ? AND ?", (lo, hi)):
            add("bia_review", f"{b['code']} {b['title']}", b["review_date"], None, "bias", b["id"], b["status"])
    if on("plan_review") and _readable(c, "bc_plans"):
        for p in rows(db, "SELECT id, code, title, status, review_date FROM tdr_bc_plans WHERE status='approved' AND "
                          "review_date BETWEEN ? AND ?", (lo, hi)):
            add("plan_review", f"{p['code']} {p['title']}", p["review_date"], None, "bc_plans", p["id"], p["status"])
    if on("contract_end") and _readable(c, "contracts"):
        for k in rows(db, "SELECT id, code, title, status, end_date FROM tdr_contracts WHERE status='active' AND "
                          "end_date BETWEEN ? AND ?", (lo, hi)):
            add("contract_end", f"{k['code']} {k['title']}", k["end_date"], None, "contracts", k["id"], k["status"])
    if on("survey") and _readable(c, "survey_campaigns"):
        for s in rows(db, "SELECT id, code, name, status, opens_on, closes_on, opened_at FROM tdr_survey_campaigns WHERE "
                          "status IN ('draft','open')"):
            add("survey", s["name"], s["opens_on"] or _day(s["opened_at"]) or s["closes_on"], s["closes_on"],
                "survey_campaigns", s["id"], s["status"])
    if on("supplier_review") and _readable(c, "suppliers") and c.app.enabled("dashboard"):
        from .dashboard import schedule
        view = type("Ctx", (), {"principal": c.principal, "db": c.db, "app": c.app, "query": {"all": "1"}})()
        for item in schedule(view)["items"]:
            if item["kind"] == "review" and item.get("due") and lo <= item["due"] <= hi:
                add("supplier_review", f"{item['code']} {item['name']}", item["due"], None, "suppliers",
                    item["supplier_id"], item["state"])
    simple = (   # (tür, kaynak, SQL, başlık alanı, tarih alanı)
        ("evidence_request", "evidence_requests", "SELECT id, code, title, status, due_date AS d FROM tdr_evidence_requests "
                                                  "WHERE status IN ('requested','rejected','submitted') AND due_date BETWEEN ? AND ?"),
        ("exception_end", "policy_exceptions", "SELECT id, code, title, status, end_date AS d FROM tdr_policy_exceptions "
                                               "WHERE status='approved' AND end_date BETWEEN ? AND ?"),
        ("attestation", "attestation_campaigns", "SELECT id, code, title, status, due_date AS d FROM tdr_attestation_campaigns "
                                                 "WHERE status='open' AND due_date BETWEEN ? AND ?"),
        ("access_review", "access_reviews", "SELECT id, code, title, status, due_date AS d FROM tdr_access_reviews "
                                            "WHERE status IN ('draft','open') AND due_date BETWEEN ? AND ?"),
        ("obligation_review", "obligations", "SELECT id, code, title, status, review_date AS d FROM tdr_obligations "
                                             "WHERE status='active' AND review_date BETWEEN ? AND ?"),
        ("rcsa", "rcsa_campaigns", "SELECT id, code, title, status, due_date AS d FROM tdr_rcsa_campaigns "
                                   "WHERE status IN ('draft','open') AND due_date BETWEEN ? AND ?"))
    for kind, res, sql in simple:
        if on(kind) and _readable(c, res):
            for r in rows(db, sql, (lo, hi)):
                add(kind, f"{r['code']} {r['title']}", r["d"], None, res, r["id"], r["status"])
    if on("certification") and _readable(c, "certifications"):
        for r in rows(db, "SELECT id, code, title, status, expires_on, next_surveillance FROM tdr_certifications "
                          "WHERE status='active'"):
            add("certification", f"{r['code']} {r['title']} — geçerlilik sonu", r["expires_on"], None, "certifications", r["id"],
                r["status"])
            add("certification", f"{r['code']} {r['title']} — gözetim denetimi", r["next_surveillance"], None,
                "certifications", r["id"], r["status"])
    if on("breach_deadline") and _readable(c, "privacy_breaches"):
        from .incidents import deadline
        for b in rows(db, "SELECT * FROM tdr_privacy_breaches WHERE status<>'closed'"):
            add("breach_deadline", f"{b['code']} {b['title']}", deadline(db, b).date().isoformat(), None,
                "privacy_breaches", b["id"], b["status"])
    events.sort(key=lambda e: (e["start"], e["type"]))
    return {"from": lo, "to": hi, "types": [{"key": k, "label": v[0]} for k, v in EVENT_TYPES.items()
                                            if c.app.enabled(v[1])], "events": events}


# ------------------------------------------------------------------ İşlerim

def my_work(c):
    """Oturumdaki kişiye atanmış açık işler. Sahip alanları kullanıcı adı veya görünen adla eşleşir."""
    authz.require_human(c.principal)
    me = {c.principal.username, c.principal.display_name or c.principal.username}
    names = sorted(me)
    marks = ",".join("?" * len(names))
    db, today = c.db, date.today().isoformat()
    soon = (date.today() + timedelta(days=30)).isoformat()
    out = {}

    def take(key, res, sql, params=()):
        if _readable(c, res):
            out[key] = rows(db, sql, params)
    take("risks", "supplier_risks", f"""SELECT id, code, title, status, risk_level, review_date, residual_score,
        last_assessed_at FROM tdr_supplier_risks WHERE owner IN ({marks}) AND status IN ('open','in_treatment','accepted')
        AND (review_date <= ? OR last_assessed_at IS NULL) ORDER BY review_date""", (*names, soon))
    take("risk_actions", "risk_actions", f"""SELECT id, code, title, status, due_date FROM tdr_risk_actions WHERE owner IN
        ({marks}) AND status IN ('open','in_progress','validation') ORDER BY due_date""", names)
    take("capa", "grc_actions", f"""SELECT id, code, title, status, due_date FROM tdr_grc_actions WHERE owner IN ({marks})
        AND status IN ('open','in_progress') ORDER BY due_date""", names)
    if c.principal.role in ("ADMIN", "AUDITOR"):
        take("capa_validation", "grc_actions", f"""SELECT id, code, title, owner, due_date FROM tdr_grc_actions
            WHERE status='validation' AND owner NOT IN ({marks}) ORDER BY due_date""", names)
    take("findings", "findings", f"""SELECT id, code, title, status, severity, due_date FROM tdr_findings WHERE owner IN
        ({marks}) AND status IN ('open','in_progress') ORDER BY due_date""", names)
    take("documents_to_approve", "documents", f"""SELECT id, code, title, prepared_by FROM tdr_documents WHERE
        status='in_review' AND (approver IN ({marks}) OR (approver IS NULL AND ?)) AND COALESCE(prepared_by,'') NOT IN
        ({marks})""", (*names, c.principal.can("manage"), *names))
    take("documents_to_review", "documents", f"""SELECT id, code, title, review_date FROM tdr_documents WHERE owner IN
        ({marks}) AND status IN ('published','active') AND review_date <= ? ORDER BY review_date""", (*names, soon))
    if c.principal.can("manage"):
        take("bias_to_approve", "bias", f"""SELECT id, code, title, owner FROM tdr_bias WHERE status='in_review' AND
            owner NOT IN ({marks}) AND COALESCE(prepared_by,'') NOT IN ({marks})""", (*names, *names))
    take("bias_to_review", "bias", f"""SELECT id, code, title, review_date FROM tdr_bias WHERE owner IN ({marks}) AND
        status='approved' AND review_date <= ?""", (*names, soon))
    take("exercises", "bc_exercises", f"""SELECT id, code, title, planned_date FROM tdr_bc_exercises WHERE
        facilitator IN ({marks}) AND status='planned' ORDER BY planned_date""", names)
    take("controls", "controls", f"""SELECT id, code, name FROM tdr_controls WHERE owner IN ({marks}) AND active=1
        ORDER BY code""", names)
    take("evidence_requests", "evidence_requests", f"""SELECT id, code, title, status, due_date FROM tdr_evidence_requests
        WHERE assignee IN ({marks}) AND status IN ('requested','rejected') ORDER BY due_date""", names)
    take("finding_responses", "findings", f"""SELECT id, code, title, severity, response_due AS due_date FROM tdr_findings
        WHERE owner IN ({marks}) AND response_status='pending' AND status IN ('open','in_progress') ORDER BY response_due""",
         names)
    if c.principal.role in ("ADMIN", "AUDITOR"):
        take("evidence_to_review", "evidence_requests", f"""SELECT id, code, title, assignee, due_date FROM
            tdr_evidence_requests WHERE status='submitted' AND assignee NOT IN ({marks}) ORDER BY due_date""", names)
        take("workpapers_to_review", "workpapers", f"""SELECT id, code, title, preparer FROM tdr_workpapers
            WHERE status='ready' AND COALESCE(preparer,'') NOT IN ({marks}) ORDER BY code""", names)
    if c.principal.role == "ADMIN":
        take("exceptions_to_approve", "policy_exceptions", f"""SELECT id, code, title, risk_level, start_date AS due_date
            FROM tdr_policy_exceptions WHERE status='requested' AND COALESCE(requested_by,'') NOT IN ({marks})
            AND owner NOT IN ({marks}) ORDER BY start_date""", (*names, *names))
    take("rcsa", "rcsa_items", f"""SELECT i.id, k.code, k.title, k.due_date, i.item_type, i.risk_id, i.control_id
        FROM tdr_rcsa_items i JOIN tdr_rcsa_campaigns k ON k.id=i.campaign_id WHERE i.respondent IN ({marks})
        AND i.status='pending' AND k.status='open' ORDER BY k.due_date""", names)
    take("access_reviews", "access_reviews", f"""SELECT id, code, title, due_date, system FROM tdr_access_reviews
        WHERE reviewer IN ({marks}) AND status='open' ORDER BY due_date""", names)
    take("breaches", "privacy_breaches", f"""SELECT id, code, title, detected_at FROM tdr_privacy_breaches
        WHERE owner IN ({marks}) AND status<>'closed' ORDER BY detected_at""", names)
    take("crisis_tasks", "bc_incident_tasks", f"""SELECT t.id, k.code, t.action AS title, t.phase, t.incident_id
        FROM tdr_bc_incident_tasks t JOIN tdr_bc_incidents k ON k.id=t.incident_id WHERE t.responsible IN ({marks})
        AND t.status IN ('todo','doing') AND k.status<>'closed' ORDER BY t.id""", names)
    take("attestations", "attestations", """SELECT a.id, k.code, k.title, k.due_date, k.statement, k.document_id
        FROM tdr_attestations a JOIN tdr_attestation_campaigns k ON k.id=a.campaign_id WHERE a.username=?
        AND a.status='pending' AND k.status='open' ORDER BY k.due_date""", (c.principal.username,))
    if c.app.enabled("surveys"):
        out["surveys"] = rows(db, """SELECT c.id, c.code, c.name, c.closes_on FROM tdr_survey_invitations i
            JOIN tdr_survey_campaigns c ON c.id=i.campaign_id WHERE i.respondent=? AND i.status='pending'
            AND c.status='open'""", (c.principal.username,))
    out["overdue"] = sum(1 for key in ("risk_actions", "capa", "findings", "evidence_requests", "finding_responses")
                         for r in out.get(key, [])
                         if r.get("due_date") and str(r["due_date"]) < today)
    out["total"] = sum(len(v) for k, v in out.items() if isinstance(v, list) and k != "controls")
    return out


# ------------------------------------------------------------------ GRC sağlık kontrolü

OPEN_RISKS = "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE status IN ('open','in_treatment')"
PUBLISHED_DOCS = "SELECT COUNT(*) AS n FROM tdr_documents WHERE status IN ('published','active')"


def _n(db, sql, params=()):
    return one(db, sql, params)["n"] or 0


def _check(key, title, why, severity, items, resource, link=None, population=None):
    """population: kuralın uygulandığı kayıt sayısı; puan ihlal oranıyla hesaplanır (tek kayıt tüm puanı sıfırlamaz)."""
    return {"key": key, "title": title, "why": why, "severity": severity, "count": len(items),
            "population": max(population or 0, len(items)), "items": items[:25], "resource": resource, "link": link}


def health(c):
    """İlişki bütünlüğü ve yönetişim boşlukları. Her madde neden önemli olduğunu ve ilgili kaydı verir."""
    authz.require(c.principal, "read")
    db, today, checks = c.db, date.today().isoformat(), []
    stale = (date.today() - timedelta(days=14)).isoformat()
    if c.app.enabled("grc"):
        checks.append(_check("controls_no_objective", "Kontrol hedefine bağlı olmayan kontroller",
                             "Her kontrol bir kontrol hedefine hizmet etmeli; aksi halde neyi güvence altına aldığı belirsiz.",
                             "medium", rows(db, """SELECT id, code, name AS title FROM tdr_controls k WHERE active=1 AND NOT
                             EXISTS (SELECT 1 FROM tdr_control_objectives m WHERE m.control_id=k.id) ORDER BY code"""),
                             "controls", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_controls WHERE active=1")))
        checks.append(_check("controls_no_clause", "Hiçbir standart maddesine eşlenmemiş kontroller",
                             "Eşlenmemiş kontrol uyum göstergesine katkı vermez; gereksiz veya eksik eşlenmiş olabilir.",
                             "low", rows(db, """SELECT id, code, name AS title FROM tdr_controls k WHERE active=1 AND NOT
                             EXISTS (SELECT 1 FROM tdr_control_clauses m WHERE m.control_id=k.id) ORDER BY code"""),
                             "controls", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_controls WHERE active=1")))
        checks.append(_check("objectives_no_control", "Kontrolü olmayan kontrol hedefleri",
                             "Hedef tanımlanmış ama onu karşılayan kontrol yok: tasarım boşluğu.", "high",
                             rows(db, """SELECT id, code, name AS title FROM tdr_objectives o WHERE NOT EXISTS (SELECT 1 FROM
                             tdr_control_objectives m WHERE m.objective_id=o.id) ORDER BY code"""), "objectives", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_objectives")))
        checks.append(_check("clauses_uncovered", "Kontrolle karşılanmayan uygulanabilir maddeler",
                             "Uygulanabilirlik bildiriminde kapsamda olan her madde en az bir kontrolle karşılanmalı.",
                             "medium", rows(db, """SELECT cl.id, s.code || ' ' || cl.code AS code, cl.title FROM tdr_clauses cl
                             JOIN tdr_standards s ON s.id=cl.standard_id WHERE cl.applicable=1 AND s.active=1 AND NOT EXISTS
                             (SELECT 1 FROM tdr_control_clauses m WHERE m.clause_id=cl.id) AND NOT EXISTS (SELECT 1 FROM
                             tdr_clauses ch WHERE ch.parent_id=cl.id) ORDER BY s.code, cl.code"""), "clauses", population=_n(db, """SELECT COUNT(*) AS n FROM tdr_clauses cl JOIN tdr_standards s ON s.id=cl.standard_id WHERE cl.applicable=1 AND
                             s.active=1 AND NOT EXISTS (SELECT 1 FROM tdr_clauses ch WHERE ch.parent_id=cl.id)""")))
        checks.append(_check("obligations_no_control", "Kontrolle karşılanmayan yükümlülükler",
                             "Uygulanan her mevzuat veya sözleşme yükümlülüğü en az bir kontrolle güvence altına alınmalı; "
                             "yoksa uyum durumu bilinemez.", "high",
                             rows(db, """SELECT id, code, title FROM tdr_obligations o WHERE status='active' AND
                             applicability='applicable' AND NOT EXISTS (SELECT 1 FROM tdr_obligation_controls m
                             WHERE m.obligation_id=o.id) ORDER BY code"""), "obligations",
                             population=_n(db, "SELECT COUNT(*) AS n FROM tdr_obligations WHERE status='active' AND "
                                               "applicability='applicable'")))
        checks.append(_check("certifications_expiring", "90 gün içinde süresi dolan sertifikalar",
                             "Yeniden belgelendirme denetimi zamanında planlanmazsa sertifika düşer; müşteri ve "
                             "düzenleyici yükümlülükleri etkilenir.", "high",
                             rows(db, "SELECT id, code, title FROM tdr_certifications WHERE status='active' AND expires_on <= ? "
                                      "ORDER BY expires_on", ((date.today() + timedelta(days=90)).isoformat(),)),
                             "certifications", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_certifications WHERE status='active'")))
        checks.append(_check("exceptions_expired_open", "Süresi geçmiş ama kapanmamış politika istisnaları",
                             "Süresi geçen istisna ya yenilenmeli ya da kontrol uygulanmalı; aksi halde örtük risk kabulüdür.",
                             "medium", rows(db, "SELECT id, code, title FROM tdr_policy_exceptions WHERE status='approved' AND "
                                                "end_date < ? ORDER BY end_date", (today,)), "policy_exceptions",
                             population=_n(db, "SELECT COUNT(*) AS n FROM tdr_policy_exceptions WHERE status='approved'")))
        checks.append(_check("findings_no_action", "14 günden eski ve düzeltici faaliyeti olmayan açık bulgular",
                             "Bulgu açıldıktan sonra makul sürede DÖF planlanmalı (ISO 9001 10.2).", "high",
                             rows(db, """SELECT id, code, title FROM tdr_findings f WHERE status IN ('open','in_progress') AND
                             created_at < ? AND NOT EXISTS (SELECT 1 FROM tdr_grc_actions a WHERE a.finding_id=f.id)
                             ORDER BY created_at""", (stale,)), "findings", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_findings WHERE status IN ('open','in_progress')")))
        checks.append(_check("capa_overdue", "Hedef tarihi geçmiş düzeltici faaliyetler",
                             "Geciken DÖF bulgunun tekrarlama riskini artırır.", "high",
                             rows(db, """SELECT id, code, title FROM tdr_grc_actions WHERE status IN ('open','in_progress')
                             AND due_date < ? ORDER BY due_date""", (today,)), "grc_actions", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_grc_actions WHERE status IN ('open','in_progress')")))
        year_ago = (date.today() - timedelta(days=365)).isoformat()
        checks.append(_check("core_process_not_audited", "Son 12 ayda denetlenmemiş ana süreçler",
                             "ISO 9001 9.2: iç denetim programı süreçlerin önemini dikkate alır; ana süreçler düzenli denetlenmeli.",
                             "medium", rows(db, """SELECT id, code, name AS title FROM tdr_processes p WHERE active=1 AND
                             process_type='core' AND NOT EXISTS (SELECT 1 FROM tdr_audit_processes m JOIN tdr_audits a ON
                             a.id=m.audit_id WHERE m.process_id=p.id AND a.status IN ('in_progress','completed','closed') AND
                             COALESCE(a.actual_end, a.planned_end, a.planned_start) >= ?) ORDER BY code""", (year_ago,)),
                             "processes", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_processes WHERE active=1 AND "
                                                             "process_type='core'")))
        checks.append(_check("high_risks_no_control", "Kontrolü veya işleme faaliyeti olmayan yüksek/kritik riskler",
                             "ISO 31000 6.5: yüksek risk işlenmeli; kontrol veya faaliyet yoksa işleme planı eksiktir.",
                             "critical", rows(db, """SELECT id, code, title FROM tdr_supplier_risks r WHERE status IN
                             ('open','in_treatment') AND risk_level IN ('high','critical') AND NOT EXISTS (SELECT 1 FROM
                             tdr_control_risks m WHERE m.risk_id=r.id) AND NOT EXISTS (SELECT 1 FROM tdr_risk_actions a
                             WHERE a.risk_id=r.id AND a.status NOT IN ('cancelled')) ORDER BY code"""), "supplier_risks", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE status IN ('open','in_treatment') AND risk_level IN ('high','critical')")))
    if c.app.enabled("risks"):
        checks.append(_check("risks_unassessed", "Hiç değerlendirilmemiş açık riskler",
                             "Tanımlanan risk analiz ve değerlendirme olmadan önceliklendirilemez (ISO 31000 6.4).",
                             "medium", rows(db, """SELECT id, code, title FROM tdr_supplier_risks WHERE status IN
                             ('open','in_treatment') AND last_assessed_at IS NULL ORDER BY code"""), "supplier_risks", population=_n(db, OPEN_RISKS)))
        checks.append(_check("risks_review_overdue", "Gözden geçirme tarihi geçmiş riskler",
                             "İzleme ve gözden geçirme ISO 31000 6.6'nın parçasıdır.", "medium",
                             rows(db, """SELECT id, code, title FROM tdr_supplier_risks WHERE status IN ('open','in_treatment',
                             'accepted') AND review_date < ? ORDER BY review_date""", (today,)), "supplier_risks", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE status IN ('open','in_treatment','accepted')")))
        checks.append(_check("risks_no_context", "Süreç, tedarikçi veya varlık bağı olmayan riskler",
                             "Bağlamı belirsiz risk sahiplenilemez ve kontrollere bağlanamaz (ISO 31000 6.3).", "low",
                             rows(db, """SELECT id, code, title FROM tdr_supplier_risks WHERE status IN ('open','in_treatment')
                             AND process_id IS NULL AND supplier_id IS NULL AND origin_ref IS NULL ORDER BY code"""),
                             "supplier_risks", population=_n(db, OPEN_RISKS)))
        checks.append(_check("appetite_breach", "İştah üstünde kalan ve kabul edilmemiş riskler",
                             "Artık risk iştahı aşıyorsa ya işlenmeli ya da yetkili istisnayla kabul edilmeli.", "critical",
                             rows(db, """SELECT id, code, title FROM tdr_supplier_risks WHERE status IN ('open','in_treatment')
                             AND residual_score > appetite ORDER BY residual_score DESC"""), "supplier_risks", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE status IN ('open','in_treatment') AND residual_score IS NOT NULL")))
    if c.app.enabled("cmdb"):
        checks.append(_check("cis_no_company", "Şirketi eşlenmemiş CI'lar",
                             "Şirketi bilinmeyen CI'ın riski kimin riski olduğu belirlenemediği için kayda alınamaz.",
                             "medium", rows(db, """SELECT id, code, name AS title FROM tdr_cmdb_cis WHERE company_id IS NULL
                             AND stale=0 ORDER BY name"""), "cmdb_cis", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_cmdb_cis WHERE stale=0")))
        checks.append(_check("cmdb_risks_cleared", "Etkilenen CI'ı kalmayan CMDB riskleri",
                             "Kural kaynaklı riskte etkilenen CI kalmadıysa risk sahibi kapatmayı değerlendirmeli.", "low",
                             rows(db, """SELECT id, code, title FROM tdr_supplier_risks r WHERE origin_ref LIKE 'cmdb:%' AND
                             status IN ('open','in_treatment') AND NOT EXISTS (SELECT 1 FROM tdr_risk_cis m WHERE
                             m.risk_id=r.id AND m.link_source='rule')"""), "supplier_risks", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE origin_ref LIKE 'cmdb:%' AND status IN ('open','in_treatment')")))
    if c.app.enabled("continuity"):
        months = int(policy(db, "bcm.exercise_months", 12))
        limit = (date.today() - timedelta(days=round(months * 30.44))).isoformat()
        checks.append(_check("core_process_no_bia", "Onaylı BİA'sı olmayan ana süreçler",
                             "ISO 22301 8.2.2: kritik faaliyetler BİA ile belirlenir; ana süreçler analiz edilmeli.",
                             "high", rows(db, """SELECT id, code, name AS title FROM tdr_processes p WHERE active=1 AND
                             process_type='core' AND NOT EXISTS (SELECT 1 FROM tdr_bias b WHERE b.process_id=p.id AND
                             b.status='approved') ORDER BY code"""), "processes", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_processes WHERE active=1 AND process_type='core'")))
        checks.append(_check("critical_bia_no_plan", "Onaylı planı olmayan kritik / yüksek BİA'lar",
                             "ISO 22301 8.4: kritik faaliyet için iş sürekliliği planı gerekir.", "critical",
                             rows(db, """SELECT id, code, title FROM tdr_bias b WHERE status='approved' AND criticality IN
                             ('critical','high') AND NOT EXISTS (SELECT 1 FROM tdr_bc_plan_bias pb JOIN tdr_bc_plans p ON
                             p.id=pb.plan_id WHERE pb.bia_id=b.id AND p.status='approved')"""), "bias", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_bias WHERE status='approved' AND criticality IN ('critical','high')")))
        checks.append(_check("plans_not_exercised", f"{months} ay içinde tatbik edilmemiş onaylı planlar",
                             "ISO 22301 8.5: planlar düzenli aralıklarla tatbik edilmeli.", "high",
                             rows(db, """SELECT id, code, title FROM tdr_bc_plans p WHERE status='approved' AND NOT EXISTS
                             (SELECT 1 FROM tdr_bc_exercises x WHERE x.plan_id=p.id AND x.status='completed' AND
                             x.actual_date >= ?)""", (limit,)), "bc_plans", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_bc_plans WHERE status='approved'")))
    if c.app.enabled("documents"):
        checks.append(_check("documents_review_overdue", "Gözden geçirme tarihi geçmiş yayımlanmış dokümanlar",
                             "ISO 9001 7.5.3: dokümante bilgi güncel ve uygun tutulmalı.", "medium",
                             rows(db, """SELECT id, code, title FROM tdr_documents WHERE status IN ('published','active') AND
                             review_date < ? ORDER BY review_date""", (today,)), "documents", population=_n(db, PUBLISHED_DOCS)))
        checks.append(_check("documents_no_process", "Sürece bağlı olmayan yayımlanmış dokümanlar",
                             "ISO 9001 4.4: süreçleri destekleyen dokümanlar süreçle ilişkilendirilmeli.", "low",
                             rows(db, """SELECT id, code, title FROM tdr_documents WHERE status IN ('published','active') AND
                             process_id IS NULL ORDER BY code"""), "documents", population=_n(db, PUBLISHED_DOCS)))
    checks.append(_check("processes_no_owner", "Sahibi olmayan süreçler",
                         "Sahibi olmayan süreçte risk, kontrol ve BİA sorumluluğu belirsiz kalır.", "medium",
                         rows(db, """SELECT id, code, name AS title FROM tdr_processes WHERE active=1 AND (owner IS NULL OR
                         owner='') ORDER BY code"""), "processes", population=_n(db, "SELECT COUNT(*) AS n FROM tdr_processes WHERE active=1")))
    checks = [x for x in checks if _readable(c, x["resource"])]
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    checks.sort(key=lambda x: (x["count"] == 0, order[x["severity"]], -x["count"]))
    weights = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    total = sum(weights[x["severity"]] for x in checks)
    passed = sum(weights[x["severity"]] * (1 - x["count"] / x["population"] if x["population"] else 1) for x in checks)
    return {"score": round(100 * passed / total) if total else None, "checks": checks}


# ------------------------------------------------------------------ genel arama

def search(c):
    """Komut paleti: okunabilen kaynaklarda kod, ad ve başlıkta arama; kaynak başına en çok 5 sonuç."""
    authz.require_human(c.principal)
    q = (c.query.get("q") or "").strip()
    if len(q) < 2:
        return {"results": []}
    pattern = "%" + fold(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    results = []
    for name, res in RESOURCES.items():
        if not _readable(c, name) or not res.search or name in ("audit_log", "import_rows", "policies"):
            continue
        fields = [f for f in res.search if f in ("code", "name", "title")] or list(res.search)[:2]
        label = "name" if "name" in res.fields else "title" if "title" in res.fields else fields[0]
        where = " OR ".join(f"tdr_fold({f}) LIKE ? ESCAPE '\\'" for f in fields)
        for r in rows(c.db, f"SELECT id, {', '.join(dict.fromkeys(['code' if 'code' in res.fields else 'id', label]))} "
                            f"FROM {res.table} WHERE {where} ORDER BY id DESC LIMIT 5", [pattern] * len(fields)):
            results.append({"resource": name, "resource_label": res.label, "id": r["id"],
                            "code": r.get("code"), "title": r.get(label)})
    return {"results": results[:60]}


# ------------------------------------------------------------------ ilişki modeli (harita)

def model(c):
    """Şemadan üretilen ilişki modeli: varlıklar (etkin, okunabilir, listelenebilir) ve aralarındaki ilişkiler.
    1:N ilişki yabancı anahtardan, M:N ilişki iki yabancı anahtarlı bağlantı tablosundan türetilir."""
    authz.require(c.principal, "read")
    from ..model_map import GROUPS, POSITIONS
    entities, by_table = {}, {}
    for name, res in RESOURCES.items():
        if name in POSITIONS and c.app.enabled(res.module) and _readable(c, name):
            entities[name] = {"name": name, "label": res.label, "module": res.module, "position": POSITIONS[name],
                              "count": one(c.db, f"SELECT COUNT(*) AS n FROM {res.table}")["n"]}
            by_table[res.table] = name
    relations = []
    for name, res in RESOURCES.items():
        if not c.app.enabled(res.module):
            continue
        refs = [(f, col.ref) for f, col in res.columns.items() if col.ref]
        if name in entities:
            for field_name, ref in refs:
                target = by_table.get(ref)
                if target and target != name:
                    relations.append({"from": name, "to": target, "kind": "1:N", "via": field_name})
                elif target == name:
                    relations.append({"from": name, "to": name, "kind": "hierarchy", "via": field_name})
        elif len(refs) >= 2 and not ({"code", "name", "title"} & set(res.fields)):
            targets = [by_table.get(ref) for _, ref in refs[:2]]     # bağlantı tablosu (ek nitelikli olabilir)
            if all(targets) and targets[0] != targets[1]:
                relations.append({"from": targets[0], "to": targets[1], "kind": "M:N", "via": res.name})
    unique = {(r["from"], r["to"], r["kind"], r["via"]): r for r in relations}
    return {"groups": GROUPS, "entities": list(entities.values()), "relations": list(unique.values())}


M = "insights"


def register(app):
    if app.enabled("grc"):
        app.route("GET", API + "/objectives/{id}/context", objective_context)
        app.route("POST", API + "/objectives/{id}/risks", objective_risks)
        app.route("GET", API + "/clauses/{id}/context", clause_context)
        app.route("POST", API + "/documents/{id}/clauses", document_clauses)
    app.route("GET", API + "/processes/{id}/context", process_context)
    app.route("GET", API + "/processes-map", process_map)
    app.route("GET", API + "/calendar", calendar)
    app.route("GET", API + "/my-work", my_work)
    app.route("GET", API + "/health-check", health)
    app.route("GET", API + "/search", search)
    app.route("GET", API + "/model", model)
