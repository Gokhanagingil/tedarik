"""Veri yönetişimi Faz 2 — KVKK ve sınıflandırma (K-029): doğrulayıcılar, kişisel veri keşfi (meta veri ve yerel örnek
sayıları), işleme envanteri ve açıklar, saklama ve periyodik imha, risk puanı, veri talepleri, ilgili kişi başvuruları,
VKED ve ihlal ↔ veri varlığı. Test verisi sentetiktir."""
import base64
import json
import unittest
from datetime import date, timedelta

from test_tedarik import Base
from tedarik import pii

CSV = """SCHEMA_NAME;TABLE_NAME;COLUMN_NAME;POSITION;DATA_TYPE;DATA_LENGTH;COLUMN_COMMENT
CRM;MUSTERI;MUSTERI_NO;1;NVARCHAR;10;Müşteri numarası
CRM;MUSTERI;AD_SOYAD;2;NVARCHAR;80;
CRM;MUSTERI;TCKN;3;NVARCHAR;11;
CRM;MUSTERI;CEP_TELEFONU;4;NVARCHAR;20;
CRM;MUSTERI;SAGLIK_RAPORU;5;NVARCHAR;200;
CRM;MUSTERI;NOTLAR;6;NVARCHAR;500;
CRM;URUN;URUN_ADI;1;NVARCHAR;80;
CRM;URUN;NAME;2;NVARCHAR;80;
"""


def day(n):
    return (date.today() + timedelta(days=n)).isoformat()


class Dogrulayicilar(unittest.TestCase):
    def test_bilinen_ornekler_ve_yerel_tarama(self):
        self.assertTrue(pii.is_tckn("10000000146"))
        self.assertFalse(pii.is_tckn("10000000147"))
        self.assertFalse(pii.is_tckn("01234567890"))
        self.assertTrue(pii.is_iban("TR33 0006 1005 1978 6457 8413 26"))
        self.assertFalse(pii.is_iban("TR330006100519786457841327"))
        self.assertTrue(pii.is_card("4111 1111 1111 1111"))
        self.assertFalse(pii.is_card("4111111111111112"))
        self.assertTrue(pii.is_phone("0532 123 45 67") and pii.is_phone("+90 212 555 00 00"))
        self.assertTrue(pii.is_email("ad.soyad@ornek.com.tr") and not pii.is_email("ornek.com"))
        self.assertTrue(pii.is_ipv4("10.20.30.40") and not pii.is_ipv4("999.1.1.1"))
        stats = pii.scan(["kimlik", "aciklama"], [["10000000146", "x"], ["10000000146", ""], ["", "y"]])
        self.assertEqual(stats["columns"]["kimlik"], {"non_empty": 2, "matches": {"tckn": 2}})
        self.assertNotIn("10000000146", json.dumps(stats))                 # değer dönmez, yalnızca sayı


class KvkkBase(Base):
    def setUp(self):
        super().setUp()
        self.unit = self.ok("POST", "/org_units", {"name": "Müşteri Hizmetleri"})["id"]
        self.dom = self.ok("POST", "/data_domains", {"name": "Müşteri", "org_unit_id": self.unit, "owner": "veri.sahibi"})["id"]
        self.sid = self.ok("POST", "/data_sources", {"name": "CRM", "platform": "sql_server", "domain_id": self.dom,
                                                     "custodian": "crm.ekibi"})["id"]
        raw = base64.b64encode(CSV.encode()).decode()
        self.ok("POST", f"/data_sources/{self.sid}/import", {"filename": "crm.csv", "content_base64": raw})
        tables = self.ok("GET", f"/datagov/tables?source_id={self.sid}")["items"]
        self.musteri = next(t["id"] for t in tables if t["name"] == "MUSTERI")
        self.urun = next(t["id"] for t in tables if t["name"] == "URUN")
        cols = self.ok("GET", f"/data_tables/{self.musteri}/context")["columns"]
        self.col = {c["name"]: c["id"] for c in cols}


