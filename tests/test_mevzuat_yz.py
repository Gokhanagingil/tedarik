"""Veri yönetişimi Faz 6 — KVKK/GDPR boşluk analizi (K-033), yapay zekâ envanteri ve AB Yapay Zekâ Tüzüğü risk
sınıflandırması (K-034), rol ve yetki matrisi (K-035). Test verisi sentetiktir."""
import gzip
import json
import unittest
from pathlib import Path

from test_kvkk import KvkkBase, day
from test_tedarik import KEY, Base
from tedarik.modules import ai_inventory

LIB = Path(__file__).resolve().parent.parent / "tedarik" / "data" / "standards"


class MevzuatPaketleri(unittest.TestCase):
    def test_kvkk_ve_gdpr_tam_metin_ve_kaynak(self):
        kvkk = json.load(gzip.open(LIB / "kvkk-6698.json.gz"))
        arts = [c for c in kvkk["clauses"] if c["type"] == "article"]
        self.assertEqual(len(arts), 36)                                   # 33 madde + 3 geçici madde
        self.assertEqual(sum(1 for c in arts if c.get("applicable", True)), 12)
        md5 = next(c for c in arts if c["code"] == "md. 5")
        self.assertIn("açık rızası olmaksızın", md5["text"])
        self.assertTrue(kvkk["sources"][0]["url"].startswith("https://www.mevzuat.gov.tr/"))
        self.assertEqual(len(kvkk["sources"][0]["sha256"]), 64)
        gdpr = json.load(gzip.open(LIB / "gdpr-2016-679.json.gz"))
        self.assertEqual(sum(1 for c in gdpr["clauses"] if c["type"] == "article"), 99)
        self.assertEqual(sum(1 for c in gdpr["clauses"] if c["code"].startswith("Rec. ")), 173)
        art33 = next(c for c in gdpr["clauses"] if c["code"] == "Art. 33")
        self.assertIn("72 hours", art33["text"])
        self.assertIn("eur-lex.europa.eu", gdpr["sources"][0]["url"])


