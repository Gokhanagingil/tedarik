"""Veri yönetişimi (K-028): yol haritası, katalog içe aktarımı (SAP HANA, SAP ABAP sözlüğü, ServiceNow, Dynamics 365,
Power BI, kendi JSON sözleşmesi), şema değişikliği, iş açıklamaları, iş sözlüğü onay akışı, sahiplik ve kapsam.
Test verisi sentetiktir."""
import base64
import gzip
import importlib.util
import json
import unittest

from test_tedarik import Base


def upload(name, text, **extra):
    raw = text.encode("utf-8") if isinstance(text, str) else text
    return {"filename": name, "content_base64": base64.b64encode(raw).decode(), **extra}


HANA = """SCHEMA_NAME;TABLE_NAME;OBJECT_TYPE;TABLE_COMMENT;COLUMN_NAME;POSITION;DATA_TYPE;DATA_LENGTH;SCALE;NULLABLE;PRIMARY_KEY;REFERENCES_TO;COLUMN_COMMENT
SATIS;MUSTERI;TABLE;Müşteri ana verisi;MUSTERI_NO;1;NVARCHAR;10;0;FALSE;YES;;Müşteri numarası
SATIS;MUSTERI;TABLE;Müşteri ana verisi;AD_SOYAD;2;NVARCHAR;80;0;TRUE;NO;;
SATIS;MUSTERI;TABLE;Müşteri ana verisi;TCKN;3;NVARCHAR;11;0;TRUE;NO;;
SATIS;SIPARIS;TABLE;;SIPARIS_NO;1;NVARCHAR;10;0;FALSE;YES;;
SATIS;SIPARIS;TABLE;;MUSTERI_NO;2;NVARCHAR;10;0;FALSE;NO;SATIS.MUSTERI.MUSTERI_NO;
SATIS;SIPARIS;TABLE;;TUTAR;3;DECIMAL;15;2;TRUE;NO;;
FINANS;FATURA;VIEW;;FATURA_NO;1;NVARCHAR;12;0;FALSE;NO;;
"""


class YolHaritasi(Base):
    def test_surum_maddeleri_salt_okunur_kurum_maddesi_eklenir(self):
        data = self.ok("GET", "/roadmap")
        dg = next(m for m in data["modules"] if m["key"] == "datagov")
        self.assertGreater(dg["total"], 20)
        phase1 = next(p for p in data["phases"] if p["module"] == "datagov" and p["phase"] == 1)
        self.assertEqual(phase1["status"], "done")
        self.assertTrue(any(n["key"] == "dg.3.powerbi" for n in data["needs"]))
        item = next(i for i in phase1["items"] if i["key"] == "dg.1.glossary")
        self.assertEqual(self.call("PATCH", f"/roadmap_items/{item['id']}", {"status": "planned"})[0], 400)
        self.ok("PATCH", f"/roadmap_items/{item['id']}", {"note": "Kurumda pilot: Satış alanı", "target": "2027-Ç1"})
        own = self.ok("POST", "/roadmap_items", {"module": "datagov", "phase": 3, "title": "Oracle EBS bağlayıcısı",
                                                 "status": "planned"})["id"]
        self.ok("PATCH", f"/roadmap_items/{own}", {"status": "done"})
        rec = self.ok("GET", f"/roadmap_items/{own}")
        self.assertEqual((rec["source"], rec["status"]), ("custom", "done"))
        self.assertIsNotNone(rec["completed_on"])
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("GET", "/roadmap", app=viewer)[0], 200)
        self.assertEqual(self.call("POST", "/roadmap_items", {"module": "platform", "title": "x"}, app=viewer)[0], 403)
        from tedarik.modules.core import sync_roadmap
        with self.db() as db:                     # yeniden eşitleme kurum notunu korur
            sync_roadmap(db)
        self.assertEqual(self.ok("GET", f"/roadmap_items/{item['id']}")["note"], "Kurumda pilot: Satış alanı")


