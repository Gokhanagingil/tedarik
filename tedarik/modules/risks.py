"""Tedarikçi riskleri. Model ve kurallar KS GRC ile aynıdır (control@7720f4b, risk_management.py).

- Risk ifadesi: neden (cause), olay (risk_event), iş etkisi (consequence); olasılık ve etki 1-5, iştah 1-25.
- Değerlendirme riskin o anki anlık görüntüsünü saklar; içsel = olasılık × etki;
  katkı düşük %20, orta %40, yüksek %60, kısmen etkili önlem yarısı, toplam en çok %100;
  artık = içsel × (1 − katkı).
- Kabul ve kapanış güncel değerlendirme ve karar gerekçesi ister; karar ayrı, değiştirilemez kayıttır.
  Değerlendirmeden sonra risk veya iştah değiştiyse yeniden değerlendirme gerekir.
- İştah üstü kabulü, değerlendirmeyi yapandan farklı bir Yönetici ayrı istisna gerekçesiyle onaylar.
- Kabul edilmiş veya kapalı risk değiştirilmeden önce yalnızca gerekçeyle yeniden açılır; yeniden açılan
  risk için yeni değerlendirme gerekir. Açık faaliyeti olan risk kapatılamaz.

Bilinçli fark: portalda kontrol kaydı yoktur. Azaltıcı önlemler (mitigations) serbest tanımlıdır; KS GRC
kontrolüne dayanıyorsa `control_ref` alanına kontrol kodu yazılır.
"""
import json
from datetime import date
from decimal import Decimal

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, guard_readonly
from ..schema import Resource, fk
from .core import engagement_or_supplier, via

M = "risks"
WEIGHTS = {"low": Decimal("0.2"), "medium": Decimal("0.4"), "high": Decimal("0.6")}
TERMINAL = ("accepted", "closed")
DECISION_INPUT = {"assessment_id", "decision_rationale", "exception_rationale"}
STATEMENT = ("owner", "cause", "risk_event", "consequence")
SNAPSHOT = ("code", "title", "supplier_id", "engagement_id", "owner", "cause", "risk_event", "consequence",
            "likelihood", "impact", "review_date", "response_strategy", "treatment")
COMPARED = ("supplier_id", "engagement_id", "cause", "risk_event", "consequence", "likelihood", "impact", "owner")
TEXT_LIMIT = 5000

RISKS = Resource("supplier_risks", "Tedarikçi Riskleri", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "supplier_id": fk("suppliers"),
    "engagement_id": fk("engagements", False), "category": "TEXT NOT NULL", "description": "TEXT",
    "cause": "TEXT", "risk_event": "TEXT", "consequence": "TEXT",
    "likelihood": "INTEGER NOT NULL DEFAULT 3", "impact": "INTEGER NOT NULL DEFAULT 3",
    "owner": "TEXT NOT NULL", "appetite": "INTEGER NOT NULL", "status": "TEXT NOT NULL DEFAULT 'open'",
    "response_strategy": "TEXT", "treatment": "TEXT", "review_date": "DATE", "control_risk_ref": "TEXT",
    "origin_ref": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="write", api=("list", "get", "create"), search=("code", "title"), machine="r",
    readonly=("origin_ref",),
    enums={"category": ("continuity", "security", "compliance", "financial", "concentration", "performance",
                        "privacy", "reputation", "exit"),
           "status": ("open", "in_treatment", "accepted", "closed"),
           "response_strategy": ("mitigate", "avoid", "transfer", "accept")})

ASSESSMENTS = Resource("risk_assessments", "Risk Değerlendirmeleri", {
    "risk_id": fk("supplier_risks"), "assessed_at": "TIMESTAMP NOT NULL", "assessor": "TEXT NOT NULL",
    "rationale": "TEXT NOT NULL", "inherent": "INTEGER NOT NULL", "mitigation_pct": "REAL NOT NULL",
    "residual": "REAL NOT NULL", "appetite": "INTEGER NOT NULL", "snapshot": "TEXT NOT NULL"},
    module=M, write="write", api=("list", "get"), search=(), machine="r", immutable=True)

