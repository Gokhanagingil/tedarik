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

Tek risk kaydı (K-015): kurumsal ve tedarikçi riskleri aynı kayıttadır; tedarikçi ve angajman bağı isteğe
bağlıdır. Tablo ve uç nokta adı (`supplier_risks`) MCP sözleşmesi bozulmasın diye korunur. Risk kataloğu
(KS GRC `risk_catalog`) yeniden kullanılabilir senaryolardır; katalogdan açılan risk `catalog_id` taşır.
Azaltıcı önlem bir GRC kontrolüne dayanıyorsa `control_ref` alanına kontrol kodu yazılır; grc modülü açıksa
riskin bağlı kontrolleri ve son test sonuçları risk bağlamında görünür.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, guard_readonly
from ..schema import Resource, fk
from .core import default_company, engagement_or_supplier, policy, via

M = "risks"
WEIGHTS = {"low": Decimal("0.2"), "medium": Decimal("0.4"), "high": Decimal("0.6")}
TERMINAL = ("accepted", "closed")
DECISION_INPUT = {"assessment_id", "decision_rationale", "exception_rationale"}
STATEMENT = ("owner", "cause", "risk_event", "consequence")
SNAPSHOT = ("code", "title", "supplier_id", "engagement_id", "entity_name", "company_id", "process_id", "owner", "cause", "risk_event", "consequence",
            "likelihood", "impact", "review_date", "response_strategy", "treatment")
COMPARED = ("supplier_id", "engagement_id", "cause", "risk_event", "consequence", "likelihood", "impact", "owner",
            "company_id")
CATEGORIES = ("strategic", "operational", "financial", "compliance", "legal", "technology", "security", "privacy",
              "continuity", "supplier", "concentration", "performance", "exit", "people", "reputation")
IMPACT_AREAS = ("financial", "operational", "customer", "reputational", "legal", "information", "people")
LEVELS = {"low": 4, "medium": 9, "high": 15, "critical": 25}        # varsayılan üst sınırlar; politika değiştirir
TEXT_LIMIT = 5000

CATALOG = Resource("risk_catalog", "Risk Kataloğu", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "category": "TEXT NOT NULL",
    "cause": "TEXT NOT NULL", "risk_event": "TEXT NOT NULL", "consequence": "TEXT NOT NULL",
    "likelihood": "INTEGER NOT NULL DEFAULT 3", "impact": "INTEGER NOT NULL DEFAULT 3", "description": "TEXT",
    "active": "INTEGER NOT NULL DEFAULT 1", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="manage", search=("code", "title"), code_prefix="RKT",
    enums={"category": CATEGORIES})

RISKS = Resource("supplier_risks", "Risk Kaydı", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "supplier_id": fk("suppliers", False),
    "engagement_id": fk("engagements", False), "category": "TEXT NOT NULL", "description": "TEXT",
    "cause": "TEXT", "risk_event": "TEXT", "consequence": "TEXT",
    "likelihood": "INTEGER NOT NULL DEFAULT 3", "impact": "INTEGER NOT NULL DEFAULT 3",
    "owner": "TEXT NOT NULL", "appetite": "INTEGER NOT NULL DEFAULT 9", "status": "TEXT NOT NULL DEFAULT 'open'",
    "response_strategy": "TEXT", "treatment": "TEXT", "review_date": "DATE", "control_risk_ref": "TEXT",
    "origin_ref": "TEXT", "catalog_id": fk("risk_catalog", False), "entity_name": "TEXT",
    "company_id": fk("companies", False), "org_unit_id": fk("org_units", False), "process_id": fk("processes", False),
    "risk_type": "TEXT NOT NULL DEFAULT 'threat'", "source": "TEXT NOT NULL DEFAULT 'manual'", "impact_area": "TEXT",
    "target_likelihood": "INTEGER", "target_impact": "INTEGER", "consulted": "TEXT",
    "inherent_score": "INTEGER", "residual_score": "REAL", "risk_level": "TEXT", "last_assessed_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="write", api=("list", "get", "create"), search=("code", "title"), machine="r", code_prefix="RSK",
    readonly=("origin_ref", "source", "inherent_score", "residual_score", "risk_level", "last_assessed_at"),
    indexes=(("company_id", "status"),),
    enums={"category": CATEGORIES, "status": ("open", "in_treatment", "accepted", "closed"),
           "response_strategy": ("mitigate", "avoid", "transfer", "accept", "exploit"),
           "risk_type": ("threat", "opportunity"), "impact_area": IMPACT_AREAS,
           "source": ("manual", "supplier", "survey", "cmdb_rule", "audit", "bia"),
           "risk_level": tuple(LEVELS)})

