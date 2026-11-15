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
        self.assertTrue(all(s["code"].startswith("TED-") for s in suppliers))      # kodları sunucu üretir (K-017)
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
        campaigns = {c["name"]: c for c in self.ok("GET", "/survey_campaigns")}
        results = self.ok("GET", f"/survey_campaigns/{campaigns['2026 ilk yarı tedarikçi memnuniyeti']['id']}/results")
        self.assertGreater(results["submitted"], 20)
        anonymous = self.ok("GET", f"/survey_campaigns/{campaigns['Satın alma süreci iç müşteri memnuniyeti']['id']}/results")
        self.assertEqual(anonymous["submitted"], 8)
        self.assertFalse(anonymous["hidden"])
        # GRC platformu bölümleri: şirketler, kurumsal risk, CMDB, iş sürekliliği, dokümanlar
        companies = {c["name"]: c for c in self.ok("GET", "/companies")}
        self.assertEqual(companies["Demo Banka A.Ş."]["kind"], "customer")
        overview = self.ok("GET", "/risks/overview")
        self.assertGreater(len(overview["by_company"]), 3)
        self.assertGreater(overview["opportunities"], 0)
        self.assertTrue(any(c["status"] == "open" and c["assessed"] for c in overview["cycles"]))
        cmdb = self.ok("GET", "/cmdb/status")
        self.assertEqual(cmdb["unmapped_company"], 1)
        self.assertEqual({e["key"] for e in cmdb["exposures"]}, {"os_eos", "app_eos", "patch", "uptime"})
        cmdb_risks = self.ok("GET", "/supplier_risks?source=cmdb_rule")
        self.assertIn(companies["Demo Banka A.Ş."]["id"], {r["company_id"] for r in cmdb_risks})   # müşteri riski
        bcm = self.ok("GET", "/bcm/overview")
        self.assertEqual(bcm["rto_gaps"][0]["achieved_recovery_minutes"], 290)
        bia = self.ok("GET", f"/bias/{self.ok('GET', '/bias?status=approved')[0]['id']}/context")
        self.assertTrue(bia["mtpd_hours"] and bia["applications"] and bia["impacts"])
        docs = self.ok("GET", "/documents-overview")
        self.assertTrue(docs["awaiting_approval"])
        with self.db() as db:
            from tedarik.db import rows
            for d in rows(db, "SELECT * FROM tdr_documents WHERE status='published'"):
                self.assertTrue(rows(db, "SELECT id FROM tdr_document_revisions WHERE document_id=? AND revision=?",
                                     (d["id"], d["current_revision"])))
            for r in rows(db, "SELECT * FROM tdr_supplier_risks"):       # özet puanlar son değerlendirmeyle tutarlı
                last = rows(db, "SELECT residual FROM tdr_risk_assessments WHERE risk_id=? ORDER BY assessed_at DESC, id DESC "
                                "LIMIT 1", (r["id"],))
                self.assertEqual(r["residual_score"], float(last[0]["residual"]) if last else None)
        self.assertGreater(self.ok("GET", "/health-check")["score"], 0)

    def test_eski_demoya_bolum_eklenir(self):
        from unittest import mock
        older = tuple(x for x in demo.SECTIONS if x[0] not in ("cmdb", "continuity", "audit_scope"))
        with mock.patch.object(demo, "SECTIONS", older):            # önceki sürüm: CMDB ve süreklilik bölümü yok
            demo.seed(self.app)
        self.assertEqual(self.ok("GET", "/bias"), [])
        self.assertEqual(demo.seed(self.app), {"added": ["cmdb", "continuity", "audit_scope"]})
        self.assertTrue(any(a["processes"] for a in (self.ok("GET", f"/audits/{x['id']}/context") for x in self.ok("GET", "/audits"))))
        self.assertIsNone(demo.seed(self.app))
        self.assertTrue(self.ok("GET", "/bias"))

    def test_demo_disi_veriye_yuklenmez(self):
        self.base_data()
        with self.assertRaises(SystemExit):
            demo.seed(self.app)


if __name__ == "__main__":
    unittest.main()
