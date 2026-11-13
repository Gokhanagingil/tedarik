"""Anket motoru: tedarikçi memnuniyeti, tedarikçi risk değerlendirmesi ve bağımsız (genel) anketler.

Kavramlar
- **Şablon** (`survey_templates`): amaç (memnuniyet, risk, genel), giriş ve kapanış metni, bölümler, sorular.
  Taslakken düzenlenir; yayımlanınca dondurulur. Değişiklik için yeni sürüm kopyalanır; geçmiş yanıtlar
  hangi sorularla verildiyse onlarla kalır.
- **Soru** (`survey_questions`): türler 1–5 ölçek, tavsiye (0–10), evet/hayır, tek seçim, çoklu seçim, metin,
  sayı, tarih. Ağırlık, seçenek puanları, koşullu gösterim (`show_if`), risk kategorisi ve eşiği taşır.
- **Kampanya** (`survey_campaigns`): şablonun bir uygulaması. Konu: yok (bağımsız anket), tedarikçi veya
  angajman. Katılım: davetliler veya tüm kullanıcılar. Anonim olabilir.
- **Hedef** (`survey_targets`): değerlendirilen tedarikçi veya angajman. Bir kampanya birçok hedefi kapsar.
- **Davet** ve **yanıt**: yanıt taslak olarak kaydedilir, gönderilince değişmez.

Puanlama (0–100): 1–5 ölçek (v−1)×25; tavsiye v×10; evet/hayır ve seçimler seçenek puanıyla (evet=100,
hayır=0 varsayılan; olumsuz soruda seçenek puanı tersine çevrilir); çoklu seçimde seçilenlerin ortalaması.
Metin, sayı ve tarih puanlanmaz. Yanıt puanı ağırlıklı ortalamadır. Tavsiye sorusunda ayrıca NPS hesaplanır.

Risk bağlantısı: risk kategorisi ve eşiği olan soruda bir hedefin ortalama puanı eşiğin altındaysa sonuçta
"risk sinyali" görünür; yetkili kişi sinyalden tek adımda tedarikçi riski açar (`origin_ref` ile izlenir).

Anonimlik: anonim kampanyada yanıt kişiyle eşleşmez (davet yalnızca "yanıtlandı" olur); kişi anahtarı
kampanyaya özgü gizli tuzla özetlenir. Yanıt sayısı `min_responses` altındaysa ayrıntılı sonuç gösterilmez.
"""
import hashlib
import json
import secrets
from datetime import date

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, guard_readonly
from ..schema import RESOURCES, Resource, fk

M = "surveys"
KINDS = ("scale_1_5", "nps_0_10", "yes_no", "single_choice", "multi_choice", "text", "number", "date")
CHOICE_KINDS = ("single_choice", "multi_choice")
RISK_CATEGORIES = ("continuity", "security", "compliance", "financial", "concentration", "performance",
                   "privacy", "reputation", "exit")
YES_NO = [{"value": "yes", "label": "Evet", "score": 100}, {"value": "no", "label": "Hayır", "score": 0}]
TEXT_LIMIT = 5000

TEMPLATES = Resource("survey_templates", "Anket Şablonları", {
    "code": "TEXT NOT NULL", "name": "TEXT NOT NULL", "purpose": "TEXT NOT NULL DEFAULT 'general'",
    "description": "TEXT", "intro": "TEXT", "outro": "TEXT", "status": "TEXT NOT NULL DEFAULT 'draft'",
    "version": "INTEGER NOT NULL DEFAULT 1", "parent_id": fk("survey_templates", False),
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, unique=(("code", "version"),), search=("code", "name", "description"),
    readonly=("status", "version", "parent_id"),
    enums={"purpose": ("satisfaction", "risk", "general"), "status": ("draft", "published", "retired")})

SECTIONS = Resource("survey_sections", "Anket Bölümleri", {
    "template_id": fk("survey_templates"), "position": "INTEGER NOT NULL DEFAULT 1", "title": "TEXT NOT NULL",
    "description": "TEXT"}, module=M, search=("title",))

QUESTIONS = Resource("survey_questions", "Anket Soruları", {
    "template_id": fk("survey_templates"), "section_id": fk("survey_sections", False),
    "position": "INTEGER NOT NULL DEFAULT 1", "code": "TEXT", "text": "TEXT NOT NULL", "help": "TEXT",
    "kind": "TEXT NOT NULL DEFAULT 'scale_1_5'", "required": "INTEGER NOT NULL DEFAULT 1",
    "weight": "REAL NOT NULL DEFAULT 1", "options_json": "TEXT", "show_if_json": "TEXT",
    "risk_category": "TEXT", "risk_threshold": "INTEGER"},
    module=M, unique=(("template_id", "code"),), search=("text", "code"),
    enums={"kind": KINDS, "risk_category": RISK_CATEGORIES})

CAMPAIGNS = Resource("survey_campaigns", "Anket Kampanyaları", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "template_id": fk("survey_templates"),
    "description": "TEXT", "subject": "TEXT NOT NULL DEFAULT 'none'", "audience": "TEXT NOT NULL DEFAULT 'invited'",
    "anonymous": "INTEGER NOT NULL DEFAULT 0", "min_responses": "INTEGER NOT NULL DEFAULT 3",
    "period_start": "DATE", "period_end": "DATE", "opens_on": "DATE", "closes_on": "DATE",
    "owner": "TEXT", "status": "TEXT NOT NULL DEFAULT 'draft'", "opened_at": "TIMESTAMP", "closed_at": "TIMESTAMP",
    "salt": "TEXT", "created_at": "TIMESTAMP NOT NULL"},
    module=M, search=("code", "name", "description"), readonly=("status", "opened_at", "closed_at", "salt"),
    enums={"subject": ("none", "supplier", "engagement"), "audience": ("invited", "all"),
           "status": ("draft", "open", "closed")})

TARGETS = Resource("survey_targets", "Değerlendirilen Tedarikçiler", {
    "campaign_id": fk("survey_campaigns"), "supplier_id": fk("suppliers"), "engagement_id": fk("engagements", False)},
    module=M, api=("list", "get", "create"), search=())

INVITES = Resource("survey_invitations", "Anket Davetleri", {
    "campaign_id": fk("survey_campaigns"), "respondent": "TEXT NOT NULL", "target_id": fk("survey_targets", False),
    "org_unit_id": fk("org_units", False), "status": "TEXT NOT NULL DEFAULT 'pending'", "answered_at": "TIMESTAMP"},
    module=M, api=("list", "get", "create"), search=("respondent",), readonly=("status", "answered_at"),
    enums={"status": ("pending", "answered")})

