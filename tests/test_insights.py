"""İlişkiler ve içgörüler: kayıt bağlamları, GRC takvimi, İşlerim, sağlık kontrolü, arama, ilişki modeli, süreç haritası."""
import unittest
from datetime import date, timedelta

from test_tedarik import Base


class Icgoruler(Base):
    def setUp(self):
        super().setUp()
        self.process = self.ok("POST", "/processes", {"name": "Tedarikçi yönetimi", "process_type": "core"})["id"]
        self.objective = self.ok("POST", "/objectives", {"name": "Kritik tedarikçiler izlenir", "process_id": self.process})["id"]
        self.control = self.ok("POST", "/controls", {"name": "Değerlendirme kontrolü", "owner": "dev", "frequency": "monthly"})["id"]
        self.ok("POST", f"/controls/{self.control}/links", {"objectives": [self.objective], "processes": [self.process]})
        self.risk = self.ok("POST", "/supplier_risks", {"title": "Tek tedarikçi", "category": "concentration", "owner": "dev",
                                                       "entity_name": "Ödeme", "likelihood": 4, "impact": 5,
                                                       "process_id": self.process,
                                                       "review_date": (date.today() + timedelta(days=10)).isoformat()})["id"]

    def test_kontrol_hedefi_ve_surec_baglami(self):
        self.ok("POST", f"/objectives/{self.objective}/risks", {"risk_ids": [self.risk]})
        objective = self.ok("GET", f"/objectives/{self.objective}/context")
        self.assertEqual(([k["id"] for k in objective["controls"]], [r["id"] for r in objective["risks"]],
                          objective["process"]["id"]), ([self.control], [self.risk], self.process))
        self.ok("POST", "/executions", {"control_id": self.control, "status": "pass"})
        self.assertEqual(self.ok("GET", f"/objectives/{self.objective}/context")["effectiveness"],
                         {"controls": 1, "tested": 1, "passed": 1})
        process = self.ok("GET", f"/processes/{self.process}/context")
        self.assertEqual(([r["id"] for r in process["risks"]], [k["id"] for k in process["controls"]],
                          [o["id"] for o in process["objectives"]]), ([self.risk], [self.control], [self.objective]))
        landscape = self.ok("GET", "/processes-map")["processes"][0]
        self.assertEqual((landscape["risks"], landscape["high_risks"], landscape["controls"]), (1, 1, 1))

    def test_takvim_isler_ve_saglik(self):
        today = date.today()
        self.ok("POST", "/audits", {"name": "Süreç denetimi", "planned_start": today.isoformat(),
                                    "planned_end": (today + timedelta(days=5)).isoformat()})
        finding = self.ok("POST", "/findings", {"title": "Eksik değerlendirme", "owner": "dev", "severity": "high",
                                                "due_date": (today + timedelta(days=3)).isoformat()})["id"]
        events = self.ok("GET", f"/calendar?from={today.isoformat()}&to={(today + timedelta(days=30)).isoformat()}")
        kinds = {e["type"] for e in events["events"]}
        self.assertTrue({"audit", "finding", "risk_review"} <= kinds, kinds)
        only = self.ok("GET", f"/calendar?from={today.isoformat()}&types=audit")["events"]
        self.assertEqual({e["type"] for e in only}, {"audit"})
        self.assertEqual(self.call("GET", "/calendar?from=2026-01-01&to=2028-01-01")[0], 400)
        work = self.ok("GET", "/my-work")
        self.assertEqual(([r["id"] for r in work["risks"]], [f["id"] for f in work["findings"]]), ([self.risk], [finding]))
        health = {c["key"]: c for c in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual((health["high_risks_no_control"]["count"], health["high_risks_no_control"]["population"]), (1, 1))
        self.assertTrue(0 < self.ok("GET", "/health-check")["score"] < 100)    # puan ihlal oranıyla hesaplanır
        self.assertEqual(health["controls_no_clause"]["count"], 1)
        self.assertEqual(health["objectives_no_control"]["count"], 0)
        self.assertEqual(health["core_process_no_bia"]["items"][0]["id"], self.process)
        self.ok("POST", f"/controls/{self.control}/links", {"risks": [self.risk], "objectives": [self.objective]})
        self.assertEqual({c["key"]: c for c in self.ok("GET", "/health-check")["checks"]}["high_risks_no_control"]["count"], 0)
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertNotIn("risks", self.ok("GET", "/my-work", app=viewer).get("risks_none", {}))

    def test_denetim_surec_kapsami(self):
        today = date.today()
        audit = self.ok("POST", "/audits", {"name": "Süreç denetimi", "planned_start": today.isoformat(), "process_ids": [self.process]})
        self.assertEqual([p["id"] for p in audit["processes"]], [self.process])
        self.assertEqual(self.ok("GET", f"/processes/{self.process}/context")["audits"][0]["id"], audit["id"])
        checks = {c["key"]: c for c in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(checks["core_process_not_audited"]["count"], 1)            # planlı denetim sayılmaz
        self.ok("PATCH", f"/audits/{audit['id']}", {"status": "in_progress", "scope": "Süreç adımları", "actual_start": today.isoformat(),
                                                     "expected_revision": audit["revision"]})
        checks = {c["key"]: c for c in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(checks["core_process_not_audited"]["count"], 0)
        self.assertEqual(self.call("POST", "/audits", {"name": "x", "process_ids": [999]})[0], 400)

    def test_arama_ve_iliski_modeli(self):
        found = self.ok("GET", "/search?q=tedarikci")["results"]
        self.assertIn(("processes", self.process), {(r["resource"], r["id"]) for r in found})
        self.assertEqual(self.ok("GET", "/search?q=a")["results"], [])
        model = self.ok("GET", "/model")
        from tedarik.model_map import POSITIONS
        from tedarik.schema import RESOURCES
        self.assertEqual(set(POSITIONS) - set(RESOURCES), set())
        relations = {(r["from"], r["to"], r["kind"]) for r in model["relations"]}
        for expected in (("controls", "clauses", "M:N"), ("controls", "objectives", "M:N"), ("supplier_risks", "companies", "1:N"),
                         ("bias", "processes", "1:N"), ("bias", "cmdb_cis", "M:N"), ("findings", "clauses", "1:N"),
                         ("objectives", "supplier_risks", "M:N"), ("supplier_risks", "cmdb_cis", "M:N")):
            self.assertIn(expected, relations)
        self.assertEqual(next(e for e in model["entities"] if e["name"] == "processes")["count"], 1)
        mcp = self.app.dispatch("GET", "/api/tdr/search?q=ted", {"X-API-Key": "k" * 40})
        self.assertEqual(mcp[0], 403)


if __name__ == "__main__":
    unittest.main()
