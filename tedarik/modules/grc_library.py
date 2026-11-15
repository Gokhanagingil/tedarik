"""Standart kütüphanesi, standartlar arası madde ilişkileri ve entegre denetim (grc modülünün parçası). K-023.

Kütüphane
- `tedarik/data/standards/*.json.gz`: tam metniyle dağıtılabilen standartlar (bugün NIST SP 800-53 Rev. 5.2.0 ve
  NIST CSF 2.0; ABD federal hükümeti eseri). Dosyalar `scripts/build_standards.py` ile NIST OSCAL kaynaklarından
  üretilir; kaynak adresi ve SHA-256 özeti pakette ve standart kaydında saklanır.
- Kurulum ve güncelleme aynı işlemdir: madde metni, rehber ve değerlendirme alanları güncellenir; kurumun girdiği
  uygulanabilirlik bildirimi (uygulanabilir, gerekçe) ve eşlemeler korunur. Paketten çıkan madde silinmez.
- Telifli standartlar (ISO, TS EN, PCI DSS, CIS) pakete konmaz; kurum lisanslı kopyasını Excel/CSV veya aynı JSON
  biçimiyle içe aktarır (`POST /standards/import`).

Madde ilişkileri (`clause_links`)
- Küme ilişkisi (NIST IR 8477): equivalent, subset (from ⊂ to), superset, intersects, related. İlişki yönsüzdür;
  karşı taraftan bakınca subset ↔ superset döner. Aynı çift için tek kayıt tutulur.
- Etki: bir maddede bulgu varsa eşdeğer maddeler ve onu kapsayan (subset ilişkisinde "to") maddeler kesin etkilenir;
  kesişen, alt kümesi olan ve ilgili maddeler olası etkidir. Kesin zincir en çok 3 adım izlenir.
- Ortak kontrol: aynı kontrole eşlenen maddeler tek testle güvence alır (ortak kontrol çerçevesi). Bulgu bir
  kontrole bağlıysa kontrolün eşlendiği tüm maddeler doğrudan etkilenir.

Entegre denetim
- Kapsamdaki maddeler kontrol başına gruplanır: her kontrol bir kez test edilir, bir kez kanıt istenir ve sonuç
  eşlendiği tüm maddelere (tüm standartlarda) sayılır. Kontrolü olmayan maddeler, aralarındaki ilişkilere göre soru
  gruplarına ayrılır; grup tek tıkla ortak kontrole dönüştürülür.
"""
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from .. import audit, auth as authz, crud
from ..db import fold, one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY, Raw
from ..schema import RESOURCES

LIBRARY_DIR = Path(__file__).resolve().parent.parent / "data" / "standards"
FORMAT = "tedarik-standard/1"
RELATIONS = ("equivalent", "subset", "superset", "intersects", "related")
INVERSE = {"subset": "superset", "superset": "subset"}
IMPACT = {"equivalent": "certain", "subset": "certain", "superset": "possible", "intersects": "possible",
          "related": "related"}
LEVEL_ORDER = {"direct": 0, "certain": 1, "possible": 2, "related": 3}
RELATION_LABELS = {"equivalent": "Eşdeğer", "subset": "Alt küme", "superset": "Üst küme", "intersects": "Kesişir",
                   "related": "İlgili"}
GROUPING = ("equivalent", "subset", "superset", "intersects")       # entegre denetimde aynı soru grubu
MAX_PACKAGE = 64 * 1024 * 1024
MAX_CLAUSES = 20000
TEXT_FIELDS = ("title", "clause_type", "description", "guidance", "assessment", "tags", "position")
STOP = set("""a an and are as at be by for from has have in is it its of on or that the their this to with within
which when where shall should must may can any all such other into than then these those been being not
ve ile bir bu için olan veya da de ya ise gibi her olarak tarafından ilgili göre kadar daha en çok""".split())

_cache = {}


# ------------------------------------------------------------------ paketler

def _read_package(path):
    stamp = path.stat().st_mtime_ns
    cached = _cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    with gzip.open(path, "rb") as fh:
        data = fh.read(MAX_PACKAGE + 1)
    if len(data) > MAX_PACKAGE:
        raise crud.Invalid("Standart paketi çok büyük")
    package = validate_package(json.loads(data.decode("utf-8")))
    _cache[path] = (stamp, package)
    return package


def validate_package(package):
    """Paket biçimini denetler (kütüphane dosyası veya kurumun yüklediği JSON)."""
    if not isinstance(package, dict) or package.get("format") != FORMAT:
        raise crud.Invalid(f"Paket biçimi '{FORMAT}' olmalı")
    for key in ("code", "name"):
        if not isinstance(package.get(key), str) or not package[key].strip():
            raise crud.Invalid(f"Pakette '{key}' gerekli")
    clauses = package.get("clauses")
    if not isinstance(clauses, list) or not clauses or len(clauses) > MAX_CLAUSES:
        raise crud.Invalid(f"Pakette 1–{MAX_CLAUSES} madde olmalı")
    codes = set()
    for i, cl in enumerate(clauses, 1):
        if not isinstance(cl, dict) or not str(cl.get("code") or "").strip() or not str(cl.get("title") or "").strip():
            raise crud.Invalid(f"{i}. maddede kod ve başlık gerekli")
        if cl["code"] in codes:
            raise crud.Invalid(f"Madde kodu tekrar ediyor: {cl['code']}")
        codes.add(cl["code"])
        if cl.get("type") and cl["type"] not in RESOURCES["clauses"].enums["clause_type"]:
            raise crud.Invalid(f"{cl['code']}: tanımsız madde türü '{cl['type']}'")
    for cl in clauses:
        if cl.get("parent") and cl["parent"] not in codes:
            raise crud.Invalid(f"{cl['code']}: üst madde '{cl['parent']}' pakette yok")
    for link in package.get("links") or ():
        if link.get("from") not in codes or link.get("to") not in codes or link.get("relation") not in RELATIONS:
            raise crud.Invalid(f"Geçersiz madde ilişkisi: {link}")
    return package


def packages():
    return [(p.name.split(".")[0], _read_package(p)) for p in sorted(LIBRARY_DIR.glob("*.json.gz"))]


def _installed(db, package):
    return one(db, "SELECT * FROM tdr_standards WHERE code=? AND COALESCE(version,'')=?",
               (package["code"], package.get("version") or ""))