RESPONSES = Resource("survey_responses", "Anket Yanıtları", {
    "campaign_id": fk("survey_campaigns"), "target_id": fk("survey_targets", False),
    "invitation_id": fk("survey_invitations", False), "respondent": "TEXT", "respondent_key": "TEXT NOT NULL",
    "status": "TEXT NOT NULL DEFAULT 'draft'", "score": "REAL", "started_at": "TIMESTAMP NOT NULL",
    "submitted_at": "TIMESTAMP"},
    module=M, api=(), search=(), unique=(("campaign_id", "respondent_key"),),
    enums={"status": ("draft", "submitted")})

ANSWERS = Resource("survey_answers", "Yanıt Ayrıntıları", {
    "response_id": fk("survey_responses"), "question_id": fk("survey_questions"), "value_text": "TEXT",
    "value_number": "REAL", "values_json": "TEXT", "score": "REAL"},
    module=M, api=(), search=(), unique=(("response_id", "question_id"),))


# ------------------------------------------------------------------ yardımcılar

def _json(text, default=None):
    return json.loads(text) if text else default


def _template_draft(db, template_id):
    template = crud.get(db, TEMPLATES, template_id)
    if template["status"] != "draft":
        raise crud.Conflict("Yayımlanmış şablon değiştirilemez; yeni sürüm oluşturun")
    return template


def _options(kind, raw):
    if kind == "yes_no" and not raw:
        return YES_NO
    if kind not in CHOICE_KINDS + ("yes_no",):
        if raw:
            raise crud.Invalid("Seçenekler yalnızca seçimli sorularda kullanılır")
        return None
    options = _json(raw, []) if isinstance(raw, str) else raw
    if not isinstance(options, list) or not options or len(options) > 50:
        raise crud.Invalid("Seçimli soru için 1–50 seçenek gerekli")
    seen = set()
    for item in options:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str) or not item["label"].strip():
            raise crud.Invalid("Her seçeneğin bir etiketi olmalı")
        item.setdefault("value", item["label"].strip())
        if item["value"] in seen:
            raise crud.Invalid("Seçenek değerleri tekrarlanamaz")
        seen.add(item["value"])
        score = item.get("score")
        if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100):
            raise crud.Invalid("Seçenek puanı 0–100 aralığında olmalı")
    if kind == "yes_no" and {o["value"] for o in options} != {"yes", "no"}:
        raise crud.Invalid("Evet/Hayır sorusunda seçenek değerleri yes ve no olmalı")
    return options


def _question_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    _template_draft(db, merged["template_id"])
    if current and data.get("template_id") not in (None, current["template_id"]):
        raise crud.Invalid("Soru başka şablona taşınamaz")
    kind = merged.get("kind") or "scale_1_5"
    if "options_json" in data or "kind" in data or current is None:
        options = _options(kind, data.get("options_json", merged.get("options_json")))
        data["options_json"] = json.dumps(options, ensure_ascii=False) if options else None
    if merged.get("section_id"):
        section = crud.get(db, SECTIONS, merged["section_id"])
        if section["template_id"] != merged["template_id"]:
            raise crud.Invalid("Bölüm bu şablona ait değil")
    weight = merged.get("weight", 1)
    if weight is not None and not 0 <= weight <= 100:
        raise crud.Invalid("Ağırlık 0–100 aralığında olmalı")
    threshold = merged.get("risk_threshold")
    if threshold is not None and not 0 <= threshold <= 100:
        raise crud.Invalid("Risk eşiği 0–100 aralığında olmalı")
    if threshold is not None and not merged.get("risk_category"):
        raise crud.Invalid("Risk eşiği için risk kategorisi seçin")
    if kind not in ("scale_1_5", "nps_0_10", "yes_no", "single_choice", "multi_choice") and merged.get("risk_category"):
        raise crud.Invalid("Risk kategorisi yalnızca puanlanan sorularda kullanılır")
    if current is None and not merged.get("code"):
        count = one(db, "SELECT COUNT(*) AS n FROM tdr_survey_questions WHERE template_id=?",
                    (merged["template_id"],))["n"]
        code = f"S{count + 1}"
        while one(db, "SELECT 1 AS x FROM tdr_survey_questions WHERE template_id=? AND code=?",
                  (merged["template_id"], code)):
            count += 1
            code = f"S{count + 1}"
        data["code"] = code
    if "show_if_json" in data and data["show_if_json"]:
        rule = _json(data["show_if_json"]) if isinstance(data["show_if_json"], str) else data["show_if_json"]
        if not isinstance(rule, dict) or not isinstance(rule.get("question"), str) or \
                not {"equals", "in", "min", "max"} & set(rule):
            raise crud.Invalid("Koşul biçimi: {\"question\": \"S1\", \"equals\" | \"in\" | \"min\" | \"max\": ...}")
        source = one(db, "SELECT * FROM tdr_survey_questions WHERE template_id=? AND code=?",
                     (merged["template_id"], rule["question"]))
        if not source or (current and source["id"] == current["id"]):
            raise crud.Invalid("Koşuldaki soru bu şablonda bulunamadı")
        data["show_if_json"] = json.dumps(rule, ensure_ascii=False)


def _section_rules(db, data, current, principal):
    _template_draft(db, {**(current or {}), **data}["template_id"])


def _template_rules(db, data, current, principal):
    if current is not None and current["status"] != "draft":
        raise crud.Conflict("Yayımlanmış şablon değiştirilemez; yeni sürüm oluşturun")


def _campaign_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if current is not None and current["status"] != "draft":
        allowed = {"name", "description", "closes_on", "owner", "min_responses"}
        if set(data) - allowed:
            raise crud.Conflict("Açılmış kampanyada yalnızca ad, açıklama, kapanış tarihi ve sahip değişir")
    template = crud.get(db, TEMPLATES, merged["template_id"])
    if template["status"] == "retired":
        raise crud.Invalid("Kullanımdan kalkmış şablonla kampanya açılamaz")
    if merged.get("min_responses") is not None and not 1 <= merged["min_responses"] <= 100:
        raise crud.Invalid("En az yanıt sayısı 1–100 olmalı")
    if merged.get("anonymous") not in (None, 0, 1):
        raise crud.Invalid("Anonim 0 veya 1 olmalı")
    if merged.get("opens_on") and merged.get("closes_on") and merged["closes_on"] < merged["opens_on"]:
        raise crud.Invalid("Kapanış tarihi açılıştan önce olamaz")
    if current is None:
        data["salt"] = secrets.token_hex(16)
        data.setdefault("owner", principal.username if principal else None)


