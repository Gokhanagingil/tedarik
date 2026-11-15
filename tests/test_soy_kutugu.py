"""Veri yönetişimi Faz 4 — soy kütüğü ve etki analizi (K-031): elle ve Excel ile bağlantı, OpenLineage alıcısı (kolon
eşlemesi, eşlenemeyen veri seti ve yeniden işleme), dbt manifesti, etki analizi (kolon düzeyi yayılım, döngü, raporlar,
kontroller, kişiler), etki raporu ve bildirimi, akış şeması ve şema değişikliğinde aşağı akış uyarısı. Veriler sentetiktir."""
import base64
import json

from test_tedarik import Base


def catalog(*tables):
    return {"format": "tedarik.catalog.v1", "tables": [
        {"schema": schema, "name": name, "object_type": kind, "columns": [{"name": c, "data_type": "varchar"} for c in cols]}
        for schema, name, kind, cols in tables]}


def b64(text):
    return base64.b64encode(text.encode()).decode()


SAP = catalog(("SAPHANADB", "KNA1", "table", ["KUNNR", "NAME1", "STCD1"]), ("SAPHANADB", "VBAK", "table", ["VBELN", "KUNNR", "NETWR"]))
DWH = catalog(("dwh", "dim_musteri", "table", ["musteri_no", "ad", "vergi_no"]),
              ("dwh", "fct_satis", "table", ["belge_no", "musteri_no", "tutar"]),
              ("mart", "satis_ozet", "view", ["musteri_no", "toplam_tutar"]))
PBI = catalog(("Satış Modeli", "Satış", "semantic_model", ["Müşteri", "Tutar"]))


class SoyBase(Base):
    def setUp(self):
        super().setUp()
        self.src = {}
        for name, platform, data, extra in (("SAP S/4HANA", "sap_hana", SAP, {}),
                                            ("Veri Ambarı", "postgresql", DWH, {"lineage_namespace": "postgres://dwh:5432"}),
                                            ("Power BI", "power_bi", PBI, {})):
            sid = self.ok("POST", "/data_sources", {"name": name, "platform": platform, **extra})["id"]
            self.ok("POST", f"/data_sources/{sid}/import", {"filename": "k.json", "content_base64": b64(json.dumps(data))})
            self.src[name] = sid
        self.t, self.c = {}, {}
        for sid in self.src.values():
            for t in self.ok("GET", f"/datagov/tables?source_id={sid}")["items"]:
                self.t[t["name"]] = t["id"]
                for col in self.ok("GET", f"/data_tables/{t['id']}/context")["columns"]:
                    self.c[f"{t['name']}.{col['name']}"] = col["id"]

    def edge(self, src, dst, **kw):
        body = {"source_table_id": self.t[src.split(".")[0]], "target_table_id": self.t[dst.split(".")[0]], **kw}
        if "." in src:
            body.update(source_column_id=self.c[src], target_column_id=self.c[dst])
        return self.call("POST", "/lineage_edges", body)

    def email_on(self, *users):
        self.ok("POST", "/integrations/save", {"kind": "email", "enabled": 1, "settings": {
            "host": "smtp.ornek.test", "port": 587, "security": "starttls", "sender": "grc@ornek.test"}})
        with self.db() as db:
            for u in users:
                db.execute("INSERT INTO users (username, email, display_name, is_active, created_at) VALUES (?,?,?,1,?)",
                           (u, f"{u}@ornek.test", u, "2026-01-01T00:00:00+00:00"))

    def notes(self, event):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT username, subject, body FROM tdr_notifications WHERE event=? ORDER BY id",
                                                (event,)).fetchall()]