class Katalog(Base):
    def source(self, **kw):
        body = {"name": kw.pop("name", "SAP S/4HANA Üretim"), "platform": kw.pop("platform", "sap_hana"), **kw}
        return self.ok("POST", "/data_sources", body)["id"]

    def test_hana_icerik_aktarimi_on_izleme_ve_degisiklik(self):
        sid = self.source()
        preview = self.ok("POST", f"/data_sources/{sid}/import", upload("hana.csv", HANA, dry_run=True))
        self.assertEqual((preview["tables_in_file"], preview["columns_in_file"]), (3, 7))
        self.assertEqual(preview["counts"]["table_added"], 3)
        self.assertEqual(self.ok("GET", f"/datagov/tables?source_id={sid}")["total"], 0)       # ön izleme yazmaz
        first = self.ok("POST", f"/data_sources/{sid}/import", upload("hana.csv", HANA))
        self.assertTrue(first["initial"])
        tables = self.ok("GET", f"/datagov/tables?source_id={sid}")["items"]
        self.assertEqual(sorted(t["name"] for t in tables), ["FATURA", "MUSTERI", "SIPARIS"])
        fatura = next(t for t in tables if t["name"] == "FATURA")
        self.assertEqual(fatura["object_type"], "view")
        musteri = next(t for t in tables if t["name"] == "MUSTERI")
        ctx = self.ok("GET", f"/data_tables/{musteri['id']}/context")
        self.assertEqual(ctx["technical_description"], "Müşteri ana verisi")
        mno = next(c for c in ctx["columns"] if c["name"] == "MUSTERI_NO")
        self.assertEqual((mno["is_primary_key"], mno["nullable"], mno["data_length"]), (1, 0, "10"))
        self.assertEqual(len(ctx["referenced_by"]), 1)                    # SIPARIS.MUSTERI_NO → MUSTERI.MUSTERI_NO
        siparis = next(t for t in tables if t["name"] == "SIPARIS")
        tutar = next(c for c in self.ok("GET", f"/data_tables/{siparis['id']}/context")["columns"] if c["name"] == "TUTAR")
        self.assertEqual(tutar["data_length"], "15,2")
        ref = next(c for c in self.ok("GET", f"/data_tables/{siparis['id']}/context")["columns"] if c["name"] == "MUSTERI_NO")
        col = self.ok("GET", f"/data_columns/{ref['id']}/context")
        self.assertEqual(col["references"][0]["column_id"], mno["id"])
        # iş tanımı ekle; yeniden yükleme tanımı korur, değişiklikleri kaydeder
        self.ok("PATCH", f"/data_columns/{mno['id']}", {"business_name": "Müşteri numarası", "description": "SAP müşteri kodu"})
        changed = HANA.replace("AD_SOYAD;2;NVARCHAR;80", "AD_SOYAD;2;NVARCHAR;120").replace(
            "SATIS;MUSTERI;TABLE;Müşteri ana verisi;TCKN;3;NVARCHAR;11;0;TRUE;NO;;\n", "") + \
            "SATIS;MUSTERI;TABLE;Müşteri ana verisi;EPOSTA;4;NVARCHAR;120;0;TRUE;NO;;\n"
        changed = "\n".join(line for line in changed.splitlines() if not line.startswith("FINANS")) + "\n"
        second = self.ok("POST", f"/data_sources/{sid}/import", upload("hana2.csv", changed, scope="full"))
        counts = second["counts"]
        self.assertEqual((counts["type_changed"], counts["column_added"], counts["column_removed"], counts["table_removed"]),
                         (1, 1, 1, 1))
        ctx = self.ok("GET", f"/data_tables/{musteri['id']}/context")
        mno = next(c for c in ctx["columns"] if c["name"] == "MUSTERI_NO")
        self.assertEqual(mno["business_name"], "Müşteri numarası")
        ad = next(c for c in ctx["columns"] if c["name"] == "AD_SOYAD")
        self.assertEqual((ad["data_length"], ad["previous_type"]), ("120", "NVARCHAR(80)"))
        self.assertEqual(next(c for c in ctx["columns"] if c["name"] == "TCKN")["status"], "removed")
        kinds = {x["change"] for x in ctx["changes"]}
        self.assertTrue({"column_added", "column_removed", "type_changed"} <= kinds)
        self.assertEqual(self.ok("GET", f"/data_tables/{fatura['id']}")["status"], "removed")
        third = self.ok("POST", f"/data_sources/{sid}/import", upload("hana.csv", HANA, scope="full"))
        self.assertEqual((third["counts"]["table_restored"], third["counts"]["column_restored"]), (1, 1))
        with self.db() as db:                                              # değişiklik geçmişi değiştirilemez
            with self.assertRaises(Exception):
                db.execute("UPDATE tdr_catalog_changes SET detail='x'")
        self.assertEqual(len(self.ok("GET", f"/data_sources/{sid}/context")["imports"]), 3)

    def test_kapsam_tablolar_disariyi_kaldirmaz_ve_gzip(self):
        sid = self.source()
        self.ok("POST", f"/data_sources/{sid}/import", upload("hana.csv", HANA))
        only = "TABLE_NAME;COLUMN_NAME;DATA_TYPE\nMUSTERI;MUSTERI_NO;NVARCHAR\n"
        r = self.ok("POST", f"/data_sources/{sid}/import", upload("tek.csv", gzip.compress(only.encode()),
                                                                  compressed="gzip", default_schema="SATIS"))
        self.assertNotIn("table_removed", r["counts"])
        self.assertEqual(r["counts"]["column_removed"], 2)                 # yalnızca dosyadaki tablonun kolonları
        self.assertEqual(self.ok("GET", f"/datagov/tables?source_id={sid}")["total"], 3)
        bomb = gzip.compress(b"a" * (125 * 1024 * 1024))
        self.assertEqual(self.call("POST", f"/data_sources/{sid}/import", upload("x.csv", bomb, compressed="gzip"))[0], 400)

    def test_sap_ddic_servicenow_dynamics_powerbi_ve_json(self):
        sap = self.source(name="SAP ECC")
        ddic = ("TABNAME,FIELDNAME,POSITION,DATATYPE,LENG,DECIMALS,KEYFLAG,NOTNULL,CHECKTABLE,DDTEXT,SCRTEXT_L\n"
                "KNA1,MANDT,0001,CLNT,000003,000000,X,X,T000,Genel müşteri ana verileri,Üst birim\n"
                "KNA1,KUNNR,0002,CHAR,000010,000000,X,X,,Genel müşteri ana verileri,Müşteri\n"
                "KNA1,.INCLUDE,0003,,000000,000000,,,,Genel müşteri ana verileri,\n"
                "KNA1,STCD1,0004,CHAR,000016,000000,,,,Genel müşteri ana verileri,Vergi numarası 1\n")
        r = self.ok("POST", f"/data_sources/{sap}/import", upload("dd03l.csv", ddic, default_schema="SAPABAP1"))
        self.assertEqual((r["format"], r["columns_in_file"]), ("sap_ddic", 3))
        t = self.ok("GET", f"/datagov/tables?source_id={sap}")["items"][0]
        self.assertEqual((t["schema_name"], t["technical_description"]), ("SAPABAP1", "Genel müşteri ana verileri"))
        cols = {c["name"]: c for c in self.ok("GET", f"/data_tables/{t['id']}/context")["columns"]}
        self.assertEqual((cols["KUNNR"]["data_length"], cols["KUNNR"]["is_primary_key"], cols["MANDT"]["references_to"]),
                         ("10", 1, "T000"))
        sn = self.source(name="ServiceNow", platform="servicenow")
        result = {"result": [
            {"name": {"value": "incident", "display_value": "incident"}, "element": {"value": "", "display_value": ""},
             "column_label": {"value": "Incident", "display_value": "Olay"}, "internal_type": {"value": "collection"}},
            {"name": "incident", "element": "sys_id", "column_label": "Sys ID", "internal_type": "GUID", "max_length": "32"},
            {"name": "incident", "element": "caller_id", "column_label": {"display_value": "Arayan", "value": "Caller"},
             "internal_type": {"display_value": "Referans", "value": "reference"}, "reference": {"value": "sys_user"},
             "mandatory": "true", "max_length": "32"}]}
        r = self.ok("POST", f"/data_sources/{sn}/import", upload("sys_dictionary.json", json.dumps(result)))
        self.assertEqual(r["format"], "servicenow")
        t = self.ok("GET", f"/datagov/tables?source_id={sn}")["items"][0]
        cols = {c["name"]: c for c in self.ok("GET", f"/data_tables/{t['id']}/context")["columns"]}
        self.assertEqual((t["technical_description"], cols["sys_id"]["is_primary_key"], cols["caller_id"]["references_to"],
                          cols["caller_id"]["nullable"], cols["caller_id"]["data_type"]), ("Olay", 1, "sys_user", 0, "reference"))
        crm = self.source(name="Dynamics 365", platform="dynamics365")
        label = lambda tr, en: {"LocalizedLabels": [{"Label": en, "LanguageCode": 1033}, {"Label": tr, "LanguageCode": 1055}],  # noqa: E731
                                "UserLocalizedLabel": {"Label": en, "LanguageCode": 1033}}
        ents = {"value": [{"LogicalName": "account", "DisplayName": label("Firma", "Account"), "PrimaryIdAttribute": "accountid",
                           "Attributes": [{"LogicalName": "accountid", "AttributeType": "Uniqueidentifier", "IsPrimaryId": True,
                                           "DisplayName": label("Firma", "Account"), "RequiredLevel": {"Value": "SystemRequired"}},
                                          {"LogicalName": "name", "AttributeType": "String", "DisplayName": label("Firma adı", "Account Name"),
                                           "RequiredLevel": {"Value": "ApplicationRequired"}},
                                          {"LogicalName": "createdbyname", "AttributeType": "String", "AttributeOf": "createdby"}]}]}
        r = self.ok("POST", f"/data_sources/{crm}/import", upload("entities.json", json.dumps(ents)))
        t = self.ok("GET", f"/datagov/tables?source_id={crm}")["items"][0]
        cols = {c["name"]: c for c in self.ok("GET", f"/data_tables/{t['id']}/context")["columns"]}
        self.assertEqual((r["columns_in_file"], t["object_type"], t["technical_description"], cols["name"]["technical_description"]),
                         (2, "entity", "Firma", "Firma adı"))
        pbi = self.source(name="Satış Performans Modeli", platform="power_bi")
        dax = "[Table],[Name],[DataType],[Description],[IsKey],[IsNullable]\nDimMusteri,MusteriKey,Int64,,True,False\n" \
              "FactSatis,Tutar,Decimal,Net satış tutarı,False,True\n"
        r = self.ok("POST", f"/data_sources/{pbi}/import", upload("info_view_columns.csv", dax, default_schema="Satış Modeli"))
        self.assertEqual((r["tables_in_file"], r["columns_in_file"]), (2, 2))
        own = self.source(name="Toplayıcı", platform="postgresql")
        doc = {"format": "tedarik.catalog.v1", "tables": [{"schema": "public", "name": "orders", "object_type": "BASE TABLE",
               "row_count": 1200, "columns": [{"name": "id", "data_type": "bigint", "primary_key": True, "nullable": False}]}]}
        r = self.ok("POST", f"/data_sources/{own}/import", upload("catalog.json", json.dumps(doc)))
        t = self.ok("GET", f"/datagov/tables?source_id={own}")["items"][0]
        self.assertEqual((r["format"], t["row_count"]), ("tedarik.catalog.v1", 1200))
        self.assertEqual(self.call("POST", f"/data_sources/{own}/import", upload("x.json", '{"foo": 1}'))[0], 400)
        self.assertEqual(self.call("POST", f"/data_sources/{own}/import", upload("x.csv", "a;b\n1;2\n"))[0], 400)
        q = self.ok("GET", "/datagov/queries?platform=sap_hana")["queries"]
        self.assertTrue(any("DD03L" in x["text"] for x in q) and any(x["kind"] == "template" for x in q))

    def test_aciklama_disa_ve_ice_aktarim_ve_yetki(self):
        sid = self.source()
        self.ok("POST", f"/data_sources/{sid}/import", upload("hana.csv", HANA))
        term = self.ok("POST", "/glossary_terms", {"name": "Müşteri numarası", "definition": "Müşteriyi tekil tanımlayan kod"})["id"]
        status, payload = self.call("GET", f"/data_sources/{sid}/export?format=csv")
        self.assertEqual(status, 200)
        text = payload.content.decode("utf-8-sig")
        self.assertIn("İş adı", text.splitlines()[0])
        filled = ("Şema;Tablo;Kolon;İş adı;Açıklama;Sınıf;Kişisel veri;Kritik veri;Terimler;Sahip\n"
                  "SATIS;MUSTERI;;Müşteri;Müşteri ana kaydı;Gizli;;;;satis.mudur\n"
                  "SATIS;MUSTERI;TCKN;T.C. kimlik numarası;;Çok gizli;Kişisel veri;Evet;;\n"
                  "SATIS;MUSTERI;MUSTERI_NO;;;;;;Müşteri numarası;\n"
                  "SATIS;YOK;;x;;;;;;\n"
                  "SATIS;MUSTERI;AD_SOYAD;;;Süper gizli;;;;\n")
        dry = self.ok("POST", f"/data_sources/{sid}/import-descriptions", upload("aciklama.csv", filled, dry_run=True))
        self.assertEqual((dry["counts"]["tables_updated"], dry["counts"]["columns_updated"], dry["counts"]["terms_linked"],
                          dry["counts"]["errors"]), (1, 1, 1, 2))
        self.ok("POST", f"/data_sources/{sid}/import-descriptions", upload("aciklama.csv", filled))
        musteri = next(t for t in self.ok("GET", f"/datagov/tables?source_id={sid}")["items"] if t["name"] == "MUSTERI")
        self.assertEqual((musteri["classification"], musteri["eff_owner"], musteri["documented_count"]), ("confidential", "satis.mudur", 2))
        tckn = next(c for c in self.ok("GET", f"/data_tables/{musteri['id']}/context")["columns"] if c["name"] == "TCKN")
        self.assertEqual((tckn["classification"], tckn["personal_data"], tckn["is_critical"]), ("restricted", "personal", 1))
        used = self.ok("GET", f"/glossary_terms/{term}/context")
        self.assertEqual(used["used_in"][0]["count"], 1)
        st, xl = self.call("GET", f"/data_sources/{sid}/export?format=xlsx&only=undocumented")
        if importlib.util.find_spec("defusedxml"):
            self.assertEqual(st, 200)
            self.assertTrue(xl.content[:2] == b"PK")
        else:                                          # paketsiz kurulum: Excel yerine CSV önerilir
            self.assertEqual(st, 400)
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("POST", f"/data_sources/{sid}/import", upload("hana.csv", HANA), app=viewer)[0], 403)
        self.assertEqual(self.call("PATCH", f"/data_columns/{tckn['id']}", {"description": "x"}, app=viewer)[0], 403)
        self.assertEqual(self.ok("GET", "/datagov/search?q=kimlik")["columns"][0]["name"], "TCKN")
        self.assertEqual(self.ok("GET", f"/datagov/tables?source_id={sid}&filter=personal")["total"], 1)
        adopt = self.ok("POST", f"/data_tables/{musteri['id']}/adopt-descriptions", {})
        self.assertGreaterEqual(adopt["adopted"], 0)


