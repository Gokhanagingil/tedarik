"""Erişim gözden geçirme kampanyaları ve ServiceNow görev eşlemesi — grc modülünün parçası (K-027).

Erişim gözden geçirme: bir sistemin hesap–yetki listesi (dosyadan, MCP'den veya portalın kendi kullanıcılarından)
gözden geçirene atanır; her satır için "kalsın / kaldırılsın / değiştirilsin" kararı verilir (kaldırma gerekçe ister);
kaldırılan erişimin uygulandığı işaretlenir. Tüm kararlar verilince kampanya tamamlanır ve sonuç dosyası kanıt olarak
ilgili kontrole bağlanır (ör. "Yönetici hesaplarına erişim periyodik onayı"). Veri yönetişimi modülüyle genişletilecek.

ServiceNow görev eşlemesi (isteğe bağlı): `servicenow.tasks` parametresinde açıksa düzeltici faaliyet (DÖF) ServiceNow'da
görev olarak açılır, numarası ve durumu DÖF'te görünür. Portal CMDB'ye hiçbir zaman yazmaz; yazma yalnızca bu
parametreyle ve yalnızca görev tablosuna yapılır.
"""
import csv
import io
import json

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY
from ..schema import RESOURCES, Resource, fk
from . import reminder  # noqa: F401
from .core import policy
from .grc import _date, store_file

M = "grc"

REVIEWS = Resource("access_reviews", "Erişim Gözden Geçirmeleri", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "system": "TEXT NOT NULL", "control_id": fk("controls", False),
    "company_id": fk("companies", False), "reviewer": "TEXT NOT NULL", "due_date": "DATE NOT NULL",
    "status": "TEXT NOT NULL DEFAULT 'draft'", "source": "TEXT NOT NULL DEFAULT 'import'", "instructions": "TEXT",
    "launched_at": "TIMESTAMP", "completed_at": "TIMESTAMP", "evidence_id": fk("evidence", False), "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="ERG", code_yearly=True, search=("code", "title", "system"), write_roles={"ADMIN", "AUDITOR"},
    readonly=("status", "launched_at", "completed_at", "evidence_id", "created_by"),
    enums={"status": ("draft", "open", "completed"), "source": ("import", "portal_users", "mcp")})
ITEMS = Resource("access_review_items", "Erişim Gözden Geçirme Kalemleri", {
    "review_id": fk("access_reviews"), "account": "TEXT NOT NULL", "person": "TEXT", "entitlement": "TEXT NOT NULL",
    "last_login": "TEXT", "decision": "TEXT NOT NULL DEFAULT 'pending'", "comment": "TEXT", "decided_by": "TEXT",
    "decided_at": "TIMESTAMP", "remediated": "INTEGER NOT NULL DEFAULT 0", "remediated_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list", "get"), search=("account", "person", "entitlement"), write_roles={"ADMIN", "AUDITOR"},
    unique=(("review_id", "account", "entitlement"),),
    enums={"decision": ("pending", "keep", "revoke", "modify")})


def _review_rules(db, data, current, principal):
    _date({**(current or {}), **data}.get("due_date"), "Son tarih")
    if current is None:
        data["created_by"] = principal.username if principal else "system"
        data["status"] = "draft"
    elif current["status"] != "draft" and set(data) - {"due_date", "instructions", "updated_at"}:
        raise crud.Conflict("Başlamış gözden geçirmede yalnızca son tarih ve açıklama değişir")


REVIEWS.before_save = _review_rules


