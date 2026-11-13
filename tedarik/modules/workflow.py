"""Genel iş akışı motoru: süreç koda gömülmez, veri olarak tanımlanır.

Tanım (definition_json): initial, terminal, states (kod -> etiket), transitions
(action, from, to, min_level, guards). Koruma (guard) işlevleri adla kaydedilir; parametreleri
politika tablosundan gelir. Yeni bir süreç = yeni tanım + gerekirse yeni koruma işlevi.
"""
import json

from .. import crud
from ..db import one, rows, utcnow
from ..schema import Resource, fk

M = "workflow"
GUARDS = {}

DEFINITIONS = Resource("workflow_definitions", "İş Akışı Tanımları", {
    "code": "TEXT NOT NULL", "name": "TEXT NOT NULL", "version": "INTEGER NOT NULL DEFAULT 1",
    "definition_json": "TEXT NOT NULL", "active": "INTEGER NOT NULL DEFAULT 1"},
    module=M, write="admin", unique=(("code", "version"),))

INSTANCES = Resource("workflow_instances", "İş Akışı Örnekleri", {
    "definition_id": fk("workflow_definitions"), "subject_type": "TEXT NOT NULL", "subject_id": "INTEGER NOT NULL",
    "state": "TEXT NOT NULL", "started_by": "TEXT NOT NULL", "created_at": "TEXT NOT NULL", "updated_at": "TEXT"},
    module=M, api=("list", "get"), search=("subject_type", "state"))

Resource("workflow_history", "İş Akışı Geçmişi", {
    "instance_id": fk("workflow_instances"), "from_state": "TEXT", "to_state": "TEXT NOT NULL",
    "action": "TEXT NOT NULL", "actor": "TEXT NOT NULL", "at": "TEXT NOT NULL", "comment": "TEXT"},
    module=M, api=("list",), search=("action", "actor"))

Resource("policies", "Politika Parametreleri", {
    "code": "TEXT NOT NULL UNIQUE", "value_json": "TEXT NOT NULL", "description": "TEXT"},
    module=M, write="admin", search=("code", "description"))


def _definition_rules(db, data, current, principal):
    if "definition_json" in data:
        spec = json.loads(data["definition_json"])
        if not {"initial", "states", "transitions"} <= set(spec) or spec["initial"] not in spec["states"]:
            raise crud.Invalid("Tanım initial, states ve transitions içermeli")
        for t in spec["transitions"]:
            unknown = [g if isinstance(g, str) else g.get("name") for g in t.get("guards", [])]
            unknown = [g for g in unknown if g not in GUARDS]
            if unknown or t["to"] not in spec["states"]:
                raise crud.Invalid(f"Geçersiz geçiş: {t.get('action')} (bilinmeyen durum veya koruma)")


DEFINITIONS.before_save = _definition_rules


def guard(name):
    def register(fn):
        GUARDS[name] = fn
        return fn
    return register


def policy(db, code, default=None):
    row = one(db, "SELECT value_json FROM tdr_policies WHERE code=?", (code,))
    return json.loads(row["value_json"]) if row else default


def _spec(db, definition_id):
    return json.loads(one(db, "SELECT definition_json FROM tdr_workflow_definitions WHERE id=?",
                          (definition_id,))["definition_json"])


def _record(db, instance_id, source, target, action, actor, comment=None):
    db.execute("INSERT INTO tdr_workflow_history (instance_id, from_state, to_state, action, actor, at, comment) "
               "VALUES (?,?,?,?,?,?,?)", (instance_id, source, target, action, actor, utcnow(), comment))


def start(db, code, subject_type, subject_id, principal):
    definition = one(db, "SELECT * FROM tdr_workflow_definitions WHERE code=? AND active=1 "
                         "ORDER BY version DESC LIMIT 1", (code,))
    if not definition:
        raise crud.NotFound(f"İş akışı tanımı bulunamadı: {code}")
    initial = json.loads(definition["definition_json"])["initial"]
    instance_id = crud.insert(db, INSTANCES, {
        "definition_id": definition["id"], "subject_type": subject_type, "subject_id": subject_id,
        "state": initial, "started_by": principal.username})
    _record(db, instance_id, None, initial, "start", principal.username)
    return instance_id


def available(db, instance):
    """Bulunulan durumdan yapılabilecek işlemler (arayüz düğmeleri bundan üretilir)."""
    spec = _spec(db, instance["definition_id"])
    if instance["state"] in spec.get("terminal", []):
        return []
    return [{"action": t["action"], "to": t["to"], "label": spec["states"][t["to"]]}
            for t in spec["transitions"] if t["from"] in ("*", instance["state"])]


def transition(db, instance_id, action, principal, comment=None):
    instance = crud.get(db, INSTANCES, instance_id)
    spec = _spec(db, instance["definition_id"])
    chosen = None
    if instance["state"] not in spec.get("terminal", []):
        chosen = next((t for t in spec["transitions"]
                       if t["action"] == action and t["from"] in ("*", instance["state"])), None)
    if not chosen:
        raise crud.Conflict(f"'{instance['state']}' durumunda '{action}' işlemi yapılamaz")
    if not principal.can(chosen.get("min_level", "write")):
        raise crud.Forbidden("Bu geçiş için yetkiniz yok")
    for item in chosen.get("guards", []):
        name, params = (item, {}) if isinstance(item, str) else (item["name"], item.get("params", {}))
        problem = GUARDS[name](db, instance, params)
        if problem:
            raise crud.Conflict(problem)
    db.execute("UPDATE tdr_workflow_instances SET state=?, updated_at=? WHERE id=?",
               (chosen["to"], utcnow(), instance_id))
    _record(db, instance_id, instance["state"], chosen["to"], action, principal.username, comment)
    return chosen["to"]


def history(db, instance_id):
    return rows(db, "SELECT * FROM tdr_workflow_history WHERE instance_id=? ORDER BY id", (instance_id,))