def library(c):
    authz.check(c.principal, RESOURCES["standards"], "read")
    out = []
    for name, pkg in packages():
        std = _installed(c.db, pkg)
        count = one(c.db, "SELECT COUNT(*) AS n FROM tdr_clauses WHERE standard_id=?", (std["id"],))["n"] if std else 0
        out.append({"key": pkg.get("key") or name, "code": pkg["code"], "name": pkg["name"],
                    "version": pkg.get("version"), "issuer": pkg.get("issuer"), "license": pkg.get("license"),
                    "description": pkg.get("description"), "published": pkg.get("published"),
                    "language": pkg.get("language"), "clauses": len(pkg["clauses"]), "links": len(pkg.get("links") or ()),
                    "sources": pkg.get("sources") or [],
                    "installed": {"standard_id": std["id"], "clauses": count, "installed_at": std["installed_at"],
                                  "current": std["source_sha256"] == _digest(pkg)} if std else None})
    standards = rows(c.db, """SELECT s.id, s.code, s.name, s.version, s.issuer, s.active, s.library_key, s.license,
        s.installed_at, (SELECT COUNT(*) FROM tdr_clauses cl WHERE cl.standard_id=s.id) AS clauses,
        (SELECT COUNT(DISTINCT m.clause_id) FROM tdr_control_clauses m JOIN tdr_clauses cl ON cl.id=m.clause_id
          WHERE cl.standard_id=s.id) AS mapped,
        (SELECT COUNT(*) FROM tdr_clause_links l JOIN tdr_clauses a ON a.id=l.from_clause_id
          JOIN tdr_clauses b ON b.id=l.to_clause_id WHERE l.active=1 AND a.standard_id<>b.standard_id
          AND (a.standard_id=s.id OR b.standard_id=s.id)) AS cross_links
        FROM tdr_standards s ORDER BY s.code, s.version""")
    return {"packages": out, "standards": standards,
            "unavailable": [
                {"name": "ISO/IEC 27001, 27017, 27701, 20000-1; ISO 9001, 14001, 22301, 45001, 50001, 10002",
                 "reason": "ISO telif hakkı; tam metin yalnızca lisanslı kopyadan içe aktarılabilir."},
                {"name": "TS EN 50600", "reason": "TSE/CENELEC telif hakkı; lisanslı kopyadan içe aktarılabilir."},
                {"name": "PCI DSS v4.0.1", "reason": "PCI SSC lisansı; dağıtımı sözleşmeye bağlı."},
                {"name": "CIS Controls v8.1", "reason": "CIS lisansı (kayıtla indirilir); kurum kopyasından içe aktarılabilir."}]}


def _digest(package):
    sources = package.get("sources") or []
    return sources[0].get("sha256") if sources else None