class BoslukAnalizi(KvkkBase):
    def install(self, *keys):
        for k in keys:
            self.assertEqual(self.call("POST", "/standards/library/install", {"key": k})[0], 201)

    def article(self, code, art):
        return next(a for a in self.ok("GET", f"/datagov/regulation?code={code}")["articles"] if a["code"] == art)

    def test_kurulum_gostergeler_degerlendirme_bulgu(self):
        r = self.ok("GET", "/datagov/regulation?code=KVKK")
        self.assertEqual((r["installed"], r["library_key"], r["can_install"]), (False, "kvkk-6698", True))
        self.assertEqual(self.call("GET", "/datagov/regulation?code=CCPA")[0], 400)
        self.install("kvkk-6698")
        r = self.ok("GET", "/datagov/regulation?code=KVKK")
        self.assertEqual((r["applicable"], len(r["articles"]), r["score"]), (12, 36, None))
        self.assertEqual(r["counts"], {"not_assessed": 12})                # veri yokken uyumlu sayılmaz
        # kişisel veri içeren tablo: envanter ve saklama açığı
        self.ok("PATCH", f"/data_columns/{self.col['TCKN']}", {"personal_data": "personal"})
        aid = self.ok("POST", "/processing_activities", {"name": "Müşteri iletişimi", "purpose": "Sipariş bilgilendirmesi"})["id"]
        md5 = self.article("KVKK", "md. 5")
        self.assertEqual(md5["auto_status"], "non_compliant")
        legal = md5["indicators"][0]
        self.assertEqual((legal["key"], legal["population"], legal["gaps"]), ("legal_basis", 1, 1))
        self.assertEqual(legal["items"][0]["link"], f"#/activity/{aid}")
        md16 = self.article("KVKK", "md. 16")
        inv = md16["indicators"][0]
        self.assertTrue(any(i["link"] == f"#/catalog/table/{self.musteri}" for i in inv["items"]))
        md4 = self.article("KVKK", "md. 4")
        self.assertEqual(md4["status"], "non_compliant")
        self.ok("PATCH", f"/processing_activities/{aid}", {"legal_basis": "contract"})
        self.assertEqual(self.article("KVKK", "md. 5")["auto_status"], "compliant")
        # değerlendirme: kısmen/uyumsuzda not zorunlu; otomatik durum yan yana kalır
        cid = md4["id"]
        self.assertEqual(self.call("POST", "/datagov/regulation/assess", {"clause_id": cid, "status": "partial"})[0], 400)
        self.assertEqual(self.call("POST", "/datagov/regulation/assess", {"clause_id": cid, "status": "bogus"})[0], 400)
        self.ok("POST", "/datagov/regulation/assess", {"clause_id": cid, "status": "partial", "note": "Saklama süreleri CRM için belirlenmedi",
                                                       "owner": "kvkk.sorumlusu", "due_date": day(30)})
        md4 = self.article("KVKK", "md. 4")
        self.assertEqual((md4["status"], md4["auto_status"], md4["assessment"]["assessed_by"]), ("partial", "non_compliant", "dev"))
        self.ok("POST", "/datagov/regulation/assess", {"clause_id": cid, "status": "partial", "note": "Saklama süreleri CRM için belirlenmedi; taslak hazır"})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS n FROM tdr_regulation_assessments").fetchone()["n"], 1)
        # bulgu ve DÖF
        f = self.ok("POST", "/datagov/regulation/finding", {"clause_id": cid, "owner": "kvkk.sorumlusu", "due_date": day(30)})
        self.assertTrue(f["code"].startswith("BLG-") and f["action_id"])
        finding = self.ok("GET", f"/findings/{f['finding_id']}")
        self.assertEqual((finding["source"], finding["clause_id"]), ("self_assessment", cid))
        self.assertEqual(self.article("KVKK", "md. 4")["open_findings"], 1)
        self.assertEqual(self.call("POST", "/datagov/regulation/finding", {"clause_id": 999999, "description": "x" * 20})[0], 404)
        # NIST maddesi mevzuat değerlendirmesine konamaz
        self.install("nist-csf-2")
        with self.db() as db:
            nist = db.execute("SELECT c.id FROM tdr_clauses c JOIN tdr_standards s ON s.id=c.standard_id WHERE s.code<>'KVKK' LIMIT 1").fetchone()["id"]
        self.assertEqual(self.call("POST", "/datagov/regulation/assess", {"clause_id": nist, "status": "compliant"})[0], 404)

    def test_yetkiler_ve_kvkk_gdpr_eslemesi(self):
        self.install("kvkk-6698")
        self.assertEqual(self.call("POST", "/datagov/regulation/crosswalk", {})[0], 409)   # GDPR kurulu değil
        self.install("gdpr-2016-679")
        r = self.ok("POST", "/datagov/regulation/crosswalk", {})
        self.assertEqual((r["added"], r["links"]), (26, 26))
        self.assertEqual(self.ok("POST", "/datagov/regulation/crosswalk", {})["added"], 0)
        gdpr = self.ok("GET", "/datagov/regulation?code=GDPR")
        self.assertEqual(gdpr["crosswalk"]["links"], 26)
        self.assertGreater(gdpr["applicable"], 40)
        art33 = next(a for a in gdpr["articles"] if a["code"] == "Art. 33")
        self.assertEqual(art33["indicators"][0]["key"], "breach")
        md12 = self.article("KVKK", "md. 12")
        with self.db() as db:
            links = db.execute("""SELECT COUNT(*) AS n FROM tdr_clause_links WHERE from_clause_id=? AND source='crosswalk'""",
                               (md12["id"],)).fetchone()["n"]
        self.assertEqual(links, 4)                                       # Art. 28, 32, 33, 34
        viewer = self.make(role="VIEWER", user="izleyici")
        v = self.ok("GET", "/datagov/regulation?code=KVKK", app=viewer)
        self.assertFalse(v["can_edit"] or v["can_finding"] or v["can_library"])
        self.assertEqual(self.call("POST", "/datagov/regulation/assess", {"clause_id": md12["id"], "status": "compliant"}, app=viewer)[0], 403)
        auditor = self.make(role="AUDITOR", user="denetci")
        self.assertEqual(self.call("POST", "/datagov/regulation/assess", {"clause_id": md12["id"], "status": "compliant"}, app=auditor)[0], 403)
        self.assertTrue(self.ok("GET", "/datagov/regulation?code=KVKK", app=auditor)["can_finding"])
        manager = self.make(role="SUPPLIER_MANAGER", user="kvkk.sorumlusu")
        self.ok("POST", "/datagov/regulation/assess", {"clause_id": md12["id"], "status": "compliant"}, app=manager)
        self.assertEqual(self.call("POST", "/datagov/regulation/finding", {"clause_id": md12["id"], "description": "Deneme açığı metni"},
                                   app=manager)[0], 403)

    def test_ihlal_ve_basvuru_gostergeleri(self):
        self.install("gdpr-2016-679")
        self.ok("POST", "/privacy_breaches", {"title": "E-posta yanlış alıcıya", "owner": "kvkk.sorumlusu", "description": "Toplu e-posta",
                                              "detected_at": f"{day(-5)}T09:00:00+03:00"})
        art33 = next(a for a in self.ok("GET", "/datagov/regulation?code=GDPR")["articles"] if a["code"] == "Art. 33")
        self.assertEqual((art33["indicators"][0]["gaps"], art33["auto_status"]), (1, "non_compliant"))
        groups = {g["name"]: g["id"] for g in self.ok("GET", "/data_subject_groups?limit=100")}
        self.ok("POST", "/subject_requests", {"received_on": day(-40), "request_type": "access", "description": "Verilerimi istiyorum",
                                              "owner": "kvkk.sorumlusu", "subject_group_id": groups["Müşteri"]})
        art15 = next(a for a in self.ok("GET", "/datagov/regulation?code=GDPR")["articles"] if a["code"] == "Art. 15")
        self.assertEqual(art15["indicators"][0]["gaps"], 1)