ASSESSMENTS = Resource("risk_assessments", "Risk Değerlendirmeleri", {
    "risk_id": fk("supplier_risks"), "assessed_at": "TIMESTAMP NOT NULL", "assessor": "TEXT NOT NULL",
    "rationale": "TEXT NOT NULL", "inherent": "INTEGER NOT NULL", "mitigation_pct": "REAL NOT NULL",
    "residual": "REAL NOT NULL", "appetite": "INTEGER NOT NULL", "snapshot": "TEXT NOT NULL",
    "cycle_id": fk("risk_cycles", False)},
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
    module=M, write="write", search=("code", "title"), readonly=("closed_at",), code_prefix="RIF",
    enums={"priority": ("low", "medium", "high", "critical"),
           "status": ("open", "in_progress", "validation", "completed", "cancelled")})

CRITERIA = Resource("risk_criteria", "Risk Kriterleri", {
    "dimension": "TEXT NOT NULL", "level": "INTEGER NOT NULL", "label": "TEXT NOT NULL", "description": "TEXT",
    "frequency": "TEXT", "financial": "TEXT", "operational": "TEXT", "reputational": "TEXT", "legal": "TEXT"},
    module=M, write="admin", unique=(("dimension", "level"),), search=("label", "description"),
    enums={"dimension": ("likelihood", "impact")})         # ISO 31000 6.3.4: risk kriterleri

APPETITES = Resource("risk_appetites", "Risk İştahı", {
    "code": "TEXT NOT NULL UNIQUE", "category": "TEXT NOT NULL UNIQUE", "appetite": "INTEGER NOT NULL",
    "tolerance": "INTEGER NOT NULL", "statement": "TEXT NOT NULL", "approved_by": "TEXT", "approved_on": "DATE",
    "review_date": "DATE", "active": "INTEGER NOT NULL DEFAULT 1"},
    module=M, write="admin", code_prefix="RIS", search=("code", "statement"), enums={"category": CATEGORIES})

CYCLES = Resource("risk_cycles", "Risk Değerlendirme Dönemleri", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "company_id": fk("companies", False),
    "period_start": "DATE NOT NULL", "period_end": "DATE NOT NULL", "status": "TEXT NOT NULL DEFAULT 'planned'",
    "owner": "TEXT", "scope": "TEXT", "description": "TEXT", "created_at": "TIMESTAMP NOT NULL"},
    module=M, write="manage", code_prefix="RDD", code_yearly=True, search=("code", "name"),
    enums={"status": ("planned", "open", "closed")})

KRIS = Resource("kris", "Anahtar Risk Göstergeleri", {
    "code": "TEXT NOT NULL UNIQUE", "risk_id": fk("supplier_risks"), "name": "TEXT NOT NULL", "unit": "TEXT",
    "direction": "TEXT NOT NULL DEFAULT 'higher_worse'", "threshold_amber": "REAL NOT NULL",
    "threshold_red": "REAL NOT NULL", "frequency": "TEXT NOT NULL DEFAULT 'monthly'", "owner": "TEXT",
    "description": "TEXT", "last_value": "REAL", "last_status": "TEXT", "last_measured_at": "DATE",
    "active": "INTEGER NOT NULL DEFAULT 1"},
    module=M, write="write", code_prefix="KRI", search=("code", "name"), machine="r",
    readonly=("last_value", "last_status", "last_measured_at"),
    enums={"direction": ("higher_worse", "lower_worse"), "frequency": ("weekly", "monthly", "quarterly"),
           "last_status": ("green", "amber", "red")})

