"""Kullanım kılavuzları (Yardım): ayrıştırıcı ve güvenlik (HTML yorumlanmaz, dış bağlantı düz metin), kılavuz bütünlüğü
(bölüm bağlantıları, uygulama içi bağlantıların gerçek ekranlara gitmesi), rol önerisi, modül süzme, arama ve yetki."""
import re
import unittest
from pathlib import Path

from test_tedarik import KEY, Base
from tedarik import help as H
from tedarik.schema import RESOURCES

STATIC = Path(__file__).resolve().parent.parent / "tedarik" / "static"


def routes():
    """İstemcideki rota anahtarları: PAGES.x, PAGES['x'] ve yönlendiricideki key === 'x'."""
    text = "".join(p.read_text(encoding="utf-8") for p in STATIC.glob("*.js"))
    found = set(re.findall(r"PAGES\.([a-z]+) = ", text)) | set(re.findall(r"PAGES\['([a-z-]+)'\] = ", text))
    return found | set(re.findall(r"key === '([a-z-]+)'", text)) | {"home"}


class Ayristirici(unittest.TestCase):
    def test_bloklar_ve_guvenlik(self):
        title, blocks = H.parse("""# Başlık

> Kimler için: herkes.

## Giriş ve Çıkış (md. 12/5)

Metin **kalın [bağlantı](#/home)** ve `kod` <script>alert(1)</script> [dış](https://ornek.test) [js](javascript:alert(1)).

1. Bir
2. İki
   - alt madde
- yeni liste

| A | B |
|---|---|
| **x** | y |

```
düz | metin
```
## Giriş ve Çıkış (md. 12/5)
""")
        self.assertEqual(title, "Başlık")
        kinds = [b["type"] for b in blocks]
        self.assertEqual(kinds, ["quote", "heading", "p", "list", "list", "table", "code", "heading"])
        self.assertEqual([b["id"] for b in blocks if b["type"] == "heading"], ["giris-ve-cikis-md-12-5", "giris-ve-cikis-md-12-5-2"])
        p = blocks[2]["c"]
        self.assertEqual(p[1]["t"], "b")
        self.assertEqual(p[1]["c"][1], {"t": "a", "href": "#/home", "c": [{"t": "text", "v": "bağlantı"}]})
        self.assertIn({"t": "code", "v": "kod"}, p)
        flat = repr(p)
        self.assertIn("<script>alert(1)</script>", flat)                 # metin olarak kalır; istemci textContent ile yazar
        self.assertNotIn("https://ornek.test", flat)                      # dış bağlantı düz metne döner
        self.assertNotIn("javascript:", flat)
        ordered = blocks[3]
        self.assertTrue(ordered["ordered"])
        self.assertEqual(len(ordered["items"]), 2)
        self.assertEqual(ordered["items"][1]["children"][0], [{"t": "text", "v": "alt madde"}])
        self.assertFalse(blocks[4]["ordered"])
        self.assertEqual(blocks[5]["rows"][0][0][0]["t"], "b")
        self.assertEqual(blocks[6]["text"], "düz | metin")


class KilavuzButunlugu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tedarik import modules
        from tedarik.config import Config, KNOWN_MODULES
        modules.load(Config({"TEDARIK_DB": ":memory:", "TEDARIK_AUTH_MODE": "dev", "TEDARIK_MODULES": ",".join(KNOWN_MODULES)}))

    def test_tum_kilavuzlar_ve_baglantilar(self):
        guides = H.load()
        self.assertEqual(set(guides), set(H.GUIDES))
        known = routes()
        for key, g in guides.items():
            self.assertTrue(g["title"] and g["summary"].startswith("Kimler için") or key == "yapay-zeka" or g["summary"], key)
            self.assertGreaterEqual(len([s for s in g["sections"] if s["level"] == 2]), 2, key)
            hrefs = []

            def walk(nodes):
                for n in nodes:
                    if n.get("t") == "a":
                        hrefs.append(n["href"])
                    walk(n.get("c", []))
            for b in g["blocks"]:
                for part in ([b.get("c", [])] + [it["c"] for it in b.get("items", [])] +
                             [c for row in b.get("rows", []) for c in row] + b.get("header", [])):
                    walk(part)
            for href in hrefs:
                parts = href[2:].split("?")[0].split("/")
                if parts[0] == "r":
                    self.assertIn(parts[1], RESOURCES, f"{key}: {href}")
                else:
                    self.assertIn(parts[0], known, f"{key}: {href}")
        ids = {k: {s["id"] for s in g["sections"]} for k, g in guides.items()}
        for route, (key, anchor) in H.CONTEXT.items():
            self.assertIn(anchor, ids[key], route)
            if route.startswith("r/"):
                self.assertIn(route[2:], RESOURCES, route)
            else:
                self.assertIn(route, known, route)

    def test_menudeki_ekranlarin_yardimi_var(self):
        menu = re.findall(r"\['((?:r/)?[a-z_-]+)', '[a-z]+'", (STATIC / "app.js").read_text(encoding="utf-8").split("const MENU = [")[1].split("];")[0])
        missing = [m for m in menu if m not in H.CONTEXT and m not in ("help", "r/needs", "r/quotes")]
        self.assertEqual(missing, [])


class YardimUclari(Base):
    def test_rol_onerisi_modul_suzme_arama_yetki(self):
        idx = self.ok("GET", "/help")
        keys = [g["key"] for g in idx["guides"]]
        self.assertEqual(keys[0], "baslarken")
        rec = {g["key"] for g in idx["guides"] if g["recommended"]}
        self.assertTrue({"baslarken", "yonetici"} <= rec and "denetci" not in rec)
        self.assertEqual(idx["context"]["r/findings"], ["uyum-ve-denetim", "bulgular-ve-duzeltici-faaliyetler"])
        auditor = self.ok("GET", "/help", app=self.make(role="AUDITOR", user="denetci"))
        self.assertIn("denetci", {g["key"] for g in auditor["guides"] if g["recommended"]})
        g = self.ok("GET", "/help/guide?key=kvkk")
        self.assertEqual(g["title"], "Kişisel veri (KVKK ve GDPR)")
        self.assertTrue(any(b["type"] == "table" for b in g["blocks"]))
        self.assertEqual(self.call("GET", "/help/guide?key=yok")[0], 404)
        narrow = self.make(modules="core,performance,surveys")
        n = self.ok("GET", "/help", app=narrow)
        self.assertNotIn("kvkk", {x["key"] for x in n["guides"]})
        self.assertNotIn("privacy", n["context"])
        self.assertEqual(self.call("GET", "/help/guide?key=kvkk", app=narrow)[0], 404)
        hits = self.ok("GET", "/help/search?q=GEÇİCİ parola")["results"]
        self.assertTrue(hits and any(h["key"] == "yonetici" for h in hits))
        self.assertTrue(all(h["anchor"] is None or isinstance(h["anchor"], str) for h in hits))
        self.assertTrue(self.ok("GET", "/help/search?q=72 saat")["results"])
        self.assertEqual(self.call("GET", "/help/search?q=a")[0], 400)
        self.assertEqual(self.call("GET", "/help", headers={"X-API-Key": KEY})[0], 403)
        self.ok("GET", "/help", app=self.make(role="VIEWER", user="izleyici"))


if __name__ == "__main__":
    unittest.main()
