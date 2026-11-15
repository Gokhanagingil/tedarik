"""Veri yönetişimi Faz 3 — otomatik toplama (K-030): toplayıcı anahtarı ve yetki sınırı, uçtan uca toplama (SQLite,
genel SQL sürücüsü, CSV klasörü, eklenti bağlayıcı, hazır dışa aktarım), yerel örnek doğrulama, kaldırma eşiği, şema
değişikliği bildirimi, gecikme hatırlatması, sağlık kontrolü ve indirilebilir .pyz. Test verisi sentetiktir."""
import json
import os
import random
import sqlite3
import subprocess
import sys
import unittest
from datetime import datetime, timedelta, timezone

from test_tedarik import KEY, PG_URL, Base
from tedarik import collector, notify


def tckn(rnd):
    d = [rnd.randint(1, 9)] + [rnd.randint(0, 9) for _ in range(8)]
    d.append((sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10)
    d.append(sum(d) % 10)
    return "".join(map(str, d))


class AppClient:
    """Toplayıcının platform istemcisi; ağ yerine uygulamaya doğrudan bağlanır (aynı başlık ve gövde)."""

    def __init__(self, app, key):
        self.app, self.key = app, key

    def _send(self, method, path, body=None):
        raw = json.dumps(body).encode() if body is not None else b""
        status, payload = self.app.dispatch(method, "/api/tdr/collector/" + path, {"X-Collector-Key": self.key}, raw)
        if status >= 300:
            raise collector.CollectorError(f"Platform yanıtı {status}: {payload.get('error')}")
        return payload

    def get(self, path):
        return self._send("GET", path)

    def post(self, path, body):
        return self._send("POST", path, body)


class ToplayiciBase(Base):
    def setUp(self):
        super().setUp()
        self.sid = self.ok("POST", "/data_sources", {"name": "Müşteri Uygulaması", "platform": "postgresql",
                                                     "steward": "veri.yoneticisi", "custodian": "uygulama.ekibi"})["id"]

    def collector(self, **body):
        out = self.ok("POST", f"/data_sources/{self.sid}/collectors", {"connector": "sqlite", **body})
        return out["collector"], out["key"]

    def as_collector(self, key, method, path, body=None):
        return self.call(method, path, body, headers={"X-Collector-Key": key})

    def config(self, connector, settings, **extra):
        path = os.path.join(self.tmp.name, f"ayar-{connector}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"platform": "https://platform.ornek.test", "connector": connector, "settings": settings, **extra}, fh)
        return path

    def run_collector(self, key, *args):
        lines = []
        code = collector.main(list(args), client=AppClient(self.app, key), out=lines.append)
        return code, lines

    def tables(self, removed=False):
        flt = "&filter=removed" if removed else ""
        return {t["name"]: t for t in self.ok("GET", f"/datagov/tables?source_id={self.sid}{flt}")["items"]}

    def email_on(self, *users):
        self.ok("POST", "/integrations/save", {"kind": "email", "enabled": 1, "settings": {
            "host": "smtp.ornek.test", "port": 587, "security": "starttls", "sender": "grc@ornek.test"}})
        with self.db() as db:
            for u in users:
                db.execute("INSERT INTO users (username, email, display_name, is_active, created_at) VALUES (?,?,?,1,?)",
                           (u, f"{u}@ornek.test", u, "2026-01-01T00:00:00+00:00"))

    def notes(self, event):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT username, subject, body FROM tdr_notifications WHERE event=? "
                                                "ORDER BY id", (event,)).fetchall()]

    def sqlite_source(self):
        path = os.path.join(self.tmp.name, "kaynak.db")
        rnd = random.Random(7)
        db = sqlite3.connect(path)
        db.executescript("""CREATE TABLE musteri (id INTEGER PRIMARY KEY, ad_soyad TEXT NOT NULL, kimlik_no TEXT,
                eposta TEXT, sehir TEXT);
            CREATE TABLE siparis (id INTEGER PRIMARY KEY, musteri_id INTEGER REFERENCES musteri(id), tutar REAL);
            CREATE VIEW v_ozet AS SELECT sehir, COUNT(*) AS adet FROM musteri GROUP BY sehir;""")
        db.executemany("INSERT INTO musteri (ad_soyad, kimlik_no, eposta, sehir) VALUES (?,?,?,?)",
                       [(f"Kişi {i}", tckn(rnd), f"kisi{i}@ornek.test", "Ankara") for i in range(30)])
        db.executemany("INSERT INTO siparis (musteri_id, tutar) VALUES (?,?)", [(i % 30 + 1, 10.5 * i) for i in range(12)])
        db.commit()
        db.close()
        return path


