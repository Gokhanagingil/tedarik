"""İş sürekliliği yönetimi (ISO 22301). K-020.

ISO 22301 karşılıkları
- 8.2.2 İş etki analizi (BİA): süreç bazında; zaman aralıklarına göre etki matrisi (finansal, operasyonel, müşteri,
  itibar, yasal); azami tolere edilebilir kesinti süresi (MTPD) etkinin "tolere edilemez" seviyeye ulaştığı ilk
  zaman aralığıdır (`bcm.intolerable_level`). RTO ≤ MTPD; RPO; asgari iş sürekliliği hedefi (MBCO); kaynak
  gereksinimleri: uygulamalar (CMDB), tedarikçiler, personel, konum, hayati kayıtlar. Onay dört gözle (hazırlayan ≠
  onaylayan); onaylı BİA değiştirilmez, revizyona alınır. Yıllık gözden geçirme.
- 8.2.3 Risk değerlendirmesi: BİA, kurumsal risk kaydındaki risklere bağlanır.
- 8.3 Strateji ve çözümler, 8.4 planlar: plan türü (İSP, felaket kurtarma, kriz yönetimi, iletişim), kapsam BİA'ları,
  kurtarılacak uygulamalar ve sıra, aktivasyon ölçütü, ekip ve iletişim, adımlar (aktivasyon, müdahale, kurtarma,
  normale dönüş) ve hedef süreleri; onay dört gözle; onaylı planın adımları değiştirilmez.
- 8.5 Tatbikat ve test: tür, senaryo, hedefler, hedef ve gerçekleşen kurtarma süresi, sonuç, alınan dersler.
  Hedef süre aşıldıysa sonuç "başarılı" olamaz. Tatbikat bulgusu GRC bulgusu olarak açılır (DÖF akışı ortak).
- 9 Performans değerlendirme: süreç kapsaması, RTO açığı, tatbikatı geciken plan, gözden geçirmesi geciken BİA ve
  plan, destek bitişi geçmiş uygulamaya bağlı BİA, kritik tedarikçi bağımlılıkları.
"""
from datetime import date, timedelta

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, guard_readonly
from ..schema import RESOURCES, Resource, fk
from .core import policy

M = "continuity"
REQUIRES = ("cmdb", "grc")
WINDOWS = {"h1": 1, "h4": 4, "h8": 8, "d1": 24, "d3": 72, "w1": 168, "w2": 336, "m1": 720}
IMPACT_CATEGORIES = ("financial", "operational", "customer", "reputational", "legal")
CRITICALITY = {"critical": 4, "high": 24, "medium": 72}
MANAGERS = {"ADMIN", "SUPPLIER_MANAGER"}

BIAS = Resource("bias", "İş Etki Analizleri", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "process_id": fk("processes"),
    "company_id": fk("companies", False), "org_unit_id": fk("org_units", False), "owner": "TEXT NOT NULL",
    "status": "TEXT NOT NULL DEFAULT 'draft'", "description": "TEXT", "peak_periods": "TEXT", "min_staff": "INTEGER",
    "locations": "TEXT", "vital_records": "TEXT", "workaround": "TEXT", "mtpd_hours": "REAL", "rto_hours": "REAL",
    "rpo_hours": "REAL", "mbco": "TEXT", "criticality": "TEXT", "prepared_by": "TEXT", "approved_by": "TEXT",
    "approved_at": "TIMESTAMP", "review_date": "DATE", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="write", code_prefix="BIA", search=("code", "title", "owner"),
    readonly=("status", "mtpd_hours", "criticality", "prepared_by", "approved_by", "approved_at"),
    enums={"status": ("draft", "in_review", "approved", "archived"),
           "criticality": ("critical", "high", "medium", "low")})

IMPACTS = Resource("bia_impacts", "BİA Etki Değerlendirmesi", {
    "bia_id": fk("bias", cascade=True), "category": "TEXT NOT NULL", "time_window": "TEXT NOT NULL",
    "level": "INTEGER NOT NULL", "note": "TEXT"},
    module=M, unique=(("bia_id", "category", "time_window"),), api=("list",), search=(),
    enums={"category": IMPACT_CATEGORIES, "time_window": tuple(WINDOWS)})