class Siniflandirma(unittest.TestCase):
    def test_tuzuk_kurallari(self):
        c = ai_inventory.classify
        self.assertEqual(c({"prohibited": ["social_scoring"], "annex_iii": ["credit"]})["risk_class"], "prohibited")
        high = c({"annex_iii": ["employment"]}, "deployer")
        self.assertEqual(high["risk_class"], "high")
        refs = {o["ref"] for o in high["obligations"]}
        self.assertTrue({"md. 4", "md. 26(2)", "md. 26(6)"} <= refs and "md. 17" not in refs and not high["fria_required"])
        self.assertIn("md. 17", {o["ref"] for o in c({"annex_iii": ["employment"]}, "provider")["obligations"]})
        # md. 6(3) istisnası; profil çıkarmada uygulanmaz
        derog = c({"annex_iii": ["education"], "derogation": "preparatory"})
        self.assertEqual(derog["risk_class"], "minimal")
        self.assertIn("md. 6(4)", {o["ref"] for o in derog["obligations"]})
        self.assertEqual(c({"annex_iii": ["education"], "derogation": "preparatory", "profiling": True})["risk_class"], "high")
        self.assertEqual(c({"annex_iii": ["education"], "derogation": "preparatory", "transparency": ["interacts"]})["risk_class"], "limited")
        # FRIA: kredi puanlama veya kamu hizmeti
        self.assertTrue(c({"annex_iii": ["credit"]})["fria_required"])
        self.assertTrue(c({"annex_iii": ["employment"], "public_service": True})["fria_required"])
        self.assertEqual(c({"product_safety": True})["risk_class"], "high")
        lim = c({"transparency": ["interacts", "synthetic"]})
        self.assertEqual(lim["risk_class"], "limited")
        self.assertIn("md. 50(2)", {o["ref"] for o in lim["obligations"]})
        self.assertEqual(c({})["risk_class"], "minimal")
        for bad in ({"prohibited": ["yok"]}, {"derogation": "x"}, {"annex_iii": "credit"}, []):
            with self.assertRaises(Exception):
                c(bad)


