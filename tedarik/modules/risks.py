"""Tedarikçi riskleri. Puanlama KS GRC ile aynıdır: olasılık ve etki 1-5, iştah 1-25,
artık skor = içsel × (1 − toplam azaltıcı katkı). Değerlendirmeler değiştirilemez geçmiş olarak saklanır.
"""
import json

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API
from ..schema import Resource, fk

M = "risks"
WEIGHTS = {"low": 20, "medium": 40, "high": 60}   # KS GRC: düşük/orta/yüksek katkı yüzdeleri

RISKS = Resource("supplier_risks", "Tedarikçi Riskleri", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "supplier_id": fk("suppliers"),
    "engagement_id": fk("engagements", False), "category": "TEXT NOT NULL", "description": "TEXT",
    "owner": "TEXT NOT NULL", "appetite": "INTEGER NOT NULL", "status": "TEXT NOT NULL DEFAULT 'open'",
    "strategy": "TEXT", "review_due": "TEXT", "decision_rationale": "TEXT", "control_risk_ref": "TEXT",
    "created_at": "TEXT NOT NULL", "updated_at": "TEXT"},
    module=M, write="write", search=("code", "title"), machine="r",
    enums={"category": ("continuity", "security", "compliance", "financial", "concentration", "performance",
                        "reputation", "exit"),
           "status": ("open", "treating", "accepted", "closed"),
           "strategy": ("accept", "mitigate", "avoid", "transfer")})

ASSESSMENTS = Resource("risk_assessments", "Risk Değerlendirmeleri", {
    "risk_id": fk("supplier_risks"), "likelihood": "INTEGER NOT NULL", "impact": "INTEGER NOT NULL",
    "inherent": "INTEGER NOT NULL", "mitigation_pct": "REAL NOT NULL", "residual": "REAL NOT NULL",
    "mitigations_json": "TEXT", "rationale": "TEXT NOT NULL", "assessed_by": "TEXT NOT NULL",
    "assessed_at": "TEXT NOT NULL"}, module=M, write="write", api=("list", "get"), search=(), machine="r")

Resource("risk_actions", "Risk İşleme Faaliyetleri", {
    "risk_id": fk("supplier_risks"), "title": "TEXT NOT NULL", "owner": "TEXT NOT NULL", "due_date": "TEXT NOT NULL",
    "status": "TEXT NOT NULL DEFAULT 'open'", "note": "TEXT"},
    module=M, write="write", search=("title",), enums={"status": ("open", "in_progress", "done", "cancelled")})


def contribution(mitigations):
    """Azaltıcı önlemlerin toplam katkısı (%). Kısmen etkili önlem ağırlığının yarısını verir; üst sınır %100."""
    if not isinstance(mitigations, list):
        raise crud.Invalid("mitigations liste olmalı")
    total = 0.0
    for item in mitigations:
        if not isinstance(item, dict) or item.get("weight") not in WEIGHTS:
            raise crud.Invalid("Her önlem için weight: low | medium | high")
        effectiveness = item.get("effectiveness", "effective")
        if effectiveness not in ("effective", "partial"):
            raise crud.Invalid("effectiveness: effective | partial")
        total += WEIGHTS[item["weight"]] / (1 if effectiveness == "effective" else 2)
    return min(total, 100.0)


def latest(db, risk_id):
    return one(db, "SELECT * FROM tdr_risk_assessments WHERE risk_id=? ORDER BY id DESC LIMIT 1", (risk_id,))


def _risk_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if type(merged.get("appetite")) is not int or not 1 <= merged["appetite"] <= 25:
        raise crud.Invalid("Risk iştahı 1-25 aralığında tamsayı olmalı")
    if current is None or data.get("status") not in ("accepted", "closed"):
        return
    last = latest(db, current["id"])
    if not last or not merged.get("decision_rationale"):
        raise crud.Conflict("Kabul ve kapanış için güncel değerlendirme ve karar gerekçesi gerekir")
    if data["status"] == "accepted" and last["residual"] > merged["appetite"]:
        # İştah üstü kabul: yönetici seviyesi ve değerlendirmeyi yapandan farklı kişi (yerel geliştirme hariç).
        if not principal or not principal.can("manage"):
            raise crud.Forbidden("İştah üstü risk kabulü için yönetici onayı gerekir")
        if principal.auth_type != "dev" and principal.username == last["assessed_by"]:
            raise crud.Forbidden("İştah üstü kabulü, değerlendirmeyi yapandan farklı bir yönetici onaylar")


RISKS.before_save = _risk_rules


def assess(c):
    authz.check(c.principal, ASSESSMENTS, "write")
    risk = crud.get(c.db, RISKS, c.params["id"])
    likelihood, impact = c.body["likelihood"], c.body["impact"]
    if any(type(v) is not int or not 1 <= v <= 5 for v in (likelihood, impact)):
        raise crud.Invalid("Olasılık ve etki 1-5 aralığında tamsayı olmalı")
    mitigations = c.body.get("mitigations", [])
    pct = contribution(mitigations)
    inherent = likelihood * impact
    residual = round(inherent * (1 - pct / 100), 2)
    record_id = crud.insert(c.db, ASSESSMENTS, {
        "risk_id": risk["id"], "likelihood": likelihood, "impact": impact, "inherent": inherent,
        "mitigation_pct": pct, "residual": residual,
        "mitigations_json": json.dumps(mitigations, ensure_ascii=False), "rationale": c.body["rationale"],
        "assessed_by": c.principal.username, "assessed_at": utcnow()})
    audit.log(c.db, c.principal, "ASSESS", "supplier_risks", risk["id"], {"inherent": inherent, "residual": residual})
    return 201, {"id": record_id, "inherent": inherent, "residual": residual,
                 "above_appetite": residual > risk["appetite"]}


def risk_context(c):
    authz.check(c.principal, RISKS, "read")
    risk = crud.get(c.db, RISKS, c.params["id"])
    risk["assessments"] = rows(c.db, "SELECT * FROM tdr_risk_assessments WHERE risk_id=? ORDER BY id DESC",
                               (risk["id"],))
    risk["actions"] = rows(c.db, "SELECT * FROM tdr_risk_actions WHERE risk_id=? ORDER BY due_date", (risk["id"],))
    return risk


def register(app):
    app.route("POST", API + "/supplier_risks/{id}/assessments", assess)
    app.route("GET", API + "/supplier_risks/{id}/context", risk_context)