BIA_APPS = Resource("bia_applications", "BİA Uygulama Bağımlılıkları", {
    "bia_id": fk("bias", cascade=True), "ci_id": fk("cmdb_cis"), "required_rto_hours": "REAL", "note": "TEXT"},
    module=M, unique=(("bia_id", "ci_id"),), write="write", search=("note",))

BIA_SUPPLIERS = Resource("bia_suppliers", "BİA Tedarikçi Bağımlılıkları", {
    "bia_id": fk("bias", cascade=True), "supplier_id": fk("suppliers"), "engagement_id": fk("engagements", False),
    "note": "TEXT"},
    module=M, unique=(("bia_id", "supplier_id"),), write="write", search=("note",))

BIA_RISKS = Resource("bia_risks", "BİA Riskleri", {
    "bia_id": fk("bias", cascade=True), "risk_id": fk("supplier_risks"), "note": "TEXT"},
    module=M, unique=(("bia_id", "risk_id"),), write="write", search=("note",))

PLANS = Resource("bc_plans", "İş Sürekliliği Planları", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "plan_type": "TEXT NOT NULL DEFAULT 'bcp'",
    "company_id": fk("companies", False), "owner": "TEXT NOT NULL", "status": "TEXT NOT NULL DEFAULT 'draft'",
    "version": "TEXT NOT NULL DEFAULT '1.0'", "scope": "TEXT", "activation_criteria": "TEXT", "strategy": "TEXT",
    "team": "TEXT", "communication": "TEXT", "document_id": fk("documents", False), "prepared_by": "TEXT",
    "approved_by": "TEXT", "approved_at": "TIMESTAMP", "review_date": "DATE",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="manage", code_prefix="BSP", search=("code", "title", "owner"),
    readonly=("status", "prepared_by", "approved_by", "approved_at"),
    enums={"plan_type": ("bcp", "drp", "crisis", "communication", "pandemic"),
           "status": ("draft", "approved", "retired")})

PLAN_BIAS = Resource("bc_plan_bias", "Planın Kapsadığı BİA'lar", {
    "plan_id": fk("bc_plans", cascade=True), "bia_id": fk("bias", cascade=True)},
    module=M, unique=(("plan_id", "bia_id"),), api=("list",), search=())

PLAN_APPS = Resource("bc_plan_applications", "Planda Kurtarılacak Uygulamalar", {
    "plan_id": fk("bc_plans", cascade=True), "ci_id": fk("cmdb_cis"), "recovery_order": "INTEGER NOT NULL DEFAULT 1",
    "target_rto_hours": "REAL", "note": "TEXT"},
    module=M, unique=(("plan_id", "ci_id"),), write="manage", search=("note",))

STEPS = Resource("bc_plan_steps", "Plan Adımları", {
    "plan_id": fk("bc_plans", cascade=True), "phase": "TEXT NOT NULL DEFAULT 'response'",
    "position": "INTEGER NOT NULL DEFAULT 1", "action": "TEXT NOT NULL", "responsible": "TEXT",
    "target_minutes": "INTEGER"},
    module=M, write="manage", search=("action", "responsible"),
    enums={"phase": ("activation", "response", "recovery", "resumption")})

EXERCISES = Resource("bc_exercises", "Tatbikatlar", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "exercise_type": "TEXT NOT NULL DEFAULT 'tabletop'",
    "plan_id": fk("bc_plans"), "scenario": "TEXT NOT NULL", "objectives": "TEXT", "planned_date": "DATE NOT NULL",
    "actual_date": "DATE", "status": "TEXT NOT NULL DEFAULT 'planned'", "facilitator": "TEXT", "participants": "TEXT",
    "target_recovery_minutes": "INTEGER", "achieved_recovery_minutes": "INTEGER", "outcome": "TEXT",
    "lessons_learned": "TEXT", "report": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="manage", code_prefix="TAT", code_yearly=True, search=("code", "title", "scenario"),
    enums={"exercise_type": ("tabletop", "walkthrough", "simulation", "functional", "full_scale", "call_tree"),
           "status": ("planned", "completed", "cancelled"),
           "outcome": ("successful", "partially_successful", "failed")})

