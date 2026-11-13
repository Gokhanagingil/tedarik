"""Kimlik, oturum ve birim kapsamı testleri. RSA anahtarları, hesaplar ve tokenlar sentetiktir.

KS GRC `tests/test_entra.py` yaklaşımıyla: Entra imza anahtarları ve kod değişimi taklit edilir; geri kalan
akış (PKCE, durum, nonce, bağlam, rol, oturum) gerçek kopya kodla çalışır.
"""
import importlib.util
import json
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

from test_tedarik import Base

from tedarik import bootstrap
from tedarik.vendor import identity

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT.parent / "control"
LOCAL_HOST = "127.0.0.1:8090"
LOCAL_ORIGIN = "http://" + LOCAL_HOST


def cookie_of(reply):
    return reply.headers["Set-Cookie"].split(";")[0]


class KopyaDosyalar(unittest.TestCase):
    @unittest.skipUnless((CONTROL / "identity.py").exists(), "../control yok")
    def test_kopyalar_kaynakla_ayni(self):
        for name, allowed in (("identity.py", 0), ("entra_auth.py", 3), ("xlsx_io.py", 0)):
            ours = (ROOT / "tedarik" / "vendor" / name).read_text("utf-8").splitlines()[1:]
            theirs = (CONTROL / name).read_text("utf-8").splitlines()
            changed = [line for line in ours if line not in theirs]
            self.assertEqual(len(changed), allowed, changed)
            self.assertTrue(all("[tedarik yaması K-012]" in line for line in changed))
            self.assertIn("7720f4b095a067dbf810dbc1cd25937d88a2ee5f",
                          (ROOT / "tedarik" / "vendor" / name).read_text("utf-8").splitlines()[0])


