"""Denetim izi: her yazma işlemi kim, ne zaman, neyi değiştirdi bilgisiyle saklanır.

Sütun adları KS GRC'nin `activity_log` tablosuyla aynıdır (actor, method, object_type, object_id,
description, occurred_at); birleşmede iki tablo tek görünümde birleşir. Tedarik ayrıca kimlik türünü
(`auth_type`) ve yapılandırılmış değişikliği (`changes_json`) saklar.
Karşılık: control@7720f4b, grc_plus.py `log()` ve `activity_log` tablosu.
"""
import json

from .db import utcnow
from .schema import Resource

DESCRIPTION_LIMIT = 600          # KS GRC ile aynı
CHANGES_LIMIT = 20000
SECRET_FIELDS = {"content_base64", "password", "current_password", "new_password", "api_key"}

Resource("audit_log", "Denetim İzi", {
    "occurred_at": "TEXT NOT NULL", "actor": "TEXT NOT NULL", "auth_type": "TEXT NOT NULL",
    "method": "TEXT NOT NULL", "object_type": "TEXT NOT NULL", "object_id": "TEXT",
    "description": "TEXT", "changes_json": "TEXT",
}, module="core", api=("list",), search=("object_type", "actor"),
    read_roles={"ADMIN", "SUPPLIER_MANAGER", "AUDITOR"})


def _redact(changes):
    if isinstance(changes, dict):
        return {k: ("<gizlendi>" if k in SECRET_FIELDS else _redact(v)) for k, v in changes.items()}
    if isinstance(changes, list):
        return [_redact(v) for v in changes]
    return changes


def log(db, principal, method, object_type, object_id=None, changes=None, description=""):
    encoded = None
    if changes is not None:
        encoded = json.dumps(_redact(changes), ensure_ascii=False)
        if len(encoded) > CHANGES_LIMIT:
            keys = sorted(changes)[:200] if isinstance(changes, dict) else []
            encoded = json.dumps({"kesildi": True, "alanlar": keys}, ensure_ascii=False)
    db.execute(
        "INSERT INTO tdr_audit_log (occurred_at, actor, auth_type, method, object_type, object_id, description, "
        "changes_json) VALUES (?,?,?,?,?,?,?,?)",
        (utcnow(), principal.username, principal.auth_type, method, object_type,
         str(object_id) if object_id is not None else None,
         str(description or "")[:DESCRIPTION_LIMIT] or None, encoded))
