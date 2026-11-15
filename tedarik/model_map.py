"""İlişki haritasının yerleşimi. İlişkilerin kendisi şemadan türetilir (insights.model); burada yalnızca hangi kayıt
türünün hangi bantta ve sırada çizileceği durur. `tests/test_insights.py` buradaki adların şemada var olduğunu ve
temel ilişkilerin modelde göründüğünü denetler; böylece harita şemayla birlikte güncel kalır."""

GROUPS = [
    {"key": "context", "label": "Bağlam ve yönetişim", "hint": "Şirketler, birimler, süreçler, dokümanlar, standartlar"},
    {"key": "risk", "label": "Kurumsal risk (ISO 31000)", "hint": "Kriter, iştah, kayıt, değerlendirme, karar, işleme, KRİ"},
    {"key": "compliance", "label": "Uyum ve denetim", "hint": "Kontrol, test, kanıt, denetim, bulgu, DÖF"},
    {"key": "bcm", "label": "İş sürekliliği (ISO 22301)", "hint": "BİA, plan, adım, tatbikat"},
    {"key": "assets", "label": "Varlıklar (CMDB)", "hint": "CI ve CI risk maruziyetleri"},
    {"key": "supplier", "label": "Tedarikçi yönetimi", "hint": "Tedarikçi, angajman, sözleşme, SLA, anket"},
]

POSITIONS = {
    "companies": ("context", 0), "org_units": ("context", 1), "processes": ("context", 2), "documents": ("context", 3),
    "standards": ("context", 4), "clauses": ("context", 5), "objectives": ("context", 6),
    "risk_catalog": ("risk", 0), "risk_appetites": ("risk", 1), "supplier_risks": ("risk", 2),
    "risk_assessments": ("risk", 3), "risk_decisions": ("risk", 4), "risk_actions": ("risk", 5), "kris": ("risk", 6),
    "risk_cycles": ("risk", 7),
    "controls": ("compliance", 0), "executions": ("compliance", 1), "evidence": ("compliance", 2),
    "audits": ("compliance", 3), "findings": ("compliance", 4), "grc_actions": ("compliance", 5),
    "bias": ("bcm", 0), "bc_plans": ("bcm", 1), "bc_plan_steps": ("bcm", 2), "bc_exercises": ("bcm", 3),
    "cmdb_cis": ("assets", 0), "ci_exposures": ("assets", 1),
    "suppliers": ("supplier", 0), "engagements": ("supplier", 1), "contracts": ("supplier", 2),
    "catalog_items": ("supplier", 3), "sla_definitions": ("supplier", 4), "survey_campaigns": ("supplier", 5),
}