class ElleVeExcel(SoyBase):
    def test_elle_baglanti_kurallari_ve_kapsam(self):
        status, e = self.edge("KNA1", "dim_musteri", kind="transform", transformation="Müşteri ana verisi gece yüklemesi")
        self.assertEqual(status, 201, e)
        got = self.ok("GET", f"/lineage_edges/{e['id']}")
        self.assertEqual((got["method"], got["created_by"]), ("manual", "dev"))
        self.assertEqual(self.edge("KNA1", "dim_musteri")[0], 409)
        self.assertEqual(self.edge("KNA1.KUNNR", "KNA1.KUNNR")[0], 400)
        self.assertEqual(self.call("POST", "/lineage_edges", {"source_table_id": self.t["KNA1"], "target_table_id": self.t["dim_musteri"],
                                                              "source_column_id": self.c["VBAK.KUNNR"], "target_column_id": self.c["dim_musteri.musteri_no"]})[0], 400)
        self.assertEqual(self.call("POST", "/lineage_edges", {"source_table_id": self.t["KNA1"], "target_table_id": self.t["fct_satis"],
                                                              "source_column_id": self.c["KNA1.KUNNR"]})[0], 400)
        self.assertEqual(self.edge("KNA1.STCD1", "dim_musteri.vergi_no")[0], 201)
        unit = self.ok("POST", "/org_units", {"name": "Satış"})["id"]
        stranger = self.make(role="UNIT_USER", user="birimci", units=str(unit))
        self.assertEqual(self.call("POST", "/lineage_edges", {"source_table_id": self.t["VBAK"], "target_table_id": self.t["fct_satis"]},
                                   app=stranger)[0], 403)
        lin = self.ok("GET", f"/data_tables/{self.t['dim_musteri']}/lineage")
        self.assertEqual([(u["name"], u["columns"], u["table_level"]) for u in lin["upstream"]], [("KNA1", 1, True)])
        col = self.ok("GET", f"/data_columns/{self.c['dim_musteri.vergi_no']}/lineage")
        self.assertEqual({e["source_column"] for e in col["upstream"]}, {"STCD1", None})

    def test_excel_ice_aktarim_on_izleme_hata_ve_disa_aktarim(self):
        csv = ("Kaynak sistem;Kaynak şema;Kaynak tablo;Kaynak kolon;Hedef sistem;Hedef şema;Hedef tablo;Hedef kolon;Tür;Dönüşüm;Veri akış işi;Not\n"
               "SAP S/4HANA;SAPHANADB;VBAK;NETWR;Veri Ambarı;dwh;fct_satis;tutar;Dönüşüm;WAERK ile TRY'ye çevrilir;SAP → DWH gece yüklemesi;\n"
               "Veri Ambarı;dwh;fct_satis;tutar;Veri Ambarı;mart;satis_ozet;toplam_tutar;Toplama / özet;SUM(tutar);;\n"
               "Veri Ambarı;mart;satis_ozet;;Power BI;Satış Modeli;Satış;;Doğrudan aktarım;;;Model yenilemesi\n"
               "Veri Ambarı;dwh;olmayan_tablo;;Power BI;;Satış;;;;;\n")
        dry = self.ok("POST", "/datagov/lineage/import", {"filename": "soy.csv", "content_base64": b64(csv), "dry_run": True})
        self.assertEqual((dry["new"], dry["errors"]), (3, 1))
        self.assertEqual(dry["error_rows"][0]["row"], 5)
        self.assertEqual(self.ok("GET", "/datagov/lineage")["stats"]["edges"], 0)
        done = self.ok("POST", "/datagov/lineage/import", {"filename": "soy.csv", "content_base64": b64(csv)})
        self.assertEqual((done["new"], done["errors"]), (3, 1))
        again = self.ok("POST", "/datagov/lineage/import", {"filename": "soy.csv", "content_base64": b64(csv)})
        self.assertEqual((again["new"], again["seen"]), (0, 3))
        ov = self.ok("GET", "/datagov/lineage")
        self.assertEqual((ov["stats"]["edges"], ov["stats"]["column_edges"], ov["by_method"]), (3, 2, {"excel": 3}))
        self.assertEqual([j["name"] for j in ov["jobs"]], ["SAP → DWH gece yüklemesi"])
        status, raw = self.call("GET", "/datagov/lineage/export?format=csv")
        text = raw.content.decode("utf-8-sig")
        self.assertIn("Toplama / özet", text)
        self.assertIn("Model yenilemesi", text)
        bad = self.call("POST", "/datagov/lineage/import", {"filename": "x.csv", "content_base64": b64("a;b\n1;2\n")})
        self.assertEqual(bad[0], 400)


