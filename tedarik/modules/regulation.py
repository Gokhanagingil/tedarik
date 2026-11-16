"""Veri yönetişimi Faz 6 — KVKK ve GDPR boşluk analizi (K-033). `datagov` modülünün parçasıdır.

- Mevzuat metni standart kütüphanesindedir (`tedarik/data/standards/kvkk-6698.json.gz`, `gdpr-2016-679.json.gz`; resmî
  kaynaktan, kaynak adresi ve SHA-256 ile). Kurulu değilse boşluk analizi ekranı tek tıkla kurar.
- Her uygulanabilir madde için durum üç kaynaktan gelir:
  1. Platform göstergeleri: KVKK modülündeki kayıtlardan kural olarak hesaplanır (hukuki sebepsiz faaliyet, saklama süresiz
     kişisel veri, gecikmiş periyodik imha, mekanizmasız yurt dışı aktarım, aydınlatma metni, DPA'sız veri işleyen, düşük
     sınıflı kişisel veri, 72 saati aşan ihlal bildirimi, süresi geçen başvuru, envanter dışı kişisel veri, VKED, insan
     gözetimsiz otomatik karar). Her gösterge etkilenen kayıtları listeler (veri varlığına bağlantı).
  2. Maddeye eşlenen GRC kontrolleri ve son test sonuçları.
  3. Uyum sorumlusunun değerlendirmesi (durum, not, sorumlu, hedef tarih). Değerlendirme otomatik durumu geçersiz kılmaz;
     ikisi yan yana gösterilir.
- Açık maddeden tek tıkla bulgu açılır (madde bağlı, öz değerlendirme kaynaklı); DÖF GRC akışıyla yürür.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API
from ..schema import RESOURCES, Resource, fk
from .datagov import M

STANDARDS = {"KVKK": "kvkk-6698", "GDPR": "gdpr-2016-679"}
STATUSES = ("compliant", "partial", "non_compliant", "not_assessed", "not_applicable")
INDICATORS = {
    "KVKK": {"md. 4": ["retention"], "md. 5": ["legal_basis"], "md. 6": ["special"], "md. 7": ["retention", "disposal"],
             "md. 9": ["transfer"], "md. 10": ["notice"], "md. 11": ["subject_requests", "automated"],
             "md. 12": ["security", "processors", "breach"], "md. 13": ["subject_requests"], "md. 16": ["inventory"]},
    "GDPR": {"Art. 5": ["retention"], "Art. 6": ["legal_basis"], "Art. 9": ["special"], "Art. 12": ["subject_requests"],
             "Art. 13": ["notice"], "Art. 14": ["notice"], "Art. 15": ["subject_requests"], "Art. 17": ["retention", "disposal"],
             "Art. 16": ["subject_requests"], "Art. 18": ["subject_requests"], "Art. 20": ["subject_requests"],
             "Art. 21": ["subject_requests"], "Art. 22": ["automated"], "Art. 28": ["processors"], "Art. 30": ["inventory"],
             "Art. 32": ["security"], "Art. 33": ["breach"], "Art. 34": ["breach"], "Art. 35": ["dpia"],
             "Art. 44": ["transfer"], "Art. 45": ["transfer"], "Art. 46": ["transfer"], "Art. 49": ["transfer"]},
}
# KVKK ↔ GDPR madde eşlemesi (platformun önerisi; resmî eşleme değildir). İlişki kaynağı "crosswalk", türü kesişim.
CROSSWALK = (
    ("md. 3", "Art. 4", "Tanımlar"), ("md. 4", "Art. 5", "Genel ilkeler"), ("md. 5", "Art. 6", "İşleme şartları / hukuki sebep"),
    ("md. 6", "Art. 9", "Özel nitelikli kişisel veri"), ("md. 7", "Art. 17", "Silme, yok etme, anonim hâle getirme"),
    ("md. 8", "Art. 6", "Yurt içi aktarımda işleme şartları"), ("md. 9", "Art. 44", "Yurt dışı aktarımın genel ilkesi"),
    ("md. 9", "Art. 45", "Yeterlilik kararı"), ("md. 9", "Art. 46", "Uygun güvenceler (standart sözleşme, BCR)"),
    ("md. 9", "Art. 49", "Arızi aktarım istisnaları"), ("md. 10", "Art. 13", "Aydınlatma (veri ilgili kişiden alındığında)"),
    ("md. 10", "Art. 14", "Aydınlatma (veri başka kaynaktan alındığında)"), ("md. 11", "Art. 15", "Erişim hakkı"),
    ("md. 11", "Art. 16", "Düzeltme hakkı"), ("md. 11", "Art. 17", "Silme hakkı"), ("md. 11", "Art. 19", "Alıcılara bildirim"),
    ("md. 11", "Art. 21", "İtiraz hakkı"), ("md. 11", "Art. 22", "Otomatik karar"), ("md. 12", "Art. 28", "Veri işleyen"),
    ("md. 12", "Art. 32", "İşleme güvenliği"), ("md. 12", "Art. 33", "İhlalin otoriteye bildirimi"),
    ("md. 12", "Art. 34", "İhlalin ilgili kişiye bildirimi"), ("md. 13", "Art. 12", "Başvuru usulü ve süresi"),
    ("md. 14", "Art. 77", "Şikâyet hakkı"), ("md. 16", "Art. 30", "Sicil (VERBİS) / işleme kayıtları"),
    ("md. 18", "Art. 83", "İdari para cezaları"),
)

ASSESSMENTS = Resource("regulation_assessments", "Mevzuat Uyum Değerlendirmeleri", {
    "clause_id": fk("clauses"), "status": "TEXT NOT NULL", "note": "TEXT", "owner": "TEXT", "due_date": "DATE",
    "assessed_by": "TEXT", "assessed_at": "TIMESTAMP", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, api=("list", "get"), unique=(("clause_id",),), search=("note",), write_roles={"ADMIN", "SUPPLIER_MANAGER"},
    enums={"status": ("compliant", "partial", "non_compliant", "not_assessed")})


# ------------------------------------------------------------------ göstergeler

class Context:
    """Göstergelerin ortak verisi (bir istekte bir kez hesaplanır)."""

    def __init__(self, db):
        from .privacy import activity_categories, activity_gaps, disposal_state, dpia_required, linked_column_categories
        self.db = db
        self.activities = rows(db, "SELECT * FROM tdr_processing_activities WHERE status<>'retired' ORDER BY code")
        self.gaps, self.dpia_required = {}, 0
        for a in self.activities:
            cats = activity_categories(db, a["id"])
            self.gaps[a["id"]] = {g["key"]: g["text"] for g in activity_gaps(db, a, cats=cats)}
            self.dpia_required += 1 if dpia_required(a, list(cats) + linked_column_categories(db, a["id"])) else 0
        self.disposal = disposal_state(db)
        self.personal_tables = rows(db, """SELECT DISTINCT t.id, t.schema_name, t.name, t.retention_rule_id, s.name AS source_name
            FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id JOIN tdr_data_columns c ON c.table_id=t.id
            WHERE t.status<>'removed' AND c.status='active' AND c.personal_data IN ('personal','special') ORDER BY s.name, t.name""")

    def by_gap(self, *keys):
        out = []
        for a in self.activities:
            for k in keys:
                if k in self.gaps[a["id"]]:
                    out.append({"label": f"{a['code']} {a['name']}", "detail": self.gaps[a["id"]][k], "link": f"#/activity/{a['id']}"})
                    break
        return out


def _table_item(t, detail):
    name = f"{t['schema_name']}.{t['name']}" if t["schema_name"] else t["name"]
    return {"label": f"{t['source_name']} / {name}", "detail": detail, "link": f"#/catalog/table/{t['id']}"}


def ind_legal_basis(ctx):
    return len(ctx.activities), ctx.by_gap("legal_basis", "balance_test")


def ind_special(ctx):
    return len(ctx.activities), ctx.by_gap("special_basis")


def ind_retention(ctx):
    items = ctx.by_gap("retention")
    items += [_table_item(t, "Kişisel veri içeren tabloya saklama ve imha kuralı bağlanmamış") for t in ctx.personal_tables
              if not t["retention_rule_id"]]
    return len(ctx.activities) + len(ctx.personal_tables), items


def ind_disposal(ctx):
    st = ctx.disposal
    if not st["tables_in_scope"]:
        return 0, []
    if st["overdue"]:
        return 1, [{"label": "Periyodik imha gecikti", "detail": f"Son gün {st['next_due']}", "link": "#/r/disposal_runs"}]
    if st["unplanned"]:
        return 1, [{"label": "Periyodik imha hiç planlanmamış", "detail": f"{st['tables_in_scope']} tablo kapsamda",
                    "link": "#/r/disposal_runs"}]
    return 1, []


def ind_transfer(ctx):
    return sum(1 for a in ctx.activities if a["foreign_transfer"]), ctx.by_gap("transfer", "transfer_notice", "transfer_late")


def ind_notice(ctx):
    return len(ctx.activities), ctx.by_gap("notice")


def ind_processors(ctx):
    data = rows(ctx.db, """SELECT p.dpa_signed, s.id AS supplier_id, s.name AS supplier, a.id AS activity_id, a.code
        FROM tdr_processing_processors p JOIN tdr_suppliers s ON s.id=p.supplier_id JOIN tdr_processing_activities a
        ON a.id=p.activity_id WHERE p.role='processor' AND a.status<>'retired'""")
    return len(data), [{"label": f"{d['supplier']} ({d['code']})", "detail": "Veri işleme sözleşmesi (DPA) imzalı değil",
                        "link": f"#/activity/{d['activity_id']}"} for d in data if not d["dpa_signed"]]


def ind_security(ctx):
    low = rows(ctx.db, """SELECT c.id, c.name, t.id AS table_id, t.schema_name, t.name AS table_name, s.name AS source_name
        FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources s ON s.id=t.source_id
        WHERE c.status='active' AND t.status<>'removed' AND c.personal_data IN ('personal','special')
        AND COALESCE(c.classification, t.classification, 'public') IN ('public','internal') ORDER BY s.name, t.name, c.name LIMIT 200""")
    personal = one(ctx.db, """SELECT COUNT(*) AS n FROM tdr_data_columns WHERE status='active'
        AND personal_data IN ('personal','special')""")["n"]
    items = [{"label": f"{r['source_name']} / {r['table_name']}.{r['name']}", "detail": "Kişisel veri 'Gizli' sınıfının altında",
              "link": f"#/catalog/table/{r['table_id']}"} for r in low]
    return personal + len(ctx.activities), items + ctx.by_gap("measures")


def ind_breach(ctx):
    now = datetime.now(timezone.utc)
    data = rows(ctx.db, "SELECT id, code, title, detected_at, authority_notified_at, notify_decision, delay_reason, status "
                        "FROM tdr_privacy_breaches")
    items = []
    for b in data:
        detected = datetime.fromisoformat(str(b["detected_at"]).replace("Z", "+00:00"))
        if detected.tzinfo is None:
            detected = detected.replace(tzinfo=timezone.utc)
        deadline = detected + timedelta(hours=72)
        if b["authority_notified_at"]:
            sent = datetime.fromisoformat(str(b["authority_notified_at"]).replace("Z", "+00:00"))
            if sent.tzinfo is None:
                sent = sent.replace(tzinfo=timezone.utc)
            if sent > deadline and not b["delay_reason"]:
                items.append({"label": f"{b['code']} {b['title']}", "detail": "Kurula 72 saatten sonra bildirilmiş; gecikme gerekçesi yok",
                              "link": f"#/r/privacy_breaches/{b['id']}"})
        elif b["notify_decision"] in ("pending", "notify") and now > deadline and b["status"] != "closed":
            items.append({"label": f"{b['code']} {b['title']}", "detail": "72 saat doldu; Kurula bildirim yapılmamış veya karar verilmemiş",
                          "link": f"#/r/privacy_breaches/{b['id']}"})
    return len(data), items


def ind_subject_requests(ctx):
    data = rows(ctx.db, "SELECT id, code, request_type, due_date, response_date, status FROM tdr_subject_requests")
    today = datetime.now(timezone.utc).date().isoformat()
    items = []
    for r in data:
        due = str(r["due_date"])[:10] if r["due_date"] else None
        if not due:
            continue
        if r["status"] in ("received", "in_progress") and due < today:
            items.append({"label": r["code"], "detail": f"Yanıt süresi {due} tarihinde doldu", "link": f"#/r/subject_requests/{r['id']}"})
        elif r["response_date"] and str(r["response_date"])[:10] > due:
            items.append({"label": r["code"], "detail": f"Süre sonundan sonra yanıtlanmış ({str(r['response_date'])[:10]})",
                          "link": f"#/r/subject_requests/{r['id']}"})
    return len(data), items


def ind_inventory(ctx):
    linked = {r["table_id"] for r in rows(ctx.db, """SELECT table_id FROM tdr_processing_tables UNION
        SELECT c.table_id FROM tdr_processing_columns pc JOIN tdr_data_columns c ON c.id=pc.column_id""")}
    items = [_table_item(t, "Kişisel veri içeriyor, hiçbir işleme faaliyetine (VERBİS) bağlı değil") for t in ctx.personal_tables
             if t["id"] not in linked]
    return len(ctx.personal_tables) + len(ctx.activities), items + ctx.by_gap("categories", "subjects", "categories_mismatch")


def ind_dpia(ctx):
    return ctx.dpia_required, ctx.by_gap("dpia")


def ind_automated(ctx):
    if "ai_systems" not in RESOURCES:
        return 0, []
    data = rows(ctx.db, "SELECT id, code, name, human_oversight FROM tdr_ai_systems WHERE automated_decision=1 AND lifecycle<>'retired'")
    return len(data), [{"label": f"{a['code']} {a['name']}", "detail": "Kişi hakkında otomatik karar; insan gözetimi ve itiraz yolu tanımlı değil",
                        "link": f"#/aisystem/{a['id']}"} for a in data if not (a["human_oversight"] or "").strip()]


DEFINITIONS = {   # anahtar: (başlık, önem, hesap)
    "legal_basis": ("Hukuki sebebi olmayan işleme faaliyetleri", "high", ind_legal_basis),
    "special": ("Özel nitelikli veride md. 6 / Art. 9 dayanağı eksik", "high", ind_special),
    "retention": ("Saklama süresi belirlenmemiş faaliyet ve kişisel veri tabloları", "high", ind_retention),
    "disposal": ("Periyodik imha", "high", ind_disposal),
    "transfer": ("Yurt dışı aktarım mekanizması ve bildirim", "high", ind_transfer),
    "notice": ("Aydınlatma metni bağlanmamış faaliyetler", "medium", ind_notice),
    "processors": ("Veri işleme sözleşmesi olmayan veri işleyenler", "medium", ind_processors),
    "security": ("Kişisel verinin sınıfı ve teknik/idari tedbirler", "high", ind_security),
    "breach": ("Kişisel veri ihlali 72 saat bildirimi", "high", ind_breach),
    "subject_requests": ("İlgili kişi başvurularının süresi", "high", ind_subject_requests),
    "inventory": ("Envanter (VERBİS / işleme kayıtları) kapsamı", "medium", ind_inventory),
    "dpia": ("Veri koruma etki değerlendirmesi", "medium", ind_dpia),
    "automated": ("Otomatik karar ve insan gözetimi (yapay zekâ)", "high", ind_automated),
}


def indicators_for(ctx, keys, cache):
    out = []
    for key in keys:
        if key not in cache:
            title, severity, fn = DEFINITIONS[key]
            population, items = fn(ctx)
            cache[key] = {"key": key, "title": title, "severity": severity, "population": population, "gaps": len(items),
                          "items": items[:25]}
        out.append(cache[key])
    return out


def auto_status(applicable, indicators, controls):
    if not applicable:
        return "not_applicable"
    gaps = [i for i in indicators if i["gaps"]]
    if any(i["severity"] == "high" for i in gaps):
        return "non_compliant"
    if gaps:
        return "partial"
    if controls:
        results = [k["last_status"] for k in controls]
        if "fail" in results:
            return "non_compliant"
        if results and all(r == "pass" for r in results):
            return "compliant"
        return "partial"
    if indicators and all(i["population"] for i in indicators):
        return "compliant"
    return "not_assessed"


# ------------------------------------------------------------------ uç noktalar

def _standard(db, code):
    return one(db, "SELECT * FROM tdr_standards WHERE code=? ORDER BY id DESC LIMIT 1", (code,))


def analysis(db, code):
    std = _standard(db, code)
    if std is None:
        return None
    clauses = rows(db, "SELECT * FROM tdr_clauses WHERE standard_id=? ORDER BY position, id", (std["id"],))
    ids = [c["id"] for c in clauses]
    controls = {}
    if ids:
        for r in rows(db, f"""SELECT m.clause_id, k.id, k.code, k.name, k.owner,
                (SELECT e.status FROM tdr_executions e WHERE e.control_id=k.id ORDER BY e.executed_at DESC, e.id DESC LIMIT 1) AS last_status
                FROM tdr_control_clauses m JOIN tdr_controls k ON k.id=m.control_id WHERE k.active=1
                AND m.clause_id IN ({','.join('?' * len(ids))})""", ids):
            controls.setdefault(r["clause_id"], []).append(r)
    assessments = {a["clause_id"]: a for a in rows(db, "SELECT * FROM tdr_regulation_assessments WHERE clause_id IN "
                                                       "(SELECT id FROM tdr_clauses WHERE standard_id=?)", (std["id"],))}
    findings = Counter(r["clause_id"] for r in rows(db, """SELECT clause_id FROM tdr_findings WHERE status IN ('open','in_progress')
        AND clause_id IN (SELECT id FROM tdr_clauses WHERE standard_id=?)""", (std["id"],)))
    ctx, cache = Context(db), {}
    chapters = {c["id"]: c for c in clauses if c["clause_type"] == "category"}
    out = []
    for c in clauses:
        if c["clause_type"] != "article":
            continue
        inds = indicators_for(ctx, INDICATORS.get(code, {}).get(c["code"], []), cache)
        ctrls = controls.get(c["id"], [])
        auto = auto_status(c["applicable"], inds, ctrls)
        a = assessments.get(c["id"])
        out.append({"id": c["id"], "code": c["code"], "title": c["title"], "text": c["description"], "applicable": c["applicable"],
                    "justification": c["justification"], "chapter": (chapters.get(c["parent_id"]) or {}).get("title"),
                    "indicators": inds, "controls": ctrls, "auto_status": auto, "assessment": a,
                    "status": "not_applicable" if not c["applicable"] else (a["status"] if a else auto),
                    "open_findings": findings.get(c["id"], 0)})
    applicable = [x for x in out if x["applicable"]]
    counts = Counter(x["status"] for x in applicable)
    evaluated = sum(counts[s] for s in ("compliant", "partial", "non_compliant"))
    score = round(100 * (counts["compliant"] + 0.5 * counts["partial"]) / evaluated, 1) if evaluated else None
    return {"standard": {k: std[k] for k in ("id", "code", "name", "version", "language", "source_url", "source_sha256",
                                             "published", "active")},
            "articles": out, "counts": dict(counts), "applicable": len(applicable), "score": score,
            "indicators": list(cache.values())}


def _human(principal):
    return principal.auth_type not in ("api_key", "collector")


def crosswalk_state(db):
    kvkk, gdpr = _standard(db, "KVKK"), _standard(db, "GDPR")
    if not kvkk or not gdpr:
        return None
    present = one(db, """SELECT COUNT(*) AS n FROM tdr_clause_links l JOIN tdr_clauses a ON a.id=l.from_clause_id
        JOIN tdr_clauses b ON b.id=l.to_clause_id WHERE l.active=1 AND ((a.standard_id=? AND b.standard_id=?)
        OR (a.standard_id=? AND b.standard_id=?))""", (kvkk["id"], gdpr["id"], gdpr["id"], kvkk["id"]))["n"]
    return {"links": present, "available": len(CROSSWALK)}


def gap_analysis(c):
    authz.check(c.principal, RESOURCES["clauses"], "read")
    code = c.query.get("code") or "KVKK"
    if code not in STANDARDS:
        raise crud.Invalid("Mevzuat KVKK veya GDPR olmalı")
    result = analysis(c.db, code)
    library = _human(c.principal) and authz.can_write(c.principal, RESOURCES["standards"])
    if result is None:
        return {"installed": False, "code": code, "library_key": STANDARDS[code], "can_install": library}
    return {"installed": True, "code": code, **result, "crosswalk": crosswalk_state(c.db), "can_library": library,
            "can_edit": _human(c.principal) and authz.can_write(c.principal, ASSESSMENTS),
            "can_finding": _human(c.principal) and authz.can_write(c.principal, RESOURCES["findings"])}


def apply_crosswalk(db, principal):
    """KVKK–GDPR madde eşlemesini kurar (iki mevzuat da kurulu olmalı). Var olan ilişkiye dokunmaz. Dönüş: eklenen sayısı."""
    kvkk, gdpr = _standard(db, "KVKK"), _standard(db, "GDPR")
    if not kvkk or not gdpr:
        raise crud.Conflict("Önce KVKK ve GDPR metinlerini kütüphaneden kurun")
    ids = {(r["standard_id"], r["code"]): r["id"] for r in rows(
        db, "SELECT id, standard_id, code FROM tdr_clauses WHERE standard_id IN (?,?)", (kvkk["id"], gdpr["id"]))}
    now, added = utcnow(), 0
    for k, g, rationale in CROSSWALK:
        a, b = ids.get((kvkk["id"], k)), ids.get((gdpr["id"], g))
        if not a or not b or one(db, """SELECT 1 AS x FROM tdr_clause_links WHERE (from_clause_id=? AND to_clause_id=?)
                OR (from_clause_id=? AND to_clause_id=?)""", (a, b, b, a)):
            continue
        db.execute("""INSERT INTO tdr_clause_links (from_clause_id, to_clause_id, relation, source, rationale, active,
            created_by, created_at) VALUES (?,?,'intersects','crosswalk',?,1,?,?)""",
                   (a, b, f"{rationale} (platform eşlemesi; resmî değildir)", principal.username, now))
        added += 1
    audit.log(db, principal, "CROSSWALK", "standards", kvkk["id"], {"to": "GDPR", "added": added})
    return added


def install_crosswalk(c):
    authz.require_human(c.principal)
    authz.check(c.principal, RESOURCES["clause_links"], "write")
    added = apply_crosswalk(c.db, c.principal)
    return {"added": added, **crosswalk_state(c.db)}


def _clause(db, clause_id):
    cl = one(db, """SELECT cl.*, s.code AS standard_code FROM tdr_clauses cl JOIN tdr_standards s ON s.id=cl.standard_id
        WHERE cl.id=?""", (clause_id,))
    if not cl or cl["standard_code"] not in STANDARDS:
        raise crud.NotFound("Mevzuat maddesi bulunamadı")
    return cl


def assess(c):
    authz.require_human(c.principal)
    authz.check(c.principal, ASSESSMENTS, "write")
    cl = _clause(c.db, int(c.body.get("clause_id") or 0))
    status = c.body.get("status")
    if status not in ASSESSMENTS.enums["status"]:
        raise crud.Invalid("Durum: uyumlu, kısmen, uyumsuz veya değerlendirilmedi")
    note = str(c.body.get("note") or "").strip()
    if status in ("partial", "non_compliant") and len(note) < 5:
        raise crud.Invalid("Kısmen veya uyumsuz değerlendirmede açığı not olarak yazın")
    due = c.body.get("due_date") or None
    if due:
        due = crud.normalize("due_date", ASSESSMENTS.columns["due_date"], due)
    now = utcnow()
    values = {"status": status, "note": note or None, "owner": (c.body.get("owner") or "").strip() or None, "due_date": due,
              "assessed_by": c.principal.username, "assessed_at": now}
    cur = one(c.db, "SELECT id FROM tdr_regulation_assessments WHERE clause_id=?", (cl["id"],))
    if cur:
        c.db.execute(f"UPDATE tdr_regulation_assessments SET {', '.join(f'{k}=?' for k in values)}, updated_at=? WHERE id=?",
                     (*values.values(), now, cur["id"]))
    else:
        c.db.execute(f"INSERT INTO tdr_regulation_assessments (clause_id, {', '.join(values)}, created_at) VALUES "
                     f"(?, {', '.join('?' * len(values))}, ?)", (cl["id"], *values.values(), now))
    audit.log(c.db, c.principal, "ASSESS", "clauses", cl["id"], {"standard": cl["standard_code"], "code": cl["code"], **values})
    return {"ok": True}


def raise_finding(c):
    """Açık maddeden bulgu (öz değerlendirme kaynaklı); sorumlu ve hedef tarih varsa DÖF de açılır."""
    authz.require_human(c.principal)
    findings, actions = RESOURCES["findings"], RESOURCES["grc_actions"]
    authz.check(c.principal, findings, "write")
    cl = _clause(c.db, int(c.body.get("clause_id") or 0))
    a = one(c.db, "SELECT * FROM tdr_regulation_assessments WHERE clause_id=?", (cl["id"],)) or {}
    description = str(c.body.get("description") or a.get("note") or "").strip()
    if len(description) < 10:
        raise crud.Invalid("Açığı açıklayın (en az 10 karakter)")
    severity = c.body.get("severity") or ("high" if a.get("status") == "non_compliant" else "medium")
    owner = (c.body.get("owner") or a.get("owner") or "").strip() or None
    due = c.body.get("due_date") or (str(a["due_date"])[:10] if a.get("due_date") else None)
    title = f"{cl['standard_code']} {cl['code']} {cl['title']}: uyum açığı"[:300]
    fid = crud.insert(c.db, findings, {"title": title, "clause_id": cl["id"], "source": "self_assessment", "severity": severity,
                                       "description": description, "owner": owner, "due_date": due}, c.principal)
    audit.log(c.db, c.principal, "CREATE", "findings", fid, {"clause": f"{cl['standard_code']} {cl['code']}", "severity": severity})
    action_id = None
    if owner and due and authz.can_write(c.principal, actions):
        action_id = crud.insert(c.db, actions, {"title": f"Uyum açığını gider: {cl['standard_code']} {cl['code']}"[:300],
                                                "finding_id": fid, "description": description, "owner": owner,
                                                "due_date": due, "priority": severity}, c.principal)
        audit.log(c.db, c.principal, "CREATE", "grc_actions", action_id, {"finding_id": fid})
    return 201, {"finding_id": fid, "code": crud.get(c.db, findings, fid)["code"], "action_id": action_id}


def overview_cards(db):
    """KVKK panosu için: kurulu mevzuatın skoru ve açık madde sayısı."""
    out = []
    for code in STANDARDS:
        result = analysis(db, code)
        if result:
            out.append({"code": code, "score": result["score"], "non_compliant": result["counts"].get("non_compliant", 0),
                        "partial": result["counts"].get("partial", 0), "applicable": result["applicable"]})
    return out


def register(app):
    app.route("GET", API + "/datagov/regulation", gap_analysis)
    app.route("POST", API + "/datagov/regulation/assess", assess)
    app.route("POST", API + "/datagov/regulation/finding", raise_finding)
    app.route("POST", API + "/datagov/regulation/crosswalk", install_crosswalk)
