"""Uyum (GRC) modülü: KS GRC kuralları bu altyapıda (K-015)."""
import base64
import json
import unittest
from datetime import datetime, timedelta, timezone

from test_tedarik import KEY, Base

PDF = b"%PDF-1.4\n% sentetik kanit\n"


def b64(raw):
    return base64.b64encode(raw).decode()


class GrcBase(Base):
    def setUp(self):
        super().setUp()
        self.std = self.ok("POST", "/standards", {"code": "ISO 27001", "name": "Bilgi güvenliği", "version": "2022"})["id"]
        self.cl1 = self.ok("POST", "/clauses", {"standard_id": self.std, "code": "A.5.19", "title": "Tedarikçi ilişkilerinde bilgi güvenliği"})["id"]
        self.cl2 = self.ok("POST", "/clauses", {"standard_id": self.std, "code": "A.5.22", "title": "Tedarikçi hizmetlerinin izlenmesi"})["id"]
        self.ctl = self.ok("POST", "/controls", {"name": "Kritik tedarikçi değerlendirmesi",
                                                 "frequency": "quarterly", "criticality": "high", "owner": "ayse"})["id"]
        self.auto = self.ok("POST", "/controls", {"name": "Tedarikçi sahibi atanmış",
                                                  "execution_mode": "automatic", "automation": "supplier.owner",
                                                  "frequency": "daily"})["id"]
        self.ok("POST", f"/controls/{self.ctl}/links", {"clauses": [self.cl1, self.cl2]})
        self.ok("POST", f"/controls/{self.auto}/links", {"clauses": [self.cl2]})
        self.auditor = self.make(role="AUDITOR", user="denetci")
        self.auto_code = self.ok("GET", f"/controls/{self.auto}")["code"]

    def execute(self, body, app=None, **kw):
        return self.call("POST", "/executions", body, app=app or self.auditor, **kw)


class Cerceve(GrcBase):
    def test_kutuphane_yalnizca_yonetici_yazar(self):
        for role in ("AUDITOR", "SUPPLIER_MANAGER", "UNIT_USER"):
            other = self.make(role=role, user=role.lower())
            self.assertEqual(self.call("POST", "/controls", {"name": "x"}, app=other)[0], 403, role)
        meta = self.ok("GET", "/metadata", app=self.auditor)["resources"]
        self.assertFalse(meta["controls"]["can_write"])
        self.assertTrue(meta["findings"]["can_write"])

    def test_eslemeler_kume_olarak_degisir_ve_kural_dogrulanir(self):
        context = self.ok("GET", f"/controls/{self.ctl}/context")
        self.assertEqual([c["code"] for c in context["clauses"]], ["A.5.19", "A.5.22"])
        self.ok("POST", f"/controls/{self.ctl}/links", {"clauses": [self.cl2]})
        self.assertEqual([c["code"] for c in self.ok("GET", f"/controls/{self.ctl}/context")["clauses"]], ["A.5.22"])
        self.assertEqual(self.call("POST", f"/controls/{self.ctl}/links", {"clauses": [999]})[0], 400)
        self.assertEqual(self.call("PATCH", f"/controls/{self.ctl}", {"automation": "yok.kural"})[0], 400)
        self.assertEqual(self.call("PATCH", f"/controls/{self.ctl}", {"automation": "supplier.owner"})[0], 400)  # manuel
        # uygulanabilirlik bildirimi: dışarıda bırakılan madde gerekçe ister
        self.assertEqual(self.call("PATCH", f"/clauses/{self.cl1}", {"applicable": 0})[0], 400)
        self.ok("PATCH", f"/clauses/{self.cl1}", {"applicable": 0, "justification": "Kapsam dışı hizmet"})

    def test_kurumsal_risk_tedarikcisiz_acilir(self):
        self.assertEqual(self.call("POST", "/supplier_risks", {"title": "Veri merkezi kesintisi",
                                                                "category": "operational", "owner": "x",
                                                                "appetite": 8})[0], 400)
        risk = self.ok("POST", "/supplier_risks", {"title": "Veri merkezi kesintisi",
                                                    "category": "operational", "owner": "x", "appetite": 8,
                                                    "entity_name": "Birincil veri merkezi"})["id"]
        context = self.ok("POST", f"/controls/{self.ctl}/links", {"risks": [risk]})
        self.assertEqual(context["risks"][0]["id"], risk)


