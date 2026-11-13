"""Pano özeti: arayüzdeki kartların ve grafiklerin tek veri kaynağı. Kapalı modülün bölümü yanıtta yer almaz."""
from .. import auth as authz
from datetime import date

from ..db import one, rows, today
from ..http import API
from ..schema import RESOURCES
from .core import policy

M = "dashboard"


def _count(db, column, table):
    return rows(db, f"SELECT {column} AS key, COUNT(*) AS count FROM {table} GROUP BY {column} ORDER BY count DESC")


def summary(c):
    authz.check(c.principal, RESOURCES["suppliers"], "read")
    db, data = c.db, {}
    data["suppliers"] = {
        "total": one(db, "SELECT COUNT(*) AS n FROM tdr_suppliers")["n"],
        "by_status": _count(db, "status", "tdr_suppliers"),
        "by_tier": _count(db, "tier", "tdr_suppliers"),
        "by_type": rows(db, """SELECT t.name AS key, COUNT(m.supplier_id) AS count FROM tdr_supplier_types t
            LEFT JOIN tdr_supplier_type_map m ON m.type_id=t.id GROUP BY t.id ORDER BY count DESC"""),
        "without_owner": one(db, "SELECT COUNT(*) AS n FROM tdr_suppliers WHERE owner IS NULL "
                                 "AND status='active'")["n"],
    }
    data["engagements"] = {
        "by_beneficiary": _count(db, "beneficiary", "tdr_engagements"),
        "by_unit": rows(db, """SELECT u.name AS key, COUNT(e.id) AS count FROM tdr_org_units u
            JOIN tdr_engagements e ON e.org_unit_id=u.id GROUP BY u.id ORDER BY count DESC"""),
        "without_owner": one(db, "SELECT COUNT(*) AS n FROM tdr_engagements WHERE business_owner IS NULL "
                                 "AND status='active'")["n"],
    }
    data["contracts_ending_90d"] = one(db, """SELECT COUNT(*) AS n FROM tdr_contracts WHERE status='active'
        AND end_date BETWEEN ? AND ?""", (today(), today(days=90)))["n"]
    if c.app.enabled("performance"):
        sla = one(db, """SELECT COUNT(*) AS total, COALESCE(SUM(met), 0) AS met FROM tdr_sla_measurements
            WHERE period_start >= ?""", (today(months=-3),))
        sla["rate"] = round(100 * sla["met"] / sla["total"], 1) if sla["total"] else None
        data["sla_90d"] = sla
        data["events_90d"] = rows(db, """SELECT event_type AS key, COUNT(*) AS count FROM tdr_performance_events
            WHERE occurred_at >= ? GROUP BY event_type ORDER BY count DESC""", (today(months=-3),))
    if c.app.enabled("risks"):
        data["risks"] = {
            "open": one(db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks "
                            "WHERE status IN ('open','in_treatment')")["n"],
            "above_appetite": one(db, """SELECT COUNT(*) AS n FROM tdr_supplier_risks r
                JOIN tdr_risk_assessments a ON a.id=(SELECT MAX(x.id) FROM tdr_risk_assessments x WHERE x.risk_id=r.id)
                WHERE r.status IN ('open','in_treatment') AND a.residual > a.appetite""")["n"],
            "unassessed": one(db, """SELECT COUNT(*) AS n FROM tdr_supplier_risks r WHERE r.status='open'
                AND NOT EXISTS (SELECT 1 FROM tdr_risk_assessments a WHERE a.risk_id=r.id)""")["n"],
            "review_overdue": one(db, """SELECT COUNT(*) AS n FROM tdr_supplier_risks
                WHERE status IN ('open','in_treatment','accepted') AND review_date < ?""", (today(),))["n"],
        }
    if c.app.enabled("surveys"):
        data["surveys"] = one(db, """SELECT COUNT(*) AS invited, COALESCE(SUM(CASE WHEN status='answered' THEN 1 ELSE 0 END), 0) AS answered
            FROM tdr_survey_invitations""")
        data["surveys"]["open_campaigns"] = one(db, "SELECT COUNT(*) AS n FROM tdr_survey_campaigns "
                                                    "WHERE status='open'")["n"]
        data["surveys"]["submitted"] = one(db, "SELECT COUNT(*) AS n FROM tdr_survey_responses "
                                               "WHERE status='submitted'")["n"]
    return data


def _add_months(day, months):
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, 28))


def schedule(c):
    """Periyodik işler: kritiklik seviyesine göre değerlendirme ve anket takvimi, gözden geçirmesi geçen riskler.
    Sıklıklar `policies` tablosundadır (review.cadence_months, survey.cadence_months, schedule.warning_days)."""
    authz.check(c.principal, RESOURCES["suppliers"], "read")
    db, today_ = c.db, date.today()
    warn = int(policy(db, "schedule.warning_days", 30))
    kinds = []
    if c.app.enabled("performance"):
        kinds.append(("review", policy(db, "review.cadence_months", {}),
                      "SELECT MAX(period_end) AS last FROM tdr_performance_reviews WHERE supplier_id=?"))
    if c.app.enabled("surveys"):
        kinds.append(("survey", policy(db, "survey.cadence_months", {}),
                      "SELECT MAX(r.submitted_at) AS last FROM tdr_survey_responses r JOIN tdr_survey_targets t "
                      "ON t.id=r.target_id WHERE t.supplier_id=? AND r.status='submitted'"))
    items = []
    for supplier in rows(db, "SELECT id, code, name, tier, owner, created_at FROM tdr_suppliers WHERE status='active'"):
        for kind, cadence, sql in kinds:
            months = cadence.get(supplier["tier"]) if isinstance(cadence, dict) else None
            if not months:
                continue
            last = one(db, sql, (supplier["id"],))["last"]
            base = date.fromisoformat((last or supplier["created_at"])[:10])
            due = _add_months(base, int(months))
            days = (due - today_).days
            state = "overdue" if days < 0 else "due_soon" if days <= warn else "ok"
            if state == "ok" and c.query.get("all") != "1":
                continue
            items.append({"supplier_id": supplier["id"], "code": supplier["code"], "name": supplier["name"],
                          "tier": supplier["tier"], "owner": supplier["owner"], "kind": kind, "last": last[:10] if last else None,
                          "due": due.isoformat(), "days": days, "state": state, "never": last is None,
                          "cadence_months": int(months)})
    items.sort(key=lambda i: (i["days"], i["name"]))
    risks = rows(db, """SELECT id, code, title, supplier_id, owner, status, review_date FROM tdr_supplier_risks
        WHERE status IN ('open','in_treatment','accepted') AND review_date IS NOT NULL AND review_date <= ?
        ORDER BY review_date""", (today(days=warn),)) if c.app.enabled("risks") else []
    for risk in risks:
        risk["days"] = (date.fromisoformat(risk["review_date"]) - today_).days
        risk["state"] = "overdue" if risk["days"] < 0 else "due_soon"
    summary = {f"{k}_{s}": sum(1 for i in items if i["kind"] == k and i["state"] == s)
               for k in ("review", "survey") for s in ("overdue", "due_soon")}
    summary["risk_overdue"] = sum(1 for r in risks if r["state"] == "overdue")
    summary["risk_due_soon"] = sum(1 for r in risks if r["state"] == "due_soon")
    return {"items": items, "risks": risks, "summary": summary, "warning_days": warn}


def register(app):
    app.route("GET", API + "/dashboard/summary", summary)
    app.route("GET", API + "/schedule", schedule)