class AnahtarVeYetki(ToplayiciBase):
    def test_anahtar_bir_kez_gorunur_ve_yalniz_toplayici_ucu(self):
        col, key = self.collector(name="Gece toplayıcısı")
        self.assertTrue(key.startswith("tdrc_") and len(key) > 40)
        self.assertTrue(col["code"].startswith("TPL-") and col["key_hint"].endswith(key[-4:]))
        got = self.ok("GET", f"/data_collectors/{col['id']}")
        listing = self.ok("GET", "/data_collectors")
        ctx = self.ok("GET", f"/data_collectors/{col['id']}/context")
        for payload in (got, listing, ctx):
            self.assertNotIn(key, json.dumps(payload))
            self.assertNotIn("key_hash", json.dumps(payload))
        self.assertIn("gonder --ayar", ctx["setup"]["run"])
        self.assertIn('"connector": "sqlite"', ctx["setup"]["config"])
        self.assertTrue(ctx["setup"]["cron"].startswith("30 2 * * *"))
        with self.db() as db:
            stored = db.execute("SELECT key_hash FROM tdr_collector_keys WHERE collector_id=?", (col["id"],)).fetchone()[0]
            logged = " ".join(r[0] or "" for r in db.execute("SELECT changes_json FROM tdr_audit_log").fetchall())
        self.assertNotEqual(stored, key)
        self.assertNotIn(key, logged)

        status, who = self.as_collector(key, "GET", "/collector/whoami")
        self.assertEqual(status, 200, who)
        self.assertEqual((who["source"]["name"], who["collector"]["scope"]), ("Müşteri Uygulaması", "schemas"))
        self.assertTrue(any(q["key"] == "pg_columns" for q in who["queries"]))
        self.assertEqual(self.as_collector(key, "GET", "/suppliers")[0], 403)
        self.assertEqual(self.as_collector(key, "GET", f"/data_collectors/{col['id']}/context")[0], 403)
        self.assertEqual(self.as_collector(key, "GET", "/metadata")[0], 403)
        self.assertEqual(self.as_collector("tdrc_yanlis-anahtar", "GET", "/collector/whoami")[0], 401)
        self.assertEqual(self.call("GET", "/collector/whoami")[0], 403)                       # oturum toplayıcı değildir
        self.assertEqual(self.call("POST", "/collector/catalog", {}, headers={"X-API-Key": KEY})[0], 403)  # MCP de değil
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("POST", f"/data_sources/{self.sid}/collectors", {}, app=viewer)[0], 403)
        self.assertEqual(self.call("GET", "/datagov/collector.pyz", app=viewer)[0], 200)      # okuyabilen indirir

        rotated = self.ok("POST", f"/data_collectors/{col['id']}/rotate-key", {})["key"]
        self.assertEqual(self.as_collector(key, "GET", "/collector/whoami")[0], 401)
        self.assertEqual(self.as_collector(rotated, "GET", "/collector/whoami")[0], 200)
        self.ok("PATCH", f"/data_collectors/{col['id']}", {"schedule": "weekly", "sample_rows": 100})
        self.assertEqual(self.call("PATCH", f"/data_collectors/{col['id']}", {"max_removal_pct": 140})[0], 400)
        self.ok("POST", f"/data_collectors/{col['id']}/revoke", {"reason": "Sunucu değişti"})
        self.assertEqual(self.as_collector(rotated, "GET", "/collector/whoami")[0], 401)
        self.assertEqual(self.call("PATCH", f"/data_collectors/{col['id']}", {"name": "Yeni"})[0], 409)
        self.assertEqual(self.call("POST", f"/data_collectors/{col['id']}/rotate-key", {})[0], 409)