class Calismalar(GrcBase):
    def test_basarisiz_sonuc_bulgu_acar_ve_tanim_donar(self):
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "fail"})[0], 400)        # açıklama zorunlu
        status, result = self.execute({"control_id": self.ctl, "status": "fail", "details": "2 kritik tedarikçi gecikmiş",
                                       "sample_size": 8, "exceptions": 2})
        self.assertEqual(status, 201)
        finding = self.ok("GET", f"/findings/{result['finding_id']}/context")
        self.assertEqual((finding["severity"], finding["status"], finding["owner"]), ("high", "open", "ayse"))
        self.assertTrue(finding["code"].startswith("BLG-"))
        self.ok("POST", f"/controls/{self.ctl}/links", {"clauses": []})
        self.ok("PATCH", f"/controls/{self.ctl}", {"name": "Yeni ad"})
        run = self.ok("GET", f"/executions/{result['execution_id']}/context")
        self.assertEqual(run["definition"]["name"], "Kritik tedarikçi değerlendirmesi")
        self.assertEqual([c["code"] for c in run["definition"]["clauses"]], ["A.5.19", "A.5.22"])
        with self.db() as db, self.assertRaises(Exception):
            db.execute("UPDATE tdr_executions SET status='pass' WHERE id=?", (result["execution_id"],))

    def test_kurallar_zaman_toplama_ve_yetki(self):
        future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "pass", "executed_at": future})[0], 400)
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "pass", "executed_at": "2026-01-01T10:00"})[0], 400)
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "pass",
                                       "provenance": {"collection_status": "partial"}})[0], 400)
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "inconclusive",
                                       "provenance": {"collection_status": "error"}})[0], 201)
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "pass"}, app=viewer)[0], 403)
        self.ok("PATCH", f"/controls/{self.ctl}", {"active": 0})
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "pass"})[0], 400)

    def test_mcp_yalnizca_otomatik_kontrole_yazar_ve_tekrar_korunur(self):
        mcp = {"X-API-Key": KEY}
        body = {"control_id": self.ctl, "status": "pass", "source": "mcp"}
        self.assertEqual(self.call("POST", "/executions", body, headers=mcp)[0], 403)
        body = {"control_id": self.auto, "status": "fail", "details": "3 sahipsiz tedarikçi", "source": "mcp",
                "provenance": {"collection_status": "complete", "query": "approved:v1"},
                "idempotency_key": "mcp-ctl-2-2026-11-15"}
        status, first = self.call("POST", "/executions", body, headers=mcp)
        self.assertEqual(status, 201)
        status, again = self.call("POST", "/executions", body, headers=mcp)
        self.assertEqual((status, again["execution_id"], again["replayed"]), (200, first["execution_id"], True))
        self.assertEqual(self.call("POST", "/executions", {**body, "status": "pass"}, headers=mcp)[0], 409)
        self.assertEqual(self.call("POST", "/controls", {"name": "z"}, headers=mcp)[0], 403)
        # aynı kontrolde açık MCP bulgusu varken yeni başarısızlık tekrar sayar
        second = self.call("POST", "/executions", {**body, "idempotency_key": "mcp-ctl-2-2026-11-16"}, headers=mcp)[1]
        self.assertEqual(second["finding_id"], first["finding_id"])
        self.assertEqual(self.ok("GET", f"/findings/{first['finding_id']}")["recurrence"], 2)


