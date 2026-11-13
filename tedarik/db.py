"""Veritabanı katmanı: PostgreSQL (üretim) ve SQLite (geliştirme, test, KS GRC ile tek dosya) — K-011.

Uygulama kodu tek bir SQL lehçesi yazar ve motor farkını bilmez:
- parametre işareti her zaman `?`;
- eklenen kaydın kimliği `cursor.lastrowid` (PostgreSQL'de `RETURNING id` kendiliğinden eklenir);
- çakışmada `INSERT ... ON CONFLICT DO NOTHING` (iki motorda da geçerli);
- tarih hesabı SQL'de değil Python'da yapılır (`today()`), sonuç parametre olarak verilir;
- yazıcıları sıralamak için `db.lock(ad)`;
- hatalar `IntegrityError` ve `DatabaseError` adlarıyla yakalanır.

Motor farkları (bağlantı, kimlik sütunu, tip eşlemesi, tetikleyici, sütun listesi) yalnızca bu dosyada ve
`migrate.py` içindedir. PostgreSQL sürücüsü yalnızca PostgreSQL yapılandırıldığında gerekir; SQLite ek paket
istemez. SQLite bağlantı ayarları KS GRC ile aynıdır (WAL, foreign_keys, busy_timeout=15000).
"""
import re
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

try:   # isteğe bağlı: PostgreSQL yapılandırılmadıysa gerekmez
    import psycopg
    from psycopg_pool import ConnectionPool
except ImportError:      # pragma: no cover - yalnızca SQLite kurulumu
    psycopg = ConnectionPool = None

IntegrityError = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())
DatabaseError = (sqlite3.Error,) + ((psycopg.Error,) if psycopg else ())


FOLD_FROM, FOLD_TO = "ÇĞİIÖŞÜÂÎÛçğıöşüâîû", "CGIIOSUAIUcgiosuaiu"
_FOLD = str.maketrans(FOLD_FROM, FOLD_TO)


def fold(text):
    """Türkçe harf katlama: aramada 'Örnek', 'ÖRNEK', 'ornek' aynıdır. SQL karşılığı `tdr_fold()`."""
    return str(text or "").translate(_FOLD).lower()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today(days=0, months=0):
    """Bugünden göreli tarih (YYYY-AA-GG). SQL'de `date('now', ...)` yerine parametre olarak verilir."""
    value = date.today()
    if months:
        month = value.month - 1 + months
        value = value.replace(year=value.year + month // 12, month=month % 12 + 1, day=min(value.day, 28))
    return (value + timedelta(days=days)).isoformat()


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def one(db, sql, args=()):
    row = db.execute(sql, args).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- SQLite

class SqliteConn:
    dialect = "sqlite"

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, args=()):
        return self.raw.execute(sql, tuple(args))

    def executemany(self, sql, seq):
        return self.raw.executemany(sql, seq)

    @property
    def in_transaction(self):
        return self.raw.in_transaction

    def lock(self, name=None):
        """SQLite tek yazıcılıdır: yazma kilidini hemen al (KS GRC `BEGIN IMMEDIATE`)."""
        if not self.raw.in_transaction:
            self.raw.execute("BEGIN IMMEDIATE")

    @staticmethod
    def group_concat(expr, sep):
        return f"GROUP_CONCAT({expr}, '{sep}')"

    def columns(self, table):
        return {r["name"] for r in self.raw.execute(f"PRAGMA table_info({table})")}


# ---------------------------------------------------------------- PostgreSQL

_TOKEN = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|\?|%")
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", re.IGNORECASE)


def translate(sql):
    """`?` -> `%s`, `%` -> `%%`. Tırnak içindeki `?` parametre sayılmaz."""
    def repl(match):
        token = match.group(0)
        if token == "?":
            return "%s"
        return token.replace("%", "%%")
    return _TOKEN.sub(repl, sql)


