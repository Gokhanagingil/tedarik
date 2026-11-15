"""Denetim arşivi: geçmiş denetimler, kontrol sonuçları ve sunulan kanıtlar (grc modülünün parçası).

- `GET /api/tdr/assurance/search?q=&standard_id=&clause_id=&from=&to=`: bir standart maddesi (ör. `A.5.19`, `8.3.4`,
  `ISO 27001 5.19`) veya konu (ör. "yedekleme") için hangi denetimde, hangi kontrol test edildi, sonuç ne oldu ve
  hangi kanıt (hangi sürüm, SHA-256) sunuldu; denetim dışındaki sürekli izleme sonuçları; eşleşen kanıt kütüphanesi.
- `GET /api/tdr/audits/{id}/history`: bir denetimin kapsamının önceki denetimleri ve her kontrolün geçmiş sonuçları.

Kayıtlar değiştirilemez çalışmalardan (executions) ve onlara dondurulmuş kanıt sürümlerinden okunur; kısıtlı kanıtın
başlığı ve dosyası yalnızca bilmesi gerekene görünür (grc.evidence_visible).
"""
import re

from .. import auth as authz, crud
from ..db import fold, one, rows
from ..schema import RESOURCES

CODE = re.compile(r"^(?:[A-Za-z]{1,3}\.?\s?)?\d+(?:\.\d+)*[a-z]?$")
LEAD = re.compile(r"^(?:madde|md\.?|clause|kontrol)\s+", re.I)
RESULT_LIMIT = 600


def _like(text):
    return "%" + re.sub(r"([\\%_])", r"\\\1", fold(text)) + "%"


def _ids(items):
    return sorted({i for i in items if i is not None})


def _in(ids):
    return ",".join("?" * len(ids)) if ids else "NULL"


def _parse(q):
    """Sorgu → (madde kodu veya None, standart metni, serbest metin)."""
    q = LEAD.sub("", (q or "").strip())
    tokens = q.split()
    for i in range(len(tokens) - 1, -1, -1):
        if CODE.fullmatch(tokens[i]) and any(ch.isdigit() for ch in tokens[i]):
            return tokens[i], " ".join(tokens[:i]).strip(), ""
    return None, "", q


def _clauses(db, code, standard_text, text, standard_id, clause_id):
    sql = """SELECT cl.id, cl.code, cl.title, cl.applicable, cl.standard_id, s.code AS standard_code,
        s.version AS standard_version FROM tdr_clauses cl JOIN tdr_standards s ON s.id=cl.standard_id WHERE 1=1"""
    args = []
    if standard_id:
        sql += " AND cl.standard_id=?"
        args.append(int(standard_id))
    if clause_id:
        base = one(db, "SELECT id, code, standard_id FROM tdr_clauses WHERE id=?", (int(clause_id),))
        if not base:
            raise crud.NotFound("Madde bulunamadı")
        sql += " AND cl.standard_id=? AND (cl.id=? OR cl.code LIKE ? ESCAPE '\\')"
        args += [base["standard_id"], base["id"], re.sub(r"([\\%_])", r"\\\1", base["code"]) + ".%"]
    elif code:
        c = fold(code.replace(" ", ""))
        bare = re.sub(r"^[a-z]{1,3}\.", "", c)                     # "a.5.19" ile "5.19" aynı maddeyi bulur
        sql += (" AND (tdr_fold(cl.code)=? OR tdr_fold(cl.code)=? OR tdr_fold(cl.code)=? OR tdr_fold(cl.code) LIKE ? "
                "ESCAPE '\\')")
        args += [c, bare, "a." + bare, re.sub(r"([\\%_])", r"\\\1", c) + ".%"]
        for token in re.findall(r"\w+", standard_text):        # "ISO 27001" → "ISO/IEC 27001" (her parça geçmeli)
            sql += " AND (tdr_fold(s.code) LIKE ? ESCAPE '\\' OR tdr_fold(s.name) LIKE ? ESCAPE '\\')"
            args += [_like(token), _like(token)]
    elif text:
        sql += " AND (tdr_fold(cl.title) LIKE ? ESCAPE '\\' OR tdr_fold(cl.description) LIKE ? ESCAPE '\\')"
        args += [_like(text), _like(text)]
    else:
        return []
    return rows(db, sql + " ORDER BY s.code, cl.code LIMIT 200", args)