class IcOtomatik(GrcBase):
    def test_portal_verisinden_kontrol_calisir(self):
        self.ok("POST", "/suppliers", {"name": "Sahipsiz A.Ş.", "tier": "critical"})
        result = self.ok("POST", f"/controls/{self.auto}/run", {}, app=self.auditor)
        run = self.ok("GET", f"/executions/{result['execution_id']}/context")
        self.assertEqual((run["status"], run["source"]), ("fail", "system"))
        self.assertEqual(run["provenance"]["items"][0]["name"], "Sahipsiz A.Ş.")
        self.assertEqual(len(run["provenance"]["result_sha256"]), 64)
        again = self.ok("POST", f"/controls/{self.auto}/run", {}, app=self.auditor)
        self.assertEqual((again["finding_id"], again["finding_repeated"]), (result["finding_id"], True))
        supplier = self.ok("GET", "/suppliers")[0]
        self.ok("PATCH", f"/suppliers/{supplier['id']}", {"owner": "ayse"})
        fixed = self.ok("POST", f"/controls/{self.auto}/run", {}, app=self.auditor)
        self.assertIsNone(fixed["finding_id"])
        self.assertEqual(self.ok("GET", f"/controls/{self.auto}/context")["latest"]["status"], "pass")
        self.assertEqual(self.call("POST", f"/controls/{self.ctl}/run", {}, app=self.auditor)[0], 400)
        results = self.ok("POST", "/grc/run-automatic", {})["results"]
        self.assertEqual([r["code"] for r in results], [self.auto_code])

    def test_kapali_modul_belirsiz_sonuc_verir(self):
        app = self.make(modules="core,risks,documents,grc")
        ctl = self.ok("POST", "/controls", {"name": "SLA", "execution_mode": "automatic",
                                            "automation": "supplier.sla"}, app=app)["id"]
        result = self.ok("POST", f"/controls/{ctl}/run", {}, app=app)
        run = self.ok("GET", f"/executions/{result['execution_id']}/context", app=app)
        self.assertEqual((run["status"], run["provenance"]["collection_status"]), ("inconclusive", "error"))


class Denetimler(GrcBase):
    def audit(self, **extra):
        body = {"name": "2026 tedarikçi yönetimi iç denetimi", "standard_ids": [self.std], "clause_ids": [self.cl1, self.cl2],
                "planned_start": "2026-10-01", "planned_end": "2026-11-30", **extra}
        return self.ok("POST", "/audits", body, app=self.auditor)

    def test_yasam_dongusu_plan_dondurma_ve_kapsam(self):
        audit = self.audit()
        self.assertTrue(audit["code"].startswith("DNT-"))
        self.assertEqual({c["id"] for c in audit["controls"]}, {self.ctl, self.auto})
        aid, rev = audit["id"], audit["revision"]
        self.assertEqual(self.call("PATCH", f"/audits/{aid}", {"status": "in_progress"}, app=self.auditor)[0], 400)
        self.ok("PATCH", f"/audits/{aid}", {"status": "in_progress", "actual_start": "2026-10-02"}, app=self.auditor)
        # eşzamanlı kapsam düzenlemesi: eski sürümle gönderilen değişiklik reddedilir
        self.assertEqual(self.call("PATCH", f"/audits/{aid}", {"standard_ids": [self.std], "clause_ids": [self.cl2],
                                                               "expected_revision": rev}, app=self.auditor)[0], 409)
        self.execute({"control_id": self.ctl, "status": "pass", "audit_id": aid})
        self.execute({"control_id": self.auto, "status": "fail", "details": "istisna", "audit_id": aid})
        context = self.ok("GET", f"/audits/{aid}/context")
        self.assertEqual((context["progress"]["completion_pct"], context["progress"]["pass_pct"]), (100.0, 50.0))
        self.assertEqual(len(context["findings"]), 1)
        self.assertEqual(self.call("PATCH", f"/audits/{aid}", {"status": "completed", "actual_end": "2026-11-10"},
                                   app=self.auditor)[0], 400)      # sonuç yazısı ve görüş gerekli
        self.ok("PATCH", f"/audits/{aid}", {"status": "completed", "actual_end": "2026-11-10", "opinion": "partially_effective",
                                            "conclusion": "Bir kontrol etkin değil."}, app=self.auditor)
        self.ok("POST", f"/controls/{self.ctl}/links", {"clauses": []})          # plan dondu: değişiklik etkilemez
        self.assertEqual(len(self.ok("GET", f"/audits/{aid}/context")["controls"]), 2)
        self.assertEqual(self.execute({"control_id": self.ctl, "status": "pass", "audit_id": aid})[0], 409)
        self.assertEqual(self.call("PATCH", f"/audits/{aid}", {"status": "in_progress"}, app=self.auditor)[0], 409)
        self.ok("PATCH", f"/audits/{aid}", {"status": "closed"}, app=self.auditor)
        compliance = self.ok("GET", f"/grc/compliance?audit_id={aid}")
        self.assertEqual((compliance["counts"]["pass"], compliance["counts"]["fail"]), (1, 1))

    def test_kapsam_kurallari(self):
        other = self.ok("POST", "/standards", {"code": "ISO 20000-1", "name": "Hizmet yönetimi", "version": "2018"})["id"]
        status, _ = self.call("POST", "/audits", {"name": "x", "standard_ids": [other], "clause_ids": [self.cl1]}, app=self.auditor)
        self.assertEqual(status, 400)                          # madde seçilen standarda ait değil
        status, _ = self.call("POST", "/audits", {"name": "x", "standard_ids": [self.std, other], "clause_ids": [self.cl1],
                                                  "status": "in_progress", "actual_start": "2026-10-01"}, app=self.auditor)
        self.assertEqual(status, 400)                          # her standarda en az bir madde
        status, _ = self.call("POST", "/audits", {"name": "Tedarikçi denetimi", "kind": "supplier"}, app=self.auditor)
        self.assertEqual(status, 400)                          # tedarikçi denetimi tedarikçi ister
        self.assertEqual(self.call("POST", "/audits", {"name": "x"}, app=self.make(role="SUPPLIER_MANAGER"))[0], 403)


