"""Entegrasyonlar (Yönetim) ve bildirim altyapısı (K-024): şifreli sırlar, sınama, etkin yapılandırma, kuyruk, özet."""
import io
import json
import os
import unittest
from unittest import mock

from test_cmdb import PASSWORD, FakeServiceNow, server
from test_kimlik import CLIENT, TENANT
from test_tedarik import Base

try:
    import cryptography  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class FakeSMTP:
    sent, logins, instances = [], [], 0

    def __init__(self, host, port, timeout=None, **kw):
        FakeSMTP.instances += 1
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        FakeSMTP.logins.append((user, password))

    def send_message(self, message):
        FakeSMTP.sent.append(message)


class Recorder:
    """Teams web kancası ve Entra uç noktaları için sahte açıcı (ağa çıkılmaz)."""

    def __init__(self):
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((request.full_url, request.data))

        class Response(io.BytesIO):
            status = 202

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        return Response(b"1")


@unittest.skipUnless(HAS_CRYPTO, "cryptography paketi gerekli")
class Entegrasyon(Base):
    def setUp(self):
        from tedarik.secretbox import generate_key
        super().setUp()
        self.keyfile = os.path.join(self.tmp.name, "secret.key")
        with open(self.keyfile, "w") as fh:
            fh.write(generate_key())
        self.app = self.make(TEDARIK_SECRET_KEY_FILE=self.keyfile, TEDARIK_PUBLIC_URL="https://grc.ornek.test",
                             TEDARIK_SN_ALLOW_HTTP="1")
        FakeSMTP.sent, FakeSMTP.logins = [], []

    def save(self, body, **kw):
        return self.call("POST", "/integrations/save", body, **kw)

    def test_sirlar_yalnizca_yazilir_ve_sifreli_durur(self):
        status, out = self.save({"kind": "email", "enabled": 1, "settings": {"host": "smtp.ornek.test", "port": 587,
                                 "security": "starttls", "username": "grc@ornek.test", "sender": "grc@ornek.test"},
                                 "secrets": {"password": "sentetik-smtp-parolasi"}})
        self.assertEqual(status, 200, out)
        listed = self.ok("GET", "/integrations")
        email = next(i for i in listed["integrations"] if i["kind"] == "email")
        self.assertEqual((email["state"], email["secrets"][0]["set"]), ("enabled", True))
        self.assertNotIn("sentetik-smtp-parolasi", json.dumps(listed))
        with self.db() as db:
            stored = db.execute("SELECT secrets_json FROM tdr_integrations WHERE kind='email'").fetchone()["secrets_json"]
            trail = json.dumps([dict(r) for r in db.execute("SELECT changes_json FROM tdr_audit_log").fetchall()])
        self.assertNotIn("sentetik-smtp-parolasi", stored)            # Fernet ile şifreli
        self.assertNotIn("sentetik-smtp-parolasi", trail)
        viewer = self.make(role="AUDITOR", user="denetci", TEDARIK_SECRET_KEY_FILE=self.keyfile)
        self.assertEqual(self.call("GET", "/integrations", app=viewer)[0], 403)
        # doğrulama
        self.assertEqual(self.save({"kind": "email", "settings": {"sender": "adres-degil"}})[0], 400)
        self.assertEqual(self.save({"kind": "teams", "enabled": 1})[0], 400)                 # web kancası yok
        self.assertEqual(self.save({"kind": "teams", "secrets": {"webhook_url": "http://x.test/kanca"}})[0], 400)
        self.assertEqual(self.save({"kind": "entra", "settings": {"tenant_id": "x", "client_id": CLIENT,
                                                                  "auth_context": "c1"}})[0], 400)
        self.assertEqual(self.save({"kind": "yok"})[0], 400)
        # anahtar yoksa sır kaydedilemez
        nokey = self.make()
        self.assertEqual(self.save({"kind": "teams", "secrets": {"webhook_url": "https://x.test/k"}}, app=nokey)[0], 409)

    def test_eposta_ve_teams_sinamasi_ve_kuyruk(self):
        self.save({"kind": "email", "enabled": 1, "settings": {"host": "smtp.ornek.test", "port": 587, "security": "starttls",
                                                                "username": "grc", "sender": "grc@ornek.test",
                                                                "test_recipient": "test@ornek.test"},
                   "secrets": {"password": "sentetik-smtp-parolasi"}})
        with mock.patch("smtplib.SMTP", FakeSMTP):
            result = self.ok("POST", "/integrations/test", {"kind": "email"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(FakeSMTP.sent[-1]["To"], "test@ornek.test")
        self.assertEqual(FakeSMTP.logins[-1], ("grc", "sentetik-smtp-parolasi"))
        recorder = Recorder()
        self.app.integration_opener = recorder
        self.save({"kind": "teams", "enabled": 1, "secrets": {"webhook_url": "https://ornek.webhook.office.test/k1"}})
        self.assertTrue(self.ok("POST", "/integrations/test", {"kind": "teams"})["ok"])
        card = json.loads(recorder.calls[-1][1])
        self.assertEqual(card["attachments"][0]["contentType"], "application/vnd.microsoft.card.adaptive")
        # olaylar kuyruğa yazılır, istek sırasında gönderilmez; teslim ayrı adımdır
        from tedarik import notify
        with self.db() as db:
            db.execute("INSERT INTO users (username, email, display_name, is_active, created_at) "
                       "VALUES ('ayse', 'ayse@ornek.test', 'Ayşe', 1, '2026-01-01T00:00:00+00:00')")
            n = notify.enqueue(db, "crisis.declared", "Kriz ilan edildi", "Veri merkezi kesintisi",
                               users=["ayse", "adresi-olmayan"], link="#/crisis/1", dedupe="kriz:1")
            again = notify.enqueue(db, "crisis.declared", "Kriz", "", users=["ayse"], dedupe="kriz:1")
        self.assertEqual((n, again), (3, 0))                                      # 2 e-posta (biri atlandı) + Teams
        queue = self.ok("GET", "/notifications?order=id")
        self.assertEqual(sorted(q["status"] for q in queue), ["queued", "queued", "skipped"])
        with mock.patch("smtplib.SMTP", FakeSMTP):
            sent = self.ok("POST", "/notifications/deliver", {})
        self.assertEqual((sent["sent"], sent["failed"], sent["waiting"]), (2, 0, 0))
        self.assertIn("https://grc.ornek.test/#/crisis/1", FakeSMTP.sent[-1].get_content())
        self.assertEqual(recorder.calls[-1][0], "https://ornek.webhook.office.test/k1")
        # olay → kanal tablosu
        table = self.ok("GET", "/notifications/settings")
        events = [{**e, "teams": False} for e in table["events"]]
        self.ok("POST", "/notifications/settings", {"events": events})
        with self.db() as db:
            self.assertEqual(notify.enqueue(db, "crisis.declared", "Kriz 2", "", users=["ayse"]), 1)

    def test_gunluk_ozet(self):
        from tedarik import notify
        self.save({"kind": "email", "enabled": 1, "settings": {"host": "smtp.ornek.test", "port": 587,
                   "security": "starttls", "sender": "grc@ornek.test"}})
        with self.db() as db:
            db.execute("INSERT INTO users (username, email, display_name, is_active, created_at) "
                       "VALUES ('ayse', 'ayse@ornek.test', 'Ayşe', 1, '2026-01-01T00:00:00+00:00')")
        finding = self.ok("POST", "/findings", {"title": "Yedekleme testi yok", "owner": "ayse", "due_date": "2026-01-10"})
        self.ok("POST", "/grc_actions", {"title": "Geri yükleme testi", "owner": "ayse", "due_date": "2026-01-15",
                                         "finding_id": finding["id"]})
        with self.db() as db:
            first = notify.digest(db, self.app, day="2026-11-16")
            second = notify.digest(db, self.app, day="2026-11-16")
            body = db.execute("SELECT body, subject FROM tdr_notifications WHERE event='digest'").fetchone()
        self.assertEqual((first, second), (1, 0))
        self.assertIn("Geri yükleme testi", body["body"])
        self.assertIn("gecikmiş", body["subject"])

    def test_servicenow_tanimi_arayuzden(self):
        fake = FakeServiceNow()
        self.addCleanup(fake.close)
        fake.tables["cmdb_ci_server"] = [server("s1", "srv-ornek-01", "Linux", "9", "2030-01-01", "2026-11-01 10:00:00")]
        self.assertEqual(self.save({"kind": "servicenow", "enabled": 1, "settings": {"instance": fake.url,
                                                                                    "user": "grc.reader"}})[0], 400)
        self.ok("POST", "/integrations/save", {"kind": "servicenow", "enabled": 1, "settings": {
            "instance": fake.url, "user": "grc.reader"}, "secrets": {"password": PASSWORD}})
        self.assertTrue(self.ok("POST", "/integrations/test", {"kind": "servicenow"})["ok"])
        status = self.ok("GET", "/cmdb/status")
        self.assertEqual((status["servicenow"]["configured"], status["channel"]), (True, "servicenow"))
        result = self.ok("POST", "/cmdb/sync", {})
        self.assertGreaterEqual(result["created"], 1)
        # kurulum dosyasıyla verilen bağlantı arayüzden değiştirilemez
        env_app = self.make(TEDARIK_SECRET_KEY_FILE=self.keyfile, TEDARIK_SN_INSTANCE=fake.url, TEDARIK_SN_ALLOW_HTTP="1")
        self.assertEqual(self.save({"kind": "servicenow", "enabled": 0}, app=env_app)[0], 409)

    def test_entra_tanimi_sinanir_ve_giris_modunda_kullanilir(self):
        from test_kimlik import EntraOpener
        self.ok("POST", "/integrations/save", {"kind": "entra", "enabled": 1, "settings": {
            "tenant_id": TENANT, "client_id": CLIENT, "auth_context": "c7"},
            "secrets": {"client_secret": "synthetic-client-secret-only"}})
        self.app.integration_opener = EntraOpener()
        result = self.ok("POST", "/integrations/test", {"kind": "entra"})
        self.assertTrue(result["ok"], result)
        # Entra modunda ortam değişkeni yoksa ayarlar veritabanından okunur
        entra = self.make(TEDARIK_SECRET_KEY_FILE=self.keyfile, TEDARIK_PUBLIC_URL="https://grc.ornek.test",
                          TEDARIK_AUTH_MODE="entra", TEDARIK_COOKIE_SECURE="1")
        self.assertEqual(entra.auth.entra.config.tenant, TENANT)
        self.assertEqual(entra.auth.entra.config.redirect, "https://grc.ornek.test/auth/entra/callback")
        # tanım yoksa açılmaz (kapalı başarısızlık)
        self.ok("POST", "/integrations/save", {"kind": "entra", "enabled": 0})
        with self.assertRaises(RuntimeError):
            self.make(TEDARIK_SECRET_KEY_FILE=self.keyfile, TEDARIK_AUTH_MODE="entra", TEDARIK_COOKIE_SECURE="1")

    def test_yapay_zeka_kapaliyken_kural_tabanli_oneri(self):
        risk = self.ok("POST", "/supplier_risks", {"title": "Sorun", "category": "operational", "owner": "x",
                                                   "appetite": 8, "entity_name": "Veri merkezi"})["id"]
        out = self.ok("POST", "/ai/risk-quality", {"risk_id": risk})
        self.assertIsNone(out["ai"])
        self.assertIn("kapalı", out["ai_note"])
        self.assertLess(out["rules"]["score"], 60)
        self.assertTrue(any("Neden" in i for i in out["rules"]["issues"]))
        listed = next(i for i in self.ok("GET", "/integrations")["integrations"] if i["kind"] == "ai")
        self.assertIn("sdk", listed)
        self.assertEqual(self.save({"kind": "ai", "enabled": 1, "settings": {"model": "claude-opus-5-5",
                                    "effort": "medium", "data_approval": "Kurul 2026/1"}})[0], 400)   # anahtar yok


if __name__ == "__main__":
    unittest.main()