DECISIONS = Resource("risk_decisions", "Risk Kararları", {
    "risk_id": fk("supplier_risks"), "assessment_id": fk("risk_assessments", False),
    "from_status": "TEXT NOT NULL", "to_status": "TEXT NOT NULL", "actor": "TEXT NOT NULL",
    "actor_role": "TEXT NOT NULL", "decided_at": "TIMESTAMP NOT NULL", "rationale": "TEXT NOT NULL",
    "exception_rationale": "TEXT", "residual": "REAL", "appetite": "INTEGER", "review_date": "DATE"},
    module=M, write="admin", api=("list", "get"), search=(), immutable=True)

ACTIONS = Resource("risk_actions", "Risk İşleme Faaliyetleri", {
    "code": "TEXT NOT NULL UNIQUE", "risk_id": fk("supplier_risks"), "title": "TEXT NOT NULL",
    "description": "TEXT", "owner": "TEXT NOT NULL", "due_date": "DATE NOT NULL",
    "priority": "TEXT NOT NULL DEFAULT 'medium'", "status": "TEXT NOT NULL DEFAULT 'open'",
    "resolution": "TEXT", "closed_at": "TIMESTAMP", "created_at": "TIMESTAMP NOT NULL"},
    module=M, write="write", search=("code", "title"), readonly=("closed_at",),
    enums={"priority": ("low", "medium", "high", "critical"),
           "status": ("open", "in_progress", "validation", "completed", "cancelled")})


def _text(value, message):
    if not isinstance(value, str) or not value.strip() or len(value) > TEXT_LIMIT:
        raise crud.Invalid(message)
    return value.strip()


def _ensure_statement(risk):
    if any(not isinstance(risk.get(k), str) or not risk[k].strip() for k in STATEMENT):
        raise crud.Invalid("Risk sahibi, neden, olay ve etki gerekli")


def _risk_fields(db, data, current, principal):
    merged = {**(current or {}), **data}
    if type(merged.get("appetite")) is not int or not 1 <= merged["appetite"] <= 25:
        raise crud.Invalid("Risk iştahı eşiği 1–25 aralığında tamsayı olmalı")
    for field in ("likelihood", "impact"):
        value = merged.get(field, 3)
        if type(value) is not int or not 1 <= value <= 5:
            raise crud.Invalid("Olasılık ve etki 1–5 arasında olmalı")
    if merged.get("review_date"):
        try:
            if date.fromisoformat(merged["review_date"]).isoformat() != merged["review_date"]:
                raise ValueError
        except (TypeError, ValueError):
            raise crud.Invalid("Gözden geçirme tarihi YYYY-AA-GG olmalı") from None
    if current is None:
        if merged.get("status", "open") in TERMINAL:
            raise crud.Invalid("Kabul veya kapanış için kayıtlı değerlendirme ve karar gerekli")
        if any(merged.get(k) for k in ("cause", "risk_event", "consequence")):
            _ensure_statement(merged)


RISKS.before_save = _risk_fields


def latest(db, risk_id):
    return one(db, "SELECT * FROM tdr_risk_assessments WHERE risk_id=? ORDER BY id DESC LIMIT 1", (risk_id,))