class UctanUca(ToplayiciBase):
    def test_sqlite_toplama_ornek_dogrulama_ve_gecmis(self):
        path = self.sqlite_source()
        col, key = self.collector(sample_rows=50)
        cfg = self.config("sqlite", {"path": path, "schema": "uygulama"})
        code, lines = self.run_collector(key, "gonder", "--ayar", cfg)
        self.assertEqual(code, 0, lines)
        self.assertIn("3 tablo", lines[0])
        tables = self.tables()
        self.assertEqual(set(tables), {"musteri", "siparis", "v_ozet"})
        self.assertEqual((tables["v_ozet"]["object_type"], tables["musteri"]["row_count"]), ("view", 30))
        cols = {c["name"]: c for c in self.ok("GET", f"/data_tables/{tables['siparis']['id']}/context")["columns"]}
        self.assertEqual(cols["musteri_id"]["references_to"], "uygulama.musteri.id")
        self.assertEqual(cols["id"]["is_primary_key"], 1)
        items = self.ok("GET", f"/datagov/discovery?source_id={self.sid}")["items"]
        sampled = {i["column_name"]: i for i in items if i["method"] == "sample"}
        self.assertIn("kimlik_no", sampled)
        self.assertIn("eposta", sampled)
        self.assertNotIn("sehir", sampled)
        ctx = self.ok("GET", f"/data_collectors/{col['id']}/context")
        self.assertEqual((ctx["state"]["state"], ctx["events"][0]["kind"], ctx["client_version"]), ("ok", "push", collector.VERSION))
        imports = self.ok("GET", f"/data_sources/{self.sid}/context")["imports"]
        self.assertEqual(imports[0]["collector_id"], col["id"])
        self.assertTrue(imports[0]["created_by"].startswith("toplayici:TPL-"))
        with self.db() as db:
            audit = db.execute("SELECT actor, auth_type FROM tdr_audit_log WHERE method='COLLECT'").fetchone()
        self.assertEqual(audit["auth_type"], "collector")

        code, lines = self.run_collector(key, "gonder", "--ayar", cfg, "--on-izleme")
        self.assertEqual(code, 0)
        self.assertIn("Ön izleme", lines[0])
        self.assertEqual(len(self.ok("GET", f"/data_sources/{self.sid}/context")["imports"]), 1)

        out = os.path.join(self.tmp.name, "katalog.json")
        code, lines = self.run_collector(key, "topla", "--ayar", cfg, "--cikti", out)
        self.assertEqual(code, 0)
        with open(out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(json.loads(text)["format"], "tedarik.catalog.v1")
        self.assertNotIn("@ornek.test", text)                       # yalnızca meta veri: değer yok

    def test_genel_sql_surucusu_ve_hazir_sorgu(self):
        path = self.sqlite_source()
        col, key = self.collector(connector="sql")
        query = ("SELECT 'uyg' AS schema_name, m.name AS table_name, p.name AS column_name, p.cid + 1 AS position, "
                 "p.type AS data_type, CASE WHEN p.pk > 0 THEN 'YES' ELSE 'NO' END AS primary_key FROM sqlite_master m, "
                 "pragma_table_info(m.name) p WHERE m.type = 'table' ORDER BY 1, 2, 4")
        os.environ["TDR_TEST_CONNECT"] = json.dumps({"database": path})
        self.addCleanup(os.environ.pop, "TDR_TEST_CONNECT", None)
        cfg = self.config("sql", {"driver": "sqlite3", "connect_env": "TDR_TEST_CONNECT", "query": query})
        code, lines = self.run_collector(key, "gonder", "--ayar", cfg)
        self.assertEqual(code, 0, lines)
        tables = self.tables()
        self.assertEqual(set(tables), {"musteri", "siparis"})
        self.assertEqual(tables["musteri"]["schema_name"], "uyg")
        # hazır sorgu (preset) platformdan gelir; doldurulmamış yer tutucu çalıştırılmaz ve hata platforma bildirilir
        cfg = self.config("sql", {"driver": "sqlite3", "connect_env": "TDR_TEST_CONNECT", "preset": "pg_columns_yok"})
        code, _ = self.run_collector(key, "gonder", "--ayar", cfg)
        self.assertEqual(code, 1)
        ctx = self.ok("GET", f"/data_collectors/{col['id']}/context")
        self.assertEqual((ctx["state"]["state"], ctx["events"][0]["kind"]), ("error", "error"))
        self.assertIn("Hazır sorgu bulunamadı", ctx["last_message"])
        hana = self.ok("POST", "/data_sources", {"name": "S/4HANA", "platform": "sap_hana"})["id"]
        hkey = self.ok("POST", f"/data_sources/{hana}/collectors", {"connector": "sql"})["key"]
        cfg = self.config("sql", {"driver": "sqlite3", "connect_env": "TDR_TEST_CONNECT", "preset": "hana_catalog"})
        code, _ = self.run_collector(hkey, "gonder", "--ayar", cfg)
        self.assertEqual(code, 1)                                    # <ŞEMA_1> doldurulmadı

    def test_csv_klasoru_tip_cikarimi_ve_hazir_dosya(self):
        folder = os.path.join(self.tmp.name, "paylasim")
        os.mkdir(folder)
        with open(os.path.join(folder, "personel.csv"), "w", encoding="utf-8") as fh:
            fh.write("sicil;ad;telefon;maas;ise_giris;aktif\n")
            for i in range(20):
                fh.write(f"{1000 + i};Kişi {i};05{i % 10}21234567;{1500 + i}.50;2024-01-{i + 1:02d};evet\n")
        col, key = self.collector(connector="files")
        cfg = self.config("files", {"path": folder})
        code, lines = self.run_collector(key, "gonder", "--ayar", cfg)
        self.assertEqual(code, 0, lines)
        t = self.tables()["personel"]
        self.assertEqual((t["schema_name"], t["object_type"], t["row_count"]), ("paylasim", "file", 20))
        cols = {c["name"]: c for c in self.ok("GET", f"/data_tables/{t['id']}/context")["columns"]}
        self.assertEqual({k: cols[k]["data_type"] for k in cols},
                         {"sicil": "integer", "ad": "text", "telefon": "text", "maas": "decimal", "ise_giris": "date",
                          "aktif": "boolean"})
        export = os.path.join(self.tmp.name, "hana.csv")
        with open(export, "w", encoding="utf-8") as fh:
            fh.write("SCHEMA_NAME;TABLE_NAME;COLUMN_NAME;POSITION;DATA_TYPE\nSATIS;FATURA;FATURA_NO;1;NVARCHAR\n")
        code, lines = self.run_collector(key, "dosya-gonder", "--ayar", cfg, export)
        self.assertEqual(code, 0, lines)
        self.assertIn("FATURA", self.tables())


PLUGIN = '''
import json
from tdr_collector import Connector, connector, table, column


@connector
class Envanter(Connector):
    name = "envanter_test"
    description = "Sentetik envanter"

    def collect(self):
        with open(self.setting("path", required=True), encoding="utf-8") as fh:
            for t in json.load(fh):
                yield table("app", t["name"], columns=[column(c, data_type=d) for c, d in t["columns"]])
'''


class EklentiBildirimEsik(ToplayiciBase):
    def write(self, data):
        with open(self.data, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_eklenti_degisiklik_bildirimi_ve_kaldirma_esigi(self):
        plugin = os.path.join(self.tmp.name, "envanter.py")
        with open(plugin, "w", encoding="utf-8") as fh:
            fh.write(PLUGIN)
        self.data = os.path.join(self.tmp.name, "envanter.json")
        base = [{"name": f"tablo_{i:02d}", "columns": [["id", "int"]]} for i in range(11)]
        musteri = {"name": "musteri", "columns": [["id", "int"], ["eposta", "varchar"], ["dogum_tarihi", "date"]]}
        self.write(base + [musteri])
        col, key = self.collector(connector="custom", scope="full")
        cfg = self.config("envanter_test", {"path": self.data})
        code, lines = self.run_collector(key, "gonder", "--ayar", cfg, "--eklenti", plugin)
        self.assertEqual(code, 0, lines)
        tables = self.tables()
        self.assertEqual(len(tables), 12)
        self.ok("PATCH", f"/data_tables/{tables['musteri']['id']}", {"owner": "veri.sahibi"})
        cols = {c["name"]: c["id"] for c in self.ok("GET", f"/data_tables/{tables['musteri']['id']}/context")["columns"]}
        self.ok("PATCH", f"/data_columns/{cols['eposta']}", {"personal_data": "personal"})
        self.email_on("veri.sahibi", "veri.yoneticisi", "uygulama.ekibi")

        musteri["columns"] = [["id", "int"], ["dogum_tarihi", "timestamp"]]
        self.write(base + [musteri])
        code, lines = self.run_collector(key, "gonder", "--ayar", cfg, "--eklenti", plugin)
        self.assertEqual(code, 0, lines)
        self.assertIn("1 kolon kaldırıldı", lines[0])
        self.assertIn("1 tip değişti", lines[0])
        notes = {n["username"]: n for n in self.notes("catalog.changed")}
        self.assertEqual(set(notes), {"veri.sahibi", "veri.yoneticisi", "uygulama.ekibi"})
        self.assertIn("1 önemli", notes["veri.sahibi"]["subject"])
        self.assertIn("ÖNEMLİ: kişisel veri", notes["veri.sahibi"]["body"])
        self.assertIn("DATE → TIMESTAMP", notes["veri.sahibi"]["body"])

        self.write([musteri])                                            # 12 tablodan 11'i kaybolmuş görünüyor
        code, _ = self.run_collector(key, "gonder", "--ayar", cfg, "--eklenti", plugin)
        self.assertEqual(code, 1)
        self.assertEqual(len(self.tables(removed=True)), 0)
        ctx = self.ok("GET", f"/data_collectors/{col['id']}/context")
        self.assertEqual((ctx["events"][0]["kind"], ctx["state"]["state"]), ("rejected", "error"))
        self.assertTrue(self.notes("collector.failed"))
        self.ok("PATCH", f"/data_collectors/{col['id']}", {"max_removal_pct": 100})     # değişiklik gerçekse eşik açılır
        code, _ = self.run_collector(key, "gonder", "--ayar", cfg, "--eklenti", plugin)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.tables(removed=True)), 11)
        self.assertEqual(self.ok("GET", f"/data_collectors/{col['id']}/context")["state"]["state"], "ok")

        self.ok("PATCH", f"/data_sources/{self.sid}", {"change_notice": "none"})
        before = len(self.notes("catalog.changed"))
        self.write(base + [musteri])
        self.assertEqual(self.run_collector(key, "gonder", "--ayar", cfg, "--eklenti", plugin)[0], 0)
        self.assertEqual(len(self.notes("catalog.changed")), before)


