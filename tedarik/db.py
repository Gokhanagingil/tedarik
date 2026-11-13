"""SQLite erişimi. Bağlantı ayarları KS GRC ile aynıdır (WAL, foreign_keys, busy_timeout).

Uygulamanın geri kalanı yalnızca bu modüldeki yardımcıları kullanır; ileride PostgreSQL'e
geçiş gerekirse değişiklik bu dosya ile schema.py'de kalır.
"""
import sqlite3
from datetime import datetime, timezone

from .schema import RESOURCES


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def connect(path):
    db = sqlite3.connect(path, timeout=15, factory=ClosingConnection)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    return db


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rows(db, sql, args=()):
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def one(db, sql, args=()):
    row = db.execute(sql, args).fetchone()
    return dict(row) if row else None


def initialize(path, modules):
    """Etkin modüllerin tablolarını açar; sonradan eklenen alanları tabloya ekler (eklemeli evrim)."""
    with connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        for res in RESOURCES.values():
            if res.module not in modules:
                continue
            db.execute(res.ddl())
            have = {r["name"] for r in db.execute(f"PRAGMA table_info({res.table})")}
            for field, definition in res.fields.items():
                if field in have:
                    continue
                if ("NOT NULL" in definition and "DEFAULT" not in definition) or "UNIQUE" in definition:
                    raise RuntimeError(f"{res.table}.{field} için elle göç gerekli (zorunlu/tekil yeni alan)")
                db.execute(f"ALTER TABLE {res.table} ADD COLUMN {field} {definition}")
