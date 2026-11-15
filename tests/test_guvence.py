"""Güvence ve uyum (K-026): kanıt talepleri, çalışma kâğıtları, yönetim yanıtı, rapor, yıllık plan, sertifika,
yükümlülükler, politika istisnaları, okundu beyanı, SoA ve dış denetçi erişimi."""
import base64
import json
import unittest
from datetime import date, timedelta

from test_tedarik import Base


def day(n):
    return (date.today() + timedelta(days=n)).isoformat()


def b64(raw):
    return base64.b64encode(raw).decode()


class GuvenceBase(Base):
    def setUp(self):
        super().setUp()
        self.std = self.ok("POST", "/standards", {"code": "STD-A", "name": "Sentetik A", "version": "1"})["id"]
        self.std_b = self.ok("POST", "/standards", {"code": "STD-B", "name": "Sentetik B", "version": "1"})["id"]
        self.cl1 = self.ok("POST", "/clauses", {"standard_id": self.std, "code": "5.1", "title": "Yedekleme"})["id"]
        self.cl2 = self.ok("POST", "/clauses", {"standard_id": self.std_b, "code": "8.2", "title": "Geri yükleme"})["id"]
        self.ctl = self.ok("POST", "/controls", {"name": "Yedekleme kontrolü", "owner": "ayse",
                                                 "method": "Son çeyreğin yedek günlükleri"})["id"]
        self.ok("POST", f"/controls/{self.ctl}/links", {"clauses": [self.cl1, self.cl2]})
        self.audit = self.ok("POST", "/audits", {"name": "Entegre denetim", "standard_ids": [self.std, self.std_b],
                                                 "clause_ids": [self.cl1, self.cl2], "planned_start": day(-2),
                                                 "planned_end": day(10)})["id"]
        self.auditor = self.make(role="AUDITOR", user="denetci")
        self.auditor2 = self.make(role="AUDITOR", user="denetci2")
        self.owner = self.make(role="UNIT_USER", user="ayse")


class KanitTalepleri(GuvenceBase):
    def test_kontrol_basina_tek_talep_teslim_iade_kabul(self):
        made = self.ok("POST", "/evidence_requests/bulk", {"audit_id": self.audit, "items": [{"control_id": self.ctl}]},
                       app=self.auditor)
        self.assertEqual(len(made["created"]), 1)
        again = self.ok("POST", "/evidence_requests/bulk", {"audit_id": self.audit, "items": [{"control_id": self.ctl}]},
                        app=self.auditor)
        self.assertEqual(len(again["skipped"]), 1)                          # açık talep varken ikincisi açılmaz
        rid = made["created"][0]
        req = self.ok("GET", f"/evidence_requests/{rid}")
        self.assertEqual(req["assignee"], "ayse")                          # kontrol sahibi
        self.assertIn("STD-A 5.1", req["description"])                     # tek kanıt iki standarda sayılır
        self.assertIn("STD-B 8.2", req["description"])
        other = self.make(role="UNIT_USER", user="baskasi")
        self.assertEqual(self.call("POST", f"/evidence_requests/{rid}/submit", {"note": "x"}, app=other)[0], 403)
        body = {"file_name": "yedek.txt", "content_base64": b64(b"sentetik yedek gunlugu\n"), "note": "Q3 günlükleri"}
        sub = self.ok("POST", f"/evidence_requests/{rid}/submit", body, app=self.owner)
        self.assertEqual(sub["status"], "submitted")
        ev = self.ok("GET", f"/evidence/{sub['evidence_id']}/context")
        self.assertEqual([c["id"] for c in ev["controls"]], [self.ctl])
        self.assertEqual([a["id"] for a in ev["audits"]], [self.audit])
        self.assertEqual(self.call("POST", f"/evidence_requests/{rid}/review", {"decision": "reject"}, app=self.auditor)[0], 400)
        self.assertEqual(self.call("POST", f"/evidence_requests/{rid}/review", {"decision": "accept"}, app=self.owner)[0], 403)
        self.ok("POST", f"/evidence_requests/{rid}/review", {"decision": "reject", "note": "Eylül eksik"}, app=self.auditor)
        cands = self.ok("GET", f"/evidence_requests/{rid}/candidates", app=self.owner)
        self.assertEqual([c["id"] for c in cands], [sub["evidence_id"]])   # mevcut kanıt yeniden kullanılabilir
        self.ok("POST", f"/evidence_requests/{rid}/submit", {"evidence_id": sub["evidence_id"], "note": "Eylül eklendi"},
                app=self.owner)
        # teslim edilmiş ama incelenmemiş kanıt denetimin tamamlanmasını engeller
        self.ok("PATCH", f"/audits/{self.audit}", {"status": "in_progress", "actual_start": day(-1)}, app=self.auditor)
        done = {"status": "completed", "actual_end": day(0), "opinion": "effective", "conclusion": "Etkin."}
        status, err = self.call("PATCH", f"/audits/{self.audit}", done, app=self.auditor)
        self.assertEqual(status, 409, err)
        self.assertIn("incelenmedi", err["error"])
        self.ok("POST", f"/evidence_requests/{rid}/review", {"decision": "accept"}, app=self.auditor)
        self.ok("PATCH", f"/audits/{self.audit}", done, app=self.auditor)