KRI_VALUES = Resource("kri_values", "KRİ Ölçümleri", {
    "kri_id": fk("kris"), "period": "DATE NOT NULL", "value": "REAL NOT NULL", "status": "TEXT NOT NULL",
    "note": "TEXT", "source": "TEXT NOT NULL DEFAULT 'manual'", "recorded_by": "TEXT NOT NULL",
    "recorded_at": "TIMESTAMP NOT NULL"},
    module=M, write="write", api=("list", "get", "create"), search=(), machine="rw", immutable=True,
    unique=(("kri_id", "period"),), readonly=("status", "recorded_by", "recorded_at"),
    enums={"status": ("green", "amber", "red"), "source": ("manual", "mcp")})


def _text(value, message):
    if not isinstance(value, str) or not value.strip() or len(value) > TEXT_LIMIT:
        raise crud.Invalid(message)
    return value.strip()


def _ensure_statement(risk):
    if any(not isinstance(risk.get(k), str) or not risk[k].strip() for k in STATEMENT):
        raise crud.Invalid("Risk sahibi, neden, olay ve etki gerekli")


def level_of(db, score):
    """Puanın risk seviyesi (ISO 31000 risk kriterleri; eşikler `risk.levels` politikasında)."""
    if score is None:
        return None
    bounds = policy(db, "risk.levels", LEVELS)
    for name in ("low", "medium", "high", "critical"):
        if score <= bounds.get(name, LEVELS[name]):
            return name
    return "critical"


def _risk_fields(db, data, current, principal):
    merged = {**(current or {}), **data}
    if not merged.get("company_id"):
        company = default_company(db)
        if company is None:
            raise crud.Invalid("Şirket seçin (riskin ait olduğu kendi şirketimiz veya müşteri)")
        data["company_id"] = merged["company_id"] = company
    if current is None and merged.get("appetite") is None:
        row = one(db, "SELECT appetite FROM tdr_risk_appetites WHERE category=? AND active=1", (merged.get("category"),))
        data["appetite"] = merged["appetite"] = row["appetite"] if row else int(policy(db, "risk.default_appetite", 9))
    for field in ("target_likelihood", "target_impact"):
        value = merged.get(field)
        if value is not None and (type(value) is not int or not 1 <= value <= 5):
            raise crud.Invalid("Hedef olasılık ve etki 1–5 arasında olmalı")
    if merged.get("target_likelihood") and merged.get("target_impact") and \
            merged["target_likelihood"] * merged["target_impact"] > merged.get("likelihood", 3) * merged.get("impact", 3):
        raise crud.Invalid("Hedef risk, içsel riskten yüksek olamaz")
    if merged.get("response_strategy") == "exploit" and merged.get("risk_type") != "opportunity":
        raise crud.Invalid("'Fırsatı değerlendir' yanıtı yalnızca fırsat türündeki risklerde seçilir")
    if current is None:
        data["source"] = ("survey" if merged.get("origin_ref", "") and str(merged["origin_ref"]).startswith("survey")
                          else "cmdb_rule" if str(merged.get("origin_ref") or "").startswith("cmdb:")
                          else "supplier" if merged.get("supplier_id") else "manual")
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
    if merged.get("engagement_id") and not merged.get("supplier_id"):
        engagement = one(db, "SELECT supplier_id FROM tdr_engagements WHERE id=?", (merged["engagement_id"],))
        if engagement:
            data["supplier_id"] = engagement["supplier_id"]
    if not merged.get("supplier_id") and not (merged.get("entity_name") or "").strip():
        raise crud.Invalid("Tedarikçi seçin ya da etkilenen varlık / hizmeti yazın")
    if current is None:
        if merged.get("status", "open") in TERMINAL:
            raise crud.Invalid("Kabul veya kapanış için kayıtlı değerlendirme ve karar gerekli")
        if any(merged.get(k) for k in ("cause", "risk_event", "consequence")):
            _ensure_statement(merged)


def _risk_scores(db, data, current, principal):
    _risk_fields(db, data, current, principal)
    merged = {**(current or {}), **data}
    data["inherent_score"] = merged.get("likelihood", 3) * merged.get("impact", 3)
    residual = merged.get("residual_score")
    data["risk_level"] = level_of(db, residual if residual is not None else data["inherent_score"])