class Kanitlar(GrcBase):
    def test_surumler_butunluk_ve_calismaya_baglanma(self):
        bad = self.call("POST", "/evidence/upload", {"title": "Rapor", "file_name": "rapor.pdf", "content_base64": b64(b"not pdf")},
                        app=self.auditor)
        self.assertEqual(bad[0], 400)
        first = self.ok("POST", "/evidence/upload", {"title": "Değerlendirme raporu", "file_name": "rapor.pdf",
                                                     "content_base64": b64(PDF), "controls": [self.ctl]}, app=self.auditor)
        eid = first["id"]
        second = self.ok("POST", f"/evidence/{eid}/files", {"file_name": "rapor-v2.pdf", "content_base64": b64(PDF + b"v2")},
                         app=self.auditor)
        self.assertEqual(second["version"], 2)
        status, raw = self.call("GET", f"/evidence/{eid}/files/1")
        self.assertEqual((status, raw.content), (200, PDF))
        result = self.execute({"control_id": self.ctl, "status": "pass", "evidence_ids": [eid],
                               "evidence_versions": {str(eid): 1}})[1]
        run = self.ok("GET", f"/executions/{result['execution_id']}/context")
        self.assertEqual((run["evidence"][0]["version"], run["evidence"][0]["sha256"]), (1, first["sha256"]))
        context = self.ok("GET", f"/evidence/{eid}/context")
        self.assertEqual([f["version"] for f in context["files"]], [2, 1])
        self.assertEqual(context["controls"][0]["id"], self.ctl)
        with self.db() as db, self.assertRaises(Exception):
            db.execute("UPDATE tdr_evidence_blobs SET content=? WHERE file_id=1", (b"x",))
        self.assertEqual(self.call("GET", f"/evidence/{eid}/files/1", headers={"X-API-Key": KEY})[0], 403)

    def test_birim_kullanicisi_kendi_birimine_kanit_yukler(self):
        unit = self.ok("POST", "/org_units", {"name": "BT"})["id"]
        other = self.ok("POST", "/org_units", {"name": "İK"})["id"]
        user = self.make(role="UNIT_USER", user="birim", units=str(unit))
        body = {"title": "Erişim gözden geçirme", "file_name": "liste.csv", "content_base64": b64(b"kullanici,yetki\n")}
        self.assertEqual(self.call("POST", "/evidence/upload", {**body, "org_unit_id": other}, app=user)[0], 403)
        self.assertEqual(self.call("POST", "/evidence/upload", {**body, "org_unit_id": unit}, app=user)[0], 201)


