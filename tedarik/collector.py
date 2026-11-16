"""Katalog toplayıcısı ve bağlayıcı geliştirme kiti (K-030).

Verinin bulunduğu ağda çalışır. Kaynağa salt okunur hesapla bağlanır, yalnızca meta veriyi (şema, tablo, kolon, tip,
açıklama, satır sayısı) okur ve platforma `tedarik.catalog.v1` sözleşmesiyle iter. İsteğe bağlı örnek doğrulamada tablo
başına sınırlı sayıda satır yerelde okunur; değerler gönderilmez, yalnızca doğrulayıcı sayıları gider (K-029).

Python 3.9+ standart kitaplığı yeterlidir. Kaynağın sürücüsü (psycopg, hdbcli, pyodbc, oracledb ...) toplayıcının çalıştığı
makineye kurum tarafından kurulur; platform sürücü içermez. Platform anahtarı ortam değişkeninde veya izinleri kısıtlı bir
dosyada durur, komut satırına yazılmaz. Platform adresi HTTPS olmalıdır (yerel deneme için 127.0.0.1/localhost hariç).

    python tedarik-toplayici.pyz ornek-ayar postgresql > toplayici.json
    python tedarik-toplayici.pyz dene --ayar toplayici.json               # platform ve kaynak bağlantısı
    python tedarik-toplayici.pyz topla --ayar toplayici.json --cikti k.json   # yalnızca dosyaya yazar (gözden geçirme)
    python tedarik-toplayici.pyz gonder --ayar toplayici.json [--on-izleme]
    python tedarik-toplayici.pyz dosya-gonder --ayar toplayici.json disa_aktarim.csv
    python tedarik-toplayici.pyz baglayicilar

Kendi bağlayıcınız (ayrıntı: docs/TOPLAYICI.md):

    from tdr_collector import Connector, connector, table, column

    @connector
    class Envanter(Connector):
        name = "envanter"
        description = "Kurum içi envanter servisi"

        def collect(self):
            yield table("app", "musteri", description="Müşteriler", row_count=1200, columns=[
                column("id", data_type="integer", primary_key=True),
                column("eposta", data_type="varchar", length=200, description="İletişim e-postası")])

    python tedarik-toplayici.pyz gonder --ayar toplayici.json --eklenti envanter.py
"""
import argparse
import base64
import csv
import fnmatch
import gzip
import importlib
import importlib.util
import io
import json
import os
import platform as _platform
import re
import socket
import sqlite3
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:                                   # depodan çalışırken
    from tedarik import pii as _pii
except ImportError:                    # .pyz içinden çalışırken
    import tdr_pii as _pii
try:
    from tedarik import dq_sql as _dq
except ImportError:
    import tdr_dq_sql as _dq

VERSION = "1.0"
FORMAT = "tedarik.catalog.v1"
MAX_PUSH = 13 * 1024 * 1024            # sıkıştırılmış gönderim üst sınırı (base64 ile platformun 18 MB sınırı altında)
CONNECTORS = {}
_STDERR = sys.stderr


class CollectorError(Exception):
    """Kullanıcıya gösterilen hata (Türkçe)."""


# ------------------------------------------------------------------ sözleşme (SDK)

def table(schema, name, *, object_type="table", description=None, row_count=None, columns=()):
    """Bir tablo / görünüm / varlık. object_type: table, view, entity, semantic_model, report, file, collection, other."""
    return {"schema": schema or "", "name": name, "object_type": object_type, "description": description,
            "row_count": row_count, "columns": list(columns)}


def column(name, *, position=None, data_type=None, length=None, scale=None, nullable=None, primary_key=False,
           references=None, description=None):
    """Bir kolon. references: 'şema.tablo.kolon' biçiminde yabancı anahtar hedefi."""
    return {"name": name, "position": position, "data_type": data_type, "length": length, "scale": scale,
            "nullable": nullable, "primary_key": bool(primary_key), "references": references, "description": description}


class Connector:
    """Bağlayıcı sözleşmesi.

    - `collect()` tablo sözlükleri üretir (`table()` ve `column()` yardımcılarıyla).
    - `sample(schema, name, limit)` isteğe bağlıdır: (başlıklar, satırlar) döner; örnek doğrulama için yerelde kullanılır,
      platforma gönderilmez. Desteklemeyen bağlayıcı None döner.
    - `export()` gönderilecek dosyayı (ad, içerik) üretir; varsayılanı `collect()` çıktısını sözleşme JSON'una çevirir.
    - `settings` ayar dosyasındaki "settings" sözlüğüdür; parola ve bağlantı dizesi ortam değişkeninden okunur.
    """
    name = "base"
    description = ""
    options = {}
    dialect = None                       # veri kalitesi SQL lehçesi (dq_sql); None: kurallar Python'da değerlendirilir

    def __init__(self, settings):
        self.settings = dict(settings or {})
        self.tables = []

    def collect(self):
        raise NotImplementedError

    def sample(self, schema, name, limit):
        return None

    def adapt(self, rule):
        """Kural tanımını bağlayıcıya uyarlar (ör. SQLite'ta şema adı yoktur)."""
        return rule

    def query(self, sql, max_rows=1):
        """Veri kalitesi sorgusu: (başlıklar, satırlar). Değerler yalnızca yerelde sayılır, gönderilmez."""
        raise CollectorError(f"{self.name} bağlayıcısı veri kalitesi sorgusu çalıştıramaz; sonucu platformda elle girin")

    def export(self):
        self.tables = list(self.collect())
        payload = {"format": FORMAT, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "connector": self.name, "tables": self.tables}
        return f"{self.name}.json", json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")

    def table_keys(self):
        return [(t["schema"], t["name"], t.get("object_type") or "table") for t in self.tables]

    def close(self):
        pass

    def setting(self, key, default=None, required=False):
        value = self.settings.get(key, default)
        if required and value in (None, ""):
            raise CollectorError(f"{self.name} bağlayıcısı için '{key}' ayarı gerekli")
        return value

    def secret(self, key, default_env):
        """Gizli bağlantı bilgisini ortam değişkeninden okur; ayar dosyası yalnızca değişkenin adını taşır."""
        env = self.settings.get(key) or default_env
        value = os.environ.get(env)
        if not value:
            raise CollectorError(f"{env} ortam değişkeni tanımlı değil ({self.name} bağlantı bilgisi)")
        return value


