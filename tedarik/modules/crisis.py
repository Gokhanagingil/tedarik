"""Kriz yönetimi modu — continuity modülünün parçası (K-027, ISO 22301 8.4).

Kriz ilan edilince seçilen planların adımları görev listesine kopyalanır (aktivasyon → müdahale → kurtarma → normale
dönüş); görevler sorumlusuna göre işaretlenir; kararlar, iletişim ve durum güncellemeleri değiştirilemez günlüğe yazılır.
Etkin kriz tüm kullanıcılara üst bantta görünür. Kriz kapanınca olay sonrası rapor yazılır ve kriz "gerçek olay"
türünde bir tatbikat kaydına dönüşür (alınan dersler, gerçekleşen kurtarma süresi); böylece planın sınandığı görünür.
"""
from datetime import datetime, timezone

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API
from ..schema import RESOURCES, Resource, fk

M = "continuity"

INCIDENTS = Resource("bc_incidents", "Krizler", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "severity": "TEXT NOT NULL DEFAULT 'high'",
    "status": "TEXT NOT NULL DEFAULT 'active'", "description": "TEXT NOT NULL", "company_id": fk("companies", False),
    "commander": "TEXT NOT NULL", "declared_by": "TEXT", "declared_at": "TIMESTAMP NOT NULL", "recovered_at": "TIMESTAMP",
    "closed_at": "TIMESTAMP", "summary": "TEXT", "lessons_learned": "TEXT", "exercise_id": fk("bc_exercises", False),
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="KRZ", code_yearly=True, search=("code", "title"), api=("list", "get"), write="manage",
    enums={"severity": ("medium", "high", "critical"), "status": ("active", "recovering", "closed")})
Resource("bc_incident_plans", "Krizde devreye alınan planlar", {
    "incident_id": fk("bc_incidents", cascade=True), "plan_id": fk("bc_plans")},
    module=M, unique=(("incident_id", "plan_id"),), api=(), search=())
TASKS = Resource("bc_incident_tasks", "Kriz Görevleri", {
    "incident_id": fk("bc_incidents"), "plan_id": fk("bc_plans", False), "phase": "TEXT NOT NULL DEFAULT 'response'",
    "position": "INTEGER NOT NULL DEFAULT 1", "action": "TEXT NOT NULL", "responsible": "TEXT",
    "target_minutes": "INTEGER", "status": "TEXT NOT NULL DEFAULT 'todo'", "done_at": "TIMESTAMP", "done_by": "TEXT",
    "note": "TEXT", "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list", "get"), search=("action", "responsible"), write="manage",
    enums={"phase": ("activation", "response", "recovery", "resumption"),
           "status": ("todo", "doing", "done", "skipped")})
LOG = Resource("bc_incident_log", "Kriz Günlüğü", {
    "incident_id": fk("bc_incidents"), "kind": "TEXT NOT NULL DEFAULT 'update'", "text": "TEXT NOT NULL",
    "author": "TEXT NOT NULL", "logged_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), search=("text",), immutable=True,
    enums={"kind": ("decision", "communication", "update", "status")})


def _notify(db, *args, **kw):
    from .. import notify
    return notify.enqueue(db, *args, **kw)


def _everyone(db):
    return [r["username"] for r in rows(db, "SELECT username FROM users WHERE is_active=1")]


def _log(db, incident_id, kind, text, author):
    db.execute("INSERT INTO tdr_bc_incident_log (incident_id, kind, text, author, logged_at) VALUES (?,?,?,?,?)",
               (incident_id, kind, text, author, utcnow()))


def declare(c):
    """{title, description, severity, commander, plan_ids, company_id?}: krizi ilan eder ve plan adımlarını görevleştirir."""
    authz.require_human(c.principal)
    authz.check(c.principal, INCIDENTS, "write")
    plan_ids = c.body.get("plan_ids") or []
    if not isinstance(plan_ids, list) or any(type(i) is not int for i in plan_ids) or len(plan_ids) > 20:
        raise crud.Invalid("plan_ids tamsayı listesi olmalı")
    plans = [crud.get(c.db, RESOURCES["bc_plans"], pid) for pid in plan_ids]
    if any(p["status"] != "approved" for p in plans):
        raise crud.Invalid("Yalnızca onaylı planlar devreye alınır")
    title, description = str(c.body.get("title") or "").strip(), str(c.body.get("description") or "").strip()
    if not title or not description:
        raise crud.Invalid("Kriz başlığı ve durumu gerekli")
    now = utcnow()
    incident_id = crud.insert(c.db, INCIDENTS, {
        "title": title[:300], "description": description, "severity": c.body.get("severity") or "high",
        "commander": str(c.body.get("commander") or c.principal.display_name or c.principal.username)[:160],
        "company_id": c.body.get("company_id"), "declared_by": c.principal.username, "declared_at": now,
        "status": "active"}, c.principal)
    count = 0
    for plan in plans:
        c.db.execute("INSERT INTO tdr_bc_incident_plans (incident_id, plan_id) VALUES (?,?)", (incident_id, plan["id"]))
        for step in rows(c.db, "SELECT * FROM tdr_bc_plan_steps WHERE plan_id=? ORDER BY CASE phase WHEN 'activation' THEN 1 "
                               "WHEN 'response' THEN 2 WHEN 'recovery' THEN 3 ELSE 4 END, position", (plan["id"],)):
            c.db.execute("INSERT INTO tdr_bc_incident_tasks (incident_id, plan_id, phase, position, action, responsible, "
                         "target_minutes, status, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (incident_id, plan["id"], step["phase"], step["position"], step["action"], step["responsible"],
                          step["target_minutes"], "todo", now))
            count += 1
    _log(c.db, incident_id, "status", f"Kriz ilan edildi ({c.principal.display_name or c.principal.username}). "
         f"Devreye alınan planlar: {', '.join(p['code'] for p in plans) or 'yok'}.", c.principal.username)
    audit.log(c.db, c.principal, "DECLARE", "bc_incidents", incident_id, {"plans": plan_ids, "tasks": count})
    incident = crud.get(c.db, INCIDENTS, incident_id)
    _notify(c.db, "crisis.declared", f"KRİZ: {incident['code']} {title}", description[:1500], users=_everyone(c.db),
            link="#/crisis", object_type="bc_incidents", object_id=incident_id, dedupe=f"krz:{incident_id}:ilan")
    return 201, context_data(c.db, incident_id)