RISKS.before_save = _risk_scores


def latest(db, risk_id):
    """En son tarihli değerlendirme (aynı anda yazılanlarda son kayıt)."""
    return one(db, "SELECT * FROM tdr_risk_assessments WHERE risk_id=? ORDER BY assessed_at DESC, id DESC LIMIT 1",
               (risk_id,))


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
        if any(k in snapshot and proposal.get(k) != snapshot.get(k) for k in COMPARED) \
                or last["appetite"] != proposal.get("appetite"):      # eski anlık görüntüde olmayan alan karşılaştırılmaz
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
    _risk_scores(c.db, cleaned, current, c.principal)
    decision_id = decide(c.db, current, {**current, **cleaned}, details, c.principal)
    record = crud.update(c.db, RISKS, current["id"], {**body, **{k: cleaned[k] for k in
                                                         ("company_id", "inherent_score", "risk_level") if k in cleaned}},
                         c.principal)
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
    record_id = record_assessment(c.db, risk, c.principal.username, rationale, total, credits, utcnow())
    audit.log(c.db, c.principal, "ASSESS", RISKS.name, risk["id"], {"inherent": inherent, "residual": residual})
    return 201, {"id": record_id, "inherent": inherent, "residual": residual,
                 "above_appetite": residual > risk["appetite"]}


def record_assessment(db, risk, assessor, rationale, total, credits, assessed_at):
    """Değerlendirmeyi yazar (değiştirilemez), açık değerlendirme dönemine bağlar, riskin özet puanlarını günceller."""
    inherent = risk["likelihood"] * risk["impact"]
    residual = float(inherent * (1 - total))
    snapshot = {k: risk.get(k) for k in SNAPSHOT}
    snapshot.update({"method": "weighted-v1", "mitigations": credits})
    day = str(assessed_at)[:10]
    cycle = one(db, "SELECT id FROM tdr_risk_cycles WHERE status='open' AND period_start<=? AND period_end>=? AND "
                    "(company_id IS NULL OR company_id=?) ORDER BY company_id DESC, id DESC LIMIT 1",
                (day, day, risk.get("company_id")))
    record_id = db.execute(
        "INSERT INTO tdr_risk_assessments (risk_id, assessed_at, assessor, rationale, inherent, mitigation_pct, "
        "residual, appetite, snapshot, cycle_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (risk["id"], assessed_at, assessor, rationale, inherent, float(total * 100), residual,
         risk["appetite"], json.dumps(snapshot, ensure_ascii=False, default=str), cycle["id"] if cycle else None)).lastrowid
    newest = latest(db, risk["id"])               # geçmiş tarihli kayıt (ör. dönem aktarımı) özeti değiştirmez
    db.execute("UPDATE tdr_supplier_risks SET residual_score=?, risk_level=?, last_assessed_at=? WHERE id=?",
               (float(newest["residual"]), level_of(db, float(newest["residual"])), newest["assessed_at"], risk["id"]))
    return record_id


def _kri_value_rules(db, data, current, principal):
    kri = crud.get(db, KRIS, data["kri_id"])
    value = data["value"]
    worse = (lambda a, b: a >= b) if kri["direction"] == "higher_worse" else (lambda a, b: a <= b)
    data["status"] = "red" if worse(value, kri["threshold_red"]) else "amber" if worse(value, kri["threshold_amber"]) \
        else "green"
    data["recorded_by"] = principal.username if principal else "system"
    data["recorded_at"] = utcnow()
    if principal and principal.role == "MACHINE":
        data["source"] = "mcp"
    elif data.get("source") == "mcp":
        raise crud.Invalid("MCP kaynaklı ölçümü yalnızca MCP anahtarı yazar")
    latest_row = one(db, "SELECT MAX(period) AS p FROM tdr_kri_values WHERE kri_id=?", (kri["id"],))
    if not latest_row or not latest_row["p"] or str(data["period"]) >= str(latest_row["p"]):
        db.execute("UPDATE tdr_kris SET last_value=?, last_status=?, last_measured_at=? WHERE id=?",
                   (value, data["status"], data["period"], kri["id"]))