EXERCISE_FINDINGS = Resource("bc_exercise_findings", "Tatbikat Bulguları", {
    "exercise_id": fk("bc_exercises", cascade=True), "finding_id": fk("findings")},
    module=M, unique=(("exercise_id", "finding_id"),), api=("list",), search=())


# ------------------------------------------------------------------ kurallar

def _hours(value, label):
    if value is not None and (not isinstance(value, (int, float)) or value < 0):
        raise crud.Invalid(f"{label} sıfır veya pozitif saat olmalı")


def _bia_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if current is not None and current["status"] in ("approved", "archived"):
        raise crud.Conflict("Onaylı BİA değiştirilmez; önce revizyona alın")
    _hours(merged.get("rto_hours"), "RTO")
    _hours(merged.get("rpo_hours"), "RPO")
    mtpd = merged.get("mtpd_hours")
    if mtpd is not None and merged.get("rto_hours") is not None and merged["rto_hours"] > mtpd:
        raise crud.Invalid(f"RTO ({merged['rto_hours']} saat) MTPD'den ({mtpd} saat) büyük olamaz")
    if merged.get("review_date"):
        _iso(merged["review_date"])
    if current is None:
        data["prepared_by"] = principal.username if principal else "system"
        if not merged.get("company_id"):
            from .core import default_company
            data["company_id"] = default_company(db)


def _iso(value):
    try:
        date.fromisoformat(str(value)[:10])
    except ValueError:
        raise crud.Invalid("Tarih YYYY-AA-GG olmalı") from None


def _child_of_bia(db, data, current, principal):
    bia = crud.get(db, BIAS, data.get("bia_id") or current["bia_id"])
    if bia["status"] in ("approved", "archived"):
        raise crud.Conflict("Onaylı BİA'nın bağımlılıkları değiştirilmez; önce revizyona alın")
    if "required_rto_hours" in data:
        _hours(data["required_rto_hours"], "Gereken RTO")


def _plan_rules(db, data, current, principal):
    if current is not None and current["status"] == "approved" and set(data) - {"review_date", "document_id"}:
        raise crud.Conflict("Onaylı plan değiştirilmez; önce revizyona alın")
    if current is None:
        data["prepared_by"] = principal.username if principal else "system"
        if not data.get("company_id"):
            from .core import default_company
            data["company_id"] = default_company(db)


def _plan_child(db, data, current, principal):
    plan = crud.get(db, PLANS, data.get("plan_id") or current["plan_id"])
    if plan["status"] == "approved":
        raise crud.Conflict("Onaylı planın adımları ve uygulamaları değiştirilmez; önce revizyona alın")
    if data.get("target_minutes") is not None and data["target_minutes"] < 0:
        raise crud.Invalid("Hedef süre negatif olamaz")


def _exercise_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    for key in ("planned_date", "actual_date"):
        if merged.get(key):
            _iso(merged[key])
    if current is not None and current["status"] in ("completed", "cancelled") and \
            set(data) - {"report", "lessons_learned"}:
        raise crud.Conflict("Tamamlanmış veya iptal edilmiş tatbikat değiştirilmez")
    if current is None and merged.get("target_recovery_minutes") is None:
        plan = one(db, """SELECT MIN(b.rto_hours) AS rto FROM tdr_bc_plan_bias pb JOIN tdr_bias b ON b.id=pb.bia_id
            WHERE pb.plan_id=? AND b.rto_hours IS NOT NULL""", (merged["plan_id"],))
        if plan and plan["rto"] is not None:
            data["target_recovery_minutes"] = int(plan["rto"] * 60)
    if merged.get("status") == "completed":
        if not merged.get("actual_date") or str(merged["actual_date"]) > date.today().isoformat():
            raise crud.Invalid("Tamamlanan tatbikatta gerçekleşen tarih gerekli ve gelecekte olamaz")
        if not merged.get("outcome") or not (merged.get("lessons_learned") or "").strip():
            raise crud.Invalid("Tamamlanan tatbikatta sonuç ve alınan dersler gerekli (ISO 22301 8.5)")
        target, achieved = merged.get("target_recovery_minutes"), merged.get("achieved_recovery_minutes")
        if target is not None and achieved is not None and achieved > target and merged["outcome"] == "successful":
            raise crud.Invalid("Gerçekleşen kurtarma süresi hedefi aştı; sonuç 'başarılı' olamaz")


