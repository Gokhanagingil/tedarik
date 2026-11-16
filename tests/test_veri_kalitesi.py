"""Veri yönetişimi Faz 5 — veri kalitesi (K-032): kural tanımı ve SQL üretimi (lehçeler), elle sonuç, eşik, bulgu ve DÖF
(tekrar sayacı), GRC kontrolüne bağlı kural, toplayıcıyla kurum ağında çalıştırma ve profil (yalnızca sayılar), CSV
klasörü, profilden kural önerisi, hacim anomalisi ve skor kartı. Veriler sentetiktir."""
import base64
import json
import os
import random
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from test_tedarik import PG_URL, Base
from test_toplayici import AppClient, tckn
from tedarik import collector, dq_sql


def b64(text):
    return base64.b64encode(text.encode()).decode()


def vkn(rnd):
    while True:
        s = "".join(str(rnd.randint(0, 9)) for _ in range(9))
        for last in "0123456789":
            if dq_sql.is_vkn(s + last):
                return s + last


CATALOG = {"format": "tedarik.catalog.v1", "tables": [
    {"schema": "app", "name": "musteri", "row_count": 1000, "columns": [
        {"name": "id", "data_type": "integer", "primary_key": True}, {"name": "eposta", "data_type": "text"},
        {"name": "tckn", "data_type": "text"}, {"name": "sehir", "data_type": "text"}, {"name": "puan", "data_type": "integer"},
        {"name": "guncellenme", "data_type": "timestamp"}]},
    {"schema": "app", "name": "siparis", "columns": [
        {"name": "id", "data_type": "integer", "primary_key": True},
        {"name": "musteri_id", "data_type": "integer", "references": "app.musteri.id"}, {"name": "tutar", "data_type": "numeric"}]}]}


class SqlUretimi(unittest.TestCase):
    def test_lehceler_tirnak_kacis_ve_python_denetimi(self):
        rule = {"type": "allowed_values", "schema": "app", "table": "müşteri", "column": 'ad"x', "params": {"values": ["O'Neil", "B"]}}
        sql, mode = dq_sql.build(rule, "postgres")
        self.assertIn('"app"."müşteri"', sql)
        self.assertIn('"ad""x"', sql)
        self.assertIn("'O''Neil'", sql)
        self.assertEqual(mode, "counts")
        self.assertIn("[app].[müşteri]", dq_sql.build(rule, "tsql")[0])
        self.assertIn("`app`.`müşteri`", dq_sql.build(rule, "mysql")[0])
        pattern = {"type": "pattern", "schema": "s", "table": "t", "column": "c", "params": {"pattern": "[0-9]{4}"}}
        self.assertIn("~ '^([0-9]{4})$'", dq_sql.build(pattern, "postgres")[0])
        self.assertIn("LIKE_REGEXPR", dq_sql.build(pattern, "hana")[0])
        self.assertEqual(dq_sql.build(pattern, "tsql")[1], "python")            # SQL Server'da düzenli ifade yok
        self.assertEqual(dq_sql.build({**pattern, "type": "format", "params": {"format": "tckn"}}, "postgres")[1], "python")
        with self.assertRaises(dq_sql.RuleError):
            dq_sql.build({**pattern, "params": {"pattern": "("}}, "postgres")
        with self.assertRaises(dq_sql.RuleError):
            dq_sql.build({"type": "custom_sql", "params": {"sql": "DELETE FROM t"}}, "postgres")
        rnd = random.Random(3)
        good = vkn(rnd)
        self.assertTrue(dq_sql.is_vkn(good))
        self.assertFalse(dq_sql.is_vkn(good[:9] + str((int(good[9]) + 1) % 10)))
        from tedarik import pii
        checked, failed = dq_sql.python_check({"type": "format", "params": {"format": "tckn"}},
                                              [tckn(rnd), tckn(rnd), "12345678901", None, " "], pii)
        self.assertEqual((checked, failed), (3, 1))