class CalismaKagidi(GuvenceBase):
    def test_ikinci_denetci_onayi_olmadan_denetim_kapanmaz(self):
        wp = self.ok("GET", "/workpapers/" + str(self.ok("POST", "/workpapers", {
            "audit_id": self.audit, "control_id": self.ctl, "title": "Yedekleme testi"}, app=self.auditor)["id"]))
        self.assertEqual((wp["status"], wp["preparer"]), ("draft", "denetci"))
        self.assertEqual(self.call("POST", f"/workpapers/{wp['id']}/submit", {}, app=self.auditor)[0], 400)   # içerik yok
        self.ok("PATCH", f"/workpapers/{wp['id']}", {"procedure": "25 günlük örneklem", "sample_size": 25,
                                                      "exceptions_found": 0, "result": "pass", "conclusion": "Etkin"},
                app=self.auditor)
        self.assertEqual(self.call("PATCH", f"/workpapers/{wp['id']}", {"exceptions_found": 30}, app=self.auditor)[0], 400)
        self.ok("POST", f"/workpapers/{wp['id']}/submit", {}, app=self.auditor)
        self.assertEqual(self.call("POST", f"/workpapers/{wp['id']}/review", {"decision": "approve"}, app=self.auditor)[0], 403)
        self.ok("PATCH", f"/audits/{self.audit}", {"status": "in_progress", "actual_start": day(-1)}, app=self.auditor)
        done = {"status": "completed", "actual_end": day(0), "opinion": "effective", "conclusion": "Etkin."}
        self.assertEqual(self.call("PATCH", f"/audits/{self.audit}", done, app=self.auditor)[0], 409)
        context = self.ok("GET", f"/audits/{self.audit}/context")
        self.assertTrue(context["blockers"])
        self.ok("POST", f"/workpapers/{wp['id']}/review", {"decision": "approve"}, app=self.auditor2)
        self.assertEqual(self.call("PATCH", f"/workpapers/{wp['id']}", {"conclusion": "değişti"}, app=self.auditor)[0], 409)
        self.ok("PATCH", f"/audits/{self.audit}", done, app=self.auditor)


class YonetimYaniti(GuvenceBase):
    def test_yanit_ve_rapor(self):
        f = self.ok("POST", "/findings", {"title": "Geri yükleme testi yok", "control_id": self.ctl, "audit_id": self.audit,
                                          "owner": "ayse", "severity": "high", "due_date": day(30)}, app=self.auditor)
        self.assertEqual(self.call("PATCH", f"/findings/{f['id']}", {"response_status": "agreed"}, app=self.auditor)[0], 400)
        self.ok("POST", f"/findings/{f['id']}/request-response", {}, app=self.auditor)
        self.assertEqual(self.call("POST", f"/findings/{f['id']}/response", {"response_status": "agreed",
                                   "management_response": "kısa"}, app=self.owner)[0], 400)
        other = self.make(role="UNIT_USER", user="baskasi")
        self.assertEqual(self.call("POST", f"/findings/{f['id']}/response", {"response_status": "agreed",
                                   "management_response": "Çeyreklik geri yükleme testi başlatılacak."}, app=other)[0], 403)
        r = self.ok("POST", f"/findings/{f['id']}/response", {"response_status": "agreed",
                    "management_response": "Çeyreklik geri yükleme testi başlatılacak; hedef 31 Mart."}, app=self.owner)
        self.assertEqual((r["response_status"], r["responded_by"]), ("agreed", "ayse"))
        report = self.ok("GET", f"/audits/{self.audit}/report")
        self.assertEqual(report["summary"]["findings"], 1)
        self.assertEqual(report["findings"][0]["response_label"], "Katılıyor")
        self.assertEqual(set(report["findings"][0]["clauses"]), {"STD-A 1 5.1", "STD-B 1 8.2"})
        draft = self.ok("POST", f"/audits/{self.audit}/report-draft", {}, app=self.auditor)
        self.assertIn("1 bulgu", draft["rules"]["summary"])
        self.ok("PATCH", f"/audits/{self.audit}", {"executive_summary": "Onaylanan özet"}, app=self.auditor)