def _target_rules(db, data, current, principal):
    campaign = crud.get(db, CAMPAIGNS, data["campaign_id"])
    if campaign["status"] == "closed":
        raise crud.Conflict("Kapalı kampanyaya hedef eklenemez")
    if campaign["subject"] == "none":
        raise crud.Invalid("Bağımsız ankette değerlendirilen tedarikçi olmaz")
    if campaign["subject"] == "engagement":
        if not data.get("engagement_id"):
            raise crud.Invalid("Angajman anketinde angajman seçilmeli")
        engagement = crud.get(db, RESOURCES["engagements"], data["engagement_id"])
        data["supplier_id"] = engagement["supplier_id"]
    elif data.get("engagement_id"):
        raise crud.Invalid("Tedarikçi anketinde angajman seçilmez")
    if one(db, "SELECT id FROM tdr_survey_targets WHERE campaign_id=? AND supplier_id=? AND "
               "COALESCE(engagement_id, 0)=?", (data["campaign_id"], data["supplier_id"],
                                                data.get("engagement_id") or 0)):
        raise crud.Conflict("Bu hedef kampanyada zaten var")


def _invite_rules(db, data, current, principal):
    campaign = crud.get(db, CAMPAIGNS, data["campaign_id"])
    if campaign["status"] == "closed":
        raise crud.Conflict("Kapalı kampanyaya davet eklenemez")
    target = data.get("target_id")
    if campaign["subject"] != "none" and not target:
        raise crud.Invalid("Tedarikçi anketinde davet bir hedefe bağlanır (target_id)")
    if campaign["subject"] == "none" and target:
        raise crud.Invalid("Bağımsız ankette hedef olmaz")
    if target and crud.get(db, TARGETS, target)["campaign_id"] != campaign["id"]:
        raise crud.Invalid("Hedef bu kampanyaya ait değil")
    if one(db, "SELECT id FROM tdr_survey_invitations WHERE campaign_id=? AND respondent=? AND "
               "COALESCE(target_id, 0)=?", (campaign["id"], data["respondent"], target or 0)):
        raise crud.Conflict("Bu kişi bu hedef için zaten davetli")


TEMPLATES.before_save = _template_rules
SECTIONS.before_save = _section_rules
QUESTIONS.before_save = _question_rules
CAMPAIGNS.before_save = _campaign_rules
TARGETS.before_save = _target_rules
INVITES.before_save = _invite_rules


def structure(db, template_id):
    template = crud.get(db, TEMPLATES, template_id)
    sections = rows(db, "SELECT * FROM tdr_survey_sections WHERE template_id=? ORDER BY position, id", (template_id,))
    questions = rows(db, "SELECT * FROM tdr_survey_questions WHERE template_id=? ORDER BY position, id",
                     (template_id,))
    for q in questions:
        q["options"] = _json(q.pop("options_json"))
        q["show_if"] = _json(q.pop("show_if_json"))
    template["sections"], template["questions"] = sections, questions
    return template


# ------------------------------------------------------------------ şablon işlemleri

def _manage(c, res, action="write"):
    authz.require_human(c.principal)
    authz.check(c.principal, res, action)


def template_structure(c):
    authz.check(c.principal, TEMPLATES, "read")
    return structure(c.db, c.params["id"])


def publish(c):
    _manage(c, TEMPLATES)
    template = crud.get(c.db, TEMPLATES, c.params["id"])
    if template["status"] != "draft":
        raise crud.Conflict("Yalnızca taslak şablon yayımlanır")
    if not one(c.db, "SELECT 1 AS x FROM tdr_survey_questions WHERE template_id=?", (template["id"],)):
        raise crud.Invalid("Yayımlamak için en az bir soru ekleyin")
    c.db.execute("UPDATE tdr_survey_templates SET status='published', updated_at=? WHERE id=?",
                 (utcnow(), template["id"]))
    audit.log(c.db, c.principal, "PUBLISH", TEMPLATES.name, template["id"])
    return structure(c.db, template["id"])


def retire(c):
    _manage(c, TEMPLATES)
    template = crud.get(c.db, TEMPLATES, c.params["id"])
    c.db.execute("UPDATE tdr_survey_templates SET status='retired', updated_at=? WHERE id=?",
                 (utcnow(), template["id"]))
    audit.log(c.db, c.principal, "RETIRE", TEMPLATES.name, template["id"])
    return crud.get(c.db, TEMPLATES, template["id"])


def copy_template(c):
    """Yeni sürüm (aynı kod) veya yeni şablon (yeni kod). Bölümler, sorular ve koşullar kopyalanır."""
    _manage(c, TEMPLATES)
    source = structure(c.db, c.params["id"])
    code = c.body.get("code") or source["code"]
    if code == source["code"]:
        version = one(c.db, "SELECT MAX(version) AS v FROM tdr_survey_templates WHERE code=?", (code,))["v"] + 1
    else:
        version = 1
    new_id = c.db.execute(
        "INSERT INTO tdr_survey_templates (code, name, purpose, description, intro, outro, status, version, "
        "parent_id, created_at) VALUES (?,?,?,?,?,?,'draft',?,?,?)",
        (code, c.body.get("name") or source["name"], source["purpose"], source["description"], source["intro"],
         source["outro"], version, source["id"], utcnow())).lastrowid
    sections = {}
    for s in source["sections"]:
        sections[s["id"]] = c.db.execute(
            "INSERT INTO tdr_survey_sections (template_id, position, title, description) VALUES (?,?,?,?)",
            (new_id, s["position"], s["title"], s["description"])).lastrowid
    for q in source["questions"]:
        c.db.execute(
            "INSERT INTO tdr_survey_questions (template_id, section_id, position, code, text, help, kind, required, "
            "weight, options_json, show_if_json, risk_category, risk_threshold) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id, sections.get(q["section_id"]), q["position"], q["code"], q["text"], q["help"], q["kind"],
             q["required"], q["weight"], json.dumps(q["options"], ensure_ascii=False) if q["options"] else None,
             json.dumps(q["show_if"], ensure_ascii=False) if q["show_if"] else None, q["risk_category"],
             q["risk_threshold"]))
    audit.log(c.db, c.principal, "COPY", TEMPLATES.name, new_id, {"from": source["id"], "version": version})
    return 201, structure(c.db, new_id)


