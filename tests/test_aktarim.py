"""Excel ve CSV aktarımı, şablonlar, meta veri ve Türkçe etiketler. Veri sentetiktir."""
import base64
import importlib.util
import unittest

from test_tedarik import Base

from tedarik.labels import CHOICES, FIELDS, choice
from tedarik.schema import RESOURCES

HAS_XLSX = bool(importlib.util.find_spec("defusedxml"))


def b64(raw):
    return base64.b64encode(raw).decode()


class Etiketler(Base):
    def test_her_alan_ve_secim_etiketli(self):
        self.make(modules="core,performance,surveys,risks,transfer,dashboard,workflow,sourcing")
        missing = sorted({f"{r.name}.{f}" for r in RESOURCES.values() for f in r.fields if f not in FIELDS})
        self.assertEqual(missing, [])
        unlabeled = sorted({f"{r.name}.{f}={v}" for r in RESOURCES.values() for f, values in r.enums.items()
                            for v in values if choice(r.name, f, v) == v and v not in ("R", "A", "C", "I")})
        self.assertEqual(unlabeled, [])
        self.assertTrue(CHOICES["tier"])

    def test_meta_veri_yetkiye_gore(self):
        meta = self.ok("GET", "/metadata")
        suppliers = meta["resources"]["suppliers"]
        tier = next(f for f in suppliers["fields"] if f["name"] == "tier")
        self.assertIn({"value": "critical", "label": "Kritik"}, tier["options"])
        self.assertEqual(next(f for f in meta["resources"]["engagements"]["fields"]
                              if f["name"] == "supplier_id")["ref"], "suppliers")
        self.assertTrue(suppliers["can_write"])
        viewer = self.ok("GET", "/metadata", app=self.make(role="VIEWER"))
        self.assertFalse(viewer["resources"]["suppliers"]["can_write"])
        self.assertNotIn("audit_log", viewer["resources"])
        self.assertEqual(viewer["user"]["role_label"], "Görüntüleyici")