class Kesif(KvkkBase):
    def test_meta_veri_kesfi_kabul_red_ve_sinif(self):
        run = self.ok("POST", "/datagov/discovery/run", {"source_id": self.sid})
        self.assertGreaterEqual(run["new"], 4)
        items = self.ok("GET", f"/datagov/discovery?source_id={self.sid}")["items"]
        by = {(i["column_name"], i["category_name"]): i for i in items}
        self.assertIn(("TCKN", "Kimlik"), by)
        self.assertIn(("CEP_TELEFONU", "İletişim"), by)
        self.assertIn(("SAGLIK_RAPORU", "Sağlık Bilgileri"), by)
        self.assertIn(("AD_SOYAD", "Kimlik"), by)
        self.assertFalse(any(i["table_name"] == "URUN" for i in items))     # zayıf 'name' güçlü eşleşmesiz tabloda öneri olmaz
        self.assertFalse(any(i["column_name"] == "NOTLAR" for i in items))
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("POST", f"/pii_suggestions/{by[('TCKN', 'Kimlik')]['id']}/accept", {}, app=viewer)[0], 403)
        self.ok("POST", f"/pii_suggestions/{by[('TCKN', 'Kimlik')]['id']}/accept", {})
        self.ok("POST", f"/pii_suggestions/{by[('SAGLIK_RAPORU', 'Sağlık Bilgileri')]['id']}/accept", {})
        self.ok("POST", f"/pii_suggestions/{by[('AD_SOYAD', 'Kimlik')]['id']}/reject", {"note": "Test"})
        self.assertEqual(self.call("POST", f"/pii_suggestions/{by[('TCKN', 'Kimlik')]['id']}/accept", {})[0], 409)
        cols = {c["name"]: c for c in self.ok("GET", f"/data_tables/{self.musteri}/context")["columns"]}
        self.assertEqual((cols["TCKN"]["personal_data"], cols["TCKN"]["classification"]), ("personal", "confidential"))
        self.assertEqual((cols["SAGLIK_RAPORU"]["personal_data"], cols["SAGLIK_RAPORU"]["classification"]), ("special", "restricted"))
        again = self.ok("POST", "/datagov/discovery/run", {"source_id": self.sid})
        self.assertEqual(again["new"], 0)                                    # reddedilen ve kabul edilen yeniden açılmaz
        bulk = self.ok("POST", "/datagov/discovery/bulk", {"ids": [i["id"] for i in self.ok("GET", "/datagov/discovery")["items"]],
                                                         "action": "accept"})
        self.assertGreaterEqual(bulk["done"], 1)
        risk = self.ok("GET", f"/data_tables/{self.musteri}/risk")
        self.assertTrue(risk["special"])
        self.assertIn("işleme envanterinde değil", risk["gaps"])
        self.assertEqual({k["name"] for k in risk["column_categories"]} >= {"Kimlik", "Sağlık Bilgileri"}, True)

    def test_yerel_ornek_sayilari_ve_birim_kapsami(self):
        stats = pii.scan(["TCKN", "NOTLAR", "YOK"], [["10000000146", "a", "1"]] * 9 + [["123", "b", "2"]])
        r = self.ok("POST", f"/data_tables/{self.musteri}/sample-stats", stats)
        self.assertEqual([f["column"] for f in r["findings"]], ["TCKN"])
        self.assertEqual(r["unknown_columns"], ["YOK"])
        item = next(i for i in self.ok("GET", f"/datagov/discovery?table_id={self.musteri}")["items"] if i["column_name"] == "TCKN")
        self.assertEqual(item["method"], "sample")
        self.assertIn("%90", item["evidence"])
        self.assertEqual(self.call("POST", f"/data_tables/{self.musteri}/sample-stats", {"columns": {"TCKN": {"non_empty": "x"}}})[0], 400)
        other = self.make(role="UNIT_USER", user="baska", units="999")
        self.assertEqual(self.call("POST", f"/data_tables/{self.musteri}/sample-stats", stats, app=other)[0], 403)
        steward = self.make(role="UNIT_USER", user="veri.yoneticisi", units=str(self.unit))
        self.ok("POST", f"/pii_suggestions/{item['id']}/accept", {}, app=steward)
        cats = self.ok("GET", "/personal_data_categories?limit=100")
        iletisim = next(k["id"] for k in cats if k["name"] == "İletişim")
        self.ok("POST", f"/data_columns/{self.col['CEP_TELEFONU']}/categories", {"category_ids": [iletisim]}, app=steward)
        cols = {c["name"]: c for c in self.ok("GET", f"/data_tables/{self.musteri}/context")["columns"]}
        self.assertEqual(cols["CEP_TELEFONU"]["personal_data"], "personal")


