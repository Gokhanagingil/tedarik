"""Uçtan uca davranış testleri. Soket açılmaz; App.dispatch doğrudan çağrılır. Veri sentetiktir.

Varsayılan motor SQLite'tır. `TEDARIK_TEST_DATABASE_URL=postgresql://...` verilirse aynı testler
PostgreSQL'de, her test için ayrı ve sonra silinen bir şemada çalışır (K-011).
"""
import base64
import json
import os
import secrets
import tempfile
import unittest

from tedarik.auth import Principal
from tedarik.config import Config
from tedarik.crud import Forbidden
from tedarik.db import one
from tedarik.http import build

KEY = "k" * 40
PG_URL = os.environ.get("TEDARIK_TEST_DATABASE_URL", "")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "test.db")
        self.schema = ""
        if PG_URL:
            import psycopg
            self.schema = "t_" + secrets.token_hex(6)
            with psycopg.connect(PG_URL, autocommit=True) as admin:
                admin.execute(f'CREATE SCHEMA "{self.schema}"')

            def drop():
                with psycopg.connect(PG_URL, autocommit=True) as admin:
                    admin.execute(f'DROP SCHEMA "{self.schema}" CASCADE')
            self.addCleanup(drop)
        self.app = self.make()

    def env(self, **extra):
        env = {"TEDARIK_DB": self.path, "TEDARIK_AUTH_MODE": "dev", "TEDARIK_API_KEY": KEY}
        if PG_URL:
            env.update({"TEDARIK_DATABASE_URL": PG_URL, "TEDARIK_DB_SCHEMA": self.schema})
        env.update(extra)
        return env

    def make(self, role="ADMIN", user="dev", modules=None, units="", **env):
        extra = {"TEDARIK_DEV_ROLE": role, "TEDARIK_DEV_USER": user, "TEDARIK_DEV_UNITS": units, **env}
        if modules:
            extra["TEDARIK_MODULES"] = modules
        app = build(Config(self.env(**extra)))
        self.addCleanup(app.close)
        return app

    def db(self):
        return self.app.database.connect()

    def call(self, method, path, body=None, app=None, headers=None):
        raw = json.dumps(body).encode() if body is not None else b""
        return (app or self.app).dispatch(method, "/api/tdr" + path, headers or {}, raw)

    def ok(self, method, path, body=None, **kw):
        status, payload = self.call(method, path, body, **kw)
        self.assertLess(status, 300, payload)
        return payload

    def base_data(self):
        """Bir birim, bir hizmet, bir tedarikçi ve bir angajman."""
        unit = self.ok("POST", "/org_units", {"code": "BT", "name": "Bilgi Teknolojileri"})["id"]
        item = self.ok("POST", "/catalog_items", {"code": "DC-HOST", "name": "Veri Merkezi Barındırma"})["id"]
        supplier = self.ok("POST", "/suppliers", {"code": "S1", "name": "Örnek Bilişim A.Ş.",
                                                  "tax_id": "1234567890", "tier": "critical"})["id"]
        engagement = self.ok("POST", "/engagements", {
            "code": "E1", "supplier_id": supplier, "catalog_item_id": item, "org_unit_id": unit,
            "business_owner": "ayse"})["id"]
        return unit, item, supplier, engagement