def reorder(c):
    """Soru sırası (ve isteğe bağlı bölüm ataması) tek istekte: [{"id": 5, "section_id": 2}, ...]."""
    _manage(c, QUESTIONS)
    template = _template_draft(c.db, c.params["id"])
    items = c.body.get("questions")
    if not isinstance(items, list):
        raise crud.Invalid("questions listesi gerekli")
    owned = {r["id"] for r in rows(c.db, "SELECT id FROM tdr_survey_questions WHERE template_id=?",
                                   (template["id"],))}
    sections = {r["id"] for r in rows(c.db, "SELECT id FROM tdr_survey_sections WHERE template_id=?",
                                      (template["id"],))}
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict) or item.get("id") not in owned:
            raise crud.Invalid("Liste yalnızca bu şablonun sorularını içerebilir")
        section = item.get("section_id")
        if section is not None and section not in sections:
            raise crud.Invalid("Bölüm bu şablona ait değil")
        c.db.execute("UPDATE tdr_survey_questions SET position=?, section_id=? WHERE id=?",
                     (position, section, item["id"]))
    audit.log(c.db, c.principal, "REORDER", TEMPLATES.name, template["id"])
    return structure(c.db, template["id"])


# ------------------------------------------------------------------ kampanya işlemleri

def campaign_context(c):
    authz.check(c.principal, CAMPAIGNS, "read")
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    campaign.pop("salt", None)
    campaign["template"] = crud.get(c.db, TEMPLATES, campaign["template_id"])
    campaign["targets"] = rows(c.db, """SELECT t.*, s.code AS supplier_code, s.name AS supplier_name, s.tier,
        e.code AS engagement_code FROM tdr_survey_targets t JOIN tdr_suppliers s ON s.id=t.supplier_id
        LEFT JOIN tdr_engagements e ON e.id=t.engagement_id WHERE t.campaign_id=? ORDER BY s.name""",
                               (campaign["id"],))
    campaign["invitations"] = rows(c.db, "SELECT * FROM tdr_survey_invitations WHERE campaign_id=? "
                                         "ORDER BY respondent, id", (campaign["id"],))
    campaign["response_counts"] = one(c.db, """SELECT COUNT(*) AS started,
        COALESCE(SUM(CASE WHEN status='submitted' THEN 1 ELSE 0 END), 0) AS submitted
        FROM tdr_survey_responses WHERE campaign_id=?""", (campaign["id"],))
    return campaign


def add_targets(c):
    """Toplu hedef: {"supplier_ids": [...]} veya {"engagement_ids": [...]} veya {"tier": "critical"}."""
    _manage(c, TARGETS)
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    if campaign["subject"] == "engagement":
        ids = c.body.get("engagement_ids") or []
        if c.body.get("tier"):
            ids += [r["id"] for r in rows(c.db, """SELECT e.id FROM tdr_engagements e JOIN tdr_suppliers s
                ON s.id=e.supplier_id WHERE s.tier=? AND e.status='active'""", (c.body["tier"],))]
        items = [{"engagement_id": i} for i in dict.fromkeys(ids)]
    else:
        ids = c.body.get("supplier_ids") or []
        if c.body.get("tier"):
            ids += [r["id"] for r in rows(c.db, "SELECT id FROM tdr_suppliers WHERE tier=? AND status='active'",
                                          (c.body["tier"],))]
        items = [{"supplier_id": i} for i in dict.fromkeys(ids)]
    added, skipped = [], 0
    for item in items:
        try:
            with c.db.savepoint():
                added.append(crud.insert(c.db, TARGETS, {"campaign_id": campaign["id"], **item}, c.principal))
        except crud.Conflict:
            skipped += 1
    audit.log(c.db, c.principal, "TARGETS", CAMPAIGNS.name, campaign["id"], {"added": len(added), "skipped": skipped})
    return {"added": len(added), "skipped": skipped}


def invite(c):
    """Toplu davet: {"respondents": ["ayse", ...], "target_ids": [..] | "all", "org_unit_id": ...}."""
    _manage(c, INVITES)
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    people = c.body.get("respondents")
    if not isinstance(people, list) or not people or any(not isinstance(p, str) or not p.strip() for p in people):
        raise crud.Invalid("respondents kullanıcı adları listesi olmalı")
    targets = [None]
    if campaign["subject"] != "none":
        chosen = c.body.get("target_ids", "all")
        all_targets = [r["id"] for r in rows(c.db, "SELECT id FROM tdr_survey_targets WHERE campaign_id=?",
                                             (campaign["id"],))]
        targets = all_targets if chosen == "all" else chosen
        if not targets:
            raise crud.Invalid("Önce değerlendirilecek tedarikçileri ekleyin")
    created, skipped = 0, 0
    for person in dict.fromkeys(p.strip() for p in people):
        for target in targets:
            try:
                with c.db.savepoint():
                    crud.insert(c.db, INVITES, {"campaign_id": campaign["id"], "respondent": person,
                                                "target_id": target, "org_unit_id": c.body.get("org_unit_id")},
                                c.principal)
                    created += 1
            except crud.Conflict:
                skipped += 1
    audit.log(c.db, c.principal, "INVITE", CAMPAIGNS.name, campaign["id"], {"created": created, "skipped": skipped})
    return {"created": created, "skipped": skipped}


def open_campaign(c):
    _manage(c, CAMPAIGNS)
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    if campaign["status"] != "draft":
        raise crud.Conflict(f"Kampanya '{campaign['status']}' durumunda; açılamaz")
    template = crud.get(c.db, TEMPLATES, campaign["template_id"])
    if template["status"] == "draft":           # açılış şablonu dondurur
        if not one(c.db, "SELECT 1 AS x FROM tdr_survey_questions WHERE template_id=?", (template["id"],)):
            raise crud.Invalid("Şablonda soru yok")
        c.db.execute("UPDATE tdr_survey_templates SET status='published', updated_at=? WHERE id=?",
                     (utcnow(), template["id"]))
    if campaign["subject"] != "none" and not one(c.db, "SELECT 1 AS x FROM tdr_survey_targets WHERE campaign_id=?",
                                                 (campaign["id"],)):
        raise crud.Invalid("Değerlendirilecek en az bir tedarikçi ekleyin")
    if campaign["audience"] == "invited" and not one(
            c.db, "SELECT 1 AS x FROM tdr_survey_invitations WHERE campaign_id=?", (campaign["id"],)):
        raise crud.Invalid("Davetli katılımda en az bir kişiyi davet edin")
    c.db.execute("UPDATE tdr_survey_campaigns SET status='open', opened_at=? WHERE id=?", (utcnow(), campaign["id"]))
    audit.log(c.db, c.principal, "OPEN", CAMPAIGNS.name, campaign["id"])
    return {"id": campaign["id"], "status": "open"}