def _evidence_rows(db, principal, ids):
    from .grc import evidence_visible
    out = {}
    for e in rows(db, f"SELECT id, code, title, confidentiality, created_by, status, current_version, expires_at "
                      f"FROM tdr_evidence WHERE id IN ({_in(ids)})", ids):
        visible = evidence_visible(principal, e)
        out[e["id"]] = {"id": e["id"], "code": e["code"], "title": e["title"] if visible else "Kısıtlı kanıt",
                        "restricted": not visible, "status": e["status"], "current_version": e["current_version"],
                        "expires_at": e["expires_at"]}
    return out


def _results(db, principal, executions, clause_by_control):
    """Çalışmalar + o çalışmaya dondurulmuş kanıt sürümleri."""
    ids = [x["id"] for x in executions]
    frozen = rows(db, f"SELECT execution_id, evidence_id, version, sha256, file_name FROM tdr_execution_evidence "
                      f"WHERE execution_id IN ({_in(ids)})", ids) if ids else []
    evidence = _evidence_rows(db, principal, _ids(f["evidence_id"] for f in frozen))
    by_exec = {}
    for f in frozen:
        ev = evidence.get(f["evidence_id"])
        if ev:
            by_exec.setdefault(f["execution_id"], []).append({**ev, "version": f["version"], "sha256": f["sha256"],
                                                              "file_name": None if ev["restricted"] else f["file_name"]})
    return [{"execution_id": x["id"], "control_id": x["control_id"], "control_code": x["control_code"],
             "control_name": x["control_name"], "clause_codes": clause_by_control.get(x["control_id"], []),
             "status": x["status"], "source": x["source"], "executed_at": x["executed_at"], "recorded_by": x["recorded_by"],
             "details": (x["details"] or "")[:600], "audit_id": x["audit_id"], "evidence": by_exec.get(x["id"], [])}
            for x in executions]


def _summary(results):
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return counts