class GecikmeVeSaglik(ToplayiciBase):
    def test_gecikme_hatirlatmasi_hata_bildirimi_ve_saglik(self):
        col, key = self.collector(schedule="daily")
        self.email_on("uygulama.ekibi")
        self.assertEqual(self.ok("GET", f"/data_collectors/{col['id']}/context")["state"]["state"], "waiting")
        old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
        with self.db() as db:
            db.execute("UPDATE tdr_data_collectors SET created_at=?, key_created_at=? WHERE id=?", (old, old, col["id"]))
            first = notify.reminders(db, self.app)
            second = notify.reminders(db, self.app)
        self.assertGreaterEqual(first, 1)
        self.assertEqual(second, 0)
        self.assertIn("gecikti", self.notes("collector.overdue")[0]["subject"])
        self.assertEqual(self.ok("GET", f"/data_collectors/{col['id']}/context")["state"]["state"], "overdue")
        health = {c["key"]: c for c in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(health["collectors_attention"]["count"], 1)
        work = self.ok("GET", "/my-work", app=self.make(user="uygulama.ekibi"))
        self.assertEqual(len(work["collectors_attention"]), 1)
        summary = self.ok("GET", "/datagov/collectors")["summary"]
        self.assertEqual((summary["active"], summary["overdue"]), (1, 1))

        status, _ = self.as_collector(key, "POST", "/collector/status", {"result": "error", "message": "Kaynağa bağlanılamadı"})
        self.assertEqual(status, 200)
        ctx = self.ok("GET", f"/data_collectors/{col['id']}/context")
        self.assertEqual((ctx["state"]["state"], ctx["last_message"]), ("error", "Kaynağa bağlanılamadı"))
        path = self.sqlite_source()
        code, _ = self.run_collector(key, "gonder", "--ayar", self.config("sqlite", {"path": path}))
        self.assertEqual(code, 0)
        ctx = self.ok("GET", f"/data_collectors/{col['id']}/context")
        self.assertEqual((ctx["state"]["state"], ctx["overdue_notified_at"]), ("ok", None))


class Paket(ToplayiciBase):
    def test_pyz_indirilir_ve_calisir(self):
        status, raw = self.call("GET", "/datagov/collector.pyz")
        self.assertEqual(status, 200)
        path = os.path.join(self.tmp.name, "tedarik-toplayici.pyz")
        with open(path, "wb") as fh:
            fh.write(raw.content)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        run = subprocess.run([sys.executable, "-I", path, "baglayicilar"], capture_output=True, text=True, timeout=60,
                             cwd=self.tmp.name, env=env)
        self.assertEqual(run.returncode, 0, run.stderr)
        for name in ("postgresql", "sqlite", "sql", "files"):
            self.assertIn(name, run.stdout)
        run = subprocess.run([sys.executable, "-I", path, "ornek-ayar", "sql"], capture_output=True, text=True, timeout=60,
                             cwd=self.tmp.name, env=env)
        self.assertEqual(json.loads(run.stdout)["settings"]["preset"], "hana_catalog")
        run = subprocess.run([sys.executable, "-I", path, "gonder", "--ayar", os.path.join(self.tmp.name, "yok.json")],
                             capture_output=True, text=True, timeout=60, cwd=self.tmp.name, env=env)
        self.assertEqual(run.returncode, 1)
        self.assertIn("Ayar dosyası bulunamadı", run.stderr)

    def test_sifresiz_adrese_anahtar_gonderilmez(self):
        with self.assertRaises(collector.CollectorError):
            collector.Client("http://platform.ornek.test", "tdrc_x")
        collector.Client("http://127.0.0.1:8090", "tdrc_x")                 # yerel deneme


@unittest.skipUnless(PG_URL, "PostgreSQL bağlayıcısı yalnızca PostgreSQL test veritabanıyla sınanır")
class PostgresBaglayici(ToplayiciBase):
    def test_postgresql_katalogu_anahtar_ve_referanslar(self):
        os.environ["TDR_TEST_DSN"] = PG_URL
        self.addCleanup(os.environ.pop, "TDR_TEST_DSN", None)
        conn = collector.CONNECTORS["postgresql"]({"dsn_env": "TDR_TEST_DSN", "schemas": [self.schema]})
        try:
            tables = {t["name"]: t for t in conn.collect()}
            headers, sample = conn.sample(self.schema, "tdr_data_sources", 5)
        finally:
            conn.close()
        cols = {c["name"]: c for c in tables["tdr_data_tables"]["columns"]}
        self.assertTrue(cols["id"]["primary_key"])
        self.assertEqual(cols["source_id"]["references"], f"{self.schema}.tdr_data_sources.id")
        self.assertIn("name", headers)
        self.assertEqual(len(sample), 1)


if __name__ == "__main__":
    unittest.main()
