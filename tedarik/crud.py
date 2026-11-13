"""Tüm kaynaklar için ortak doğrulama ve kayıt işlemleri. Silme yoktur; kayıtlar durum alanıyla kapatılır."""
from .db import one, rows, utcnow


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


def validate(res, data, partial=False):
    unknown = set(data) - set(res.fields)
    if unknown:
        raise Invalid("Bilinmeyen alan: " + ", ".join(sorted(unknown)))
    for field, value in data.items():
        if value is None:
            continue
        if not isinstance(value, (str, int, float)):
            raise Invalid(f"Geçersiz değer: {field}")
        if isinstance(value, str) and len(value) > 20000:
            raise Invalid(f"Alan çok uzun: {field}")
        if "REFERENCES" in res.fields[field] and type(value) is not int:
            raise Invalid(f"{field} tamsayı olmalı")
        allowed = res.enums.get(field)
        if allowed and value not in allowed:
            raise Invalid(f"{field} şunlardan biri olmalı: {', '.join(allowed)}")
    missing = [f for f in res.required if (f in data or not partial) and data.get(f) is None]
    if missing:
        raise Invalid("Zorunlu alan eksik: " + ", ".join(missing))


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
    if "updated_at" in res.fields:
        data["updated_at"] = utcnow()
    sets = ", ".join(f"{field}=?" for field in data)
    db.execute(f"UPDATE {res.table} SET {sets} WHERE id=?", (*data.values(), record_id))
    return get(db, res, record_id)


def listing(db, res, query):
    where, args = [], []
    for key, value in query.items():
        if key in RESERVED:
            continue
        if key in res.fields:
            where.append(f"{key}=?")
        elif key in res.filters:
            where.append(res.filters[key])
        else:
            raise Invalid(f"Bilinmeyen filtre: {key}")
        args.append(value)
    if query.get("q") and res.search:
        where.append("(" + " OR ".join(f"{f} LIKE ?" for f in res.search) + ")")
        args += [f"%{query['q']}%"] * len(res.search)
    limit = max(1, min(int(query.get("limit", 200)), 1000))
    offset = max(int(query.get("offset", 0)), 0)
    sql = f"SELECT * FROM {res.table}" + (" WHERE " + " AND ".join(where) if where else "")
    return rows(db, sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset))
