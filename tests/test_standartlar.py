"""Standart kütüphanesi, standartlar arası madde ilişkileri, bulgu etkisi ve entegre denetim (K-023)."""
import base64
import json
import unittest

from test_tedarik import Base


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode()


class Kutuphane(Base):
    def test_nist_paketleri_tam_kurulur_ve_guncelleme_sas_korur(self):
        lib = self.ok("GET", "/standards/library")
        keys = {p["key"]: p for p in lib["packages"]}
        self.assertEqual(set(keys), {"nist-sp800-53", "nist-csf-2", "kvkk-6698", "gdpr-2016-679"})
        self.assertEqual(keys["nist-sp800-53"]["clauses"], 1034)            # 20 aile + 1014 kontrol/iyileştirme
        self.assertEqual(keys["nist-csf-2"]["clauses"], 134)                # 6 işlev + 22 kategori + 106 alt kategori
        self.assertTrue(any("ISO" in u["name"] for u in lib["unavailable"]))
        auditor = self.make(role="AUDITOR", user="denetci")
        self.assertEqual(self.call("POST", "/standards/library/install", {"key": "nist-csf-2"}, app=auditor)[0], 403)
        first = self.ok("POST", "/standards/library/install", {"key": "nist-sp800-53"})
        self.assertEqual((first["created"], first["updated"]), (1034, 0))
        self.assertGreater(first["links"], 1500)                              # resmî "related" ilişkileri
        csf = self.ok("POST", "/standards/library/install", {"key": "nist-csf-2"})
        self.assertEqual(csf["created"], 134)
        sid = first["standard_id"]
        self.assertEqual(self.ok("GET", f"/standards/{sid}")["active"], 0)      # başvuru: kapsama alınana kadar sayılmaz
        ac2 = self.ok("GET", f"/clauses?standard_id={sid}&code=AC-2")[0]
        self.assertIn("Define and document the types of accounts", ac2["description"])
        self.assertIn("[Assignment: organization-defined", ac2["description"])
        self.assertIn("Determine if:", ac2["assessment"])                     # SP 800-53A
        self.assertIn("EXAMINE:", ac2["assessment"])
        self.assertIn("MODERATE", ac2["tags"])                                # SP 800-53B temel düzeyi
        family = self.ok("GET", f"/clauses/{ac2['parent_id']}")
        self.assertEqual((family["code"], family["clause_type"]), ("AC", "family"))
        self.assertFalse(self.ok("GET", f"/clauses?standard_id={sid}&code=AC-2(10)"))   # geri çekilmiş kontrol yüklenmez
        # kurumun uygulanabilirlik bildirimi güncellemede korunur
        self.ok("PATCH", f"/clauses/{ac2['id']}", {"applicable": 0, "justification": "Kapsam dışı (örnek)"})
        again = self.ok("POST", "/standards/library/install", {"key": "nist-sp800-53"})
        self.assertEqual((again["created"], again["updated"], again["links"]), (0, 0, 0))
        self.assertEqual(self.ok("GET", f"/clauses/{ac2['id']}")["applicable"], 0)
        tree = self.ok("GET", f"/standards/{sid}/tree")
        self.assertEqual(len(tree["clauses"]), 1034)
        self.assertEqual(tree["clauses"][0]["code"], "AC")
        state = {p["key"]: p for p in self.ok("GET", "/standards/library")["packages"]}
        self.assertTrue(state["nist-sp800-53"]["installed"]["current"])
        rel = self.ok("GET", f"/clauses/{ac2['id']}/relations")
        self.assertTrue(any(link["code"] == "AC-3" and link["source"] == "official" for link in rel["links"]))

    def test_lisansli_metin_ice_aktarimi(self):
        csv = ("Madde kodu;Başlık;Üst madde;Tür;Metin;Değerlendirme;Uygulanabilir;Gerekçe\n"
               "5;Liderlik;;Madde;;;Evet;\n"
               "5.1;Liderlik ve taahhüt;5;Madde;Sentetik madde metni;Üst yönetim taahhüdü nasıl gösteriliyor?;Evet;\n"
               "5.2;Politika;5;Madde;Sentetik politika metni;;Hayır;Örnek gerekçe\n")
        body = {"filename": "ornek.csv", "content_base64": b64(csv),
                "standard": {"code": "ÖRNEK 9999", "name": "Sentetik yönetim sistemi", "version": "2026"}}
        dry = self.ok("POST", "/standards/import", {**body, "dry_run": True})
        self.assertEqual((dry["created"], dry["standard_exists"]), (3, False))
        self.assertFalse(self.ok("GET", "/standards?code=ÖRNEK 9999"))
        done = self.ok("POST", "/standards/import", body)
        self.assertEqual(done["created"], 3)
        clauses = {c["code"]: c for c in self.ok("GET", f"/clauses?standard_id={done['standard_id']}")}
        self.assertEqual(clauses["5.1"]["parent_id"], clauses["5"]["id"])
        self.assertEqual(clauses["5.2"]["applicable"], 0)
        self.assertEqual(clauses["5.1"]["assessment"], "Üst yönetim taahhüdü nasıl gösteriliyor?")
        bad = csv + "5.3;;5;Madde;;;Hayır;\n"
        self.assertEqual(self.call("POST", "/standards/import", {**body, "content_base64": b64(bad)})[0], 400)
        status, _ = self.call("POST", "/standards/import", {**body, "content_base64": b64("Başlık\nx\n")})
        self.assertEqual(status, 400)                                            # madde kodu sütunu yok
        template = self.app.dispatch("GET", "/api/tdr/standards/import/template?kind=links", {}, b"")
        self.assertEqual(template[0], 200)