def _kri_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    amber, red = merged.get("threshold_amber"), merged.get("threshold_red")
    if amber is not None and red is not None:
        if merged.get("direction", "higher_worse") == "higher_worse" and red < amber:
            raise crud.Invalid("Kırmızı eşik sarı eşikten düşük olamaz (yüksek değer kötü)")
        if merged.get("direction") == "lower_worse" and red > amber:
            raise crud.Invalid("Kırmızı eşik sarı eşikten yüksek olamaz (düşük değer kötü)")


def _appetite_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    for key in ("appetite", "tolerance"):
        if merged.get(key) is not None and not 1 <= merged[key] <= 25:
            raise crud.Invalid("İştah ve tolerans 1–25 arasında olmalı")
    if merged.get("appetite") and merged.get("tolerance") and merged["tolerance"] < merged["appetite"]:
        raise crud.Invalid("Tolerans, iştahtan düşük olamaz")


def _cycle_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if merged.get("period_start") and merged.get("period_end") and str(merged["period_end"]) < str(merged["period_start"]):
        raise crud.Invalid("Dönem bitişi başlangıçtan önce olamaz")
    if current is not None and current["status"] == "closed" and set(data) - {"description"}:
        raise crud.Conflict("Kapanmış değerlendirme dönemi değiştirilemez")


KRI_VALUES.before_save = _kri_value_rules
KRIS.before_save = _kri_rules
APPETITES.before_save = _appetite_rules
CYCLES.before_save = _cycle_rules
KRIS.scope = lambda db, record: RISKS.scope(db, one(db, "SELECT * FROM tdr_supplier_risks WHERE id=?",
                                                    (record.get("risk_id"),)) or {})
KRI_VALUES.scope = via("kris", "kri_id")


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
RISKS.scope = lambda db, record: engagement_or_supplier(db, record) | {record.get("org_unit_id")}
ACTIONS.scope = via("supplier_risks", "risk_id")


def risk_context(c):
    authz.check(c.principal, RISKS, "read")
    risk = crud.get(c.db, RISKS, c.params["id"])
    risk["assessments"] = rows(c.db, "SELECT * FROM tdr_risk_assessments WHERE risk_id=? ORDER BY assessed_at DESC, id DESC",
                               (risk["id"],))
    for item in risk["assessments"]:
        item["snapshot"] = json.loads(item["snapshot"])
    risk["decisions"] = rows(c.db, "SELECT * FROM tdr_risk_decisions WHERE risk_id=? ORDER BY id DESC",
                             (risk["id"],))
    risk["actions"] = rows(c.db, "SELECT * FROM tdr_risk_actions WHERE risk_id=? ORDER BY due_date", (risk["id"],))
    risk["kris"] = rows(c.db, "SELECT * FROM tdr_kris WHERE risk_id=? ORDER BY code", (risk["id"],))
    risk["appetite_statement"] = one(c.db, "SELECT * FROM tdr_risk_appetites WHERE category=? AND active=1",
                                     (risk["category"],))
    risk["target_score"] = (risk["target_likelihood"] * risk["target_impact"]
                            if risk["target_likelihood"] and risk["target_impact"] else None)
    risk["level_bounds"] = policy(c.db, "risk.levels", LEVELS)
    risk["cis"] = []
    if c.app.enabled("cmdb"):        # etkilenen CI'lar (elle veya CMDB kuralıyla bağlı)
        from .cmdb import risk_cis
        risk["cis"] = risk_cis(c.db, risk["id"])
    risk["controls"] = []
    if c.app.enabled("grc"):        # bağlı kontroller ve son test sonuçları (kontrol etkinliği kanıtı)
        risk["controls"] = rows(c.db, """SELECT k.id, k.code, k.name, k.active, (SELECT x.status FROM tdr_executions x
            WHERE x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC LIMIT 1) AS last_status,
            (SELECT x.executed_at FROM tdr_executions x WHERE x.control_id=k.id ORDER BY x.executed_at DESC, x.id DESC
            LIMIT 1) AS last_executed_at FROM tdr_controls k JOIN tdr_control_risks m ON m.control_id=k.id
            WHERE m.risk_id=? ORDER BY k.code""", (risk["id"],))
    return risk