def decide(db, current, proposal, details, principal):
    """KS GRC risk_management.decision() kurallarının karşılığı. Karar kaydı gerekiyorsa yazar."""
    old, status = current["status"], proposal.get("status", current["status"])
    for field in STATEMENT:
        if isinstance(current.get(field), str) and current[field].strip() and (
                not isinstance(proposal.get(field), str) or not proposal[field].strip()):
            raise crud.Invalid("Mevcut risk sahibi veya risk ifadesi boş bırakılamaz")
    if old == status or (old not in TERMINAL and status not in TERMINAL):
        if details:
            raise crud.Invalid("Karar alanları yalnızca kabul, kapanış veya yeniden açma işleminde kullanılabilir")
        if old in TERMINAL and any(proposal.get(k) != v for k, v in current.items()):
            raise crud.Conflict("Karar verilmiş riski değiştirmeden önce yeniden açın")
        return None
    reopening = old in TERMINAL
    if reopening and (status != "open" or any(proposal.get(k) != v for k, v in current.items()
                                               if k not in ("status", "updated_at"))):
        raise crud.Invalid("Önce yalnızca risk durumunu Açık olarak değiştirin")
    rationale = _text(details.get("decision_rationale"), "Karar gerekçesi gerekli (en fazla 5.000 karakter)")
    last = latest(db, current["id"])
    exception = details.get("exception_rationale")
    if reopening:
        if set(details) != {"decision_rationale"}:
            raise crud.Invalid("Yeniden açma için yalnızca karar gerekçesi girin")
    else:
        _ensure_statement(proposal)
        if not last:
            raise crud.Conflict("Önce artık risk değerlendirmesi kaydedilmeli")
        if type(details.get("assessment_id")) is not int or details["assessment_id"] != last["id"]:
            raise crud.Conflict("Karar için güncel değerlendirmeyi seçin")
        prior = one(db, "SELECT assessment_id FROM tdr_risk_decisions WHERE risk_id=? AND to_status='open' "
                        "ORDER BY id DESC LIMIT 1", (current["id"],))
        if prior and prior["assessment_id"] == last["id"]:
            raise crud.Conflict("Yeniden açılan risk için yeni değerlendirme gerekli")
        snapshot = json.loads(last["snapshot"])
        if any(proposal.get(k) != snapshot.get(k) for k in COMPARED) or last["appetite"] != proposal.get("appetite"):
            raise crud.Conflict("Risk değişti. Kabul veya kapanıştan önce yeniden değerlendirin")
        if status == "accepted" and (proposal.get("response_strategy") != "accept" or not proposal.get("review_date")
                                     or proposal["review_date"] < date.today().isoformat()):
            raise crud.Invalid("Kabul stratejisini ve geçerli bir gözden geçirme tarihini seçin")
        if status == "closed" and one(db, "SELECT 1 AS x FROM tdr_risk_actions WHERE risk_id=? "
                                          "AND status NOT IN ('completed','cancelled')", (current["id"],)):
            raise crud.Conflict("Açık işleme faaliyeti olan risk kapatılamaz")
        if status == "accepted" and last["residual"] > last["appetite"]:
            same_person = principal.username == last["assessor"] and principal.auth_type != "dev"
            if principal.role != "ADMIN" or same_person:
                raise crud.Forbidden("Risk iştahı istisnasını değerlendirmeyi yapandan farklı bir yönetici onaylamalı")
            exception = _text(exception, "Risk iştahının aşılması için ayrı istisna gerekçesi gerekli")
        elif exception:
            raise crud.Invalid("İstisna yalnızca iştah üzerindeki riskin kabulünde kullanılabilir")
    return db.execute(
        "INSERT INTO tdr_risk_decisions (risk_id, assessment_id, from_status, to_status, actor, actor_role, "
        "decided_at, rationale, exception_rationale, residual, appetite, review_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (current["id"], last["id"] if last else None, old, status, principal.username,
         principal.role, utcnow(), rationale, exception or None, last["residual"] if last else None,
         last["appetite"] if last else None, proposal.get("review_date"))).lastrowid


def update_risk(c):
    authz.check(c.principal, RISKS, "write")
    body = dict(c.body)
    details = {k: body.pop(k) for k in DECISION_INPUT if k in body}
    guard_readonly(RISKS, body)
    if not body:
        raise crud.Invalid("Güncellenecek alan yok")
    current = crud.get(c.db, RISKS, c.params["id"])
    crud.check_scope(c.db, RISKS, c.principal, current)
    cleaned = crud.clean(body)
    crud.validate(RISKS, cleaned, partial=True)
    _risk_fields(c.db, cleaned, current, c.principal)
    decision_id = decide(c.db, current, {**current, **cleaned}, details, c.principal)
    record = crud.update(c.db, RISKS, current["id"], body, c.principal)
    audit.log(c.db, c.principal, "UPDATE", RISKS.name, current["id"], body)
    if decision_id:
        audit.log(c.db, c.principal, "DECIDE", RISKS.name, current["id"],
                  {"to_status": record["status"], "decision_id": decision_id})
    return record


def contribution(mitigations):
    """Azaltıcı önlemlerin toplam katkısı (0-1). Kısmen etkili önlem ağırlığının yarısını verir; üst sınır 1."""
    if not isinstance(mitigations, list) or len(mitigations) > 50:
        raise crud.Invalid("mitigations en fazla 50 öğelik liste olmalı")
    total, items = Decimal(0), []
    for item in mitigations:
        if not isinstance(item, dict) or item.get("weight") not in WEIGHTS:
            raise crud.Invalid("Her önlem için weight: low | medium | high")
        effectiveness = item.get("effectiveness", "effective")
        if effectiveness not in ("effective", "partial"):
            raise crud.Invalid("effectiveness: effective | partial")
        value = WEIGHTS[item["weight"]] * (Decimal("0.5") if effectiveness == "partial" else 1)
        total += value
        items.append({"title": str(item.get("title") or "")[:300], "weight": item["weight"],
                      "effectiveness": effectiveness, "control_ref": item.get("control_ref"),
                      "contribution": float(value)})
    return min(total, Decimal(1)), items