def close_campaign(c):
    _manage(c, CAMPAIGNS)
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    if campaign["status"] != "open":
        raise crud.Conflict("Yalnızca açık kampanya kapatılır")
    c.db.execute("UPDATE tdr_survey_campaigns SET status='closed', closed_at=? WHERE id=?",
                 (utcnow(), campaign["id"]))
    audit.log(c.db, c.principal, "CLOSE", CAMPAIGNS.name, campaign["id"])
    return {"id": campaign["id"], "status": "closed"}


# ------------------------------------------------------------------ yanıtlama

def _key(campaign, username, target_id):
    return hashlib.sha256(f"{campaign['salt']}:{username}:{target_id or 0}".encode()).hexdigest()


def _is_open(campaign):
    today = date.today().isoformat()
    return (campaign["status"] == "open" and (not campaign["opens_on"] or campaign["opens_on"] <= today)
            and (not campaign["closes_on"] or campaign["closes_on"] >= today))


def _respondent(c):
    if c.principal.auth_type == "api_key":
        raise crud.Forbidden("Anketleri kullanıcılar yanıtlar")
    return c.principal.username


def my_surveys(c):
    """Kişinin yanıtlayabileceği ve yanıtladığı anketler (davetler ve herkese açık kampanyalar)."""
    username = _respondent(c)
    found = []
    campaigns = rows(c.db, "SELECT * FROM tdr_survey_campaigns WHERE status IN ('open','closed') ORDER BY id DESC")
    for campaign in campaigns:
        if campaign["audience"] == "invited":
            invites = rows(c.db, "SELECT * FROM tdr_survey_invitations WHERE campaign_id=? AND respondent=?",
                           (campaign["id"], username))
            slots = [(i["target_id"], i) for i in invites]
        else:
            targets = rows(c.db, "SELECT id FROM tdr_survey_targets WHERE campaign_id=?", (campaign["id"],))
            slots = [(t["id"], None) for t in targets] if campaign["subject"] != "none" else [(None, None)]
        for target_id, invitation in slots:
            response = one(c.db, "SELECT id, status, submitted_at FROM tdr_survey_responses WHERE campaign_id=? "
                                 "AND respondent_key=?", (campaign["id"], _key(campaign, username, target_id)))
            if campaign["status"] == "closed" and not response:
                continue
            target = one(c.db, """SELECT t.id, s.name AS supplier_name, e.code AS engagement_code
                FROM tdr_survey_targets t JOIN tdr_suppliers s ON s.id=t.supplier_id
                LEFT JOIN tdr_engagements e ON e.id=t.engagement_id WHERE t.id=?""", (target_id,)) if target_id else None
            found.append({"campaign_id": campaign["id"], "campaign": campaign["name"], "code": campaign["code"],
                          "anonymous": bool(campaign["anonymous"]), "closes_on": campaign["closes_on"],
                          "open": _is_open(campaign), "target": target, "invitation_id": invitation and invitation["id"],
                          "response_id": response and response["id"],
                          "state": "submitted" if response and response["status"] == "submitted"
                          else "draft" if response else "new"})
    return found


def start_response(c):
    """Kişi için yanıt açar veya taslağını döner. Anonim kampanyada yanıt kişiyle eşleşmez."""
    username = _respondent(c)
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    if not _is_open(campaign):
        raise crud.Conflict("Anket şu anda yanıtlamaya açık değil")
    target_id = c.body.get("target_id")
    if campaign["subject"] == "none":
        target_id = None
    elif not target_id or crud.get(c.db, TARGETS, target_id)["campaign_id"] != campaign["id"]:
        raise crud.Invalid("Değerlendirilecek tedarikçiyi seçin (target_id)")
    invitation = None
    if campaign["audience"] == "invited":
        invitation = one(c.db, "SELECT * FROM tdr_survey_invitations WHERE campaign_id=? AND respondent=? "
                               "AND COALESCE(target_id, 0)=?", (campaign["id"], username, target_id or 0))
        if not invitation:
            raise crud.Forbidden("Bu ankete davetli değilsiniz")
    key = _key(campaign, username, target_id)
    c.db.lock("survey:" + key)
    existing = one(c.db, "SELECT * FROM tdr_survey_responses WHERE campaign_id=? AND respondent_key=?",
                   (campaign["id"], key))
    if existing:
        return {"response_id": existing["id"], "status": existing["status"]}
    anonymous = bool(campaign["anonymous"])
    response_id = c.db.execute(
        "INSERT INTO tdr_survey_responses (campaign_id, target_id, invitation_id, respondent, respondent_key, status, "
        "started_at) VALUES (?,?,?,?,?,'draft',?)",
        (campaign["id"], target_id, None if anonymous or not invitation else invitation["id"],
         None if anonymous else username, key, utcnow())).lastrowid
    return 201, {"response_id": response_id, "status": "draft"}


def _own_response(c):
    username = _respondent(c)
    response = one(c.db, "SELECT * FROM tdr_survey_responses WHERE id=?", (c.params["id"],))
    if not response:
        raise crud.NotFound("Yanıt bulunamadı")
    campaign = crud.get(c.db, CAMPAIGNS, response["campaign_id"])
    if response["respondent_key"] != _key(campaign, username, response["target_id"]):
        raise crud.Forbidden("Bu yanıt size ait değil")
    return response, campaign


def visible(question, values):
    rule = question.get("show_if")
    if not rule:
        return True
    value = values.get(rule["question"])
    if value is None:
        return False
    if "equals" in rule:
        return value == rule["equals"] or (isinstance(value, list) and rule["equals"] in value)
    if "in" in rule:
        return value in rule["in"] or (isinstance(value, list) and bool(set(value) & set(rule["in"])))
    if not isinstance(value, (int, float)):
        return False
    return ("min" not in rule or value >= rule["min"]) and ("max" not in rule or value <= rule["max"])


