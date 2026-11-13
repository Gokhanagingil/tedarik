"""Memnuniyet anketleri: şablon -> soru -> kampanya -> davet -> yanıt. Yanıtlayanlar iç kullanıcılardır."""
from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API
from ..schema import Resource, fk

M = "surveys"
RANGES = {"scale_1_5": (1, 5), "nps_0_10": (0, 10), "yes_no": (0, 1)}

Resource("survey_templates", "Anket Şablonları", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "description": "TEXT",
    "active": "INTEGER NOT NULL DEFAULT 1"}, module=M)

Resource("survey_questions", "Anket Soruları", {
    "template_id": fk("survey_templates"), "position": "INTEGER NOT NULL DEFAULT 1", "text": "TEXT NOT NULL",
    "kind": "TEXT NOT NULL DEFAULT 'scale_1_5'", "required": "INTEGER NOT NULL DEFAULT 1"},
    module=M, search=("text",), enums={"kind": ("scale_1_5", "nps_0_10", "yes_no", "text")})

CAMPAIGNS = Resource("survey_campaigns", "Anket Kampanyaları", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "template_id": fk("survey_templates"),
    "supplier_id": fk("suppliers"), "engagement_id": fk("engagements", False), "period_start": "TEXT",
    "period_end": "TEXT", "status": "TEXT NOT NULL DEFAULT 'draft'", "opened_at": "TEXT", "closed_at": "TEXT"},
    module=M, readonly=("status", "opened_at", "closed_at"), enums={"status": ("draft", "open", "closed")})

INVITES = Resource("survey_invitations", "Anket Davetleri", {
    "campaign_id": fk("survey_campaigns"), "respondent": "TEXT NOT NULL", "org_unit_id": fk("org_units", False),
    "status": "TEXT NOT NULL DEFAULT 'pending'", "answered_at": "TEXT"},
    module=M, unique=(("campaign_id", "respondent"),), search=("respondent",),
    readonly=("status", "answered_at"), enums={"status": ("pending", "answered")})

ANSWERS = Resource("survey_answers", "Anket Yanıtları", {
    "invitation_id": fk("survey_invitations"), "question_id": fk("survey_questions"), "score": "INTEGER",
    "text_value": "TEXT"}, module=M, write="write", api=("list",), search=(),
    unique=(("invitation_id", "question_id"),))


def _set_status(c, status, stamp, allowed_from):
    authz.check(c.principal, CAMPAIGNS, "write")
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    if campaign["status"] != allowed_from:
        raise crud.Conflict(f"Kampanya '{campaign['status']}' durumunda; bu işlem yapılamaz")
    c.db.execute(f"UPDATE tdr_survey_campaigns SET status=?, {stamp}=? WHERE id=?",
                 (status, utcnow(), campaign["id"]))
    audit.log(c.db, c.principal, status.upper(), "survey_campaigns", campaign["id"])
    return {"id": campaign["id"], "status": status}


def submit(c):
    """Davet edilen kişi (veya yönetici) yanıtları tek seferde gönderir; zorunlu sorular denetlenir."""
    authz.check(c.principal, ANSWERS, "write")
    invite = crud.get(c.db, INVITES, c.params["id"])
    if invite["respondent"] != c.principal.username and not c.principal.can("manage"):
        raise crud.Forbidden("Bu davet size ait değil")
    campaign = crud.get(c.db, CAMPAIGNS, invite["campaign_id"])
    if campaign["status"] != "open":
        raise crud.Conflict("Anket açık değil")
    if invite["status"] == "answered":
        raise crud.Conflict("Bu davet zaten yanıtlandı")
    questions = {q["id"]: q for q in rows(c.db, "SELECT * FROM tdr_survey_questions WHERE template_id=?",
                                          (campaign["template_id"],))}
    answers = c.body["answers"]
    if not isinstance(answers, list):
        raise crud.Invalid("answers liste olmalı")
    seen = set()
    for answer in answers:
        question = questions.get(answer.get("question_id")) if isinstance(answer, dict) else None
        if not question:
            raise crud.Invalid("Yanıt bu ankete ait olmayan bir soruya işaret ediyor")
        low_high, score = RANGES.get(question["kind"]), answer.get("score")
        if low_high and (type(score) is not int or not low_high[0] <= score <= low_high[1]):
            raise crud.Invalid(f"Soru {question['id']}: puan {low_high[0]}-{low_high[1]} aralığında olmalı")
        crud.insert(c.db, ANSWERS, {"invitation_id": invite["id"], "question_id": question["id"],
                                    "score": score if low_high else None, "text_value": answer.get("text_value")})
        seen.add(question["id"])
    if any(q["required"] and q["id"] not in seen for q in questions.values()):
        raise crud.Invalid("Zorunlu soruların tamamı yanıtlanmalı")
    c.db.execute("UPDATE tdr_survey_invitations SET status='answered', answered_at=? WHERE id=?",
                 (utcnow(), invite["id"]))
    audit.log(c.db, c.principal, "ANSWER", "survey_invitations", invite["id"], {"answers": len(seen)})
    return 201, {"invitation_id": invite["id"], "answers": len(seen)}


def results(c):
    """Soru bazında ortalama, yanıt oranı ve 0-100 ölçeğinde genel memnuniyet (1-5 ölçekli sorulardan)."""
    authz.check(c.principal, CAMPAIGNS, "read")
    campaign = crud.get(c.db, CAMPAIGNS, c.params["id"])
    invited = one(c.db, "SELECT COUNT(*) AS total, COALESCE(SUM(status='answered'), 0) AS answered "
                        "FROM tdr_survey_invitations WHERE campaign_id=?", (campaign["id"],))
    questions = rows(c.db, """SELECT q.id, q.position, q.text, q.kind, COUNT(a.id) AS responses,
        ROUND(AVG(a.score), 2) AS average FROM tdr_survey_questions q
        LEFT JOIN tdr_survey_answers a ON a.question_id=q.id AND a.invitation_id IN
          (SELECT id FROM tdr_survey_invitations WHERE campaign_id=?)
        WHERE q.template_id=? GROUP BY q.id ORDER BY q.position, q.id""", (campaign["id"], campaign["template_id"]))
    scale = [q["average"] for q in questions if q["kind"] == "scale_1_5" and q["average"] is not None]
    satisfaction = round((sum(scale) / len(scale) - 1) / 4 * 100, 1) if scale else None
    rate = round(100 * invited["answered"] / invited["total"], 1) if invited["total"] else None
    return {"campaign": campaign, "invited": invited["total"], "answered": invited["answered"],
            "response_rate": rate, "satisfaction": satisfaction, "questions": questions}


def register(app):
    app.route("POST", API + "/survey_campaigns/{id}/open", lambda c: _set_status(c, "open", "opened_at", "draft"))
    app.route("POST", API + "/survey_campaigns/{id}/close", lambda c: _set_status(c, "closed", "closed_at", "open"))
    app.route("POST", API + "/survey_invitations/{id}/answers", submit)
    app.route("GET", API + "/survey_campaigns/{id}/results", results)