def ol_event(state="COMPLETE", extra_inputs=()):
    ns = "postgres://dwh:5432"
    return {"eventType": state, "eventTime": "2026-11-15T02:00:00Z", "producer": "https://github.com/apache/airflow/providers-openlineage/1.0",
            "run": {"runId": "0193-sentetik"}, "job": {"namespace": "airflow-prod", "name": "dwh_yukleme.satis_ozet",
                                                       "facets": {"sql": {"query": "SELECT gizli_sorgu FROM x"}}},
            "inputs": [{"namespace": ns, "name": "dwh.dwh.fct_satis"}, *extra_inputs],
            "outputs": [{"namespace": ns, "name": "dwh.mart.satis_ozet", "facets": {
                "schema": {"fields": [{"name": "musteri_no"}, {"name": "toplam_tutar"}]},
                "columnLineage": {"fields": {
                    "toplam_tutar": {"inputFields": [{"namespace": ns, "name": "dwh.dwh.fct_satis", "field": "tutar",
                                                      "transformations": [{"type": "DIRECT", "subtype": "AGGREGATION"}]}]},
                    "musteri_no": {"inputFields": [{"namespace": ns, "name": "dwh.dwh.fct_satis", "field": "musteri_no",
                                                    "transformations": [{"type": "DIRECT", "subtype": "IDENTITY"}]},
                                                   {"namespace": ns, "name": "dwh.dwh.fct_satis", "field": "yok_kolon"}]}}}}}]}


class OpenLineage(SoyBase):
    def test_olay_kolon_eslemesi_eslenemeyen_ve_yeniden_isleme(self):
        out = self.ok("POST", f"/data_sources/{self.src['Veri Ambarı']}/collectors", {"connector": "openlineage"})
        col, key = out["collector"], out["key"]
        self.assertEqual(col["schedule"], "manual")
        ctx = self.ok("GET", f"/data_collectors/{col['id']}/context")
        self.assertIn("api/tdr/collector/openlineage", ctx["setup"]["config"])
        bearer = {"Authorization": f"Bearer {key}"}
        self.assertEqual(self.call("GET", "/collector/whoami", headers=bearer)[0], 200)
        crm_ds = {"namespace": "mssql://crm-db:1433", "name": "crm.dbo.musteri"}
        status, r = self.call("POST", "/collector/openlineage", ol_event(extra_inputs=[crm_ds]), headers=bearer)
        self.assertEqual(status, 200, r)
        self.assertEqual((r["accepted"], r["edges_new"]), (1, 2))           # 2 kolon; eşlemesi olan girdiye tablo bağlantısı yok
        self.assertEqual(r["unresolved"], [crm_ds])
        r2 = self.ok("POST", "/collector/openlineage", {"events": [ol_event(), ol_event("FAIL")]}, headers=bearer)
        self.assertEqual((r2["accepted"], r2["edges_new"], r2["edges_seen"]), (2, 0, 2))
        ov = self.ok("GET", "/datagov/lineage")
        job = ov["jobs"][0]
        self.assertEqual((job["system"], job["namespace"], job["last_run_state"]), ("airflow", "airflow-prod", "FAIL"))
        kinds = {(e["source_column"], e["kind"]) for e in self.ok("GET", f"/data_tables/{self.t['satis_ozet']}/lineage")["edges"]}
        self.assertEqual(kinds, {("tutar", "aggregate"), ("musteri_no", "direct")})
        with self.db() as db:
            stored = " ".join(r[0] for r in db.execute("SELECT datasets_json FROM tdr_lineage_events").fetchall())
        self.assertNotIn("gizli_sorgu", stored)                               # olayın yalnızca veri seti adları saklanır
        self.assertNotIn("schema", stored)
        self.assertEqual(self.ok("GET", "/datagov/lineage/unresolved")["items"][0]["name"], "crm.dbo.musteri")
        crm = self.ok("POST", "/data_sources", {"name": "CRM", "platform": "sql_server", "lineage_namespace": "mssql://crm-db:1433"})["id"]
        self.ok("POST", f"/data_sources/{crm}/import", {"filename": "k.json", "content_base64": b64(json.dumps(
            catalog(("dbo", "musteri", "table", ["id"]))))})
        again = self.ok("POST", "/datagov/lineage/reprocess", {})
        self.assertEqual(again["edges_new"], 1)                              # CRM girdisinin kolon eşlemesi yok: tablo düzeyi
        upstream = self.ok("GET", f"/data_tables/{self.t['satis_ozet']}/lineage")["upstream"]
        self.assertEqual({(u["name"], u["table_level"]) for u in upstream}, {("fct_satis", False), ("musteri", True)})
        self.assertEqual(self.ok("GET", "/datagov/lineage/unresolved")["items"], [])
        other = self.ok("POST", f"/data_sources/{self.src['Veri Ambarı']}/collectors", {"connector": "postgresql"})["key"]
        self.assertEqual(self.call("POST", "/collector/openlineage", ol_event(), headers={"X-Collector-Key": other})[0], 403)
        self.assertEqual(self.call("POST", "/collector/openlineage", ol_event())[0], 403)        # oturum toplayıcı değildir
        self.assertEqual(self.call("POST", "/collector/openlineage", {"job": {}}, headers=bearer)[0], 400)


