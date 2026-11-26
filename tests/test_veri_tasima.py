"""Veri taşıma (K-037): demo yüklü kurulumdan döküm, boş kuruluma yükleme; kimlikler ve bağlantılar korunur, kullanıcılar ve
sırlar dökümde yoktur, kimlik sayaçları ve kayıt kodları devam eder, dolu kuruluma yükleme reddedilir. Veri sentetiktir."""
import io
import json
import gzip
import os
import secrets
import tempfile
import unittest

from test_tedarik import KEY, PG_URL, Base
from tedarik import dataio, demo
from tedarik.config import Config
from tedarik.db import rows
from tedarik.http import build


class VeriTasima(Base):
    def target(self, engine="sqlite"):
        """Boş hedef kurulum (açılışın başlangıç kayıtlarıyla)."""
        env = {"TEDARIK_AUTH_MODE": "dev", "TEDARIK_API_KEY": KEY, "TEDARIK_DEV_ROLE": "ADMIN", "TEDARIK_DEV_USER": "dev"}
        if engine == "postgres":
            import psycopg
            schema = "t_" + secrets.token_hex(6)
            with psycopg.connect(PG_URL, autocommit=True) as admin:
                admin.execute(f'CREATE SCHEMA "{schema}"')

            def drop():
                with psycopg.connect(PG_URL, autocommit=True) as admin:
                    admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
            self.addCleanup(drop)
            env.update({"TEDARIK_DB": os.path.join(self.tmp.name, "pg.db"), "TEDARIK_DATABASE_URL": PG_URL,
                        "TEDARIK_DB_SCHEMA": schema})
        else:
            env["TEDARIK_DB"] = os.path.join(tempfile.mkdtemp(dir=self.tmp.name), "hedef.db")
        app = build(Config(env))
        self.addCleanup(app.close)
        return app

    def counts(self, app):
        with app.database.connect() as db:
            return {r.name: db.execute(f"SELECT COUNT(*) AS n FROM {r.table}").fetchone()["n"]
                    for r in dataio._tables(app, db)}

    def check_roundtrip(self, engine):
        doc = json.loads(gzip.decompress(self.blob))
        target = self.target(engine)
        self.ok("POST", "/suppliers", {"name": "Hedef İlk Kayıt A.Ş."}, app=target)          # dolu kuruluma yüklenmez
        with self.assertRaises(SystemExit):
            dataio.load(target, doc)
        target = self.target(engine)
        with target.database.connect() as db:                                          # açılışın denetim izi
            db.execute("INSERT INTO tdr_audit_log (occurred_at, actor, auth_type, method, object_type) VALUES (?,?,?,?,?)",
                       ("2026-11-26T08:00:00+00:00", "bootstrap", "system", "BOOTSTRAP", "users"))
        loaded, skipped = dataio.load(target, doc)
        self.assertEqual(skipped, [])
        source, copied = self.counts(self.app), self.counts(target)
        for name, n in source.items():
            expected = n + (2 if name == "audit_log" else 0)                         # açılış kaydı + IMPORT kaydı
            self.assertEqual(copied[name], expected, name)
        # bağlantılar ve kimlikler korunur
        with self.app.database.connect() as a, target.database.connect() as b:
            for sql in ("SELECT id, code, name, tier FROM tdr_suppliers ORDER BY id",
                        "SELECT id, code, parent_id, standard_id FROM tdr_clauses ORDER BY id",
                        "SELECT id, parent_id, replaced_by_id, status FROM tdr_glossary_terms ORDER BY id",
                        "SELECT id, residual, assessed_at FROM tdr_risk_assessments ORDER BY id",
                        "SELECT f.id, f.sha256, b.file_id FROM tdr_evidence_files f JOIN tdr_evidence_blobs b ON b.file_id=f.id ORDER BY f.id"):
                self.assertEqual([dict(r) for r in rows(a, sql)], [dict(r) for r in rows(b, sql)], sql)
            blob_a = rows(a, "SELECT content FROM tdr_evidence_blobs ORDER BY id LIMIT 1")
            blob_b = rows(b, "SELECT content FROM tdr_evidence_blobs ORDER BY id LIMIT 1")
            if blob_a:
                self.assertEqual(bytes(blob_a[0]["content"]), bytes(blob_b[0]["content"]))
        # ekranlar çalışır; yeni kayıt kimliği ve kodu kaldığı yerden devam eder
        self.assertEqual(len(self.ok("GET", "/suppliers?limit=1000", app=target)), source["suppliers"])
        self.assertGreater(self.ok("GET", "/health-check", app=target)["score"], 0)
        last = max(s["id"] for s in self.ok("GET", "/suppliers?limit=1000", app=target))
        made = self.ok("POST", "/suppliers", {"name": "Taşıma Sonrası Yeni A.Ş."}, app=target)
        self.assertGreater(made["id"], last)
        record = self.ok("GET", f"/suppliers/{made['id']}", app=target)
        self.assertEqual(record["code"], f"TED-{source['suppliers'] + 1:04d}")
        self.assertIsNone(demo.seed(target))                                           # demo zaten yüklü sayılır
        return doc

    def test_dokum_ve_bos_kuruluma_yukleme(self):
        demo.seed(self.app)
        with self.app.database.connect() as db:                                        # gizli kayıt örneği
            db.execute("INSERT INTO tdr_idempotency (idem_key, route, body_hash, response_json, created_at) VALUES (?,?,?,?,?)",
                       ("anahtar-12345678", "POST /api/tdr/users", "x", '{"temporary_password": "gizli-gecici-parola"}',
                        "2026-11-26T08:00:00+00:00"))
        buf = io.BytesIO()
        counts = dataio.export(self.app, buf)
        self.blob = buf.getvalue()
        text = gzip.decompress(self.blob).decode("utf-8")
        doc = json.loads(text)
        self.assertEqual(doc["format"], "tedarik.data.v1")
        self.assertFalse(set(doc["tables"]) & dataio.EXCLUDE)
        self.assertNotIn("users", doc["tables"])
        self.assertNotIn("pbkdf2_sha256", text)                                         # parola özeti yok
        self.assertNotIn("gizli-gecici-parola", text)
        self.assertGreater(counts["suppliers"], 40)
        self.assertGreater(sum(counts.values()), 5000)
        self.check_roundtrip("sqlite")
        if PG_URL:
            self.check_roundtrip("postgres")

    def test_bicim_ve_disarida_kalan_tablo_denetimi(self):
        with self.assertRaises(SystemExit):
            dataio.read(io.BytesIO(b'{"format": "baska"}'))
        with self.assertRaises(SystemExit):
            dataio.load(self.target(), {"format": dataio.FORMAT, "tables": {"user_roles": {"columns": [], "rows": []}}})


if __name__ == "__main__":
    unittest.main()
