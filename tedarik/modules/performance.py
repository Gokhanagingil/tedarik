"""Performans: SLA tanımı ve ölçümü, kriter bazlı değerlendirme (scorecard), performans olay günlüğü."""
from .. import auth as authz, crud
from ..db import one, rows, today, utcnow
from ..http import API
from ..schema import RESOURCES, Resource, fk
from .core import engagement_or_supplier, engagement_units, via

M = "performance"

SLAS = Resource("sla_definitions", "SLA Tanımları", {
    "engagement_id": fk("engagements"), "code": "TEXT NOT NULL", "name": "TEXT NOT NULL",
    "unit": "TEXT NOT NULL DEFAULT 'percent'", "target_value": "REAL NOT NULL",
    "direction": "TEXT NOT NULL DEFAULT 'higher_better'", "period": "TEXT NOT NULL DEFAULT 'monthly'",
    "active": "INTEGER NOT NULL DEFAULT 1"},
    module=M, unique=(("engagement_id", "code"),), machine="r",
    enums={"unit": ("percent", "hours", "minutes", "count"), "direction": ("higher_better", "lower_better"),
           "period": ("monthly", "quarterly", "yearly")})

MEASUREMENTS = Resource("sla_measurements", "SLA Ölçümleri", {
    "sla_id": fk("sla_definitions"), "period_start": "DATE NOT NULL", "actual_value": "REAL NOT NULL",
    "met": "INTEGER NOT NULL", "source": "TEXT NOT NULL DEFAULT 'manual'", "note": "TEXT",
    "recorded_by": "TEXT NOT NULL", "recorded_at": "TIMESTAMP NOT NULL"},
    module=M, write="write", unique=(("sla_id", "period_start"),), search=(), machine="rw",
    readonly=("met", "recorded_by", "recorded_at"), enums={"source": ("manual", "import", "mcp")})

Resource("review_criteria", "Değerlendirme Kriterleri", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "weight": "INTEGER NOT NULL DEFAULT 1",
    "active": "INTEGER NOT NULL DEFAULT 1"}, module=M, write="admin")

Resource("performance_reviews", "Performans Değerlendirmeleri", {
    "supplier_id": fk("suppliers"), "engagement_id": fk("engagements", False), "period_start": "DATE NOT NULL",
    "period_end": "DATE NOT NULL", "comment": "TEXT", "reviewer": "TEXT NOT NULL", "created_at": "TIMESTAMP NOT NULL"},
    module=M, write="write", search=("comment",), readonly=("reviewer",))

Resource("review_scores", "Değerlendirme Puanları", {
    "review_id": fk("performance_reviews", cascade=True), "criterion_id": fk("review_criteria"),
    "score": "INTEGER NOT NULL", "note": "TEXT"},
    module=M, write="write", unique=(("review_id", "criterion_id"),), search=())

EVENTS = Resource("performance_events", "Performans Olayları", {
    "supplier_id": fk("suppliers"), "engagement_id": fk("engagements", False), "event_type": "TEXT NOT NULL",
    "severity": "TEXT NOT NULL DEFAULT 'medium'", "occurred_at": "TIMESTAMP NOT NULL", "description": "TEXT NOT NULL",
    "reference": "TEXT", "source": "TEXT NOT NULL DEFAULT 'manual'", "recorded_by": "TEXT NOT NULL"},
    module=M, write="write", search=("description", "reference"), machine="rw", readonly=("recorded_by",),
    enums={"event_type": ("sla_breach", "incident", "delivery_delay", "escalation", "praise", "other"),
           "severity": ("low", "medium", "high", "critical"), "source": ("manual", "import", "mcp")})


def _machine_source(data, principal):
    """MCP anahtarı yalnızca kendi kaynağını beyan ederek yazar (KS GRC kuralı)."""
    if principal and principal.auth_type == "api_key" and data.get("source") != "mcp":
        raise crud.Forbidden("MCP anahtarı yalnızca source=mcp ile kayıt yazabilir")


def _measurement(db, data, current, principal):
    _machine_source(data, principal)
    merged = {**(current or {}), **data}
    sla = crud.get(db, SLAS, merged["sla_id"])
    higher = sla["direction"] == "higher_better"
    data["met"] = int(merged["actual_value"] >= sla["target_value"] if higher
                      else merged["actual_value"] <= sla["target_value"])
    data["recorded_by"] = principal.username if principal else "system"
    data["recorded_at"] = utcnow()


def _event(db, data, current, principal):
    _machine_source(data, principal)
    if current is None:
        data["recorded_by"] = principal.username if principal else "system"


def _review(db, data, current, principal):
    if current is None:
        data["reviewer"] = principal.username if principal else "system"


def _score(db, data, current, principal):
    score = {**(current or {}), **data}.get("score")
    if type(score) is not int or not 1 <= score <= 5:
        raise crud.Invalid("Puan 1-5 aralığında tamsayı olmalı")


MEASUREMENTS.before_save = _measurement
SLAS.scope = lambda db, record: engagement_units(db, record.get("engagement_id"))
MEASUREMENTS.scope = via("sla_definitions", "sla_id")
EVENTS.scope = engagement_or_supplier
RESOURCES["performance_reviews"].scope = engagement_or_supplier
RESOURCES["review_scores"].scope = via("performance_reviews", "review_id")
EVENTS.before_save = _event
RESOURCES["performance_reviews"].before_save = _review
RESOURCES["review_scores"].before_save = _score


def scorecard(c):
    """Tedarikçinin son 12 aylık özeti: SLA başarı oranı, ağırlıklı değerlendirme puanı, olay sayıları."""
    authz.check(c.principal, RESOURCES["suppliers"], "read")
    sid = c.params["id"]
    crud.get(c.db, RESOURCES["suppliers"], sid)
    since = today(months=-12)
    sla = one(c.db, """SELECT COUNT(*) AS total, COALESCE(SUM(m.met), 0) AS met FROM tdr_sla_measurements m
        JOIN tdr_sla_definitions d ON d.id=m.sla_id JOIN tdr_engagements e ON e.id=d.engagement_id
        WHERE e.supplier_id=? AND m.period_start >= ?""", (sid, since))
    sla["rate"] = round(100 * sla["met"] / sla["total"], 1) if sla["total"] else None
    review = one(c.db, """SELECT SUM(s.score * k.weight) AS weighted, SUM(k.weight) AS weights,
        COUNT(DISTINCT r.id) AS reviews FROM tdr_review_scores s
        JOIN tdr_performance_reviews r ON r.id=s.review_id JOIN tdr_review_criteria k ON k.id=s.criterion_id
        WHERE r.supplier_id=? AND r.period_end >= ?""", (sid, since))
    weighted, weights = review.pop("weighted"), review.pop("weights")
    review["score"] = round(weighted / weights, 2) if weights else None
    events = rows(c.db, """SELECT event_type, COUNT(*) AS count FROM tdr_performance_events
        WHERE supplier_id=? AND occurred_at >= ? GROUP BY event_type""", (sid, since))
    return {"supplier_id": sid, "sla": sla, "review": review, "events": events}


def register(app):
    app.route("GET", API + "/suppliers/{id}/scorecard", scorecard)


def seed(db):
    for code, name, weight in (("QUALITY", "Hizmet ve Ürün Kalitesi", 3), ("DELIVERY", "Zamanında Teslim", 3),
                               ("COMMS", "İletişim ve Çözüm Hızı", 2), ("COMMERCIAL", "Ticari Uyum", 1),
                               ("COMPLIANCE", "Güvenlik ve Uyum", 2)):
        db.execute("INSERT INTO tdr_review_criteria (code, name, weight) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, name, weight))