def manifest(with_dim=True):
    nodes = {
        "model.analitik.satis_ozet": {"resource_type": "model", "name": "satis_ozet", "schema": "mart", "alias": "satis_ozet",
                                      "config": {"materialized": "view"}, "description": "Müşteri bazında satış özeti",
                                      "columns": {"toplam_tutar": {"name": "toplam_tutar", "description": "Net satış tutarı (TRY)"}},
                                      "depends_on": {"nodes": ["source.analitik.dwh.fct_satis"] + (["model.analitik.dim_musteri"] if with_dim else [])}},
        "model.analitik.dim_musteri": {"resource_type": "model", "name": "dim_musteri", "schema": "dwh", "alias": "dim_musteri",
                                       "config": {"materialized": "table"}, "depends_on": {"nodes": ["source.analitik.sap.stg"]}}}
    sources = {"source.analitik.dwh.fct_satis": {"resource_type": "source", "name": "fct_satis", "schema": "dwh", "identifier": "fct_satis"},
               "source.analitik.sap.stg": {"resource_type": "source", "name": "stg_musteri", "schema": "staging", "identifier": "stg_musteri"}}
    return {"metadata": {"dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json", "project_name": "analitik"},
            "nodes": nodes, "sources": sources}


class Dbt(SoyBase):
    def test_manifest_on_izleme_aciklama_ve_kaldirilan_bagimlilik(self):
        body = {"filename": "manifest.json", "source_id": self.src["Veri Ambarı"], "adopt_descriptions": True}
        dry = self.ok("POST", "/datagov/lineage/dbt", {**body, "content_base64": b64(json.dumps(manifest())), "dry_run": True})
        self.assertEqual((dry["edges_new"], dry["unresolved"]), (2, ["staging.stg_musteri"]))
        self.assertEqual(self.ok("GET", "/datagov/lineage")["stats"]["edges"], 0)
        done = self.ok("POST", "/datagov/lineage/dbt", {**body, "content_base64": b64(json.dumps(manifest()))})
        self.assertEqual((done["edges_new"], done["descriptions"], done["project"]), (2, 2, "analitik"))
        t = self.ok("GET", f"/data_tables/{self.t['satis_ozet']}/context")
        self.assertEqual(t["technical_description"], "Müşteri bazında satış özeti")
        self.assertEqual(next(c for c in t["columns"] if c["name"] == "toplam_tutar")["technical_description"], "Net satış tutarı (TRY)")
        later = self.ok("POST", "/datagov/lineage/dbt", {**body, "content_base64": b64(json.dumps(manifest(with_dim=False)))})
        self.assertEqual((later["edges_seen"], later["edges_removed"]), (1, 1))
        self.assertEqual(self.ok("GET", "/datagov/lineage")["stats"]["edges"], 1)
        self.assertEqual(self.call("POST", "/datagov/lineage/dbt", {**body, "content_base64": b64("{}")})[0], 400)
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("POST", "/datagov/lineage/dbt", {**body, "content_base64": b64("{}")}, app=viewer)[0], 403)