BIAS.before_save = _bia_rules
BIAS.scope = lambda db, record: {record.get("org_unit_id")}
for _res in (BIA_APPS, BIA_SUPPLIERS, BIA_RISKS):
    _res.before_save = _child_of_bia
    _res.scope = lambda db, record: {(one(db, "SELECT org_unit_id FROM tdr_bias WHERE id=?", (record.get("bia_id"),))
                                      or {}).get("org_unit_id")}
PLANS.before_save = _plan_rules
STEPS.before_save = _plan_child
PLAN_APPS.before_save = _plan_child
EXERCISES.before_save = _exercise_rules


# ------------------------------------------------------------------ BİA işlemleri

def derive(db, bia_id):
    """Etki matrisinden MTPD ve kritiklik."""
    intolerable = int(policy(db, "bcm.intolerable_level", 4))
    impacts = rows(db, "SELECT time_window, level FROM tdr_bia_impacts WHERE bia_id=?", (bia_id,))
    mtpd = None
    for window, hours in sorted(WINDOWS.items(), key=lambda x: x[1]):
        if any(i["time_window"] == window and i["level"] >= intolerable for i in impacts):
            mtpd = hours
            break
    bounds = policy(db, "bcm.criticality_hours", CRITICALITY)
    criticality = None if mtpd is None else "critical" if mtpd <= bounds["critical"] else "high" \
        if mtpd <= bounds["high"] else "medium" if mtpd <= bounds["medium"] else "low"
    if impacts and mtpd is None:
        criticality = "low"
    return mtpd, criticality


def set_impacts(c):
    bia = crud.get(c.db, BIAS, c.params["id"])
    authz.check(c.principal, BIAS, "write")
    crud.check_scope(c.db, BIAS, c.principal, bia)
    if bia["status"] in ("approved", "archived"):
        raise crud.Conflict("Onaylı BİA değiştirilmez; önce revizyona alın")
    items = c.body.get("impacts")
    if not isinstance(items, list) or len(items) > len(WINDOWS) * len(IMPACT_CATEGORIES):
        raise crud.Invalid("impacts listesi gerekli")
    seen = set()
    for item in items:
        key = (item.get("category"), item.get("time_window"))
        if key[0] not in IMPACT_CATEGORIES or key[1] not in WINDOWS or key in seen:
            raise crud.Invalid("Geçersiz veya tekrarlanan etki satırı")
        if type(item.get("level")) is not int or not 1 <= item["level"] <= 5:
            raise crud.Invalid("Etki seviyesi 1–5 olmalı")
        seen.add(key)
    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append((WINDOWS[item["time_window"]], item["level"]))
    for category, points in by_category.items():
        ordered = [level for _, level in sorted(points)]
        if any(b < a for a, b in zip(ordered, ordered[1:])):
            raise crud.Invalid("Etki zamanla azalamaz: aynı kategoride sonraki zaman aralığı daha düşük olamaz")
    c.db.execute("DELETE FROM tdr_bia_impacts WHERE bia_id=?", (bia["id"],))
    for item in items:
        c.db.execute("INSERT INTO tdr_bia_impacts (bia_id, category, time_window, level, note) VALUES (?,?,?,?,?)",
                     (bia["id"], item["category"], item["time_window"], item["level"], (item.get("note") or "")[:500]))
    mtpd, criticality = derive(c.db, bia["id"])
    if mtpd is not None and bia["rto_hours"] is not None and bia["rto_hours"] > mtpd:
        raise crud.Invalid(f"Bu etkilerle MTPD {mtpd} saat; mevcut RTO ({bia['rto_hours']} saat) bunu aşıyor. "
                           "Önce RTO'yu düşürün")
    c.db.execute("UPDATE tdr_bias SET mtpd_hours=?, criticality=?, updated_at=? WHERE id=?",
                 (mtpd, criticality, utcnow(), bia["id"]))
    audit.log(c.db, c.principal, "UPDATE", BIAS.name, bia["id"], {"impacts": len(items), "mtpd_hours": mtpd})
    return bia_context_data(c.db, c.app, bia["id"])