class YapayZekaEnvanteri(KvkkBase):
    def test_kayit_siniflandirma_veri_aciklar_ve_etki(self):
        self.assertEqual(self.ok("GET", "/datagov/ai")["active"], 0)
        sid = self.ok("POST", "/ai_systems", {"name": "Kredi ön skorlama", "purpose": "Bireysel kredi başvurusunu ön puanlama",
                                              "role": "deployer", "source_type": "vendor", "lifecycle": "production",
                                              "automated_decision": 1, "model_type": "classical_ml"})["id"]
        s = self.ok("GET", f"/ai_systems/{sid}")
        self.assertTrue(s["code"].startswith("YZS-"))
        self.assertEqual(s["risk_class"], "unassessed")
        self.assertEqual(self.call("PATCH", f"/ai_systems/{sid}", {"risk_class": "minimal"})[0], 400)   # sınıf elle girilmez
        ctx = self.ok("GET", f"/ai_systems/{sid}/context")
        self.assertTrue({"unassessed", "automated", "owner", "supplier", "data"} <= {g["key"] for g in ctx["gaps"]})
        r = self.ok("POST", f"/ai_systems/{sid}/classify", {"answers": {"annex_iii": ["credit"], "profiling": True}})
        self.assertEqual((r["risk_class"], r["fria_required"]), ("high", True))
        ctx = self.ok("GET", f"/ai_systems/{sid}/context")
        self.assertEqual(ctx["system"]["classified_by"], "dev")
        self.assertIn("Ek III madde 5(b)", ctx["system"]["risk_basis"])
        keys = {g["key"] for g in ctx["gaps"]}
        self.assertTrue({"oversight", "fria", "logs", "transparency", "evaluation"} <= keys and "unassessed" not in keys)
        # veri bağlantısı: kişisel veri ve işleme faaliyeti açığı
        self.ok("PATCH", f"/data_columns/{self.col['TCKN']}", {"personal_data": "personal"})
        self.assertEqual(self.call("POST", f"/ai_systems/{sid}/tables", {"items": [{"table_id": self.musteri, "usage": "bogus"}]})[0], 400)
        ctx = self.ok("POST", f"/ai_systems/{sid}/tables", {"items": [{"table_id": self.musteri, "usage": "training"},
                                                                      {"table_id": self.urun, "usage": "input"}]})
        self.assertEqual(len(ctx["tables"]), 2)
        keys = {g["key"] for g in ctx["gaps"]}
        self.assertTrue({"personal_flag", "activity", "dpia"} <= keys)
        self.assertEqual(self.ok("GET", f"/data_tables/{self.musteri}/ai-systems")[0]["usage"], "training")
        ctx = self.ok("POST", f"/ai_systems/{sid}/tables", {"items": [{"table_id": self.musteri, "usage": "training"}]})
        self.assertEqual(len(ctx["tables"]), 1)
        # açıkları kapat
        aid = self.ok("POST", "/processing_activities", {"name": "Kredi değerlendirme", "purpose": "Kredi başvurusu", "legal_basis": "contract"})["id"]
        self.ok("PATCH", f"/ai_systems/{sid}", {"owner": "kredi.muduru", "uses_personal_data": 1, "activity_id": aid,
                                                "human_oversight": "Ret önerileri kredi uzmanınca incelenir; müşteri itiraz edebilir",
                                                "log_retention_months": 12, "transparency_notice": 1, "fria_done_on": day(-10),
                                                "last_evaluated_on": day(-30)})
        keys = {g["key"] for g in self.ok("GET", f"/ai_systems/{sid}/context")["gaps"]}
        self.assertEqual(keys, {"dpia", "supplier"})
        self.assertEqual(self.call("PATCH", f"/ai_systems/{sid}", {"log_retention_months": 9999})[0], 400)
        # soy kütüğü etki analizi ve KVKK md. 11 göstergesi
        imp = self.ok("GET", f"/data_tables/{self.musteri}/impact")
        self.assertEqual([x["id"] for x in imp["ai_systems"]], [sid])
        self.assertTrue(any("Yapay zekâ sistemi sahibi" in p["roles"] for p in imp["people"]))
        self.install_kvkk()
        md11 = next(a for a in self.ok("GET", "/datagov/regulation?code=KVKK")["articles"] if a["code"] == "md. 11")
        auto = next(i for i in md11["indicators"] if i["key"] == "automated")
        self.assertEqual((auto["population"], auto["gaps"]), (1, 0))
        # sağlık kontrolü, liste, dışa aktarma
        overview = self.ok("GET", "/datagov/ai")
        self.assertEqual((overview["by_class"]["high"], overview["personal"], overview["automated"]), (1, 1, 1))
        status, raw = self.call("GET", "/datagov/ai/export")
        self.assertEqual(status, 200)
        sid2 = self.ok("POST", "/ai_systems", {"name": "Sohbet botu", "purpose": "Müşteri sorularını yanıtlama", "lifecycle": "pilot"})["id"]
        health = {x["key"]: x for x in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(health["ai_unassessed"]["count"], 1)
        self.assertEqual(health["ai_oversight"]["count"], 0)
        self.ok("POST", f"/ai_systems/{sid2}/classify", {"answers": {"prohibited": ["manipulation"]}})
        health = {x["key"]: x for x in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual((health["ai_prohibited"]["count"], health["ai_unassessed"]["count"]), (1, 0))
        self.ok("PATCH", f"/ai_systems/{sid}", {"review_date": day(10)})
        work = self.ok("GET", "/my-work", app=self.make(user="kredi.muduru"))
        self.assertEqual([i["id"] for i in work["ai_systems"]], [sid])

    def install_kvkk(self):
        self.assertEqual(self.call("POST", "/standards/library/install", {"key": "kvkk-6698"})[0], 201)

    def test_birim_kapsami_ve_yetki(self):
        other = self.ok("POST", "/org_units", {"name": "Pazarlama"})["id"]
        unit_user = self.make(role="UNIT_USER", user="birim.kullanici", units=str(self.unit))
        self.assertEqual(self.call("POST", "/ai_systems", {"name": "Kampanya önerici", "purpose": "Öneri", "org_unit_id": other},
                                   app=unit_user)[0], 403)
        mine = self.ok("POST", "/ai_systems", {"name": "Çağrı özetleyici", "purpose": "Çağrı kaydı özetleme", "org_unit_id": self.unit},
                       app=unit_user)["id"]
        self.ok("POST", f"/ai_systems/{mine}/classify", {"answers": {"transparency": ["synthetic"]}}, app=unit_user)
        theirs = self.ok("POST", "/ai_systems", {"name": "Kampanya önerici", "purpose": "Öneri", "org_unit_id": other})["id"]
        self.assertEqual(self.call("POST", f"/ai_systems/{theirs}/classify", {"answers": {}}, app=unit_user)[0], 403)
        self.assertFalse(self.ok("GET", f"/ai_systems/{theirs}/context", app=unit_user)["can_write"])
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertFalse(self.ok("GET", "/datagov/ai", app=viewer)["can_write"])
        self.assertEqual(self.call("POST", f"/ai_systems/{mine}/tables", {"items": []}, app=viewer)[0], 403)


class RolMatrisi(Base):
    def test_matris_koddan_hesaplanir(self):
        m = self.ok("GET", "/roles/matrix")
        roles = {r["code"]: r for r in m["roles"]}
        self.assertEqual(list(roles), ["ADMIN", "SUPPLIER_MANAGER", "UNIT_USER", "AUDITOR", "VIEWER"])
        self.assertEqual(roles["ADMIN"]["entra_role"], "KS.TDR.Admin")
        res = {r["name"]: r for r in m["resources"]}
        self.assertNotIn("user_roles", res)                               # API'siz eşleme tabloları listelenmez
        f = res["findings"]["roles"]
        self.assertEqual((f["AUDITOR"]["write"], f["SUPPLIER_MANAGER"]["write"], f["VIEWER"]["read"]), ("full", "none", True))
        self.assertEqual(res["subject_requests"]["roles"]["VIEWER"]["read"], False)
        self.assertEqual(res["grc_actions"]["roles"]["UNIT_USER"]["write"], "unit")
        self.assertEqual(res["executions"]["roles"]["AUDITOR"]["write"], "append")
        self.assertEqual(res["audit_log"]["path"], "system")
        self.assertEqual(res["audit_log"]["roles"]["ADMIN"]["write"], "none")
        self.assertEqual(res["ai_systems"]["roles"]["UNIT_USER"]["write"], "unit")
        self.assertEqual(res["controls"]["machine"], "r")
        self.assertTrue(any("VKED" in s["rule"] for s in m["segregation"]))
        self.assertEqual(len(m["special"]), 3)
        status, raw = self.call("GET", "/roles/matrix?format=csv")
        self.assertEqual(status, 200)
        for role, ok in (("AUDITOR", 200), ("VIEWER", 403), ("SUPPLIER_MANAGER", 403), ("UNIT_USER", 403)):
            self.assertEqual(self.call("GET", "/roles/matrix", app=self.make(role=role, user="u_" + role.lower()))[0], ok)
        self.assertEqual(self.call("GET", "/roles/matrix", headers={"X-API-Key": KEY})[0], 403)
        grc_off = self.make(modules="core,performance,surveys,risks,documents")
        names = {r["name"] for r in self.ok("GET", "/roles/matrix", app=grc_off)["resources"]}
        self.assertNotIn("findings", names)
        self.assertIn("suppliers", names)


if __name__ == "__main__":
    unittest.main()