class KaliteBase(Base):
    def setUp(self):
        super().setUp()
        self.sid = self.ok("POST", "/data_sources", {"name": "Müşteri Uygulaması", "platform": "postgresql",
                                                     "steward": "veri.yoneticisi", "custodian": "uygulama.ekibi"})["id"]
        self.ok("POST", f"/data_sources/{self.sid}/import", {"filename": "k.json", "content_base64": b64(json.dumps(CATALOG))})
        self.t, self.c = {}, {}
        for t in self.ok("GET", f"/datagov/tables?source_id={self.sid}")["items"]:
            self.t[t["name"]] = t["id"]
            for col in self.ok("GET", f"/data_tables/{t['id']}/context")["columns"]:
                self.c[f"{t['name']}.{col['name']}"] = col["id"]

    def rule(self, table, column=None, kind="not_null", params=None, expect=201, **kw):
        body = {"table_id": self.t[table], "rule_type": kind, "params_json": json.dumps(params or {}), **kw}
        if column:
            body["column_id"] = self.c[f"{table}.{column}"]
        status, out = self.call("POST", "/dq_rules", body)
        self.assertEqual(status, expect, out)
        return out.get("id")

    def result(self, rid, **body):
        return self.ok("POST", f"/dq_rules/{rid}/results", body)

    def email_on(self, *users):
        self.ok("POST", "/integrations/save", {"kind": "email", "enabled": 1, "settings": {
            "host": "smtp.ornek.test", "port": 587, "security": "starttls", "sender": "grc@ornek.test"}})
        with self.db() as db:
            for u in users:
                db.execute("INSERT INTO users (username, email, display_name, is_active, created_at) VALUES (?,?,?,1,?)",
                           (u, f"{u}@ornek.test", u, "2026-01-01T00:00:00+00:00"))

    def notes(self, event):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT username, subject, body FROM tdr_notifications WHERE event=?", (event,)).fetchall()]


