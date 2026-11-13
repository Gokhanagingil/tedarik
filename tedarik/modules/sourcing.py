"""Kaynak bulma (varsayılan olarak kapalı; TEDARIK_MODULES'e workflow,sourcing eklenince açılır).

İhtiyaç girilir -> mevcut tedarikçilerden biri seçilir YA DA politika gereği en az N tedarikçiden teklif
toplanır -> değerlendirme -> onay. Kural (N=3) politika parametresidir; süreç adımları iş akışı tanımındadır.
"""
import json

from .. import audit, auth as authz, crud
from ..db import one, rows
from ..http import API, guard_readonly
from ..schema import RESOURCES, Resource, fk
from .core import via
from . import workflow

M = "sourcing"
REQUIRES = ("workflow",)
FLOW = "sourcing_default"

NEEDS = Resource("needs", "İş İhtiyaçları", {
    "code": "TEXT NOT NULL UNIQUE", "title": "TEXT NOT NULL", "description": "TEXT", "org_unit_id": fk("org_units"),
    "catalog_item_id": fk("catalog_items", False), "requester": "TEXT NOT NULL", "needed_by": "DATE",
    "workflow_instance_id": fk("workflow_instances", False), "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="write", api=("list", "get", "update"), search=("code", "title"),
    readonly=("requester", "workflow_instance_id"))

Resource("need_candidates", "Aday Tedarikçiler", {
    "need_id": fk("needs"), "supplier_id": fk("suppliers"), "origin": "TEXT NOT NULL DEFAULT 'existing'",
    "selected": "INTEGER NOT NULL DEFAULT 0", "note": "TEXT"},
    module=M, write="write", unique=(("need_id", "supplier_id"),), search=(),
    enums={"origin": ("existing", "new")})

Resource("quotes", "Teklifler", {
    "need_id": fk("needs"), "supplier_id": fk("suppliers"), "amount": "DECIMAL NOT NULL",
    "currency": "TEXT NOT NULL DEFAULT 'TRY'", "received_at": "DATE NOT NULL", "valid_until": "DATE",
    "document_ref": "TEXT", "note": "TEXT"}, module=M, write="write", search=("note",))

DEFINITION = {
    "initial": "draft",
    "terminal": ["completed", "cancelled"],
    "states": {"draft": "Taslak", "candidate_review": "Aday İnceleme", "quoting": "Teklif Toplama",
               "evaluation": "Değerlendirme", "approval": "Onay", "completed": "Tamamlandı", "cancelled": "İptal"},
    "transitions": [
        {"action": "submit", "from": "draft", "to": "candidate_review"},
        {"action": "select_existing", "from": "candidate_review", "to": "approval", "guards": ["existing_selected"]},
        {"action": "request_quotes", "from": "candidate_review", "to": "quoting"},
        {"action": "evaluate", "from": "quoting", "to": "evaluation",
         "guards": [{"name": "min_quotes", "params": {"policy": "sourcing.min_quotes"}}]},
        {"action": "award", "from": "evaluation", "to": "approval", "guards": ["winner_selected"]},
        {"action": "approve", "from": "approval", "to": "completed", "min_level": "manage"},
        {"action": "reject", "from": "approval", "to": "candidate_review", "min_level": "manage"},
        {"action": "cancel", "from": "*", "to": "cancelled"},
    ],
}


NEEDS.scope = lambda db, record: {record.get("org_unit_id")}
RESOURCES["need_candidates"].scope = via("needs", "need_id")
RESOURCES["quotes"].scope = via("needs", "need_id")


def _selected(db, need_id, extra=""):
    return one(db, f"SELECT COUNT(*) AS n FROM tdr_need_candidates WHERE need_id=? AND selected=1 {extra}",
               (need_id,))["n"]


@workflow.guard("existing_selected")
def existing_selected(db, instance, params):
    if _selected(db, instance["subject_id"], "AND origin='existing'") != 1:
        return "Mevcut tedarikçilerden tam olarak bir aday seçilmelidir"


@workflow.guard("min_quotes")
def min_quotes(db, instance, params):
    needed = workflow.policy(db, params.get("policy", "sourcing.min_quotes"), 3)
    have = one(db, "SELECT COUNT(DISTINCT supplier_id) AS n FROM tdr_quotes WHERE need_id=?",
               (instance["subject_id"],))["n"]
    if have < needed:
        return f"En az {needed} farklı tedarikçiden teklif gerekli (mevcut: {have})"


@workflow.guard("winner_selected")
def winner_selected(db, instance, params):
    winners = rows(db, "SELECT supplier_id FROM tdr_need_candidates WHERE need_id=? AND selected=1",
                   (instance["subject_id"],))
    if len(winners) != 1:
        return "Tam olarak bir kazanan aday seçilmelidir"
    if not one(db, "SELECT id FROM tdr_quotes WHERE need_id=? AND supplier_id=?",
               (instance["subject_id"], winners[0]["supplier_id"])):
        return "Seçilen tedarikçinin teklifi bulunmuyor"


def create_need(c):
    authz.check(c.principal, NEEDS, "write")
    guard_readonly(NEEDS, c.body)
    need_id = crud.insert(c.db, NEEDS, {**c.body, "requester": c.principal.username}, c.principal)
    instance_id = workflow.start(c.db, FLOW, "needs", need_id, c.principal)
    c.db.execute("UPDATE tdr_needs SET workflow_instance_id=? WHERE id=?", (instance_id, need_id))
    audit.log(c.db, c.principal, "CREATE", "needs", need_id, c.body)
    return 201, {"id": need_id, "state": DEFINITION["initial"]}


def need_context(c):
    authz.check(c.principal, NEEDS, "read")
    need = crud.get(c.db, NEEDS, c.params["id"])
    instance = crud.get(c.db, workflow.INSTANCES, need["workflow_instance_id"])
    need["state"] = instance["state"]
    need["actions"] = workflow.available(c.db, instance)
    need["history"] = workflow.history(c.db, instance["id"])
    need["candidates"] = rows(c.db, """SELECT k.*, s.name AS supplier_name FROM tdr_need_candidates k
        JOIN tdr_suppliers s ON s.id=k.supplier_id WHERE k.need_id=?""", (need["id"],))
    need["quotes"] = rows(c.db, "SELECT * FROM tdr_quotes WHERE need_id=? ORDER BY amount", (need["id"],))
    return need


def need_transition(c):
    authz.check(c.principal, NEEDS, "write")
    need = crud.get(c.db, NEEDS, c.params["id"])
    crud.check_scope(c.db, NEEDS, c.principal, need)
    state = workflow.transition(c.db, need["workflow_instance_id"], c.body["action"], c.principal,
                                c.body.get("comment"))
    audit.log(c.db, c.principal, "TRANSITION", "needs", need["id"], {"action": c.body["action"], "to": state})
    return {"id": need["id"], "state": state}


def register(app):
    app.route("POST", API + "/needs", create_need)
    app.route("GET", API + "/needs/{id}/context", need_context)
    app.route("POST", API + "/needs/{id}/transition", need_transition)


def seed(db):
    db.execute("INSERT INTO tdr_workflow_definitions (code, name, version, definition_json) "
               "VALUES (?,?,1,?) ON CONFLICT DO NOTHING", (FLOW, "Kaynak Bulma (varsayılan)", json.dumps(DEFINITION, ensure_ascii=False)))
    db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
               ("sourcing.min_quotes", "3", "Mevcut tedarikçi seçilmediğinde alınması gereken en az teklif sayısı"))