def load_items(c):
    """{rows: [{account, person?, entitlement, last_login?}]} veya {filename, content_base64} (CSV/XLSX) veya
    {source: "portal_users"}: portalın kendi kullanıcıları ve rolleri."""
    authz.require_human(c.principal)
    review = crud.get(c.db, REVIEWS, c.params["id"])
    authz.check(c.principal, REVIEWS, "write")
    if review["status"] != "draft":
        raise crud.Conflict("Kalemler yalnızca taslakta yüklenir")
    if c.body.get("source") == "portal_users":
        items = [{"account": r["username"], "person": r["display_name"], "entitlement": r["role"] or "rol yok",
                  "last_login": str(r["last_login_at"] or "")[:10]}
                 for r in rows(c.db, """SELECT u.username, u.display_name, u.last_login_at, r.role FROM users u
                     LEFT JOIN tdr_user_roles r ON r.user_id=u.id WHERE u.is_active=1 ORDER BY u.username""")]
        c.db.execute("UPDATE tdr_access_reviews SET source='portal_users' WHERE id=?", (review["id"],))
    elif c.body.get("filename"):
        from .transfer import _decode, read_table
        filename, raw = _decode(c)
        headers, records = read_table(filename, raw)
        keys = {"hesap": "account", "account": "account", "kullanici": "account", "kisi": "person", "ad soyad": "person",
                "person": "person", "yetki": "entitlement", "rol": "entitlement", "entitlement": "entitlement",
                "son giris": "last_login", "last login": "last_login"}
        from ..db import fold
        mapping = {h: keys[" ".join(fold(h).split())] for h in headers if " ".join(fold(h).split()) in keys}
        items = [{mapping[h]: str(v).strip() for h, v in r.items() if h in mapping} for r in records]
    else:
        items = c.body.get("rows")
    if not isinstance(items, list) or not items or len(items) > 20000:
        raise crud.Invalid("1–20000 satır gerekli (hesap ve yetki sütunları)")
    now, added = utcnow(), 0
    for item in items:
        account, entitlement = str(item.get("account") or "").strip(), str(item.get("entitlement") or "").strip()
        if not account or not entitlement:
            raise crud.Invalid("Her satırda hesap ve yetki gerekli")
        if one(c.db, "SELECT id FROM tdr_access_review_items WHERE review_id=? AND account=? AND entitlement=?",
               (review["id"], account, entitlement)):
            continue
        c.db.execute("INSERT INTO tdr_access_review_items (review_id, account, person, entitlement, last_login, decision, "
                     "created_at) VALUES (?,?,?,?,?,?,?)", (review["id"], account[:200], (item.get("person") or None),
                                                             entitlement[:300], item.get("last_login") or None,
                                                             "pending", now))
        added += 1
    audit.log(c.db, c.principal, "IMPORT", "access_reviews", review["id"], {"added": added})
    return context_data(c.db, review["id"])


def launch(c):
    authz.require_human(c.principal)
    review = crud.get(c.db, REVIEWS, c.params["id"])
    authz.check(c.principal, REVIEWS, "write")
    if review["status"] != "draft":
        raise crud.Conflict("Gözden geçirme zaten başlamış")
    if not one(c.db, "SELECT id FROM tdr_access_review_items WHERE review_id=? LIMIT 1", (review["id"],)):
        raise crud.Invalid("Önce hesap–yetki listesini yükleyin")
    c.db.execute("UPDATE tdr_access_reviews SET status='open', launched_at=?, updated_at=? WHERE id=?",
                 (utcnow(), utcnow(), review["id"]))
    audit.log(c.db, c.principal, "LAUNCH", "access_reviews", review["id"], None)
    from .. import notify
    notify.enqueue(c.db, "access_review.assigned", f"Erişim gözden geçirmesi: {review['title']}",
                   f"{review['system']} erişimlerini {review['due_date']} tarihine kadar gözden geçirin.",
                   users=[review["reviewer"]], link=f"#/r/access_reviews/{review['id']}", object_type="access_reviews",
                   object_id=review["id"])
    return context_data(c.db, review["id"])


def decide(c):
    authz.require_human(c.principal)
    item = crud.get(c.db, ITEMS, c.params["id"])
    review = crud.get(c.db, REVIEWS, item["review_id"])
    if c.principal.username != review["reviewer"] and c.principal.role != "ADMIN":
        raise crud.Forbidden("Kararı atanan gözden geçiren verir")
    if review["status"] != "open":
        raise crud.Conflict("Gözden geçirme açık değil")
    decision, comment = c.body.get("decision"), (c.body.get("comment") or "").strip()
    if decision not in ("keep", "revoke", "modify"):
        raise crud.Invalid("Karar: kalsın, kaldırılsın veya değiştirilsin")
    if decision in ("revoke", "modify") and not comment:
        raise crud.Invalid("Kaldırma veya değişiklik için açıklama gerekli")
    if item["account"] == c.principal.username:
        raise crud.Forbidden("Kendi erişiminiz hakkında karar veremezsiniz")
    c.db.execute("UPDATE tdr_access_review_items SET decision=?, comment=?, decided_by=?, decided_at=? WHERE id=?",
                 (decision, comment or None, c.principal.username, utcnow(), item["id"]))
    audit.log(c.db, c.principal, "DECIDE", "access_review_items", item["id"], {"decision": decision, "comment": comment})
    return crud.get(c.db, ITEMS, item["id"])


def bulk_keep(c):
    """Seçilen satırlara "kalsın" kararı (gözden geçiren her satırı görmüş olmalı; arayüz satırları listeler)."""
    authz.require_human(c.principal)
    review = crud.get(c.db, REVIEWS, c.params["id"])
    if c.principal.username != review["reviewer"] and c.principal.role != "ADMIN":
        raise crud.Forbidden("Kararı atanan gözden geçiren verir")
    ids = c.body.get("item_ids")
    if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(ids) > 5000:
        raise crud.Invalid("item_ids listesi gerekli")
    n = 0
    for item_id in ids:
        item = one(c.db, "SELECT * FROM tdr_access_review_items WHERE id=? AND review_id=?", (item_id, review["id"]))
        if item and item["decision"] == "pending" and item["account"] != c.principal.username:
            c.db.execute("UPDATE tdr_access_review_items SET decision='keep', decided_by=?, decided_at=? WHERE id=?",
                         (c.principal.username, utcnow(), item_id))
            n += 1
    audit.log(c.db, c.principal, "DECIDE", "access_reviews", review["id"], {"keep": n})
    return context_data(c.db, review["id"])