class Guvenlik(Base):
    def test_anonim_erisim_acilmaz(self):
        with self.assertRaises(ValueError):
            Config({"TEDARIK_DB": self.path})
        with self.assertRaises(ValueError):
            Config({"TEDARIK_DB": self.path, "TEDARIK_AUTH_MODE": "dev", "TEDARIK_HOST": "0.0.0.0"})
        with self.assertRaises(ValueError):        # eksik Entra ayarıyla uygulama açılmaz
            build(Config(self.env(TEDARIK_AUTH_MODE="entra")))

    def test_roller(self):
        self.base_data()
        viewer = self.make(role="VIEWER")
        self.assertEqual(self.call("GET", "/suppliers", app=viewer)[0], 200)
        self.assertEqual(self.call("POST", "/suppliers", {"code": "X", "name": "X"}, app=viewer)[0], 403)
        self.assertEqual(self.call("GET", "/audit_log", app=viewer)[0], 403)
        unit_user = self.make(role="UNIT_USER", units="1")
        self.assertEqual(self.call("POST", "/suppliers", {"code": "X", "name": "X"}, app=unit_user)[0], 403)
        self.assertEqual(self.call("PATCH", "/engagements/1", {"business_owner": "can"}, app=unit_user)[0], 200)

    def test_mcp_anahtari_en_az_yetki(self):
        _, _, _, engagement = self.base_data()
        sla = self.ok("POST", "/sla_definitions", {"engagement_id": engagement, "code": "UP", "name": "Erişilebilirlik",
                                                   "target_value": 99.5})["id"]
        mcp = {"X-API-Key": KEY}
        self.assertEqual(self.call("GET", "/suppliers", headers=mcp)[0], 200)
        self.assertEqual(self.call("POST", "/suppliers", {"code": "X", "name": "X"}, headers=mcp)[0], 403)
        self.assertEqual(self.call("GET", "/export/suppliers", headers=mcp)[0], 403)
        body = {"sla_id": sla, "period_start": "2026-10-01", "actual_value": 99.9}
        self.assertEqual(self.call("POST", "/sla_measurements", body, headers=mcp)[0], 403)   # source=mcp yok
        self.assertEqual(self.call("POST", "/sla_measurements", {**body, "source": "mcp"}, headers=mcp)[0], 201)
        self.assertEqual(self.call("GET", "/suppliers", headers={"X-API-Key": "yanlis"})[0], 401)

    def test_farkli_kokenden_degisiklik_reddedilir(self):
        headers = {"Origin": "http://kotu.example", "Host": "127.0.0.1:8090"}
        self.assertEqual(self.call("POST", "/org_units", {"code": "A", "name": "A"}, headers=headers)[0], 403)

    def test_tekrar_korumasi(self):
        body = {"code": "A", "name": "A", "idempotency_key": "istek-0001"}
        first = self.call("POST", "/org_units", body)
        again = self.call("POST", "/org_units", dict(body))
        self.assertEqual((first[0], again[0]), (201, 200))
        self.assertTrue(again[1]["replayed"])
        self.assertEqual(again[1]["id"], first[1]["id"])
        changed = self.call("POST", "/org_units", {"code": "B", "name": "B", "idempotency_key": "istek-0001"})
        self.assertEqual(changed[0], 409)
        for bad in ("kisa", "bosluk içeren anahtar", "x" * 161):
            self.assertEqual(self.call("POST", "/org_units", {"code": "C", "name": "C", "idempotency_key": bad})[0], 400)

    def test_eszamanli_tekrarlar_tek_kayit_uretir(self):
        from concurrent.futures import ThreadPoolExecutor
        body = {"code": "P", "name": "Paralel", "idempotency_key": "paralel-0001"}
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: self.call("POST", "/org_units", dict(body)), range(8)))
        self.assertEqual(sorted(r[0] for r in results), [200] * 7 + [201])
        self.assertEqual(len({r[1]["id"] for r in results}), 1)

    def test_saglik_kimlik_ister_ve_hata_ayrintisi_sizdirilmaz(self):
        self.assertEqual(self.app.dispatch("GET", "/api/health", {"X-API-Key": "yanlis"})[0], 401)
        self.assertEqual(self.app.dispatch("GET", "/api/health", {"X-API-Key": KEY})[0], 200)

        def broken(c):
            c.db.execute("SELECT * FROM olmayan_tablo")
        self.app.route("GET", "/api/tdr/bozuk", broken)
        with self.assertLogs("tedarik", "ERROR"):
            status, payload = self.call("GET", "/bozuk")
        self.assertEqual((status, payload), (500, {"error": "Beklenmeyen işlem hatası"}))

    def test_birden_fazla_origin_reddedilir(self):
        from email.message import Message
        headers = Message()
        headers["Host"] = "127.0.0.1:8090"
        headers["Origin"] = "http://127.0.0.1:8090"
        self.assertEqual(self.call("POST", "/org_units", {"code": "A", "name": "A"}, headers=headers)[0], 201)
        headers["Origin"] = "http://127.0.0.1:8090"
        self.assertEqual(self.call("POST", "/org_units", {"code": "B", "name": "B"}, headers=headers)[0], 403)

    def test_denetim_izi_ks_grc_alanlari(self):
        self.ok("POST", "/org_units", {"code": "A", "name": "A"})
        entry = self.ok("GET", "/audit_log")[0]
        self.assertEqual({k: entry[k] for k in ("actor", "method", "object_type", "object_id")},
                         {"actor": "dev", "method": "CREATE", "object_type": "org_units", "object_id": "1"})
        self.assertTrue(entry["occurred_at"].endswith("+00:00"))
        self.ok("POST", "/import/suppliers", {"source_system": "sap", "filename": "a.csv", "dry_run": True,
                                              "content_base64": base64.b64encode(b"name\r\nA\r\n").decode()})
        self.assertNotIn("QQ", json.dumps(self.ok("GET", "/audit_log")))


