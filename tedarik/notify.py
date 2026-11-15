"""Bildirim altyapısı (K-024): kuyruk, e-posta (SMTP), Microsoft Teams kartı, günlük iş özeti.

- Uygulama istek sırasında dışarıya bağlanmaz: olaylar `enqueue` ile `tdr_notifications` kutusuna yazılır.
- Gönderim zamanlanmış görevle yapılır: `python -m tedarik.notify deliver` (10 dakikada bir) ve
  `python -m tedarik.notify digest` (her sabah: kişiye atanmış açık işlerin özeti, `İşlerim` ile aynı kaynak).
  Yönetici "Şimdi gönder" ile de tetikleyebilir.
- Hangi olayın hangi kanala gideceği `notify.events` sistem parametresindedir (Bildirimler ekranından değişir).
- E-posta alıcısı kullanıcı kaydındaki e-posta adresidir (yoksa kullanıcı adı e-posta biçimindeyse o); adresi
  olmayan alıcı "atlandı" olarak işaretlenir. Teams kanala tek kart gönderir.
- Her ileti en çok 5 kez denenir; sonuç ve son hata kutuda görünür. Aynı `dedupe_key` ile ikinci ileti oluşmaz.
"""
import json
import smtplib
import ssl
import sys
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr

from .db import IntegrityError, one, rows, utcnow

MAX_ATTEMPTS = 5
EVENTS = {   # olay: (Türkçe ad, varsayılan e-posta, varsayılan Teams)
    "digest": ("Günlük iş özeti", True, False),
    "evidence_request.assigned": ("Kanıt talebi atandı", True, False),
    "evidence_request.reviewed": ("Kanıt talebi incelendi (kabul / iade)", True, False),
    "evidence_request.overdue": ("Kanıt talebi gecikti", True, False),
    "finding.assigned": ("Bulgu atandı", True, False),
    "finding.response_requested": ("Bulguya yönetim yanıtı istendi", True, False),
    "action.assigned": ("Düzeltici faaliyet atandı", True, False),
    "workpaper.review_requested": ("Çalışma kâğıdı gözden geçirme bekliyor", True, False),
    "exception.requested": ("Politika istisnası onay bekliyor", True, False),
    "exception.expiring": ("Politika istisnası sona eriyor", True, True),
    "attestation.assigned": ("Politika okundu beyanı bekleniyor", True, False),
    "access_review.assigned": ("Erişim gözden geçirmesi atandı", True, False),
    "rcsa.assigned": ("Öz değerlendirme atandı", True, False),
    "certification.expiring": ("Sertifika süresi doluyor", True, True),
    "privacy_breach.detected": ("Kişisel veri ihlali kaydedildi (72 saat)", True, True),
    "privacy_breach.deadline": ("Kişisel veri ihlali bildirim süresi yaklaşıyor", True, True),
    "crisis.declared": ("Kriz ilan edildi", True, True),
    "crisis.closed": ("Kriz kapatıldı", True, True),
    "glossary.review": ("Sözlük terimi onay bekliyor / iade edildi", True, False),
    "data_request.decided": ("Veri talebi onaylandı / reddedildi", True, False),
    "subject_request.due": ("İlgili kişi başvurusunun süresi doluyor", True, True),
    "catalog.changed": ("Veri kaynağında şema değişikliği (sahip ve veri yöneticisine)", True, False),
    "collector.overdue": ("Toplayıcı beklenen sürede veri göndermedi", True, True),
    "collector.failed": ("Toplayıcı hata bildirdi veya gönderimi reddedildi", True, True),
}


class _Principal:
    username, auth_type = "system", "system"


# ------------------------------------------------------------------ olay → kanal tablosu

def event_table(db):
    from .modules.core import policy
    stored = policy(db, "notify.events", {}) or {}
    return [{"event": key, "label": label, "email": bool(stored.get(key, {}).get("email", email)),
             "teams": bool(stored.get(key, {}).get("teams", teams))} for key, (label, email, teams) in EVENTS.items()]


def save_event_table(db, principal, events):
    from . import audit, crud
    if not isinstance(events, list):
        raise crud.Invalid("events listesi gerekli")
    value = {}
    for item in events:
        if not isinstance(item, dict) or item.get("event") not in EVENTS:
            raise crud.Invalid("Tanımsız olay")
        value[item["event"]] = {"email": bool(item.get("email")), "teams": bool(item.get("teams"))}
    text = json.dumps(value, ensure_ascii=False)
    if one(db, "SELECT id FROM tdr_policies WHERE code='notify.events'"):
        db.execute("UPDATE tdr_policies SET value_json=? WHERE code='notify.events'", (text,))
    else:
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?)",
                   ("notify.events", text, "Hangi olayın hangi kanala (e-posta, Teams) bildirileceği."))
    audit.log(db, principal, "UPDATE", "policies", None, {"notify.events": value})
    return {"events": event_table(db)}