def remediated(c):
    authz.require_human(c.principal)
    item = crud.get(c.db, ITEMS, c.params["id"])
    authz.check(c.principal, REVIEWS, "write")
    if item["decision"] not in ("revoke", "modify"):
        raise crud.Invalid("Yalnızca kaldırma/değişiklik kararı uygulanır")
    c.db.execute("UPDATE tdr_access_review_items SET remediated=1, remediated_at=? WHERE id=?", (utcnow(), item["id"]))
    audit.log(c.db, c.principal, "REMEDIATE", "access_review_items", item["id"], None)
    return crud.get(c.db, ITEMS, item["id"])


def complete(c):
    authz.require_human(c.principal)
    review = crud.get(c.db, REVIEWS, c.params["id"])
    if c.principal.username != review["reviewer"] and c.principal.role != "ADMIN":
        raise crud.Forbidden("Gözden geçirmeyi atanan kişi tamamlar")
    if review["status"] != "open":
        raise crud.Conflict("Gözden geçirme açık değil")
    items = rows(c.db, "SELECT * FROM tdr_access_review_items WHERE review_id=? ORDER BY account", (review["id"],))
    pending = sum(1 for i in items if i["decision"] == "pending")
    if pending:
        raise crud.Conflict(f"{pending} satırda karar bekleniyor")
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["Hesap", "Kişi", "Yetki", "Son giriş", "Karar", "Açıklama", "Karar veren", "Karar zamanı", "Uygulandı"])
    labels = {"keep": "Kalsın", "revoke": "Kaldırılsın", "modify": "Değiştirilsin"}
    for i in items:
        writer.writerow([i["account"], i["person"] or "", i["entitlement"], i["last_login"] or "", labels[i["decision"]],
                         i["comment"] or "", i["decided_by"], i["decided_at"], "Evet" if i["remediated"] else ""])
    revoke = sum(1 for i in items if i["decision"] == "revoke")
    evidence_id = crud.insert(c.db, RESOURCES["evidence"], {
        "title": f"Erişim gözden geçirmesi — {review['system']} ({review['code']})",
        "description": f"{len(items)} erişim gözden geçirildi; {revoke} kaldırma, "
                       f"{sum(1 for i in items if i['decision'] == 'modify')} değişiklik kararı.",
        "source": "system", "confidentiality": "confidential", "period_end": utcnow()[:10]}, c.principal)
    store_file(c.db, evidence_id, f"erisim-gozden-gecirme-{review['code']}.csv",
               ("﻿" + buffer.getvalue()).encode("utf-8"), c.principal.username)
    if review["control_id"]:
        c.db.execute("INSERT INTO tdr_evidence_controls (evidence_id, control_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                     (evidence_id, review["control_id"]))
    c.db.execute("UPDATE tdr_access_reviews SET status='completed', completed_at=?, evidence_id=?, updated_at=? WHERE id=?",
                 (utcnow(), evidence_id, utcnow(), review["id"]))
    audit.log(c.db, c.principal, "COMPLETE", "access_reviews", review["id"], {"items": len(items), "revoke": revoke})
    return context_data(c.db, review["id"])


def context_data(db, review_id):
    item = crud.get(db, REVIEWS, review_id)
    item["items"] = rows(db, "SELECT * FROM tdr_access_review_items WHERE review_id=? ORDER BY decision DESC, account",
                         (review_id,))
    counts = {}
    for i in item["items"]:
        counts[i["decision"]] = counts.get(i["decision"], 0) + 1
    item["counts"] = counts
    item["open_remediation"] = sum(1 for i in item["items"] if i["decision"] in ("revoke", "modify") and not i["remediated"])
    return item


def context(c):
    authz.check(c.principal, REVIEWS, "read")
    return context_data(c.db, c.params["id"])


# ------------------------------------------------------------------ ServiceNow görev eşlemesi

TASK_DEFAULTS = {"enabled": False, "table": "task", "assignment_group": "", "short_description_prefix": "[GRC]"}


def task_settings(db):
    return {**TASK_DEFAULTS, **(policy(db, "servicenow.tasks", {}) or {})}


def _client(db, app):
    from .cmdb import effective, servicenow_client
    return servicenow_client(effective(db, app))


def push_action(c):
    """DÖF'ü ServiceNow'da görev olarak açar (isteğe bağlı, `servicenow.tasks.enabled`)."""
    authz.require_human(c.principal)
    actions = RESOURCES["grc_actions"]
    authz.check(c.principal, actions, "write")
    action = crud.get(c.db, actions, c.params["id"])
    if not c.app.enabled("cmdb"):
        raise crud.Conflict("ServiceNow bağlantısı için CMDB modülü açık olmalı")
    settings = task_settings(c.db)
    if not settings["enabled"]:
        raise crud.Conflict("ServiceNow görev eşlemesi kapalı (Sistem parametreleri → servicenow.tasks)")
    if action["external_id"]:
        raise crud.Conflict(f"Bu faaliyet ServiceNow'da zaten açık: {action['external_number']}")
    from ..servicenow import ServiceNowError
    finding = one(c.db, "SELECT code, title FROM tdr_findings WHERE id=?", (action["finding_id"],)) if action["finding_id"] else None
    payload = {"short_description": f"{settings['short_description_prefix']} {action['code']} {action['title']}"[:160],
               "description": "\n".join(filter(None, [action["description"], f"Bulgu: {finding['code']} {finding['title']}" if finding else None,
                                                       f"Hedef tarih: {action['due_date']}", f"Kaynak: GRC platformu {action['code']}"])),
               "correlation_id": action["code"]}
    if settings.get("assignment_group"):
        payload["assignment_group"] = settings["assignment_group"]
    try:
        result = _client(c.db, c.app).create(settings["table"], payload)
    except ServiceNowError as exc:
        raise crud.Conflict(str(exc)) from None
    sys_id, number = str(result.get("sys_id") or ""), str(result.get("number") or "")
    if not sys_id:
        raise crud.Conflict("ServiceNow kayıt kimliği dönmedi")
    c.db.execute("UPDATE tdr_grc_actions SET external_id=?, external_number=?, external_status=?, external_synced_at=? "
                 "WHERE id=?", (sys_id, number, "Açık", utcnow(), action["id"]))
    audit.log(c.db, c.principal, "EXPORT", "grc_actions", action["id"], {"servicenow": number, "table": settings["table"]})
    return crud.get(c.db, actions, action["id"])


def pull_status(db, app, action_ids=None):
    """ServiceNow'daki görev durumlarını DÖF'e yansıtır (yalnızca bilgi; DÖF durumunu değiştirmez)."""
    from ..servicenow import ServiceNowError
    settings = task_settings(db)
    if not settings["enabled"]:
        return 0
    sql = "SELECT id, external_id FROM tdr_grc_actions WHERE external_id IS NOT NULL AND status NOT IN ('completed','cancelled')"
    targets = rows(db, sql)
    if action_ids is not None:
        targets = [t for t in targets if t["id"] in action_ids]
    if not targets:
        return 0
    client = _client(db, app)
    n = 0
    for t in targets:
        try:
            rec = client.record(settings["table"], t["external_id"], ["number", "state"])
        except ServiceNowError:
            continue
        state = rec.get("state")
        label = state.get("display_value") if isinstance(state, dict) else state
        db.execute("UPDATE tdr_grc_actions SET external_status=?, external_synced_at=? WHERE id=?",
                   (str(label or "")[:80], utcnow(), t["id"]))
        n += 1
    return n


def refresh_action(c):
    authz.require_human(c.principal)
    actions = RESOURCES["grc_actions"]
    authz.check(c.principal, actions, "read")
    action = crud.get(c.db, actions, c.params["id"])
    if not action["external_id"]:
        raise crud.Conflict("Faaliyet ServiceNow'a bağlı değil")
    from ..servicenow import ServiceNowError
    try:
        pull_status(c.db, c.app, [action["id"]])
    except (ServiceNowError, crud.Conflict) as exc:
        raise crud.Conflict(str(exc)) from None
    return crud.get(c.db, actions, action["id"])


def register(app):
    app.route("POST", API + "/access_reviews/{id}/items", load_items, max_body=MAX_UPLOAD_BODY)
    app.route("POST", API + "/access_reviews/{id}/launch", launch)
    app.route("POST", API + "/access_reviews/{id}/keep", bulk_keep)
    app.route("POST", API + "/access_reviews/{id}/complete", complete)
    app.route("GET", API + "/access_reviews/{id}/context", context)
    app.route("POST", API + "/access_review_items/{id}/decide", decide)
    app.route("POST", API + "/access_review_items/{id}/remediated", remediated)
    app.route("POST", API + "/grc_actions/{id}/servicenow", push_action)
    app.route("POST", API + "/grc_actions/{id}/servicenow/refresh", refresh_action)


def seed(db):
    db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
               ("servicenow.tasks", json.dumps(TASK_DEFAULTS),
                "DÖF'lerin ServiceNow'da görev olarak açılması (isteğe bağlı; hesabın görev tablosuna yazma yetkisi gerekir)."))