def transition(c):
    """BİA ve plan onay akışı: submit (gözden geçirmeye gönder), approve (dört göz), revise (revizyona al), archive."""
    res = BIAS if c.path_kind == "bias" else PLANS
    record = crud.get(c.db, res, c.params["id"])
    action = c.body.get("action")
    now = utcnow()
    if res is BIAS:
        authz.check(c.principal, BIAS, "write")
        crud.check_scope(c.db, BIAS, c.principal, record)
    else:
        authz.check(c.principal, PLANS, "write")
    status = record["status"]
    if action == "submit" and res is BIAS and status == "draft":
        missing = [label for key, label in (("rto_hours", "RTO"), ("rpo_hours", "RPO")) if record.get(key) is None]
        if not one(c.db, "SELECT 1 AS x FROM tdr_bia_impacts WHERE bia_id=? LIMIT 1", (record["id"],)):
            missing.append("etki matrisi")
        if missing:
            raise crud.Invalid("Göndermeden önce tamamlayın: " + ", ".join(missing))
        new = {"status": "in_review"}
    elif action == "approve" and status in (("in_review",) if res is BIAS else ("draft",)):
        if c.principal.role not in MANAGERS:
            raise crud.Forbidden("Onayı Yönetici veya Tedarikçi Yöneticisi verir")
        if c.principal.username in (record.get("prepared_by"), record.get("owner")):
            raise crud.Forbidden("Hazırlayan veya sahibi kendi kaydını onaylayamaz (dört göz)")
        if res is PLANS and not one(c.db, "SELECT 1 AS x FROM tdr_bc_plan_steps WHERE plan_id=? LIMIT 1", (record["id"],)):
            raise crud.Invalid("Onaydan önce plana en az bir adım ekleyin")
        review = (date.today() + timedelta(days=365)).isoformat()
        new = {"status": "approved", "approved_by": c.principal.username, "approved_at": now,
               "review_date": record.get("review_date") if record.get("review_date") and
               str(record["review_date"]) > date.today().isoformat() else review}
    elif action == "revise" and status == "approved":
        new = {"status": "draft", "approved_by": None, "approved_at": None}
        if res is PLANS:
            major, _, minor = str(record.get("version") or "1.0").partition(".")
            new["version"] = f"{major}.{int(minor or 0) + 1}" if minor.isdigit() or not minor else f"{major}.1"
    elif action == "archive" and status != ("archived" if res is BIAS else "retired"):
        authz.require(c.principal, "manage")
        new = {"status": "archived" if res is BIAS else "retired"}
    else:
        raise crud.Conflict("Bu durumda bu işlem yapılamaz")
    sets = ", ".join(f"{k}=?" for k in new)
    c.db.execute(f"UPDATE {res.table} SET {sets}, updated_at=? WHERE id=?", (*new.values(), now, record["id"]))
    audit.log(c.db, c.principal, action.upper(), res.name, record["id"], {"from": status, "to": new["status"]})
    return crud.get(c.db, res, record["id"])


def _routed(kind, fn):
    def handler(c):
        c.path_kind = kind
        return fn(c)
    return handler