def search(c):
    from .grc import evidence_filter
    authz.require_human(c.principal)
    authz.check(c.principal, RESOURCES["executions"], "read")
    q = (c.query.get("q") or "").strip()[:200]
    standard_id, clause_id = c.query.get("standard_id"), c.query.get("clause_id")
    since, until = c.query.get("from"), c.query.get("to")
    for value in (standard_id, clause_id):
        if value and not value.isdigit():
            raise crud.Invalid("standard_id ve clause_id tamsayı olmalı")
    if len(q) < 2 and not clause_id and not standard_id:
        return {"query": q, "mode": None, "clauses": [], "controls": [], "audits": [], "monitoring": [], "evidence": [],
                "findings": [], "summary": {}}
    code, standard_text, text = _parse(q) if not clause_id else (None, "", "")
    db = c.db
    clauses = _clauses(db, code, standard_text, text, standard_id, clause_id) if (code or text or clause_id) else []
    if standard_id and not q and not clause_id:          # yalnızca standart: tüm maddeleri
        clauses = rows(db, """SELECT cl.id, cl.code, cl.title, cl.applicable, cl.standard_id, s.code AS standard_code,
            s.version AS standard_version FROM tdr_clauses cl JOIN tdr_standards s ON s.id=cl.standard_id
            WHERE cl.standard_id=? ORDER BY cl.code LIMIT 400""", (int(standard_id),))
    clause_ids = [x["id"] for x in clauses]
    mapping = rows(db, f"""SELECT m.control_id, cl.code FROM tdr_control_clauses m JOIN tdr_clauses cl ON cl.id=m.clause_id
        WHERE m.clause_id IN ({_in(clause_ids)}) ORDER BY cl.code""", clause_ids) if clause_ids else []
    clause_by_control = {}
    for m in mapping:
        clause_by_control.setdefault(m["control_id"], []).append(m["code"])
    control_ids = set(clause_by_control)
    if text and not code:
        pattern = _like(text)
        control_ids |= {r["id"] for r in rows(db, "SELECT id FROM tdr_controls WHERE tdr_fold(name) LIKE ? ESCAPE '\\' "
                                                  "OR tdr_fold(description) LIKE ? ESCAPE '\\' OR tdr_fold(code) LIKE ? "
                                                  "ESCAPE '\\' LIMIT 200", (pattern, pattern, pattern))}
    control_ids = sorted(control_ids)
    # çalışmalar (sonuçlar): eşleşen kontrollerin ve (metin aramada) ayrıntısı eşleşenlerin
    where, args = [], []
    if control_ids:
        where.append(f"x.control_id IN ({_in(control_ids)})")
        args += control_ids
    if text and not code:
        where.append("tdr_fold(x.details) LIKE ? ESCAPE '\\'")
        args.append(_like(text))
    executions = []
    if where:
        period = ""
        if since:
            period += " AND x.executed_at >= ?"
            args.append(since)
        if until:
            period += " AND x.executed_at < ?"
            args.append(until + "T23:59:59Z" if len(until) == 10 else until)
        executions = rows(db, f"""SELECT x.id, x.control_id, x.audit_id, x.status, x.source, x.executed_at, x.recorded_by,
            x.details, k.code AS control_code, k.name AS control_name FROM tdr_executions x JOIN tdr_controls k
            ON k.id=x.control_id WHERE ({' OR '.join(where)}){period} ORDER BY x.executed_at DESC, x.id DESC
            LIMIT {RESULT_LIMIT}""", args)
    results = _results(db, c.principal, executions, clause_by_control)
    # denetimler: sonuçları olanlar, kapsamında madde olanlar, metniyle eşleşenler
    audit_ids = {r["audit_id"] for r in results if r["audit_id"]}
    if clause_ids:
        audit_ids |= {r["audit_id"] for r in rows(db, f"SELECT DISTINCT audit_id FROM tdr_audit_clauses WHERE clause_id IN "
                                                      f"({_in(clause_ids)})", clause_ids)}
    if text and not code:
        pattern = _like(text)
        audit_ids |= {r["id"] for r in rows(db, """SELECT id FROM tdr_audits WHERE tdr_fold(name) LIKE ? ESCAPE '\\' OR
            tdr_fold(scope) LIKE ? ESCAPE '\\' OR tdr_fold(audit_objective) LIKE ? ESCAPE '\\' OR tdr_fold(conclusion)
            LIKE ? ESCAPE '\\' LIMIT 100""", (pattern,) * 4)}
    audit_ids = _ids(audit_ids)
    audits = rows(db, f"""SELECT a.id, a.code, a.name, a.kind, a.status, a.planned_start, a.planned_end, a.actual_start,
        a.actual_end, a.opinion, a.conclusion, a.lead_auditor, a.supplier_id, a.company_id FROM tdr_audits a
        WHERE a.id IN ({_in(audit_ids)})""", audit_ids) if audit_ids else []
    visible, vargs = evidence_filter(c.principal, "e")
    linked = rows(db, f"""SELECT m.audit_id, e.id FROM tdr_evidence_audits m JOIN tdr_evidence e ON e.id=m.evidence_id
        WHERE m.audit_id IN ({_in(audit_ids)}) AND {visible}""", (*audit_ids, *vargs)) if audit_ids else []
    # bulgular
    fwhere, fargs = [], []
    if clause_ids:
        fwhere.append(f"f.clause_id IN ({_in(clause_ids)})")
        fargs += clause_ids
    if control_ids:
        fwhere.append(f"f.control_id IN ({_in(control_ids)})")
        fargs += control_ids
    if text and not code:
        fwhere.append("tdr_fold(f.title) LIKE ? ESCAPE '\\'")
        fargs.append(_like(text))
    findings = rows(db, f"""SELECT f.id, f.code, f.title, f.severity, f.status, f.audit_id, f.control_id, f.created_at,
        f.closed_at FROM tdr_findings f WHERE {' OR '.join(fwhere)} ORDER BY f.id DESC LIMIT 300""", fargs) if fwhere else []
    # kanıt kütüphanesi: maddeye/kontrole bağlı veya metniyle eşleşen kanıtlar (kullanıldığı denetimlerle)
    ewhere, eargs = [], []
    if clause_ids:
        ewhere.append(f"e.id IN (SELECT evidence_id FROM tdr_evidence_clauses WHERE clause_id IN ({_in(clause_ids)}))")
        eargs += clause_ids
    if control_ids:
        ewhere.append(f"e.id IN (SELECT evidence_id FROM tdr_evidence_controls WHERE control_id IN ({_in(control_ids)}))")
        eargs += control_ids
    used = _ids(ev["id"] for r in results for ev in r["evidence"])
    if used:
        ewhere.append(f"e.id IN ({_in(used)})")
        eargs += used
    if text and not code:
        ewhere.append("(tdr_fold(e.title) LIKE ? ESCAPE '\\' OR tdr_fold(e.description) LIKE ? ESCAPE '\\')")
        eargs += [_like(text)] * 2
    library = rows(db, f"""SELECT e.id, e.code, e.title, e.status, e.confidentiality, e.current_version, e.expires_at,
        e.period_start, e.period_end, e.source FROM tdr_evidence e WHERE ({' OR '.join(ewhere)}) AND {visible}
        ORDER BY e.id DESC LIMIT 300""", (*eargs, *vargs)) if ewhere else []
    used_in = {}
    for r in results:
        for ev in r["evidence"]:
            if r["audit_id"]:
                used_in.setdefault(ev["id"], set()).add(r["audit_id"])
    for m in linked:
        used_in.setdefault(m["id"], set()).add(m["audit_id"])
    codes = {a["id"]: a["code"] for a in audits}
    for e in library:
        e["audits"] = sorted(codes.get(a) or str(a) for a in used_in.get(e["id"], set()))
    # denetim başına gruplama
    by_audit = {a["id"]: {**a, "results": [], "evidence": [], "findings": []} for a in audits}
    monitoring = []
    for r in results:
        (by_audit[r["audit_id"]]["results"] if r["audit_id"] in by_audit else monitoring).append(r)
    ev_info = _evidence_rows(db, c.principal, _ids(m["id"] for m in linked))
    for m in linked:
        if m["audit_id"] in by_audit and m["id"] in ev_info:
            by_audit[m["audit_id"]]["evidence"].append(ev_info[m["id"]])
    for f in findings:
        if f["audit_id"] in by_audit:
            by_audit[f["audit_id"]]["findings"].append(f)
    grouped = []
    for a in by_audit.values():
        a["counts"] = _summary(a["results"])
        grouped.append(a)
    grouped.sort(key=lambda a: str(a["actual_start"] or a["planned_start"] or ""), reverse=True)
    controls = rows(db, f"SELECT id, code, name, execution_mode, active FROM tdr_controls WHERE id IN ({_in(control_ids)}) "
                        "ORDER BY code", control_ids) if control_ids else []
    return {"query": q, "mode": "clause" if (code or clause_id or (standard_id and not q)) else "text", "clauses": clauses,
            "controls": controls, "audits": grouped, "monitoring": monitoring[:60], "evidence": library,
            "findings": [f for f in findings if f["audit_id"] not in by_audit][:100],
            "summary": {"audits": len(grouped), "results": len(results), "evidence": len(library),
                        "findings": len(findings), "truncated": len(executions) >= RESULT_LIMIT}}