class Envanter(KvkkBase):
    def test_faaliyet_aciklari_baglantilar_ve_verbis(self):
        self.ok("POST", "/datagov/discovery/run", {})
        for i in self.ok("GET", "/datagov/discovery")["items"]:
            self.ok("POST", f"/pii_suggestions/{i['id']}/accept", {})
        body = {"name": "Müşteri ilişkileri yönetimi", "purpose": "Müşteriyle sözleşme ilişkisinin yürütülmesi",
                "org_unit_id": self.unit, "owner": "veri.sahibi"}
        self.assertEqual(self.call("POST", "/processing_activities", {**body, "status": "active"})[0], 400)   # hukuki sebep
        aid = self.ok("POST", "/processing_activities", body)["id"]
        ctx = self.ok("GET", f"/processing_activities/{aid}/context")
        keys = {g["key"] for g in ctx["gaps"]}
        self.assertTrue({"legal_basis", "categories", "subjects", "retention", "notice"} <= keys)
        cats = {k["name"]: k["id"] for k in self.ok("GET", "/personal_data_categories?limit=100")}
        groups = {g["name"]: g["id"] for g in self.ok("GET", "/data_subject_groups?limit=100")}
        sup = self.ok("POST", "/suppliers", {"name": "Bulut CRM Hizmetleri A.Ş.", "tier": "critical"})["id"]
        ctx = self.ok("POST", f"/processing_activities/{aid}/links", {
            "categories": [cats["Kimlik"]], "subjects": [groups["Müşteri"]], "tables": [self.musteri],
            "processors": [{"supplier_id": sup, "role": "processor", "dpa_signed": False}]})
        self.assertEqual({k["name"] for k in ctx["observed_categories"]} >= {"Kimlik", "İletişim", "Sağlık Bilgileri"}, True)
        keys = {g["key"] for g in ctx["gaps"]}
        self.assertIn("categories_mismatch", keys)
        self.assertIn("special_basis", keys)                                  # sağlık verisi → md. 6
        ctx = self.ok("POST", f"/processing_activities/{aid}/adopt-categories", {})
        self.assertNotIn("categories_mismatch", {g["key"] for g in ctx["gaps"]})
        rule = self.ok("POST", "/retention_rules", {"name": "Müşteri kayıtları", "period_value": 10, "period_unit": "year",
                                                    "trigger_event": "Sözleşme ilişkisinin sona ermesi",
                                                    "legal_reference": "Örnek dayanak (sentetik)"})["id"]
        self.ok("PATCH", f"/processing_activities/{aid}", {"legal_basis": "contract", "special_legal_basis": "explicit_consent",
                                                           "retention_rule_id": rule, "foreign_transfer": 1,
                                                           "transfer_countries": "İrlanda", "transfer_mechanism": "standard_contract",
                                                           "transfer_signed_on": "2026-03-02", "transfer_notified_on": "2026-03-12",
                                                           "security_measures": "Şifreleme, erişim kontrolü", "status": "active"})
        ctx = self.ok("GET", f"/processing_activities/{aid}/context")
        keys = {g["key"] for g in ctx["gaps"]}
        self.assertIn("transfer_late", keys)                                   # 5 iş günü: 9 Mart
        self.assertEqual(ctx["transfer_notice_deadline"], "2026-03-09")
        self.assertTrue(ctx["dpia_required"])
        self.assertIn("dpia", keys)
        dpia = self.ok("POST", "/dpias", {"activity_id": aid, "title": "CRM VKED", "necessity": "Sözleşme için gerekli",
                                          "risks": "Sağlık verisinin ifşası", "measures": "Ayrı şema ve maskeleme",
                                          "residual_risk": "medium", "decision": "proceed_with_measures"})["id"]
        self.ok("POST", f"/dpias/{dpia}/submit", {})
        self.assertEqual(self.call("POST", f"/dpias/{dpia}/approve", {})[0], 403)          # hazırlayan onaylayamaz
        other = self.make(role="SUPPLIER_MANAGER", user="kvkk.sorumlusu")
        self.ok("POST", f"/dpias/{dpia}/approve", {}, app=other)
        self.assertNotIn("dpia", {g["key"] for g in self.ok("GET", f"/processing_activities/{aid}/context")["gaps"]})
        self.assertEqual(self.call("PATCH", f"/dpias/{dpia}", {"risks": "x"})[0], 400)
        risk = self.ok("GET", f"/data_tables/{self.musteri}/risk")
        self.assertIn("veri işleyenle sözleşme (DPA) yok", risk["gaps"])
        self.assertNotIn("işleme envanterinde değil", risk["gaps"])
        st, out = self.call("GET", "/datagov/verbis-export?format=csv")
        self.assertEqual(st, 200)
        text = out.content.decode("utf-8-sig")
        self.assertIn("Müşteri ilişkileri yönetimi", text)
        self.assertIn("Standart sözleşme", text)
        health = {x["key"]: x for x in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(health["personal_not_in_inventory"]["count"], 0)
        raised = self.ok("POST", f"/data_tables/{self.musteri}/raise-risk", {})
        self.assertTrue(raised["code"].startswith("RSK-"))
        self.assertEqual(self.call("POST", f"/data_tables/{self.musteri}/raise-risk", {})[0], 409)
        rec = self.ok("GET", f"/supplier_risks/{raised['risk_id']}")
        self.assertEqual((rec["category"], rec["owner"]), ("privacy", "veri.sahibi"))
        ov = self.ok("GET", "/datagov/privacy")
        self.assertEqual(ov["columns"]["uncovered"], 0)
        self.assertTrue(any(m["category"] == "Sağlık Bilgileri" for m in ov["matrix"]))


class SaklamaImha(KvkkBase):
    def test_periyodik_imha_ve_degismezlik(self):
        rule = self.ok("POST", "/retention_rules", {"name": "Kampanya listeleri", "period_value": 2, "period_unit": "year",
                                                    "trigger_event": "Kampanya bitişi", "disposal_method": "destruction"})["id"]
        self.ok("PATCH", f"/data_tables/{self.musteri}", {"retention_rule_id": rule})
        health = {x["key"]: x for x in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(health["disposal_overdue"]["count"], 1)               # hiç planlanmadı
        run = self.ok("POST", "/disposal_runs", {"title": "2026 2. dönem periyodik imha", "planned_date": day(0), "owner": "dev"})["id"]
        self.assertEqual(self.call("POST", f"/disposal_runs/{run}/complete", {"summary": "Özet yeterince uzun"})[0], 400)
        ctx = self.ok("POST", f"/disposal_runs/{run}/generate", {})
        self.assertEqual((len(ctx["items"]), ctx["status"]), (1, "in_progress"))
        item = ctx["items"][0]
        self.assertEqual(self.call("POST", f"/disposal_runs/{run}/complete", {"summary": "Özet yeterince uzun"})[0], 400)
        self.ok("PATCH", f"/disposal_items/{item['id']}", {"outcome": "done", "record_count": 1250})
        self.assertEqual(self.call("POST", f"/disposal_runs/{run}/complete", {"summary": "kısa"})[0], 400)
        done = self.ok("POST", f"/disposal_runs/{run}/complete", {"summary": "Süresi dolan 1250 kampanya kaydı yok edildi."})
        self.assertEqual(done["status"], "completed")
        self.assertEqual(self.call("PATCH", f"/disposal_items/{item['id']}", {"record_count": 1})[0], 400)
        self.assertEqual(self.call("PATCH", f"/disposal_runs/{run}", {"title": "x"})[0], 400)
        state = done["state"]
        self.assertFalse(state["overdue"])
        self.assertGreater(state["next_due"], day(150))
        work = self.ok("GET", "/my-work")
        self.assertEqual(work["disposals"], [])
        cal = self.ok("GET", f"/calendar?from={day(150)}&to={day(200)}")
        self.assertTrue(any(e["type"] == "disposal" for e in cal["events"]))


class Talepler(KvkkBase):
    def setUp(self):
        super().setUp()
        cats = {k["name"]: k["id"] for k in self.ok("GET", "/personal_data_categories?limit=100")}
        self.ok("POST", f"/data_columns/{self.col['TCKN']}/categories", {"category_ids": [cats["Kimlik"]]})

    def test_veri_talebi_dort_goz_ve_amac_sinirlamasi(self):
        analyst = self.make(role="UNIT_USER", user="analist", units=str(self.unit))
        owner = self.make(role="UNIT_USER", user="veri.sahibi", units=str(self.unit))
        custodian = self.make(role="UNIT_USER", user="crm.ekibi", units=str(self.unit))
        body = {"kind": "access", "table_id": self.musteri, "purpose": "Şikâyet analizi", "access_until": day(30)}
        self.assertEqual(self.call("POST", "/data_requests", body, app=analyst)[0], 400)          # işleme faaliyeti yok
        aid = self.ok("POST", "/processing_activities", {"name": "Şikâyet yönetimi", "purpose": "Şikâyetlerin çözümü",
                                                         "org_unit_id": self.unit, "legal_basis": "legal_obligation"})["id"]
        rid = self.ok("POST", "/data_requests", {**body, "activity_id": aid}, app=analyst)["id"]
        self.ok("POST", f"/data_requests/{rid}/columns", {"column_ids": [self.col["TCKN"]]}, app=analyst)
        self.assertEqual(self.call("POST", f"/data_requests/{rid}/approve", {}, app=analyst)[0], 403)
        self.assertEqual(self.call("POST", f"/data_requests/{rid}/approve", {}, app=custodian)[0], 403)  # sahip değil
        self.assertEqual(self.ok("GET", "/my-work", app=owner)["data_requests_to_approve"][0]["id"], rid)
        self.ok("POST", f"/data_requests/{rid}/approve", {"note": "Süreli erişim uygun"}, app=owner)
        self.assertEqual(self.call("POST", f"/data_requests/{rid}/fulfill", {"note": "Rol verildi"}, app=owner)[0], 403)
        self.assertEqual(self.ok("GET", "/my-work", app=custodian)["data_requests_to_fulfill"][0]["id"], rid)
        ctx = self.ok("POST", f"/data_requests/{rid}/fulfill", {"note": "Salt okunur rol 30 günlüğüne verildi"}, app=custodian)
        self.assertEqual(ctx["status"], "fulfilled")
        mask = self.ok("POST", "/data_requests", {"kind": "masking", "table_id": self.musteri, "purpose": "Test ortamına maskeli kopya",
                                                  "environment": "UAT"}, app=analyst)["id"]
        self.ok("POST", f"/data_requests/{mask}/reject", {"note": "Sentetik veri kullanın"}, app=owner)
        self.assertEqual(self.call("POST", f"/data_requests/{mask}/cancel", {}, app=analyst)[0], 409)

    def test_ilgili_kisi_basvurusu_30_gun(self):
        groups = {g["name"]: g["id"] for g in self.ok("GET", "/data_subject_groups?limit=100")}
        body = {"received_on": day(-35), "request_type": "access", "description": "Hangi verilerimin işlendiğini öğrenmek istiyorum",
                "owner": "kvkk.sorumlusu", "subject_group_id": groups["Müşteri"], "subject_reference": "CRM-48213"}
        rid = self.ok("POST", "/subject_requests", body)["id"]
        rec = self.ok("GET", f"/subject_requests/{rid}/context")
        self.assertEqual(rec["due_date"], day(-5))
        self.assertTrue(rec["late"])
        self.assertEqual(self.call("POST", "/subject_requests", {**body, "received_on": day(2)})[0], 400)
        health = {x["key"]: x for x in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(health["subject_requests_overdue"]["count"], 1)
        self.assertEqual(self.call("PATCH", f"/subject_requests/{rid}", {"status": "answered"})[0], 400)
        self.assertEqual(self.call("PATCH", f"/subject_requests/{rid}", {"status": "answered", "response_date": day(0),
                                                                          "response_summary": "Veri dökümü gönderildi"})[0], 400)
        self.ok("PATCH", f"/subject_requests/{rid}", {"status": "answered", "response_date": day(0), "identity_verified": 1,
                                                      "response_summary": "Veri dökümü KEP ile gönderildi"})
        self.assertTrue(self.ok("GET", f"/subject_requests/{rid}/context")["late"])
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("GET", "/subject_requests", app=viewer)[0], 403)
        self.ok("POST", f"/subject_requests/{rid}/tables", {"table_ids": [self.musteri]})
        self.assertEqual(len(self.ok("GET", f"/subject_requests/{rid}/context")["tables"]), 1)

    def test_ihlal_veri_varliklari(self):
        breach = self.ok("POST", "/privacy_breaches", {"title": "Liste yanlış alıcıya gitti", "owner": "kvkk.sorumlusu",
                                                       "detected_at": "2026-11-10T09:00:00+00:00", "description": "Sentetik"})["id"]
        self.ok("PATCH", f"/data_tables/{self.musteri}", {"row_count": 4200})
        r = self.ok("POST", f"/privacy_breaches/{breach}/data-assets", {"table_ids": [self.musteri]})
        self.assertEqual(([k["name"] for k in r["categories"]], r["special"], r["max_rows"]), (["Kimlik"], False, 4200))
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("GET", f"/privacy_breaches/{breach}/data-assets", app=viewer)[0], 403)


if __name__ == "__main__":
    unittest.main()