class KuralTanimi(KaliteBase):
    def test_dogrulama_varsayilanlar_ve_sql(self):
        rid = self.rule("musteri", "eposta")
        r = self.ok("GET", f"/dq_rules/{rid}/context")
        self.assertEqual((r["name"], r["owner"], r["dimension"], r["code"][:4]), ("eposta boş olmamalı", "veri.yoneticisi", "completeness", "VKK-"))
        self.assertIn('FROM "app"."musteri"', r["sql"])
        self.assertIn('"eposta" IS NULL', r["sql"])
        self.assertEqual((r["mode"], r["dialect"]), ("counts", "postgres"))
        self.rule("musteri", "puan", "range", {"min": 0, "max": 100})
        self.rule("musteri", "sehir", "pattern", {}, expect=400)
        self.rule("musteri", "tckn", "format", {"format": "pasaport"}, expect=400)
        self.rule("musteri", "guncellenme", "freshness", {}, expect=400)
        self.rule("musteri", None, "row_count", {}, expect=400)
        self.rule("musteri", None, "not_null", {}, expect=400)                          # kolon gerekli
        status, _ = self.call("POST", "/dq_rules", {"table_id": self.t["musteri"], "column_id": self.c["siparis.tutar"],
                                                    "rule_type": "not_null"})
        self.assertEqual(status, 400)
        other = self.ok("POST", "/data_sources", {"name": "Başka", "platform": "mysql"})["id"]
        self.ok("POST", f"/data_sources/{other}/import", {"filename": "k.json", "content_base64": b64(json.dumps(
            {"format": "tedarik.catalog.v1", "tables": [{"name": "kisi", "columns": [{"name": "id"}]}]}))})
        far = self.ok("GET", f"/datagov/tables?source_id={other}")["items"][0]["id"]
        far_col = self.ok("GET", f"/data_tables/{far}/context")["columns"][0]["id"]
        self.rule("siparis", "musteri_id", "reference", expect=400, ref_column_id=far_col)
        ref = self.rule("siparis", "musteri_id", "reference", ref_column_id=self.c["musteri.id"])
        self.assertIn('LEFT JOIN (SELECT DISTINCT "id" FROM "app"."musteri")', self.ok("GET", f"/dq_rules/{ref}/context")["sql"])
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("POST", "/dq_rules", {"table_id": self.t["musteri"], "rule_type": "row_count",
                                                         "params_json": json.dumps({"min_rows": 1})}, app=viewer)[0], 403)
        unit = self.ok("POST", "/org_units", {"name": "Satış"})["id"]
        writer = self.make(role="SUPPLIER_MANAGER", user="yazar")
        self.ok("PATCH", f"/data_sources/{self.sid}", {"domain_id": self.ok("POST", "/data_domains", {"name": "Müşteri", "org_unit_id": unit})["id"]})
        unit_user = self.make(role="UNIT_USER", user="birimci", units=str(unit))
        self.assertEqual(self.call("POST", "/dq_rules", {"table_id": self.t["musteri"], "rule_type": "custom_sql",
                                                         "params_json": json.dumps({"sql": "SELECT 1 AS checked, 0 AS failed"})},
                                   app=unit_user)[0], 403)
        self.assertEqual(self.call("POST", "/dq_rules", {"table_id": self.t["musteri"], "rule_type": "custom_sql",
                                                         "params_json": json.dumps({"sql": "SELECT 1 AS checked, 0 AS failed"})},
                                   app=writer)[0], 201)
        sql_server = self.ok("POST", "/data_sources", {"name": "ERP", "platform": "sql_server"})["id"]
        self.ok("POST", f"/data_sources/{sql_server}/import", {"filename": "k.json", "content_base64": b64(json.dumps(
            {"format": "tedarik.catalog.v1", "tables": [{"schema": "dbo", "name": "cari", "columns": [{"name": "vkn"}]}]}))})
        cari = self.ok("GET", f"/datagov/tables?source_id={sql_server}")["items"][0]["id"]
        col = self.ok("GET", f"/data_tables/{cari}/context")["columns"][0]["id"]
        p = self.ok("POST", "/dq_rules", {"table_id": cari, "column_id": col, "rule_type": "pattern",
                                          "params_json": json.dumps({"pattern": "[0-9]{10}"})})["id"]
        ctx = self.ok("GET", f"/dq_rules/{p}/context")
        self.assertEqual((ctx["mode"], ctx["dialect"]), ("python", "tsql"))