class Sozluk(Base):
    def test_dort_goz_onay_degisiklik_onerisi_ve_surum(self):
        unit = self.ok("POST", "/org_units", {"name": "Satış"})["id"]
        dom = self.ok("POST", "/data_domains", {"name": "Müşteri", "org_unit_id": unit, "owner": "veri.sahibi"})["id"]
        steward = self.make(role="UNIT_USER", user="veri.yoneticisi", units=str(unit))
        other_unit = self.make(role="UNIT_USER", user="baska.birim", units="999")
        owner = self.make(role="UNIT_USER", user="veri.sahibi", units=str(unit))
        body = {"name": "Aktif müşteri", "definition": "Son 12 ayda en az bir faturası olan müşteri", "domain_id": dom,
                "calculation": "COUNT(DISTINCT müşteri) WHERE fatura_tarihi >= bugün - 12 ay"}
        self.assertEqual(self.call("POST", "/glossary_terms", body, app=other_unit)[0], 403)       # kapsam dışı
        self.assertEqual(self.call("POST", "/glossary_terms", {**body, "domain_id": None}, app=steward)[0], 403)
        term = self.ok("POST", "/glossary_terms", body, app=steward)["id"]
        self.assertEqual(self.call("POST", "/glossary_terms", body, app=steward)[0], 400)          # aynı alanda aynı ad
        self.ok("POST", f"/glossary_terms/{term}/submit", {}, app=steward)
        self.assertEqual(self.call("PATCH", f"/glossary_terms/{term}", {"definition": "x"}, app=steward)[0], 400)
        self.assertEqual(self.call("POST", f"/glossary_terms/{term}/approve", {}, app=steward)[0], 403)   # öneren
        self.assertEqual(self.call("POST", f"/glossary_terms/{term}/approve", {}, app=other_unit)[0], 403)
        self.assertEqual(self.call("POST", f"/glossary_terms/{term}/reject", {"note": ""}, app=owner)[0], 400)
        self.ok("POST", f"/glossary_terms/{term}/reject", {"note": "Hesaplama dönemini netleştirin"}, app=owner)
        work = self.ok("GET", "/my-work", app=steward)
        self.assertEqual(work["glossary_returned"][0]["id"], term)
        self.ok("PATCH", f"/glossary_terms/{term}", {"definition": "Son 12 takvim ayında en az bir faturası olan müşteri"}, app=steward)
        self.ok("POST", f"/glossary_terms/{term}/submit", {}, app=steward)
        self.assertEqual(self.ok("GET", "/my-work", app=owner)["glossary_to_approve"][0]["id"], term)
        ctx = self.ok("POST", f"/glossary_terms/{term}/approve", {"note": "Uygun"}, app=owner)
        self.assertEqual((ctx["status"], ctx["version"], len(ctx["versions"])), ("approved", 1, 1))
        self.assertEqual(self.call("PATCH", f"/glossary_terms/{term}", {"definition": "x"}, app=steward)[0], 400)
        self.assertEqual(self.call("POST", f"/glossary_terms/{term}/propose", {"changes": {"definition": "Son 12 takvim "
                         "ayında en az bir faturası olan müşteri"}, "note": "aynı"}, app=steward)[0], 400)
        self.ok("POST", f"/glossary_terms/{term}/propose", {"changes": {"definition": "Son 12 ayda faturası veya aktif "
                "sözleşmesi olan müşteri"}, "note": "Sözleşmeli müşteriler de sayılmalı"}, app=steward)
        self.assertEqual(self.call("POST", f"/glossary_terms/{term}/propose", {"changes": {"example": "x"}, "note": "ikinci"},
                                   app=steward)[0], 409)
        ctx = self.ok("GET", f"/glossary_terms/{term}/context", app=owner)
        self.assertTrue(ctx["can"]["approve"])
        self.assertEqual(ctx["pending"]["fields"][0]["field"], "definition")
        self.assertIn("12 takvim", ctx["definition"])                         # onaylanana kadar eski tanım geçerli
        ctx = self.ok("POST", f"/glossary_terms/{term}/approve", {}, app=owner)
        self.assertEqual((ctx["version"], len(ctx["versions"]), ctx["pending"]), (2, 2, None))
        self.assertIn("sözleşmesi", ctx["definition"])
        old = json.loads(ctx["versions"][1]["snapshot_json"])
        self.assertIn("12 takvim", old["definition"])
        with self.db() as db:
            with self.assertRaises(Exception):
                db.execute("UPDATE tdr_glossary_term_versions SET change_note='x'")
        repl = self.ok("POST", "/glossary_terms", {"name": "Etkin müşteri", "definition": "Yeni tanım", "domain_id": dom})["id"]
        self.ok("POST", f"/glossary_terms/{repl}/submit", {})
        self.ok("POST", f"/glossary_terms/{repl}/approve", {}, app=owner)
        self.assertEqual(self.call("POST", f"/glossary_terms/{term}/retire", {"note": "Birleştirildi"}, app=steward)[0], 403)
        ctx = self.ok("POST", f"/glossary_terms/{term}/retire", {"note": "Etkin müşteri ile birleştirildi",
                                                                 "replaced_by_id": repl}, app=owner)
        self.assertEqual((ctx["status"], ctx["replaced_by"]["id"]), ("retired", repl))

    def test_terim_kolon_eslemesi_sahiplik_ve_saglik(self):
        unit = self.ok("POST", "/org_units", {"name": "Satış"})["id"]
        dom = self.ok("POST", "/data_domains", {"name": "Müşteri", "org_unit_id": unit, "owner": "veri.sahibi",
                                                "steward": "veri.yoneticisi"})["id"]
        sid = self.ok("POST", "/data_sources", {"name": "CRM", "platform": "dynamics365", "custodian": "crm.ekibi"})["id"]
        self.ok("POST", f"/data_sources/{sid}/import", upload("hana.csv", HANA))
        tables = self.ok("GET", f"/datagov/tables?source_id={sid}")["items"]
        self.assertEqual(self.ok("GET", f"/datagov/tables?source_id={sid}&filter=unowned")["total"], 3)
        musteri = next(t for t in tables if t["name"] == "MUSTERI")
        steward = self.make(role="UNIT_USER", user="veri.yoneticisi", units=str(unit))
        col = next(c for c in self.ok("GET", f"/data_tables/{musteri['id']}/context")["columns"] if c["name"] == "TCKN")
        self.assertEqual(self.call("PATCH", f"/data_columns/{col['id']}", {"personal_data": "personal"}, app=steward)[0], 403)
        self.ok("PATCH", f"/data_tables/{musteri['id']}", {"domain_id": dom})
        self.ok("PATCH", f"/data_columns/{col['id']}", {"personal_data": "special", "business_name": "Kimlik no"}, app=steward)
        ctx = self.ok("GET", f"/data_tables/{musteri['id']}/context")
        self.assertEqual((ctx["effective"]["owner"], ctx["effective"]["owner_from"], ctx["effective"]["custodian"]),
                         ("veri.sahibi", "domain", "crm.ekibi"))
        self.assertEqual(self.call("PATCH", f"/data_tables/{musteri['id']}", {"status": "removed"})[0], 400)
        term = self.ok("POST", "/glossary_terms", {"name": "T.C. kimlik numarası", "definition": "11 haneli kimlik no",
                                                   "domain_id": dom, "format_rule": "11 hane, rakam"})["id"]
        self.ok("POST", f"/glossary_terms/{term}/links", {"add_columns": [col["id"]], "add_tables": [musteri["id"]]}, app=steward)
        meaning = self.ok("GET", f"/data_columns/{col['id']}/context")
        self.assertEqual((meaning["terms"][0]["id"], meaning["meaning"]["name"]), (term, "Kimlik no"))
        self.assertEqual(meaning["effective"]["owner"], "veri.sahibi")
        self.ok("POST", f"/data_columns/{col['id']}/terms", {"term_ids": []}, app=steward)
        self.assertEqual(self.ok("GET", f"/glossary_terms/{term}/context")["columns"], [])
        health = self.ok("GET", "/health-check")
        low = next(x for x in health["checks"] if x["key"] == "personal_low_class")
        self.assertEqual(low["count"], 1)
        bulk = self.ok("POST", "/datagov/bulk", {"column_ids": [col["id"]], "set": {"classification": "restricted"}})
        self.assertEqual(bulk["updated"], 1)
        self.assertEqual(next(x for x in self.ok("GET", "/health-check")["checks"] if x["key"] == "personal_low_class")["count"], 0)
        bulk = self.ok("POST", "/datagov/bulk", {"table_ids": [t["id"] for t in tables], "set": {"owner": "satis.mudur"}})
        self.assertEqual(bulk["updated"], 3)
        self.assertEqual(self.call("POST", "/datagov/bulk", {"table_ids": [musteri["id"]], "set": {"name": "x"}})[0], 400)
        matrix = self.ok("GET", "/datagov/stewardship")
        self.assertEqual(matrix["unowned_tables"], 0)
        self.assertEqual(next(p for p in matrix["people"] if p["person"] == "satis.mudur")["owner"]["tables"], 3)
        ov = self.ok("GET", "/datagov/overview")
        self.assertEqual((ov["totals"]["tables"], ov["coverage"]["owned"], ov["coverage"]["special"]), (3, 3, 1))
        st, cal = self.call("GET", "/calendar")
        self.assertEqual(st, 200)
        self.assertTrue(any(t["key"] == "glossary_review" for t in cal["types"]))


if __name__ == "__main__":
    unittest.main()