def bia_context_data(db, app, bia_id):
    bia = crud.get(db, BIAS, bia_id)
    bia["impacts"] = rows(db, "SELECT category, time_window, level, note FROM tdr_bia_impacts WHERE bia_id=?", (bia_id,))
    bia["windows"] = [{"key": k, "hours": v} for k, v in WINDOWS.items()]
    bia["intolerable_level"] = int(policy(db, "bcm.intolerable_level", 4))
    bia["applications"] = rows(db, """SELECT a.id AS link_id, a.required_rto_hours, a.note, ci.id, ci.code, ci.name,
        ci.ci_class, ci.environment, ci.business_criticality, (SELECT COUNT(*) FROM tdr_ci_exposures e WHERE e.ci_id=ci.id
        AND e.status='open') AS open_exposures FROM tdr_bia_applications a JOIN tdr_cmdb_cis ci ON ci.id=a.ci_id
        WHERE a.bia_id=? ORDER BY ci.name""", (bia_id,))
    for app_row in bia["applications"]:
        app_row["exposures"] = rows(db, "SELECT rule, detail FROM tdr_ci_exposures WHERE ci_id=? AND status='open'",
                                    (app_row["id"],))
    bia["suppliers"] = rows(db, """SELECT b.id AS link_id, b.note, s.id, s.code, s.name, s.tier, s.status,
        (SELECT COUNT(*) FROM tdr_supplier_risks r WHERE r.supplier_id=s.id AND r.status IN ('open','in_treatment'))
        AS open_risks FROM tdr_bia_suppliers b JOIN tdr_suppliers s ON s.id=b.supplier_id WHERE b.bia_id=?
        ORDER BY s.name""", (bia_id,))
    bia["risks"] = rows(db, """SELECT l.id AS link_id, r.id, r.code, r.title, r.risk_level, r.status FROM tdr_bia_risks l
        JOIN tdr_supplier_risks r ON r.id=l.risk_id WHERE l.bia_id=? ORDER BY r.code""", (bia_id,))
    bia["plans"] = rows(db, """SELECT p.id, p.code, p.title, p.plan_type, p.status, (SELECT MAX(x.actual_date) FROM
        tdr_bc_exercises x WHERE x.plan_id=p.id AND x.status='completed') AS last_exercise FROM tdr_bc_plans p
        JOIN tdr_bc_plan_bias pb ON pb.plan_id=p.id WHERE pb.bia_id=? ORDER BY p.code""", (bia_id,))
    gaps = []
    for app_row in bia["applications"]:
        if app_row["open_exposures"]:
            gaps.append(f"{app_row['name']}: {app_row['open_exposures']} açık CI riski (destek bitişi / yama)")
    for sup in bia["suppliers"]:
        if sup["open_risks"]:
            gaps.append(f"{sup['name']}: {sup['open_risks']} açık tedarikçi riski")
    if bia["status"] == "approved" and not bia["plans"]:
        gaps.append("Bu BİA'yı kapsayan iş sürekliliği planı yok")
    bia["gaps"] = gaps
    return bia


def bia_context(c):
    authz.check(c.principal, BIAS, "read")
    return bia_context_data(c.db, c.app, c.params["id"])


def plan_links(c):
    plan = crud.get(c.db, PLANS, c.params["id"])
    authz.check(c.principal, PLANS, "write")
    if plan["status"] == "approved":
        raise crud.Conflict("Onaylı planın kapsamı değiştirilmez; önce revizyona alın")
    ids = c.body.get("bia_ids")
    if not isinstance(ids, list) or any(type(i) is not int for i in ids):
        raise crud.Invalid("bia_ids tam sayı listesi olmalı")
    if ids and len(rows(c.db, f"SELECT id FROM tdr_bias WHERE id IN ({','.join('?' * len(set(ids)))})",
                        sorted(set(ids)))) != len(set(ids)):
        raise crud.Invalid("Bulunamayan BİA seçildi")
    c.db.execute("DELETE FROM tdr_bc_plan_bias WHERE plan_id=?", (plan["id"],))
    for bia_id in sorted(set(ids)):
        c.db.execute("INSERT INTO tdr_bc_plan_bias (plan_id, bia_id) VALUES (?,?)", (plan["id"], bia_id))
    audit.log(c.db, c.principal, "LINK", PLANS.name, plan["id"], {"bia_ids": sorted(set(ids))})
    return plan_context_data(c.db, plan["id"])


