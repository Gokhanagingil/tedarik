"""NIST OSCAL kataloglarından portalın standart kütüphanesi dosyalarını üretir (tedarik/data/standards/*.json.gz).

Kullanım (indirilen dosyalar güvenilmeyen veridir; betik ayrı dizinden, -I ile çalıştırılır):
    python -I scripts/build_standards.py sp80053 <SP800-53 katalog.json> <LOW.json> <MODERATE.json> <HIGH.json> <PRIVACY.json>
    python -I scripts/build_standards.py csf2 <CSF 2.0 katalog.json>
    python -I scripts/build_standards.py kvkk <mevzuat.gov.tr 6698 metin HTML>
    python -I scripts/build_standards.py gdpr <EUR-Lex 32016R0679 EN HTML>

Kaynaklar (usnistgov/oscal-content, main dalı):
    nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json
    nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_{LOW,MODERATE,HIGH,PRIVACY}-baseline_profile.json
    nist.gov/CSF/v2.0/json/NIST_CSF_v2.0_catalog.json
NIST yayınları ABD federal hükümeti eseridir (17 U.S.C. §105); telif koruması dışındadır.
KVKK (6698): https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatNo=6698&MevzuatTertip=5 —
resmî metin; 5846 sayılı FSEK md. 31 uyarınca kanun metinleri üzerinde fikrî hak yoktur.
GDPR (2016/679): https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32016R0679 — © Avrupa Birliği;
2011/833/AB Komisyon Kararı uyarınca kaynak gösterilerek yeniden kullanılabilir.

Kurallar: geri çekilmiş (withdrawn) kontroller ve alt kategoriler yüklenmez; parametreler NIST'in basılı biçimiyle
([Assignment: organization-defined ...], [Selection (one or more): ...]) yazılır; resmi ilişkiler (SP 800-53 "related")
madde ilişkisi olarak taşınır.
"""
import gzip
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tedarik" / "data" / "standards"
INSERT = re.compile(r"\{\{\s*insert:\s*param,\s*([A-Za-z0-9_.\-]+)\s*\}\}")
BASE = "https://raw.githubusercontent.com/usnistgov/oscal-content/main/nist.gov/"


def _prop(item, name, cls=None):
    for p in item.get("props", ()):
        if p["name"] == name and (cls is None or p.get("class") == cls):
            return p["value"]
    return None


def _withdrawn(item):
    return any(p["name"] == "status" and p["value"] == "withdrawn" for p in item.get("props", ()))


class Renderer:
    def __init__(self, params):
        self.params = params

    def param(self, pid, depth=0):
        p = self.params.get(pid)
        if p is None or depth > 5:
            return "[Assignment: organization-defined value]"
        if "select" in p:
            how = p["select"].get("how-many")
            head = "Selection (one or more)" if how == "one-or-more" else "Selection"
            choices = "; ".join(self.text(c, depth + 1) for c in p["select"].get("choice", ()))
            return f"[{head}: {choices}]"
        label = (p.get("label") or (p.get("guidelines") or [{}])[0].get("prose", "value")).strip()
        return f"[Assignment: {label}]" if label.startswith("organization-defined") else \
            f"[Assignment: organization-defined {label}]"

    def text(self, prose, depth=0):
        return INSERT.sub(lambda m: self.param(m.group(1), depth), prose or "").strip()

    def items(self, parts, indent=0):
        lines = []
        for part in parts:
            if part.get("name") != "item":
                continue
            label = _prop(part, "label") or ""
            prose = self.text(part.get("prose"))
            lines.append(("  " * indent) + (label + " " if label else "") + prose)
            lines += self.items(part.get("parts", ()), indent + 1)
        return lines

    def statement(self, control):
        for part in control.get("parts", ()):
            if part["name"] == "statement":
                lines = [self.text(part["prose"])] if part.get("prose") else []
                return "\n".join(lines + self.items(part.get("parts", ())))
        return ""

    def objectives(self, part, out):
        label = _prop(part, "label", "sp800-53a")
        if part.get("prose"):
            out.append(f"{label} {self.text(part['prose'])}" if label else self.text(part["prose"]))
        for child in part.get("parts", ()):
            if child["name"] == "assessment-objective":
                self.objectives(child, out)
        return out

    def assessment(self, control):
        lines, methods = [], []
        for part in control.get("parts", ()):
            if part["name"] == "assessment-objective":
                lines = self.objectives(part, [])
            elif part["name"] == "assessment-method":
                method = _prop(part, "method") or ""
                objects = [o for sub in part.get("parts", ()) if sub["name"] == "assessment-objects"
                           for o in (sub.get("prose") or "").split("\n\n") if o.strip()]
                if objects:
                    methods.append(f"{method}: " + "; ".join(self.text(o) for o in objects))
        text = []
        if lines:
            text.append("Determine if:\n" + "\n".join(lines))
        if methods:
            text.append("\n".join(methods))
        return "\n\n".join(text)