class Veritabani(Base):
    def test_motor_secimi_ve_yerel_tipler(self):
        self.assertEqual(self.app.database.dialect, "postgres" if PG_URL else "sqlite")
        if not PG_URL:
            return
        with self.db() as db:
            types = {(r["table_name"], r["column_name"]): r["data_type"] for r in db.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema()").fetchall()}
        self.assertEqual(types[("tdr_engagements", "start_date")], "date")
        self.assertEqual(types[("tdr_suppliers", "created_at")], "timestamp with time zone")
        self.assertEqual(types[("tdr_sla_definitions", "target_value")], "double precision")
        self.assertEqual(types[("users", "username")], "text")          # KS GRC ile ortak kimlik tablosu
        self.assertEqual(types[("tdr_suppliers", "id")], "bigint")

    def test_tarih_ve_zaman_dogrulanir_ve_utc_ye_cevrilir(self):
        unit, item, supplier, engagement = self.base_data()
        body = {"code": "E9", "supplier_id": supplier, "catalog_item_id": item, "org_unit_id": unit}
        for bad in ("2026-13-01", "13.11.2026", "2026-2-1", 20261113):
            self.assertEqual(self.call("POST", "/engagements", {**body, "start_date": bad})[0], 400, bad)
        self.ok("POST", "/engagements", {**body, "start_date": "2026-11-13"})
        event = {"supplier_id": supplier, "event_type": "incident", "description": "Kesinti"}
        self.assertEqual(self.call("POST", "/performance_events", {**event, "occurred_at": "2026-11-13T12:00"})[0], 400)
        made = self.ok("POST", "/performance_events", {**event, "occurred_at": "2026-11-13T12:00:00+03:00"})
        self.assertEqual(self.ok("GET", f"/performance_events/{made['id']}")["occurred_at"], "2026-11-13T09:00:00+00:00")
        self.assertEqual(self.call("POST", "/suppliers", {"code": 5, "name": "Sayı kodlu"})[0], 400)
        self.assertEqual(self.call("GET", "/suppliers?limit=x")[0], 400)

    def test_turkce_arama_iki_motorda_ayni(self):
        self.ok("POST", "/suppliers", {"code": "S1", "name": "Örnek Bilişim A.Ş."})
        self.ok("POST", "/suppliers", {"code": "S2", "name": "İZMİR ÇÖZÜM LTD"})
        self.ok("POST", "/suppliers", {"code": "S3", "name": "Yüzde%50 Ticaret"})
        for query, expected in (("örnek", ["S1"]), ("ÖRNEK", ["S1"]), ("ornek bilisim", ["S1"]),
                                ("izmir", ["S2"]), ("çözüm", ["S2"]), ("%", ["S3"]), ("_", [])):
            from urllib.parse import quote
            found = [r["code"] for r in self.ok("GET", "/suppliers?q=" + quote(query))]
            self.assertEqual(found, expected, query)

    def test_degismez_tablolar_veritabaninda_korunur(self):
        from tedarik.db import IntegrityError
        self.ok("POST", "/org_units", {"code": "A", "name": "A"})
        for sql in ("UPDATE tdr_audit_log SET actor='baskasi'", "DELETE FROM tdr_audit_log"):
            with self.assertRaises(IntegrityError):
                with self.db() as db:
                    db.execute(sql)
        self.assertEqual(self.ok("GET", "/audit_log")[0]["actor"], "dev")

    def test_sema_evrimi(self):
        from tedarik import migrate
        from tedarik.schema import RESOURCES
        suppliers = RESOURCES["suppliers"]
        migrate.sync(self.app.database, self.app.config.modules)          # tekrar çalıştırmak zararsız
        self.ok("POST", "/suppliers", {"code": "S1", "name": "Önce"})
        original = dict(suppliers.fields), dict(suppliers.columns)
        self.addCleanup(lambda: (suppliers.fields.clear(), suppliers.fields.update(original[0]),
                                 suppliers.columns.clear(), suppliers.columns.update(original[1])))
        from tedarik.schema import Field
        suppliers.fields["duns"] = "TEXT"
        suppliers.columns["duns"] = Field("duns", "TEXT")
        migrate.sync(self.app.database, self.app.config.modules)
        self.ok("PATCH", "/suppliers/1", {"duns": "123456789"})
        suppliers.fields["zorunlu"] = "TEXT NOT NULL"
        suppliers.columns["zorunlu"] = Field("zorunlu", "TEXT NOT NULL")
        with self.assertRaises(RuntimeError):
            migrate.sync(self.app.database, self.app.config.modules)

    def test_sayisal_ozetler_iki_motorda_ayni(self):
        _, _, supplier, engagement = self.base_data()
        card = self.ok("GET", f"/suppliers/{supplier}/scorecard")
        self.assertEqual(card["sla"], {"total": 0, "met": 0, "rate": None})
        self.assertIs(type(card["sla"]["total"]), int)
        summary = self.ok("GET", "/dashboard/summary")
        self.assertIs(type(summary["suppliers"]["total"]), int)
        self.assertEqual(summary["surveys"], {"invited": 0, "answered": 0})


class Cekirdek(Base):
    def test_dogrulama(self):
        self.base_data()
        self.assertEqual(self.call("POST", "/suppliers", {"code": "S2", "name": "Y", "bilinmeyen": 1})[0], 400)
        self.assertEqual(self.call("POST", "/suppliers", {"code": "S2", "name": "Y", "tier": "çok"})[0], 400)
        self.assertEqual(self.call("POST", "/suppliers", {"code": "S2", "name": "Y", "created_at": "x"})[0], 400)
        self.assertEqual(self.call("POST", "/suppliers", {"code": "S1", "name": "Aynı kod"})[0], 409)
        self.assertEqual(self.call("GET", "/suppliers?olmayan=1")[0], 400)
        self.assertEqual(self.call("GET", "/suppliers/999")[0], 404)

    def test_musteriye_sunulan_hizmet_ayrisir(self):
        unit, item, supplier, _ = self.base_data()
        body = {"code": "E2", "supplier_id": supplier, "catalog_item_id": item, "org_unit_id": unit,
                "beneficiary": "customer"}
        self.assertEqual(self.call("POST", "/engagements", body)[0], 400)
        self.ok("POST", "/engagements", {**body, "customer_name": "Müşteri A"})
        self.assertEqual(len(self.ok("GET", "/engagements?beneficiary=customer")), 1)
        self.assertEqual(len(self.ok("GET", "/engagements?beneficiary=internal")), 1)

    def test_tip_filtresi_baglam_ve_kullanim_raporu(self):
        unit, _, supplier, engagement = self.base_data()
        other_unit = self.ok("POST", "/org_units", {"code": "OPS", "name": "Operasyon"})["id"]
        self.ok("POST", "/suppliers", {"code": "S2", "name": "Diğer Ltd."})
        cloud = next(t["id"] for t in self.ok("GET", "/supplier_types") if t["code"] == "CLOUD")
        self.ok("POST", f"/suppliers/{supplier}/types", {"type_ids": [cloud]})
        self.assertEqual([s["code"] for s in self.ok("GET", f"/suppliers?type_id={cloud}")], ["S1"])
        self.assertEqual([s["code"] for s in self.ok("GET", "/suppliers?q=Diğer")], ["S2"])
        self.ok("POST", f"/engagements/{engagement}/users", {"org_unit_ids": [unit, other_unit]})
        context = self.ok("GET", f"/suppliers/{supplier}/context")
        self.assertEqual(context["types"][0]["code"], "CLOUD")
        self.assertEqual(context["engagements"][0]["unit_name"], "Bilgi Teknolojileri")
        report = self.ok("GET", "/reports/usage")
        self.assertEqual(report[0]["buyer_unit"], "Bilgi Teknolojileri")
        self.assertIn("Operasyon", report[0]["user_units"])
        self.assertGreaterEqual(len(self.ok("GET", "/audit_log")), 5)


class Performans(Base):
    def test_sla_ve_scorecard(self):
        _, _, supplier, engagement = self.base_data()
        sla = self.ok("POST", "/sla_definitions", {"engagement_id": engagement, "code": "UP", "name": "Erişilebilirlik",
                                                   "target_value": 99.5})["id"]
        resp = self.ok("POST", "/sla_definitions", {"engagement_id": engagement, "code": "RT", "name": "Yanıt süresi",
                                                    "unit": "hours", "target_value": 4, "direction": "lower_better"})
        from datetime import date
        month = date.today().replace(day=1).isoformat()
        a = self.ok("POST", "/sla_measurements", {"sla_id": sla, "period_start": month, "actual_value": 99.1})["id"]
        b = self.ok("POST", "/sla_measurements", {"sla_id": resp["id"], "period_start": month, "actual_value": 3})["id"]
        self.assertEqual(self.ok("GET", f"/sla_measurements/{a}")["met"], 0)
        self.assertEqual(self.ok("GET", f"/sla_measurements/{b}")["met"], 1)
        self.assertEqual(self.call("POST", "/sla_measurements", {"sla_id": sla, "period_start": month,
                                                                 "actual_value": 100})[0], 409)   # dönem tekil
        review = self.ok("POST", "/performance_reviews", {"supplier_id": supplier, "period_start": month,
                                                          "period_end": month})["id"]
        criteria = {c["code"]: c["id"] for c in self.ok("GET", "/review_criteria")}
        self.ok("POST", "/review_scores", {"review_id": review, "criterion_id": criteria["QUALITY"], "score": 5})
        self.ok("POST", "/review_scores", {"review_id": review, "criterion_id": criteria["COMMERCIAL"], "score": 1})
        self.assertEqual(self.call("POST", "/review_scores", {"review_id": review,
                                                              "criterion_id": criteria["COMMS"], "score": 9})[0], 400)
        card = self.ok("GET", f"/suppliers/{supplier}/scorecard")
        self.assertEqual(card["sla"], {"total": 2, "met": 1, "rate": 50.0})
        self.assertEqual(card["review"]["score"], 4.0)   # (5*3 + 1*1) / 4


class Risk(Base):
    STATEMENT = {"cause": "Kritik hizmette alternatif tedarikçi olmadığı için",
                 "risk_event": "tedarikçi kesintisi hizmeti durdurabilir",
                 "consequence": "müşteriye taahhüt edilen süre aşılabilir"}

    def new_risk(self, supplier, appetite=6, **extra):
        body = {"code": "R1", "title": "Tek tedarikçiye bağımlılık", "supplier_id": supplier,
                "category": "concentration", "owner": "ayse", "appetite": appetite, "likelihood": 4, "impact": 5,
                "review_date": "2099-01-01", **self.STATEMENT, **extra}
        return self.ok("POST", "/supplier_risks", body)["id"]

    def assess(self, risk, mitigations=(), app=None):
        return self.ok("POST", f"/supplier_risks/{risk}/assessments",
                       {"rationale": "Alternatif yok", "mitigations": list(mitigations)}, app=app)

    def test_puanlama_ks_grc_ile_ayni(self):
        *_, supplier, _ = self.base_data()
        risk = self.new_risk(supplier)
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", {"status": "accepted"})[0], 400)
        result = self.assess(risk, [{"weight": "medium"}, {"weight": "low", "effectiveness": "partial"}])
        self.assertEqual((result["inherent"], result["residual"], result["above_appetite"]), (20, 10.0, True))
        full = self.assess(risk, [{"weight": "high"}, {"weight": "high"}])     # katkı %100 ile sınırlı
        self.assertEqual(full["residual"], 0.0)
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", {"likelihood": 6})[0], 400)
        self.assertEqual(self.call("POST", "/supplier_risks", {"code": "R2", "title": "t", "supplier_id": supplier,
                                                               "category": "exit", "owner": "a", "appetite": 30})[0], 400)
        self.assertEqual(self.call("POST", "/supplier_risks", {"code": "R3", "title": "t", "supplier_id": supplier,
                                                               "category": "exit", "owner": "a", "appetite": 5,
                                                               "cause": "yalnız neden"})[0], 400)
        context = self.ok("GET", f"/supplier_risks/{risk}/context")
        self.assertEqual(len(context["assessments"]), 2)
        self.assertEqual(context["assessments"][1]["snapshot"]["likelihood"], 4)
        self.assertEqual(self.call("PATCH", f"/risk_assessments/{full['id']}", {"residual": 1})[0], 404)
        summary = self.ok("GET", "/dashboard/summary")["risks"]
        self.assertEqual((summary["above_appetite"], summary["open"]), (0, 1))

    def test_karar_kurallari(self):
        *_, supplier, _ = self.base_data()
        risk = self.new_risk(supplier, appetite=12)
        first = self.assess(risk, [{"weight": "medium"}])                      # 20 × 0,6 = 12, iştah içinde
        accept = {"status": "accepted", "response_strategy": "accept", "decision_rationale": "İş kararı"}
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", accept)[0], 409)   # değerlendirme seçilmedi
        self.ok("PATCH", f"/supplier_risks/{risk}", {"appetite": 13})
        stale = self.call("PATCH", f"/supplier_risks/{risk}", {**accept, "assessment_id": first["id"]})
        self.assertEqual(stale[0], 409)
        self.assertIn("yeniden değerlendirin", stale[1]["error"])
        second = self.assess(risk, [{"weight": "medium"}])
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}",
                                   {**accept, "assessment_id": second["id"], "exception_rationale": "x"})[0], 400)
        self.ok("PATCH", f"/supplier_risks/{risk}", {**accept, "assessment_id": second["id"]})
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", {"title": "Yeni ad"})[0], 409)
        self.assertEqual(self.call("POST", f"/supplier_risks/{risk}/assessments", {"rationale": "x"})[0], 409)
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", {"status": "open"})[0], 400)
        self.ok("PATCH", f"/supplier_risks/{risk}", {"status": "open", "decision_rationale": "Kapsam değişti"})
        again = self.call("PATCH", f"/supplier_risks/{risk}", {**accept, "assessment_id": second["id"]})
        self.assertIn("yeni değerlendirme", again[1]["error"])
        decisions = self.ok("GET", f"/supplier_risks/{risk}/context")["decisions"]
        self.assertEqual([d["to_status"] for d in decisions], ["open", "accepted"])

    def test_istah_ustu_kabul_farkli_yonetici_ister(self):
        *_, supplier, _ = self.base_data()
        risk = self.new_risk(supplier)
        assessor = self.make(role="ADMIN", user="ayse")
        assessed = self.assess(risk, app=assessor)
        accept = {"status": "accepted", "response_strategy": "accept", "decision_rationale": "İş kararı",
                  "assessment_id": assessed["id"]}
        from tedarik.modules.risks import decide
        with self.db() as db:   # oturumlu kullanıcı: değerlendirmeyi yapan kişi kendi istisnasını onaylayamaz
            current = one(db, "SELECT * FROM tdr_supplier_risks WHERE id=?", (risk,))
            details = {k: accept[k] for k in ("decision_rationale", "assessment_id")} | {"exception_rationale": "x"}
            with self.assertRaises(Forbidden):
                decide(db, current, {**current, **accept}, details, Principal("ayse", "ADMIN", "session"))
        manager = self.make(role="SUPPLIER_MANAGER", user="zeynep")
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", accept, app=manager)[0], 403)
        admin = self.make(role="ADMIN", user="mert")
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", accept, app=admin)[0], 400)   # istisna yok
        self.ok("PATCH", f"/supplier_risks/{risk}", {**accept, "exception_rationale": "Geçiş dönemi"}, app=admin)
        decision = self.ok("GET", f"/supplier_risks/{risk}/context")["decisions"][0]
        self.assertEqual((decision["actor"], decision["actor_role"], decision["exception_rationale"]),
                         ("mert", "ADMIN", "Geçiş dönemi"))

    def test_kapanis_acik_faaliyetle_olmaz(self):
        *_, supplier, _ = self.base_data()
        risk = self.new_risk(supplier, appetite=25)
        action = self.ok("POST", "/risk_actions", {"code": "A1", "risk_id": risk, "title": "İkinci tedarikçi",
                                                   "owner": "ayse", "due_date": "2027-01-01"})["id"]
        assessed = self.assess(risk)
        close = {"status": "closed", "decision_rationale": "Tamamlandı", "assessment_id": assessed["id"]}
        self.assertEqual(self.call("PATCH", f"/supplier_risks/{risk}", close)[0], 409)
        done = self.ok("PATCH", f"/risk_actions/{action}", {"status": "completed", "resolution": "Sözleşme imzalandı"})
        self.assertIsNotNone(done["closed_at"])
        self.ok("PATCH", f"/supplier_risks/{risk}", close)
        self.assertEqual(self.call("PATCH", f"/risk_actions/{action}", {"status": "open"})[0], 409)
        self.assertEqual(self.call("POST", "/risk_actions", {"code": "A2", "risk_id": risk, "title": "x",
                                                            "owner": "a", "due_date": "2027-01-01"})[0], 409)


