"""Tüm kaynaklar için ortak doğrulama ve kayıt işlemleri. Silme yoktur; kayıtlar durum alanıyla kapatılır."""
import re
from datetime import date, datetime, timezone

from .db import fold, one, rows, utcnow

TEXT_LIMIT = 20000


class Invalid(ValueError):
    pass


class NotFound(LookupError):
    pass


class Forbidden(PermissionError):
    pass


class Conflict(RuntimeError):
    pass


RESERVED = {"q", "limit", "offset"}


def clean(payload):
    """Metinleri kırpar, boş metni NULL sayar."""
    out = {}
    for field, value in payload.items():
        if isinstance(value, str):
            value = value.strip() or None
        out[field] = value
    return out


def _date(field, value):
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise Invalid(f"{field}: tarih YYYY-AA-GG biçiminde olmalı") from None
    return value


def _timestamp(field, value):
    """Saat dilimli ISO 8601 (KS GRC kuralı) veya yalnızca tarih; UTC'ye çevrilip saniyeye yuvarlanır."""
    if isinstance(value, str) and len(value) == 10:
        return _date(field, value) + "T00:00:00+00:00"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else None
    except ValueError:
        stamp = None
    if stamp is None or stamp.tzinfo is None:
        raise Invalid(f"{field}: zaman saat dilimli ISO 8601 olmalı (ör. 2026-11-13T09:00:00+03:00)")
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def normalize(field, column, value):
    """Değeri alan tipine göre denetler ve iki motorda aynı biçime getirir."""
    kind = column.kind
    if kind == "TEXT":
        if not isinstance(value, str):
            raise Invalid(f"{field} metin olmalı")
        if len(value) > TEXT_LIMIT:
            raise Invalid(f"Alan çok uzun: {field}")
        return value
    if kind == "INTEGER":
        if isinstance(value, bool):
            return int(value)
        if type(value) is not int or abs(value) > 2 ** 62:
            raise Invalid(f"{field} tamsayı olmalı")
        return value
    if kind in ("REAL", "DECIMAL"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or abs(value) > 1e15:
            raise Invalid(f"{field} sayı olmalı")
        return round(float(value), 2) if kind == "DECIMAL" else value
    if kind == "DATE":
        return _date(field, value)
    return _timestamp(field, value)


def validate(res, data, partial=False):
    """Bilinmeyen alanı, tipi, seçim listesini ve zorunlu alanları denetler; `data` yerinde normalleşir."""
    unknown = set(data) - set(res.fields)
    if unknown:
        raise Invalid("Bilinmeyen alan: " + ", ".join(sorted(unknown)))
    for field, value in list(data.items()):
        if value is None:
            continue
        data[field] = value = normalize(field, res.columns[field], value)
        allowed = res.enums.get(field)
        if allowed and value not in allowed:
            raise Invalid(f"{field} şunlardan biri olmalı: {', '.join(allowed)}")
    missing = [f for f in res.required if (f in data or not partial) and data.get(f) is None]
    if missing:
        raise Invalid("Zorunlu alan eksik: " + ", ".join(missing))
    return data


def check_scope(db, res, principal, record):
    """Birim Kullanıcısı yalnızca kendi biriminin kaydını yazar (kaynakta `scope` tanımlıysa)."""
    if principal is None or principal.role != "UNIT_USER" or res.scope is None:
        return
    owners = {u for u in res.scope(db, record) if u is not None}
    if not owners & principal.units:
        raise Forbidden("Yalnızca kendi biriminizin kayıtlarını değiştirebilirsiniz")


def get(db, res, record_id):
    record = one(db, f"SELECT * FROM {res.table} WHERE id=?", (record_id,))
    if not record:
        raise NotFound(f"{res.label}: kayıt bulunamadı")
    return record


def insert(db, res, payload, principal=None):
    data = clean(payload)
    validate(res, data)
    if res.before_save:
        res.before_save(db, data, None, principal)
    check_scope(db, res, principal, data)
    now = utcnow()
    for field in ("created_at", "updated_at"):
        if field in res.fields:
            data[field] = now
    cols, marks = ", ".join(data), ", ".join("?" for _ in data)
    return db.execute(f"INSERT INTO {res.table} ({cols}) VALUES ({marks})", tuple(data.values())).lastrowid


def update(db, res, record_id, payload, principal=None):
    current = get(db, res, record_id)
    data = clean(payload)
    if not data:
        raise Invalid("Güncellenecek alan yok")
    validate(res, data, partial=True)
    if res.before_save:
        res.before_save(db, data, current, principal)
    check_scope(db, res, principal, current)
    check_scope(db, res, principal, {**current, **data})
    if "updated_at" in res.fields:
        data["updated_at"] = utcnow()
    sets = ", ".join(f"{field}=?" for field in data)
    db.execute(f"UPDATE {res.table} SET {sets} WHERE id=?", (*data.values(), record_id))
    return get(db, res, record_id)


def _query_value(column, value):
    if column is not None and column.kind == "INTEGER":
        try:
            return int(value)
        except ValueError:
            raise Invalid(f"{column.name} tamsayı olmalı") from None
    if column is not None and column.kind in ("REAL", "DECIMAL"):
        try:
            return float(value)
        except ValueError:
            raise Invalid(f"{column.name} sayı olmalı") from None
    return value


def listing(db, res, query):
    where, args = [], []
    for key, value in query.items():
        if key in RESERVED:
            continue
        if key in res.fields:
            where.append(f"{key}=?")
            args.append(_query_value(res.columns[key], value))
        elif key in res.filters:
            where.append(res.filters[key])
            args.append(int(value) if value.isdigit() else value)
        else:
            raise Invalid(f"Bilinmeyen filtre: {key}")
    if query.get("q") and res.search:
        # Büyük/küçük harf duyarsız arama iki motorda da aynı sonucu verir.
        pattern = "%" + re.sub(r"([\\%_])", r"\\\1", fold(query["q"])) + "%"
        where.append("(" + " OR ".join(f"tdr_fold({f}) LIKE ? ESCAPE '\\'" for f in res.search) + ")")
        args += [pattern] * len(res.search)
    try:
        limit = max(1, min(int(query.get("limit", 200)), 1000))
        offset = max(int(query.get("offset", 0)), 0)
    except ValueError:
        raise Invalid("limit ve offset tamsayı olmalı") from None
    sql = f"SELECT * FROM {res.table}" + (" WHERE " + " AND ".join(where) if where else "")
    return rows(db, sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