def install_package(db, package, principal, library_key=None, link_source="official", active=0):
    """Standardı ve maddelerini kurar veya günceller. Dönüş: özet sözlüğü.

    Kütüphaneden ilk kurulan standart başvuru amaçlıdır (active=0): uyum panosu ve sağlık kontrolü onu saymaz;
    kurum standardı kapsamına aldığında (active=1) sayılır. Güncelleme bu kararı değiştirmez."""
    validate_package(package)
    db.lock("standards-library")
    std = _installed(db, package)
    first = (package.get("sources") or [{}])[0]
    meta = {"name": package["name"][:300], "issuer": package.get("issuer"), "description": package.get("description"),
            "license": package.get("license"), "language": package.get("language"),
            "source_url": first.get("url"), "source_sha256": first.get("sha256"),
            "published": package.get("published") or None, "library_key": library_key, "installed_at": utcnow()}
    if std is None:
        sid = crud.insert(db, RESOURCES["standards"], {"code": package["code"], "version": package.get("version"),
                                                       "active": active, **meta}, principal)
    else:
        sid = std["id"]
        sets = ", ".join(f"{k}=?" for k in meta)
        db.execute(f"UPDATE tdr_standards SET {sets}, updated_at=? WHERE id=?", (*meta.values(), utcnow(), sid))
    existing = {r["code"]: r for r in rows(db, "SELECT * FROM tdr_clauses WHERE standard_id=?", (sid,))}
    created = updated = unchanged = 0
    for position, cl in enumerate(package["clauses"], 1):
        values = {"title": str(cl["title"]).strip(), "clause_type": cl.get("type") or None,
                  "description": cl.get("text") or None, "guidance": cl.get("guidance") or None,
                  "assessment": cl.get("assessment") or None, "tags": cl.get("tags") or None, "position": position}
        current = existing.get(cl["code"])
        if current is None:
            extra = {}
            if "applicable" in cl:
                extra = {"applicable": 1 if cl["applicable"] else 0, "justification": cl.get("justification")}
            cols = {"standard_id": sid, "code": cl["code"], **values, **extra}
            db.execute(f"INSERT INTO tdr_clauses ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                       tuple(cols.values()))
            created += 1
        elif any((current.get(k) or None) != (v or None) for k, v in values.items()):
            db.execute("UPDATE tdr_clauses SET " + ", ".join(f"{k}=?" for k in values) + " WHERE id=?",
                       (*values.values(), current["id"]))
            updated += 1
        else:
            unchanged += 1
    ids = {r["code"]: r["id"] for r in rows(db, "SELECT id, code FROM tdr_clauses WHERE standard_id=?", (sid,))}
    parents = {r["id"]: r["parent_id"] for r in rows(db, "SELECT id, parent_id FROM tdr_clauses WHERE standard_id=?", (sid,))}
    for cl in package["clauses"]:
        want = ids.get(cl.get("parent")) if cl.get("parent") else None
        if parents.get(ids[cl["code"]]) != want:
            db.execute("UPDATE tdr_clauses SET parent_id=? WHERE id=?", (want, ids[cl["code"]]))
    pairs = {(r["from_clause_id"], r["to_clause_id"]) for r in rows(db, """SELECT l.from_clause_id, l.to_clause_id
        FROM tdr_clause_links l JOIN tdr_clauses a ON a.id=l.from_clause_id WHERE a.standard_id=?""", (sid,))}
    links = 0
    now, actor = utcnow(), principal.username if principal else "system"
    for link in package.get("links") or ():
        a, b = ids[link["from"]], ids[link["to"]]
        if a == b or (a, b) in pairs or (b, a) in pairs:
            continue
        db.execute("INSERT INTO tdr_clause_links (from_clause_id, to_clause_id, relation, source, rationale, active, "
                   "created_by, created_at) VALUES (?,?,?,?,?,1,?,?)",
                   (a, b, link["relation"], link_source, link.get("rationale"), actor, now))
        pairs.add((a, b))
        links += 1
    kept = len(set(existing) - {cl["code"] for cl in package["clauses"]})
    summary = {"standard_id": sid, "code": package["code"], "version": package.get("version"), "created": created,
               "updated": updated, "unchanged": unchanged, "links": links, "kept_outside_package": kept}
    if principal is not None:
        audit.log(db, principal, "INSTALL", "standards", sid, summary, description=f"{package['code']} kuruldu/güncellendi")
    return summary


def install_route(c):
    authz.require_human(c.principal)
    authz.check(c.principal, RESOURCES["standards"], "write")
    key = c.body.get("key")
    found = next((pkg for name, pkg in packages() if key in (name, pkg.get("key"))), None)
    if found is None:
        raise crud.NotFound("Kütüphanede bu standart yok")
    return 201, install_package(c.db, found, c.principal, library_key=found.get("key"))


# ------------------------------------------------------------------ lisanslı metin içe aktarımı

IMPORT_COLUMNS = {   # sütun -> kabul edilen başlıklar (Türkçe karakter ve büyük/küçük harf önemsiz)
    "code": ("madde kodu", "kod", "code", "clause", "madde no", "no"),
    "title": ("baslik", "title", "madde basligi", "ad"),
    "parent": ("ust madde", "ust madde kodu", "parent"),
    "text": ("metin", "madde metni", "text", "description", "aciklama", "gereksinim"),
    "guidance": ("rehber", "guidance", "uygulama rehberi"),
    "assessment": ("degerlendirme", "assessment", "denetim sorusu", "denetim yontemi"),
    "type": ("tur", "type", "madde turu"),
    "tags": ("etiketler", "tags", "etiket"),
    "applicable": ("uygulanabilir", "applicable"),
    "justification": ("gerekce", "justification", "uygulanabilirlik gerekcesi"),
}
LINK_COLUMNS = {
    "from_standard": ("kaynak standart", "source standard", "standart a"),
    "from_clause": ("kaynak madde", "source clause", "madde a"),
    "to_standard": ("hedef standart", "target standard", "standart b"),
    "to_clause": ("hedef madde", "target clause", "madde b"),
    "relation": ("iliski", "relation", "iliski turu"),
    "rationale": ("gerekce", "rationale", "aciklama", "not"),
}
TYPE_LABELS = {"aile": "family", "kontrol": "control", "iyilestirme": "enhancement", "islev": "function",
               "kategori": "category", "alt kategori": "subcategory", "madde": "clause", "ek": "annex",
               "ek a": "annex", "gereksinim": "requirement", "mevzuat maddesi": "article"}
RELATION_INPUT = {"esdeger": "equivalent", "esit": "equivalent", "alt kume": "subset", "ust kume": "superset",
                  "kesisir": "intersects", "kesisim": "intersects", "ilgili": "related", "equal": "equivalent"}


def _key(text):
    return " ".join(fold(str(text or "")).replace("*", " ").split())


def _columns(headers, spec):
    lookup = {_key(alias): name for name, aliases in spec.items() for alias in (name, *aliases)}
    return {h: lookup[_key(h)] for h in headers if _key(h) in lookup}


def _table(c):
    from .transfer import read_table, _decode
    filename, raw = _decode(c)
    if filename.lower().endswith(".json"):
        try:
            return filename, json.loads(raw.decode("utf-8")), None
        except (UnicodeDecodeError, ValueError):
            raise crud.Invalid("JSON dosyası okunamadı") from None
    headers, records = read_table(filename, raw)
    if len(records) > MAX_CLAUSES:
        raise crud.Invalid(f"Tek seferde en fazla {MAX_CLAUSES} satır aktarılabilir")
    return filename, headers, records


def _bool(text):
    t = _key(text)
    if t in ("1", "evet", "e", "true", "yes", "uygulanabilir", "var"):
        return True
    if t in ("0", "hayir", "h", "false", "no", "kapsam disi", "yok"):
        return False
    raise crud.Invalid(f"Uygulanabilir alanı evet/hayır olmalı: '{text}'")


def import_standard(c):
    """Kurumun lisanslı standart metnini (ISO, TS EN, PCI DSS, CIS...) içe aktarır. Excel/CSV veya paket JSON."""
    authz.require_human(c.principal)
    authz.check(c.principal, RESOURCES["standards"], "write")
    filename, headers, records = _table(c)
    if records is None:                       # JSON paket
        package = headers
    else:
        info = c.body.get("standard") or {}
        if not str(info.get("code") or "").strip() or not str(info.get("name") or "").strip():
            raise crud.Invalid("Standart kodu ve adı gerekli")
        mapping = _columns(headers, IMPORT_COLUMNS)
        missing = [label for name, label in (("code", "Madde kodu"), ("title", "Başlık")) if name not in mapping.values()]
        if missing:
            raise crud.Invalid("Zorunlu sütun bulunamadı: " + ", ".join(missing))
        clauses, problems = [], []
        for row_no, record in enumerate(records, 2):
            item = {mapping[h]: str(v).strip() for h, v in record.items() if h in mapping and str(v or "").strip()}
            if not item:
                continue
            try:
                if item.get("type"):
                    t = _key(item["type"])
                    item["type"] = TYPE_LABELS.get(t, t)
                if "applicable" in item:
                    item["applicable"] = _bool(item["applicable"])
                    if not item["applicable"] and not item.get("justification"):
                        raise crud.Invalid("uygulanabilir olmayan madde gerekçe ister")
                clauses.append(item)
            except crud.Invalid as exc:
                problems.append(f"{row_no}. satır: {exc}")
        if problems:
            raise crud.Invalid("; ".join(problems[:20]))
        package = {"format": FORMAT, "code": str(info["code"]).strip(), "name": str(info["name"]).strip(),
                   "version": str(info.get("version") or "").strip() or None, "issuer": info.get("issuer"),
                   "license": info.get("license") or "Kurum lisanslı kopyası (içe aktarım)",
                   "description": info.get("description"), "clauses": clauses, "links": []}
    package = validate_package(package)
    dry_run = bool(c.body.get("dry_run"))
    if dry_run:
        std = _installed(c.db, package)
        existing = {r["code"] for r in rows(c.db, "SELECT code FROM tdr_clauses WHERE standard_id=?", (std["id"],))} \
            if std else set()
        new = sum(1 for cl in package["clauses"] if cl["code"] not in existing)
        return 200, {"dry_run": True, "code": package["code"], "version": package.get("version"),
                     "standard_exists": std is not None, "clauses": len(package["clauses"]), "created": new,
                     "updated_or_unchanged": len(package["clauses"]) - new, "links": len(package.get("links") or ())}
    summary = install_package(c.db, package, c.principal, library_key=None, link_source="crosswalk", active=1)
    return 201, {"dry_run": False, "filename": filename, **summary}


def _standard_by_text(db, text, cache):
    key = _key(text)
    if key in cache:
        return cache[key]
    found = None
    for s in rows(db, "SELECT id, code, name, version, active FROM tdr_standards ORDER BY active DESC, id DESC"):
        names = {_key(s["code"]), _key(s["name"]), _key(f"{s['code']} {s['version'] or ''}"),
                 _key(f"{s['code']}:{s['version'] or ''}")}
        if key in names:
            found = s
            break
    cache[key] = found
    return found


def _clause_by_code(db, standard_id, code):
    c = _key(code).replace(" ", "")
    bare = re.sub(r"^[a-z]{1,3}\.", "", c)
    return one(db, """SELECT id, code FROM tdr_clauses WHERE standard_id=? AND
        (REPLACE(tdr_fold(code),' ','')=? OR REPLACE(tdr_fold(code),' ','')=? OR REPLACE(tdr_fold(code),' ','')=?)
        ORDER BY id LIMIT 1""", (standard_id, c, bare, "a." + bare))


def find_link(db, a, b):
    return one(db, "SELECT * FROM tdr_clause_links WHERE (from_clause_id=? AND to_clause_id=?) OR "
                   "(from_clause_id=? AND to_clause_id=?)", (a, b, b, a))


def import_links(c):
    """Çapraz eşleme tablosu (kaynak standart/madde → hedef standart/madde, ilişki, gerekçe)."""
    authz.require_human(c.principal)
    authz.check(c.principal, RESOURCES["clause_links"], "write")
    filename, headers, records = _table(c)
    if records is None:
        raise crud.Invalid("Çapraz eşleme için Excel veya CSV dosyası yükleyin")
    mapping = _columns(headers, LINK_COLUMNS)
    need = {"from_standard": "Kaynak standart", "from_clause": "Kaynak madde", "to_standard": "Hedef standart",
            "to_clause": "Hedef madde"}
    missing = [label for name, label in need.items() if name not in mapping.values()]
    if missing:
        raise crud.Invalid("Zorunlu sütun bulunamadı: " + ", ".join(missing))
    dry_run = bool(c.body.get("dry_run"))
    c.db.lock("clause-links-import")
    cache, results, summary = {}, [], Counter()
    for row_no, record in enumerate(records, 2):
        item = {mapping[h]: str(v or "").strip() for h, v in record.items() if h in mapping}
        if not any(item.values()):
            continue
        try:
            ends = []
            for side in ("from", "to"):
                std = _standard_by_text(c.db, item.get(side + "_standard"), cache)
                if not std:
                    raise crud.Invalid(f"Standart bulunamadı: '{item.get(side + '_standard')}'")
                cl = _clause_by_code(c.db, std["id"], item.get(side + "_clause"))
                if not cl:
                    raise crud.Invalid(f"{std['code']} içinde '{item.get(side + '_clause')}' maddesi yok")
                ends.append(cl["id"])
            if ends[0] == ends[1]:
                raise crud.Invalid("Bir madde kendisiyle ilişkilendirilemez")
            rel = _key(item.get("relation") or "intersects")
            relation = RELATION_INPUT.get(rel, rel)
            if relation not in RELATIONS:
                raise crud.Invalid(f"İlişki türü tanımsız: '{item.get('relation')}' (Eşdeğer, Alt küme, Üst küme, "
                                   "Kesişir, İlgili)")
            existing = find_link(c.db, *ends)
            if existing:
                if existing["source"] == "official":
                    action = "skip"
                else:
                    stored = existing["relation"] if existing["from_clause_id"] == ends[0] else \
                        INVERSE.get(existing["relation"], existing["relation"])
                    action = "skip" if stored == relation and existing["active"] else "update"
                    if action == "update" and not dry_run:
                        rel_db = relation if existing["from_clause_id"] == ends[0] else INVERSE.get(relation, relation)
                        c.db.execute("UPDATE tdr_clause_links SET relation=?, rationale=COALESCE(?, rationale), "
                                     "active=1, updated_at=? WHERE id=?",
                                     (rel_db, item.get("rationale") or None, utcnow(), existing["id"]))
            else:
                action = "create"
                if not dry_run:
                    c.db.execute("INSERT INTO tdr_clause_links (from_clause_id, to_clause_id, relation, source, "
                                 "rationale, active, created_by, created_at) VALUES (?,?,?,?,?,1,?,?)",
                                 (ends[0], ends[1], relation, "crosswalk", item.get("rationale") or None,
                                  c.principal.username, utcnow()))
            results.append({"row_no": row_no, "action": action})
        except crud.Invalid as exc:
            action = "error"
            results.append({"row_no": row_no, "action": action, "message": str(exc)})
        summary[action] += 1
        summary["total"] += 1
    out = {"dry_run": dry_run, "filename": filename, **dict(summary), "rows": results[:500]}
    if not dry_run:
        audit.log(c.db, c.principal, "IMPORT", "clause_links", None, dict(summary), description=filename)
    return 201, out


def template(c):
    authz.check(c.principal, RESOURCES["standards"], "read")
    kind = c.query.get("kind", "standard")
    if kind == "links":
        lines = ["Kaynak standart;Kaynak madde;Hedef standart;Hedef madde;İlişki;Gerekçe",
                 "NIST CSF;PR.AA-05;NIST SP 800-53;AC-6;Kesişir;Örnek satır: erişim izinleri en az yetki ilkesiyle"]
        name = "capraz-esleme-sablonu.csv"
    else:
        lines = ["Madde kodu;Başlık;Üst madde;Tür;Metin;Rehber;Değerlendirme;Etiketler;Uygulanabilir;Gerekçe",
                 "5;Örnek bölüm;;Madde;;;;;Evet;",
                 "5.1;Örnek madde başlığı;5;Madde;Lisanslı kopyadaki madde metni;;Denetçinin soracağı soru;;Evet;"]
        name = "standart-metni-sablonu.csv"
    return Raw(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"), "text/csv; charset=utf-8", name)


# ------------------------------------------------------------------ ilişki sorguları

def _in(ids):
    return ",".join("?" * len(ids)) if ids else "NULL"


def _clause_rows(db, ids):
    ids = sorted(set(ids))
    if not ids:
        return {}
    return {r["id"]: r for r in rows(db, f"""SELECT cl.id, cl.code, cl.title, cl.applicable, cl.standard_id,
        cl.clause_type, s.code AS standard_code, s.version AS standard_version FROM tdr_clauses cl
        JOIN tdr_standards s ON s.id=cl.standard_id WHERE cl.id IN ({_in(ids)})""", ids)}


def links_of(db, clause_ids):
    """Etkin ilişkiler, verilen maddenin bakış açısından: (madde, diğer madde, ilişki, kayıt)."""
    ids = sorted(set(clause_ids))
    if not ids:
        return []
    out = []
    for r in rows(db, f"""SELECT * FROM tdr_clause_links WHERE active=1 AND
            (from_clause_id IN ({_in(ids)}) OR to_clause_id IN ({_in(ids)}))""", ids + ids):
        if r["from_clause_id"] in ids:
            out.append((r["from_clause_id"], r["to_clause_id"], r["relation"], r))
        if r["to_clause_id"] in ids:
            out.append((r["to_clause_id"], r["from_clause_id"], INVERSE.get(r["relation"], r["relation"]), r))
    return out


def control_map(db, clause_ids=None, control_ids=None):
    """Kontrol ↔ madde eşlemeleri: ({kontrol: {madde}}, {madde: {kontrol}})."""
    sql, args = "SELECT control_id, clause_id FROM tdr_control_clauses WHERE 1=1", []
    if clause_ids is not None:
        ids = sorted(set(clause_ids))
        sql += f" AND clause_id IN ({_in(ids)})"
        args += ids
    if control_ids is not None:
        ids = sorted(set(control_ids))
        sql += f" AND control_id IN ({_in(ids)})"
        args += ids
    by_control, by_clause = defaultdict(set), defaultdict(set)
    for r in rows(db, sql, args):
        by_control[r["control_id"]].add(r["clause_id"])
        by_clause[r["clause_id"]].add(r["control_id"])
    return by_control, by_clause


def _controls(db, ids):
    ids = sorted(set(ids))
    return {r["id"]: r for r in rows(db, f"SELECT id, code, name FROM tdr_controls WHERE id IN ({_in(ids)})", ids)} \
        if ids else {}


def impact(db, clause_ids=(), control_id=None):
    """Bir bulgunun (madde ve/veya kontrol) etkilediği maddeler. Dönüş: {madde: (seviye, [gerekçeler])}."""
    found = {}

    def add(cid, level, reason):
        current = found.get(cid)
        if current is None or LEVEL_ORDER[level] < LEVEL_ORDER[current[0]]:
            found[cid] = (level, [reason])
        elif level == current[0] and reason not in current[1]:
            current[1].append(reason)

    for cid in clause_ids:
        if cid:
            add(cid, "direct", "Bulgunun maddesi")
    if control_id:
        ctl = _controls(db, [control_id]).get(control_id)
        by_control, _ = control_map(db, control_ids=[control_id])
        for cid in by_control.get(control_id, ()):
            add(cid, "direct", f"{ctl['code'] if ctl else 'Kontrol'} kontrolünün eşlendiği madde")
    frontier = [cid for cid, (level, _) in found.items()]
    visited = set(frontier)
    for _depth in range(3):                                   # kesin zincir: eşdeğer ve kapsayan maddeler
        nxt = []
        for cid, other, relation, _row in links_of(db, frontier):
            level = IMPACT[relation]
            if found.get(cid, ("possible",))[0] not in ("direct", "certain"):
                level = "possible" if level == "certain" else level
            add(other, level, f"{RELATION_LABELS[relation]} ilişki")
            if level == "certain" and other not in visited:
                visited.add(other)
                nxt.append(other)
        frontier = nxt
        if not frontier:
            break
    if not control_id:                                        # ortak kontrol: aynı kontrole eşli diğer maddeler
        direct = [cid for cid, (level, _) in found.items() if level == "direct"]
        _, by_clause = control_map(db, clause_ids=direct)
        controls = {k for cid in direct for k in by_clause.get(cid, ())}
        if controls:
            names = _controls(db, controls)
            by_control, _ = control_map(db, control_ids=controls)
            for k, cids in by_control.items():
                for cid in cids:
                    add(cid, "possible", f"Ortak kontrol {names[k]['code']}")
    return found


def grouped(db, found, exclude=()):
    info = _clause_rows(db, found)
    groups = {}
    for cid, (level, reasons) in found.items():
        if cid in exclude or cid not in info:
            continue
        cl = info[cid]
        key = cl["standard_id"]
        g = groups.setdefault(key, {"standard_id": key, "standard": f"{cl['standard_code']} {cl['standard_version'] or ''}".strip(),
                                    "clauses": []})
        g["clauses"].append({"id": cid, "code": cl["code"], "title": cl["title"], "applicable": cl["applicable"],
                             "level": level, "reasons": reasons[:4]})
    for g in groups.values():
        g["clauses"].sort(key=lambda x: (LEVEL_ORDER[x["level"]], x["code"]))
    return sorted(groups.values(), key=lambda g: g["standard"])


def finding_impact_data(db, finding):
    found = impact(db, [finding.get("clause_id")], finding.get("control_id"))
    groups = grouped(db, found)
    counts = Counter(level for level, _ in found.values())
    return {"groups": groups, "counts": {"direct": counts["direct"], "certain": counts["certain"],
                                         "possible": counts["possible"], "related": counts["related"]},
            "standards": len(groups)}


def finding_impact(c):
    authz.check(c.principal, RESOURCES["findings"], "read")
    finding = crud.get(c.db, RESOURCES["findings"], c.params["id"])
    if not RESOURCES["findings"].can_read(c.principal, finding):
        raise crud.NotFound("Bulgu bulunamadı")
    return finding_impact_data(c.db, finding)


def findings_for_clause(db, clause_id):
    """Bu maddeyi doğrudan veya ilişki/ortak kontrol üzerinden etkileyen açık bulgular."""
    near = {clause_id}
    frontier = [clause_id]
    for depth in range(3):        # ilk adım her ilişki; sonrası yalnızca kesin zinciri taşıyabilen ilişkiler
        nxt = [other for _cid, other, rel, _r in links_of(db, frontier)
               if other not in near and (depth == 0 or rel in ("equivalent", "subset", "superset"))]
        near.update(nxt)
        frontier = nxt
        if not frontier:
            break
    _, by_clause = control_map(db, clause_ids=near)
    controls = {k for cid in near for k in by_clause.get(cid, ())}
    candidates = rows(db, f"""SELECT id, code, title, severity, status, clause_id, control_id, audit_id
        FROM tdr_findings WHERE status IN ('open','in_progress') AND (clause_id IN ({_in(sorted(near))})
        OR control_id IN ({_in(sorted(controls))})) ORDER BY id DESC LIMIT 200""", sorted(near) + sorted(controls))
    out = []
    for f in candidates:
        found = impact(db, [f["clause_id"]], f["control_id"]).get(clause_id)
        if found:
            out.append({**f, "level": found[0], "reasons": found[1][:3]})
    out.sort(key=lambda f: (LEVEL_ORDER[f["level"]], -f["id"]))
    return out


def clause_relations(db, clause_id):
    links = []
    info = None
    pairs = links_of(db, [clause_id])
    info = _clause_rows(db, [other for _c, other, _r, _row in pairs])
    for _cid, other, relation, row in pairs:
        cl = info.get(other)
        if cl:
            links.append({"link_id": row["id"], "clause_id": other, "code": cl["code"], "title": cl["title"],
                          "standard": f"{cl['standard_code']} {cl['standard_version'] or ''}".strip(),
                          "standard_id": cl["standard_id"], "relation": relation, "impact": IMPACT[relation],
                          "source": row["source"], "rationale": row["rationale"]})
    links.sort(key=lambda x: (x["standard"], LEVEL_ORDER[x["impact"]], x["code"]))
    _, by_clause = control_map(db, clause_ids=[clause_id])
    shared = []
    mine = by_clause.get(clause_id, set())
    if mine:
        by_control, _ = control_map(db, control_ids=mine)
        names = _controls(db, mine)
        others = _clause_rows(db, {cid for k in mine for cid in by_control[k]} - {clause_id})
        for cid, cl in others.items():
            via = sorted(names[k]["code"] for k in mine if cid in by_control[k])
            shared.append({"clause_id": cid, "code": cl["code"], "title": cl["title"],
                           "standard": f"{cl['standard_code']} {cl['standard_version'] or ''}".strip(),
                           "standard_id": cl["standard_id"], "controls": via})
        shared.sort(key=lambda x: (x["standard"], x["code"]))
    return {"links": links, "shared": shared, "findings": findings_for_clause(db, clause_id)}


def relations_route(c):
    authz.check(c.principal, RESOURCES["clauses"], "read")
    crud.get(c.db, RESOURCES["clauses"], c.params["id"])
    return clause_relations(c.db, c.params["id"])


def link_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    a, b = merged.get("from_clause_id"), merged.get("to_clause_id")
    if current is not None and (data.get("from_clause_id", a) != current["from_clause_id"]
                                or data.get("to_clause_id", b) != current["to_clause_id"]):
        raise crud.Invalid("İlişkinin maddeleri değiştirilemez; yanlış ilişkiyi pasifleştirip yenisini ekleyin")
    if current is None:
        if a == b:
            raise crud.Invalid("Bir madde kendisiyle ilişkilendirilemez")
        if find_link(db, a, b):
            raise crud.Conflict("Bu iki madde arasında zaten bir ilişki var; onu düzenleyin")
        data.setdefault("source", "manual")
        if principal is not None:
            data["created_by"] = principal.username
    if current is not None and current["source"] == "official" and any(
            k in data and data[k] != current[k] for k in ("relation", "source")):
        raise crud.Invalid("Resmî kaynaktan gelen ilişkinin türü değiştirilemez (pasifleştirilebilir)")


# ------------------------------------------------------------------ öneri (metin benzerliği)

def _tokens(text):
    words = re.findall(r"[a-z0-9]{3,}", fold(text or ""))
    return [w[:7] for w in words if w not in STOP and not w.isdigit()]


def _vectors(docs):
    df = Counter()
    tfs = []
    for text in docs:
        tf = Counter(_tokens(text))
        tfs.append(tf)
        df.update(tf.keys())
    n = len(docs) or 1
    idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}
    vectors = []
    for tf in tfs:
        v = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vectors.append({t: x / norm for t, x in v.items()})
    return vectors, idf


def _vector(text, idf):
    tf = Counter(t for t in _tokens(text) if t in idf)
    v = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / norm for t, x in v.items()}


