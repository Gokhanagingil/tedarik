"""Olay ve kayıp, KVKK ihlali (72 saat), RCSA, nicel risk, erişim gözden geçirme, kriz modu ve ServiceNow görev
eşlemesi (K-027)."""
import json
import unittest
from datetime import date, datetime, timedelta, timezone

from test_cmdb import PASSWORD, FakeServiceNow
from test_tedarik import KEY, Base


def day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def ts(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")


class Kayip(Base):
    def test_net_kayip_ve_mcp(self):
        status, err = self.call("POST", "/loss_events", {"title": "x", "occurred_on": day(-3), "gross_loss": 100, "recovery": 200})
        self.assertEqual(status, 400)
        made = self.ok("POST", "/loss_events", {"title": "Ödeme ağ geçidi kesintisi", "occurred_on": day(-3),
                                                "gross_loss": 250000, "recovery": 40000, "event_type": "systems"})
        ev = self.ok("GET", f"/loss_events/{made['id']}")
        self.assertEqual((float(ev["net_loss"]), ev["code"][:4]), (210000.0, "OLY-"))
        self.assertEqual(self.call("PATCH", f"/loss_events/{made['id']}", {"status": "closed"})[0], 400)    # kök neden
        mcp = self.call("POST", "/loss_events", {"title": "P1 olay INC0012", "occurred_on": day(-1), "gross_loss": 0,
                                                  "external_ref": "INC0012"}, headers={"X-API-Key": KEY})
        self.assertEqual(mcp[0], 201)
        self.assertEqual(self.ok("GET", f"/loss_events/{mcp[1]['id']}")["source"], "mcp")


class Ihlal(Base):
    def test_72_saat_kurallari(self):
        viewer = self.make(role="VIEWER", user="izleyici")
        body = {"title": "Müşteri listesinin yanlış alıcıya gönderilmesi", "owner": "kvkk.sorumlusu",
                "detected_at": ts(-80), "description": "Sentetik olay", "subjects_count": 120}
        b = self.ok("POST", "/privacy_breaches", body)["id"]
        self.assertEqual(self.call("GET", "/privacy_breaches", app=viewer)[0], 403)
        ctx = self.ok("GET", f"/privacy_breaches/{b}/context")
        self.assertTrue(ctx["late"] and ctx["needs_action"])
        self.assertLess(ctx["remaining_hours"], 0)
        self.assertEqual(self.call("PATCH", f"/privacy_breaches/{b}", {"notify_decision": "notify"})[0], 400)  # gerekçe
        self.ok("PATCH", f"/privacy_breaches/{b}", {"notify_decision": "notify", "decision_rationale": "Kişi sayısı ve veri türü"})
        self.assertEqual(self.call("PATCH", f"/privacy_breaches/{b}", {"authority_notified_at": ts(-1)})[0], 400)   # gecikme
        self.ok("PATCH", f"/privacy_breaches/{b}", {"authority_notified_at": ts(-1), "delay_reason": "Etki analizi uzadı",
                                                    "authority_reference": "VERBİS-2026-001"})
        self.assertEqual(self.ok("GET", f"/privacy_breaches/{b}")["status"], "notified")
        self.assertEqual(self.call("PATCH", f"/privacy_breaches/{b}", {"status": "closed"})[0], 400)        # önlem
        self.ok("PATCH", f"/privacy_breaches/{b}", {"status": "closed", "measures": "Alıcıdan silme teyidi alındı"})
        fresh = self.ok("POST", "/privacy_breaches", {**body, "detected_at": ts(-2)})["id"]
        st = self.ok("GET", f"/privacy_breaches/{fresh}/context")
        self.assertFalse(st["late"])
        self.assertGreater(st["remaining_hours"], 60)
        self.assertEqual(self.call("POST", "/privacy_breaches", {**body, "detected_at": ts(5)})[0], 400)   # gelecek


class OzDegerlendirme(Base):
    def test_rcsa_ve_bulgu(self):
        proc = self.ok("POST", "/processes", {"name": "Olay Yönetimi"})["id"]
        risk = self.ok("POST", "/supplier_risks", {"title": "Olay eskalasyonu gecikir", "category": "operational",
                                                   "owner": "ayse", "appetite": 8, "entity_name": "Hizmet masası",
                                                   "process_id": proc, "likelihood": 2, "impact": 2})["id"]
        ctl = self.ok("POST", "/controls", {"name": "P1 eskalasyon kontrolü", "owner": "ayse"})["id"]
        self.ok("POST", f"/controls/{ctl}/links", {"processes": [proc]})
        camp = self.ok("POST", "/rcsa_campaigns", {"title": "2026 H2 öz değerlendirme", "process_id": proc, "due_date": day(14)})["id"]
        ctx = self.ok("POST", f"/rcsa_campaigns/{camp}/launch", {})
        self.assertEqual(ctx["progress"]["total"], 2)
        ayse = self.make(role="UNIT_USER", user="ayse")
        other = self.make(role="UNIT_USER", user="baskasi")
        risk_item = next(i for i in ctx["items"] if i["item_type"] == "risk")
        ctl_item = next(i for i in ctx["items"] if i["item_type"] == "control")
        self.assertEqual(self.call("POST", f"/rcsa_items/{risk_item['id']}/respond", {"likelihood": 4, "impact": 4}, app=other)[0], 403)
        self.ok("POST", f"/rcsa_items/{risk_item['id']}/respond", {"likelihood": 4, "impact": 4}, app=ayse)
        self.assertEqual(self.call("POST", f"/rcsa_items/{ctl_item['id']}/respond", {"effectiveness": "ineffective"}, app=ayse)[0], 400)
        self.ok("POST", f"/rcsa_items/{ctl_item['id']}/respond", {"effectiveness": "ineffective",
                                                                 "comment": "Hafta sonu nöbetinde eskalasyon yapılmıyor"}, app=ayse)
        ctx = self.ok("GET", f"/rcsa_campaigns/{camp}/context")
        self.assertEqual((ctx["progress"]["submitted"], ctx["progress"]["divergent"], ctx["progress"]["ineffective"]), (2, 1, 1))
        made = self.ok("POST", f"/rcsa_items/{ctl_item['id']}/finding", {})
        finding = self.ok("GET", f"/findings/{made['finding_id']}")
        self.assertEqual((finding["source"], finding["control_id"]), ("self_assessment", ctl))
        work = self.ok("GET", "/my-work", app=ayse)
        self.assertIn("findings", work)


class NicelRisk(Base):
    def test_monte_carlo_tekrarlanabilir(self):
        risk = self.ok("POST", "/supplier_risks", {"title": "Fidye yazılımı", "category": "security", "owner": "x",
                                                   "appetite": 8, "entity_name": "Sunucular"})["id"]
        bad = {"freq_min": 1, "freq_likely": 0.5, "freq_max": 2, "loss_min": 1, "loss_likely": 2, "loss_max": 3}
        self.assertEqual(self.call("POST", f"/supplier_risks/{risk}/quantify", bad)[0], 400)
        body = {"freq_min": 0.1, "freq_likely": 0.3, "freq_max": 1, "loss_min": 500000, "loss_likely": 2000000,
                "loss_max": 15000000}
        a = self.ok("POST", f"/supplier_risks/{risk}/quantify", body)
        b = self.ok("POST", f"/supplier_risks/{risk}/quantify", body)
        self.assertEqual(a["mean_loss"], b["mean_loss"])                        # aynı girdi, aynı sonuç
        self.assertTrue(a["p50"] <= a["p90"] <= a["p95"] <= a["p99"])
        self.assertTrue(200000 < a["mean_loss"] < 3000000)                       # ~0.37 olay × ~3.6 M TL
        self.assertEqual(len(a["curve"]), 21)
        self.assertGreater(a["zero_share"], 0.4)
        self.assertEqual(float(self.ok("GET", f"/supplier_risks/{risk}")["ale"]), a["mean_loss"])
        summary = self.ok("GET", "/risks/quant-summary")
        self.assertEqual(summary["risks"][0]["risk_id"], risk)
        self.assertIsNotNone(summary["portfolio"])
        with self.db() as db:
            with self.assertRaises(Exception):
                db.execute("UPDATE tdr_risk_quant_runs SET mean_loss=0")       # değiştirilemez kayıt


class ErisimGozdenGecirme(Base):
    def test_kampanya_ve_kanit(self):
        ctl = self.ok("POST", "/controls", {"name": "Yönetici hesaplarına erişim periyodik onayı"})["id"]
        review = self.ok("POST", "/access_reviews", {"title": "Portal yetkileri — 2026 Q4", "system": "GRC Platformu",
                                                     "control_id": ctl, "reviewer": "denetci", "due_date": day(10)})["id"]
        self.assertEqual(self.call("POST", f"/access_reviews/{review}/launch", {})[0], 400)          # liste yok
        rows = [{"account": "dev", "entitlement": "ADMIN"}, {"account": "eski.calisan", "person": "Eski Çalışan",
                                                              "entitlement": "SUPPLIER_MANAGER"}]
        self.ok("POST", f"/access_reviews/{review}/items", {"rows": rows})
        self.ok("POST", f"/access_reviews/{review}/launch", {})
        reviewer = self.make(role="AUDITOR", user="denetci")
        ctx = self.ok("GET", f"/access_reviews/{review}/context")
        ids = {i["account"]: i["id"] for i in ctx["items"]}
        self.assertEqual(self.call("POST", f"/access_review_items/{ids['eski.calisan']}/decide", {"decision": "revoke"},
                                   app=reviewer)[0], 400)                                         # gerekçe
        self.ok("POST", f"/access_review_items/{ids['eski.calisan']}/decide", {"decision": "revoke", "comment": "Ayrıldı"},
                app=reviewer)
        self.assertEqual(self.call("POST", f"/access_reviews/{review}/complete", {}, app=reviewer)[0], 409)  # bekleyen
        self.ok("POST", f"/access_reviews/{review}/keep", {"item_ids": [ids["dev"]]}, app=reviewer)
        done = self.ok("POST", f"/access_reviews/{review}/complete", {}, app=reviewer)
        self.assertEqual((done["status"], done["open_remediation"]), ("completed", 1))
        ev = self.ok("GET", f"/evidence/{done['evidence_id']}/context")
        self.assertEqual([c["id"] for c in ev["controls"]], [ctl])
        self.ok("POST", f"/access_review_items/{ids['eski.calisan']}/remediated", {})


class Kriz(Base):
    def test_ilan_gorev_gunluk_kapanis(self):
        with self.db() as db:
            plan = db.execute("INSERT INTO tdr_bc_plans (code, title, plan_type, owner, status, version, created_at) "
                              "VALUES ('BSP-0001','Veri merkezi planı','drp','x','approved','1.0','2026-01-01T00:00:00+00:00')").lastrowid
            for phase, pos, action, who in (("activation", 1, "Kriz ekibini topla", "dev"),
                                            ("recovery", 1, "İkincil veri merkezine geç", "baskasi")):
                db.execute("INSERT INTO tdr_bc_plan_steps (plan_id, phase, position, action, responsible) VALUES (?,?,?,?,?)",
                           (plan, phase, pos, action, who))
        made = self.ok("POST", "/bc_incidents/declare", {"title": "Birincil veri merkezi erişilemiyor", "plan_ids": [plan],
                                                         "description": "Güç kesintisi, tüm raflar", "severity": "critical"})
        self.assertEqual(len(made["tasks"]), 2)
        active = self.ok("GET", "/bc_incidents/active")
        self.assertEqual(active[0]["id"], made["id"])
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(len(self.ok("GET", "/bc_incidents/active", app=viewer)), 1)              # bant herkese görünür
        unit = self.make(role="UNIT_USER", user="baskasi")
        task = next(t for t in made["tasks"] if t["responsible"] == "baskasi")
        self.ok("POST", f"/bc_incident_tasks/{task['id']}/status", {"status": "done"}, app=unit)    # sorumlusu
        self.assertEqual(self.call("POST", f"/bc_incident_tasks/{made['tasks'][0]['id']}/status", {"status": "skipped"})[0], 400)
        self.ok("POST", f"/bc_incidents/{made['id']}/log", {"kind": "decision", "text": "İkincil merkeze geçiş onaylandı"})
        self.assertEqual(self.call("POST", f"/bc_incidents/{made['id']}/transition", {"status": "closed", "summary": "kısa"})[0], 400)
        closed = self.ok("POST", f"/bc_incidents/{made['id']}/transition", {
            "status": "closed", "summary": "Güç kesintisi 3 saatte giderildi; hizmetler ikincil merkezden sürdü.",
            "lessons_learned": "Jeneratör yakıt sözleşmesi gözden geçirilmeli"})
        exercise = self.ok("GET", f"/bc_exercises/{closed['exercise_id']}")
        self.assertEqual((exercise["exercise_type"], exercise["status"]), ("real_incident", "completed"))
        self.assertEqual(self.ok("GET", "/bc_incidents/active"), [])
        with self.db() as db:
            with self.assertRaises(Exception):
                db.execute("UPDATE tdr_bc_incident_log SET text='x'")


class ServiceNowGorev(Base):
    def test_dof_gorev_olarak_acilir(self):
        fake = FakeServiceNow()
        self.addCleanup(fake.close)
        app = self.make(TEDARIK_SN_INSTANCE=fake.url, TEDARIK_SN_USER="grc.reader", TEDARIK_SN_ALLOW_HTTP="1",
                        TEDARIK_SN_PASSWORD_FILE=self._pw())
        ctl = self.ok("POST", "/controls", {"name": "Yedekleme"}, app=app)["id"]
        action = self.ok("POST", "/grc_actions", {"title": "Yedek testini otomatikleştir", "owner": "x", "due_date": day(30),
                                                  "control_id": ctl}, app=app)["id"]
        self.assertEqual(self.call("POST", f"/grc_actions/{action}/servicenow", {}, app=app)[0], 409)    # kapalı
        self.ok("PATCH", "/policies/" + str(self.ok("GET", "/policies?code=servicenow.tasks", app=app)[0]["id"]),
                {"value_json": json.dumps({"enabled": True, "table": "task"})}, app=app)
        pushed = self.ok("POST", f"/grc_actions/{action}/servicenow", {}, app=app)
        self.assertTrue(pushed["external_number"].startswith("TASK"))
        created = next(iter(fake.created.values()))
        self.assertIn("Yedek testini", created["short_description"])
        self.assertEqual(self.call("POST", f"/grc_actions/{action}/servicenow", {}, app=app)[0], 409)    # ikinci kez yok
        refreshed = self.ok("POST", f"/grc_actions/{action}/servicenow/refresh", {}, app=app)
        self.assertEqual(refreshed["external_status"], "Open")

    def _pw(self):
        import os
        path = os.path.join(self.tmp.name, "sn_pw")
        with open(path, "w") as fh:
            fh.write(PASSWORD)
        return path


if __name__ == "__main__":
    unittest.main()