def plan_context_data(db, plan_id):
    plan = crud.get(db, PLANS, plan_id)
    plan["steps"] = rows(db, "SELECT * FROM tdr_bc_plan_steps WHERE plan_id=? ORDER BY CASE phase WHEN 'activation' "
                             "THEN 1 WHEN 'response' THEN 2 WHEN 'recovery' THEN 3 ELSE 4 END, position, id", (plan_id,))
    plan["bias"] = rows(db, """SELECT b.id, b.code, b.title, b.rto_hours, b.mtpd_hours, b.criticality, b.status
        FROM tdr_bias b JOIN tdr_bc_plan_bias pb ON pb.bia_id=b.id WHERE pb.plan_id=? ORDER BY b.code""", (plan_id,))
    plan["applications"] = rows(db, """SELECT a.id AS link_id, a.recovery_order, a.target_rto_hours, a.note, ci.id,
        ci.code, ci.name, ci.ci_class FROM tdr_bc_plan_applications a JOIN tdr_cmdb_cis ci ON ci.id=a.ci_id
        WHERE a.plan_id=? ORDER BY a.recovery_order, ci.name""", (plan_id,))
    plan["exercises"] = rows(db, "SELECT * FROM tdr_bc_exercises WHERE plan_id=? ORDER BY planned_date DESC", (plan_id,))
    last = next((x for x in plan["exercises"] if x["status"] == "completed"), None)
    plan["last_exercise"] = last
    months = int(policy(db, "bcm.exercise_months", 12))
    plan["exercise_due"] = (date.fromisoformat(str(last["actual_date"])) + timedelta(days=round(months * 30.44))).isoformat() \
        if last and last["actual_date"] else None
    plan["document"] = one(db, "SELECT id, code, title, status FROM tdr_documents WHERE id=?", (plan["document_id"],)) \
        if plan["document_id"] else None
    return plan


def plan_context(c):
    authz.check(c.principal, PLANS, "read")
    return plan_context_data(c.db, c.params["id"])


def exercise_context(c):
    authz.check(c.principal, EXERCISES, "read")
    item = crud.get(c.db, EXERCISES, c.params["id"])
    item["plan"] = one(c.db, "SELECT id, code, title, plan_type, status FROM tdr_bc_plans WHERE id=?", (item["plan_id"],))
    item["findings"] = rows(c.db, """SELECT f.id, f.code, f.title, f.severity, f.status FROM tdr_findings f
        JOIN tdr_bc_exercise_findings m ON m.finding_id=f.id WHERE m.exercise_id=? ORDER BY f.id""", (item["id"],))
    item["gap_minutes"] = (item["achieved_recovery_minutes"] - item["target_recovery_minutes"]) \
        if item["achieved_recovery_minutes"] is not None and item["target_recovery_minutes"] is not None else None
    return item


def exercise_finding(c):
    """Tatbikattan GRC bulgusu açar (DÖF akışı GRC'de); bulgu tatbikata bağlanır."""
    exercise = crud.get(c.db, EXERCISES, c.params["id"])
    findings = RESOURCES["findings"]
    authz.check(c.principal, EXERCISES, "write")
    body = {k: v for k, v in c.body.items() if k in ("title", "description", "severity", "owner", "due_date")}
    body["description"] = (body.get("description") or "") + f"\n\nKaynak: {exercise['code']} — {exercise['title']}"
    guard_readonly(findings, body)
    finding_id = crud.insert(c.db, findings, {**body, "source": "exercise"} if "source" in findings.fields else body,
                             c.principal)
    c.db.execute("INSERT INTO tdr_bc_exercise_findings (exercise_id, finding_id) VALUES (?,?)", (exercise["id"], finding_id))
    audit.log(c.db, c.principal, "CREATE", findings.name, finding_id, {"exercise_id": exercise["id"]})
    return 201, {"finding_id": finding_id}