def _cos(a, b):
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(t, 0.0) for t, x in a.items())


def _doc(cl):
    return " ".join(filter(None, [cl["title"], cl["title"], (cl.get("description") or "")[:1500]]))


def suggestions_for(db, clause, target_ids, limit=6, threshold=0.12):
    targets = rows(db, f"""SELECT cl.id, cl.code, cl.title, cl.description, cl.standard_id, cl.clause_type,
        s.code AS standard_code, s.version AS standard_version FROM tdr_clauses cl JOIN tdr_standards s
        ON s.id=cl.standard_id WHERE cl.standard_id IN ({_in(target_ids)}) AND cl.standard_id<>?
        AND COALESCE(cl.clause_type,'') NOT IN ('family','function','category')""", (*target_ids, clause["standard_id"]))
    if not targets:
        return []
    vectors, idf = _vectors([_doc(t) for t in targets])
    source = _vector(_doc(clause), idf)
    linked = {other for _c, other, _r, _row in links_of(db, [clause["id"]])}
    scored = sorted(((round(_cos(source, v), 3), t) for v, t in zip(vectors, targets) if t["id"] not in linked),
                    key=lambda x: -x[0])
    return [{"clause_id": t["id"], "code": t["code"], "title": t["title"], "score": s,
             "standard": f"{t['standard_code']} {t['standard_version'] or ''}".strip(), "standard_id": t["standard_id"]}
            for s, t in scored[:limit] if s >= threshold]


