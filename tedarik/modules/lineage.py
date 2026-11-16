"""Veri yönetişimi Faz 4 — soy kütüğü ve etki analizi (K-031). `datagov` modülünün parçasıdır.

- Bağlantı (edge): kaynak tablo[.kolon] → hedef tablo[.kolon]; tür (doğrudan, dönüşüm, toplama, dolaylı), dönüşüm açıklaması,
  isteğe bağlı veri akış işi (ETL / ELT işi, Airflow DAG görevi, dbt projesi …). Kolon boşsa bağlantı tablo düzeyindedir:
  hedef tablonun tamamı kaynaktan etkilenir. Elle, Excel/CSV ile, OpenLineage olaylarından veya dbt manifestinden gelir.
  Otomatik gelen bağlantı her görüldüğünde `last_seen_at` güncellenir; dbt manifestinde artık bulunmayan bağlantı
  "kaldırıldı" olur (silinmez).
- OpenLineage alıcısı: Airflow, Spark, dbt ve Flink'in yayımladığı açık standart olaylar, toplayıcı anahtarıyla
  `/api/tdr/collector/openlineage` uç noktasına gelir (HTTP aktarımı, `Authorization: Bearer` veya `X-Collector-Key`).
  Veri seti (namespace + ad) kataloğa kaynağın `lineage_namespace` değeriyle eşlenir; eşlenemeyen veri setleri listelenir,
  eşleme tanımlanınca saklanan olaylar yeniden işlenir. `columnLineage` yüzü kolon düzeyi bağlantı üretir. Olayın yalnızca
  veri seti adları ve kolon eşlemesi saklanır; diğer yüzler (şema, istatistik, SQL) saklanmaz.
- dbt manifesti: model, seed, snapshot ve kaynaklar arasındaki bağımlılık tablo düzeyinde; isteğe bağlı olarak boş kaynak
  açıklamaları dbt açıklamalarıyla doldurulur. SQL'den kolon düzeyi çıkarım SQL ayrıştırıcı bağımlılığı (onay bekliyor) ister.
- Etki analizi: bir tablo veya kolon değişirse aşağı akıştaki tablolar, raporlar ve anlamsal modeller, sistemler, BİA
  süreçleri, işleme faaliyetleri (KVKK), kontroller, sözlük terimleri, riskler ve bildirilecek kişiler. Etki raporu CSV olarak
  alınır ve sahiplere "planlanan değişiklik" bildirimi gönderilebilir. Akış şeması aynı grafikten çizilir.
"""
import csv
import io
import json
import re
from collections import Counter, OrderedDict, deque

from .. import audit, auth as authz, crud
from ..db import fold, one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY, Raw
from ..labels import CHOICES
from ..schema import Resource, fk
from .datagov import (COLUMNS, EFF_COLS, EFFECTIVE, M, SOURCES, TABLES, _ids, _notify, _payload, _processes, _qualified,
                      _read_any, _table_units, _text, _writable, norm_header)

KINDS = ("direct", "transform", "aggregate", "indirect", "other")
METHODS = ("manual", "excel", "openlineage", "dbt")
SYSTEMS = ("airflow", "spark", "dbt", "flink", "ssis", "adf", "sap_ds", "informatica", "power_bi", "script", "manual", "other")
RUN_STATES = ("START", "RUNNING", "COMPLETE", "FAIL", "ABORT", "OTHER")
MAX_NODES = 150
MAX_IMPACT = 2000

JOBS = Resource("lineage_jobs", "Veri Akış İşleri", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "system": "TEXT NOT NULL DEFAULT 'other'", "namespace": "TEXT",
    "description": "TEXT", "owner": "TEXT", "schedule_note": "TEXT", "ci_id": fk("cmdb_cis", False),
    "process_id": fk("processes", False), "last_run_at": "TIMESTAMP", "last_run_state": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'active'", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="AKS", write="manage", readonly=("last_run_at", "last_run_state"),
    unique=(("namespace", "name"),), search=("code", "name", "namespace"),
    enums={"system": SYSTEMS, "status": ("active", "retired"), "last_run_state": RUN_STATES})
EDGES = Resource("lineage_edges", "Soy Kütüğü Bağlantıları", {
    "source_table_id": fk("data_tables"), "source_column_id": fk("data_columns", False),
    "target_table_id": fk("data_tables"), "target_column_id": fk("data_columns", False),
    "kind": "TEXT NOT NULL DEFAULT 'direct'", "transformation": "TEXT", "job_id": fk("lineage_jobs", False),
    "method": "TEXT NOT NULL DEFAULT 'manual'", "status": "TEXT NOT NULL DEFAULT 'active'", "note": "TEXT",
    "first_seen_at": "TIMESTAMP", "last_seen_at": "TIMESTAMP", "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"},
    module=M, write="write", search=("transformation", "note"),
    readonly=("method", "first_seen_at", "last_seen_at", "created_by"),
    enums={"kind": KINDS, "method": METHODS, "status": ("active", "removed")})