def response_form(c):
    response, campaign = _own_response(c)
    form = structure(c.db, campaign["template_id"])
    answers = rows(c.db, "SELECT * FROM tdr_survey_answers WHERE response_id=?", (response["id"],))
    form["answers"] = {a["question_id"]: _stored_value(a) for a in answers}
    form["response"] = {k: response[k] for k in ("id", "status", "started_at", "submitted_at", "score", "target_id")}
    form["campaign"] = {k: campaign[k] for k in ("id", "code", "name", "description", "anonymous", "closes_on",
                                                  "subject")}
    form["target"] = one(c.db, """SELECT t.id, s.name AS supplier_name, s.code AS supplier_code,
        e.code AS engagement_code FROM tdr_survey_targets t JOIN tdr_suppliers s ON s.id=t.supplier_id
        LEFT JOIN tdr_engagements e ON e.id=t.engagement_id WHERE t.id=?""", (response["target_id"],)) \
        if response["target_id"] else None
    return form


def _stored_value(answer):
    if answer["values_json"]:
        return json.loads(answer["values_json"])
    if answer["value_number"] is not None:
        number = answer["value_number"]
        return int(number) if float(number).is_integer() else number
    return answer["value_text"]


def check_value(question, value):
    """Yanıtı soru türüne göre denetler; (metin, sayı, liste, puan) döner."""
    kind, options = question["kind"], question.get("options") or []
    scores = {o["value"]: o.get("score") for o in options}
    if kind in ("scale_1_5", "nps_0_10"):
        low, high = (1, 5) if kind == "scale_1_5" else (0, 10)
        if isinstance(value, bool) or type(value) is not int or not low <= value <= high:
            raise crud.Invalid(f"'{question['text']}': {low}–{high} arasında bir değer seçin")
        return None, value, None, (value - 1) * 25 if kind == "scale_1_5" else value * 10
    if kind in ("yes_no", "single_choice"):
        if value not in scores:
            raise crud.Invalid(f"'{question['text']}': seçeneklerden birini seçin")
        return value, None, None, scores[value]
    if kind == "multi_choice":
        if not isinstance(value, list) or not value or any(v not in scores for v in value) or len(set(value)) != len(value):
            raise crud.Invalid(f"'{question['text']}': seçeneklerden en az birini seçin")
        points = [scores[v] for v in value if scores[v] is not None]
        return None, None, value, (sum(points) / len(points)) if points else None
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise crud.Invalid(f"'{question['text']}': sayı girin")
        return None, value, None, None
    if kind == "date":
        try:
            if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise crud.Invalid(f"'{question['text']}': tarih YYYY-AA-GG olmalı") from None
        return value, None, None, None
    if not isinstance(value, str) or len(value) > TEXT_LIMIT:
        raise crud.Invalid(f"'{question['text']}': en fazla {TEXT_LIMIT} karakter")
    return value, None, None, None


def save_answers(c):
    """Taslağı kaydeder; `submit: true` ile gönderir. Gönderilen yanıt değiştirilemez."""
    response, campaign = _own_response(c)
    if response["status"] == "submitted":
        raise crud.Conflict("Gönderilmiş yanıt değiştirilemez")
    if not _is_open(campaign):
        raise crud.Conflict("Anket yanıtlamaya kapandı")
    form = structure(c.db, campaign["template_id"])
    by_id = {q["id"]: q for q in form["questions"]}
    items = c.body.get("answers", [])
    if not isinstance(items, list):
        raise crud.Invalid("answers liste olmalı")
    for item in items:
        if not isinstance(item, dict) or item.get("question_id") not in by_id:
            raise crud.Invalid("Yanıt bu ankete ait olmayan bir soruya işaret ediyor")
        question, value = by_id[item["question_id"]], item.get("value")
        if value in (None, "", []):
            c.db.execute("DELETE FROM tdr_survey_answers WHERE response_id=? AND question_id=?",
                         (response["id"], question["id"]))
            continue
        text, number, values, score = check_value(question, value)
        c.db.execute("""INSERT INTO tdr_survey_answers (response_id, question_id, value_text, value_number, values_json,
            score) VALUES (?,?,?,?,?,?) ON CONFLICT(response_id, question_id) DO UPDATE SET
            value_text=excluded.value_text, value_number=excluded.value_number, values_json=excluded.values_json,
            score=excluded.score""", (response["id"], question["id"], text, number,
                                      json.dumps(values, ensure_ascii=False) if values is not None else None, score))
    saved = {a["question_id"]: a for a in rows(c.db, "SELECT * FROM tdr_survey_answers WHERE response_id=?",
                                                (response["id"],))}
    values = {by_id[q]["code"]: _stored_value(a) for q, a in saved.items()}
    shown = [q for q in form["questions"] if visible(q, values)]
    missing = [q for q in shown if q["required"] and q["id"] not in saved]
    result = {"response_id": response["id"], "status": "draft", "answered": len(saved),
              "required_missing": [q["id"] for q in missing], "visible": [q["id"] for q in shown]}
    if not c.body.get("submit"):
        return result
    if missing:
        raise crud.Invalid("Zorunlu soruları yanıtlayın: " + "; ".join(q["text"] for q in missing[:5]))
    hidden = [q["id"] for q in form["questions"] if q not in shown and q["id"] in saved]
    for question_id in hidden:             # koşulu sağlanmayan sorunun yanıtı tutulmaz
        c.db.execute("DELETE FROM tdr_survey_answers WHERE response_id=? AND question_id=?",
                     (response["id"], question_id))
    weighted = [(by_id[q]["weight"], a["score"]) for q, a in saved.items()
                if q not in hidden and a["score"] is not None and by_id[q]["weight"]]
    total_weight = sum(w for w, _ in weighted)
    score = round(sum(w * s for w, s in weighted) / total_weight, 1) if total_weight else None
    now = utcnow()
    c.db.execute("UPDATE tdr_survey_responses SET status='submitted', score=?, submitted_at=? WHERE id=?",
                 (score, now, response["id"]))
    if campaign["audience"] == "invited":
        c.db.execute("UPDATE tdr_survey_invitations SET status='answered', answered_at=? WHERE campaign_id=? AND "
                     "respondent=? AND COALESCE(target_id, 0)=?",
                     (now, campaign["id"], c.principal.username, response["target_id"] or 0))
    audit.log(c.db, c.principal, "ANSWER", CAMPAIGNS.name, campaign["id"],
              {"anonymous": bool(campaign["anonymous"])})
    return {**result, "status": "submitted", "score": score, "required_missing": []}


# ------------------------------------------------------------------ sonuçlar

def _can_see_results(c, campaign):
    if c.principal.role == "MACHINE":
        raise crud.Forbidden("MCP anahtarı anket sonuçlarını okuyamaz")
    if not (c.principal.can("manage") or c.principal.role == "AUDITOR" or campaign["owner"] == c.principal.username):
        raise crud.Forbidden("Anket sonuçlarını görme yetkiniz yok")