class Anket(Base):
    def test_kampanya_akisi(self):
        *_, supplier, _ = self.base_data()
        template = self.ok("POST", "/survey_templates", {"code": "MEMNUNIYET", "name": "Memnuniyet"})["id"]
        q1 = self.ok("POST", "/survey_questions", {"template_id": template, "text": "Genel memnuniyet"})["id"]
        q2 = self.ok("POST", "/survey_questions", {"template_id": template, "text": "Yorum", "kind": "text",
                                                   "required": 0, "position": 2})["id"]
        campaign = self.ok("POST", "/survey_campaigns", {"code": "2026-Q4", "name": "4. çeyrek",
                                                         "template_id": template, "supplier_id": supplier})["id"]
        invites = [self.ok("POST", "/survey_invitations", {"campaign_id": campaign, "respondent": who})["id"]
                   for who in ("ayse", "can")]
        answers = {"answers": [{"question_id": q1, "score": 4}, {"question_id": q2, "text_value": "İyi"}]}
        self.assertEqual(self.call("POST", f"/survey_invitations/{invites[0]}/answers", answers)[0], 409)   # kapalı
        self.ok("POST", f"/survey_campaigns/{campaign}/open", {})
        self.assertEqual(self.call("POST", f"/survey_invitations/{invites[0]}/answers",
                                   {"answers": [{"question_id": q1, "score": 7}]})[0], 400)
        self.assertEqual(self.call("POST", f"/survey_invitations/{invites[0]}/answers",
                                   {"answers": [{"question_id": q2, "text_value": "eksik"}]})[0], 400)
        self.ok("POST", f"/survey_invitations/{invites[0]}/answers", answers)
        self.assertEqual(self.ok("GET", "/audit_log?object_type=survey_invitations")[0]["method"], "ANSWER")
        self.assertEqual(self.call("POST", f"/survey_invitations/{invites[0]}/answers", answers)[0], 409)
        other = self.make(role="UNIT_USER", user="mehmet", units="1")
        self.assertEqual(self.call("POST", f"/survey_invitations/{invites[1]}/answers", answers, app=other)[0], 403)
        result = self.ok("GET", f"/survey_campaigns/{campaign}/results")
        self.assertEqual((result["invited"], result["answered"], result["response_rate"]), (2, 1, 50.0))
        self.assertEqual(result["satisfaction"], 75.0)