EVENTS = Resource("lineage_events", "OpenLineage Olayları", {
    "collector_id": fk("data_collectors", False), "event_type": "TEXT", "event_time": "TEXT", "run_id": "TEXT",
    "job_id": fk("lineage_jobs", False), "job_namespace": "TEXT", "job_name": "TEXT", "producer": "TEXT",
    "datasets_json": "TEXT", "edges_new": "INTEGER NOT NULL DEFAULT 0", "edges_seen": "INTEGER NOT NULL DEFAULT 0",
    "unresolved_json": "TEXT", "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), immutable=True, search=("job_name", "job_namespace"))
Resource("data_table_controls", "Veri varlığı kontrolleri", {
    "table_id": fk("data_tables"), "control_id": fk("controls"), "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL"},
    module=M, unique=(("table_id", "control_id"),), api=(), search=())


# ------------------------------------------------------------------ kurallar

def _table(db, table_id):
    return one(db, "SELECT * FROM tdr_data_tables WHERE id=?", (table_id,)) if table_id else None


def _edge_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    for side in ("source", "target"):
        tid, cid = merged.get(f"{side}_table_id"), merged.get(f"{side}_column_id")
        if not _table(db, tid):
            raise crud.Invalid(("Kaynak" if side == "source" else "Hedef") + " tablo bulunamadı")
        if cid and not one(db, "SELECT 1 AS x FROM tdr_data_columns WHERE id=? AND table_id=?", (cid, tid)):
            raise crud.Invalid(("Kaynak" if side == "source" else "Hedef") + " kolon bu tabloya ait değil")
    if merged["source_table_id"] == merged["target_table_id"] and (merged.get("source_column_id") or 0) == (merged.get("target_column_id") or 0):
        raise crud.Invalid("Kaynak ve hedef aynı olamaz")
    if bool(merged.get("source_column_id")) != bool(merged.get("target_column_id")):
        raise crud.Invalid("Kolon düzeyinde bağlantıda kaynak ve hedef kolon birlikte seçilir; tablo düzeyinde ikisi de boş kalır")
    found = _find_edge(db, merged["source_table_id"], merged.get("source_column_id"), merged["target_table_id"],
                       merged.get("target_column_id"))
    if found and (not current or found["id"] != current["id"]):
        raise crud.Conflict("Bu bağlantı zaten var")
    if current is None:
        now = utcnow()
        data.setdefault("method", "manual")
        data.update(first_seen_at=now, last_seen_at=now, created_by=principal.username if principal else "system")


def _edge_units(db, record):
    target = _table(db, record.get("target_table_id"))
    return _table_units(db, target) if target else set()


EDGES.before_save = _edge_rules
EDGES.scope = _edge_units


def _find_edge(db, st, sc, tt, tc):
    return one(db, """SELECT * FROM tdr_lineage_edges WHERE source_table_id=? AND COALESCE(source_column_id,0)=?
        AND target_table_id=? AND COALESCE(target_column_id,0)=?""", (st, sc or 0, tt, tc or 0))


def upsert_edge(db, st, sc, tt, tc, *, kind="direct", transformation=None, job_id=None, method="manual", principal=None,
                now=None, dry_run=False, note=None):
    """Otomatik ve toplu bağlantı: yoksa ekler ('new'), varsa görüldü işaretler ('seen'). Elle bağlantıya dokunmaz."""
    if st == tt and (sc or 0) == (tc or 0):
        return None
    now = now or utcnow()
    found = _find_edge(db, st, sc, tt, tc)
    if found:
        if not dry_run:
            sets = {"last_seen_at": now, "status": "active"}
            if job_id and not found["job_id"]:
                sets["job_id"] = job_id
            if transformation and not found["transformation"]:
                sets["transformation"] = transformation[:2000]
            db.execute(f"UPDATE tdr_lineage_edges SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?",
                       (*sets.values(), now, found["id"]))
        return "seen" if found["status"] == "active" else "restored"
    if not dry_run:
        db.execute("""INSERT INTO tdr_lineage_edges (source_table_id, source_column_id, target_table_id, target_column_id, kind,
            transformation, job_id, method, status, note, first_seen_at, last_seen_at, created_by, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (st, sc, tt, tc, kind if kind in KINDS else "other", (transformation or "")[:2000] or None, job_id, method,
                    "active", (note or "")[:2000] or None, now, now, principal.username if principal else "system", now))
    return "new"


# ------------------------------------------------------------------ katalog eşleme

def _namespaces(value):
    return [n.strip().rstrip("/").lower() for n in re.split(r"[,\n]", value or "") if n.strip()]


def _find_table(db, source_id, schema, name):
    """Kaynakta şema + ad ile (büyük/küçük harf duyarsız) tablo; şema boşsa ad tekil olmalı."""
    if not name:
        return None
    if schema:
        hit = one(db, "SELECT * FROM tdr_data_tables WHERE source_id=? AND LOWER(schema_name)=? AND LOWER(name)=? "
                      "AND status<>'removed'", (source_id, schema.lower(), name.lower()))
        if hit:
            return hit
    found = rows(db, "SELECT * FROM tdr_data_tables WHERE source_id=? AND LOWER(name)=? AND status<>'removed'",
                 (source_id, name.lower()))
    return found[0] if len(found) == 1 else None


def resolve_dataset(db, namespace, name, fallback_source_id=None, sources=None):
    """OpenLineage veri seti → katalog tablosu. Ad 'db.şema.tablo', 'şema.tablo', 'tablo' veya dosya yolu olabilir."""
    sources = sources if sources is not None else rows(
        db, "SELECT id, lineage_namespace FROM tdr_data_sources WHERE status='active'")
    ns = (namespace or "").strip().rstrip("/").lower()
    candidates = [s["id"] for s in sources if ns and any(ns == n or ns.startswith(n + "/") for n in _namespaces(s["lineage_namespace"]))]
    if not candidates and fallback_source_id:
        candidates = [fallback_source_id]
    text = str(name or "").strip()
    if "/" in text:                                  # dosya yolu: son parça, uzantısız
        text = text.rstrip("/").split("/")[-1].rsplit(".", 1)[0]
    parts = [p.strip('"`[]') for p in text.split(".") if p]
    if not parts:
        return None
    for sid in candidates:
        hit = _find_table(db, sid, parts[-2] if len(parts) > 1 else "", parts[-1])
        if hit:
            return hit
    return None


def _column_id(db, table_id, name):
    row = one(db, "SELECT id FROM tdr_data_columns WHERE table_id=? AND LOWER(name)=? AND status='active'",
              (table_id, str(name or "").lower()))
    return row["id"] if row else None


# ------------------------------------------------------------------ OpenLineage

OL_KIND = {("DIRECT", "IDENTITY"): "direct", ("DIRECT", "TRANSFORMATION"): "transform",
           ("DIRECT", "AGGREGATION"): "aggregate"}


def _system(producer):
    text = (producer or "").lower()
    for key in ("airflow", "spark", "dbt", "flink"):
        if key in text:
            return key
    return "other"


def _job(db, namespace, name, system, event_time=None, state=None):
    job = one(db, "SELECT * FROM tdr_lineage_jobs WHERE namespace=? AND name=?", (namespace, name))
    if job is None:
        jid = crud.insert(db, JOBS, {"name": name[:300], "namespace": namespace[:300], "system": system, "status": "active"})
        job = one(db, "SELECT * FROM tdr_lineage_jobs WHERE id=?", (jid,))
    if event_time or state:
        db.execute("UPDATE tdr_lineage_jobs SET last_run_at=?, last_run_state=?, updated_at=? WHERE id=?",
                   (event_time or utcnow(), state if state in RUN_STATES else "OTHER", utcnow(), job["id"]))
    return job


def _datasets(event):
    """Olaydan saklanacak en az bilgi: veri seti adları ve kolon eşlemesi (columnLineage)."""
    def pick(d, outputs=False):
        out = {"namespace": str(d.get("namespace") or "")[:300], "name": str(d.get("name") or "")[:500]}
        if outputs:
            facet = ((d.get("facets") or {}).get("columnLineage") or {}).get("fields")
            if isinstance(facet, dict):
                out["columns"] = {str(k)[:200]: [{"namespace": str(i.get("namespace") or "")[:300],
                                                  "name": str(i.get("name") or "")[:500], "field": str(i.get("field") or "")[:200],
                                                  "transformations": [{"type": t.get("type"), "subtype": t.get("subtype")}
                                                                      for t in (i.get("transformations") or [])[:3]
                                                                      if isinstance(t, dict)]}
                                                 for i in (v.get("inputFields") or [])[:50] if isinstance(i, dict)]
                                  for k, v in list(facet.items())[:500] if isinstance(v, dict)}
        return out
    inputs = [pick(d) for d in (event.get("inputs") or [])[:200] if isinstance(d, dict)]
    outputs = [pick(d, True) for d in (event.get("outputs") or [])[:200] if isinstance(d, dict)]
    return {"inputs": inputs, "outputs": outputs}


def _apply_datasets(db, data, job_id, fallback_source_id, principal, now):
    sources = rows(db, "SELECT id, lineage_namespace FROM tdr_data_sources WHERE status='active'")
    cache, unresolved, counts = {}, {}, Counter()

    def resolve(ds):
        key = (ds["namespace"], ds["name"])
        if key not in cache:
            cache[key] = resolve_dataset(db, ds["namespace"], ds["name"], fallback_source_id, sources)
            if cache[key] is None:
                unresolved[key] = unresolved.get(key, 0) + 1
        return cache[key]

    ins = [(ds, resolve(ds)) for ds in data["inputs"]]
    for out in data["outputs"]:
        target = resolve(out)
        if target is None:
            continue
        # Kolon eşlemesi verilen girdi için tablo düzeyinde bağlantı kurulmaz: etki analizi kolon düzeyinde kalır.
        mapped_inputs = {(i["namespace"], i["name"]) for fields in (out.get("columns") or {}).values() for i in fields}
        for ds, source in ins:
            if source is not None and (ds["namespace"], ds["name"]) not in mapped_inputs:
                counts[upsert_edge(db, source["id"], None, target["id"], None, kind="transform", job_id=job_id,
                                   method="openlineage", principal=principal, now=now)] += 1
        for field, mapped in (out.get("columns") or {}).items():
            tcol = _column_id(db, target["id"], field)
            if tcol is None:
                counts["column_unresolved"] += 1
                continue
            for i in mapped:
                source = resolve(i)
                scol = _column_id(db, source["id"], i["field"]) if source else None
                if scol is None:
                    counts["column_unresolved"] += 1
                    continue
                t = (i.get("transformations") or [{}])[0] or {}
                kind = "indirect" if t.get("type") == "INDIRECT" else OL_KIND.get((t.get("type"), t.get("subtype")), "direct")
                counts[upsert_edge(db, source["id"], scol, target["id"], tcol, kind=kind, job_id=job_id, method="openlineage",
                                   principal=principal, now=now,
                                   transformation=(f"{t.get('type')}/{t.get('subtype')}" if t.get("type") else None))] += 1
    return counts, [{"namespace": k[0], "name": k[1]} for k in unresolved]


def ingest(db, collector, event, principal):
    if not isinstance(event, dict) or not isinstance(event.get("job"), dict):
        raise crud.Invalid("OpenLineage olayı bekleniyor (job, run, eventType)")
    job_info, run = event["job"], event.get("run") if isinstance(event.get("run"), dict) else {}
    namespace, name = str(job_info.get("namespace") or "varsayilan")[:300], str(job_info.get("name") or "")[:300]
    if not name:
        raise crud.Invalid("İş adı (job.name) gerekli")
    state = str(event.get("eventType") or "OTHER").upper()
    when = str(event.get("eventTime") or utcnow())[:40]
    job = _job(db, namespace, name, _system(event.get("producer")), when, state)
    data = _datasets(event)
    now = utcnow()
    counts, unresolved = Counter(), []
    if state not in ("FAIL", "ABORT") and data["outputs"]:
        counts, unresolved = _apply_datasets(db, data, job["id"], collector["source_id"] if collector else None, principal, now)
    if data["inputs"] or data["outputs"]:
        db.execute("""INSERT INTO tdr_lineage_events (collector_id, event_type, event_time, run_id, job_id, job_namespace, job_name,
            producer, datasets_json, edges_new, edges_seen, unresolved_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (collector["id"] if collector else None, state, when, str(run.get("runId") or "")[:100] or None, job["id"],
                    namespace, name, str(event.get("producer") or "")[:300] or None, json.dumps(data, ensure_ascii=False),
                    counts["new"] + counts["restored"], counts["seen"], json.dumps(unresolved, ensure_ascii=False) if unresolved else None,
                    now))
    return {"job": job["code"], "edges_new": counts["new"] + counts["restored"], "edges_seen": counts["seen"],
            "unresolved": unresolved, "columns_unresolved": counts["column_unresolved"]}


def openlineage_receive(c):
    from .collection import _machine
    col = _machine(c)
    if col["connector"] != "openlineage":
        raise crud.Forbidden("Bu toplayıcı OpenLineage alıcısı değil; toplayıcı eklerken 'OpenLineage alıcısı' seçin")
    events = c.body.get("events") if isinstance(c.body.get("events"), list) else [c.body]
    out = {"accepted": 0, "edges_new": 0, "edges_seen": 0, "unresolved": []}
    for event in events[:500]:
        r = ingest(c.db, col, event, c.principal)
        out["accepted"] += 1
        out["edges_new"] += r["edges_new"]
        out["edges_seen"] += r["edges_seen"]
        out["unresolved"] += [u for u in r["unresolved"] if u not in out["unresolved"]][:50]
    now = utcnow()
    c.db.execute("UPDATE tdr_data_collectors SET last_seen_at=?, last_push_at=?, last_result='ok', last_message=?, "
                 "overdue_notified_at=NULL, updated_at=? WHERE id=?",
                 (now, now, f"OpenLineage: {out['accepted']} olay, {out['edges_new']} yeni bağlantı", now, col["id"]))
    if out["edges_new"]:
        audit.log(c.db, c.principal, "LINEAGE", "lineage_edges", 0, {"collector": col["code"], **out})
    return out


def unresolved_list(c):
    authz.check(c.principal, EDGES, "read")
    agg = {}
    for e in rows(c.db, "SELECT unresolved_json, created_at FROM tdr_lineage_events WHERE unresolved_json IS NOT NULL "
                        "ORDER BY id DESC LIMIT 2000"):
        for u in json.loads(e["unresolved_json"]):
            key = (u["namespace"], u["name"])
            item = agg.setdefault(key, {**u, "events": 0, "last_seen": e["created_at"]})
            item["events"] += 1
    sources = rows(c.db, "SELECT id, lineage_namespace FROM tdr_data_sources WHERE status='active'")
    items = [u for u in agg.values() if resolve_dataset(c.db, u["namespace"], u["name"], None, sources) is None]
    return {"items": sorted(items, key=lambda u: (-u["events"], u["namespace"], u["name"]))[:200]}


def reprocess(c):
    """Eşleme tanımlandıktan sonra eşlenemeyen veri seti içeren olayları yeniden işler."""
    authz.require_human(c.principal)
    authz.check(c.principal, EDGES, "write")
    authz.require(c.principal, "manage")
    total = Counter()
    for e in rows(c.db, "SELECT * FROM tdr_lineage_events WHERE unresolved_json IS NOT NULL AND event_type NOT IN ('FAIL','ABORT') "
                        "ORDER BY id DESC LIMIT 2000"):
        col = one(c.db, "SELECT id, source_id FROM tdr_data_collectors WHERE id=?", (e["collector_id"],)) if e["collector_id"] else None
        counts, _ = _apply_datasets(c.db, json.loads(e["datasets_json"]), e["job_id"], col["source_id"] if col else None,
                                    c.principal, utcnow())
        total.update(counts)
        total["events"] += 1
    audit.log(c.db, c.principal, "REPROCESS", "lineage_events", 0, dict(total))
    return {"events": total["events"], "edges_new": total["new"] + total["restored"], "edges_seen": total["seen"]}


# ------------------------------------------------------------------ dbt manifesti

def dbt_import(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "manage")
    source = crud.get(c.db, SOURCES, int(c.body.get("source_id") or 0))
    filename, raw = _payload(c)
    try:
        manifest = json.loads(_text(raw))
    except ValueError:
        raise crud.Invalid("manifest.json okunamadı (JSON değil)") from None
    meta = manifest.get("metadata") if isinstance(manifest, dict) else None
    if not isinstance(meta, dict) or "manifest" not in str(meta.get("dbt_schema_version") or ""):
        raise crud.Invalid("dbt manifest dosyası bekleniyor (target/manifest.json)")
    dry, adopt = bool(c.body.get("dry_run")), bool(c.body.get("adopt_descriptions"))
    project = str(meta.get("project_name") or manifest.get("metadata", {}).get("project_id") or "dbt")[:200]
    nodes = {uid: n for uid, n in (manifest.get("nodes") or {}).items()
             if isinstance(n, dict) and n.get("resource_type") in ("model", "seed", "snapshot")}
    nodes.update({uid: n for uid, n in (manifest.get("sources") or {}).items() if isinstance(n, dict)})
    resolved, unresolved = {}, []
    for uid, n in nodes.items():
        name = n.get("alias") or n.get("identifier") or n.get("name")
        table = _find_table(c.db, source["id"], n.get("schema") or "", name)
        resolved[uid] = table
        if table is None:
            unresolved.append(_qualified(n.get("schema") or "", name or uid))
    job = None if dry else _job(c.db, f"dbt://{project}", f"dbt projesi: {project}", "dbt", utcnow(), "COMPLETE")
    now, counts, seen_ids = utcnow(), Counter(), set()
    for uid, n in nodes.items():
        if n.get("resource_type") not in ("model", "snapshot") or resolved.get(uid) is None:
            continue
        target = resolved[uid]
        materialized = (n.get("config") or {}).get("materialized") or n.get("resource_type")
        for parent in (n.get("depends_on") or {}).get("nodes") or []:
            source_table = resolved.get(parent)
            if source_table is None:
                continue
            result = upsert_edge(c.db, source_table["id"], None, target["id"], None, kind="transform",
                                 transformation=f"dbt {n.get('resource_type')} {n.get('name')} ({materialized})",
                                 job_id=job["id"] if job else None, method="dbt", principal=c.principal, now=now, dry_run=dry)
            counts[result] += 1
            if not dry:
                e = _find_edge(c.db, source_table["id"], None, target["id"], None)
                seen_ids.add(e["id"])
    removed = 0
    if not dry:
        for e in rows(c.db, "SELECT id FROM tdr_lineage_edges WHERE method='dbt' AND job_id=? AND status='active'", (job["id"],)):
            if e["id"] not in seen_ids:
                c.db.execute("UPDATE tdr_lineage_edges SET status='removed', updated_at=? WHERE id=?", (now, e["id"]))
                removed += 1
    described = 0
    if adopt:
        for uid, n in nodes.items():
            table = resolved.get(uid)
            if table is None:
                continue
            if n.get("description") and not table["technical_description"]:
                described += 1
                if not dry:
                    c.db.execute("UPDATE tdr_data_tables SET technical_description=?, updated_at=? WHERE id=?",
                                 (str(n["description"])[:2000], now, table["id"]))
            for cname, col in (n.get("columns") or {}).items():
                if not isinstance(col, dict) or not col.get("description"):
                    continue
                row = one(c.db, "SELECT id, technical_description FROM tdr_data_columns WHERE table_id=? AND LOWER(name)=?",
                          (table["id"], str(cname).lower()))
                if row and not row["technical_description"]:
                    described += 1
                    if not dry:
                        c.db.execute("UPDATE tdr_data_columns SET technical_description=?, updated_at=? WHERE id=?",
                                     (str(col["description"])[:2000], now, row["id"]))
    summary = {"project": project, "nodes": len(nodes), "resolved": sum(1 for t in resolved.values() if t),
               "edges_new": counts["new"] + counts["restored"], "edges_seen": counts["seen"], "edges_removed": removed,
               "descriptions": described, "unresolved": sorted(set(unresolved))[:100], "unresolved_count": len(set(unresolved)),
               "dry_run": dry}
    if not dry:
        audit.log(c.db, c.principal, "IMPORT_DBT", "data_sources", source["id"], {k: v for k, v in summary.items() if k != "unresolved"})
    return summary


# ------------------------------------------------------------------ Excel / CSV

LINEAGE_HEADERS = OrderedDict([
    ("source_system", "Kaynak sistem"), ("source_schema", "Kaynak şema"), ("source_table", "Kaynak tablo"),
    ("source_column", "Kaynak kolon"), ("target_system", "Hedef sistem"), ("target_schema", "Hedef şema"),
    ("target_table", "Hedef tablo"), ("target_column", "Hedef kolon"), ("kind", "Tür"), ("transformation", "Dönüşüm"),
    ("job", "Veri akış işi"), ("note", "Not")])
_ALIAS = {norm_header(label): key for key, label in LINEAGE_HEADERS.items()}
_ALIAS.update({norm_header(k): k for k in LINEAGE_HEADERS})
_ALIAS.update({norm_header(k): v for k, v in (("Kaynak", "source_system"), ("Hedef", "target_system"), ("İş", "job"),
                                              ("Dönüşüm açıklaması", "transformation"), ("Bağlantı türü", "kind"))})


def _source_lookup(db):
    out = {}
    for s in rows(db, "SELECT id, code, name FROM tdr_data_sources"):
        out[fold(s["code"] or "")] = s["id"]
        out[fold(s["name"])] = s["id"]
    return out


def _kind(value):
    text = fold(str(value or "").strip())
    if not text:
        return "direct"
    for key, label in CHOICES["lineage_edges.kind"].items():
        if text in (key, fold(label), fold(label.split(" (")[0])):
            return key
    raise crud.Invalid(f"Tür tanınmadı: {value} (doğrudan, dönüşüm, toplama, dolaylı, diğer)")


def lineage_import(c):
    authz.require_human(c.principal)
    authz.check(c.principal, EDGES, "write")
    filename, raw = _payload(c)
    headers, records = _read_any(filename, raw)
    keys = [_ALIAS.get(norm_header(h)) for h in headers]
    missing = [LINEAGE_HEADERS[k] for k in ("source_system", "source_table", "target_system", "target_table") if k not in keys]
    if missing:
        raise crud.Invalid("Eksik sütun: " + ", ".join(missing))
    dry = bool(c.body.get("dry_run"))
    sources, jobs = _source_lookup(c.db), {}
    now, counts, errors = utcnow(), Counter(), []
    for n, rec in enumerate(records, start=2):
        row = {k: str(v).strip() for k, v in zip(keys, rec) if k and v not in (None, "")}
        if not row:
            continue
        try:
            with c.db.savepoint():
                ends = {}
                for side in ("source", "target"):
                    sid = sources.get(fold(row.get(f"{side}_system", "")))
                    if not sid:
                        raise crud.Invalid(f"{'Kaynak' if side == 'source' else 'Hedef'} sistem bulunamadı: {row.get(side + '_system', '')}")
                    table = _find_table(c.db, sid, row.get(f"{side}_schema", ""), row.get(f"{side}_table"))
                    if not table:
                        raise crud.Invalid(f"Tablo katalogda yok: {_qualified(row.get(side + '_schema', ''), row.get(side + '_table', ''))}")
                    col = None
                    if row.get(f"{side}_column"):
                        col = _column_id(c.db, table["id"], row[f"{side}_column"])
                        if not col:
                            raise crud.Invalid(f"Kolon katalogda yok: {table['name']}.{row[f'{side}_column']}")
                    ends[side] = (table, col)
                if bool(ends["source"][1]) != bool(ends["target"][1]):
                    raise crud.Invalid("Kolon düzeyinde kaynak ve hedef kolon birlikte yazılır")
                crud.check_scope(c.db, EDGES, c.principal, {"target_table_id": ends["target"][0]["id"]})
                job_id = None
                if row.get("job"):
                    key = fold(row["job"])
                    if key not in jobs:
                        job = one(c.db, "SELECT id FROM tdr_lineage_jobs WHERE LOWER(code)=? OR tdr_fold(name)=?",
                                  (row["job"].lower(), key))
                        if not job and not dry:
                            job = {"id": crud.insert(c.db, JOBS, {"name": row["job"][:300], "system": "manual", "status": "active"})}
                        jobs[key] = job["id"] if job else None
                    job_id = jobs[key]
                result = upsert_edge(c.db, ends["source"][0]["id"], ends["source"][1], ends["target"][0]["id"], ends["target"][1],
                                     kind=_kind(row.get("kind")), transformation=row.get("transformation"), job_id=job_id,
                                     method="excel", principal=c.principal, now=now, dry_run=dry, note=row.get("note"))
                if result is None:
                    raise crud.Invalid("Kaynak ve hedef aynı olamaz")
                counts[result] += 1
        except (crud.Invalid, crud.Forbidden) as exc:
            counts["errors"] += 1
            if len(errors) < 100:
                errors.append({"row": n, "message": str(exc)})
    summary = {"new": counts["new"] + counts["restored"], "seen": counts["seen"], "errors": counts["errors"],
               "error_rows": errors, "dry_run": dry}
    if not dry:
        audit.log(c.db, c.principal, "IMPORT", "lineage_edges", 0, {"filename": filename, **{k: summary[k] for k in ("new", "seen", "errors")}})
    return summary


def lineage_export(c):
    authz.check(c.principal, EDGES, "read")
    data = [list(LINEAGE_HEADERS.values())]
    for e in rows(c.db, """SELECT ss.code AS s_code, st.schema_name AS s_schema, st.name AS s_table, sc.name AS s_col,
            ts.code AS t_code, tt.schema_name AS t_schema, tt.name AS t_table, tc.name AS t_col, e.kind, e.transformation,
            j.name AS job, e.note FROM tdr_lineage_edges e
            JOIN tdr_data_tables st ON st.id=e.source_table_id JOIN tdr_data_sources ss ON ss.id=st.source_id
            JOIN tdr_data_tables tt ON tt.id=e.target_table_id JOIN tdr_data_sources ts ON ts.id=tt.source_id
            LEFT JOIN tdr_data_columns sc ON sc.id=e.source_column_id LEFT JOIN tdr_data_columns tc ON tc.id=e.target_column_id
            LEFT JOIN tdr_lineage_jobs j ON j.id=e.job_id WHERE e.status='active' ORDER BY ss.code, st.name, tt.name, sc.name"""):
        data.append([e["s_code"], e["s_schema"], e["s_table"], e["s_col"] or "", e["t_code"], e["t_schema"], e["t_table"],
                     e["t_col"] or "", CHOICES["lineage_edges.kind"].get(e["kind"], e["kind"]), e["transformation"] or "",
                     e["job"] or "", e["note"] or ""])
    if c.query.get("format") == "xlsx":
        from .transfer import _xlsx
        xlsx_io = _xlsx()
        if len(data) > xlsx_io.MAX_ROWS:
            raise crud.Invalid(f"Excel en çok {xlsx_io.MAX_ROWS} satır alır; CSV kullanın")
        guide = [["Sütun", "Açıklama"], ["Kaynak sistem / Hedef sistem", "Veri kaynağının kodu (VK-…) veya adı"],
                 ["Şema, tablo, kolon", "Katalogdaki adlar; kolon boşsa bağlantı tablo düzeyindedir"],
                 ["Tür", "Doğrudan aktarım, Dönüşüm, Toplama / özet, Dolaylı, Diğer"],
                 ["Veri akış işi", "İşin kodu (AKS-…) veya adı; yoksa oluşturulur"]]
        return 200, Raw(xlsx_io.make_xlsx(OrderedDict([("Soy kütüğü", data), ("Açıklama", guide)])),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "soy-kutugu.xlsx")
    buf = io.StringIO()
    csv.writer(buf, delimiter=";").writerows(data)
    return 200, Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "soy-kutugu.csv")


# ------------------------------------------------------------------ grafik ve etki

def _adjacency(db):
    """Etkin bağlantılar: tablo düzeyinde komşuluk ve kolon eşlemeleri."""
    edges = rows(db, """SELECT e.id, e.source_table_id, e.source_column_id, e.target_table_id, e.target_column_id, e.kind,
        e.transformation, e.method, e.job_id, j.name AS job_name, sc.name AS source_column, tc.name AS target_column
        FROM tdr_lineage_edges e LEFT JOIN tdr_lineage_jobs j ON j.id=e.job_id
        LEFT JOIN tdr_data_columns sc ON sc.id=e.source_column_id LEFT JOIN tdr_data_columns tc ON tc.id=e.target_column_id
        WHERE e.status='active'""")
    down, up = {}, {}
    for e in edges:
        down.setdefault(e["source_table_id"], []).append(e)
        up.setdefault(e["target_table_id"], []).append(e)
    return edges, down, up


def _walk(start_table, start_column, nexts, limit, depth_limit):
    """Genişlik öncelikli gezinti (en kısa derinlik). Kolon düzeyindeki bağlantı yalnızca eşlenen kolonu, tablo düzeyindeki
    bağlantı hedefin tamamını taşır; odak kolonsa yalnızca o kolondan çıkan kolon bağlantıları izlenir. Bir tabloya yeni
    kolonlar ulaşırsa tablo yeniden işlenir (döngüde sonlanır: küme yalnızca büyür).
    Dönüş: {tablo: [derinlik, {kolon kimlikleri} veya None (tablonun tamamı), önceki tablo]}."""
    seen = {start_table: [0, {start_column} if start_column else None, None]}
    queue = deque([start_table])
    while queue:
        tid = queue.popleft()
        depth, cols, _ = seen[tid]
        if depth >= depth_limit:
            continue
        for e, other, here_col, there_col in nexts(tid):
            if cols is not None and here_col and here_col not in cols:
                continue
            carried = {there_col} if here_col else None
            if other == start_table:
                continue
            entry = seen.get(other)
            if entry is None:
                if len(seen) >= limit:
                    continue
                seen[other] = [depth + 1, carried, tid]
                queue.append(other)
                continue
            if entry[1] is None:
                continue
            if carried is None or not carried <= entry[1]:
                entry[1] = None if carried is None else entry[1] | carried
                queue.append(other)
    return seen


def _tables_info(db, ids):
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for t in rows(db, f"""SELECT t.id, t.name, t.schema_name, t.business_name, t.object_type, t.certified, t.status,
                t.classification, s.id AS source_id, s.code AS source_code, s.name AS source_name, s.platform, s.ci_id,
                {EFF_COLS},
                (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active'
                 AND c.personal_data IN ('personal','special')) AS personal,
                (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.status='active'
                 AND c.personal_data='special') AS special
                FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id {EFFECTIVE}
                WHERE t.id IN ({','.join('?' * len(chunk))})""", chunk):
            out[t["id"]] = t
    return out


def _is_report(t):
    return t["object_type"] in ("report", "semantic_model") or t["platform"] == "power_bi"


def _column_names(db, ids):
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {r["id"]: r["name"] for r in rows(db, f"SELECT id, name FROM tdr_data_columns WHERE id IN ({','.join('?' * len(ids))})", ids)}


def graph(c):
    authz.check(c.principal, EDGES, "read")
    table = crud.get(c.db, TABLES, int(c.query.get("table_id") or 0))
    column_id = int(c.query["column_id"]) if c.query.get("column_id") else None
    depth = max(1, min(int(c.query.get("depth") or 2), 6))
    edges, down, up = _adjacency(c.db)
    down_walk = _walk(table["id"], column_id, lambda t: [(e, e["target_table_id"], e["source_column_id"], e["target_column_id"])
                                                         for e in down.get(t, [])], MAX_NODES, depth)
    up_walk = _walk(table["id"], column_id, lambda t: [(e, e["source_table_id"], e["target_column_id"], e["source_column_id"])
                                                       for e in up.get(t, [])], MAX_NODES, depth)
    level = {tid: -d for tid, (d, _, _) in up_walk.items()}
    level.update({tid: d for tid, (d, _, _) in down_walk.items()})
    info = _tables_info(c.db, level)
    names = _column_names(c.db, {cid for w in (down_walk, up_walk) for _, cols, _ in w.values() for cid in (cols or ())})
    nodes = []
    for tid, lvl in level.items():
        t = info.get(tid)
        if not t:
            continue
        cols = (down_walk.get(tid) or up_walk.get(tid))[1]
        nodes.append({"id": tid, "name": t["name"], "schema": t["schema_name"], "business_name": t["business_name"],
                      "source": t["source_name"], "platform": t["platform"], "object_type": t["object_type"], "level": lvl,
                      "personal": t["personal"], "special": t["special"], "certified": t["certified"], "report": _is_report(t),
                      "owner": t["eff_owner"], "removed": t["status"] == "removed",
                      "columns": sorted(names.get(i, "") for i in cols) if cols else None})
    shown = set(level)
    pairs = {}
    for e in edges:
        if e["source_table_id"] in shown and e["target_table_id"] in shown and \
                level[e["target_table_id"]] > level[e["source_table_id"]]:
            key = (e["source_table_id"], e["target_table_id"])
            p = pairs.setdefault(key, {"from": key[0], "to": key[1], "columns": [], "kinds": set(), "jobs": set(), "table_level": False})
            if e["source_column"]:
                if len(p["columns"]) < 40:
                    p["columns"].append({"from": e["source_column"], "to": e["target_column"], "kind": e["kind"]})
            else:
                p["table_level"] = True
            p["kinds"].add(e["kind"])
            if e["job_name"]:
                p["jobs"].add(e["job_name"])
    links = [{**p, "kinds": sorted(p["kinds"]), "jobs": sorted(p["jobs"])} for p in pairs.values()]
    return {"focus": {"id": table["id"], "name": table["name"], "column_id": column_id,
                      "column": _column_names(c.db, [column_id]).get(column_id) if column_id else None},
            "depth": depth, "nodes": sorted(nodes, key=lambda n: (n["level"], n["source"], n["name"])), "links": links,
            "truncated": len(down_walk) >= MAX_NODES or len(up_walk) >= MAX_NODES}


def _impact(db, app, table, column_id):
    edges, down, up = _adjacency(db)
    walk = _walk(table["id"], column_id, lambda t: [(e, e["target_table_id"], e["source_column_id"], e["target_column_id"])
                                                    for e in down.get(t, [])], MAX_IMPACT, 50)
    upstream = _walk(table["id"], column_id, lambda t: [(e, e["source_table_id"], e["target_column_id"], e["source_column_id"])
                                                        for e in up.get(t, [])], MAX_IMPACT, 50)
    info = _tables_info(db, walk)
    names = _column_names(db, {cid for _, cols, _ in walk.values() for cid in (cols or ())})
    affected = []
    for tid, (depth, cols, prev) in walk.items():
        if tid == table["id"] or tid not in info:
            continue
        t = info[tid]
        path, cur = [], prev
        while cur and cur != table["id"] and len(path) < 20:
            path.append(info[cur]["name"] if cur in info else str(cur))
            cur = walk[cur][2]
        affected.append({"id": tid, "name": t["name"], "schema": t["schema_name"], "business_name": t["business_name"],
                         "source_id": t["source_id"], "source": t["source_name"], "platform": t["platform"],
                         "object_type": t["object_type"], "depth": depth, "via": list(reversed(path)),
                         "columns": sorted(names.get(i, "") for i in cols) if cols else None, "report": _is_report(t),
                         "personal": t["personal"], "special": t["special"], "certified": t["certified"],
                         "owner": t["eff_owner"], "steward": t["eff_steward"], "custodian": t["eff_custodian"]})
    affected.sort(key=lambda a: (a["depth"], a["source"], a["name"]))
    focus = _tables_info(db, [table["id"]]).get(table["id"])
    all_ids = [table["id"]] + [a["id"] for a in affected]
    systems = {}
    for a in [dict(focus, id=table["id"], source=focus["source_name"])] + affected:
        s = systems.setdefault(a["source_id"], {"id": a["source_id"], "name": a["source"], "platform": a["platform"], "tables": 0})
        s["tables"] += 1
    marks = ",".join("?" * len(all_ids))
    ci_ids = sorted({r["ci_id"] for r in rows(db, f"""SELECT DISTINCT s.ci_id FROM tdr_data_tables t JOIN tdr_data_sources s
        ON s.id=t.source_id WHERE t.id IN ({marks}) AND s.ci_id IS NOT NULL""", all_ids)})
    processes = {}
    if app.enabled("continuity") and ci_ids:
        for p in rows(db, f"""SELECT DISTINCT p.id, p.code, p.name FROM tdr_bia_applications a JOIN tdr_bias b ON b.id=a.bia_id
                JOIN tdr_processes p ON p.id=b.process_id WHERE a.ci_id IN ({','.join('?' * len(ci_ids))})""", ci_ids):
            processes[p["id"]] = {**p, "via": "BİA (uygulama)"}
    activities = rows(db, f"""SELECT DISTINCT a.id, a.code, a.name, a.process_id, a.status FROM tdr_processing_activities a
        WHERE a.id IN (SELECT activity_id FROM tdr_processing_tables WHERE table_id IN ({marks}))
        OR a.id IN (SELECT pc.activity_id FROM tdr_processing_columns pc JOIN tdr_data_columns dc ON dc.id=pc.column_id
                    WHERE dc.table_id IN ({marks})) ORDER BY a.code""", (*all_ids, *all_ids))
    for a in activities:
        if a["process_id"] and a["process_id"] not in processes:
            p = one(db, "SELECT id, code, name FROM tdr_processes WHERE id=?", (a["process_id"],))
            if p:
                processes[p["id"]] = {**p, "via": f"İşleme faaliyeti {a['code']}"}
    controls = {}
    for k in rows(db, f"""SELECT DISTINCT k.id, k.code, k.name, k.owner, m.table_id FROM tdr_data_table_controls m
            JOIN tdr_controls k ON k.id=m.control_id WHERE m.table_id IN ({marks}) AND k.active=1""", all_ids):
        controls.setdefault(k["id"], {**{x: k[x] for x in ("id", "code", "name", "owner")}, "via": "Veri varlığına bağlı"})
    if processes:
        pids = sorted(processes)
        for k in rows(db, f"""SELECT DISTINCT k.id, k.code, k.name, k.owner, p.process_id FROM tdr_control_processes p
                JOIN tdr_controls k ON k.id=p.control_id WHERE p.process_id IN ({','.join('?' * len(pids))}) AND k.active=1""", pids):
            controls.setdefault(k["id"], {**{x: k[x] for x in ("id", "code", "name", "owner")},
                                          "via": f"Süreç {processes[k['process_id']]['name']}"})
    terms = rows(db, f"""SELECT DISTINCT g.id, g.code, g.name, g.owner FROM tdr_glossary_terms g WHERE g.status<>'retired' AND
        (g.id IN (SELECT term_id FROM tdr_term_tables WHERE table_id IN ({marks})) OR g.id IN (SELECT m.term_id FROM tdr_term_columns m
         JOIN tdr_data_columns dc ON dc.id=m.column_id WHERE dc.table_id IN ({marks}))) ORDER BY g.name""", (*all_ids, *all_ids))
    risks = rows(db, f"""SELECT DISTINCT r.id, r.code, r.title, r.status FROM tdr_risk_data_tables m JOIN tdr_supplier_risks r
        ON r.id=m.risk_id WHERE m.table_id IN ({marks}) AND r.status IN ('open','in_treatment') ORDER BY r.code""", all_ids)
    from .ai_inventory import impact_systems
    ai_systems = impact_systems(db, all_ids)
    people = {}
    for a in affected:
        for role, label in (("owner", "Veri sahibi"), ("steward", "Veri yöneticisi"), ("custodian", "Teknik sorumlu")):
            if a[role]:
                p = people.setdefault(a[role], {"person": a[role], "roles": set(), "tables": 0})
                p["roles"].add(label)
                p["tables"] += 1
    for k in controls.values():
        if k["owner"]:
            people.setdefault(k["owner"], {"person": k["owner"], "roles": set(), "tables": 0})["roles"].add("Kontrol sahibi")
    for x in ai_systems:
        if x["owner"]:
            people.setdefault(x["owner"], {"person": x["owner"], "roles": set(), "tables": 0})["roles"].add("Yapay zekâ sistemi sahibi")
    return {
        "focus": {"id": table["id"], "name": table["name"], "schema": table["schema_name"], "source": focus["source_name"],
                  "column_id": column_id, "column": _column_names(db, [column_id]).get(column_id) if column_id else None,
                  "owner": focus["eff_owner"], "steward": focus["eff_steward"], "custodian": focus["eff_custodian"]},
        "affected": affected, "reports": [a for a in affected if a["report"]], "systems": sorted(systems.values(), key=lambda s: s["name"]),
        "processes": sorted(processes.values(), key=lambda p: p["name"]), "activities": activities,
        "controls": sorted(controls.values(), key=lambda k: k["code"] or ""), "terms": terms, "risks": risks,
        "ai_systems": ai_systems,
        "people": sorted(({**p, "roles": sorted(p["roles"])} for p in people.values()), key=lambda p: (-p["tables"], p["person"])),
        "upstream": len(upstream) - 1,
        "summary": {"tables": len(affected), "reports": sum(1 for a in affected if a["report"]),
                    "systems": len(systems), "personal": sum(1 for a in affected if a["personal"]),
                    "max_depth": max((a["depth"] for a in affected), default=0)},
    }


def impact(c):
    authz.check(c.principal, EDGES, "read")
    table = crud.get(c.db, TABLES, c.params["id"])
    column_id = int(c.query["column_id"]) if c.query.get("column_id") else None
    if column_id and not one(c.db, "SELECT 1 AS x FROM tdr_data_columns WHERE id=? AND table_id=?", (column_id, table["id"])):
        raise crud.Invalid("Kolon bu tabloya ait değil")
    out = _impact(c.db, c.app, table, column_id)
    out["can_notify"] = authz.can_write(c.principal, TABLES) and c.principal.auth_type not in ("api_key", "collector")
    return out


def impact_export(c):
    authz.check(c.principal, EDGES, "read")
    table = crud.get(c.db, TABLES, c.params["id"])
    column_id = int(c.query["column_id"]) if c.query.get("column_id") else None
    r = _impact(c.db, c.app, table, column_id)
    focus = r["focus"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Etki raporu", _qualified(focus["schema"], focus["name"], focus["column"]), focus["source"], utcnow()[:16]])
    w.writerow([])
    w.writerow(["Derinlik", "Sistem", "Şema", "Tablo", "İş adı", "Tür", "Etkilenen kolonlar", "Kişisel veri", "Veri sahibi",
                "Veri yöneticisi", "Teknik sorumlu", "Yol"])
    for a in r["affected"]:
        w.writerow([a["depth"], a["source"], a["schema"], a["name"], a["business_name"] or "",
                    CHOICES["data_tables.object_type"].get(a["object_type"], a["object_type"]),
                    "tümü" if a["columns"] is None else ", ".join(a["columns"]), a["personal"], a["owner"] or "",
                    a["steward"] or "", a["custodian"] or "", " → ".join([focus["name"], *a["via"], a["name"]])])
    for title, items, cols in (("Süreçler", r["processes"], ("code", "name", "via")), ("İşleme faaliyetleri", r["activities"], ("code", "name")),
                               ("Kontroller", r["controls"], ("code", "name", "owner", "via")), ("Sözlük terimleri", r["terms"], ("code", "name", "owner")),
                               ("Açık riskler", r["risks"], ("code", "title")), ("Bildirilecek kişiler", r["people"], ("person", "roles"))):
        w.writerow([])
        w.writerow([title])
        for item in items:
            w.writerow([", ".join(item[k]) if isinstance(item[k], list) else item[k] or "" for k in cols])
    audit.log(c.db, c.principal, "EXPORT", "data_tables", table["id"], {"report": "impact", "column_id": column_id})
    return 200, Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", f"etki-{table['name']}.csv")


def impact_notify(c):
    """Planlanan değişikliği aşağı akıştaki sahiplere bildirir (değişiklik talebi öncesi)."""
    table = crud.get(c.db, TABLES, c.params["id"])
    _writable(c, TABLES, table)
    note = str(c.body.get("note") or "").strip()
    if len(note) < 10:
        raise crud.Invalid("Planlanan değişikliği açıklayın (en az 10 karakter)")
    column_id = int(c.body["column_id"]) if c.body.get("column_id") else None
    r = _impact(c.db, c.app, table, column_id)
    target = _qualified(r["focus"]["schema"], r["focus"]["name"], r["focus"]["column"])
    when = str(c.body.get("planned_on") or "").strip()[:10]
    lines = [f"• {_qualified(a['schema'], a['name'])} ({a['source']})" + (" — rapor/model" if a["report"] else "")
             for a in r["affected"][:40]]
    sent = 0
    for p in r["people"]:
        sent += _notify(c.db, "catalog.impact", f"Planlanan veri değişikliği: {target}",
                        f"{target} ({r['focus']['source']}) üzerinde planlanan değişiklik" + (f" ({when})" if when else "") +
                        f":\n{note}\n\nAşağı akışta etkilenebilecek {len(r['affected'])} nesne var; sizin sorumluluğunuzdaki "
                        f"rollere göre ({', '.join(p['roles'])}) gözden geçirin:\n" + "\n".join(lines),
                        users=[p["person"]], link=f"#/impact/{table['id']}" + (f"?c={column_id}" if column_id else ""),
                        object_type="data_tables", object_id=table["id"],
                        dedupe=f"impact:{table['id']}:{column_id or 0}:{fold(note)[:40]}")
    audit.log(c.db, c.principal, "IMPACT_NOTICE", "data_tables", table["id"],
              {"column_id": column_id, "note": note[:500], "people": [p["person"] for p in r["people"]], "queued": sent})
    return {"people": len(r["people"]), "queued": sent}


# ------------------------------------------------------------------ tablo ve kolon ekranları

def _edge_rows(db, where, args, order="ss.name, st.name, tt.name, sc.name", limit=2000):
    return rows(db, f"""SELECT e.*, st.name AS source_table, st.schema_name AS source_schema, ss.name AS source_system,
        tt.name AS target_table, tt.schema_name AS target_schema, ts.name AS target_system, sc.name AS source_column,
        tc.name AS target_column, j.code AS job_code, j.name AS job_name, st.object_type AS source_type, tt.object_type AS target_type
        FROM tdr_lineage_edges e JOIN tdr_data_tables st ON st.id=e.source_table_id JOIN tdr_data_sources ss ON ss.id=st.source_id
        JOIN tdr_data_tables tt ON tt.id=e.target_table_id JOIN tdr_data_sources ts ON ts.id=tt.source_id
        LEFT JOIN tdr_data_columns sc ON sc.id=e.source_column_id LEFT JOIN tdr_data_columns tc ON tc.id=e.target_column_id
        LEFT JOIN tdr_lineage_jobs j ON j.id=e.job_id WHERE {where} ORDER BY {order} LIMIT {int(limit)}""", args)


def table_lineage(c):
    authz.check(c.principal, EDGES, "read")
    t = crud.get(c.db, TABLES, c.params["id"])
    edges = _edge_rows(c.db, "e.status='active' AND (e.source_table_id=? OR e.target_table_id=?)", (t["id"], t["id"]))

    def group(here, prefix):
        """here: bu tablonun bağlantıdaki yeri; prefix: karşı uç (source / target)."""
        out = {}
        for e in edges:
            other = e[f"{prefix}_table_id"]
            if e[here] != t["id"] or other == t["id"]:
                continue
            g = out.setdefault(other, {"id": other, "name": e[f"{prefix}_table"], "schema": e[f"{prefix}_schema"],
                                       "system": e[f"{prefix}_system"], "object_type": e[f"{prefix}_type"], "columns": 0,
                                       "table_level": False, "jobs": set()})
            if e["source_column_id"]:
                g["columns"] += 1
            else:
                g["table_level"] = True
            if e["job_name"]:
                g["jobs"].add(e["job_name"])
        return sorted(({**g, "jobs": sorted(g["jobs"])} for g in out.values()), key=lambda g: (g["system"], g["name"]))
    upstream = group("target_table_id", "source")
    downstream = group("source_table_id", "target")
    controls = rows(c.db, """SELECT k.id, k.code, k.name, k.owner FROM tdr_data_table_controls m JOIN tdr_controls k
        ON k.id=m.control_id WHERE m.table_id=? ORDER BY k.code""", (t["id"],))
    can = authz.can_write(c.principal, EDGES) and c.principal.auth_type not in ("api_key", "collector")
    if can and c.principal.role == "UNIT_USER":
        can = bool(_table_units(c.db, t) & c.principal.units)
    return {"upstream": upstream, "downstream": downstream, "edges": edges, "controls": controls, "can_edit": can}


def column_lineage(c):
    authz.check(c.principal, EDGES, "read")
    col = crud.get(c.db, COLUMNS, c.params["id"])
    edges = _edge_rows(c.db, "e.status='active' AND (e.source_column_id=? OR e.target_column_id=? OR (e.source_column_id IS NULL "
                             "AND (e.source_table_id=? OR e.target_table_id=?)))", (col["id"], col["id"], col["table_id"], col["table_id"]))
    return {"upstream": [e for e in edges if e["target_column_id"] == col["id"] or (e["target_column_id"] is None and e["target_table_id"] == col["table_id"])],
            "downstream": [e for e in edges if e["source_column_id"] == col["id"] or (e["source_column_id"] is None and e["source_table_id"] == col["table_id"])]}


def table_controls(c):
    t = crud.get(c.db, TABLES, c.params["id"])
    _writable(c, TABLES, t)
    ids = _ids(c.body.get("control_ids"), "Kontrol")
    if ids and len(rows(c.db, f"SELECT id FROM tdr_controls WHERE id IN ({','.join('?' * len(ids))})", ids)) != len(ids):
        raise crud.Invalid("Bulunamayan kontrol seçildi")
    c.db.execute("DELETE FROM tdr_data_table_controls WHERE table_id=?", (t["id"],))
    for cid in ids:
        c.db.execute("INSERT INTO tdr_data_table_controls (table_id, control_id, created_by, created_at) VALUES (?,?,?,?)",
                     (t["id"], cid, c.principal.username, utcnow()))
    audit.log(c.db, c.principal, "CONTROLS", "data_tables", t["id"], {"control_ids": ids})
    return {"control_ids": ids}


def overview(c):
    authz.check(c.principal, EDGES, "read")
    db = c.db
    stats = one(db, """SELECT COUNT(*) AS edges, SUM(CASE WHEN source_column_id IS NOT NULL THEN 1 ELSE 0 END) AS column_edges,
        COUNT(DISTINCT source_table_id) AS sources, COUNT(DISTINCT target_table_id) AS targets FROM tdr_lineage_edges
        WHERE status='active'""")
    by_method = {r["method"]: r["n"] for r in rows(db, "SELECT method, COUNT(*) AS n FROM tdr_lineage_edges WHERE status='active' "
                                                       "GROUP BY method")}
    jobs = rows(db, """SELECT j.*, (SELECT COUNT(*) FROM tdr_lineage_edges e WHERE e.job_id=j.id AND e.status='active') AS edges
        FROM tdr_lineage_jobs j WHERE j.status='active' ORDER BY COALESCE(j.last_run_at, j.created_at) DESC LIMIT 30""")
    broken = rows(db, """SELECT e.id, st.name AS source_table, tt.name AS target_table, sc.name AS source_column, tc.name AS target_column,
        e.source_table_id, e.target_table_id FROM tdr_lineage_edges e JOIN tdr_data_tables st ON st.id=e.source_table_id
        JOIN tdr_data_tables tt ON tt.id=e.target_table_id LEFT JOIN tdr_data_columns sc ON sc.id=e.source_column_id
        LEFT JOIN tdr_data_columns tc ON tc.id=e.target_column_id WHERE e.status='active' AND (st.status='removed' OR
        tt.status='removed' OR sc.status='removed' OR tc.status='removed') ORDER BY e.id LIMIT 50""")
    hubs = rows(db, """SELECT t.id, t.name, t.schema_name, s.name AS source_name, COUNT(DISTINCT e.target_table_id) AS downstream
        FROM tdr_lineage_edges e JOIN tdr_data_tables t ON t.id=e.source_table_id JOIN tdr_data_sources s ON s.id=t.source_id
        WHERE e.status='active' GROUP BY t.id, t.name, t.schema_name, s.name ORDER BY downstream DESC, t.name LIMIT 10""")
    recent = _edge_rows(db, "e.status='active'", (), order="COALESCE(e.last_seen_at, e.created_at) DESC, e.id DESC", limit=12)
    events = rows(db, """SELECT id, event_type, event_time, job_name, job_namespace, edges_new, edges_seen, unresolved_json, created_at
        FROM tdr_lineage_events ORDER BY id DESC LIMIT 15""")
    for e in events:
        e["unresolved"] = len(json.loads(e.pop("unresolved_json") or "[]"))
    receivers = rows(db, """SELECT c.id, c.code, c.name, c.status, c.last_push_at, s.name AS source_name FROM tdr_data_collectors c
        JOIN tdr_data_sources s ON s.id=c.source_id WHERE c.connector='openlineage' ORDER BY c.status, c.code""")
    return {"stats": {k: stats[k] or 0 for k in ("edges", "column_edges", "sources", "targets")}, "by_method": by_method,
            "jobs": jobs, "broken": broken, "hubs": hubs, "recent": recent, "events": events, "receivers": receivers,
            "can_edit": authz.can_write(c.principal, EDGES) and c.principal.auth_type not in ("api_key", "collector"),
            "can_manage": c.principal.can("manage") and c.principal.auth_type not in ("api_key", "collector")}


# ------------------------------------------------------------------ Faz 3 bağlantısı, sağlık kontrolü

def downstream_flags(db, changes):
    """Kaldırılan veya tipi değişen nesnenin aşağı akışı varsa gerekçe (şema değişikliği bildirimi 'önemli' sayar)."""
    out = {}
    cols = {cid: tid for kind, _, _, tid, cid in changes if cid and kind in ("column_removed", "type_changed")}
    tabs = {tid for kind, _, _, tid, cid in changes if tid and not cid and kind == "table_removed"}
    for cid, tid in cols.items():
        n = one(db, """SELECT COUNT(DISTINCT target_table_id) AS n FROM tdr_lineage_edges WHERE status='active' AND
            ((source_column_id=?) OR (source_column_id IS NULL AND source_table_id=?))""", (cid, tid))["n"]
        if n:
            out[("column", cid)] = f"aşağı akışta {n} tablo/rapor"
    for tid in tabs:
        n = one(db, "SELECT COUNT(DISTINCT target_table_id) AS n FROM tdr_lineage_edges WHERE status='active' AND source_table_id=?",
                (tid,))["n"]
        if n:
            out[("table", tid)] = f"aşağı akışta {n} tablo/rapor"
    return out


def health_checks(db, check, count, readable=lambda name: True):
    if not readable("lineage_edges"):
        return []
    broken = rows(db, """SELECT e.id, st.name || ' → ' || tt.name AS code, COALESCE(sc.name, '') || ' → ' || COALESCE(tc.name, '') AS title
        FROM tdr_lineage_edges e JOIN tdr_data_tables st ON st.id=e.source_table_id JOIN tdr_data_tables tt ON tt.id=e.target_table_id
        LEFT JOIN tdr_data_columns sc ON sc.id=e.source_column_id LEFT JOIN tdr_data_columns tc ON tc.id=e.target_column_id
        WHERE e.status='active' AND (st.status='removed' OR tt.status='removed' OR sc.status='removed' OR tc.status='removed')
        ORDER BY e.id LIMIT 200""")
    return [check("lineage_broken", "Kaynakta kaldırılmış nesneye bağlı soy kütüğü bağlantıları",
                  "Kaldırılan tablo veya kolon aşağı akıştaki rapor ve sistemleri besliyordu; akış ya güncellenmeli ya da "
                  "bağlantı kaldırılmalı.", "medium", broken, "lineage_edges", link="lineage",
                  population=count(db, "SELECT COUNT(*) AS n FROM tdr_lineage_edges WHERE status='active'"))]


def register(app):
    app.route("POST", API + "/collector/openlineage", openlineage_receive, max_body=8 * 1024 * 1024)
    app.route("GET", API + "/datagov/lineage", overview)
    app.route("GET", API + "/datagov/lineage/graph", graph)
    app.route("GET", API + "/datagov/lineage/unresolved", unresolved_list)
    app.route("POST", API + "/datagov/lineage/reprocess", reprocess)
    app.route("POST", API + "/datagov/lineage/dbt", dbt_import, max_body=MAX_UPLOAD_BODY)
    app.route("POST", API + "/datagov/lineage/import", lineage_import, max_body=MAX_UPLOAD_BODY)
    app.route("GET", API + "/datagov/lineage/export", lineage_export)
    app.route("GET", API + "/data_tables/{id}/lineage", table_lineage)
    app.route("GET", API + "/data_tables/{id}/impact", impact)
    app.route("GET", API + "/data_tables/{id}/impact/export", impact_export)
    app.route("POST", API + "/data_tables/{id}/impact/notify", impact_notify)
    app.route("POST", API + "/data_tables/{id}/controls", table_controls)
    app.route("GET", API + "/data_columns/{id}/lineage", column_lineage)
