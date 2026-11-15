"""Demo verisi: boş veritabanına bir kez yüklenir, iş kurallarıyla tutarlıdır, ekranların uç noktaları çalışır."""
import unittest

from test_tedarik import Base
from tedarik import demo


class Demo(Base):
    def test_yukleme_tutarli_ve_tekrarsiz(self):
        passwords = demo.seed(self.app)
        self.assertEqual({p[0] for p in passwords}, {u[0] for u in demo.USERS})
        self.assertIsNone(demo.seed(self.app))                      # ikinci kez yüklenmez
        suppliers = self.ok("GET", "/suppliers?limit=1000")
        self.assertEqual(len(suppliers), 45)
        self.assertTrue(all(s["code"].startswith("DMO-") for s in suppliers))
        with self.db() as db:
            from tedarik.db import rows
            # artık risk = olasılık × etki × (1 − azaltım) ve kabul kararları iştah içinde
            for a in rows(db, "SELECT * FROM tdr_risk_assessments"):
                self.assertAlmostEqual(float(a["residual"]), a["inherent"] * (1 - float(a["mitigation_pct"]) / 100), 4)
            for d in rows(db, "SELECT * FROM tdr_risk_decisions WHERE to_status='accepted'"):
                self.assertLessEqual(float(d["residual"]), float(d["appetite"]))
            # SLA "hedef tuttu" uygulamanın kuralıyla hesaplanmıştır
            for m in rows(db, "SELECT m.actual_value, m.met, d.target_value, d.direction FROM tdr_sla_measurements m "
                              "JOIN tdr_sla_definitions d ON d.id=m.sla_id"):
                ok = (m["actual_value"] >= m["target_value"]) if m["direction"] == "higher_better" \
                    else (m["actual_value"] <= m["target_value"])
                self.assertEqual(bool(m["met"]), ok)
            self.assertFalse(rows(db, "SELECT id FROM tdr_suppliers WHERE description NOT LIKE '%Sentetik%'"))
        # ekranların kullandığı uç noktalar dolu döner
        self.assertGreater(self.ok("GET", "/dashboard/summary")["suppliers"]["total"], 0)
        schedule = self.ok("GET", "/schedule")
        self.assertGreater(schedule["summary"]["review_overdue"], 0)
        campaigns = {c["code"]: c for c in self.ok("GET", "/survey_campaigns")}
        results = self.ok("GET", f"/survey_campaigns/{campaigns['MEM-2026-Y1']['id']}/results")
        self.assertGreater(results["submitted"], 20)
        anonymous = self.ok("GET", f"/survey_campaigns/{campaigns['IC-MEM-2026']['id']}/results")
        self.assertEqual(anonymous["submitted"], 8)
        self.assertFalse(anonymous["hidden"])

    def test_demo_disi_veriye_yuklenmez(self):
        self.base_data()
        with self.assertRaises(SystemExit):
            demo.seed(self.app)


if __name__ == "__main__":
    unittest.main()