def plain(value):
    """Sürücü tiplerini SQLite ile aynı JSON değerine çevirir (tarih: ISO metin, sayı: int/float)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


class Row(dict):
    """sqlite3.Row gibi: ada ve sıra numarasına göre erişim; `dict(row)` çalışır."""

    def __init__(self, names, values):
        super().__init__(zip(names, values))
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    return lambda values: Row(names, [plain(v) for v in values])


class PgCursor:
    def __init__(self, cursor, lastrowid=None):
        self._cursor, self.lastrowid = cursor, lastrowid

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def fetchone(self):
        return self._cursor.fetchone() if self._cursor.description else None

    def fetchall(self):
        return self._cursor.fetchall() if self._cursor.description else []

    def __iter__(self):
        return iter(self.fetchall())


class PgConn:
    dialect = "postgres"

    def __init__(self, raw, database):
        self.raw, self.database = raw, database

    def execute(self, sql, args=()):
        match = _INSERT.match(sql)
        returning = bool(match and " RETURNING " not in sql.upper()
                         and match.group(1).lower() in self.database.id_tables(self.raw))
        cursor = self.raw.cursor(row_factory=_row_factory)
        cursor.execute(translate(sql) + (" RETURNING id" if returning else ""), tuple(args))
        lastrowid = None
        if returning:
            row = cursor.fetchone()
            lastrowid = row[0] if row else None
        return PgCursor(cursor, lastrowid)

    def executemany(self, sql, seq):
        for args in seq:
            self.execute(sql, args)

    @property
    def in_transaction(self):
        return self.raw.info.transaction_status != psycopg.pq.TransactionStatus.IDLE

    def lock(self, name=None):
        """İşlem sonuna kadar süren danışma kilidi; aynı ad için yazıcılar sıraya girer."""
        key = zlib.crc32(("tdr:" + (name or "*")).encode("utf-8")) - 2 ** 31
        self.raw.execute("SELECT pg_advisory_xact_lock(%s)", (key,))

    @staticmethod
    def group_concat(expr, sep):
        return f"STRING_AGG({expr}, '{sep}')"

    def columns(self, table):
        cursor = self.raw.execute("SELECT column_name FROM information_schema.columns "
                                  "WHERE table_schema = current_schema() AND table_name = %s", (table,))
        return {r[0] for r in cursor.fetchall()}


# ---------------------------------------------------------------- Ortak giriş

class Database:
    """Yapılandırmaya göre motoru seçer. `with database.connect() as db:` başarıda kaydeder, hatada geri alır."""

    def __init__(self, config):
        self.config = config
        self.url = getattr(config, "database_url", "") or ""
        self.dialect = "postgres" if self.url else "sqlite"
        self.schema = getattr(config, "db_schema", "") or ""
        self._pool = None
        self._id_tables = None
        self._lock = threading.Lock()
        if self.dialect == "sqlite":
            return
        if psycopg is None:
            raise RuntimeError("PostgreSQL için psycopg ve psycopg-pool kurulmalı (requirements.txt)")
        schema = self.schema

        def configure(conn):
            conn.execute("SET TIME ZONE 'UTC'")
            conn.execute("SET statement_timeout = '30s'")
            if schema:
                conn.execute(f'SET search_path TO "{schema}"')
            conn.commit()
        self._pool = ConnectionPool(self.url, min_size=1, max_size=getattr(config, "db_pool_size", 10),
                                    kwargs={"application_name": "tedarik", "autocommit": False},
                                    configure=configure, open=True, timeout=15, name="tedarik")

    @contextmanager
    def connect(self):
        if self.dialect == "postgres":
            with self._pool.connection() as raw:   # havuz başarıda kaydeder, hatada geri alır
                yield PgConn(raw, self)
            return
        raw = sqlite3.connect(self.config.db, timeout=15)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA foreign_keys=ON")
        raw.execute("PRAGMA busy_timeout=15000")
        raw.create_function("tdr_fold", 1, lambda v: None if v is None else fold(v), deterministic=True)
        try:
            yield SqliteConn(raw)
            raw.commit()
        except BaseException:
            raw.rollback()
            raise
        finally:
            raw.close()

    def id_tables(self, raw):
        """PostgreSQL: `id` sütunu olan tablolar (eklemede `RETURNING id` için). Şema değişince yenilenir."""
        with self._lock:
            if self._id_tables is None:
                cursor = raw.execute("SELECT table_name FROM information_schema.columns "
                                     "WHERE table_schema = current_schema() AND column_name = 'id'")
                self._id_tables = {r[0] for r in cursor.fetchall()}
            return self._id_tables

    def schema_changed(self):
        with self._lock:
            self._id_tables = None

    def close(self):
        if self._pool is not None:
            self._pool.close()
            self._pool = None
