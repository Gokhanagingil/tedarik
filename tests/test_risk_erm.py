"""Kurumsal risk yönetimi (ISO 31000, K-018): şirket, seviye, hedef risk, iştah, KRİ, dönem, ısı haritası."""
import unittest
from datetime import date, timedelta

from test_tedarik import KEY, Base


class KurumsalRisk(Base):
    def risk(self, **extra):
        body = {"title": "Kritik yamada gecikme", "category": "technology", "owner": "okan", "likelihood": 4,
                "impact": 4, "entity_name": "Sunucu filosu", "cause": "Yamalar hedef sürede uygulanmadığı için",
                "risk_event": "bilinen zafiyet istismar edilebilir", "consequence": "hizmet kesintisi",
                "review_date": (date.today() + timedelta(days=90)).isoformat(), **extra}
        return self.ok("POST", "/supplier_risks", body)["id"]

    def test_sirket_varsayilan_ve_musteri_ayrimi(self):
        own = self.ok("GET", "/companies")[0]
        self.assertEqual(own["kind"], "own")
        rid = self.risk()
        risk = self.ok("GET", f"/supplier_risks/{rid}")
        self.assertEqual((risk["company_id"], risk["source"], risk["inherent_score"], risk["risk_level"]),
                         (own["id"], "manual", 16, "critical"))
        self.assertTrue(risk["code"].startswith("RSK-"))
        customer = self.ok("POST", "/companies", {"name": "Müşteri Bankası A.Ş.", "kind": "customer"})["id"]
        self.ok("POST", "/companies", {"name": "İkinci Grup Şirketi", "kind": "own"})
        body = {"title": "x", "category": "technology", "owner": "a", "entity_name": "y"}
        auto = self.ok("POST", "/supplier_risks", body)["id"]          # şirket seçilmezse politikadaki varsayılan şirket
        self.assertEqual(self.ok("GET", f"/supplier_risks/{auto}")["company_id"], own["id"])
        policy = next(p for p in self.ok("GET", "/policies") if p["code"] == "core.default_company")
        self.ok("PATCH", f"/policies/{policy['id']}", {"value_json": "null"})
        self.assertEqual(self.call("POST", "/supplier_risks", body)[0], 400)    # varsayılan yok, iki kendi şirket: seçim zorunlu
        rid2 = self.risk(company_id=customer)
        self.assertEqual(self.ok("GET", f"/supplier_risks?company_id={customer}")[0]["id"], rid2)

    def test_hedef_risk_firsat_ve_istah_beyani(self):
        self.assertEqual(self.call("POST", "/supplier_risks", {"title": "x", "category": "technology", "owner": "a",
                                                               "entity_name": "y", "likelihood": 2, "impact": 2,
                                                               "target_likelihood": 3, "target_impact": 3})[0], 400)
        self.assertEqual(self.call("POST", "/supplier_risks", {"title": "x", "category": "strategic", "owner": "a",
                                                               "entity_name": "y", "response_strategy": "exploit"})[0], 400)
        self.ok("POST", "/supplier_risks", {"title": "Yeni pazar", "category": "strategic", "owner": "a", "entity_name": "y",
                                            "risk_type": "opportunity", "response_strategy": "exploit"})
        self.ok("POST", "/risk_appetites", {"category": "technology", "appetite": 6, "tolerance": 10,
                                            "statement": "Teknoloji risklerinde düşük iştah"})
        self.assertEqual(self.call("POST", "/risk_appetites", {"category": "legal", "appetite": 10, "tolerance": 5,
                                                               "statement": "x"})[0], 400)
        risk = self.ok("GET", f"/supplier_risks/{self.risk()}")
        self.assertEqual(risk["appetite"], 6)                                   # kategorinin iştah beyanından
        self.assertEqual(self.ok("GET", f"/supplier_risks/{risk['id']}/context")["appetite_statement"]["tolerance"], 10)
        self.assertEqual(self.call("POST", "/risk_appetites", {"category": "technology", "appetite": 5, "tolerance": 9,
                                                               "statement": "ikinci"})[0], 409)

    def test_degerlendirme_seviye_ve_donem(self):
        today = date.today()
        cycle = self.ok("POST", "/risk_cycles", {"name": "2026 4. çeyrek risk değerlendirmesi",
                                                 "period_start": (today - timedelta(days=10)).isoformat(),
                                                 "period_end": (today + timedelta(days=20)).isoformat()})["id"]
        self.ok("PATCH", f"/risk_cycles/{cycle}", {"status": "open"})
        rid, other = self.risk(), self.risk(title="Destek süresi biten işletim sistemi")
        result = self.ok("POST", f"/supplier_risks/{rid}/assessments", {
            "rationale": "Yama yönetimi kontrolü test edildi", "mitigations": [{"title": "Yama süreci", "weight": "high"}]})
        self.assertAlmostEqual(result["residual"], 6.4)
        risk = self.ok("GET", f"/supplier_risks/{rid}")
        self.assertEqual((risk["residual_score"], risk["risk_level"]), (6.4, "medium"))
        self.assertEqual(self.ok("GET", f"/risk_assessments?risk_id={rid}")[0]["cycle_id"], cycle)
        progress = self.ok("GET", f"/risk_cycles/{cycle}/context")
        self.assertEqual((progress["in_scope"], progress["assessed"], progress["progress_pct"]), (2, 1, 50.0))
        self.assertEqual({r["id"]: bool(r["assessed_in_cycle"]) for r in progress["risks"]}, {rid: True, other: False})
        overview = self.ok("GET", "/risks/overview")
        self.assertEqual(overview["heat"][3][3], 2)                              # olasılık 4 × etki 4
        self.assertEqual((overview["levels"]["medium"], overview["levels"]["critical"]), (1, 1))
        self.assertEqual(overview["unassessed"], 1)
        self.assertEqual(overview["cycles"][0]["assessed"], 1)
        self.ok("PATCH", f"/risk_cycles/{cycle}", {"status": "closed"})
        self.assertEqual(self.call("PATCH", f"/risk_cycles/{cycle}", {"name": "değişti"})[0], 409)

    def test_kri_esikleri_ve_mcp_olcumu(self):
        rid = self.risk()
        self.assertEqual(self.call("POST", "/kris", {"risk_id": rid, "name": "Yaması gecikmiş sunucu", "threshold_amber": 10,
                                                     "threshold_red": 5})[0], 400)
        kri = self.ok("POST", "/kris", {"risk_id": rid, "name": "Yaması gecikmiş sunucu", "unit": "adet",
                                        "threshold_amber": 5, "threshold_red": 10})["id"]
        self.ok("POST", "/kri_values", {"kri_id": kri, "period": "2026-09-01", "value": 3})
        self.ok("POST", "/kri_values", {"kri_id": kri, "period": "2026-10-01", "value": 12})
        made = self.app.dispatch("POST", "/api/tdr/kri_values", {"X-API-Key": KEY},
                                 b'{"kri_id": %d, "period": "2026-11-01", "value": 7}' % kri)
        self.assertEqual(made[0], 201)
        values = {v["period"]: (v["status"], v["source"]) for v in self.ok("GET", f"/kri_values?kri_id={kri}")}
        self.assertEqual(values, {"2026-09-01": ("green", "manual"), "2026-10-01": ("red", "manual"),
                                  "2026-11-01": ("amber", "mcp")})
        self.assertEqual(self.ok("GET", f"/kris/{kri}")["last_status"], "amber")
        self.ok("POST", "/kri_values", {"kri_id": kri, "period": "2026-08-01", "value": 1})   # geçmiş dönem sonu değiştirmez
        self.assertEqual(self.ok("GET", f"/kris/{kri}")["last_value"], 7)
        with self.db() as db, self.assertRaises(Exception):
            db.execute("UPDATE tdr_kri_values SET value=0")
        self.assertEqual(self.call("POST", "/kri_values", {"kri_id": kri, "period": "2026-11-01", "value": 1})[0], 409)

    def test_gec_kaydin_sirket_gocu(self):
        from tedarik.migrate import _risk_company_and_scores
        rid = self.risk()
        with self.db() as db:
            db.execute("UPDATE tdr_supplier_risks SET company_id=NULL, risk_level=NULL WHERE id=?", (rid,))
            _risk_company_and_scores(db)
            row = db.execute("SELECT company_id, risk_level FROM tdr_supplier_risks WHERE id=?", (rid,)).fetchone()
        self.assertEqual((row["company_id"], row["risk_level"]), (self.ok("GET", "/companies")[0]["id"], "critical"))


if __name__ == "__main__":
    unittest.main()
