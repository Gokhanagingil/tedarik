"""Veri taşıma: motor bağımsız döküm ve boş kuruluma yükleme (K-037).

Kullanım (uygulamanın ortam değişkenleriyle; Docker kurulumunda `docker exec -i tedarik-app-1 ...`):
    python -m tedarik.dataio export - > veri.json.gz          # döküm standart çıktıya (gzip JSON)
    python -m tedarik.dataio import - < veri.json.gz          # yalnızca boş kuruluma

- Döküm kullanıcı hesaplarını ve parolaları içermez: `users` ve oturumlar zaten kaynak tablosu değildir; kullanıcıya bağlı
  rol, birim, erişim süresi ve dış denetçi atamaları, tekrar koruma önbelleği (yanıt gövdeleri), entegrasyon sırları,
  toplayıcı anahtarları ve bildirim kutusu da dışarıda kalır (`EXCLUDE`). Kayıtlardaki kişi alanları (sahip, oluşturan…)
  metin olarak kalır.
- Yükleme yalnızca iş verisi olmayan kuruluma yapılır. Kurulumun açılışta eklediği başlangıç kayıtları (politikalar,
  kategoriler, yol haritası…) dökümdekilerle değiştirilir. Kimlikler korunur, bağlantılar bozulmaz; kendine başvuran
  alanlar (üst süreç, üst madde…) ikinci geçişte yazılır; PostgreSQL kimlik sayaçları en büyük kimliğe getirilir.
  Değiştirilemez bir tabloda başlangıç kaydı varsa (ör. yönetici açılışının denetim izi) ve başka tablo ona başvurmuyorsa
  döküm satırları yeni kimlikle eklenir. Hepsi tek işlemdedir: hata olursa hiçbir şey yazılmaz.
"""
import base64
import gzip
import io
import json
import sys

from . import audit
from .auth import Principal
from .db import one, rows, utcnow
from .schema import RESOURCES

FORMAT = "tedarik.data.v1"
EXCLUDE = {"user_roles", "user_units", "user_access", "user_audits", "idempotency", "integrations", "collector_keys",
           "notifications"}
GUARD = ("suppliers", "supplier_risks", "audits", "controls", "documents", "evidence", "findings", "data_sources",
         "processing_activities", "bias")    # bunlardan birinde kayıt varsa kurulum boş değildir
SYSTEM = Principal("veri-tasima", "ADMIN", "system", "Veri taşıma")


def _tables(app, db):
    from .migrate import _ordered
    chosen = [r for r in RESOURCES.values() if app.enabled(r.module) and r.name not in EXCLUDE]
    return [r for r in _ordered(chosen) if db.columns(r.table)]


def _encode(value):
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return {"$b64": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _decode(value):
    if isinstance(value, dict) and set(value) == {"$b64"}:
        return base64.b64decode(value["$b64"])
    return value


def dump(app):
    """Döküm sözlüğü: biçim, zaman, kaynak motoru, dışarıda kalan tablolar ve tablo başına sütun/satırlar."""
    tables = {}
    with app.database.connect() as db:
        dialect = db.dialect
        for res in _tables(app, db):
            columns = sorted(db.columns(res.table))
            data = rows(db, f"SELECT {', '.join(columns)} FROM {res.table} ORDER BY id")
            tables[res.name] = {"columns": columns, "rows": [[_encode(r[c]) for c in columns] for r in data]}
    return {"format": FORMAT, "created_at": utcnow(), "source_dialect": dialect, "modules": list(app.config.modules),
            "excluded": sorted(EXCLUDE), "tables": tables}


def export(app, stream):
    doc = dump(app)
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as fh:
        fh.write(raw)
    return {name: len(t["rows"]) for name, t in doc["tables"].items()}


def read(stream):
    raw = stream.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict) or doc.get("format") != FORMAT or not isinstance(doc.get("tables"), dict):
        raise SystemExit(f"Döküm biçimi '{FORMAT}' değil")
    return doc