def connector(cls):
    """Bağlayıcıyı adıyla kaydeder (eklenti dosyalarında da kullanılır)."""
    if not getattr(cls, "name", None) or cls.name == "base":
        raise CollectorError("Bağlayıcının benzersiz bir 'name' değeri olmalı")
    CONNECTORS[cls.name] = cls
    return cls


def _quote(name, char='"'):
    closing = {"[": "]"}.get(char, char)
    return char + str(name).replace(closing, closing * 2) + closing


def _module(name, hint):
    try:
        return importlib.import_module(name)
    except ImportError:
        raise CollectorError(f"'{name}' sürücüsü kurulu değil. {hint}") from None


# ------------------------------------------------------------------ yerleşik bağlayıcılar

@connector
class PostgresConnector(Connector):
    name = "postgresql"
    description = "PostgreSQL ve uyumlular (Aurora, Azure Database for PostgreSQL). psycopg sürücüsü gerekir."
    options = {"dsn_env": "Bağlantı dizesini taşıyan ortam değişkeni (varsayılan TEDARIK_SOURCE_DSN)",
               "schemas": "Yalnızca bu şemalar (liste)", "exclude_schemas": "Hariç şemalar (liste)",
               "row_counts": "İstatistikten tahmini satır sayısı (varsayılan açık)"}

    def connect(self):
        if getattr(self, "conn", None) is None:
            try:
                driver = importlib.import_module("psycopg")
            except ImportError:
                driver = _module("psycopg2", "Kurulum: pip install 'psycopg[binary]'")
            self.conn = driver.connect(self.secret("dsn_env", "TEDARIK_SOURCE_DSN"))
            cur = self.conn.cursor()
            cur.execute("SET default_transaction_read_only = on")
            cur.execute("SET statement_timeout = '60s'")
            self.conn.commit()                    # oturum ayarı kalıcı olsun (geri almada kaybolmasın)
        return self.conn

    def _filters(self):
        where, args = ["n.nspname NOT IN ('pg_catalog', 'information_schema')", "left(n.nspname, 3) <> 'pg_'"], []
        if self.settings.get("schemas"):
            where.append("n.nspname = ANY(%s)")
            args.append(list(self.settings["schemas"]))
        if self.settings.get("exclude_schemas"):
            where.append("NOT (n.nspname = ANY(%s))")
            args.append(list(self.settings["exclude_schemas"]))
        return " AND ".join(where), args

    def collect(self):
        cur = self.connect().cursor()
        where, args = self._filters()
        cur.execute(f"""SELECT n.nspname, c.relname, c.relkind, obj_description(c.oid, 'pg_class'),
                CASE WHEN c.reltuples < 0 OR c.relkind IN ('v') THEN NULL ELSE c.reltuples::bigint END,
                a.attname, a.attnum, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull, col_description(c.oid, a.attnum)
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
            WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND NOT c.relispartition AND {where}
            ORDER BY 1, 2, a.attnum""", args)       # nosec B608 - koşullar sabit, değerler parametreli
        found = {}
        for schema, name, kind, comment, estimate, col, pos, typ, nullable, col_comment in cur.fetchall():
            t = found.get((schema, name))
            if t is None:
                t = found[(schema, name)] = table(schema, name, object_type="view" if kind in ("v", "m") else "table",
                                                  description=comment,
                                                  row_count=estimate if self.settings.get("row_counts", True) else None)
            t["columns"].append(column(col, position=pos, data_type=typ, nullable=nullable, description=col_comment))
        cur.execute(f"""SELECT n.nspname, c.relname, a.attname FROM pg_index i JOIN pg_class c ON c.oid = i.indrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(i.indkey)
            WHERE i.indisprimary AND {where}""", args)    # nosec B608
        keys = {(s, t, c) for s, t, c in cur.fetchall()}
        cur.execute(f"""SELECT n.nspname, c.relname, a.attname, rn.nspname, rc.relname, ra.attname
            FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_class rc ON rc.oid = k.confrelid JOIN pg_namespace rn ON rn.oid = rc.relnamespace
            CROSS JOIN LATERAL unnest(k.conkey, k.confkey) AS u(col, rcol)
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = u.col
            JOIN pg_attribute ra ON ra.attrelid = rc.oid AND ra.attnum = u.rcol
            WHERE k.contype = 'f' AND {where}""", args)   # nosec B608
        refs = {(s, t, c): f"{rs}.{rt}.{rcol}" for s, t, c, rs, rt, rcol in cur.fetchall()}
        self.conn.rollback()
        for (schema, name), t in found.items():
            for col in t["columns"]:
                col["primary_key"] = (schema, name, col["name"]) in keys
                col["references"] = refs.get((schema, name, col["name"]))
            yield t

    def sample(self, schema, name, limit):
        cur = self.connect().cursor()
        cur.execute(f"SELECT * FROM {_quote(schema)}.{_quote(name)} LIMIT %s", (int(limit),))   # nosec B608 - tırnaklı ad
        headers = [d[0] for d in cur.description]
        out = cur.fetchall()
        self.conn.rollback()
        return headers, out

    dialect = "postgres"

    def query(self, sql, max_rows=1):
        cur = self.connect().cursor()
        try:
            cur.execute(sql.replace("%", "%%"), ())
            return [d[0] for d in cur.description], cur.fetchmany(int(max_rows))
        finally:
            self.conn.rollback()

    def close(self):
        if getattr(self, "conn", None) is not None:
            self.conn.close()