class YerelOturum(Base):
    def setUp(self):
        super().setUp()
        self.app = self.make(TEDARIK_AUTH_MODE="local")
        self.admin_password = bootstrap.run(self.app, "create", "tdradmin")

    def request(self, method, path, body=None, cookie="", origin=LOCAL_ORIGIN, client="10.0.0.1", app=None):
        headers = {"Host": LOCAL_HOST, "Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        if origin:
            headers["Origin"] = origin
        raw = json.dumps(body).encode() if body is not None else b""
        return (app or self.app).dispatch(method, path, headers, raw, client)

    def login(self, username, password, **kw):
        status, reply = self.request("POST", "/api/login", {"username": username, "password": password}, **kw)
        self.assertEqual(status, 200, getattr(reply, "payload", reply))
        return cookie_of(reply), reply.payload

    def ready(self, username, password):
        """Giriş + zorunlu parola değişimi; yeni oturum çerezini döner."""
        cookie, _ = self.login(username, password)
        status, reply = self.request("POST", "/api/change-password", {"current_password": password,
                                                                      "new_password": password + "-yeni"},
                                     cookie=cookie)
        self.assertEqual(status, 200)
        return cookie_of(reply)

    def test_anonim_istekler(self):
        self.assertEqual(self.request("GET", "/api/tdr/suppliers")[0], 401)
        self.assertEqual(self.request("GET", "/api/health")[0], 401)
        status, reply = self.request("GET", "/")
        self.assertEqual((status, reply.headers["Location"]), (303, "/login"))
        status, reply = self.request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertIn('type="password"', reply.payload.content)
        self.assertEqual(self.request("GET", "/api/tdr/suppliers", cookie="tedarik_session=uydurma-oturum")[0], 401)

    def test_ilk_giris_parola_degisimi_ve_cerez(self):
        status, _ = self.request("POST", "/api/login", {"username": "tdradmin", "password": "yanlis-parola"})
        self.assertEqual(status, 401)
        cookie, payload = self.login("tdradmin", self.admin_password)
        self.assertTrue(payload["must_change_password"])
        status, reply = self.request("POST", "/api/login", {"username": "tdradmin", "password": self.admin_password})
        header = reply.headers["Set-Cookie"]
        for part in ("tedarik_session=", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(part, header)
        self.assertNotIn("ksgrc", header)
        self.assertEqual(self.request("GET", "/api/tdr/suppliers", cookie=cookie)[1],
                         {"error": "Parolanızı değiştirmeniz gerekiyor"})
        self.assertEqual(self.request("GET", "/api/me", cookie=cookie)[1]["role"], "ADMIN")
        self.assertEqual(self.request("GET", "/", cookie=cookie)[1].headers["Location"], "/change-password")
        short = self.request("POST", "/api/change-password", {"current_password": self.admin_password,
                                                              "new_password": "kisa"}, cookie=cookie)
        self.assertEqual(short[0], 400)
        fresh = self.ready("tdradmin", self.admin_password)
        self.assertEqual(self.request("GET", "/api/tdr/suppliers", cookie=cookie)[0], 401)   # eski oturum kapandı
        self.assertEqual(self.request("GET", "/api/tdr/suppliers", cookie=fresh)[0], 200)
        self.assertEqual(self.request("POST", "/api/logout", {}, cookie=fresh)[0], 200)
        self.assertEqual(self.request("GET", "/api/tdr/suppliers", cookie=fresh)[0], 401)

    def test_giris_hiz_siniri(self):
        for _ in range(8):
            self.assertEqual(self.request("POST", "/api/login", {"username": "tdradmin", "password": "x"})[0], 401)
        self.assertEqual(self.request("POST", "/api/login", {"username": "tdradmin",
                                                             "password": self.admin_password})[0], 429)
        self.login("tdradmin", self.admin_password, client="10.0.0.2")    # başka adres etkilenmez

    def test_koken_denetimi_oturumda_zorunlu(self):
        cookie = self.ready("tdradmin", self.admin_password)
        body = {"code": "BT", "name": "Bilgi Teknolojileri"}
        self.assertEqual(self.request("POST", "/api/tdr/org_units", body, cookie=cookie, origin="http://kotu.test")[0],
                         403)
        self.assertEqual(self.request("POST", "/api/tdr/org_units", body, cookie=cookie, origin="")[0], 403)
        self.assertEqual(self.request("POST", "/api/tdr/org_units", body, cookie=cookie)[0], 201)
        self.assertEqual(self.request("POST", "/api/login", {"username": "x", "password": "y"},
                                      origin="http://kotu.test")[0], 403)

    def test_kullanici_yonetimi_ve_devre_disi_birakma(self):
        admin = self.ready("tdradmin", self.admin_password)
        status, created = self.request("POST", "/api/tdr/users", {"username": "zeynep", "display_name": "Zeynep K.",
                                                                  "role": "VIEWER"}, cookie=admin)
        self.assertEqual(status, 201)
        self.assertTrue(created["must_change_password"])
        self.assertNotIn("temporary_password", json.dumps(self.ok("GET", "/audit_log", app=self.make())))
        self.assertEqual(self.request("POST", "/api/tdr/users", {"username": "zeynep", "role": "VIEWER"},
                                      cookie=admin)[0], 409)
        self.assertEqual(self.request("POST", "/api/tdr/users", {"username": "a b", "role": "VIEWER"},
                                      cookie=admin)[0], 400)
        viewer = self.ready("zeynep", created["temporary_password"])
        self.assertEqual(self.request("GET", "/api/me", cookie=viewer)[1]["display_name"], "Zeynep K.")
        self.assertEqual(self.request("POST", "/api/tdr/org_units", {"code": "X", "name": "X"}, cookie=viewer)[0], 403)
        self.assertEqual(self.request("GET", "/api/tdr/users", cookie=viewer)[0], 403)
        self.assertEqual(self.request("PATCH", f"/api/tdr/users/{created['id']}", {"is_active": 0},
                                      cookie=admin)[0], 200)
        self.assertEqual(self.request("GET", "/api/tdr/suppliers", cookie=viewer)[0], 401)   # oturum hemen kapanır
        own = self.request("GET", "/api/me", cookie=admin)[1]
        me_id = next(u["id"] for u in self.request("GET", "/api/tdr/users", cookie=admin)[1]
                     if u["username"] == own["username"])
        self.assertEqual(self.request("PATCH", f"/api/tdr/users/{me_id}", {"is_active": 0}, cookie=admin)[0], 400)

    def test_tedarik_rolu_olmayan_hesap_giremez(self):
        with self.app.database.connect() as db:     # ortak users tablosunda KS GRC hesabı (K-013)
            identity.provision(db, "grc-only", "yalnizca-grc-parolasi")
        self.assertEqual(self.request("POST", "/api/login", {"username": "grc-only",
                                                             "password": "yalnizca-grc-parolasi"})[0], 401)

    def test_makine_anahtari_kullanici_yonetemez(self):
        self.assertEqual(self.app.dispatch("GET", "/api/tdr/users", {"X-API-Key": "k" * 40})[0], 403)


class BirimKapsami(Base):
    def setUp(self):
        super().setUp()
        self.bt, item, self.supplier, self.engagement = self.base_data()
        self.ops = self.ok("POST", "/org_units", {"code": "OPS", "name": "Operasyon"})["id"]
        self.other_supplier = self.ok("POST", "/suppliers", {"code": "S2", "name": "Diğer Ltd."})["id"]
        self.ops_engagement = self.ok("POST", "/engagements", {
            "code": "E2", "supplier_id": self.other_supplier, "catalog_item_id": item, "org_unit_id": self.ops})["id"]
        self.sla_ops = self.ok("POST", "/sla_definitions", {"engagement_id": self.ops_engagement, "code": "UP",
                                                            "name": "Erişilebilirlik", "target_value": 99})["id"]
        self.bt_user = self.make(role="UNIT_USER", user="can", units=str(self.bt))

    def test_kendi_biriminin_kaydina_yazar(self):
        u = self.bt_user
        self.assertEqual(self.call("PATCH", f"/engagements/{self.engagement}", {"business_owner": "can"}, app=u)[0], 200)
        denied = self.call("PATCH", f"/engagements/{self.ops_engagement}", {"business_owner": "can"}, app=u)
        self.assertEqual(denied, (403, {"error": "Yalnızca kendi biriminizin kayıtlarını değiştirebilirsiniz"}))
        moved = self.call("PATCH", f"/engagements/{self.engagement}", {"org_unit_id": self.ops}, app=u)
        self.assertEqual(moved[0], 403)                                     # kaydı başka birime taşıyamaz
        self.assertEqual(self.call("GET", f"/engagements/{self.ops_engagement}", app=u)[0], 200)   # okuma açık

    def test_bagli_kayitlar_ust_kayittan_kapsam_alir(self):
        u = self.bt_user
        event = {"event_type": "incident", "description": "Kesinti", "occurred_at": "2026-11-01"}
        self.assertEqual(self.call("POST", "/performance_events", {**event, "supplier_id": self.supplier}, app=u)[0],
                         201)
        self.assertEqual(self.call("POST", "/performance_events", {**event, "supplier_id": self.other_supplier},
                                   app=u)[0], 403)
        self.assertEqual(self.call("POST", "/sla_measurements", {"sla_id": self.sla_ops, "period_start": "2026-10-01",
                                                                 "actual_value": 99.5}, app=u)[0], 403)
        risk = {"title": "Bağımlılık", "category": "exit", "owner": "can", "appetite": 9}
        self.assertEqual(self.call("POST", "/supplier_risks", {**risk, "code": "R1", "supplier_id": self.supplier,
                                                               "engagement_id": self.engagement}, app=u)[0], 201)
        self.assertEqual(self.call("POST", "/supplier_risks", {**risk, "code": "R2",
                                                               "supplier_id": self.other_supplier}, app=u)[0], 403)
        other_risk = self.ok("POST", "/supplier_risks", {**risk, "code": "R3", "supplier_id": self.other_supplier,
                                                         "review_date": "2099-01-01", "cause": "a",
                                                         "risk_event": "b", "consequence": "c"})["id"]
        self.assertEqual(self.call("POST", f"/supplier_risks/{other_risk}/assessments", {"rationale": "x"},
                                   app=u)[0], 403)
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{other_risk}", {"title": "x"}, app=u)[0], 403)
        self.assertEqual(self.call("POST", f"/engagements/{self.ops_engagement}/users",
                                   {"org_unit_ids": [self.bt]}, app=u)[0], 403)

    def test_birimi_olmayan_birim_kullanicisi_yazamaz(self):
        nobody = self.make(role="UNIT_USER", user="ali")
        self.assertEqual(self.call("PATCH", f"/engagements/{self.engagement}", {"business_owner": "ali"},
                                   app=nobody)[0], 403)
        manager = self.make(role="SUPPLIER_MANAGER", user="zeynep")      # kapsam yalnızca Birim Kullanıcısına
        self.assertEqual(self.call("PATCH", f"/engagements/{self.ops_engagement}", {"business_owner": "z"},
                                   app=manager)[0], 200)

    def test_mcp_anahtari_kapsamdan_etkilenmez(self):
        status, _ = self.app.dispatch("POST", "/api/tdr/sla_measurements", {"X-API-Key": "k" * 40}, json.dumps(
            {"sla_id": self.sla_ops, "period_start": "2026-10-01", "actual_value": 99.5, "source": "mcp"}).encode())
        self.assertEqual(status, 201)


TENANT = "10000000-0000-4000-8000-000000000001"
CLIENT = "20000000-0000-4000-8000-000000000002"
OID = "30000000-0000-4000-8000-000000000003"
HOST = "tedarik.example.test"
ORIGIN = "https://" + HOST


@unittest.skipUnless(importlib.util.find_spec("jwt"), "Entra paketleri kurulu değil (requirements.txt)")
class EntraOturumu(Base):
    @classmethod
    def setUpClass(cls):
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        cls.jwt = jwt
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public = jwt.algorithms.RSAAlgorithm.to_jwk(cls.private.public_key(), as_dict=True)
        cls.public.update(kid="fixture-key", use="sig")

    def setUp(self):
        super().setUp()
        self.app = self.make(TEDARIK_AUTH_MODE="entra", TEDARIK_COOKIE_SECURE="1", TEDARIK_ENTRA_TENANT_ID=TENANT,
                             TEDARIK_ENTRA_CLIENT_ID=CLIENT, TEDARIK_ENTRA_CLIENT_SECRET="synthetic-client-secret-only",
                             TEDARIK_ENTRA_REDIRECT_URI=ORIGIN + "/auth/entra/callback",
                             TEDARIK_ENTRA_AUTH_CONTEXT="c7")
        self.provider = self.app.auth.entra
        signing = patch.object(self.provider.jwks, "fetch_data", return_value={"keys": [self.public]})
        signing.start()
        self.addCleanup(signing.stop)

    def token(self, nonce, **overrides):
        now = int(time.time())
        claims = dict(iss=self.provider.config.issuer, aud=CLIENT, sub="user", ver="2.0", oid=OID, tid=TENANT,
                      nonce=nonce, iat=now, nbf=now - 1, exp=now + 5000, roles=["KS.TDR.SupplierManager"],
                      acrs=["c7"], name="Kurumsal Kullanıcı")
        claims.update(overrides)
        return self.jwt.encode(claims, self.private, algorithm="RS256", headers={"kid": "fixture-key"})

    def request(self, method, path, body=None, cookie="", host=HOST, origin=ORIGIN):
        headers = {"Host": host, "Origin": origin, "Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        return self.app.dispatch(method, path, headers, json.dumps(body).encode() if body is not None else b"")

    def sign_in(self, expected=200, **claims):
        status, reply = self.request("GET", "/auth/entra/start")
        self.assertEqual(status, 303)
        destination = reply.headers["Location"]
        self.assertEqual(urlsplit(destination).netloc, "login.microsoftonline.com")
        flow = cookie_of(reply)
        self.assertTrue(flow.startswith("__Host-tdr_flow="))
        params = parse_qs(urlsplit(destination).query)
        query = urlencode({"state": params["state"][0], "code": "sentetik-yetki-kodu"})
        with patch.object(self.provider, "exchange", return_value=self.token(params["nonce"][0], **claims)):
            status, reply = self.request("GET", "/auth/entra/callback?" + query, cookie=flow)
        self.assertEqual(status, expected)
        return cookie_of(reply) if expected == 200 else None

    def test_rol_eslemesi_ve_reddedilen_roller(self):
        manager = self.sign_in()
        self.assertTrue(manager.startswith("__Host-tdr_session="))
        me = self.request("GET", "/api/me", cookie=manager)[1]
        self.assertEqual((me["role"], me["display_name"]), ("SUPPLIER_MANAGER", "Kurumsal Kullanıcı"))
        self.assertEqual(self.request("POST", "/api/tdr/suppliers", {"code": "S1", "name": "A"}, cookie=manager)[0],
                         201)
        self.assertEqual(self.request("GET", "/api/tdr/users", cookie=manager)[0], 403)
        self.sign_in(403, roles=["KS.GRC.Admin"])          # KS GRC rolü tedarikte yetki vermez
        self.sign_in(403, acrs=["c1"])                     # MFA bağlamı eksik
        admin = self.sign_in(roles=["KS.TDR.Viewer", "KS.TDR.Admin"])   # en yetkili rol seçilir
        self.assertEqual(self.request("GET", "/api/me", cookie=admin)[1]["role"], "ADMIN")
        self.assertEqual(self.request("GET", "/api/me", cookie=manager)[0], 401)   # rol değişince eski oturum düşer

    def test_kurumsal_modda_yerel_yollar_kapali(self):
        self.assertEqual(self.request("POST", "/api/login", {"username": "a", "password": "b"})[0], 403)
        admin = self.sign_in(roles=["KS.TDR.Admin"])
        self.assertEqual(self.request("POST", "/api/change-password", {"current_password": "a", "new_password": "b"},
                                      cookie=admin)[0], 403)
        self.assertEqual(self.request("POST", "/api/tdr/users", {"username": "yerel", "role": "ADMIN"},
                                      cookie=admin)[0], 403)
        self.assertEqual(self.request("GET", "/auth/entra/start", host="kotu.example.test")[0], 400)
        self.assertEqual(self.request("POST", "/api/tdr/org_units", {"code": "A", "name": "A"}, cookie=admin,
                                      origin="https://kotu.example.test")[0], 403)
        self.assertEqual(self.request("POST", "/api/tdr/org_units", {"code": "A", "name": "A"}, cookie=admin,
                                      host="kotu.example.test")[0], 403)
        login_page = self.request("GET", "/login")[1].payload.content
        self.assertNotIn('type="password"', login_page)

    def test_birim_atamasi_ve_hesap_kapatma(self):
        admin = self.sign_in(roles=["KS.TDR.Admin"], oid="40000000-0000-4000-8000-000000000004")
        unit_cookie = self.sign_in(roles=["KS.TDR.UnitUser"])
        users = self.request("GET", "/api/tdr/users", cookie=admin)[1]
        unit_user = next(u for u in users if u["username"].endswith(OID))
        self.assertEqual((unit_user["kind"], unit_user["role"]), ("entra", None))
        unit = self.request("POST", "/api/tdr/org_units", {"code": "BT", "name": "BT"}, cookie=admin)[1]["id"]
        self.assertEqual(self.request("PATCH", f"/api/tdr/users/{unit_user['id']}", {"role": "ADMIN"},
                                      cookie=admin)[0], 403)        # rol Entra'dan gelir
        self.request("PATCH", f"/api/tdr/users/{unit_user['id']}", {"org_unit_ids": [unit]}, cookie=admin)
        self.assertEqual(self.request("GET", "/api/me", cookie=unit_cookie)[1]["units"], [unit])
        self.request("PATCH", f"/api/tdr/users/{unit_user['id']}", {"is_active": 0}, cookie=admin)
        self.assertEqual(self.request("GET", "/api/me", cookie=unit_cookie)[0], 401)
        self.sign_in(403, roles=["KS.TDR.UnitUser"])


if __name__ == "__main__":
    unittest.main()