def overview(c):
    """Risk panosu: ısı haritası (içsel olasılık × etki), seviye dağılımı (artık, yoksa içsel), iştah üstü,
    gözden geçirmesi geciken, KRİ durumu, en yüksek riskler. Şirket ve kategori süzgeci."""
    authz.check(c.principal, RISKS, "read")
    where, params = ["status IN ('open','in_treatment','accepted')"], []
    for key in ("company_id", "category", "org_unit_id"):
        if c.query.get(key):
            where.append(f"{key}=?")
            params.append(int(c.query[key]) if key.endswith("_id") else c.query[key])
    sql = " AND ".join(where)
    risks = rows(c.db, f"SELECT * FROM tdr_supplier_risks WHERE {sql}", params)
    heat = [[0] * 5 for _ in range(5)]
    for r in risks:
        heat[r["likelihood"] - 1][r["impact"] - 1] += 1
    levels = {k: 0 for k in LEVELS}
    for r in risks:
        if r["risk_level"]:
            levels[r["risk_level"]] += 1
    today = date.today().isoformat()
    above = [r for r in risks if r["residual_score"] is not None and r["residual_score"] > r["appetite"]
             and r["status"] != "accepted"]
    top = sorted(risks, key=lambda r: -(r["residual_score"] if r["residual_score"] is not None
                                          else r["inherent_score"] or 0))[:10]
    by_company = rows(c.db, f"""SELECT co.id, co.name, co.kind, COUNT(r.id) AS count FROM tdr_companies co
        JOIN tdr_supplier_risks r ON r.company_id=co.id WHERE {sql.replace('status', 'r.status')
        .replace('company_id', 'r.company_id').replace('category', 'r.category').replace('org_unit_id', 'r.org_unit_id')}
        GROUP BY co.id, co.name, co.kind ORDER BY count DESC""", params)
    kri = rows(c.db, "SELECT last_status AS key, COUNT(*) AS count FROM tdr_kris WHERE active=1 AND last_status IS NOT NULL "
                     "GROUP BY last_status")
    cycles = rows(c.db, "SELECT * FROM tdr_risk_cycles WHERE status IN ('planned','open') ORDER BY period_start")
    return {"total": len(risks), "heat": heat, "levels": levels, "level_bounds": policy(c.db, "risk.levels", LEVELS),
            "above_appetite": len(above), "unassessed": sum(1 for r in risks if r["residual_score"] is None),
            "review_overdue": sum(1 for r in risks if r["review_date"] and str(r["review_date"]) < today),
            "by_category": _count(risks, "category"), "by_source": _count(risks, "source"),
            "by_company": by_company, "kri": kri, "cycles": [cycle_progress(c.db, x) for x in cycles],
            "opportunities": sum(1 for r in risks if r["risk_type"] == "opportunity"),
            "actions_overdue": one(c.db, "SELECT COUNT(*) AS n FROM tdr_risk_actions WHERE status IN ('open','in_progress') "
                                         "AND due_date < ?", (today,))["n"],
            "top": [{k: r[k] for k in ("id", "code", "title", "category", "company_id", "inherent_score", "residual_score",
                                       "appetite", "risk_level", "status", "owner")} for r in top]}


def _count(items, key):
    out = {}
    for item in items:
        out[item[key]] = out.get(item[key], 0) + 1
    return [{"key": k, "count": v} for k, v in sorted(out.items(), key=lambda x: -x[1])]


def cycle_progress(db, cycle):
    """Dönemdeki ilerleme: kapsamdaki açık risklerden kaçı dönem içinde değerlendirildi."""
    params = [cycle["period_start"], cycle["period_end"]]
    company = " AND r.company_id=?" if cycle["company_id"] else ""
    if company:
        params.append(cycle["company_id"])
    row = one(db, f"""SELECT COUNT(*) AS total, SUM(CASE WHEN EXISTS (SELECT 1 FROM tdr_risk_assessments a
        WHERE a.risk_id=r.id AND a.assessed_at >= ? AND a.assessed_at < ?) THEN 1 ELSE 0 END) AS done
        FROM tdr_supplier_risks r WHERE r.status IN ('open','in_treatment','accepted'){company}""",
              [cycle["period_start"], _next_day(cycle["period_end"])] + params[2:])
    total, done = row["total"] or 0, row["done"] or 0
    return {**cycle, "in_scope": total, "assessed": done, "progress_pct": round(100 * done / total, 1) if total else None}