def _question_stats(question, answers, anonymous):
    kind = question["kind"]
    values = [_stored_value(a) for a in answers]
    scores = [a["score"] for a in answers if a["score"] is not None]
    stat = {"id": question["id"], "code": question["code"], "text": question["text"], "kind": kind,
            "section_id": question["section_id"], "responses": len(answers),
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "risk_category": question["risk_category"], "risk_threshold": question["risk_threshold"]}
    if kind in ("scale_1_5", "nps_0_10", "number"):
        numbers = [v for v in values if isinstance(v, (int, float))]
        stat["average"] = round(sum(numbers) / len(numbers), 2) if numbers else None
        if kind != "number":
            low, high = (1, 5) if kind == "scale_1_5" else (0, 10)
            stat["distribution"] = [{"value": v, "count": numbers.count(v)} for v in range(low, high + 1)]
        else:
            stat["min"], stat["max"] = (min(numbers), max(numbers)) if numbers else (None, None)
    if kind == "nps_0_10" and values:
        promoters = sum(1 for v in values if v >= 9)
        detractors = sum(1 for v in values if v <= 6)
        stat["nps"] = {"promoters": promoters, "passives": len(values) - promoters - detractors,
                       "detractors": detractors, "score": round(100 * (promoters - detractors) / len(values))}
    if kind in ("yes_no", "single_choice", "multi_choice"):
        flat = [v for value in values for v in (value if isinstance(value, list) else [value])]
        stat["distribution"] = [{"value": o["value"], "label": o["label"], "count": flat.count(o["value"])}
                                for o in question.get("options") or []]
    if kind in ("text", "date"):
        stat["answers"] = [v for v in values if v][:200]
    return stat


def results(c):
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    _can_see_results(c, campaign)
    form = structure(c.db, campaign["template_id"])
    submitted = rows(c.db, "SELECT * FROM tdr_survey_responses WHERE campaign_id=? AND status='submitted'",
                     (campaign["id"],))
    invited = one(c.db, """SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN status='answered' THEN 1 ELSE 0 END),0)
        AS answered FROM tdr_survey_invitations WHERE campaign_id=?""", (campaign["id"],))
    base = {"campaign": {k: v for k, v in campaign.items() if k != "salt"},
            "template": {k: form[k] for k in ("id", "code", "name", "purpose", "version")},
            "invited": invited["total"], "submitted": len(submitted),
            "response_rate": round(100 * invited["answered"] / invited["total"], 1) if invited["total"] else None}
    if campaign["anonymous"] and len(submitted) < campaign["min_responses"]:
        return {**base, "hidden": True,
                "message": f"Anonimliği korumak için en az {campaign['min_responses']} yanıt gerekli"}
    ids = [r["id"] for r in submitted]
    answers = rows(c.db, "SELECT a.*, r.target_id FROM tdr_survey_answers a JOIN tdr_survey_responses r "
                         "ON r.id=a.response_id WHERE r.campaign_id=? AND r.status='submitted'", (campaign["id"],))
    scores = [r["score"] for r in submitted if r["score"] is not None]
    questions = [_question_stats(q, [a for a in answers if a["question_id"] == q["id"]], campaign["anonymous"])
                 for q in form["questions"]]
    sections = []
    for section in form["sections"]:
        own = [q["average_score"] for q in questions if q["section_id"] == section["id"] and q["average_score"] is not None]
        sections.append({"id": section["id"], "title": section["title"],
                         "average_score": round(sum(own) / len(own), 1) if own else None})
    targets, signals = [], []
    for target in rows(c.db, """SELECT t.id, t.supplier_id, t.engagement_id, s.name AS supplier_name, s.code AS
            supplier_code, s.tier, e.code AS engagement_code FROM tdr_survey_targets t JOIN tdr_suppliers s
            ON s.id=t.supplier_id LEFT JOIN tdr_engagements e ON e.id=t.engagement_id WHERE t.campaign_id=?
            ORDER BY s.name""", (campaign["id"],)):
        own = [r for r in submitted if r["target_id"] == target["id"]]
        own_scores = [r["score"] for r in own if r["score"] is not None]
        target.update({"responses": len(own),
                       "average_score": round(sum(own_scores) / len(own_scores), 1) if own_scores else None})
        targets.append(target)
        for q in form["questions"]:
            if q["risk_category"] is None or q["risk_threshold"] is None:
                continue
            points = [a["score"] for a in answers if a["question_id"] == q["id"] and a["target_id"] == target["id"]
                      and a["score"] is not None]
            if points and sum(points) / len(points) < q["risk_threshold"]:
                ref = f"survey:{campaign['code']}:{q['code']}:{target['supplier_id']}"
                existing = one(c.db, "SELECT id, code FROM tdr_supplier_risks WHERE origin_ref=?", (ref,)) \
                    if c.app.enabled("risks") else None
                signals.append({"target_id": target["id"], "supplier_id": target["supplier_id"],
                                "supplier_name": target["supplier_name"], "question_id": q["id"],
                                "question": q["text"], "category": q["risk_category"],
                                "average_score": round(sum(points) / len(points), 1), "threshold": q["risk_threshold"],
                                "origin_ref": ref, "risk": existing})
    if campaign["subject"] == "none" and not c.app.enabled("risks"):
        signals = []
    return {**base, "hidden": False, "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "questions": questions, "sections": sections, "targets": targets, "risk_signals": signals,
            "response_ids": ids if not campaign["anonymous"] else None}


