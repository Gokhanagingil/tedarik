"""Kullanım kılavuzları (Yardım). Kılavuzlar `tedarik/data/kilavuz/*.md` dosyalarıdır; uygulamayla birlikte dağıtılır.

- Markdown sunucuda sınırlı bir alt kümeyle (başlık, paragraf, liste, tablo, alıntı, kod, kalın, satır içi kod, bağlantı)
  JSON blok yapısına çevrilir; tarayıcı yapıyı metin düğümleriyle çizer (HTML yorumlanmaz). Bağlantılar yalnızca uygulama
  içi rotalara (`#/…`) izin verir; diğerleri düz metin olur.
- Her başlığın kimliği (bölüm bağlantısı) Türkçe karakterler katlanarak üretilir; ekranlara bağlama duyarlı yardım
  `CONTEXT` eşlemesiyle bu kimliklere gider.
- Kılavuzlar kişisel veya gizli bilgi içermez; oturum açmış her kullanıcı (makine ve toplayıcı anahtarı hariç) okur.
"""
import re
from pathlib import Path

from . import auth as authz
from .crud import Invalid, NotFound
from .db import fold
from .http import API

DIR = Path(__file__).resolve().parent / "data" / "kilavuz"
GROUPS = ("Genel", "Rol kılavuzları", "Modül kılavuzları")
# anahtar: (grup, önerildiği roller, gereken modül)
GUIDES = {
    "baslarken": ("Genel", None, None),
    "yonetici": ("Rol kılavuzları", {"ADMIN"}, None),
    "tedarikci-yoneticisi": ("Rol kılavuzları", {"SUPPLIER_MANAGER"}, None),
    "birim-kullanicisi": ("Rol kılavuzları", {"UNIT_USER"}, None),
    "denetci": ("Rol kılavuzları", {"AUDITOR"}, "grc"),
    "goruntuleyici": ("Rol kılavuzları", {"VIEWER"}, None),
    "tedarikci-yonetimi": ("Modül kılavuzları", {"SUPPLIER_MANAGER", "UNIT_USER"}, None),
    "risk-yonetimi": ("Modül kılavuzları", {"ADMIN", "SUPPLIER_MANAGER", "UNIT_USER"}, "risks"),
    "uyum-ve-denetim": ("Modül kılavuzları", {"ADMIN", "AUDITOR"}, "grc"),
    "is-surekliligi": ("Modül kılavuzları", None, "continuity"),
    "dokuman-ve-cmdb": ("Modül kılavuzları", None, "documents"),
    "veri-yonetisimi": ("Modül kılavuzları", None, "datagov"),
    "kvkk": ("Modül kılavuzları", {"SUPPLIER_MANAGER"}, "datagov"),
    "yapay-zeka": ("Modül kılavuzları", None, "datagov"),
    "sss": ("Genel", None, None),
}
# Ekran rotası (ilk iki parça) -> (kılavuz, bölüm kimliği). Bölüm kimlikleri testte doğrulanır.
CONTEXT = {
    "home": ("baslarken", "her-gun-kullanacaginiz-ekranlar"), "my-work": ("baslarken", "her-gun-kullanacaginiz-ekranlar"),
    "calendar": ("baslarken", "her-gun-kullanacaginiz-ekranlar"), "health": ("baslarken", "her-gun-kullanacaginiz-ekranlar"),
    "my-surveys": ("tedarikci-yonetimi", "anketler"), "respond": ("tedarikci-yonetimi", "anketler"),
    "risk": ("risk-yonetimi", "risk-panosu"), "r/supplier_risks": ("risk-yonetimi", "risk-acmak"),
    "r/risk_actions": ("risk-yonetimi", "islemek"), "r/kris": ("risk-yonetimi", "izlemek"),
    "r/rcsa_campaigns": ("risk-yonetimi", "oz-degerlendirme-rcsa"), "r/loss_events": ("risk-yonetimi", "kayip-olaylari-ve-nicel-risk"),
    "r/risk_cycles": ("risk-yonetimi", "izlemek"), "r/risk_catalog": ("risk-yonetimi", "risk-acmak"),
    "r/risk_appetites": ("risk-yonetimi", "surec"), "r/risk_criteria": ("risk-yonetimi", "degerlendirmek"),
    "compliance": ("uyum-ve-denetim", "uyum-panosu"), "library": ("uyum-ve-denetim", "standart-kutuphanesi-ve-capraz-esleme"),
    "standard": ("uyum-ve-denetim", "standart-kutuphanesi-ve-capraz-esleme"), "crosswalk": ("uyum-ve-denetim", "standart-kutuphanesi-ve-capraz-esleme"),
    "soa": ("uyum-ve-denetim", "standart-kutuphanesi-ve-capraz-esleme"),
    "obligations": ("uyum-ve-denetim", "yukumlulukler"), "r/controls": ("uyum-ve-denetim", "kontrol-kutuphanesi"),
    "r/objectives": ("uyum-ve-denetim", "yapi-taslari"), "r/policy_exceptions": ("uyum-ve-denetim", "politika-istisnalari"),
    "r/attestation_campaigns": ("uyum-ve-denetim", "okundu-beyani"), "r/certifications": ("uyum-ve-denetim", "sertifikalar"),
    "r/access_reviews": ("uyum-ve-denetim", "erisim-gozden-gecirmeleri"), "r/findings": ("uyum-ve-denetim", "bulgular-ve-duzeltici-faaliyetler"),
    "r/grc_actions": ("uyum-ve-denetim", "bulgular-ve-duzeltici-faaliyetler"), "r/evidence": ("uyum-ve-denetim", "kanitlar"),
    "audit-plan": ("denetci", "1-yillik-plan"), "r/audits": ("denetci", "2-denetimi-kurmak"), "audit": ("denetci", "2-denetimi-kurmak"),
    "audit-report": ("denetci", "8-rapor-ve-tamamlama"), "r/evidence_requests": ("denetci", "3-kanit-istemek"),
    "archive": ("denetci", "denetim-arsivi"), "r/audit_universe": ("denetci", "1-yillik-plan"),
    "bcm": ("is-surekliligi", "akis"), "crisis": ("is-surekliligi", "kriz-yonetimi"), "r/bias": ("is-surekliligi", "is-etki-analizi-bia"),
    "r/bc_plans": ("is-surekliligi", "sureklilik-planlari"), "r/bc_exercises": ("is-surekliligi", "tatbikatlar"),
    "r/documents": ("dokuman-ve-cmdb", "dokuman-yonetimi-iso-9001-7-5"), "cmdb": ("dokuman-ve-cmdb", "cmdb-panosu"),
    "r/cmdb_cis": ("dokuman-ve-cmdb", "varliklar-cmdb"), "r/ci_exposures": ("dokuman-ve-cmdb", "cmdb-panosu"),
    "datagov": ("veri-yonetisimi", "roller-veri-sorumluluklari"), "glossary": ("veri-yonetisimi", "3-is-sozlugu"),
    "catalog": ("veri-yonetisimi", "2-anlam-vermek"), "r/data_sources": ("veri-yonetisimi", "1-kaynaklari-kataloga-almak"),
    "datasource": ("veri-yonetisimi", "1-kaynaklari-kataloga-almak"), "r/data_domains": ("veri-yonetisimi", "1-kaynaklari-kataloga-almak"),
    "collectors": ("veri-yonetisimi", "4-otomatik-toplama-toplayici"), "collector": ("veri-yonetisimi", "4-otomatik-toplama-toplayici"),
    "lineage": ("veri-yonetisimi", "5-soy-kutugu-ve-etki-analizi"), "flow": ("veri-yonetisimi", "5-soy-kutugu-ve-etki-analizi"),
    "impact": ("veri-yonetisimi", "5-soy-kutugu-ve-etki-analizi"), "quality": ("veri-yonetisimi", "6-veri-kalitesi"),
    "dqrule": ("veri-yonetisimi", "6-veri-kalitesi"), "stewardship": ("veri-yonetisimi", "roller-veri-sorumluluklari"),
    "privacy": ("kvkk", "kvkk-panosu"), "discovery": ("kvkk", "1-kisisel-veriyi-bulmak-kesif"),
    "regulation": ("kvkk", "7-kvkk-gdpr-bosluk-analizi"), "r/processing_activities": ("kvkk", "2-isleme-envanteri-verbis"),
    "activity": ("kvkk", "2-isleme-envanteri-verbis"), "r/subject_requests": ("kvkk", "5-ilgili-kisi-basvurulari-md-11"),
    "r/data_requests": ("kvkk", "4-veri-talepleri"), "r/privacy_breaches": ("kvkk", "6-kisisel-veri-ihlalleri-md-12-5"),
    "r/dpias": ("kvkk", "2-isleme-envanteri-verbis"), "r/retention_rules": ("kvkk", "3-saklama-ve-imha"),
    "r/disposal_runs": ("kvkk", "3-saklama-ve-imha"), "disposal": ("kvkk", "3-saklama-ve-imha"),
    "r/personal_data_categories": ("kvkk", "1-kisisel-veriyi-bulmak-kesif"),
    "ai": ("yapay-zeka", "1-sistem-kaydi"), "aisystem": ("yapay-zeka", "2-risk-siniflandirma-sihirbazi"),
    "r/suppliers": ("tedarikci-yonetimi", "tedarikci-360"),
    "r/engagements": ("tedarikci-yonetimi", "temel-kavramlar"), "r/contracts": ("tedarikci-yonetimi", "temel-kavramlar"),
    "r/catalog_items": ("tedarikci-yonetimi", "temel-kavramlar"), "schedule": ("tedarikci-yonetimi", "performans"),
    "r/sla_definitions": ("tedarikci-yonetimi", "hizmet-seviyesi-sla"), "r/sla_measurements": ("tedarikci-yonetimi", "hizmet-seviyesi-sla"),
    "r/performance_events": ("tedarikci-yonetimi", "performans"), "r/performance_reviews": ("tedarikci-yonetimi", "performans"),
    "r/survey_templates": ("tedarikci-yonetimi", "anketler"), "r/survey_campaigns": ("tedarikci-yonetimi", "anketler"),
    "templates": ("tedarikci-yonetimi", "anketler"), "surveys": ("tedarikci-yonetimi", "anketler"),
    "users": ("yonetici", "kullanici-yonetimi"), "roles": ("yonetici", "rol-ve-yetki-matrisi"),
    "integrations": ("yonetici", "entegrasyonlar"), "notifications": ("yonetici", "bildirimler"),
    "transfer": ("yonetici", "toplu-aktarim"), "r/policies": ("yonetici", "politika-parametreleri"),
    "roadmap": ("yonetici", "yol-haritasi"), "r/audit_log": ("yonetici", "denetim-izi"),
    "r/companies": ("yonetici", "ilk-kurulum-sirasi"), "r/org_units": ("yonetici", "ilk-kurulum-sirasi"),
    "r/processes": ("yonetici", "ilk-kurulum-sirasi"), "process-map": ("baslarken", "haritalar"), "map": ("baslarken", "haritalar"),
    "r/import_batches": ("yonetici", "toplu-aktarim"), "r/cmdb_sync_runs": ("dokuman-ve-cmdb", "senkron"),
    "r/supplier_types": ("yonetici", "ana-veri-ekranlari"), "r/review_criteria": ("yonetici", "ana-veri-ekranlari"),
    "r/data_subject_groups": ("yonetici", "ana-veri-ekranlari"),
}