def assess(c):
    authz.check(c.principal, ASSESSMENTS, "write")
    risk = crud.get(c.db, RISKS, c.params["id"])
    crud.check_scope(c.db, RISKS, c.principal, risk)
    if risk["status"] in TERMINAL:
        raise crud.Conflict("Yeni değerlendirme için riski yeniden açın")
    if not risk.get("review_date") or not all(risk.get(k) for k in STATEMENT):
        raise crud.Invalid("Önce risk sahibini, neden, olay ve etkiyi ve gözden geçirme tarihini kaydedin")
    rationale = _text(c.body.get("rationale"), "Bir değerlendirme gerekçesi girin (en fazla 5.000 karakter)")
    total, credits = contribution(c.body.get("mitigations", []))
    inherent = risk["likelihood"] * risk["impact"]
    residual = float(inherent * (1 - total))
    snapshot = {k: risk.get(k) for k in SNAPSHOT}
    snapshot.update({"method": "weighted-v1", "mitigations": credits})
    record_id = c.db.execute(
        "INSERT INTO tdr_risk_assessments (risk_id, assessed_at, assessor, rationale, inherent, mitigation_pct, "
        "residual, appetite, snapshot) VALUES (?,?,?,?,?,?,?,?,?)",
        (risk["id"], utcnow(), c.principal.username, rationale, inherent, float(total * 100), residual,
         risk["appetite"], json.dumps(snapshot, ensure_ascii=False))).lastrowid
    audit.log(c.db, c.principal, "ASSESS", RISKS.name, risk["id"], {"inherent": inherent, "residual": residual})
    return 201, {"id": record_id, "inherent": inherent, "residual": residual,
                 "above_appetite": residual > risk["appetite"]}


def _action_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    risk = crud.get(db, RISKS, merged["risk_id"])
    relinked = current is not None and data.get("risk_id") not in (None, current["risk_id"])
    if risk["status"] in TERMINAL and (current is None or relinked):
        raise crud.Conflict("Bağlantıyı değiştirmeden önce riski yeniden açın")
    if relinked and crud.get(db, RISKS, current["risk_id"])["status"] in TERMINAL:
        raise crud.Conflict("Bağlantıyı değiştirmeden önce riski yeniden açın")
    if risk["status"] == "closed" and merged.get("status") not in ("completed", "cancelled"):
        raise crud.Conflict("Faaliyeti açmadan önce riski yeniden açın")
    if "status" in data:
        data["closed_at"] = utcnow() if data["status"] in ("completed", "cancelled") else None


ACTIONS.before_save = _action_rules
RISKS.scope = engagement_or_supplier
ACTIONS.scope = via("supplier_risks", "risk_id")


def risk_context(c):
    authz.check(c.principal, RISKS, "read")
    risk = crud.get(c.db, RISKS, c.params["id"])
    risk["assessments"] = rows(c.db, "SELECT * FROM tdr_risk_assessments WHERE risk_id=? ORDER BY id DESC",
                               (risk["id"],))
    for item in risk["assessments"]:
        item["snapshot"] = json.loads(item["snapshot"])
    risk["decisions"] = rows(c.db, "SELECT * FROM tdr_risk_decisions WHERE risk_id=? ORDER BY id DESC",
                             (risk["id"],))
    risk["actions"] = rows(c.db, "SELECT * FROM tdr_risk_actions WHERE risk_id=? ORDER BY due_date", (risk["id"],))
    last = risk["assessments"][0] if risk["assessments"] else None
    risk["inherent_score"] = risk["likelihood"] * risk["impact"]
    risk["residual_score"] = last["residual"] if last else None
    return risk


def register(app):
    app.route("PATCH", API + "/supplier_risks/{id}", update_risk)
    app.route("POST", API + "/supplier_risks/{id}/assessments", assess)
    app.route("GET", API + "/supplier_risks/{id}/context", risk_context)
