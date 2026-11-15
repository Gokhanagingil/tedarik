"""İş sürekliliği (ISO 22301, K-020): BİA, MTPD, onay, bağımlılıklar, planlar, tatbikatlar."""
import json
import unittest
from datetime import date, timedelta

from test_tedarik import KEY, Base


class Sureklilik(Base):
    def setUp(self):
        super().setUp()
        self.process = self.ok("POST", "/processes", {"name": "Ödeme işlemleri", "process_type": "core", "owner": "zeynep"})["id"]
        self.manager = self.make(role="SUPPLIER_MANAGER", user="ayse")
        payload = {"items": [{"sys_id": "a1", "name": "Ödeme Sistemi", "ci_class": "business_app",
                              "environment": "production", "eos_date": "2020-01-31", "business_criticality": "critical"}]}
        self.app.dispatch("POST", "/api/tdr/cmdb/cis/bulk", {"X-API-Key": KEY}, json.dumps(payload).encode())
        self.ci = self.ok("GET", "/cmdb_cis")[0]["id"]
        self.bia = self.ok("POST", "/bias", {"title": "Ödeme işlemleri BİA", "process_id": self.process, "owner": "zeynep",
                                             "rto_hours": 2, "rpo_hours": 0.25})["id"]

    def impacts(self, levels):
        windows = ["h1", "h4", "h8", "d1", "d3", "w1", "w2", "m1"]
        return {"impacts": [{"category": category, "time_window": w, "level": lvl}
                            for category, row in levels.items() for w, lvl in zip(windows, row)]}

    def test_mtpd_turetimi_ve_rto_kurali(self):
        bad = self.impacts({"financial": [1, 2, 4, 3, 5, 5, 5, 5]})                 # zamanla azalan etki
        self.assertEqual(self.call("POST", f"/bias/{self.bia}/impacts", bad)[0], 400)
        result = self.ok("POST", f"/bias/{self.bia}/impacts", self.impacts({
            "financial": [1, 2, 3, 4, 5, 5, 5, 5], "customer": [2, 3, 4, 5, 5, 5, 5, 5]}))
        self.assertEqual((result["mtpd_hours"], result["criticality"]), (8, "high"))   # müşteri etkisi 8 saatte 4
        self.assertEqual(self.call("PATCH", f"/bias/{self.bia}", {"rto_hours": 10})[0], 400)   # RTO > MTPD
        self.ok("PATCH", f"/bias/{self.bia}", {"rto_hours": 3})
        self.assertTrue(self.ok("GET", f"/bias/{self.bia}")["code"].startswith("BIA-"))

    def test_onay_dort_goz_revizyon_ve_kilit(self):
        self.assertEqual(self.call("POST", f"/bias/{self.bia}/transition", {"action": "submit"})[0], 400)   # matris yok
        self.ok("POST", f"/bias/{self.bia}/impacts", self.impacts({"operational": [1, 2, 3, 4, 4, 5, 5, 5]}))
        self.ok("POST", f"/bias/{self.bia}/transition", {"action": "submit"})
        zeynep = self.make(role="SUPPLIER_MANAGER", user="zeynep")
        self.assertEqual(self.call("POST", f"/bias/{self.bia}/transition", {"action": "approve"}, app=zeynep)[0], 403)
        approved = self.ok("POST", f"/bias/{self.bia}/transition", {"action": "approve"}, app=self.manager)
        self.assertEqual((approved["status"], approved["approved_by"]), ("approved", "ayse"))
        self.assertTrue(approved["review_date"])
        self.assertEqual(self.call("PATCH", f"/bias/{self.bia}", {"rto_hours": 1})[0], 409)
        self.assertEqual(self.call("POST", "/bia_applications", {"bia_id": self.bia, "ci_id": self.ci})[0], 409)
        self.ok("POST", f"/bias/{self.bia}/transition", {"action": "revise"})
        self.ok("POST", "/bia_applications", {"bia_id": self.bia, "ci_id": self.ci, "required_rto_hours": 2})
        self.assertEqual(self.ok("GET", f"/bias/{self.bia}")["status"], "draft")

    def test_bagimliliklar_ve_aciklar(self):
        supplier = self.ok("POST", "/suppliers", {"name": "Ödeme Altyapısı A.Ş.", "tier": "critical"})["id"]
        self.ok("POST", "/supplier_risks", {"title": "Tek ödeme sağlayıcısı", "category": "concentration", "owner": "a",
                                            "supplier_id": supplier})
        self.ok("POST", "/bia_applications", {"bia_id": self.bia, "ci_id": self.ci})
        self.ok("POST", "/bia_suppliers", {"bia_id": self.bia, "supplier_id": supplier})
        context = self.ok("GET", f"/bias/{self.bia}/context")
        self.assertEqual(context["applications"][0]["exposures"][0]["rule"], "app_eos")      # CMDB kuralından
        self.assertEqual(context["suppliers"][0]["open_risks"], 1)
        self.assertEqual(len(context["gaps"]), 2)
        self.assertEqual(self.ok("GET", f"/cmdb_cis/{self.ci}/context")["bias"][0]["id"], self.bia)
        unit_user = self.make(role="UNIT_USER", user="birim", units="")
        self.assertEqual(self.call("PATCH", f"/bias/{self.bia}", {"description": "x"}, app=unit_user)[0], 403)

    def test_plan_tatbikat_ve_bulgu(self):
        self.ok("POST", f"/bias/{self.bia}/impacts", self.impacts({"operational": [1, 2, 3, 4, 4, 5, 5, 5]}))
        plan = self.ok("POST", "/bc_plans", {"title": "Ödeme sistemi felaket kurtarma planı", "plan_type": "drp",
                                             "owner": "mehmet"}, app=self.manager)["id"]
        self.ok("POST", f"/bc_plans/{plan}/bias", {"bia_ids": [self.bia]}, app=self.manager)
        self.assertEqual(self.call("POST", f"/bc_plans/{plan}/transition", {"action": "approve"})[0], 400)   # adım yok
        self.ok("POST", "/bc_plan_steps", {"plan_id": plan, "phase": "activation", "action": "Kriz ekibini topla",
                                           "responsible": "BT nöbetçi", "target_minutes": 15})
        self.ok("POST", "/bc_plan_steps", {"plan_id": plan, "phase": "recovery", "action": "DR sitesine geç",
                                           "target_minutes": 90})
        self.assertEqual(self.call("POST", f"/bc_plans/{plan}/transition", {"action": "approve"}, app=self.manager)[0], 403)
        self.ok("POST", f"/bc_plans/{plan}/transition", {"action": "approve"})        # hazırlayan ayse, onaylayan dev
        self.assertEqual(self.call("POST", "/bc_plan_steps", {"plan_id": plan, "action": "ekle"})[0], 409)
        exercise = self.ok("POST", "/bc_exercises", {"title": "2026 DR testi", "exercise_type": "full_scale", "plan_id": plan,
                                                     "scenario": "Birincil veri merkezi erişilemez",
                                                     "planned_date": date.today().isoformat()})["id"]
        made = self.ok("GET", f"/bc_exercises/{exercise}")
        self.assertEqual((made["target_recovery_minutes"], made["code"][:4]), (120, "TAT-"))     # BİA RTO 2 saat
        done = {"status": "completed", "actual_date": date.today().isoformat(), "achieved_recovery_minutes": 150,
                "outcome": "successful", "lessons_learned": "Veritabanı geçişi yavaş"}
        self.assertEqual(self.call("PATCH", f"/bc_exercises/{exercise}", done)[0], 400)        # hedef aşıldı, başarılı olamaz
        self.assertEqual(self.call("PATCH", f"/bc_exercises/{exercise}", {**done, "outcome": "partially_successful",
                                                                          "lessons_learned": ""})[0], 400)
        self.ok("PATCH", f"/bc_exercises/{exercise}", {**done, "outcome": "partially_successful"})
        manager = self.make(role="SUPPLIER_MANAGER", user="bcm.yoneticisi")     # tatbikatı yönetir ama bulgu açamaz
        self.assertEqual(self.call("POST", f"/bc_exercises/{exercise}/findings", {"title": "x"}, app=manager)[0], 403)
        finding = self.ok("POST", f"/bc_exercises/{exercise}/findings", {"title": "Kurtarma hedef süreyi aştı",
                                                                        "severity": "high", "owner": "mehmet"})["finding_id"]
        context = self.ok("GET", f"/bc_exercises/{exercise}/context")
        self.assertEqual((context["gap_minutes"], context["findings"][0]["id"]), (30, finding))
        self.assertEqual(self.call("PATCH", f"/bc_exercises/{exercise}", {"scenario": "x"})[0], 409)
        overview = self.ok("GET", "/bcm/overview")
        self.assertEqual((overview["plans_total"], len(overview["rto_gaps"]), overview["exercises_year"]), (1, 1, 1))
        self.assertEqual(self.ok("GET", f"/bc_plans/{plan}/context")["exercise_due"],
                         (date.today() + timedelta(days=365)).isoformat())


if __name__ == "__main__":
    unittest.main()