_TR = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u",
                     "Ç": "c", "Ğ": "g", "I": "i", "İ": "i", "Ö": "o", "Ş": "s", "Ü": "u", "Â": "a"})
INLINE = re.compile(r"\*\*(.+?)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)")
LIST_ITEM = re.compile(r"^( *)([-*]|\d+\.) +(.*)$")
_cache = {}


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", re.sub(r"[*`]", "", text).translate(_TR).lower()).strip("-")
    return s or "bolum"


def inline(text):
    """Satır içi işaretleme -> düğüm listesi: text, b (kalın), code, a (yalnızca #/ rotaları)."""
    out, pos = [], 0
    for m in INLINE.finditer(text):
        if m.start() > pos:
            out.append({"t": "text", "v": text[pos:m.start()]})
        if m.group(1) is not None:
            out.append({"t": "b", "c": inline(m.group(1))})
        elif m.group(2) is not None:
            out.append({"t": "code", "v": m.group(2)})
        else:
            label, href = m.group(3), m.group(4)
            out.append({"t": "a", "href": href, "c": inline(label)} if href.startswith("#/") else {"t": "text", "v": label})
        pos = m.end()
    if pos < len(text):
        out.append({"t": "text", "v": text[pos:]})
    return out


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse(markdown):
    """Kılavuz metnini blok listesine çevirir. Dönüş: (başlık, blocks)."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    blocks, title, ids, i = [], None, {}, 0

    def unique(text):
        base = slug(text)
        ids[base] = ids.get(base, 0) + 1
        return base if ids[base] == 1 else f"{base}-{ids[base]}"
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            body, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            blocks.append({"type": "code", "text": "\n".join(body)})
            i += 1
            continue
        heading = re.match(r"^(#{1,4}) +(.*)$", stripped)
        if heading:
            level, text = len(heading.group(1)), heading.group(2).strip()
            if level == 1 and title is None:
                title = text
            else:
                blocks.append({"type": "heading", "level": level, "text": re.sub(r"[*`]", "", text), "id": unique(text)})
            i += 1
            continue
        if stripped.startswith(">"):
            body = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                body.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append({"type": "quote", "c": inline(" ".join(body))})
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?[\s:|-]+\|?$", lines[i + 1].strip()) \
                and "-" in lines[i + 1]:
            header, rows_, i = _cells(stripped), [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows_.append(_cells(lines[i]))
                i += 1
            blocks.append({"type": "table", "header": [inline(c) for c in header],
                           "rows": [[inline(c) for c in r] for r in rows_]})
            continue
        item = LIST_ITEM.match(line)
        if item:
            ordered = item.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m = LIST_ITEM.match(lines[i])
                if not m:
                    if lines[i].strip() and lines[i].startswith("   ") and items:   # maddenin devam satırı
                        items[-1]["text"] += " " + lines[i].strip()
                        i += 1
                        continue
                    break
                if len(m.group(1)) >= 2 and items:
                    items[-1].setdefault("children", []).append(m.group(3))
                elif m.group(2)[0].isdigit() != ordered:
                    break
                else:
                    items.append({"text": m.group(3)})
                i += 1
            blocks.append({"type": "list", "ordered": ordered, "items": [
                {"c": inline(it["text"]), "children": [inline(ch) for ch in it.get("children", [])]} for it in items]})
            continue
        body = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,4} |>|\||```)", lines[i].strip()) \
                and not LIST_ITEM.match(lines[i]):
            body.append(lines[i].strip())
            i += 1
        blocks.append({"type": "p", "c": inline(" ".join(body))})
    return title or "Kılavuz", blocks


def _plain(nodes):
    out = []
    for n in nodes:
        out.append(n.get("v") or _plain(n.get("c", [])))
    return "".join(out)


def load():
    """Tüm kılavuzlar: anahtar -> {title, summary, blocks, sections, text}. Dosya değişince yenilenir."""
    out = {}
    for path in sorted(DIR.glob("*.md")):
        key = re.sub(r"^\d+-", "", path.stem)
        if key not in GUIDES:
            continue
        stamp = path.stat().st_mtime_ns
        cached = _cache.get(path)
        if not cached or cached[0] != stamp:
            title, blocks = parse(path.read_text(encoding="utf-8"))
            summary = next((_plain(b["c"]) for b in blocks if b["type"] == "quote"), "")
            sections = [{"id": b["id"], "title": b["text"], "level": b["level"]} for b in blocks if b["type"] == "heading"]
            cached = (stamp, {"key": key, "title": title, "summary": summary, "blocks": blocks, "sections": sections})
            _cache[path] = cached
        out[key] = cached[1]
    return out


def _available(app, key):
    module = GUIDES[key][2]
    return module is None or app.enabled(module)


def _allowed(principal):
    authz.require_human(principal)
    authz.require(principal, "read")


def index(c):
    _allowed(c.principal)
    guides = load()
    role = c.principal.role
    items = []
    for key, (group, roles, _module) in GUIDES.items():
        if key not in guides or not _available(c.app, key):
            continue
        g = guides[key]
        items.append({"key": key, "title": g["title"], "summary": g["summary"], "group": group,
                      "recommended": key == "baslarken" or bool(roles and role in roles),
                      "sections": [s for s in g["sections"] if s["level"] == 2]})
    context = {route: list(target) for route, target in CONTEXT.items() if target[0] in {i["key"] for i in items}}
    return {"groups": list(GROUPS), "guides": items, "context": context, "role": role,
            "external": c.principal.external}


def guide(c):
    _allowed(c.principal)
    key = str(c.query.get("key") or "")
    guides = load()
    if key not in guides or key not in GUIDES or not _available(c.app, key):
        raise NotFound("Kılavuz bulunamadı")
    return guides[key]


def search(c):
    _allowed(c.principal)
    q = fold(str(c.query.get("q") or "").strip())
    if len(q) < 2:
        raise Invalid("En az 2 karakter yazın")
    if len(q) > 100:
        raise Invalid("Arama metni çok uzun")
    words = q.split()
    hits = []
    for key, g in load().items():
        if not _available(c.app, key):
            continue
        section = {"id": None, "title": g["title"]}
        for b in g["blocks"]:
            if b["type"] == "heading":
                section = {"id": b["id"], "title": b["text"]}
                text = b["text"]
            elif b["type"] in ("p", "quote"):
                text = _plain(b["c"])
            elif b["type"] == "list":
                text = " · ".join(_plain(it["c"]) + " " + " ".join(_plain(ch) for ch in it["children"]) for it in b["items"])
            elif b["type"] == "table":
                text = " · ".join(" | ".join(_plain(cell) for cell in row) for row in b["rows"])
            else:
                text = b.get("text", "")
            folded = fold(text)
            if all(w in folded for w in words):
                at = folded.find(words[0])
                start = max(0, at - 60)
                snippet = ("…" if start else "") + text[start:start + 180].strip() + ("…" if start + 180 < len(text) else "")
                score = (2 if b["type"] == "heading" else 0) + sum(folded.count(w) for w in words)
                hits.append({"key": key, "guide": g["title"], "section": section["title"], "anchor": section["id"],
                             "snippet": snippet, "score": score})
    hits.sort(key=lambda h: -h["score"])
    seen, out = set(), []
    for h in hits:
        k = (h["key"], h["anchor"])
        if k in seen:
            continue
        seen.add(k)
        out.append({x: h[x] for x in ("key", "guide", "section", "anchor", "snippet")})
        if len(out) >= 30:
            break
    return {"query": c.query.get("q"), "results": out}


def register(app):
    app.route("GET", API + "/help", index)
    app.route("GET", API + "/help/search", search)
    app.route("GET", API + "/help/guide", guide)