def _source(path, url):
    return {"url": url, "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "retrieved": date.today().isoformat()}


def _write(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=False).encode()
    target = OUT / name
    with gzip.GzipFile(target, "wb", mtime=0) as fh:     # mtime=0: aynı girdi aynı dosyayı üretir
        fh.write(data)
    print(f"{target}: {len(payload['clauses'])} madde, {len(payload['links'])} ilişki, {target.stat().st_size} bayt")


def sp80053(catalog_path, *baselines):
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))["catalog"]
    base = {}
    for path, tag in zip(baselines, ("LOW", "MODERATE", "HIGH", "PRIVACY")):
        profile = json.loads(Path(path).read_text(encoding="utf-8"))["profile"]
        for imp in profile["imports"]:
            for inc in imp.get("include-controls", ()):
                for cid in inc.get("with-ids", ()):
                    base.setdefault(cid, []).append(tag)

    def walk(controls):
        for c in controls:
            yield c
            yield from walk(c.get("controls", ()))

    params = {p["id"]: p for g in catalog["groups"] for c in walk(g.get("controls", ())) for p in c.get("params", ())}
    render = Renderer(params)
    clauses, links, labels = [], [], {}
    withdrawn = sum(1 for g in catalog["groups"] for c in walk(g.get("controls", ())) if _withdrawn(c))
    for group in catalog["groups"]:
        clauses.append({"code": _prop(group, "label") or group["id"].upper(), "title": group["title"],
                        "type": "family", "parent": None})
        for control in walk(group.get("controls", ())):    # basılı etiket: "AC-2(1)" (sıfır dolgusuz)
            labels[control["id"]] = next((p["value"] for p in control.get("props", ())
                                          if p["name"] == "label" and not p.get("class")), control["id"].upper())
    for group in catalog["groups"]:
        fam = _prop(group, "label") or group["id"].upper()

        def emit(control, parent):
            if _withdrawn(control):
                return
            code = labels[control["id"]]
            guidance = next((render.text(p.get("prose")) for p in control.get("parts", ()) if p["name"] == "guidance"), "")
            tags = base.get(control["id"], [])
            clauses.append({"code": code, "title": control["title"], "parent": parent,
                            "type": "enhancement" if control.get("class") == "SP800-53-enhancement" else "control",
                            "text": render.statement(control), "guidance": guidance,
                            "assessment": render.assessment(control), "tags": ", ".join(tags)})
            for link in control.get("links", ()):
                if link.get("rel") == "related" and link["href"].startswith("#"):
                    target = link["href"][1:]
                    if target in labels:
                        links.append({"from": code, "to": labels[target], "relation": "related"})
            for child in control.get("controls", ()):
                emit(child, code)

        for control in group.get("controls", ()):
            emit(control, fam)
    present = {c["code"] for c in clauses}
    links = [l for l in links if l["to"] in present and l["from"] != l["to"]]
    meta = catalog["metadata"]
    payload = {
        "format": "tedarik-standard/1", "key": "nist-sp800-53", "code": "NIST SP 800-53",
        "name": "Security and Privacy Controls for Information Systems and Organizations",
        "version": "Rev. 5.2.0", "issuer": "NIST", "language": "en",
        "description": ("NIST SP 800-53 Rev. 5.2.0 kontrolleri ve iyileştirmeleri; SP 800-53A Rev. 5.2.0 değerlendirme "
                        "prosedürleri (denetçi için 'Değerlendirme' alanı) ve SP 800-53B temel düzeyleri (LOW, MODERATE, "
                        f"HIGH, PRIVACY etiketleri). Geri çekilmiş {withdrawn} kontrol yüklenmedi."),
        "published": meta.get("last-modified", "")[:10],
        "license": "ABD federal hükümeti eseri (17 U.S.C. §105), telif koruması dışında.",
        "sources": [_source(catalog_path, BASE + "SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json")] + [
            _source(p, BASE + f"SP800-53/rev5/json/NIST_SP-800-53_rev5_{t}-baseline_profile.json")
            for p, t in zip(baselines, ("LOW", "MODERATE", "HIGH", "PRIVACY"))],
        "clauses": clauses, "links": links}
    _write("nist-sp800-53r5.json.gz", payload)