class KaynakBulma(Base):
    def setUp(self):
        super().setUp()
        self.full = self.make(modules="core,workflow,sourcing")

    def step(self, need, action, app=None):
        return self.call("POST", f"/needs/{need}/transition", {"action": action}, app=app or self.full)

    def test_modul_kapaliyken_yoktur(self):
        self.assertEqual(self.call("GET", "/needs")[0], 404)

    def test_mevcut_tedarikci_yoksa_en_az_uc_teklif(self):
        unit, *_ = self.base_data()
        suppliers = [self.ok("POST", "/suppliers", {"code": f"T{i}", "name": f"Teklif Veren {i}"})["id"]
                     for i in range(3)]
        need = self.ok("POST", "/needs", {"code": "N1", "title": "Yedekleme hizmeti", "org_unit_id": unit},
                       app=self.full)["id"]
        self.assertEqual(self.step(need, "submit")[0], 200)
        self.assertEqual(self.step(need, "select_existing")[0], 409)   # seçili mevcut tedarikçi yok
        self.assertEqual(self.step(need, "request_quotes")[0], 200)
        for supplier in suppliers[:2]:
            self.ok("POST", "/need_candidates", {"need_id": need, "supplier_id": supplier, "origin": "new"},
                    app=self.full)
            self.ok("POST", "/quotes", {"need_id": need, "supplier_id": supplier, "amount": 100,
                                        "received_at": "2026-11-01"}, app=self.full)
        blocked = self.step(need, "evaluate")
        self.assertEqual(blocked[0], 409)
        self.assertIn("En az 3", blocked[1]["error"])
        self.ok("POST", "/quotes", {"need_id": need, "supplier_id": suppliers[2], "amount": 90,
                                    "received_at": "2026-11-02"}, app=self.full)
        self.assertEqual(self.step(need, "evaluate")[0], 200)
        self.assertEqual(self.step(need, "award")[0], 409)             # kazanan seçilmedi
        winner = self.ok("POST", "/need_candidates", {"need_id": need, "supplier_id": suppliers[2], "origin": "new",
                                                      "selected": 1}, app=self.full)
        self.assertTrue(winner["id"])
        self.assertEqual(self.step(need, "award")[0], 200)
        unit_user = self.make(role="UNIT_USER", modules="core,workflow,sourcing", units="1")
        self.assertEqual(self.step(need, "approve", app=unit_user)[0], 403)
        self.assertEqual(self.step(need, "approve")[1]["state"], "completed")
        context = self.ok("GET", f"/needs/{need}/context", app=self.full)
        self.assertEqual((context["state"], context["actions"], len(context["history"])), ("completed", [], 6))

    def test_mevcut_tedarikciden_secim_kisayolu(self):
        unit, _, supplier, _ = self.base_data()
        need = self.ok("POST", "/needs", {"code": "N2", "title": "Ek lisans", "org_unit_id": unit},
                       app=self.full)["id"]
        self.step(need, "submit")
        self.ok("POST", "/need_candidates", {"need_id": need, "supplier_id": supplier, "selected": 1}, app=self.full)
        self.assertEqual(self.step(need, "select_existing")[1]["state"], "approval")

    def test_politika_degisince_kural_degisir(self):
        with self.db() as db:
            db.execute("UPDATE tdr_policies SET value_json='1' WHERE code='sourcing.min_quotes'")
        unit, _, supplier, _ = self.base_data()
        need = self.ok("POST", "/needs", {"code": "N3", "title": "x", "org_unit_id": unit}, app=self.full)["id"]
        self.step(need, "submit"), self.step(need, "request_quotes")
        self.ok("POST", "/quotes", {"need_id": need, "supplier_id": supplier, "amount": 1,
                                    "received_at": "2026-11-01"}, app=self.full)
        self.assertEqual(self.step(need, "evaluate")[0], 200)