def load(app, doc):
    """Dökümü boş kuruluma yükler. Dönüş: {tablo: satır sayısı} ve atlanan tablolar."""
    leaked = set(doc["tables"]) & EXCLUDE
    if leaked:
        raise SystemExit("Döküm dışarıda kalması gereken tablolar içeriyor: " + ", ".join(sorted(leaked)))
    referenced = {c.ref for r in RESOURCES.values() for c in r.columns.values() if c.ref}
    loaded, skipped = {}, []
    with app.database.connect() as db:
        db.lock("data-import")
        resources = _tables(app, db)
        names = {r.name for r in resources}
        skipped = sorted(set(doc["tables"]) - names)
        busy = [t for t in GUARD if t in names and one(db, f"SELECT 1 AS x FROM {RESOURCES[t].table} LIMIT 1")]
        if busy:
            raise SystemExit("Hedef kurulumda iş verisi var (" + ", ".join(busy) + "); yükleme yalnızca boş kuruluma yapılır")
        append = set()
        for res in reversed(resources):                  # açılışın başlangıç kayıtları dökümdekilerle değişir
            if res.name not in doc["tables"] or not one(db, f"SELECT 1 AS x FROM {res.table} LIMIT 1"):
                continue
            if not res.immutable:
                db.execute(f"DELETE FROM {res.table}")
            elif res.table in referenced:
                raise SystemExit(f"{res.table} değiştirilemez ve dolu; yükleme yalnızca boş kuruluma yapılır")
            else:
                append.add(res.name)
        for res in resources:
            data = doc["tables"].get(res.name)
            if not data or not data["rows"]:
                continue
            have = db.columns(res.table)
            columns = [c for c in data["columns"] if c in have]
            missing = [f for f, col in res.columns.items() if col.required and f not in columns]
            if missing:
                raise SystemExit(f"{res.table}: dökümde zorunlu alan yok ({', '.join(missing)})")
            keep_id = res.name not in append
            if not keep_id:
                columns = [c for c in columns if c != "id"]
            self_ref = [c for c in columns if c in res.columns and res.columns[c].ref == res.table]
            index = {c: i for i, c in enumerate(data["columns"])}
            sql = f"INSERT INTO {res.table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
            later = []
            for row in data["rows"]:
                values = []
                for c in columns:
                    value = _decode(row[index[c]])
                    if c in self_ref and value is not None:
                        later.append((c, value, row[index["id"]]))
                        value = None
                    values.append(value)
                db.execute(sql, values)
            for column, value, record_id in later:
                db.execute(f"UPDATE {res.table} SET {column}=? WHERE id=?", (value, record_id))
            db.reset_identity(res.table)
            loaded[res.name] = len(data["rows"])
        audit.log(db, SYSTEM, "IMPORT", "data", None, {"format": FORMAT, "source_created_at": doc.get("created_at"),
                                                       "tables": len(loaded), "rows": sum(loaded.values()),
                                                       "skipped": skipped})
    return loaded, skipped


def main(argv=None):
    from .config import Config
    from .http import build
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in ("export", "import"):
        raise SystemExit("Kullanım: python -m tedarik.dataio export -|DOSYA  |  import -|DOSYA")
    command, target = argv
    app = build(Config())
    try:
        if command == "export":
            if target == "-":
                counts = export(app, sys.stdout.buffer)
                sys.stdout.buffer.flush()
            else:
                with open(target, "wb") as fh:
                    counts = export(app, fh)
            print(f"Döküm: {len(counts)} tablo, {sum(counts.values())} satır (kullanıcılar ve sırlar hariç)", file=sys.stderr)
        else:
            if target == "-":
                doc = read(io.BytesIO(sys.stdin.buffer.read()))
            else:
                with open(target, "rb") as fh:
                    doc = read(fh)
            loaded, skipped = load(app, doc)
            print(f"Yüklendi: {len(loaded)} tablo, {sum(loaded.values())} satır" +
                  (f"; bu kurulumda olmayan tablolar atlandı: {', '.join(skipped)}" if skipped else ""))
    finally:
        app.close()


if __name__ == "__main__":
    main()