def _channels(db, event):
    for item in event_table(db):
        if item["event"] == event:
            return item
    return {"email": True, "teams": False}


# ------------------------------------------------------------------ kuyruğa yazma

def email_of(db, username):
    row = one(db, "SELECT email FROM users WHERE username=?", (username,))
    if row and row["email"]:
        return row["email"]
    return username if "@" in (username or "") else None


def _insert(db, values):
    cols = ", ".join(values)
    try:
        with db.savepoint():
            db.execute(f"INSERT INTO tdr_notifications ({cols}) VALUES ({','.join('?' * len(values))})",
                       tuple(values.values()))
        return True
    except IntegrityError:                     # aynı dedupe_key: ileti zaten kuyrukta
        return False


def enqueue(db, event, subject, body, *, users=(), link=None, object_type=None, object_id=None, dedupe=None,
            teams=None):
    """Olayı kanallara yazar. users: kullanıcı adları (e-posta). teams: Teams'e de gitsin mi (None: tabloya göre).
    Dönüş: kuyruğa yazılan ileti sayısı. Kapalı kanal için ileti yazılmaz."""
    from .modules.integrations import enabled
    channels = _channels(db, event)
    now, count = utcnow(), 0
    base = {"event": event, "subject": subject[:300], "body": (body or "")[:8000], "link": link,
            "object_type": object_type, "object_id": object_id, "status": "queued", "attempts": 0, "created_at": now}
    if channels["email"] and enabled(db, "email"):
        for username in dict.fromkeys(u for u in users if u):
            address = email_of(db, username)
            row = {**base, "channel": "email", "username": username, "recipient": address,
                   "dedupe_key": f"{dedupe}:email:{username}" if dedupe else None}
            if not address:
                row.update(status="skipped", last_error="Kullanıcının e-posta adresi yok")
            count += _insert(db, row)
    if (channels["teams"] if teams is None else teams) and enabled(db, "teams"):
        count += _insert(db, {**base, "channel": "teams", "recipient": "kanal",
                              "dedupe_key": f"{dedupe}:teams" if dedupe else None})
    return count


# ------------------------------------------------------------------ gönderim

def _absolute(app_or_config, link):
    config = getattr(app_or_config, "config", app_or_config)
    if not link:
        return None
    return (config.public_url + "/" + link.lstrip("/")) if config.public_url else None


def send_email(settings, password, to, subject, body, link, timeout=20):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.get("sender_name") or "GRC Platformu", settings["sender"]))
    message["To"] = to
    message.set_content(body + (f"\n\nAç: {link}" if link else "") +
                        "\n\n— Bu ileti GRC platformu tarafından otomatik gönderildi.")
    context = ssl.create_default_context()
    if settings.get("security") == "ssl":
        server = smtplib.SMTP_SSL(settings["host"], int(settings.get("port") or 465), timeout=timeout, context=context)
    else:
        server = smtplib.SMTP(settings["host"], int(settings.get("port") or 587), timeout=timeout)
    with server:
        if settings.get("security") != "ssl":
            server.starttls(context=context)
        if settings.get("username"):
            server.login(settings["username"], password or "")
        server.send_message(message)


def teams_card(subject, body, link):
    content = {"type": "AdaptiveCard", "version": "1.4",
               "body": [{"type": "TextBlock", "text": subject, "weight": "Bolder", "size": "Medium", "wrap": True},
                        {"type": "TextBlock", "text": body or "", "wrap": True}]}
    if link:
        content["actions"] = [{"type": "Action.OpenUrl", "title": "Platformda aç", "url": link}]
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                                                 "contentUrl": None, "content": content}]}