def context_data(db, incident_id):
    item = crud.get(db, INCIDENTS, incident_id)
    item["plans"] = rows(db, "SELECT p.id, p.code, p.title FROM tdr_bc_plans p JOIN tdr_bc_incident_plans m ON m.plan_id=p.id "
                             "WHERE m.incident_id=?", (incident_id,))
    item["tasks"] = rows(db, """SELECT t.*, p.code AS plan_code FROM tdr_bc_incident_tasks t LEFT JOIN tdr_bc_plans p
        ON p.id=t.plan_id WHERE t.incident_id=? ORDER BY CASE t.phase WHEN 'activation' THEN 1 WHEN 'response' THEN 2
        WHEN 'recovery' THEN 3 ELSE 4 END, t.position, t.id""", (incident_id,))
    item["log"] = rows(db, "SELECT * FROM tdr_bc_incident_log WHERE incident_id=? ORDER BY logged_at DESC, id DESC",
                       (incident_id,))
    done = sum(1 for t in item["tasks"] if t["status"] in ("done", "skipped"))
    start = datetime.fromisoformat(str(item["declared_at"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(item["closed_at"]).replace("Z", "+00:00")) if item["closed_at"] else datetime.now(timezone.utc)
    item["progress"] = {"total": len(item["tasks"]), "done": done,
                        "pct": round(100 * done / len(item["tasks"]), 1) if item["tasks"] else None,
                        "elapsed_minutes": int((end - start).total_seconds() // 60)}
    return item


def context(c):
    authz.check(c.principal, INCIDENTS, "read")
    return context_data(c.db, c.params["id"])


def active(c):
    """Üst bant için etkin krizler (tüm kullanıcılar)."""
    return rows(c.db, "SELECT id, code, title, severity, status, declared_at, commander FROM tdr_bc_incidents "
                      "WHERE status<>'closed' ORDER BY declared_at DESC")


def task_status(c):
    authz.require_human(c.principal)
    task = crud.get(c.db, TASKS, c.params["id"])
    incident = crud.get(c.db, INCIDENTS, task["incident_id"])
    if incident["status"] == "closed":
        raise crud.Conflict("Kapanmış krizin görevleri değişmez")
    mine = task["responsible"] in (c.principal.username, c.principal.display_name)
    if not (mine or c.principal.can("manage")):
        raise crud.Forbidden("Görevi sorumlusu veya kriz ekibi (yönetici) günceller")
    status = c.body.get("status")
    if status not in TASKS.enums["status"]:
        raise crud.Invalid("Geçersiz görev durumu")
    note = (c.body.get("note") or "").strip()
    if status == "skipped" and not note:
        raise crud.Invalid("Atlanan görev için gerekçe yazın")
    done = status in ("done", "skipped")
    c.db.execute("UPDATE tdr_bc_incident_tasks SET status=?, note=COALESCE(?, note), done_at=?, done_by=? WHERE id=?",
                 (status, note or None, utcnow() if done else None, c.principal.username if done else None, task["id"]))
    _log(c.db, incident["id"], "update", f"Görev {'tamamlandı' if status == 'done' else 'atlandı' if status == 'skipped' else 'başladı' if status == 'doing' else 'yeniden açıldı'}: "
         f"{task['action'][:200]}" + (f" — {note}" if note else ""), c.principal.username)
    audit.log(c.db, c.principal, "UPDATE", "bc_incident_tasks", task["id"], {"status": status, "note": note})
    return context_data(c.db, incident["id"])


def add_log(c):
    authz.require_human(c.principal)
    incident = crud.get(c.db, INCIDENTS, c.params["id"])
    authz.check(c.principal, INCIDENTS, "read")
    if not c.principal.can("write"):
        raise crud.Forbidden("Günlüğe kriz ekibi yazar")
    kind, text = c.body.get("kind") or "update", str(c.body.get("text") or "").strip()
    if kind not in ("decision", "communication", "update") or not text:
        raise crud.Invalid("Günlük türü ve metni gerekli")
    _log(c.db, incident["id"], kind, text[:4000], c.principal.username)
    audit.log(c.db, c.principal, "LOG", "bc_incidents", incident["id"], {"kind": kind})
    return context_data(c.db, incident["id"])


def transition(c):
    """active → recovering → closed. Kapanışta olay sonrası rapor zorunlu; kriz 'gerçek olay' tatbikatına dönüşür."""
    authz.require_human(c.principal)
    incident = crud.get(c.db, INCIDENTS, c.params["id"])
    authz.check(c.principal, INCIDENTS, "write")
    target = c.body.get("status")
    allowed = {"active": ("recovering", "closed"), "recovering": ("active", "closed")}.get(incident["status"], ())
    if target not in allowed:
        raise crud.Conflict("Bu geçiş yapılamaz")
    now = utcnow()
    if target == "recovering":
        c.db.execute("UPDATE tdr_bc_incidents SET status='recovering', recovered_at=?, updated_at=? WHERE id=?",
                     (now, now, incident["id"]))
        _log(c.db, incident["id"], "status", "Hizmetler kurtarıldı; normale dönüş aşaması.", c.principal.username)
    elif target == "active":
        c.db.execute("UPDATE tdr_bc_incidents SET status='active', updated_at=? WHERE id=?", (now, incident["id"]))
        _log(c.db, incident["id"], "status", "Kriz yeniden etkin.", c.principal.username)
    else:
        summary, lessons = str(c.body.get("summary") or "").strip(), str(c.body.get("lessons_learned") or "").strip()
        if len(summary) < 20 or not lessons:
            raise crud.Invalid("Olay sonrası rapor (özet) ve alınan dersler gerekli")
        ctx = context_data(c.db, incident["id"])
        exercise_id = None
        plans = ctx["plans"]
        if plans:
            exercise_id = crud.insert(c.db, RESOURCES["bc_exercises"], {
                "title": f"Gerçek olay: {incident['title']}"[:300], "exercise_type": "real_incident",
                "plan_id": plans[0]["id"], "scenario": incident["description"], "planned_date": str(incident["declared_at"])[:10],
                "actual_date": now[:10], "status": "completed", "facilitator": incident["commander"],
                "achieved_recovery_minutes": ctx["progress"]["elapsed_minutes"],
                "outcome": "successful" if ctx["progress"]["pct"] in (None, 100.0) else "partially_successful",
                "lessons_learned": lessons, "report": summary}, None)
        c.db.execute("UPDATE tdr_bc_incidents SET status='closed', closed_at=?, summary=?, lessons_learned=?, exercise_id=?, "
                     "updated_at=? WHERE id=?", (now, summary, lessons, exercise_id, now, incident["id"]))
        _log(c.db, incident["id"], "status", "Kriz kapatıldı; olay sonrası rapor yazıldı.", c.principal.username)
        _notify(c.db, "crisis.closed", f"Kriz kapatıldı: {incident['code']} {incident['title']}", summary[:1500],
                users=_everyone(c.db), link=f"#/crisis/{incident['id']}", object_type="bc_incidents",
                object_id=incident["id"], dedupe=f"krz:{incident['id']}:kapanis")
    audit.log(c.db, c.principal, "TRANSITION", "bc_incidents", incident["id"], {"status": target})
    return context_data(c.db, incident["id"])


def register(app):
    app.route("POST", API + "/bc_incidents/declare", declare)
    app.route("GET", API + "/bc_incidents/active", active)
    app.route("GET", API + "/bc_incidents/{id}/context", context)
    app.route("POST", API + "/bc_incidents/{id}/log", add_log)
    app.route("POST", API + "/bc_incidents/{id}/transition", transition)
    app.route("POST", API + "/bc_incident_tasks/{id}/status", task_status)
