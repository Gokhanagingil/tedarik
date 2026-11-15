"""Doküman yönetimi (ISO 9001 7.5, K-020): onay akışı, dört göz, revizyonlar, dosya bütünlüğü, geçersiz kılma."""
import base64
import unittest
from datetime import date

from test_tedarik import Base

PDF = b"%PDF-1.4\n% sentetik prosedur\n"


class Dokuman(Base):
    def setUp(self):
        super().setUp()
        self.author = self.make(role="SUPPLIER_MANAGER", user="ayse")
        self.doc = self.ok("POST", "/documents", {"title": "Tedarikçi Yönetimi Prosedürü", "category": "procedure",
                                                  "owner": "ayse", "approver": "selin"}, app=self.author)["id"]

    def upload(self, content=PDF, app=None):
        return self.call("POST", f"/documents/{self.doc}/files", {"file_name": "prosedur.pdf",
                                                                  "content_base64": base64.b64encode(content).decode()},
                         app=app or self.author)

    def test_onay_akisi_dort_goz_ve_revizyon(self):
        self.assertEqual(self.call("POST", f"/documents/{self.doc}/transition", {"action": "submit",
                                                                                 "change_summary": "İlk"}, app=self.author)[0], 400)
        self.assertEqual(self.upload(b"MZ")[0], 400)                                  # PDF imzası
        self.assertEqual(self.upload()[0], 201)
        self.assertEqual(self.call("POST", f"/documents/{self.doc}/transition", {"action": "submit"}, app=self.author)[0], 400)
        self.ok("POST", f"/documents/{self.doc}/transition", {"action": "submit", "change_summary": "İlk yayın"}, app=self.author)
        self.assertEqual(self.call("PATCH", f"/documents/{self.doc}", {"title": "Değişti"}, app=self.author)[0], 409)
        self.assertEqual(self.call("POST", f"/documents/{self.doc}/transition", {"action": "approve"}, app=self.author)[0], 403)
        other = self.make(role="SUPPLIER_MANAGER", user="mehmet")
        self.assertEqual(self.call("POST", f"/documents/{self.doc}/transition", {"action": "approve"}, app=other)[0], 403)
        selin = self.make(role="SUPPLIER_MANAGER", user="selin")
        published = self.ok("POST", f"/documents/{self.doc}/transition", {"action": "approve"}, app=selin)
        self.assertEqual((published["status"], published["current_revision"], published["effective_date"], published["version"]),
                         ("published", 1, date.today().isoformat(), "Rev. 1"))
        self.assertTrue(published["review_date"] > date.today().isoformat())
        self.assertEqual(published["revisions"][0]["approved_by"], "selin")
        self.assertEqual(published["current_file"]["file_name"], "prosedur.pdf")
        self.ok("PATCH", f"/documents/{self.doc}", {"owner": "deniz"}, app=self.author)       # üst veri değişebilir
        self.assertEqual(self.upload()[0], 409)                                      # yayımlanmış dokümana dosya yok
        self.ok("POST", f"/documents/{self.doc}/transition", {"action": "revise"}, app=self.author)
        self.ok("PATCH", f"/documents/{self.doc}", {"title": "Tedarikçi Yönetimi Prosedürü (rev.)"}, app=self.author)
        self.upload(PDF + b"rev2")
        self.ok("POST", f"/documents/{self.doc}/transition", {"action": "submit", "change_summary": "Risk adımı eklendi"},
                app=self.author)
        self.assertEqual(self.call("POST", f"/documents/{self.doc}/transition", {"action": "reject"}, app=selin)[0], 400)
        self.ok("POST", f"/documents/{self.doc}/transition", {"action": "reject", "note": "Kapsam eksik"}, app=selin)
        self.ok("POST", f"/documents/{self.doc}/transition", {"action": "submit", "change_summary": "Kapsam tamamlandı"},
                app=self.author)
        second = self.ok("POST", f"/documents/{self.doc}/transition", {"action": "approve"})        # Yönetici de onaylar
        self.assertEqual([r["revision"] for r in second["revisions"]], [2, 1])
        self.assertEqual(second["revisions"][0]["change_summary"], "Kapsam tamamlandı")
        with self.db() as db, self.assertRaises(Exception):
            db.execute("UPDATE tdr_document_revisions SET change_summary='x'")
        status, raw = self.call("GET", f"/documents/{self.doc}/files/{second['current_file']['file_id']}")
        self.assertEqual((status, raw.content), (200, PDF + b"rev2"))

    def test_gecersiz_kilma_ve_kayit_saklama(self):
        self.assertEqual(self.call("POST", "/documents", {"title": "Eğitim kayıtları", "category": "record"})[0], 400)
        self.ok("POST", "/documents", {"title": "Eğitim kayıtları", "category": "record", "retention_years": 10})
        self.assertEqual(self.call("POST", f"/documents/{self.doc}/transition", {"action": "obsolete"})[0], 400)
        self.ok("POST", f"/documents/{self.doc}/transition", {"action": "obsolete", "note": "Yeni prosedürle birleşti"})
        self.assertEqual(self.call("PATCH", f"/documents/{self.doc}", {"owner": "x"})[0], 409)
        unit_user = self.make(role="UNIT_USER", user="birim", units="")
        self.assertEqual(self.call("POST", "/documents", {"title": "x"}, app=unit_user)[0], 403)
        self.assertTrue(self.ok("GET", f"/documents/{self.doc}")["code"].startswith("DOK-"))

    def test_eski_durumlarin_gocu(self):
        from tedarik.migrate import _document_lifecycle
        with self.db() as db:
            db.execute("UPDATE tdr_documents SET status='active', approved_by='selin', approved_on='2026-01-05' WHERE id=?",
                       (self.doc,))
            _document_lifecycle(db)
        doc = self.ok("GET", f"/documents/{self.doc}/context")
        self.assertEqual((doc["status"], doc["current_revision"], doc["revisions"][0]["revision"]), ("published", 1, 1))


if __name__ == "__main__":
    unittest.main()