class YillikPlan(Base):
    def test_risk_bazli_oncelik_ve_onay(self):
        proc = self.ok("POST", "/processes", {"name": "Ödeme İşlemleri"})["id"]
        hi = self.ok("POST", "/audit_universe", {"name": "Ödeme İşlemleri", "entity_type": "process", "process_id": proc,
                                                 "inherent_rating": 5, "frequency_months": 12})["id"]
        lo = self.ok("POST", "/audit_universe", {"name": "Kantin hizmeti", "entity_type": "other", "inherent_rating": 1,
                                                 "frequency_months": 36})["id"]
        pr = self.ok("GET", "/audit_universe/priorities")
        self.assertEqual([p["universe_id"] for p in pr], [hi, lo])
        self.assertIn("hiç denetlenmedi", pr[0]["reasons"][-1])
        plan = self.ok("POST", "/audit_plans", {"year": date.today().year + 1, "title": "Gelecek yıl iç denetim planı"})
        gen = self.ok("POST", f"/audit_plans/{plan['id']}/generate", {"limit": 5})
        self.assertEqual(gen["added"], 2)                                      # hiç denetlenmeyen ikisi de "zamanı gelmiş"
        self.assertEqual(self.call("POST", f"/audit_plans/{plan['id']}/approve", {})[0], 403)   # hazırlayan onaylayamaz
        boss = self.make(user="kurul")
        ctx = self.ok("POST", f"/audit_plans/{plan['id']}/approve", {}, app=boss)
        self.assertEqual(ctx["status"], "approved")
        item = next(i for i in ctx["items"] if i["universe_id"] == hi)
        started = self.ok("POST", f"/audit_plan_items/{item['id']}/start", {})
        ctx = self.ok("GET", f"/audit_plans/{plan['id']}/context")
        self.assertEqual(next(i for i in ctx["items"] if i["universe_id"] == hi)["progress"], "scheduled")
        processes = self.ok("GET", f"/audits/{started['audit_id']}/context")["processes"]
        self.assertEqual([p["id"] for p in processes], [proc])