class Aktarim(Base):
    CSV = ("Satıcı No;Tedarikçi Adı;VKN;ŞEHİR;Bilinmeyen\r\n"
           "100;Örnek Bilişim A.Ş.;1234567890;İstanbul;x\r\n"       # VKN ile eşleşir
           "200;Yeni Tedarikçi Ltd. Şti.;5555555555;Ankara;x\r\n"   # yeni
           "300;DİĞER LTD;;İzmir;x\r\n"                             # ad benzerliği: inceleme
           "400;;;;x\r\n")                                          # ad yok: hata

    def send(self, dry_run=False, source="sap"):
        return self.ok("POST", "/import/suppliers", {
            "source_system": source, "filename": "sap.csv", "dry_run": dry_run,
            "content_base64": base64.b64encode(self.CSV.encode("utf-8-sig")).decode()})

    def test_eslestirme_ve_tekrar_aktarim(self):
        *_, supplier, _ = self.base_data()
        self.ok("POST", "/suppliers", {"code": "S2", "name": "Diğer Ltd."})
        preview = self.send(dry_run=True)
        self.assertEqual({k: preview[k] for k in ("total", "create", "update", "review", "error")},
                         {"total": 4, "create": 1, "update": 1, "review": 1, "error": 1})
        self.assertEqual(len(self.ok("GET", "/suppliers")), 2)          # deneme çalıştırması veri yazmaz
        result = self.send()
        self.assertEqual((result["create"], result["update"], result["unmapped_columns"]), (1, 1, ["Bilinmeyen"]))
        self.assertEqual(len(self.ok("GET", "/suppliers")), 3)
        updated = self.ok("GET", f"/suppliers/{supplier}")
        self.assertEqual((updated["city"], updated["name"]), ("İstanbul", "Örnek Bilişim A.Ş."))
        refs = self.ok("GET", f"/source_refs?supplier_id={supplier}")
        self.assertEqual((refs[0]["source_system"], refs[0]["external_id"]), ("sap", "100"))
        again = self.send()                                              # aynı dosya: çoğaltma olmaz
        self.assertEqual((again["create"], again["update"], again["skip"]), (0, 0, 2))
        self.assertEqual(len(self.ok("GET", "/suppliers")), 3)

    def test_disa_aktarim_formul_enjeksiyonunu_etkisizlestirir(self):
        self.ok("POST", "/suppliers", {"code": "S9", "name": "=HYPERLINK(\"http://x\")"})
        status, raw = self.call("GET", "/export/suppliers")
        self.assertEqual(status, 200)
        self.assertTrue(raw.content.startswith("\ufeffKayıt No;Kod;Ad"))
        self.assertIn("'=HYPERLINK", raw.content)


if __name__ == "__main__":
    unittest.main()