class Iliskiler(Base):
    def setUp(self):
        super().setUp()
        self.a = self.ok("POST", "/standards", {"code": "STD-A", "name": "Sentetik A", "version": "1"})["id"]
        self.b = self.ok("POST", "/standards", {"code": "STD-B", "name": "Sentetik B", "version": "1"})["id"]
        self.c = self.ok("POST", "/standards", {"code": "STD-C", "name": "Sentetik C", "version": "1"})["id"]
        mk = lambda std, code, title: self.ok("POST", "/clauses", {"standard_id": std, "code": code, "title": title})["id"]
        self.a542 = mk(self.a, "5.4.2", "Yedeklerin düzenli alınması ve geri yükleme testi")
        self.a61 = mk(self.a, "6.1", "Erişim haklarının gözden geçirilmesi")
        self.b361 = mk(self.b, "3.6.1", "Yedekleme ve geri yükleme")
        self.b40 = mk(self.b, "4.0", "Bilgi güvenliği politikası")
        self.c11 = mk(self.c, "1.1", "Operasyonel dayanıklılık")
        self.c12 = mk(self.c, "1.2", "Kayıt yönetimi")

    def link(self, a, b, relation, **kw):
        return self.ok("POST", "/clause_links", {"from_clause_id": a, "to_clause_id": b, "relation": relation, **kw})

    def test_iliski_kurallari(self):
        self.link(self.a542, self.b361, "equivalent", rationale="Aynı gereksinim")
        self.assertEqual(self.call("POST", "/clause_links", {"from_clause_id": self.b361, "to_clause_id": self.a542,
                                                             "relation": "subset"})[0], 409)        # ters yön de aynı çift
        self.assertEqual(self.call("POST", "/clause_links", {"from_clause_id": self.a61, "to_clause_id": self.a61})[0], 400)
        self.assertEqual(self.call("POST", "/clause_links", {"from_clause_id": self.a61, "to_clause_id": self.b40,
                                                             "relation": "same"})[0], 400)
        auditor = self.make(role="AUDITOR", user="denetci")
        self.assertEqual(self.call("POST", "/clause_links", {"from_clause_id": self.a61, "to_clause_id": self.b40},
                                   app=auditor)[0], 403)
        rel = self.ok("GET", f"/clauses/{self.b361}/relations")
        self.assertEqual((rel["links"][0]["code"], rel["links"][0]["relation"]), ("5.4.2", "equivalent"))

    def test_bulgu_baska_standardin_maddesini_de_ihlal_eder(self):
        self.link(self.a542, self.b361, "equivalent")                # kesin
        self.link(self.b361, self.c11, "subset")                     # B 3.6.1 ⊂ C 1.1: zincir yoluyla kesin
        self.link(self.a542, self.c12, "intersects")                 # olası
        self.link(self.b40, self.a542, "related")                    # bilgi amaçlı
        finding = self.ok("POST", "/findings", {"title": "Geri yükleme testi yapılmamış", "clause_id": self.a542,
                                                "severity": "high"})["id"]
        impact = self.ok("GET", f"/findings/{finding}/impact")
        levels = {c["code"]: c["level"] for g in impact["groups"] for c in g["clauses"]}
        self.assertEqual(levels, {"5.4.2": "direct", "3.6.1": "certain", "1.1": "certain", "1.2": "possible",
                                  "4.0": "related"})
        self.assertEqual(impact["standards"], 3)
        context = self.ok("GET", f"/findings/{finding}/context")
        self.assertEqual(context["impact"]["counts"]["certain"], 2)
        # ters yön: B 3.6.1'e bakan, A'daki bulguyu görür
        rel = self.ok("GET", f"/clauses/{self.b361}/relations")
        self.assertEqual([(f["id"], f["level"]) for f in rel["findings"]], [(finding, "certain")])
        # üst küme yönünde ihlal kesin değildir
        other = self.ok("POST", "/findings", {"title": "C 1.1 eksik", "clause_id": self.c11})["id"]
        levels = {c["code"]: c["level"] for g in self.ok("GET", f"/findings/{other}/impact")["groups"] for c in g["clauses"]}
        self.assertEqual(levels["3.6.1"], "possible")
        # pasifleştirilen ilişki etkiyi kaldırır
        link = self.ok("GET", f"/clause_links?from_clause_id={self.a542}&to_clause_id={self.c12}")[0]
        self.ok("PATCH", f"/clause_links/{link['id']}", {"active": 0})
        levels = {c["code"] for g in self.ok("GET", f"/findings/{finding}/impact")["groups"] for c in g["clauses"]}
        self.assertNotIn("1.2", levels)

    def test_ortak_kontrol_bulgusu_tum_maddeleri_etkiler(self):
        ctl = self.ok("POST", "/controls", {"name": "Yedekleme kontrolü"})["id"]
        self.ok("POST", f"/controls/{ctl}/links", {"clauses": [self.a542, self.b361, self.c11]})
        finding = self.ok("POST", "/findings", {"title": "Yedek alınmamış", "control_id": ctl})["id"]
        levels = {c["code"]: c["level"] for g in self.ok("GET", f"/findings/{finding}/impact")["groups"] for c in g["clauses"]}
        self.assertEqual(levels, {"5.4.2": "direct", "3.6.1": "direct", "1.1": "direct"})
        only_clause = self.ok("POST", "/findings", {"title": "A 5.4.2", "clause_id": self.a542})["id"]
        levels = {c["code"]: c["level"] for g in self.ok("GET", f"/findings/{only_clause}/impact")["groups"]
                  for c in g["clauses"]}
        self.assertEqual(levels["3.6.1"], "possible")                 # ortak kontrol üzerinden
        rel = self.ok("GET", f"/clauses/{self.a542}/relations")
        self.assertEqual(sorted(s["code"] for s in rel["shared"]), ["1.1", "3.6.1"])

    def test_capraz_esleme_ice_aktarimi_ve_oneriler(self):
        csv = ("Kaynak standart;Kaynak madde;Hedef standart;Hedef madde;İlişki;Gerekçe\n"
               "STD-A;5.4.2;STD-B;3.6.1;Eşdeğer;Yedekleme\n"
               "Sentetik A;6.1;STD-B 1;4.0;İlgili;\n"
               "STD-A;9.9;STD-B;4.0;Kesişir;\n"
               "STD-A;6.1;STD-C;1.2;bilinmeyen;\n")
        body = {"filename": "esleme.csv", "content_base64": b64(csv)}
        dry = self.ok("POST", "/clause_links/import", {**body, "dry_run": True})
        self.assertEqual((dry.get("create"), dry.get("error")), (2, 2))
        self.assertFalse(self.ok("GET", "/clause_links"))
        done = self.ok("POST", "/clause_links/import", body)
        self.assertEqual(done["create"], 2)
        again = self.ok("POST", "/clause_links/import", body)
        self.assertEqual(again.get("skip"), 2)
        links = self.ok("GET", "/clause_links")
        self.assertEqual({(l["relation"], l["source"]) for l in links}, {("equivalent", "crosswalk"), ("related", "crosswalk")})
        sug = self.ok("GET", f"/clauses/{self.c11}/suggestions?standard_id={self.a}")
        self.assertIn("note", sug)
        work = self.ok("GET", f"/standards/{self.a}/crosswalk?target_id={self.b}")
        self.assertEqual(work["total"], 2)
        item = next(i for i in work["items"] if i["code"] == "5.4.2")
        self.assertEqual(item["links"][0]["code"], "3.6.1")
        unlinked = self.ok("GET", f"/standards/{self.a}/crosswalk?target_id={self.b}&unlinked=1")
        self.assertEqual(unlinked["total"], 0)

    def test_entegre_denetim_tek_test_tek_kanit(self):
        backup = self.ok("POST", "/controls", {"name": "Yedekleme ve geri yükleme testi"})["id"]
        self.ok("POST", f"/controls/{backup}/links", {"clauses": [self.a542, self.b361]})
        self.link(self.a61, self.b40, "intersects")
        self.link(self.a61, self.c11, "related")                     # ilgili ilişki soru grubu oluşturmaz
        audit = self.ok("POST", "/audits", {"name": "Entegre denetim", "standard_ids": [self.a, self.b, self.c],
                                            "clause_ids": [self.a542, self.a61, self.b361, self.b40, self.c11]})["id"]
        plan = self.ok("GET", f"/audits/{audit}/integrated")
        s = plan["summary"]
        self.assertEqual((s["scope_clauses"], s["tests"], s["groups"], s["questions"], s["saved"]), (5, 1, 2, 3, 2))
        # bir test iki maddeyi (A 5.4.2, B 3.6.1), bir soru grubu iki maddeyi (A 6.1, B 4.0) karşılar: 2 soru tekrarlanmaz
        self.assertEqual(s["multi_standard_tests"], 1)
        test = plan["tests"][0]
        self.assertEqual([x["standard"] for x in test["standards"]], ["STD-A 1", "STD-B 1"])
        group = next(g for g in plan["groups"] if len(g["clauses"]) == 2)
        self.assertEqual({c["code"] for c in group["clauses"]}, {"6.1", "4.0"})
        made = self.ok("POST", "/controls/common", {"name": "Erişim gözden geçirme", "clause_ids": [c["id"] for c in group["clauses"]]})
        self.assertTrue(made["code"].startswith("KTL-"))
        plan = self.ok("GET", f"/audits/{audit}/integrated")
        self.assertEqual((plan["summary"]["tests"], plan["summary"]["groups"]), (2, 1))
        auditor = self.make(role="AUDITOR", user="denetci")
        self.assertEqual(self.call("POST", "/controls/common", {"name": "x", "clause_ids": [self.c11]}, app=auditor)[0], 403)

    def test_eksik_referans_kimlikle_yuklenir(self):
        rows = self.ok("GET", f"/clauses?id__in={self.a542},{self.c12}")
        self.assertEqual({r["code"] for r in rows}, {"5.4.2", "1.2"})
        self.assertEqual(self.call("GET", "/clauses?id__in=x")[0], 400)


if __name__ == "__main__":
    unittest.main()