def overview(c):
    authz.check(c.principal, BIAS, "read")
    db = c.db
    today = date.today().isoformat()
    months = int(policy(db, "bcm.exercise_months", 12))
    limit = (date.today() - timedelta(days=round(months * 30.44))).isoformat()
    # kapsam ana (değer) süreçlerine göre ölçülür: ISO 22301 8.2.2 kritik faaliyetleri BİA ile belirler
    processes = one(db, "SELECT COUNT(*) AS n FROM tdr_processes WHERE active=1 AND process_type='core'")["n"]
    covered = one(db, """SELECT COUNT(DISTINCT b.process_id) AS n FROM tdr_bias b JOIN tdr_processes p ON p.id=b.process_id
        WHERE b.status='approved' AND p.active=1 AND p.process_type='core'""")["n"]
    plans = rows(db, """SELECT p.id, p.code, p.title, p.status, (SELECT MAX(x.actual_date) FROM tdr_bc_exercises x
        WHERE x.plan_id=p.id AND x.status='completed') AS last_exercise FROM tdr_bc_plans p WHERE p.status='approved'""")
    gaps = rows(db, """SELECT x.id, x.code, x.title, x.target_recovery_minutes, x.achieved_recovery_minutes, p.code AS plan_code
        FROM tdr_bc_exercises x JOIN tdr_bc_plans p ON p.id=x.plan_id WHERE x.status='completed'
        AND x.achieved_recovery_minutes > x.target_recovery_minutes ORDER BY x.actual_date DESC""")
    critical_without_plan = rows(db, """SELECT b.id, b.code, b.title FROM tdr_bias b WHERE b.status='approved' AND
        b.criticality IN ('critical','high') AND NOT EXISTS (SELECT 1 FROM tdr_bc_plan_bias pb JOIN tdr_bc_plans p
        ON p.id=pb.plan_id WHERE pb.bia_id=b.id AND p.status='approved')""")
    eos_apps = rows(db, """SELECT DISTINCT b.id, b.code, b.title, ci.name AS ci_name, e.rule FROM tdr_bias b
        JOIN tdr_bia_applications a ON a.bia_id=b.id JOIN tdr_cmdb_cis ci ON ci.id=a.ci_id
        JOIN tdr_ci_exposures e ON e.ci_id=ci.id AND e.status='open' WHERE b.status <> 'archived' ORDER BY b.code""")
    return {
        "processes": processes, "processes_with_bia": covered,
        "coverage_pct": round(100 * covered / processes, 1) if processes else None,
        "bias": rows(db, "SELECT status AS key, COUNT(*) AS count FROM tdr_bias GROUP BY status"),
        "criticality": rows(db, "SELECT criticality AS key, COUNT(*) AS count FROM tdr_bias WHERE status<>'archived' "
                                "AND criticality IS NOT NULL GROUP BY criticality"),
        "plans_total": len(plans),
        "plans_not_exercised": [p for p in plans if not p["last_exercise"] or str(p["last_exercise"]) < limit],
        "exercises_planned": rows(db, "SELECT id, code, title, planned_date, exercise_type FROM tdr_bc_exercises WHERE "
                                      "status='planned' ORDER BY planned_date LIMIT 20"),
        "exercises_year": one(db, "SELECT COUNT(*) AS n FROM tdr_bc_exercises WHERE status='completed' AND actual_date >= ?",
                              (date.today().replace(month=1, day=1).isoformat(),))["n"],
        "rto_gaps": gaps, "critical_without_plan": critical_without_plan, "eos_applications": eos_apps,
        "bia_review_overdue": one(db, "SELECT COUNT(*) AS n FROM tdr_bias WHERE status='approved' AND review_date < ?",
                                  (today,))["n"],
        "plan_review_overdue": one(db, "SELECT COUNT(*) AS n FROM tdr_bc_plans WHERE status='approved' AND review_date < ?",
                                   (today,))["n"],
        "exercise_months": months,
    }


def register(app):
    app.route("POST", API + "/bias/{id}/impacts", set_impacts)
    app.route("POST", API + "/bias/{id}/transition", _routed("bias", transition))
    app.route("GET", API + "/bias/{id}/context", bia_context)
    app.route("POST", API + "/bc_plans/{id}/transition", _routed("plans", transition))
    app.route("POST", API + "/bc_plans/{id}/bias", plan_links)
    app.route("GET", API + "/bc_plans/{id}/context", plan_context)
    app.route("GET", API + "/bc_exercises/{id}/context", exercise_context)
    app.route("POST", API + "/bc_exercises/{id}/findings", exercise_finding)
    app.route("GET", API + "/bcm/overview", overview)


DEFAULT_POLICIES = (
    ("bcm.intolerable_level", 4, "BİA'da tolere edilemez etki seviyesi (1–5); MTPD bu seviyeye ulaşılan ilk zaman aralığıdır"),
    ("bcm.criticality_hours", CRITICALITY, "MTPD'ye göre süreç kritikliği üst sınırları (saat)"),
    ("bcm.exercise_months", 12, "Onaylı her planın en geç kaç ayda bir tatbik edilmesi gerektiği"),
)


def seed(db):
    import json
    for code, value, description in DEFAULT_POLICIES:
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))