def suggest_route(c):
    authz.check(c.principal, RESOURCES["clauses"], "read")
    clause = crud.get(c.db, RESOURCES["clauses"], c.params["id"])
    target = c.query.get("standard_id")
    if target:
        ids = [int(target)]
    else:
        ids = [r["id"] for r in rows(c.db, "SELECT id FROM tdr_standards WHERE active=1 AND id<>?", (clause["standard_id"],))]
    return {"clause_id": clause["id"], "suggestions": suggestions_for(c.db, clause, ids or [0]),
            "note": "Öneriler metin benzerliğine dayanır; ilişki ancak siz onayladığınızda kaydedilir."}


def crosswalk(c):
    """Eşleme çalışma alanı: kaynak standardın maddeleri, hedef standarttaki mevcut ilişkileri ve öneriler."""
    authz.check(c.principal, RESOURCES["clauses"], "read")
    source = crud.get(c.db, RESOURCES["standards"], c.params["id"])
    try:
        target_id = int(c.query.get("target_id", "0"))
        offset = max(int(c.query.get("offset", "0")), 0)
        limit = min(max(int(c.query.get("limit", "20")), 1), 50)
    except ValueError:
        raise crud.Invalid("target_id, offset ve limit tamsayı olmalı") from None
    target = crud.get(c.db, RESOURCES["standards"], target_id)
    if target["id"] == source["id"]:
        raise crud.Invalid("Hedef standart kaynakla aynı olamaz")
    where = "standard_id=? AND COALESCE(clause_type,'') NOT IN ('family','function','category')"
    args = [source["id"]]
    if c.query.get("q"):
        where += " AND (tdr_fold(code) LIKE ? ESCAPE '\\' OR tdr_fold(title) LIKE ? ESCAPE '\\')"
        pattern = "%" + re.sub(r"([\\%_])", r"\\\1", fold(c.query["q"])) + "%"
        args += [pattern, pattern]
    if c.query.get("unlinked") == "1":
        where += f""" AND id NOT IN (SELECT l.from_clause_id FROM tdr_clause_links l JOIN tdr_clauses t
            ON t.id=l.to_clause_id WHERE l.active=1 AND t.standard_id=?) AND id NOT IN (SELECT l.to_clause_id
            FROM tdr_clause_links l JOIN tdr_clauses t ON t.id=l.from_clause_id WHERE l.active=1 AND t.standard_id=?)"""
        args += [target["id"], target["id"]]
    total = one(c.db, f"SELECT COUNT(*) AS n FROM tdr_clauses WHERE {where}", args)["n"]
    page = rows(c.db, f"SELECT id, code, title, description, standard_id, clause_type FROM tdr_clauses WHERE {where} "
                      f"ORDER BY COALESCE(position, 0), code LIMIT ? OFFSET ?", (*args, limit, offset))
    targets = rows(c.db, """SELECT cl.id, cl.code, cl.title, cl.description, cl.standard_id, cl.clause_type,
        s.code AS standard_code, s.version AS standard_version FROM tdr_clauses cl JOIN tdr_standards s ON
        s.id=cl.standard_id WHERE cl.standard_id=? AND COALESCE(cl.clause_type,'') NOT IN ('family','function','category')""",
                   (target["id"],))
    vectors, idf = _vectors([_doc(t) for t in targets])
    info = {t["id"]: t for t in targets}
    items = []
    for cl in page:
        existing = [{"link_id": row["id"], "clause_id": other, "code": info[other]["code"],
                     "title": info[other]["title"], "relation": rel, "source": row["source"]}
                    for _c, other, rel, row in links_of(c.db, [cl["id"]]) if other in info]
        have = {e["clause_id"] for e in existing}
        src = _vector(_doc(cl), idf)
        scored = sorted(((round(_cos(src, v), 3), t) for v, t in zip(vectors, targets) if t["id"] not in have),
                        key=lambda x: -x[0])[:3]
        items.append({"id": cl["id"], "code": cl["code"], "title": cl["title"], "links": existing,
                      "suggestions": [{"clause_id": t["id"], "code": t["code"], "title": t["title"], "score": s}
                                      for s, t in scored if s >= 0.12]})
    return {"source": {"id": source["id"], "code": source["code"], "version": source["version"]},
            "target": {"id": target["id"], "code": target["code"], "version": target["version"]},
            "total": total, "offset": offset, "limit": limit, "items": items}


