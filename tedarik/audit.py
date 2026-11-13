"""Denetim izi: her yazma işlemi kim, ne zaman, neyi değiştirdi bilgisiyle saklanır."""
import json

from .db import utcnow
from .schema import Resource

Resource("audit_log", "Denetim İzi", {
    "at": "TEXT NOT NULL", "actor": "TEXT NOT NULL", "auth_type": "TEXT NOT NULL", "action": "TEXT NOT NULL",
    "table_name": "TEXT NOT NULL", "record_id": "INTEGER", "changes_json": "TEXT",
}, module="core", api=("list",), search=("table_name", "actor"),
    read_roles={"ADMIN", "SUPPLIER_MANAGER", "AUDITOR"})


def log(db, principal, action, resource, record_id=None, changes=None):
    db.execute(
        "INSERT INTO tdr_audit_log (at, actor, auth_type, action, table_name, record_id, changes_json) "
        "VALUES (?,?,?,?,?,?,?)",
        (utcnow(), principal.username, principal.auth_type, action, resource, record_id,
         json.dumps(changes, ensure_ascii=False) if changes is not None else None))