def csf2(catalog_path):
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))["catalog"]
    render = Renderer({})
    clauses, withdrawn = [], 0

    def statement(item):
        return next((render.text(p.get("prose")) for p in item.get("parts", ()) if p["name"] == "statement"), "")

    def examples(item):
        ex = [render.text(p.get("prose")) for p in item.get("parts", ()) if p["name"] == "guidance"]
        return "\n".join(f"Ex{i}: {e}" for i, e in enumerate(ex, 1))

    for function in catalog["groups"]:
        clauses.append({"code": function["id"], "title": function["title"].title(), "type": "function", "parent": None,
                        "text": statement(function)})
        for category in function.get("controls", ()):
            if _withdrawn(category):
                withdrawn += 1
                continue
            clauses.append({"code": category["id"], "title": category["title"], "type": "category",
                            "parent": function["id"], "text": statement(category)})
            for sub in category.get("controls", ()):
                if _withdrawn(sub):
                    withdrawn += 1
                    continue
                parties = [p.get("remarks", "") for p in sub.get("props", ()) if p.get("class") == "risk-party"]
                clauses.append({"code": sub["id"], "title": statement(sub) or sub["title"], "type": "subcategory",
                                "parent": category["id"], "guidance": examples(sub),
                                "tags": ", ".join(parties)})
    meta = catalog["metadata"]
    payload = {
        "format": "tedarik-standard/1", "key": "nist-csf-2", "code": "NIST CSF", "name": "Cybersecurity Framework",
        "version": "2.0", "issuer": "NIST", "language": "en",
        "description": ("NIST Cybersecurity Framework 2.0 (CSWP 29): 6 işlev, kategoriler ve alt kategoriler; uygulama "
                        f"örnekleri 'Rehber' alanında. Geri çekilmiş {withdrawn} öğe yüklenmedi."),
        "published": meta.get("last-modified", "")[:10],
        "license": "ABD federal hükümeti eseri (17 U.S.C. §105), telif koruması dışında.",
        "sources": [_source(catalog_path, BASE + "CSF/v2.0/json/NIST_CSF_v2.0_catalog.json")],
        "clauses": clauses, "links": []}
    _write("nist-csf-2.json.gz", payload)


# ------------------------------------------------------------------ KVKK ve GDPR (K-033)

KVKK_NOT_APPLICABLE = {
    **{f"md. {n}": "Amaç, kapsam veya tanım maddesi; doğrudan yükümlülük getirmez." for n in (1, 2, 3)},
    "md. 14": "İlgili kişinin Kurula şikâyet yolu; veri sorumlusunun yükümlülüğü md. 13 ve md. 15'tedir.",
    "md. 17": "Suçlar (Türk Ceza Kanunu atfı); yaptırım maddesi.", "md. 18": "Kabahatler; idari para cezası maddesi.",
    **{f"md. {n}": "Kişisel Verileri Koruma Kurumunun teşkilatı ve işleyişi; veri sorumlusuna yükümlülük getirmez."
       for n in range(19, 32)},
    "md. 32": "Yürürlük.", "md. 33": "Yürütme.",
    **{f"Geçici md. {n}": "Geçiş hükmü; süresi geçmiş veya Kurumla ilgili." for n in (1, 2, 3)},
}