def apply_signals(c):
    """Risk sinyallerinden tedarikçi riski açar. Aynı sinyal ikinci kez risk açmaz (`origin_ref`)."""
    if not c.app.enabled("risks"):
        raise crud.NotFound("Risk modülü kapalı")
    risks = RESOURCES["supplier_risks"]
    authz.require_human(c.principal)
    authz.check(c.principal, risks, "write")
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    _can_see_results(c, campaign)
    wanted = c.body.get("origin_refs")
    if not isinstance(wanted, list) or not wanted:
        raise crud.Invalid("origin_refs listesi gerekli")
    available = {s["origin_ref"]: s for s in results(c).get("risk_signals", [])}
    created = []
    for ref in wanted:
        signal = available.get(ref)
        if signal is None:
            raise crud.Invalid("Sinyal bulunamadı veya artık eşiğin altında değil")
        if signal["risk"]:
            continue
        count = one(c.db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks")["n"] + 1
        risk_id = crud.insert(c.db, risks, {
            "code": f"ANK-{campaign['code']}-{count:04d}", "title": f"Anket sinyali: {signal['question']}"[:300],
            "supplier_id": signal["supplier_id"], "category": signal["category"], "owner": c.principal.username,
            "appetite": int(c.body.get("appetite", 9)), "origin_ref": ref,
            "description": (f"'{campaign['name']}' anketinde ortalama puan {signal['average_score']}, "
                            f"eşik {signal['threshold']}."),
            "cause": "Anket yanıtlarında tedarikçi bu konuda eşiğin altında değerlendirildi",
            "risk_event": signal["question"], "consequence": "Değerlendirilmeli: hizmet, uyum veya süreklilik etkisi"},
            c.principal)
        audit.log(c.db, c.principal, "CREATE", risks.name, risk_id, {"origin_ref": ref})
        created.append(risk_id)
    return {"created": created}


def supplier_surveys(c):
    """Tedarikçi 360 için: tedarikçinin değerlendirildiği kampanyalar ve puanları."""
    authz.check(c.principal, RESOURCES["suppliers"], "read")
    crud.get(c.db, RESOURCES["suppliers"], c.params["id"])
    found = rows(c.db, """SELECT k.id AS campaign_id, k.code, k.name, k.status, k.anonymous, k.min_responses,
        k.period_start, k.period_end, tp.purpose, t.id AS target_id,
        (SELECT COUNT(*) FROM tdr_survey_responses r WHERE r.target_id=t.id AND r.status='submitted') AS responses,
        (SELECT AVG(r.score) FROM tdr_survey_responses r WHERE r.target_id=t.id AND r.status='submitted') AS score
        FROM tdr_survey_targets t JOIN tdr_survey_campaigns k ON k.id=t.campaign_id
        JOIN tdr_survey_templates tp ON tp.id=k.template_id WHERE t.supplier_id=? ORDER BY k.id DESC""",
                 (c.params["id"],))
    for item in found:
        if item["anonymous"] and item["responses"] < item["min_responses"]:
            item["score"] = None
        elif item["score"] is not None:
            item["score"] = round(item["score"], 1)
    return found


def register(app):
    T, K = API + "/survey_templates/{id}", API + "/survey_campaigns/{id}"
    app.route("GET", T + "/structure", template_structure)
    app.route("POST", T + "/publish", publish)
    app.route("POST", T + "/retire", retire)
    app.route("POST", T + "/copy", copy_template)
    app.route("POST", T + "/reorder", reorder)
    app.route("GET", K + "/context", campaign_context)
    app.route("POST", K + "/targets", add_targets)
    app.route("POST", K + "/invite", invite)
    app.route("POST", K + "/open", open_campaign)
    app.route("POST", K + "/close", close_campaign)
    app.route("GET", K + "/results", results)
    app.route("POST", K + "/risk-signals", apply_signals)
    app.route("POST", K + "/responses", start_response)
    app.route("GET", API + "/my/surveys", my_surveys)
    app.route("GET", API + "/survey_responses/{id}/form", response_form)
    app.route("POST", API + "/survey_responses/{id}/answers", save_answers)
    app.route("GET", API + "/suppliers/{id}/surveys", supplier_surveys)


# ------------------------------------------------------------------ başlangıç şablonları (öneri; düzenlenebilir)

STARTERS = [
    ("MEMNUNIYET", "Tedarikçi Memnuniyet Anketi", "satisfaction",
     "Birimlerin tedarikçiden aldığı hizmet ve ürünlere ilişkin memnuniyeti.",
     [("Hizmet kalitesi", [
         ("Aldığınız ürün veya hizmetin kalitesinden ne kadar memnunsunuz?", "scale_1_5", 2, None),
         ("Taahhüt edilen sürelere uyum", "scale_1_5", 2, ("performance", 50)),
         ("Sorunların çözüm hızı", "scale_1_5", 1, None)]),
      ("İlişki", [
         ("İletişim ve erişilebilirlik", "scale_1_5", 1, None),
         ("Bu tedarikçiyi başka bir birime tavsiye eder misiniz?", "nps_0_10", 1, None),
         ("Geliştirilmesini istediğiniz konular", "text", 0, None)])]),
    ("RISK-DEG", "Tedarikçi Risk Değerlendirme Anketi", "risk",
     "Tedarikçiyle çalışan birimlerin süreklilik, güvenlik ve uyum gözlemleri.",
     [("Süreklilik", [
         ("Tedarikçinin hizmeti kesintisiz sürdürebileceğine güveniyor musunuz?", "scale_1_5", 2, ("continuity", 50)),
         ("Bu hizmet için alternatif tedarikçi var mı?", "yes_no", 1, ("concentration", 50))]),
      ("Bilgi güvenliği ve uyum", [
         ("Tedarikçi bilgi güvenliği gereksinimlerine uyuyor mu?", "scale_1_5", 2, ("security", 50)),
         ("Son 12 ayda tedarikçi kaynaklı güvenlik olayı yaşandı mı?", "yes_no_negative", 2, ("security", 50)),
         ("Sözleşme ve mevzuat yükümlülüklerine uyum", "scale_1_5", 1, ("compliance", 50))])]),
]


def seed(db):
    for code, name, purpose, description, sections in STARTERS:
        if one(db, "SELECT 1 AS x FROM tdr_survey_templates WHERE code=?", (code,)):
            continue
        template_id = db.execute("INSERT INTO tdr_survey_templates (code, name, purpose, description, status, version, "
                                 "created_at) VALUES (?,?,?,?,'draft',1,?)",
                                 (code, name, purpose, description, utcnow())).lastrowid
        number = 0
        for s_position, (title, questions) in enumerate(sections, start=1):
            section_id = db.execute("INSERT INTO tdr_survey_sections (template_id, position, title) VALUES (?,?,?)",
                                    (template_id, s_position, title)).lastrowid
            for text, kind, weight, risk in questions:
                number += 1
                options = None
                if kind == "yes_no":
                    options = YES_NO
                if kind == "yes_no_negative":       # olumsuz soru: "Evet" düşük puan
                    kind, options = "yes_no", [{"value": "yes", "label": "Evet", "score": 0},
                                               {"value": "no", "label": "Hayır", "score": 100}]
                db.execute("INSERT INTO tdr_survey_questions (template_id, section_id, position, code, text, kind, "
                           "required, weight, options_json, risk_category, risk_threshold) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (template_id, section_id, number, f"S{number}", text, kind, 0 if kind == "text" else 1,
                            weight, json.dumps(options, ensure_ascii=False) if options else None,
                            risk[0] if risk else None, risk[1] if risk else None))