class SonucVeGrc(KaliteBase):
    def test_elle_sonuc_esik_bulgu_dof_tekrar_ve_bildirim(self):
        self.email_on("veri.sahibi", "veri.yoneticisi")
        rid = self.rule("musteri", "eposta", threshold_pct=99, severity="high", owner="veri.sahibi")
        r = self.result(rid, checked=1000, failed=5)
        self.assertEqual((r["result"], r["pass_rate"], r["finding_id"]), ("pass", 99.5, None))
        r = self.result(rid, checked=1000, failed=50)
        self.assertEqual(r["result"], "fail")
        self.assertTrue(r["finding_id"] and r["action_id"])
        finding = self.ok("GET", f"/findings/{r['finding_id']}")
        self.assertEqual((finding["source"], finding["severity"], finding["owner"], finding["recurrence"]),
                         ("data_quality", "high", "veri.sahibi", 1))
        action = self.ok("GET", f"/grc_actions/{r['action_id']}")
        self.assertEqual((action["owner"], action["finding_id"]), ("veri.sahibi", r["finding_id"]))
        again = self.result(rid, checked=1000, failed=60)
        self.assertEqual((again["finding_id"], again["action_id"]), (r["finding_id"], None))
        self.assertEqual(self.ok("GET", f"/findings/{r['finding_id']}")["recurrence"], 2)
        self.assertEqual(self.call("POST", f"/dq_rules/{rid}/results", {"checked": 10, "failed": 11})[0], 400)
        ctx = self.ok("GET", f"/dq_rules/{rid}/context")
        self.assertEqual((len(ctx["results"]), ctx["last_result"], ctx["finding"]["recurrence"], len(ctx["actions"])), (3, "fail", 2, 1))
        self.assertTrue(any(n["username"] == "veri.sahibi" for n in self.notes("dq.failed")))
        work = self.ok("GET", "/my-work", app=self.make(user="veri.sahibi"))
        self.assertEqual([x["code"] for x in work["dq_failing"]], [ctx["code"]])
        health = {c["key"]: c for c in self.ok("GET", "/health-check")["checks"]}
        self.assertEqual(health["dq_failing_high"]["count"], 1)
        viewer = self.make(role="VIEWER", user="izleyici")
        self.assertEqual(self.call("POST", f"/dq_rules/{rid}/results", {"checked": 1, "failed": 0}, app=viewer)[0], 403)

        fresh = self.rule("musteri", "guncellenme", "freshness", {"max_age_hours": 24})
        recent = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.assertEqual(self.result(fresh, measured=recent)["result"], "pass")
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        stale = self.result(fresh, measured=old)
        self.assertEqual(stale["result"], "fail")
        self.assertIn("30.0 saat önce", stale["message"])
        count = self.rule("musteri", None, "row_count", {"min_rows": 500, "max_rows": 5000})
        self.assertEqual(self.result(count, measured=120)["result"], "fail")

    def test_kontrole_bagli_kural_kontrol_sonucu_yazar(self):
        control = self.ok("POST", "/controls", {"name": "Müşteri e-posta tamlığı", "owner": "kontrol.sahibi",
                                                "execution_mode": "automatic", "criticality": "high"})["id"]
        rid = self.rule("musteri", "eposta", control_id=control, owner="veri.sahibi")
        ok = self.result(rid, checked=10, failed=0)
        self.assertTrue(ok["execution_id"])
        bad = self.result(rid, checked=10, failed=4)
        self.assertTrue(bad["finding_id"] and bad["action_id"])
        execs = self.ok("GET", f"/executions?control_id={control}")
        statuses = sorted((e["status"], e["source"], e["exceptions"]) for e in (execs["items"] if isinstance(execs, dict) else execs))
        self.assertEqual(statuses, [("fail", "system", 4), ("pass", "system", 0)])
        finding = self.ok("GET", f"/findings/{bad['finding_id']}")
        self.assertEqual((finding["control_id"], finding["source"]), (control, "control_test"))
        again = self.result(rid, checked=10, failed=5)
        self.assertEqual((again["finding_id"], again["action_id"]), (bad["finding_id"], None))