class Uyum(GuvenceBase):
    def test_yukumluluk_durumu_kontrollerden(self):
        o = self.ok("GET", "/obligations/" + str(self.ok("POST", "/obligations", {
            "title": "Kişisel veri güvenliği tedbirleri", "source_type": "law", "source": "6698 sayılı KVKK",
            "article": "Madde 12", "regulator": "kvkk"})["id"]))
        self.assertTrue(o["code"].startswith("YKM-"))
        self.assertEqual(self.ok("GET", f"/obligations/{o['id']}/context")["state"], "not_assessed")
        self.ok("POST", f"/obligations/{o['id']}/links", {"controls": [self.ctl], "clauses": [self.cl1]})
        self.ok("POST", "/executions", {"control_id": self.ctl, "status": "pass", "details": "Örneklem temiz"}, app=self.auditor)
        self.assertEqual(self.ok("GET", f"/obligations/{o['id']}/context")["state"], "compliant")
        self.ok("POST", "/executions", {"control_id": self.ctl, "status": "fail", "details": "Eksik"}, app=self.auditor)
        ctx = self.ok("GET", f"/obligations/{o['id']}/context")
        self.assertEqual(ctx["state"], "non_compliant")
        self.assertEqual(self.ok("GET", "/obligations/summary")["counts"]["non_compliant"], 1)
        self.assertEqual(self.call("POST", f"/obligations/{o['id']}/change-review", {"note": "x"})[0], 400)
        self.ok("POST", f"/obligations/{o['id']}/change-review", {"note": "Yönetmelik değişikliği 2026/11, yürürlük 1 Ocak"})
        self.assertEqual(self.ok("GET", f"/obligations/{o['id']}")["applicability"], "under_review")

    def test_istisna_dort_goz_sure_ve_bitis(self):
        base = {"title": "Eski sistemde MFA yok", "control_id": self.ctl, "scope": "Muhasebe eski sunucusu",
                "justification": "Üretici desteği bitiyor; geçiş 2027 Q1", "owner": "ayse",
                "start_date": day(0), "end_date": day(90), "risk_level": "high"}
        self.assertEqual(self.call("POST", "/policy_exceptions", base, app=self.owner)[0], 400)   # telafi edici zorunlu
        base["compensating_controls"] = "Ağ yalıtımı ve haftalık oturum gözden geçirme"
        self.assertEqual(self.call("POST", "/policy_exceptions", {**base, "end_date": day(500)}, app=self.owner)[0], 400)
        self.assertEqual(self.call("POST", "/policy_exceptions", base, app=self.owner)[0], 403)   # birim seçilmedi
        unit = self.ok("POST", "/org_units", {"name": "Muhasebe"})["id"]
        owner = self.make(role="UNIT_USER", user="ayse", units=str(unit))
        ex = self.ok("GET", "/policy_exceptions/" + str(self.ok("POST", "/policy_exceptions", {**base, "org_unit_id": unit},
                                                                 app=owner)["id"]))
        self.assertEqual(ex["status"], "requested")
        self.assertEqual(self.call("POST", f"/policy_exceptions/{ex['id']}/decide", {"decision": "approve", "note": "ok"},
                                   app=self.auditor)[0], 403)
        self.ok("POST", f"/policy_exceptions/{ex['id']}/decide", {"decision": "approve", "note": "Geçici; Q1 takipte"})
        self.assertEqual(self.call("PATCH", f"/policy_exceptions/{ex['id']}", {"scope": "x"}, app=owner)[0], 409)
        soa = self.ok("GET", f"/standards/{self.std}/soa")
        self.assertEqual(soa["rows"][0]["exceptions"], [ex["code"]])
        with self.db() as db:
            db.execute("UPDATE tdr_policy_exceptions SET end_date=? WHERE id=?", (day(-1), ex["id"]))
            from tedarik.modules.compliance import expire_exceptions
            self.assertEqual(expire_exceptions(db), 1)
        self.assertEqual(self.ok("GET", f"/policy_exceptions/{ex['id']}")["status"], "expired")

    def test_okundu_beyani_ve_kanit(self):
        doc = self.ok("POST", "/documents", {"title": "Bilgi Güvenliği Politikası", "category": "policy", "owner": "x"})["id"]
        self.assertEqual(self.call("POST", "/attestation_campaigns", {"title": "2026 okundu", "document_id": doc,
                                   "statement": "Okudum, anladım.", "due_date": day(14)})[0], 400)   # yayımlanmamış
        with self.db() as db:
            db.execute("UPDATE tdr_documents SET status='published', current_revision=2 WHERE id=?", (doc,))
            for user in ("ayse", "mehmet"):
                db.execute("INSERT INTO users (username, display_name, is_active, created_at) VALUES (?,?,1,?)",
                           (user, user.title(), "2026-01-01T00:00:00+00:00"))
        self.ok("POST", f"/controls/{self.ctl}/links", {"documents": [doc]})
        camp = self.ok("POST", "/attestation_campaigns", {"title": "2026 okundu", "document_id": doc,
                                                          "statement": "Okudum, anladım.", "due_date": day(14)})
        self.assertEqual(self.ok("GET", f"/attestation_campaigns/{camp['id']}")["status"], "draft")
        ctx = self.ok("POST", f"/attestation_campaigns/{camp['id']}/launch", {})
        self.assertEqual(ctx["progress"]["total"], 2)
        mine = self.ok("GET", "/my/attestations", app=self.owner)
        self.assertEqual(len(mine), 1)
        att = mine[0]["id"]
        self.assertEqual(self.call("POST", f"/attestations/{att}/acknowledge", {"confirm": True})[0], 403)   # başkası
        self.ok("POST", f"/attestations/{att}/acknowledge", {"confirm": True}, app=self.owner)
        self.assertEqual(self.call("POST", f"/attestations/{att}/acknowledge", {"confirm": True}, app=self.owner)[0], 409)
        self.assertEqual(len(self.ok("GET", "/attestations", app=self.owner)), 1)          # yalnızca kendi beyanı
        closed = self.ok("POST", f"/attestation_campaigns/{camp['id']}/close", {})
        self.assertEqual(closed["progress"]["acknowledged"], 1)
        ev = self.ok("GET", f"/evidence/{closed['evidence_id']}/context")
        self.assertEqual([c["id"] for c in ev["controls"]], [self.ctl])                   # politikaya eşli kontrolün kanıtı

    def test_soa_ve_csv(self):
        self.ok("PATCH", f"/clauses/{self.cl2}", {"applicable": 0, "justification": "Kapsam dışı hizmet"})
        soa = self.ok("GET", f"/standards/{self.std}/soa")
        self.assertEqual(soa["rows"][0]["state"], "partial")                    # test edilmemiş kontrol
        self.ok("POST", "/executions", {"control_id": self.ctl, "status": "pass", "details": "ok"}, app=self.auditor)
        self.assertEqual(self.ok("GET", f"/standards/{self.std}/soa")["rows"][0]["state"], "implemented")
        self.assertEqual(self.ok("GET", f"/standards/{self.std_b}/soa")["counts"]["not_applicable"], 1)
        status, raw = self.app.dispatch("GET", f"/api/tdr/standards/{self.std}/soa?format=csv", {}, b"")
        self.assertEqual(status, 200)
        self.assertIn("Uygulanıyor", raw.content.decode("utf-8"))

    def test_sertifika(self):
        self.assertEqual(self.call("POST", "/certifications", {"title": "x", "issued_on": day(0), "expires_on": day(-1)})[0], 400)
        cert = self.ok("GET", "/certifications/" + str(self.ok("POST", "/certifications", {
            "title": "ISO/IEC 27001 sertifikası", "standard_id": self.std, "issued_on": day(-900), "expires_on": day(30),
            "owner": "ayse"})["id"]))
        self.assertTrue(cert["code"].startswith("SRT-"))