class Etki(SoyBase):
    def chain(self):
        for src, dst in (("KNA1.KUNNR", "dim_musteri.musteri_no"), ("KNA1.STCD1", "dim_musteri.vergi_no"),
                         ("dim_musteri.musteri_no", "satis_ozet.musteri_no")):
            self.assertEqual(self.edge(src, dst)[0], 201)
        self.assertEqual(self.edge("satis_ozet", "Satış")[0], 201)

    def test_kolon_duzeyi_yayilim_raporlar_kontroller_kisiler_ve_dongu(self):
        self.chain()
        stcd = self.ok("GET", f"/data_tables/{self.t['KNA1']}/impact?column_id={self.c['KNA1.STCD1']}")
        self.assertEqual([(a["name"], a["columns"]) for a in stcd["affected"]], [("dim_musteri", ["vergi_no"])])
        kunnr = self.ok("GET", f"/data_tables/{self.t['KNA1']}/impact?column_id={self.c['KNA1.KUNNR']}")
        self.assertEqual([(a["name"], a["depth"], a["columns"]) for a in kunnr["affected"]],
                         [("dim_musteri", 1, ["musteri_no"]), ("satis_ozet", 2, ["musteri_no"]), ("Satış", 3, None)])
        self.assertEqual(kunnr["affected"][2]["via"], ["dim_musteri", "satis_ozet"])
        self.assertEqual([r["name"] for r in kunnr["reports"]], ["Satış"])
        self.assertEqual(kunnr["summary"]["systems"], 3)
        whole = self.ok("GET", f"/data_tables/{self.t['KNA1']}/impact")
        self.assertEqual(len(whole["affected"]), 3)
        self.assertEqual(self.call("GET", f"/data_tables/{self.t['KNA1']}/impact?column_id={self.c['VBAK.KUNNR']}")[0], 400)

        self.ok("PATCH", f"/data_tables/{self.t['dim_musteri']}", {"owner": "dwh.sahibi"})
        self.ok("PATCH", f"/data_tables/{self.t['Satış']}", {"owner": "rapor.sahibi", "steward": "rapor.yoneticisi"})
        control = self.ok("POST", "/controls", {"name": "Satış özeti mutabakatı", "owner": "kontrol.sahibi"})["id"]
        code = self.ok("GET", f"/controls/{control}")["code"]
        self.ok("POST", f"/data_tables/{self.t['satis_ozet']}/controls", {"control_ids": [control]})
        term = self.ok("POST", "/glossary_terms", {"name": "Vergi numarası", "definition": "Müşterinin vergi kimlik numarası."})["id"]
        self.ok("POST", f"/data_columns/{self.c['dim_musteri.vergi_no']}/terms", {"term_ids": [term]})
        r = self.ok("GET", f"/data_tables/{self.t['KNA1']}/impact")
        self.assertEqual([k["code"] for k in r["controls"]], [code])
        self.assertEqual([g["name"] for g in r["terms"]], ["Vergi numarası"])
        people = {p["person"]: p["roles"] for p in r["people"]}
        self.assertEqual(people["rapor.sahibi"], ["Veri sahibi"])
        self.assertIn("Kontrol sahibi", people["kontrol.sahibi"])

        self.assertEqual(self.edge("satis_ozet", "dim_musteri")[0], 201)                # döngü
        loop = self.ok("GET", f"/data_tables/{self.t['KNA1']}/impact")
        self.assertEqual(sorted(a["name"] for a in loop["affected"]), ["Satış", "dim_musteri", "satis_ozet"])
        g = self.ok("GET", f"/datagov/lineage/graph?table_id={self.t['dim_musteri']}&depth=2")
        levels = {n["name"]: n["level"] for n in g["nodes"]}
        self.assertEqual((levels["KNA1"], levels["dim_musteri"], levels["satis_ozet"], levels["Satış"]), (-1, 0, 1, 2))
        link = next(x for x in g["links"] if x["from"] == self.t["KNA1"])
        self.assertEqual(sorted(c["from"] for c in link["columns"]), ["KUNNR", "STCD1"])

    def test_etki_raporu_ve_planlanan_degisiklik_bildirimi(self):
        self.chain()
        self.ok("PATCH", f"/data_tables/{self.t['Satış']}", {"owner": "rapor.sahibi"})
        self.ok("PATCH", f"/data_tables/{self.t['dim_musteri']}", {"owner": "dwh.sahibi"})
        self.email_on("rapor.sahibi", "dwh.sahibi")
        status, raw = self.call("GET", f"/data_tables/{self.t['KNA1']}/impact/export?column_id={self.c['KNA1.KUNNR']}")
        text = raw.content.decode("utf-8-sig")
        self.assertIn("KNA1 → dim_musteri → satis_ozet → Satış", text)
        self.assertIn("rapor.sahibi", text)
        self.assertEqual(self.call("POST", f"/data_tables/{self.t['KNA1']}/impact/notify", {"note": "kısa"})[0], 400)
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("POST", f"/data_tables/{self.t['KNA1']}/impact/notify",
                                   {"note": "KUNNR alanı 10'dan 12 haneye çıkıyor"}, app=viewer)[0], 403)
        r = self.ok("POST", f"/data_tables/{self.t['KNA1']}/impact/notify",
                    {"note": "KUNNR alanı 10'dan 12 haneye çıkıyor", "column_id": self.c["KNA1.KUNNR"], "planned_on": "2026-12-01"})
        self.assertEqual(r["queued"], 2)
        notes = {n["username"]: n for n in self.notes("catalog.impact")}
        self.assertIn("SAPHANADB.KNA1.KUNNR", notes["rapor.sahibi"]["subject"])
        self.assertIn("2026-12-01", notes["rapor.sahibi"]["body"])

    def test_sema_degisikliginde_asagi_akis_onemli_ve_kopuk_baglanti(self):
        self.chain()
        self.ok("PATCH", f"/data_tables/{self.t['KNA1']}", {"owner": "sap.sahibi"})
        self.email_on("sap.sahibi")
        changed = catalog(("SAPHANADB", "KNA1", "table", ["KUNNR", "NAME1"]), ("SAPHANADB", "VBAK", "table", ["VBELN", "KUNNR", "NETWR"]))
        self.ok("POST", f"/data_sources/{self.src['SAP S/4HANA']}/import",
                {"filename": "k2.json", "content_base64": b64(json.dumps(changed))})
        body = self.notes("catalog.changed")[0]["body"]
        self.assertIn("ÖNEMLİ: aşağı akışta 1 tablo/rapor", body)
        health = {c["key"]: c for c in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(health["lineage_broken"]["count"], 1)
        self.assertEqual(len(self.ok("GET", "/datagov/lineage")["broken"]), 1)


class KisiselVeriYayilimi(SoyBase):
    def test_kategori_soy_kutugu_boyunca_oneri_olur(self):
        self.assertEqual(self.edge("KNA1.STCD1", "dim_musteri.vergi_no", kind="direct")[0], 201)
        self.assertEqual(self.edge("KNA1.NAME1", "dim_musteri.ad", kind="indirect")[0], 201)
        kimlik = next(k["id"] for k in self.ok("GET", "/personal_data_categories?limit=100") if k["name"] == "Kimlik")
        for col in ("KNA1.STCD1", "KNA1.NAME1"):
            self.ok("POST", f"/data_columns/{self.c[col]}/categories", {"category_ids": [kimlik]})
        self.ok("POST", "/datagov/discovery/run", {"source_id": self.src["Veri Ambarı"]})
        items = self.ok("GET", f"/datagov/discovery?source_id={self.src['Veri Ambarı']}")["items"]
        lineage = [(i["column_name"], i["category_name"]) for i in items if i["method"] == "lineage"]
        self.assertEqual(lineage, [("vergi_no", "Kimlik")])                  # dolaylı bağlantı kişisel veri taşımaz
        self.assertIn("KNA1.STCD1", next(i["evidence"] for i in items if i["method"] == "lineage"))