# ------------------------------------------------------------------ ağaç ve entegre denetim

def tree(c):
    """Standart tarayıcısı ve madde seçici için tüm maddeler (kısa biçim)."""
    authz.check(c.principal, RESOURCES["clauses"], "read")
    std = crud.get(c.db, RESOURCES["standards"], c.params["id"])
    items = rows(c.db, """SELECT cl.id, cl.code, cl.title, cl.parent_id, cl.clause_type, cl.applicable, cl.tags,
        (SELECT COUNT(*) FROM tdr_control_clauses m WHERE m.clause_id=cl.id) AS controls
        FROM tdr_clauses cl WHERE cl.standard_id=? ORDER BY COALESCE(cl.position, 0), cl.code""", (std["id"],))
    linked = {r["id"] for r in rows(c.db, """SELECT a.id FROM tdr_clauses a JOIN tdr_clause_links l ON
        (l.from_clause_id=a.id OR l.to_clause_id=a.id) JOIN tdr_clauses b ON b.id=(CASE WHEN l.from_clause_id=a.id
        THEN l.to_clause_id ELSE l.from_clause_id END) WHERE a.standard_id=? AND l.active=1 AND b.standard_id<>?""",
                                    (std["id"], std["id"]))}
    for item in items:
        item["cross"] = 1 if item["id"] in linked else 0
    return {"standard": std, "clauses": items}


