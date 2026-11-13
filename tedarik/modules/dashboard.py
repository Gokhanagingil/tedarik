"""Pano özeti: arayüzdeki kartların ve grafiklerin tek veri kaynağı. Kapalı modülün bölümü yanıtta yer almaz."""
from .. import auth as authz
from ..db import one, rows, today
from ..http import API
from ..schema import RESOURCES

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


def register(app):
    app.route("GET", API + "/dashboard/summary", summary)
