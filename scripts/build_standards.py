"""NIST OSCAL kataloglarından portalın standart kütüphanesi dosyalarını üretir (tedarik/data/standards/*.json.gz).

Kullanım (indirilen dosyalar güvenilmeyen veridir; betik ayrı dizinden, -I ile çalıştırılır):
    python -I scripts/build_standards.py sp80053 <SP800-53 katalog.json> <LOW.json> <MODERATE.json> <HIGH.json> <PRIVACY.json>
    python -I scripts/build_standards.py csf2 <CSF 2.0 katalog.json>

Kaynaklar (usnistgov/oscal-content, main dalı):
    nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json
    nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_{LOW,MODERATE,HIGH,PRIVACY}-baseline_profile.json
    nist.gov/CSF/v2.0/json/NIST_CSF_v2.0_catalog.json
NIST yayınları ABD federal hükümeti eseridir (17 U.S.C. §105); telif koruması dışındadır.

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


if __name__ == "__main__":
    kind, *paths = sys.argv[1:]
    {"sp80053": sp80053, "csf2": csf2}[kind](*paths)