def _union(groups, a, b):
    ra, rb = _find(groups, a), _find(groups, b)
    if ra != rb:
        groups[rb] = ra


def _find(groups, a):
    while groups[a] != a:
        groups[a] = groups[groups[a]]
        a = groups[a]
    return a


def integrated_data(db, audit_id, principal=None):
    from .grc import evidence_filter
    audit_row = crud.get(db, RESOURCES["audits"], audit_id)
    scope = _clause_rows(db, [r["clause_id"] for r in rows(db, "SELECT clause_id FROM tdr_audit_clauses WHERE audit_id=?",
                                                              (audit_id,))])
    standards = sorted({cl["standard_id"] for cl in scope.values()})
    _, by_clause = control_map(db, clause_ids=scope)
    control_ids = {k for ks in by_clause.values() for k in ks}
    by_control, _ = control_map(db, control_ids=control_ids)
    covered = _clause_rows(db, {cid for k in control_ids for cid in by_control[k]})
    controls = rows(db, f"""SELECT k.id, k.code, k.name, k.method_type, k.method, k.expected_result, k.owner, k.active,
        (SELECT x.status FROM tdr_executions x WHERE x.control_id=k.id AND x.audit_id=? ORDER BY x.executed_at DESC,
         x.id DESC LIMIT 1) AS audit_status
        FROM tdr_controls k WHERE k.id IN ({_in(sorted(control_ids))}) ORDER BY k.code""",
                    (audit_id, *sorted(control_ids)))
    visible, vargs = evidence_filter(principal, "e")
    evidence = Counter(r["control_id"] for r in rows(db, f"""SELECT m.control_id FROM tdr_evidence_controls m
        JOIN tdr_evidence e ON e.id=m.evidence_id WHERE m.control_id IN ({_in(sorted(control_ids))})
        AND e.status='current' AND {visible}""", (*sorted(control_ids), *vargs)))
    tests = []
    for k in controls:
        clauses = [covered[cid] for cid in by_control[k["id"]] if cid in covered]
        in_scope = [cl for cl in clauses if cl["id"] in scope]
        extra = [cl for cl in clauses if cl["id"] not in scope]
        by_std = defaultdict(list)
        for cl in sorted(in_scope, key=lambda x: x["code"]):
            by_std[f"{cl['standard_code']} {cl['standard_version'] or ''}".strip()].append(
                {"id": cl["id"], "code": cl["code"], "title": cl["title"]})
        tests.append({"control": {key: k[key] for key in ("id", "code", "name", "method_type", "method",
                                                          "expected_result", "owner", "active")},
                      "status": k["audit_status"], "evidence": evidence.get(k["id"], 0),
                      "standards": [{"standard": s, "clauses": cls} for s, cls in sorted(by_std.items())],
                      "scope_clauses": len(in_scope),
                      "extra": [{"id": cl["id"], "code": cl["code"], "title": cl["title"],
                                 "standard": f"{cl['standard_code']} {cl['standard_version'] or ''}".strip()}
                                for cl in sorted(extra, key=lambda x: (x["standard_code"], x["code"]))][:30]})
    tests.sort(key=lambda t: (-len(t["standards"]), -t["scope_clauses"], t["control"]["code"]))
    uncovered = [cid for cid in scope if not by_clause.get(cid)]
    parent = {cid: cid for cid in uncovered}
    suggestions = defaultdict(set)
    for cid, other, relation, _row in links_of(db, uncovered):
        if relation not in GROUPING or other not in scope:
            continue
        if other in parent:
            _union(parent, cid, other)
        else:
            for k in by_clause.get(other, ()):
                suggestions[cid].add(k)
    clusters = defaultdict(list)
    for cid in uncovered:
        clusters[_find(parent, cid)].append(cid)
    names = {k["id"]: k for k in controls}
    groups = []
    for members in clusters.values():
        cls = sorted((scope[cid] for cid in members), key=lambda x: (x["standard_code"], x["code"]))
        hints = sorted({k for cid in members for k in suggestions.get(cid, ())})
        groups.append({"clauses": [{"id": cl["id"], "code": cl["code"], "title": cl["title"],
                                    "standard": f"{cl['standard_code']} {cl['standard_version'] or ''}".strip(),
                                    "applicable": cl["applicable"]} for cl in cls],
                       "standards": len({cl["standard_id"] for cl in cls}),
                       "suggested_controls": [{"id": k, "code": names[k]["code"], "name": names[k]["name"]}
                                              for k in hints if k in names]})
    groups.sort(key=lambda g: (-g["standards"], -len(g["clauses"]), g["clauses"][0]["code"]))
    applicable = [cid for cid in scope if scope[cid]["applicable"]]
    questions = len(tests) + len(groups)
    # tekrar sorulmayan madde: bir test (veya soru grubu) birden çok kapsam maddesini karşılıyorsa her ek madde ayrı
    # bir soru ve ayrı bir kanıt olmaktan çıkar
    saved = sum(max(t["scope_clauses"] - 1, 0) for t in tests) + sum(len(g["clauses"]) - 1 for g in groups)
    return {"audit": {"id": audit_row["id"], "code": audit_row["code"], "name": audit_row["name"],
                      "status": audit_row["status"]},
            "summary": {"standards": len(standards), "scope_clauses": len(scope), "applicable": len(applicable),
                        "tests": len(tests), "groups": len(groups), "questions": questions,
                        "covered_clauses": len(scope) - len(uncovered),
                        "saved": saved,
                        "multi_standard_tests": sum(1 for t in tests if len(t["standards"]) > 1)},
            "tests": tests, "groups": groups}