@connector
class SqliteConnector(Connector):
    name = "sqlite"
    description = "SQLite veritabanı dosyası (ek paket gerekmez, salt okunur açılır)."
    options = {"path": "Veritabanı dosyası", "schema": "Platformda görünecek şema adı (varsayılan main)",
               "row_counts": "Tam satır sayısı (varsayılan açık)"}

    def connect(self):
        if getattr(self, "conn", None) is None:
            path = Path(self.setting("path", required=True)).expanduser()
            if not path.is_file():
                raise CollectorError(f"SQLite dosyası bulunamadı: {path}")
            self.conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
            self.conn.create_function("REGEXP", 2, lambda p, v: v is not None and re.search(p, str(v)) is not None)
        return self.conn

    def collect(self):
        db = self.connect()
        schema = self.settings.get("schema") or "main"
        for name, kind in db.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') "
                                     "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
            refs = {r[3]: f"{schema}.{r[2]}.{r[4] or 'id'}" for r in db.execute(f"PRAGMA foreign_key_list({_quote(name)})")}
            cols = [column(r[1], position=r[0] + 1, data_type=r[2] or None, nullable=not r[3], primary_key=bool(r[5]),
                           references=refs.get(r[1])) for r in db.execute(f"PRAGMA table_info({_quote(name)})")]
            count = None
            if kind == "table" and self.settings.get("row_counts", True):
                count = db.execute(f"SELECT COUNT(*) FROM {_quote(name)}").fetchone()[0]    # nosec B608 - tırnaklı ad
            yield table(schema, name, object_type=kind, row_count=count, columns=cols)

    def sample(self, schema, name, limit):
        cur = self.connect().execute(f"SELECT * FROM {_quote(name)} LIMIT ?", (int(limit),))   # nosec B608
        return [d[0] for d in cur.description], cur.fetchall()

    dialect = "ansi"

    def adapt(self, rule):
        return {**rule, "schema": "", "ref_schema": ""}

    def query(self, sql, max_rows=1):
        cur = self.connect().execute(sql)
        return [d[0] for d in cur.description], cur.fetchmany(int(max_rows))

    def close(self):
        if getattr(self, "conn", None) is not None:
            self.conn.close()