class BulguVeFaaliyet(GrcBase):
    def test_dof_dogrulama_ayriligi_ve_bulgu_kapanisi(self):
        finding = self.execute({"control_id": self.ctl, "status": "fail", "details": "Değerlendirme yok"})[1]["finding_id"]
        owner = self.make(role="SUPPLIER_MANAGER", user="ayse")
        action = self.ok("POST", "/grc_actions", {"title": "Değerlendirmeleri tamamla", "finding_id": finding,
                                                  "owner": "ayse", "due_date": "2026-12-31"}, app=owner)["id"]
        self.assertEqual(self.ok("GET", f"/grc_actions/{action}")["control_id"], self.ctl)
        self.assertEqual(self.call("PATCH", f"/findings/{finding}", {"status": "closed", "closure_note": "Bitti"},
                                   app=self.auditor)[0], 409)
        self.assertEqual(self.call("PATCH", f"/grc_actions/{action}", {"status": "completed"}, app=owner)[0], 409)
        self.assertEqual(self.call("PATCH", f"/grc_actions/{action}", {"status": "validation"}, app=owner)[0], 400)
        self.ok("PATCH", f"/grc_actions/{action}", {"status": "validation", "resolution": "İki değerlendirme yapıldı"}, app=owner)
        self.assertEqual(self.call("PATCH", f"/grc_actions/{action}", {"status": "completed", "verification_note": "x"},
                                   app=owner)[0], 403)
        self.assertEqual(self.call("PATCH", f"/grc_actions/{action}", {"status": "completed"}, app=self.auditor)[0], 400)
        done = self.ok("PATCH", f"/grc_actions/{action}", {"status": "completed",
                                                           "verification_note": "Raporlar incelendi"}, app=self.auditor)
        self.assertEqual(done["verified_by"], "denetci")
        self.assertEqual(self.call("PATCH", f"/grc_actions/{action}", {"title": "değişti"}, app=self.auditor)[0], 409)
        self.assertEqual(self.call("PATCH", f"/findings/{finding}", {"status": "closed"}, app=self.auditor)[0], 400)
        closed = self.ok("PATCH", f"/findings/{finding}", {"status": "closed", "closure_note": "Faaliyet doğrulandı"},
                         app=self.auditor)
        self.assertIsNotNone(closed["closed_at"])
        self.assertEqual(self.call("POST", "/grc_actions", {"title": "x", "finding_id": finding,
                                                            "owner": "a", "due_date": "2026-12-31"})[0], 409)

    def test_bulgu_kabulu_yalnizca_yonetici(self):
        finding = self.execute({"control_id": self.ctl, "status": "fail", "details": "x"})[1]["finding_id"]
        self.assertEqual(self.call("PATCH", f"/findings/{finding}", {"status": "accepted", "closure_note": "Kabul"},
                                   app=self.auditor)[0], 403)
        self.ok("PATCH", f"/findings/{finding}", {"status": "accepted", "closure_note": "Telafi edici kontrol var"})


class Uyum(GrcBase):
    def test_gosterge_ks_grc_anlaminda(self):
        empty = self.ok("GET", f"/grc/compliance?standard_id={self.std}")
        self.assertEqual((empty["total_controls"], empty["completion_pct"], empty["pass_pct"]), (2, 0.0, None))
        self.assertEqual((empty["clause_count"], empty["mapped_clauses"], empty["framework_coverage_pct"]), (2, 2, 100.0))
        self.execute({"control_id": self.ctl, "status": "pass"})
        self.execute({"control_id": self.auto, "status": "inconclusive"})
        data = self.ok("GET", f"/grc/compliance?standard_id={self.std}")
        self.assertEqual((data["completed"], data["completion_pct"], data["pass_pct"], data["indicative_pct"]),
                         (1, 50.0, 100.0, 50.0))
        self.assertIn("sertifikasyon", data["disclaimer"])
        self.assertEqual(self.call("GET", "/grc/compliance?standard_id=abc")[0], 400)
        overview = self.ok("GET", "/grc/overview")
        self.assertEqual(overview["standards"][0]["framework_coverage_pct"], 100.0)


if __name__ == "__main__":
    unittest.main()