def integrated(c):
    authz.check(c.principal, RESOURCES["audits"], "read")
    authz.require_audit(c.principal, c.params["id"])
    return integrated_data(c.db, c.params["id"], c.principal)


def common_control(c):
    """Soru grubunu (ilişkili maddeler) tek ortak kontrole dönüştürür veya var olan kontrole ekler."""
    authz.require_human(c.principal)
    authz.check(c.principal, RESOURCES["controls"], "write")
    ids = c.body.get("clause_ids")
    if not isinstance(ids, list) or not ids or len(ids) > 200 or any(type(i) is not int for i in ids):
        raise crud.Invalid("clause_ids: madde kimlikleri listesi gerekli")
    ids = sorted(set(ids))
    if len(_clause_rows(c.db, ids)) != len(ids):
        raise crud.Invalid("Bulunamayan madde seçildi")
    control_id = c.body.get("control_id")
    if control_id:
        control = crud.get(c.db, RESOURCES["controls"], control_id)
    else:
        name = str(c.body.get("name") or "").strip()
        if not name:
            raise crud.Invalid("Ortak kontrolün adı gerekli")
        control_id = crud.insert(c.db, RESOURCES["controls"], {
            "name": name[:300], "description": c.body.get("description") or None,
            "method_type": c.body.get("method_type") or "inspection", "frequency": c.body.get("frequency") or "yearly",
            "owner": c.body.get("owner") or None}, c.principal)
        control = crud.get(c.db, RESOURCES["controls"], control_id)
        audit.log(c.db, c.principal, "POST", "controls", control_id, {"name": control["name"], "common": True})
    have = {r["clause_id"] for r in rows(c.db, "SELECT clause_id FROM tdr_control_clauses WHERE control_id=?", (control_id,))}
    added = [cid for cid in ids if cid not in have]
    for cid in added:
        c.db.execute("INSERT INTO tdr_control_clauses (control_id, clause_id) VALUES (?,?)", (control_id, cid))
    audit.log(c.db, c.principal, "LINK", "controls", control_id, {"clauses": {"added": added, "removed": []}})
    return 201, {"control_id": control_id, "code": control["code"], "added": len(added)}


def register(app):
    app.route("GET", API + "/standards/library", library)
    app.route("POST", API + "/standards/library/install", install_route)
    app.route("POST", API + "/standards/import", import_standard, max_body=MAX_UPLOAD_BODY)
    app.route("GET", API + "/standards/import/template", template)
    app.route("POST", API + "/clause_links/import", import_links, max_body=MAX_UPLOAD_BODY)
    app.route("GET", API + "/standards/{id}/tree", tree)
    app.route("GET", API + "/standards/{id}/crosswalk", crosswalk)
    app.route("GET", API + "/clauses/{id}/relations", relations_route)
    app.route("GET", API + "/clauses/{id}/suggestions", suggest_route)
    app.route("GET", API + "/findings/{id}/impact", finding_impact)
    app.route("GET", API + "/audits/{id}/integrated", integrated)
    app.route("POST", API + "/controls/common", common_control)