@unittest.skipUnless(HAS_XLSX, "defusedxml kurulu değil (requirements.txt)")
class Excel(Base):
    def setUp(self):
        super().setUp()
        from tedarik.vendor import xlsx_io
        self.xlsx = xlsx_io

    def upload(self, resource, sheets, dry_run=False, name="veri.xlsx", **extra):
        raw = self.xlsx.make_xlsx(sheets)
        return self.call("POST", f"/import/{resource}", {"filename": name, "content_base64": b64(raw),
                                                         "dry_run": dry_run, **extra})

    def test_sablon_doldurulup_aktarilir(self):
        status, reply = self.call("GET", "/import/templates/engagements")
        self.assertEqual(status, 200)
        sheets = self.xlsx.read_xlsx(reply.content)
        self.assertEqual(list(sheets), ["Veri", "Açıklama"])
        header = sheets["Veri"][0]
        self.assertIn("Tedarikçi (kod) *", header)
        self.assertIn("Faydalanan", header)
        notes = {r[0]: r for r in sheets["Açıklama"][1:] if r}
        self.assertIn("Şirket içi", notes["Faydalanan"][2])
        self.ok("POST", "/org_units", {"code": "BT", "name": "Bilgi Teknolojileri"})
        self.ok("POST", "/catalog_items", {"code": "DC", "name": "Barındırma"})
        self.ok("POST", "/suppliers", {"code": "S1", "name": "Örnek Bilişim"})
        index = {h.rstrip(" *"): i for i, h in enumerate(header)}

        def row(**values):
            cells = [""] * len(header)
            for label, value in values.items():
                cells[index[label]] = value
            return cells
        data = [header,
                row(**{"Kod": "E1", "Tedarikçi (kod)": "S1", "Ürün / hizmet (kod)": "DC", "Birim (kod)": "BT",
                       "Faydalanan": "Müşteri", "Müşteri adı": "Banka A", "Başlangıç tarihi": "01.02.2026",
                       "Kritiklik": "Yüksek"}),
                row(**{"Kod": "E2", "Tedarikçi (kod)": "YOK", "Ürün / hizmet (kod)": "DC", "Birim (kod)": "BT"}),
                row(**{"Kod": "E3", "Tedarikçi (kod)": "S1", "Ürün / hizmet (kod)": "DC", "Birim (kod)": "BT",
                       "Faydalanan": "Müşteri"}),                          # müşteri adı kuralı
                row(**{"Kod": "E4", "Tedarikçi (kod)": "S1", "Ürün / hizmet (kod)": "DC", "Birim (kod)": "BT",
                       "Kritiklik": "çok"})]
        preview = self.upload("engagements", {"Veri": data}, dry_run=True)[1]
        self.assertEqual({k: preview[k] for k in ("total", "create", "error")}, {"total": 4, "create": 1, "error": 3})
        self.assertEqual(self.ok("GET", "/engagements"), [])
        self.assertIn("'YOK' kodlu kayıt bulunamadı", preview["rows"][1]["message"])
        self.assertIn("customer_name", preview["rows"][2]["message"])
        self.assertIn("izin verilenler: Kritik, Yüksek, Orta, Düşük", preview["rows"][3]["message"])
        result = self.upload("engagements", {"Veri": data})[1]
        self.assertEqual((result["create"], result["error"]), (1, 3))
        made = self.ok("GET", "/engagements")[0]
        self.assertEqual((made["beneficiary"], made["start_date"], made["criticality"]),
                         ("customer", "2026-02-01", "high"))
        batch = self.ok("GET", f"/import_rows?batch_id={result['batch_id']}")
        self.assertEqual(sorted(r["action"] for r in batch), ["create", "error", "error", "error"])

    def test_portalda_girilen_deger_ezilmez(self):
        self.ok("POST", "/org_units", {"code": "BT", "name": "BT Portal Adı"})
        data = [["Kod", "Ad", "Yönetici"], ["BT", "Excel Adı", "ayse"], ["OPS", "Operasyon", ""]]
        result = self.upload("org_units", {"Birimler": data})[1]
        self.assertEqual((result["update"], result["create"]), (1, 1))
        self.assertIn("Portaldaki değer korundu: Ad", result["rows"][0]["message"])
        unit = self.ok("GET", "/org_units?code=BT")[0]
        self.assertEqual((unit["name"], unit["manager"]), ("BT Portal Adı", "ayse"))
        again = self.upload("org_units", {"Birimler": data})[1]
        self.assertEqual((again["skip"], again["create"]), (2, 0))

    def test_tedarikci_xlsx_kaynak_kimligiyle(self):
        data = [["LIFNR", "NAME1", "STCD2", "Kritiklik seviyesi"], ["100", "Örnek Bilişim A.Ş.", "1234567890", "Kritik"]]
        first = self.upload("suppliers", {"LFA1": data}, source_system="sap")[1]
        self.assertEqual(first["create"], 1)
        supplier = self.ok("GET", "/suppliers")[0]
        self.assertEqual((supplier["tier"], supplier["code"]), ("critical", "TDR-00001"))
        renamed = [data[0], ["100", "Örnek Bilişim (yeni ad)", "", "Standart"]]
        second = self.upload("suppliers", {"LFA1": renamed}, source_system="sap")[1]
        self.assertEqual((second["create"], second["skip"]), (0, 1))
        self.assertEqual(len(self.ok("GET", "/suppliers")), 1)

    def test_formul_ve_makro_reddedilir_disa_aktarim_okunur(self):
        self.ok("POST", "/suppliers", {"code": "S1", "name": "=HYPERLINK(\"x\")", "tier": "critical"})
        status, reply = self.call("GET", "/export/suppliers?format=xlsx")
        self.assertEqual(status, 200)
        sheet = self.xlsx.read_xlsx(reply.content)["Tedarikçiler"]
        self.assertEqual(sheet[0][:3], ["Kayıt No", "Kod", "Ad"])
        self.assertEqual(sheet[1][2], "'=HYPERLINK(\"x\")")
        self.assertIn("Kritik", sheet[1])
        whole = self.xlsx.read_xlsx(self.call("GET", "/export")[1].content)
        self.assertIn("Angajmanlar", whole)
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.xlsx.make_xlsx({"Veri": [["Kod", "Ad"], ["X", "Y"]]}))) as source, \
                zipfile.ZipFile(buffer, "w") as target:
            for item in source.infolist():
                content = source.read(item)
                if item.filename.startswith("xl/worksheets/"):
                    content = content.replace(b'<c r="A2" t="inlineStr" s="0">', b'<c r="A2" s="0"><f>1+1</f>', 1)
                    content = content.replace(b'<is><t xml:space="preserve">X</t></is></c>', b'<v>2</v></c>', 1)
                target.writestr(item, content)
        status, payload = self.call("POST", "/import/org_units", {"filename": "f.xlsx",
                                                                  "content_base64": b64(buffer.getvalue())})
        self.assertEqual(status, 400)
        self.assertIn("Formül", payload["error"])

    def test_yetki(self):
        data = {"filename": "a.csv", "content_base64": b64("Kod;Ad\r\nA;B\r\n".encode())}
        self.assertEqual(self.call("POST", "/import/org_units", data, app=self.make(role="UNIT_USER", units="1"))[0],
                         403)
        self.assertEqual(self.app.dispatch("GET", "/api/tdr/export", {"X-API-Key": "k" * 40})[0], 403)
        self.assertEqual(self.ok("POST", "/import/org_units", data)["create"], 1)    # CSV de aynı hattan
        catalog = self.ok("GET", "/transfer/catalog")
        self.assertIn("engagements", [i["resource"] for i in catalog["imports"]])


if __name__ == "__main__":
    unittest.main()