class Toplayici(KaliteBase):
    def sqlite_db(self):
        path = os.path.join(self.tmp.name, "kaynak.db")
        rnd = random.Random(11)
        db = sqlite3.connect(path)
        db.executescript("""CREATE TABLE musteri (id INTEGER PRIMARY KEY, eposta TEXT, tckn TEXT, sehir TEXT, puan INTEGER,
            guncellenme TEXT); CREATE TABLE siparis (id INTEGER PRIMARY KEY, musteri_id INTEGER, tutar REAL);""")
        now = datetime.now(timezone.utc)
        for i in range(40):
            db.execute("INSERT INTO musteri (eposta, tckn, sehir, puan, guncellenme) VALUES (?,?,?,?,?)",
                       (None if i % 10 == 0 else f"kisi{i}@ornek.test", tckn(rnd) if i % 8 else "11111111111",
                        ["Ankara", "İzmir", "istanbul"][i % 3], 10 + i, (now - timedelta(hours=i)).isoformat()))
        db.executemany("INSERT INTO siparis (musteri_id, tutar) VALUES (?,?)", [(i % 45 + 1, 5.0 * i) for i in range(30)])
        db.commit()
        db.close()
        return path

    def test_kurum_aginda_calistirma_profil_ve_oneri(self):
        path = self.sqlite_db()
        out = self.ok("POST", f"/data_sources/{self.sid}/collectors", {"connector": "sqlite", "profile_rows": 100})
        key = out["key"]
        cfg = os.path.join(self.tmp.name, "ayar.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"platform": "https://platform.ornek.test", "connector": "sqlite", "settings": {"path": path, "schema": "app"}}, fh)
        lines = []
        self.assertEqual(collector.main(["gonder", "--ayar", cfg], client=AppClient(self.app, key), out=lines.append), 0, lines)
        self.ok("PATCH", f"/data_columns/{self.c['musteri.tckn']}", {"personal_data": "personal"})
        rules = {
            "eposta": self.rule("musteri", "eposta", threshold_pct=95),
            "tckn": self.rule("musteri", "tckn", "format", {"format": "tckn"}),
            "sehir": self.rule("musteri", "sehir", "allowed_values", {"values": ["Ankara", "İzmir", "İstanbul"]}),
            "desen": self.rule("musteri", "sehir", "pattern", {"pattern": "[A-ZÇĞİÖŞÜ][a-zçğıöşü]+"}),
            "puan": self.rule("musteri", "puan", "range", {"min": 0, "max": 40}),
            "ref": self.rule("siparis", "musteri_id", "reference", ref_column_id=self.c["musteri.id"]),
            "taze": self.rule("musteri", "guncellenme", "freshness", {"max_age_hours": 2}),
            "adet": self.rule("musteri", None, "row_count", {"min_rows": 10}),
            "ozel": self.rule("musteri", None, "custom_sql", {"sql": "SELECT COUNT(*) AS checked, 0 AS failed FROM musteri"}),
        }
        lines = []
        self.assertEqual(collector.main(["kalite", "--ayar", cfg], client=AppClient(self.app, key), out=lines.append), 0, lines)
        self.assertIn("9 kural", lines[-1])
        got = {k: self.ok("GET", f"/dq_rules/{v}/context") for k, v in rules.items()}
        last = {k: (r["results"][0]["checked"], r["results"][0]["failed"], r["last_result"]) for k, r in got.items()}
        self.assertEqual(last["eposta"], (40, 4, "fail"))                # %90 < %95
        self.assertEqual(last["tckn"], (40, 5, "fail"))                  # 11111111111 geçersiz
        self.assertEqual(last["sehir"], (40, 13, "fail"))                # 'istanbul' listede yok
        self.assertEqual(last["desen"], (40, 13, "fail"))
        self.assertEqual(last["puan"], (40, 9, "fail"))                  # 41..49
        self.assertEqual(last["ref"], (30, 0, "pass"))                   # 1..30 ⊂ 1..40
        self.assertEqual(got["taze"]["last_result"], "pass")
        self.assertEqual((got["adet"]["last_result"], got["adet"]["results"][0]["measured"]), ("pass", "40"))
        self.assertEqual(got["ozel"]["last_result"], "error")
        self.assertIn("allow_custom_sql", got["ozel"]["last_message"])
        self.assertEqual(got["eposta"]["results"][0]["source"], "collector")

        q = self.ok("GET", f"/data_tables/{self.t['musteri']}/quality")
        prof = {p["column"]: p for p in q["profiles"]}
        self.assertEqual((prof["eposta"]["sample_size"], prof["eposta"]["null_count"]), (40, 4))
        self.assertEqual((prof["puan"]["min_value"], prof["puan"]["max_value"]), ("10.0", "49.0"))
        self.assertIsNone(prof["tckn"]["min_value"])                     # kişisel veri: en küçük/en büyük gönderilmez
        kinds = {(s["rule_type"], s["column"]) for s in q["suggestions"]}
        self.assertIn(("format", "eposta"), kinds)
        self.assertIn(("not_null", "id"), kinds)
        self.assertNotIn(("format", "tckn"), kinds)                      # kuralı zaten var
        with self.db() as db:
            stored = " ".join(str(r[0]) + str(r[1]) for r in db.execute("SELECT min_value, max_value FROM tdr_dq_profiles").fetchall())
        self.assertNotIn("@ornek.test", stored)

        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"platform": "https://platform.ornek.test", "connector": "sqlite", "allow_custom_sql": True,
                       "settings": {"path": path, "schema": "app"}}, fh)
        lines = []
        self.assertEqual(collector.main(["gonder", "--ayar", cfg], client=AppClient(self.app, key), out=lines.append), 0)
        self.assertTrue(any(l.startswith("Kalite:") for l in lines))   # gönderim kaliteyi de çalıştırır
        self.assertEqual(self.ok("GET", f"/dq_rules/{rules['ozel']}/context")["last_result"], "pass")

    def test_csv_klasoru_kurallari_yerelde(self):
        folder = os.path.join(self.tmp.name, "paylasim")
        os.mkdir(folder)
        with open(os.path.join(folder, "personel.csv"), "w", encoding="utf-8") as fh:
            fh.write("sicil;ad;maas\n" + "".join(f"{1000 + i % 18};Kişi {i};{1500 + 100 * i}\n" for i in range(20)) + "1100;;abc\n")
        src = self.ok("POST", "/data_sources", {"name": "Paylaşım", "platform": "file"})["id"]
        key = self.ok("POST", f"/data_sources/{src}/collectors", {"connector": "files"})["key"]
        cfg = os.path.join(self.tmp.name, "dosya.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"platform": "https://platform.ornek.test", "connector": "files", "settings": {"path": folder}}, fh)
        self.assertEqual(collector.main(["gonder", "--ayar", cfg], client=AppClient(self.app, key), out=lambda x: None), 0)
        t = self.ok("GET", f"/datagov/tables?source_id={src}")["items"][0]["id"]
        cols = {c["name"]: c["id"] for c in self.ok("GET", f"/data_tables/{t}/context")["columns"]}
        mk = lambda col, kind, params=None: self.ok("POST", "/dq_rules", {"table_id": t, "column_id": cols.get(col), "rule_type": kind,   # noqa: E731
                                                                          "params_json": json.dumps(params or {})})["id"]
        rules = {"ad": mk("ad", "not_null"), "sicil": mk("sicil", "unique"), "maas": mk("maas", "range", {"min": 0, "max": 3000})}
        self.assertEqual(collector.main(["kalite", "--ayar", cfg], client=AppClient(self.app, key), out=lambda x: None), 0)
        last = {k: self.ok("GET", f"/dq_rules/{v}/context")["results"][0] for k, v in rules.items()}
        self.assertEqual((last["ad"]["checked"], last["ad"]["failed"]), (21, 1))
        self.assertEqual((last["sicil"]["checked"], last["sicil"]["failed"]), (21, 2))
        self.assertEqual((last["maas"]["checked"], last["maas"]["failed"]), (21, 5))   # 3100..3400 ve 'abc'


class AnomaliVeSkor(KaliteBase):
    def test_hacim_anomalisi_skor_karti_ve_egilim(self):
        self.email_on("veri.yoneticisi")
        self.rule("musteri", None, "row_count", {"min_rows": 1})
        for n in (1000, 1040, 980, 1010, 1020):
            data = json.loads(json.dumps(CATALOG))
            data["tables"][0]["row_count"] = n
            self.ok("POST", f"/data_sources/{self.sid}/import", {"filename": "k.json", "content_base64": b64(json.dumps(data))})
        self.assertEqual(self.ok("GET", "/datagov/quality")["anomalies"], [])
        data = json.loads(json.dumps(CATALOG))
        data["tables"][0]["row_count"] = 120
        self.ok("POST", f"/data_sources/{self.sid}/import", {"filename": "k.json", "content_base64": b64(json.dumps(data))})
        anomalies = self.ok("GET", "/datagov/quality")["anomalies"]
        self.assertEqual(len(anomalies), 1)
        a = anomalies[0]
        self.assertEqual((a["measured"], a["expected"]), (120, 1010))
        self.assertTrue(self.notes("dq.anomaly"))
        self.assertEqual(self.call("POST", f"/dq_anomalies/{a['id']}/acknowledge", {"note": "x"})[0], 400)
        self.ok("POST", f"/dq_anomalies/{a['id']}/acknowledge", {"note": "Arşivleme işi eski kayıtları taşıdı"})
        self.assertEqual(self.call("POST", f"/dq_anomalies/{a['id']}/acknowledge", {"note": "tekrar deneme"})[0], 409)

        comp = self.rule("musteri", "eposta", threshold_pct=90)
        valid = self.rule("musteri", "sehir", "allowed_values", {"values": ["Ankara"]}, severity="high", threshold_pct=95)
        self.result(comp, checked=1000, failed=5)
        self.result(valid, checked=100, failed=10)
        sc = self.ok("GET", "/datagov/quality")["scorecard"]
        self.assertEqual((sc["dimensions"]["completeness"], sc["dimensions"]["validity"]), (99.5, 90.0))
        self.assertEqual(sc["overall"], 94.8)
        self.assertEqual((sc["rules"], sc["failing"]), (2, 1))
        self.assertEqual(sc["by_source"][0]["name"], "Müşteri Uygulaması")
        trend = self.ok("GET", "/datagov/quality")["trend"]
        self.assertEqual(trend[-1]["runs"], 2)
        table = self.ok("GET", f"/data_tables/{self.t['musteri']}/quality")
        self.assertEqual(table["score"]["overall"], 94.8)
        self.assertEqual(len(table["volumes"]), 6)


@unittest.skipUnless(PG_URL, "PostgreSQL lehçesi yalnızca PostgreSQL test veritabanıyla sınanır")
class PostgresLehcesi(KaliteBase):
    def test_uretilen_sorgular_gercek_postgresqlde_calisir(self):
        os.environ["TDR_TEST_DSN"] = PG_URL
        self.addCleanup(os.environ.pop, "TDR_TEST_DSN", None)
        conn = collector.CONNECTORS["postgresql"]({"dsn_env": "TDR_TEST_DSN", "schemas": [self.schema]})
        base = {"schema": self.schema, "table": "tdr_data_sources"}
        cases = [({"type": "not_null", "column": "description"}, (1, 1)), ({"type": "unique", "column": "code"}, (1, 0)),
                 ({"type": "pattern", "column": "code", "params": {"pattern": "VK-[0-9]{4}"}}, (1, 0)),
                 ({"type": "allowed_values", "column": "platform", "params": {"values": ["postgresql"]}}, (1, 0)),
                 ({"type": "range", "column": "id", "params": {"min": 0, "max": 0.5}}, (1, 1)),
                 ({"type": "not_null", "column": "name", "params": {"empty_is_null": True}}, (1, 0))]
        try:
            for rule, expected in cases:
                sql, mode = dq_sql.build({**base, **rule}, "postgres")
                headers, rows = conn.query(sql, 1)
                self.assertEqual((rows[0][0], rows[0][1]), expected, rule)
            _, rows = conn.query(dq_sql.build({**base, "type": "freshness", "column": "created_at"}, "postgres")[0], 1)
            self.assertIsNotNone(collector._plain(rows[0][0]))
            _, rows = conn.query(dq_sql.build({**base, "type": "row_count"}, "postgres")[0], 1)
            self.assertEqual(rows[0][0], 1)
        finally:
            conn.close()