def _next_day(value):
    return (date.fromisoformat(str(value)[:10]) + timedelta(days=1)).isoformat()


def cycle_context(c):
    authz.check(c.principal, CYCLES, "read")
    cycle = cycle_progress(c.db, crud.get(c.db, CYCLES, c.params["id"]))
    company = " AND r.company_id=?" if cycle["company_id"] else ""
    cycle["risks"] = rows(c.db, f"""SELECT r.id, r.code, r.title, r.owner, r.risk_level, r.residual_score, r.status,
        (SELECT MAX(a.assessed_at) FROM tdr_risk_assessments a WHERE a.risk_id=r.id AND a.assessed_at >= ? AND
         a.assessed_at < ?) AS assessed_in_cycle FROM tdr_supplier_risks r
        WHERE r.status IN ('open','in_treatment','accepted'){company} ORDER BY r.code""",
                          [cycle["period_start"], _next_day(cycle["period_end"])] +
                          ([cycle["company_id"]] if company else []))
    return cycle


def register(app):
    app.route("PATCH", API + "/supplier_risks/{id}", update_risk)
    app.route("POST", API + "/supplier_risks/{id}/assessments", assess)
    app.route("GET", API + "/supplier_risks/{id}/context", risk_context)
    app.route("GET", API + "/risks/overview", overview)
    app.route("GET", API + "/risk_cycles/{id}/context", cycle_context)


DEFAULT_POLICIES = (
    ("risk.levels", LEVELS, "Risk seviyesi üst sınırları (olasılık × etki puanına göre): düşük, orta, yüksek, kritik"),
    ("risk.default_appetite", 9, "Kategorisinin iştah beyanı yoksa yeni riskin iştah eşiği (1–25)"),
)
LIKELIHOOD = (
    (1, "Çok düşük", "Olağanüstü koşullarda olabilir", "10 yılda bir veya daha seyrek"),
    (2, "Düşük", "Bazı koşullarda olabilir", "5–10 yılda bir"),
    (3, "Orta", "Belirli bir dönemde olabilir", "1–5 yılda bir"),
    (4, "Yüksek", "Çoğu koşulda olması beklenir", "Yılda bir"),
    (5, "Çok yüksek", "Neredeyse kesin", "Yılda birden çok"),
)
IMPACT = (
    (1, "Önemsiz", "< 100 bin TL", "Kesinti yok veya < 1 saat", "Yerel, kısa süreli", "İhlal yok"),
    (2, "Küçük", "100 bin – 1 M TL", "1–4 saat kesinti", "Sınırlı müşteri şikâyeti", "Küçük uyumsuzluk"),
    (3, "Orta", "1–10 M TL", "4–24 saat kesinti", "Yerel medya, müşteri kaybı", "Düzenleyici uyarı"),
    (4, "Büyük", "10–50 M TL", "1–3 gün kesinti", "Ulusal medya", "İdari para cezası"),
    (5, "Çok büyük", "> 50 M TL", "> 3 gün kesinti", "Kalıcı itibar kaybı", "Faaliyet izni riski"),
)


def seed(db):
    for code, value, description in DEFAULT_POLICIES:
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))
    if not one(db, "SELECT id FROM tdr_risk_criteria LIMIT 1"):     # öneri ölçek; kurum kendi eşikleriyle değiştirir
        for level, label, description, frequency in LIKELIHOOD:
            db.execute("INSERT INTO tdr_risk_criteria (dimension, level, label, description, frequency) VALUES (?,?,?,?,?)",
                       ("likelihood", level, label, description, frequency))
        for level, label, financial, operational, reputational, legal in IMPACT:
            db.execute("INSERT INTO tdr_risk_criteria (dimension, level, label, financial, operational, reputational, "
                       "legal) VALUES (?,?,?,?,?,?,?)", ("impact", level, label, financial, operational, reputational, legal))