def deliver(db, app, limit=200, opener=None):
    """Kuyruktaki iletileri gönderir. Dönüş: {sent, failed, waiting}."""
    from .modules.integrations import enabled, post_json, secret, settings
    opener = opener or getattr(app, "integration_opener", None)
    db.lock("notify:deliver")
    pending = rows(db, "SELECT * FROM tdr_notifications WHERE status='queued' AND attempts<? ORDER BY id LIMIT ?",
                   (MAX_ATTEMPTS, limit))
    sent = failed = 0
    cache = {}

    def creds(kind):
        if kind not in cache:
            cache[kind] = (settings(db, kind), secret(db, app.config, kind, {"email": "password", "teams": "webhook_url"}[kind]))
        return cache[kind]

    for n in pending:
        if not enabled(db, n["channel"]):
            db.execute("UPDATE tdr_notifications SET status='skipped', last_error=? WHERE id=?", ("Kanal kapalı", n["id"]))
            continue
        link = _absolute(app, n["link"])
        try:
            values, secret_value = creds(n["channel"])
            if n["channel"] == "email":
                send_email(values, secret_value, n["recipient"], n["subject"], n["body"] or "", link)
            else:
                post_json(secret_value, teams_card(n["subject"], n["body"], link), opener=opener)
            db.execute("UPDATE tdr_notifications SET status='sent', sent_at=?, attempts=attempts+1, last_error=NULL "
                       "WHERE id=?", (utcnow(), n["id"]))
            sent += 1
        except Exception as exc:                 # noqa: BLE001 - her ileti ayrı denenir, hata kayda yazılır
            attempts = n["attempts"] + 1
            db.execute("UPDATE tdr_notifications SET attempts=?, status=?, last_error=? WHERE id=?",
                       (attempts, "failed" if attempts >= MAX_ATTEMPTS else "queued",
                        f"{type(exc).__name__}: {str(exc)[:300]}", n["id"]))
            failed += 1
    waiting = one(db, "SELECT COUNT(*) AS n FROM tdr_notifications WHERE status='queued'")["n"]
    return {"sent": sent, "failed": failed, "waiting": waiting}


# ------------------------------------------------------------------ günlük özet

DIGEST_SECTIONS = (("risks", "Gözden geçirilecek riskler"), ("risk_actions", "Risk faaliyetleri"),
                   ("capa", "Düzeltici faaliyetler (DÖF)"), ("capa_validation", "Doğrulama bekleyen DÖF"),
                   ("findings", "Bulgular"), ("evidence_requests", "Kanıt talepleri"),
                   ("documents_to_approve", "Onayınızı bekleyen dokümanlar"),
                   ("documents_to_review", "Gözden geçirilecek dokümanlar"), ("bias_to_approve", "Onay bekleyen BİA"),
                   ("exercises", "Tatbikatlar"), ("attestations", "Okundu beyanları"),
                   ("access_reviews", "Erişim gözden geçirmeleri"), ("rcsa", "Öz değerlendirmeler"),
                   ("workpapers_to_review", "Gözden geçirilecek çalışma kâğıtları"),
                   ("exceptions_to_approve", "Onay bekleyen istisnalar"), ("surveys", "Anketler"))


def digest(db, app, day=None):
    """Her etkin kullanıcıya açık işlerinin özeti (iş yoksa ileti yok). Aynı gün ikinci kez oluşmaz."""
    from .auth import ENTRA_ROLES, Principal
    from .http import Ctx
    from .modules.insights import my_work
    day = day or date.today().isoformat()
    created = 0
    for user in rows(db, "SELECT id, username, display_name FROM users WHERE is_active=1"):
        role_row = one(db, "SELECT role FROM tdr_user_roles WHERE user_id=?", (user["id"],))
        role = role_row["role"] if role_row else "VIEWER"
        principal = Principal(user["username"], role, "session", user["display_name"] or user["username"],
                              user_id=user["id"])
        work = my_work(Ctx(app, db, principal, {}, {}, {}))
        lines = []
        for key, title in DIGEST_SECTIONS:
            items = work.get(key) or []
            if items:
                lines.append(f"{title} ({len(items)}):")
                for it in items[:8]:
                    due = it.get("due_date") or it.get("review_date") or it.get("closes_on")
                    lines.append(f"  • {it.get('code') or ''} {it.get('title') or it.get('name') or ''}"
                                 + (f" — {str(due)[:10]}" if due else ""))
        if not lines:
            continue
        overdue = work.get("overdue", 0)
        subject = f"{app.config.app_name}: {work.get('total', 0)} açık işiniz var" + (f", {overdue} gecikmiş" if overdue else "")
        body = f"Merhaba {user['display_name'] or user['username']},\n\n" + "\n".join(lines)
        created += enqueue(db, "digest", subject, body, users=[user["username"]], link="#/my-work",
                           dedupe=f"digest:{day}")
    return created


def reminders(db, app):
    """Modüllerin süreli hatırlatmaları (istisna bitişi, sertifika, KVKK süresi, geciken talepler)."""
    total = 0
    from .modules import REMINDERS
    for fn in REMINDERS:
        total += fn(db, app) or 0
    return total


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = argv[0] if argv else "deliver"
    from .config import Config
    from .http import build
    app = build(Config())
    try:
        with app.database.connect() as db:
            if command == "digest":
                print(f"Özet: {digest(db, app)} ileti; hatırlatma: {reminders(db, app)} ileti")
            result = deliver(db, app)
            print(f"Gönderildi {result['sent']}, hata {result['failed']}, bekleyen {result['waiting']}")
    finally:
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