def audit_history(c):
    """Denetim çalışma alanı: aynı kapsamın önceki denetimleri ve kontrol başına geçmiş sonuçlar ile kanıtlar."""
    authz.check(c.principal, RESOURCES["audits"], "read")
    from .grc import audit_scope, planned_controls
    audit = crud.get(c.db, RESOURCES["audits"], c.params["id"])
    db = c.db
    _, clauses = audit_scope(db, audit["id"])
    clauses = sorted(clauses)
    processes = [r["process_id"] for r in rows(db, "SELECT process_id FROM tdr_audit_processes WHERE audit_id=?", (audit["id"],))]
    controls = _ids([p["control_id"] for p in planned_controls(db, audit["id"])] +
                    [r["control_id"] for r in rows(db, "SELECT DISTINCT control_id FROM tdr_executions WHERE audit_id=?",
                                                   (audit["id"],))])
    start = str(audit["actual_start"] or audit["planned_start"] or "9999")
    candidates = {}
    for sql, ids, kind in (
            (f"SELECT audit_id, COUNT(*) AS n FROM tdr_audit_clauses WHERE clause_id IN ({_in(clauses)}) GROUP BY audit_id",
             clauses, "clauses"),
            (f"SELECT audit_id, COUNT(*) AS n FROM tdr_audit_processes WHERE process_id IN ({_in(processes)}) GROUP BY audit_id",
             processes, "processes"),
            (f"SELECT audit_id, COUNT(DISTINCT control_id) AS n FROM tdr_executions WHERE audit_id IS NOT NULL AND "
             f"control_id IN ({_in(controls)}) GROUP BY audit_id", controls, "controls")):
        if not ids:
            continue
        for r in rows(db, sql, ids):
            if r["audit_id"] != audit["id"]:
                candidates.setdefault(r["audit_id"], {})[kind] = r["n"]
    previous = []
    if candidates:
        ids = sorted(candidates)
        for a in rows(db, f"""SELECT id, code, name, kind, status, planned_start, actual_start, actual_end, opinion, conclusion
                FROM tdr_audits WHERE id IN ({_in(ids)}) AND status <> 'cancelled'""", ids):
            when = str(a["actual_start"] or a["planned_start"] or "")
            if when and when > start:
                continue                                        # yalnızca önceki denetimler
            counts = _summary([{"status": r["status"]} for r in rows(
                db, "SELECT status FROM tdr_executions WHERE audit_id=?", (a["id"],))])
            previous.append({**a, "overlap": candidates[a["id"]], "counts": counts,
                             "findings": one(db, "SELECT COUNT(*) AS n FROM tdr_findings WHERE audit_id=?", (a["id"],))["n"]})
        previous.sort(key=lambda a: str(a["actual_start"] or a["planned_start"] or ""), reverse=True)
    history = {}
    if controls:
        executions = rows(db, f"""SELECT x.id, x.control_id, x.audit_id, x.status, x.source, x.executed_at, x.recorded_by,
            x.details, k.code AS control_code, k.name AS control_name FROM tdr_executions x JOIN tdr_controls k
            ON k.id=x.control_id WHERE x.control_id IN ({_in(controls)}) AND COALESCE(x.audit_id, 0) <> ?
            ORDER BY x.executed_at DESC, x.id DESC LIMIT {RESULT_LIMIT}""", (*controls, audit["id"]))
        codes = {r["id"]: r["code"] for r in rows(db, "SELECT id, code FROM tdr_audits")}
        for r in _results(db, c.principal, executions, {}):
            items = history.setdefault(r["control_id"], [])
            if len(items) < 8:
                r["audit_code"] = codes.get(r["audit_id"])
                items.append(r)
    return {"audit_id": audit["id"], "previous": previous[:30],
            "controls": {str(k): v for k, v in history.items()}}