class DisDenetci(GuvenceBase):
    def test_sureli_ve_kapsamli_salt_okunur(self):
        local = self.make(TEDARIK_AUTH_MODE="local")
        from tedarik import session
        with local.database.connect() as db:
            session.provision(db, "dis.denetci", "Dış Denetçi")
            uid = db.execute("SELECT id FROM users WHERE username='dis.denetci'").fetchone()["id"]
            db.execute("UPDATE users SET must_change_password=0 WHERE id=?", (uid,))
            db.execute("INSERT INTO tdr_user_roles (user_id, role, assigned_by, assigned_at) VALUES (?,?,?,?)",
                       (uid, "AUDITOR", "dev", "2026-01-01T00:00:00+00:00"))
        other = self.ok("POST", "/audits", {"name": "Başka denetim", "standard_ids": [self.std], "clause_ids": [self.cl1]})["id"]
        f_in = self.ok("POST", "/findings", {"title": "Kapsamda", "audit_id": self.audit}, app=self.auditor)["id"]
        f_out = self.ok("POST", "/findings", {"title": "Kapsam dışı", "audit_id": other}, app=self.auditor)["id"]
        self.assertEqual(self.call("PATCH", f"/users/{uid}", {"external": 1})[0], 400)            # süresiz dış denetçi olmaz
        self.ok("PATCH", f"/users/{uid}", {"external": 1, "access_expires": day(30), "audit_ids": [self.audit]})
        from tedarik.vendor import identity
        with local.database.connect() as db:
            token = identity.new_session(db, uid)
        cookie = {"Cookie": f"tedarik_session={token}"}
        get = lambda path: local.dispatch("GET", "/api/tdr" + path, cookie, b"")
        me = local.dispatch("GET", "/api/me", cookie, b"")[1]
        self.assertTrue(me["external"])
        self.assertEqual([a["id"] for a in get("/audits")[1]], [self.audit])
        self.assertEqual(get(f"/audits/{other}")[0], 404)
        self.assertEqual(get(f"/audits/{other}/context")[0], 404)
        self.assertEqual([f["id"] for f in get("/findings")[1]], [f_in])
        self.assertEqual(get(f"/findings/{f_out}/context")[0], 404)
        self.assertEqual(get("/supplier_risks")[0], 403)                                    # izinli ekran dışı
        self.assertEqual(get("/assurance/search?q=x")[0], 403)
        status, _ = local.dispatch("POST", "/api/tdr/findings", {**cookie, "Origin": "http://127.0.0.1:8090"},
                                   json.dumps({"title": "x"}).encode())
        self.assertEqual(status, 403)                                                       # salt okunur
        # süresi dolunca oturum geçersiz
        with local.database.connect() as db:
            db.execute("UPDATE tdr_user_access SET expires_on=? WHERE user_id=?", (day(-1), uid))
        self.assertEqual(get("/audits")[0], 401)


if __name__ == "__main__":
    unittest.main()