@connector
class SqlConnector(Connector):
    """Genel DB-API bağlayıcısı: kaynağın kendi sürücüsüyle hazır katalog sorgusu çalıştırılır, sonuç CSV olarak gider.

    Platform CSV başlıklarını tanır (schema_name, table_name, column_name, data_type, ...): SAP HANA, SAP ABAP sözlüğü,
    SQL Server, Oracle, MySQL, Snowflake ve Redshift sorguları kaynağın "Nasıl içe aktarılır" sekmesindedir.
    """
    name = "sql"
    description = "Herhangi bir DB-API sürücüsüyle hazır katalog sorgusu (SAP HANA, SQL Server, Oracle, MySQL, Snowflake…)."
    options = {"driver": "Sürücü modülü (hdbcli.dbapi, pyodbc, oracledb, pymysql, snowflake.connector)",
               "connect_env": "Bağlantı bilgilerini JSON olarak taşıyan ortam değişkeni (anahtar=değer)",
               "dsn_env": "Tek bağlantı dizesi kullanan sürücüler için ortam değişkeni (ör. pyodbc)",
               "preset": "Platformdaki hazır sorgunun anahtarı (ör. hana_catalog, sap_ddic, mssql_columns)",
               "replace": "Hazır sorgudaki yer tutucuların değerleri ({\"<ŞEMA_1>\": \"SATIS\"})",
               "query": "Sorgu metni", "query_file": "Sorgu dosyası", "quote": "Ad tırnağı (\" varsayılan, [ veya `)",
               "sample_sql": "Örnek sorgu kalıbı: {table} ve {n} (varsayılan SELECT * FROM {table} LIMIT {n})"}
    presets = {}

    def connect(self):
        if getattr(self, "conn", None) is None:
            driver = _module(self.setting("driver", required=True), "Sürücüyü toplayıcı makinesine kurun.")
            if self.settings.get("dsn_env"):
                self.conn = driver.connect(self.secret("dsn_env", "TEDARIK_SOURCE_DSN"))
            else:
                try:
                    kwargs = json.loads(self.secret("connect_env", "TEDARIK_SOURCE_CONNECT"))
                except ValueError:
                    raise CollectorError("Bağlantı ortam değişkeni geçerli JSON değil") from None
                self.conn = driver.connect(**kwargs)
        return self.conn

    def catalog_query(self):
        text = self.settings.get("query")
        if not text and self.settings.get("query_file"):
            text = Path(self.settings["query_file"]).expanduser().read_text(encoding="utf-8")
        if not text and self.settings.get("preset"):
            text = self.presets.get(self.settings["preset"])
            if not text:
                raise CollectorError(f"Hazır sorgu bulunamadı: {self.settings['preset']} "
                                     f"(kaynakta olanlar: {', '.join(self.presets) or 'yok'})")
        if not text:
            raise CollectorError("sql bağlayıcısı için query, query_file veya preset ayarı gerekli")
        for key, value in (self.settings.get("replace") or {}).items():
            text = text.replace(key, str(value).replace("'", "''"))
        if re.search(r"<[A-ZÇĞİÖŞÜa-z_0-9]+>", text):
            raise CollectorError("Sorguda doldurulmamış yer tutucu var (ör. <ŞEMA_1>); 'replace' ayarına ekleyin")
        return text.strip().rstrip(";")

    def export(self):
        cur = self.connect().cursor()
        cur.execute(self.catalog_query())
        headers = [str(d[0]) for d in cur.description]
        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=";")
        writer.writerow(headers)
        lower = [h.lower() for h in headers]
        si = next((lower.index(k) for k in ("schema_name", "table_schema", "owner") if k in lower), None)
        ti = next((lower.index(k) for k in ("table_name", "tabname") if k in lower), None)
        seen, n = {}, 0
        while True:
            batch = cur.fetchmany(5000)
            if not batch:
                break
            for row in batch:
                writer.writerow(["" if v is None else v for v in row])
                n += 1
                if ti is not None:
                    seen.setdefault((str(row[si]) if si is not None and row[si] is not None else "", str(row[ti])), 1)
        if not n:
            raise CollectorError("Katalog sorgusu satır döndürmedi; şema adlarını ve hesabın okuma yetkisini denetleyin")
        self.tables = [table(s, t) for s, t in seen]
        return f"{self.name}-{self.settings.get('preset') or 'sorgu'}.csv", buf.getvalue().encode("utf-8")

    def query(self, sql, max_rows=1):
        cur = self.connect().cursor()
        cur.execute(sql)
        return [str(d[0]) for d in cur.description], cur.fetchmany(int(max_rows))

    def sample(self, schema, name, limit):
        char = self.settings.get("quote") or '"'
        target = f"{_quote(schema, char)}.{_quote(name, char)}" if schema else _quote(name, char)
        pattern = self.settings.get("sample_sql") or "SELECT * FROM {table} LIMIT {n}"
        cur = self.connect().cursor()
        cur.execute(pattern.format(table=target, n=int(limit)))
        return [str(d[0]) for d in cur.description], cur.fetchmany(int(limit))

    def close(self):
        if getattr(self, "conn", None) is not None:
            self.conn.close()


INT = re.compile(r"^-?(0|[1-9]\d*)$")
DEC = re.compile(r"^-?\d+[.,]\d+$")
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})$")
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{2}[./]\d{2}[./]\d{4})[ T]\d{2}:\d{2}(:\d{2})?")
BOOL = {"true", "false", "evet", "hayır", "hayir", "yes", "no"}


def infer_type(values):
    """Örnek değerlerden kolon tipi ve en uzun değer; değerler yerelde kalır."""
    values = [v for v in values if v not in (None, "")]
    if not values:
        return "text", None
    for name, test in (("integer", INT.match), ("decimal", lambda v: INT.match(v) or DEC.match(v)), ("date", DATE.match),
                       ("timestamp", STAMP.match), ("boolean", lambda v: v.lower() in BOOL)):
        if all(test(v) for v in values):
            return name, None
    return "text", max(len(v) for v in values)