def kvkk(html_path):
    """mevzuat.gov.tr metni paragraf (<p>) yapısıyla okunur: ortalanmış kalın paragraflar bölüm, kalın paragraflar madde
    başlığı, "MADDE n-" ile başlayan paragraf madde metnidir."""
    import html as htmlmod
    raw = Path(html_path).read_text(encoding="utf-8", errors="replace")
    paras = []
    for m in re.finditer(r"<p([^>]*)>(.*?)</p>", raw, re.S | re.I):
        attrs, inner = m.group(1), m.group(2)
        clean = lambda h: re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", h))).replace("\xa0", " ").strip()   # noqa: E731
        text = clean(inner)
        if not text:
            continue
        bold = clean(" ".join(re.findall(r"<b[^>]*>(.*?)</b>", inner, re.S | re.I)))
        paras.append({"text": text, "bold": bold == text, "center": "center" in attrs.lower()})
    clauses, chapter, pending, article = [], None, [], None
    ordinals = {"BİRİNCİ": "Birinci", "İKİNCİ": "İkinci", "ÜÇÜNCÜ": "Üçüncü", "DÖRDÜNCÜ": "Dördüncü", "BEŞİNCİ": "Beşinci",
                "ALTINCI": "Altıncı", "YEDİNCİ": "Yedinci", "SEKİZİNCİ": "Sekizinci"}
    section_title = None
    started = False
    for para in paras:
        text = para["text"]
        if text.startswith("(I) SAYILI CETVEL"):
            break
        if para["bold"] and para["center"] and text.endswith("BÖLÜM"):
            started = True
            chapter = f"B{sum(1 for c in clauses if c['type'] == 'category') + 1}"
            section_title = {"code": chapter, "title": f"{ordinals.get(text.split()[0], text.split()[0])} Bölüm", "type": "category",
                             "parent": None, "applicable": False, "justification": "Bölüm başlığı."}
            clauses.append(section_title)
            article, pending = None, []
            continue
        if not started:
            continue
        if para["bold"] and para["center"] and section_title is not None and article is None and not pending:
            section_title["title"] += (" — " if "—" not in section_title["title"] else " ") + text
            continue
        head = re.match(r"^(GEÇİCİ )?MADDE (\d+)\s*[-–]\s*(.*)$", text)
        if head:
            num = head.group(2)
            code = f"Geçici md. {num}" if head.group(1) else f"md. {num}"
            title = re.sub(r"\[\d+\]", "", " ".join(pending)).strip() or (f"Geçici madde {num}" if head.group(1) else f"Madde {num}")
            article = {"code": code, "title": title, "type": "article", "parent": chapter, "text": head.group(3)}
            if code in KVKK_NOT_APPLICABLE:
                article.update(applicable=False, justification=KVKK_NOT_APPLICABLE[code])
            clauses.append(article)
            pending = []
            section_title = None
            continue
        if para["bold"] and not para["center"] and not text.startswith("("):
            pending.append(text)
            continue
        if article is not None:
            article["text"] = (article["text"] + "\n" + text).strip()
    for c in clauses:                       # mevzuat.gov.tr dipnot işaretleri ([1], [7]) metinden çıkarılır
        if c.get("text"):
            c["text"] = re.sub(r"\[\d+\]", "", c["text"])
    arts = [c for c in clauses if c["type"] == "article"]
    if len(arts) != 36 or len({c["code"] for c in arts}) != 36 or any(not a["text"] for a in arts):
        raise SystemExit(f"Beklenen 33 madde ve 3 geçici madde bulunamadı ({len(arts)})")
    payload = {
        "format": "tedarik-standard/1", "key": "kvkk-6698", "code": "KVKK", "name": "Kişisel Verilerin Korunması Kanunu (6698)",
        "version": "7499 değişikliğiyle (2024)", "issuer": "TBMM", "language": "tr",
        "description": ("6698 sayılı Kanunun mevzuat.gov.tr'deki güncel metni: 33 madde ve 3 geçici madde, bölümler başlık olarak. "
                        "Kurumun kadro cetveli (I sayılı cetvel) Kanunun ekidir ve veri sorumlusuna yükümlülük getirmediği için "
                        "alınmadı. Kurum teşkilatı, yaptırım ve yürürlük maddeleri 'uygulanamaz' olarak gelir."),
        "published": "2016-04-07",
        "license": "Resmî kanun metni; 5846 sayılı FSEK md. 31 uyarınca fikrî hak yoktur.",
        "sources": [_source(html_path, "https://www.mevzuat.gov.tr/anasayfa/MevzuatFihristDetayIframe?MevzuatTur=1&MevzuatNo=6698&MevzuatTertip=5")],
        "clauses": clauses, "links": []}
    _write("kvkk-6698.json.gz", payload)


GDPR_NOT_APPLICABLE = {
    **{n: "Konu, kapsam ve tanımlar; doğrudan yükümlülük getirmez." for n in (1, 2, 3, 4)},
    40: "Davranış kuralları: isteğe bağlı (katılım hâlinde uygulanır).", 41: "Davranış kurallarını izleyen kuruluşlar.",
    42: "Belgelendirme: isteğe bağlı.", 43: "Belgelendirme kuruluşları.",
    48: "Birlik hukukunca izin verilmeyen aktarım veya ifşa: üçüncü ülke kararları; durum hâlinde uygulanır.",
    50: "Uluslararası iş birliği: Komisyon ve denetim makamları.",
    **{n: "Bağımsız denetim makamları ve aralarındaki iş birliği." for n in range(51, 77)},
    **{n: "Başvuru yolları; ilgili kişi ve makam hakları." for n in range(77, 82)},
    82: "Tazminat sorumluluğu.", 83: "İdari para cezaları.", 84: "Yaptırımlar (üye devlet).",
    85: "İfade özgürlüğü: üye devlet hukuku.", 86: "Resmî belgelere erişim: kamu kurumları.",
    87: "Ulusal kimlik numarası: üye devlet hukuku.", 90: "Sır saklama yükümlülükleri: üye devlet hukuku.",
    91: "Kiliseler ve dinî kuruluşlar.", 92: "Yetki devri.", 93: "Komite usulü.",
    **{n: "Son hükümler." for n in range(94, 100)},
}


def gdpr(html_path):
    import html as htmlmod
    raw = Path(html_path).read_text(encoding="utf-8")
    merged = re.sub(r"</p>\s*</td>\s*<td[^>]*>\s*<p[^>]*>", " ", raw)     # (a) + metin aynı satır

    def paras(segment):
        out = []
        for m in re.finditer(r"<p[^>]*class=\"oj-(normal|ti-grseq-1)\"[^>]*>(.*?)</p>", segment, re.S):
            text = htmlmod.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                out.append(text)
        return out

    def title_of(segment, cls):
        m = re.search(r"<p[^>]*class=\"%s\"[^>]*>(.*?)</p>" % cls, segment, re.S)
        return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", m.group(1)))).strip() if m else ""
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'<div[^>]*\sid="((?:cpt_[IVX]+)|(?:art_\d+)|(?:rct_\d+))">', merged)]
    for stop in ("HAVE ADOPTED THIS REGULATION", "This Regulation shall be binding in its entirety"):
        at = merged.find(stop)
        if at > 0:
            marks.append((at, "stop"))
    marks.sort()
    clauses, recitals, chapter = [], [], None
    for k, (pos, ident) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(merged)
        seg = merged[pos:end]
        if ident == "stop":
            continue
        if ident.startswith("cpt_"):
            num = ident[4:]
            name = title_of(seg, "oj-ti-section-2")
            chapter = f"Ch. {num}"
            clauses.append({"code": chapter, "title": f"Chapter {num} — {name}", "type": "category", "parent": None,
                            "applicable": False, "justification": "Bölüm başlığı."})
        elif ident.startswith("art_"):
            n = int(ident[4:])
            item = {"code": f"Art. {n}", "title": title_of(seg, "oj-sti-art"), "type": "article", "parent": chapter,
                    "text": "\n".join(paras(seg))}
            if n in GDPR_NOT_APPLICABLE:
                item.update(applicable=False, justification=GDPR_NOT_APPLICABLE[n])
            clauses.append(item)
        else:
            n = int(ident[4:])
            body = paras(seg)
            recitals.append({"code": f"Rec. {n}", "title": f"Recital ({n})", "type": "clause", "parent": "REC",
                             "text": re.sub(r"^\(\d+\)\s*", "", " ".join(body)), "applicable": False,
                             "justification": "Gerekçe (açıklayıcı); doğrudan yükümlülük değil."})
    arts = [c for c in clauses if c["type"] == "article"]
    if len(arts) != 99 or len(recitals) != 173 or any(not a["text"] or not a["title"] for a in arts):
        raise SystemExit(f"GDPR çözümlenemedi: {len(arts)} madde, {len(recitals)} gerekçe")
    clauses.append({"code": "REC", "title": "Recitals (gerekçeler)", "type": "category", "parent": None, "applicable": False,
                    "justification": "Gerekçeler bölümü."})
    payload = {
        "format": "tedarik-standard/1", "key": "gdpr-2016-679", "code": "GDPR",
        "name": "General Data Protection Regulation (EU) 2016/679", "version": "2016/679", "issuer": "Avrupa Birliği",
        "language": "en",
        "description": ("Tüzüğün EUR-Lex'teki İngilizce metni: 11 bölüm, 99 madde ve 173 gerekçe. Denetim makamları, yaptırım, "
                        "üye devlet hukukuna bırakılan durumlar ve son hükümler ile gerekçeler 'uygulanamaz' olarak gelir; "
                        "kurum kapsamına göre değiştirir (GDPR, AB'deki kişilere mal/hizmet sunulduğunda veya davranışları "
                        "izlendiğinde uygulanır, md. 3/2)."),
        "published": "2016-05-04",
        "license": "© Avrupa Birliği, EUR-Lex; 2011/833/AB Komisyon Kararı uyarınca kaynak gösterilerek yeniden kullanılabilir.",
        "sources": [_source(html_path, "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32016R0679")],
        "clauses": clauses + recitals, "links": []}
    _write("gdpr-2016-679.json.gz", payload)


if __name__ == "__main__":
    kind, *paths = sys.argv[1:]
    {"sp80053": sp80053, "csf2": csf2, "kvkk": kvkk, "gdpr": gdpr}[kind](*paths)