@connector
class FilesConnector(Connector):
    name = "files"
    description = "Klasördeki CSV dosyaları: her dosya bir tablo, başlık satırı kolonlar; tip yerelde örnekten çıkarılır."
    options = {"path": "Klasör", "pattern": "Dosya kalıbı (varsayılan *.csv)", "schema": "Şema adı (varsayılan klasör adı)",
               "recursive": "Alt klasörler (varsayılan kapalı)", "infer_rows": "Tip için okunacak satır (varsayılan 500)",
               "row_counts": "Satır sayısı (varsayılan açık)", "encoding": "Karakter kodlaması (varsayılan utf-8-sig)"}

    def _files(self):
        root = Path(self.setting("path", required=True)).expanduser()
        if not root.is_dir():
            raise CollectorError(f"Klasör bulunamadı: {root}")
        pattern = self.settings.get("pattern") or "*.csv"
        found = root.rglob("*") if self.settings.get("recursive") else root.iterdir()
        return root, sorted(p for p in found if p.is_file() and fnmatch.fnmatch(p.name.lower(), pattern.lower()))

    def _reader(self, path):
        fh = open(path, encoding=self.settings.get("encoding") or "utf-8-sig", newline="")
        head = fh.read(8192)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(head, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        return fh, csv.reader(fh, dialect)

    def collect(self):
        root, files = self._files()
        default_schema = self.settings.get("schema") or root.name
        limit = int(self.settings.get("infer_rows") or 500)
        self.paths = {}
        for path in files:
            schema = default_schema if path.parent == root else f"{default_schema}/{path.parent.relative_to(root).as_posix()}"
            fh, reader = self._reader(path)
            with fh:
                headers = next(reader, None) or []
                sample, total = [], 0
                for row in reader:
                    total += 1
                    if len(sample) < limit:
                        sample.append(row)
                    elif not self.settings.get("row_counts", True):
                        break
            cols = []
            for i, h in enumerate(headers):
                if not h.strip():
                    continue
                values = [r[i].strip() if i < len(r) else "" for r in sample]
                kind, length = infer_type(values)
                cols.append(column(h.strip(), position=i + 1, data_type=kind, length=length,
                                   nullable=any(not v for v in values)))
            self.paths[(schema, path.stem)] = path
            yield table(schema, path.stem, object_type="file", columns=cols,
                        row_count=total if self.settings.get("row_counts", True) else None,
                        description=f"{path.name}")

    def _all(self, schema, name):
        path = getattr(self, "paths", {}).get((schema, name))
        if not path:
            raise CollectorError(f"Dosya bulunamadı: {schema}/{name}")
        fh, reader = self._reader(path)
        with fh:
            headers = [h.strip() for h in next(reader, None) or []]
            return headers, [row for row in reader]

    def evaluate(self, rule):
        """CSV dosyasında kuralı yerelde değerlendirir; yalnızca sayılar döner."""
        headers, records = self._all(rule["schema"], rule["table"])
        kind = rule["type"]
        if kind == "row_count":
            return {"measured": len(records)}
        if kind == "custom_sql":
            raise CollectorError("CSV klasöründe özel SQL kuralı çalışmaz")
        lower = [h.lower() for h in headers]
        if str(rule.get("column") or "").lower() not in lower:
            raise CollectorError(f"Kolon dosyada yok: {rule.get('column')}")
        i = lower.index(rule["column"].lower())
        values = [(r[i].strip() if i < len(r) else "") for r in records]
        filled = [v for v in values if v]
        p = rule.get("params") or {}
        if kind == "not_null":
            return {"checked": len(values), "failed": len(values) - len(filled)}
        if kind == "unique":
            return {"checked": len(filled), "failed": len(filled) - len(set(filled))}
        if kind == "freshness":
            stamps = [v for v in filled if DATE.match(v[:10])]
            return {"measured": max(stamps) if stamps else None}
        if kind == "range":
            def bad(v):
                try:
                    n = float(v.replace(",", "."))
                except ValueError:
                    return True
                return (p.get("min") not in (None, "") and n < float(p["min"])) or (p.get("max") not in (None, "") and n > float(p["max"]))
            return {"checked": len(filled), "failed": sum(1 for v in filled if bad(v))}
        if kind == "allowed_values":
            allowed = {str(v) for v in p.get("values") or []}
            return {"checked": len(filled), "failed": sum(1 for v in filled if v not in allowed)}
        if kind in ("pattern", "format"):
            checked, failed = _dq.python_check(rule, filled, _pii)
            return {"checked": checked, "failed": failed}
        if kind == "reference":
            ref_headers, ref_rows = self._all(rule.get("ref_schema") or rule["schema"], rule["ref_table"])
            j = [h.lower() for h in ref_headers].index(str(rule["ref_column"]).lower())
            known = {(r[j].strip() if j < len(r) else "") for r in ref_rows}
            return {"checked": len(filled), "failed": sum(1 for v in filled if v not in known)}
        raise CollectorError("Bilinmeyen kural türü")

    def sample(self, schema, name, limit):
        path = getattr(self, "paths", {}).get((schema, name))
        if not path:
            return None
        fh, reader = self._reader(path)
        with fh:
            headers = next(reader, None) or []
            out = []
            for row in reader:
                if len(out) >= limit:
                    break
                out.append(row)
        return headers, out


# ------------------------------------------------------------------ platform istemcisi

class Client:
    """Platform ile konuşan istemci. Testler aynı arayüzle (get/post) uygulamaya doğrudan bağlanır."""

    def __init__(self, base, key, ca_file=None, timeout=120, retries=3):
        base = (base or "").rstrip("/")
        host = re.sub(r"^https?://", "", base).split("/")[0].split(":")[0]
        if not base.startswith("https://") and not (base.startswith("http://") and host in ("127.0.0.1", "localhost")):
            raise CollectorError("Platform adresi https:// ile başlamalı (anahtar şifresiz bağlantıda gönderilmez)")
        if not key:
            raise CollectorError("Toplayıcı anahtarı bulunamadı (key_env veya key_file)")
        self.base, self.key, self.timeout, self.retries = base, key, timeout, retries
        context = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    def _send(self, method, path, body=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        request = urllib.request.Request(f"{self.base}/api/tdr/collector/{path}", data=data, method=method, headers={
            "X-Collector-Key": self.key, "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": f"tedarik-toplayici/{VERSION}"})
        for attempt in range(self.retries):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:   # nosec B310 - adres HTTPS (yukarıda)
                    return json.loads(response.read() or b"{}")
            except urllib.error.HTTPError as exc:
                try:
                    message = json.loads(exc.read() or b"{}").get("error") or exc.reason
                except ValueError:
                    message = exc.reason
                if exc.code >= 500 and attempt + 1 < self.retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                if exc.code == 401:
                    message = "Anahtar geçersiz veya toplayıcı iptal edilmiş"
                raise CollectorError(f"Platform yanıtı {exc.code}: {message}") from None
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt + 1 < self.retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise CollectorError(f"Platforma bağlanılamadı: {getattr(exc, 'reason', exc)}") from None
        raise CollectorError("Platforma bağlanılamadı")

    def get(self, path):
        return self._send("GET", path)

    def post(self, path, body):
        return self._send("POST", path, body)


# ------------------------------------------------------------------ çalıştırma

def load_config(path):
    try:
        cfg = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CollectorError(f"Ayar dosyası bulunamadı: {path}") from None
    except ValueError as exc:
        raise CollectorError(f"Ayar dosyası geçerli JSON değil: {exc}") from None
    if not isinstance(cfg, dict) or not cfg.get("platform"):
        raise CollectorError("Ayar dosyasında 'platform' adresi gerekli")
    return cfg


def read_key(cfg):
    env = cfg.get("key_env") or "TEDARIK_COLLECTOR_KEY"
    if os.environ.get(env):
        return os.environ[env].strip()
    if cfg.get("key_file"):
        path = Path(cfg["key_file"]).expanduser()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            raise CollectorError(f"Anahtar dosyası okunamadı: {path}") from None
    return None


def load_plugins(paths):
    for i, path in enumerate(paths or []):
        path = Path(path).expanduser()
        if not path.is_file():
            raise CollectorError(f"Eklenti dosyası bulunamadı: {path}")
        spec = importlib.util.spec_from_file_location(f"tdr_eklenti_{i}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


def make_connector(cfg, info=None):
    load_plugins(cfg.get("plugins"))
    name = cfg.get("connector")
    if name not in CONNECTORS:
        raise CollectorError(f"Bilinmeyen bağlayıcı: {name} (var olanlar: {', '.join(sorted(CONNECTORS))})")
    conn = CONNECTORS[name](cfg.get("settings") or {})
    if isinstance(conn, SqlConnector):
        conn.presets = {q["key"]: q["text"] for q in (info or {}).get("queries") or []}
    return conn


def sample_stats(conn, rows, max_tables=500):
    """Tablo başına `rows` satırı yerelde okur ve doğrular; yalnızca sayılar döner."""
    out, errors = [], 0
    for schema, name, kind in conn.table_keys()[:max_tables]:
        if kind == "view":
            continue
        try:
            got = conn.sample(schema, name, rows)
        except Exception:   # noqa: BLE001 - tek tablonun okunamaması toplamayı durdurmaz
            errors += 1
            continue
        if not got:
            continue
        headers, records = got
        stats = _pii.scan([str(h) for h in headers], ([("" if v is None else v) for v in r] for r in records), rows)
        cols = {k: v for k, v in stats["columns"].items() if v["matches"]}
        if cols:
            out.append({"schema": schema, "table": name, "sample_size": stats["sample_size"], "columns": cols})
    return out, errors


def client_info(name):
    return {"version": VERSION, "connector": name, "host": socket.gethostname()[:100],
            "python": _platform.python_version()}


def encode(filename, raw):
    packed = gzip.compress(raw, compresslevel=6)
    if len(packed) > MAX_PUSH:
        raise CollectorError(f"Katalog sıkıştırılmış hâliyle {len(packed) // (1024 * 1024)} MB; şemalara bölün "
                             "(settings.schemas) ve birden çok toplayıcı tanımlayın")
    return {"filename": filename, "content_base64": base64.b64encode(packed).decode("ascii"), "compressed": "gzip"}


COUNT_TEXT = {"table_added": "tablo eklendi", "table_removed": "tablo kaldırıldı", "table_restored": "tablo geri geldi",
              "column_added": "kolon eklendi", "column_removed": "kolon kaldırıldı", "column_restored": "kolon geri geldi",
              "type_changed": "tip değişti"}


def describe(result):
    counts = ", ".join(f"{n} {COUNT_TEXT.get(k, k)}" for k, n in (result.get("counts") or {}).items() if n) or "değişiklik yok"
    text = f"{result.get('tables_in_file', 0)} tablo, {result.get('columns_in_file', 0)} kolon — {counts}"
    sample = result.get("sample") or {}
    if sample.get("tables"):
        text += f"; örnek doğrulama: {sample['tables']} tablo, {sample.get('new', 0)} yeni kişisel veri önerisi"
    return text


def _plain(value):
    """Ölçüm değerini JSON'a uygun düz metne/sayıya çevirir."""
    if value is None or isinstance(value, (int, float, str)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


NUMBER = re.compile(r"^-?\d+([.,]\d+)?$")


def profile_columns(headers, records, sensitive):
    """Örnekten kolon istatistiği: boş, farklı değer, uzunluk; hassas olmayan sayısal/tarih kolonda en küçük/en büyük."""
    out = {}
    for i, h in enumerate(headers):
        name = str(h)
        nulls, seen, lengths, nums, dates, numeric, datelike = 0, set(), [], [], [], True, True
        for row in records:
            v = row[i] if i < len(row) else None
            if v is None or (isinstance(v, str) and not v.strip()):
                nulls += 1
                continue
            text = str(v).strip() if not hasattr(v, "isoformat") else v.isoformat()
            seen.add(text[:200])
            lengths.append(len(text))
            if isinstance(v, bool):
                numeric = datelike = False
            elif isinstance(v, (int, float)) or (not isinstance(v, str) and type(v).__name__ == "Decimal"):
                nums.append(float(v))
                datelike = False
            elif hasattr(v, "isoformat"):
                dates.append(text)
                numeric = False
            elif NUMBER.match(text):
                nums.append(float(text.replace(",", ".")))
                datelike = False
            elif DATE.match(text[:10]) and text[:4].isdigit():
                dates.append(text)
                numeric = False
            else:
                numeric = datelike = False
        stat = {"nulls": nulls, "distinct": len(seen), "min_len": min(lengths) if lengths else None,
                "max_len": max(lengths) if lengths else None}
        if name.lower() not in sensitive:
            if numeric and nums:
                stat.update(min=min(nums), max=max(nums))
            elif datelike and dates:
                stat.update(min=min(dates), max=max(dates))
        out[name] = stat
    return out


def run_quality(cfg, client, conn, info=None, out=print):
    """Platformdaki kuralları kurum ağında çalıştırır; yalnızca sayıları ve profil istatistiklerini gönderir."""
    plan = client.get("quality")
    dialect = getattr(conn, "dialect", None)
    if isinstance(conn, SqlConnector):
        dialect = conn.settings.get("dialect") or plan.get("dialect") or "ansi"
    results = []
    for rule in plan.get("rules") or []:
        item = {"rule": rule["code"]}
        try:
            rule = conn.adapt(rule)
            if rule["type"] == "custom_sql" and not cfg.get("allow_custom_sql"):
                raise CollectorError("Özel SQL kuralı bu toplayıcıda kapalı; ayar dosyasına \"allow_custom_sql\": true ekleyin")
            if dialect is None:
                item.update(conn.evaluate(rule))
            else:
                sql, mode = _dq.build(rule, dialect)
                if mode == "python":
                    limit = int((rule.get("params") or {}).get("max_rows") or 200000)
                    headers, records = conn.query(sql, limit)
                    checked, failed = _dq.python_check(rule, (r[0] for r in records), _pii)
                    item.update(checked=checked, failed=failed)
                else:
                    headers, records = conn.query(sql, 1)
                    row = dict(zip([str(h).lower() for h in headers], records[0] if records else []))
                    if mode == "measured":
                        item["measured"] = _plain(row.get("measured"))
                    else:
                        item.update(checked=int(row.get("checked") or 0), failed=int(row.get("failed") or 0))
            if "measured" in item:
                item["measured"] = _plain(item["measured"])
        except Exception as exc:   # noqa: BLE001 - tek kuralın hatası diğerlerini durdurmaz; platformda "çalışmadı" olur
            item = {"rule": rule["code"], "error": str(exc)[:400] if isinstance(exc, (CollectorError, _dq.RuleError))
                    else f"{type(exc).__name__}: {str(exc)[:300]}"}
        results.append(item)
    profiles = []
    rows_n = int((plan.get("profile") or {}).get("rows") or 0)
    sensitive_all = set(plan.get("sensitive") or [])
    for t in (plan.get("profile") or {}).get("tables") or [] if rows_n else []:
        try:
            got = conn.sample(t["schema"], t["table"], rows_n)
        except Exception:   # noqa: BLE001 - okunamayan tablo atlanır
            continue
        if not got:
            continue
        headers, records = got
        prefix = f"{(t['schema'] or '').lower()}.{t['table'].lower()}."
        sensitive = {k[len(prefix):] for k in sensitive_all if k.startswith(prefix)}
        profiles.append({"schema": t["schema"], "table": t["table"], "sample_size": len(records),
                         "columns": profile_columns([str(h) for h in headers], records, sensitive)})
    if not results and not profiles:
        return None
    r = client.post("quality", {"results": results, "profiles": profiles, "client": client_info(conn.name)})
    out(f"Kalite: {len(results)} kural (geçti {r.get('pass', 0)}, başarısız {r.get('fail', 0)}, çalışmadı {r.get('error', 0)}); "
        f"{r.get('profiles', 0)} tablo profillendi")
    return r


def report(client, exc, name):
    """Yerel hatayı platforma bildirir (teknik sorumluya iletilir); bildirilemezse sessizce geçer."""
    try:
        client.post("status", {"result": "error", "message": str(exc)[:1000], "client": client_info(name)})
    except CollectorError:
        pass


def push(cfg, client, preview=False, out=print):
    info = client.get("whoami")
    name = str(cfg.get("connector") or "?")
    try:
        conn = make_connector(cfg, info)
    except CollectorError as exc:
        report(client, exc, name)
        raise
    try:
        try:
            filename, raw = conn.export()
            limit = int(cfg["sample_rows"] if cfg.get("sample_rows") is not None else info["collector"].get("sample_rows") or 0)
            stats, skipped = sample_stats(conn, limit) if limit and not preview else ([], 0)
        except CollectorError as exc:
            report(client, exc, name)
            raise
        except Exception as exc:   # noqa: BLE001 - kaynak sürücüsünün hatası platforma da bildirilir
            error = CollectorError(f"Kaynaktan okunamadı: {type(exc).__name__}: {str(exc)[:300]}")
            report(client, error, name)
            raise error from None
        body = {**encode(filename, raw), "dry_run": bool(preview), "client": client_info(conn.name), "sample_stats": stats}
        if cfg.get("scope"):
            body["scope"] = cfg["scope"]
        if cfg.get("default_schema"):
            body["default_schema"] = cfg["default_schema"]
        result = client.post("catalog", body)
        head = "Ön izleme (veri yazılmadı)" if preview else "Gönderildi"
        out(f"{head}: {info['source']['name']} — {describe(result)}")
        if skipped:
            out(f"Uyarı: {skipped} tablonun örneği okunamadı (yetki veya tip); yapı yine de gönderildi.")
        quality = info.get("quality") or {}
        if not preview and (quality.get("rules") or quality.get("profile_rows")):
            run_quality(cfg, client, conn, info, out)
        return result
    finally:
        conn.close()


def push_file(cfg, client, path, preview=False, out=print):
    info = client.get("whoami")
    path = Path(path).expanduser()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        error = CollectorError(f"Dışa aktarım dosyası okunamadı: {path} ({exc.strerror})")
        report(client, error, "file")
        raise error from None
    body = {**encode(path.name, raw), "dry_run": bool(preview), "client": client_info("file")}
    if cfg.get("scope"):
        body["scope"] = cfg["scope"]
    if cfg.get("default_schema"):
        body["default_schema"] = cfg["default_schema"]
    result = client.post("catalog", body)
    out(f"{'Ön izleme (veri yazılmadı)' if preview else 'Gönderildi'}: {info['source']['name']} — {describe(result)}")
    return result


EXAMPLES = {
    "postgresql": {"dsn_env": "TEDARIK_SOURCE_DSN", "schemas": ["public"], "row_counts": True},
    "sqlite": {"path": "/veri/uygulama.db"},
    "sql": {"driver": "hdbcli.dbapi", "connect_env": "TEDARIK_SOURCE_CONNECT", "preset": "hana_catalog",
            "replace": {"<ŞEMA_1>": "SATIS", "<ŞEMA_2>": "FINANS"}},
    "files": {"path": "/paylasim/veri", "pattern": "*.csv", "schema": "paylasim"},
}


def example(name):
    cfg = {"platform": "https://<platform-adresi>", "key_file": "/etc/tedarik/anahtar", "connector": name or "postgresql",
           "settings": EXAMPLES.get(name or "postgresql", {})}
    return json.dumps(cfg, ensure_ascii=False, indent=2)


def build_client(cfg):
    return Client(cfg["platform"], read_key(cfg), cfg.get("ca_file"), int(cfg.get("timeout") or 120))


def main(argv=None, client=None, out=print):
    sys.modules.setdefault("tdr_collector", sys.modules[__name__])     # eklentiler `from tdr_collector import ...` kullanır
    parser = argparse.ArgumentParser(prog="tedarik-toplayici", description="Veri kataloğu toplayıcısı (meta veri; ham veri gönderilmez)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, aliases, text in (("dene", ["check"], "Platform ve kaynak bağlantısını sınar"),
                                ("topla", ["collect"], "Meta veriyi toplar, dosyaya yazar; göndermez"),
                                ("gonder", ["push"], "Toplar ve platforma gönderir"),
                                ("dosya-gonder", ["push-file"], "Hazır dışa aktarım dosyasını gönderir"),
                                ("kalite", ["quality"], "Veri kalitesi kurallarını ve profili çalıştırır (yalnızca sayılar gider)")):
        p = sub.add_parser(name, aliases=aliases, help=text)
        p.add_argument("--ayar", "--config", dest="config", required=True, help="Ayar dosyası (JSON)")
        p.add_argument("--eklenti", "--plugin", dest="plugins", action="append", default=[], help="Bağlayıcı eklentisi (.py)")
        if name in ("gonder", "dosya-gonder"):
            p.add_argument("--on-izleme", "--dry-run", dest="preview", action="store_true", help="Veri yazmadan sonucu göster")
        if name == "topla":
            p.add_argument("--cikti", "--out", dest="out", help="Çıktı dosyası (varsayılan: standart çıktı)")
        if name == "dosya-gonder":
            p.add_argument("dosya", help="CSV, Excel veya JSON dışa aktarım")
    sub.add_parser("baglayicilar", aliases=["connectors"], help="Bağlayıcıları listeler")
    ex = sub.add_parser("ornek-ayar", aliases=["example-config"], help="Örnek ayar dosyası yazar")
    ex.add_argument("baglayici", nargs="?", default="postgresql")
    args = parser.parse_args(argv)
    try:
        if args.command in ("baglayicilar", "connectors"):
            for name, cls in sorted(CONNECTORS.items()):
                out(f"{name:<12} {cls.description}")
                for key, text in cls.options.items():
                    out(f"{'':<14}{key}: {text}")
            return 0
        if args.command in ("ornek-ayar", "example-config"):
            out(example(args.baglayici))
            return 0
        cfg = load_config(args.config)
        cfg["plugins"] = list(cfg.get("plugins") or []) + args.plugins
        if args.command in ("topla", "collect"):
            info = None
            if cfg.get("connector") == "sql":
                info = (client or build_client(cfg)).get("whoami")
            conn = make_connector(cfg, info)
            try:
                filename, raw = conn.export()
            finally:
                conn.close()
            if args.out:
                Path(args.out).write_bytes(raw)
                out(f"Yazıldı: {args.out} ({len(conn.tables)} tablo)")
            else:
                sys.stdout.write(raw.decode("utf-8"))
            return 0
        client = client or build_client(cfg)
        if args.command in ("dene", "check"):
            info = client.get("whoami")
            out(f"Platform: bağlantı tamam — {info['collector']['code']} {info['collector']['name']} → "
                f"{info['source']['code']} {info['source']['name']}")
            if cfg.get("connector") != "file":
                conn = make_connector(cfg, info)
                try:
                    filename, raw = conn.export()
                finally:
                    conn.close()
                out(f"Kaynak: bağlantı tamam — {len(conn.tables)} tablo okunabiliyor ({len(raw) // 1024} KB meta veri)")
            return 0
        if args.command in ("gonder", "push"):
            push(cfg, client, args.preview, out)
            return 0
        if args.command in ("dosya-gonder", "push-file"):
            push_file(cfg, client, args.dosya, args.preview, out)
            return 0
        if args.command in ("kalite", "quality"):
            info = client.get("whoami")
            conn = make_connector(cfg, info)
            try:
                conn.export()                    # dosya yolları ve tablo listesi
                if run_quality(cfg, client, conn, info, out) is None:
                    out("Bu kaynak için etkin kalite kuralı veya profil ayarı yok.")
            finally:
                conn.close()
            return 0
    except CollectorError as exc:
        print(f"Hata: {exc}", file=_STDERR)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
