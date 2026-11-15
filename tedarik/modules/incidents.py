"""Olay, kayıp, kişisel veri ihlali, öz değerlendirme (RCSA) ve nicel risk — risks modülünün parçası (K-027).

- Kayıp olayları: operasyonel olay ve gerçekleşen kayıp (Basel II olay türleri), brüt kayıp, geri kazanım, net kayıp;
  riske bağlanır ve risk değerlendirmesini gerçek veriyle besler. ITSM büyük olayları MCP ile yazılabilir.
- Kişisel veri ihlali (KVKK md. 12/5, Kurul kararı 2019/10): tespit zamanından itibaren 72 saatlik bildirim süresi,
  bildirim kararı ve gerekçesi, Kurula ve ilgili kişilere bildirim zamanı; süre aşımında gecikme gerekçesi zorunlu;
  kalan süre 24 saatin altına inince ve aşılınca hatırlatma.
- RCSA: süreç sahiplerinin dönemsel risk ve kontrol öz değerlendirmesi; resmî değerlendirmeyle karşılaştırma;
  "etkin değil" denen kontrol için tek adımda bulgu.
- Nicel risk (FAIR yaklaşımı, Monte Carlo): yıllık olay sıklığı ve olay başı kayıp için en az / en olası / en çok
  tahmin (PERT), 10.000 benzetim; beklenen yıllık kayıp (TL), yüzdelikler ve kayıp aşım eğrisi. Çalıştırma
  değiştirilemez kayıttır; aynı girdi aynı sonucu verir (tohum risk ve girdilerden).
"""
import hashlib
import json
import math
import random
from datetime import date, datetime, timedelta, timezone

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API
from ..schema import RESOURCES, Resource, fk
from . import reminder
from .core import policy

M = "risks"
PRIVACY_ROLES = {"ADMIN", "SUPPLIER_MANAGER"}
BASEL = ("internal_fraud", "external_fraud", "employment", "clients_products", "physical_assets", "systems",
         "execution_process")

LOSS_EVENTS = Resource("loss_events", "Kayıp Olayları", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "event_type": "TEXT NOT NULL DEFAULT 'systems'",
    "occurred_on": "DATE NOT NULL", "discovered_on": "DATE", "company_id": fk("companies", False),
    "org_unit_id": fk("org_units", False), "process_id": fk("processes", False), "risk_id": fk("supplier_risks", False),
    "supplier_id": fk("suppliers", False), "gross_loss": "DECIMAL NOT NULL DEFAULT 0", "recovery": "DECIMAL NOT NULL DEFAULT 0",
    "net_loss": "DECIMAL", "currency": "TEXT NOT NULL DEFAULT 'TRY'", "near_miss": "INTEGER NOT NULL DEFAULT 0",
    "description": "TEXT", "root_cause": "TEXT", "status": "TEXT NOT NULL DEFAULT 'open'",
    "source": "TEXT NOT NULL DEFAULT 'manual'", "external_ref": "TEXT", "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="OLY", code_yearly=True, search=("code", "title", "external_ref"), write="write", machine="rw",
    readonly=("net_loss", "created_by"),
    enums={"event_type": BASEL, "status": ("open", "analysis", "closed"), "source": ("manual", "servicenow", "mcp")})

BREACHES = Resource("privacy_breaches", "Kişisel Veri İhlalleri", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "company_id": fk("companies", False), "owner": "TEXT NOT NULL",
    "detected_at": "TIMESTAMP NOT NULL", "occurred_at": "TIMESTAMP", "description": "TEXT NOT NULL",
    "data_categories": "TEXT", "special_categories": "INTEGER NOT NULL DEFAULT 0", "subjects_count": "INTEGER",
    "subject_groups": "TEXT", "consequences": "TEXT", "measures": "TEXT", "loss_event_id": fk("loss_events", False),
    "notify_decision": "TEXT NOT NULL DEFAULT 'pending'", "decision_rationale": "TEXT", "decided_by": "TEXT",
    "decided_at": "TIMESTAMP", "authority_notified_at": "TIMESTAMP", "authority_reference": "TEXT", "delay_reason": "TEXT",
    "subjects_notified_at": "TIMESTAMP", "status": "TEXT NOT NULL DEFAULT 'open'", "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="IHL", code_yearly=True, search=("code", "title"), write_roles=PRIVACY_ROLES,
    read_roles=PRIVACY_ROLES | {"AUDITOR"}, readonly=("decided_by", "decided_at", "created_by"),
    enums={"notify_decision": ("pending", "notify", "not_required"), "status": ("open", "notified", "closed")})

RCSA_CAMPAIGNS = Resource("rcsa_campaigns", "Öz Değerlendirme (RCSA)", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "period": "TEXT", "process_id": fk("processes", False),
    "org_unit_id": fk("org_units", False), "company_id": fk("companies", False), "due_date": "DATE NOT NULL",
    "instructions": "TEXT", "status": "TEXT NOT NULL DEFAULT 'draft'", "launched_at": "TIMESTAMP", "closed_at": "TIMESTAMP",
    "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="ROD", search=("code", "title"), write="manage",
    readonly=("status", "launched_at", "closed_at", "created_by"), enums={"status": ("draft", "open", "closed")})

RCSA_ITEMS = Resource("rcsa_items", "Öz Değerlendirme Kalemleri", {
    "campaign_id": fk("rcsa_campaigns"), "item_type": "TEXT NOT NULL", "risk_id": fk("supplier_risks", False),
    "control_id": "INTEGER", "respondent": "TEXT NOT NULL", "status": "TEXT NOT NULL DEFAULT 'pending'",
    "likelihood": "INTEGER", "impact": "INTEGER", "effectiveness": "TEXT", "comment": "TEXT", "submitted_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list", "get"), search=("respondent", "comment"), write="manage",
    enums={"item_type": ("risk", "control"), "status": ("pending", "submitted"),
           "effectiveness": ("effective", "partially_effective", "ineffective", "not_operating")})

QUANT_RUNS = Resource("risk_quant_runs", "Nicel Risk Analizleri", {
    "risk_id": fk("supplier_risks"), "inputs_json": "TEXT NOT NULL", "iterations": "INTEGER NOT NULL",
    "mean_loss": "DECIMAL NOT NULL", "p50": "DECIMAL NOT NULL", "p90": "DECIMAL NOT NULL", "p95": "DECIMAL NOT NULL",
    "p99": "DECIMAL NOT NULL", "zero_share": "REAL", "curve_json": "TEXT NOT NULL", "created_by": "TEXT NOT NULL",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list", "get"), search=(), immutable=True)

DEFAULT_POLICIES = {
    "privacy.notification_hours": (72, "Kişisel veri ihlalinin Kurula bildirim süresi (saat, KVKK Kurul kararı 2019/10)."),
    "quant.iterations": (10000, "Nicel risk analizinde Monte Carlo benzetim sayısı."),
}


def _notify(db, *args, **kw):
    from .. import notify
    return notify.enqueue(db, *args, **kw)


def _ts(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _admins(db):
    return [r["username"] for r in rows(db, "SELECT u.username FROM users u JOIN tdr_user_roles r ON r.user_id=u.id "
                                            "WHERE r.role='ADMIN' AND u.is_active=1")]


# ------------------------------------------------------------------ kayıp olayları

def _loss_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    for key in ("gross_loss", "recovery"):
        if merged.get(key) is not None and float(merged[key]) < 0:
            raise crud.Invalid("Tutarlar negatif olamaz")
    if float(merged.get("recovery") or 0) > float(merged.get("gross_loss") or 0):
        raise crud.Invalid("Geri kazanım brüt kayıptan büyük olamaz")
    data["net_loss"] = round(float(merged.get("gross_loss") or 0) - float(merged.get("recovery") or 0), 2)
    if merged.get("discovered_on") and merged.get("occurred_on") and str(merged["discovered_on"]) < str(merged["occurred_on"]):
        raise crud.Invalid("Fark edilme tarihi olay tarihinden önce olamaz")
    if merged.get("status") == "closed" and not (merged.get("root_cause") or "").strip():
        raise crud.Invalid("Kapanış için kök neden gerekli")
    if current is None:
        data["created_by"] = principal.username if principal else "system"
        if principal and principal.role == "MACHINE":
            data["source"] = "mcp"


LOSS_EVENTS.before_save = _loss_rules


# ------------------------------------------------------------------ kişisel veri ihlali

def deadline(db, breach):
    hours = int(policy(db, "privacy.notification_hours", 72))
    return _ts(breach["detected_at"]) + timedelta(hours=hours)


def _breach_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    detected = _ts(merged.get("detected_at"))
    if detected and detected > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise crud.Invalid("Tespit zamanı gelecekte olamaz")
    if merged.get("occurred_at") and _ts(merged["occurred_at"]) > detected:
        raise crud.Invalid("İhlal zamanı tespitten sonra olamaz")
    decision = merged.get("notify_decision")
    if current is not None and "notify_decision" in data and data["notify_decision"] != current["notify_decision"]:
        if data["notify_decision"] == "pending":
            raise crud.Invalid("Verilen bildirim kararı geri alınamaz; gerekçeyle değiştirin")
        if not (merged.get("decision_rationale") or "").strip():
            raise crud.Invalid("Bildirim kararının gerekçesini yazın")
        data["decided_by"] = principal.username if principal else "system"
        data["decided_at"] = utcnow()
    if merged.get("authority_notified_at"):
        if decision != "notify":
            raise crud.Invalid("Kurula bildirim için karar 'bildirilecek' olmalı")
        notified = _ts(merged["authority_notified_at"])
        if notified > deadline(db, merged) and not (merged.get("delay_reason") or "").strip():
            raise crud.Invalid("72 saatten sonra yapılan bildirimde gecikme gerekçesi zorunlu (Kurul kararı 2019/10)")
        if merged.get("status") == "open":
            data["status"] = "notified"
    if merged.get("status") == "closed":
        if decision == "pending":
            raise crud.Invalid("Bildirim kararı verilmeden ihlal kaydı kapatılamaz")
        if decision == "notify" and not merged.get("authority_notified_at"):
            raise crud.Invalid("Kurula bildirim zamanı girilmeden kapatılamaz")
        if not (merged.get("measures") or "").strip():
            raise crud.Invalid("Alınan önlemleri yazın")
    if current is None:
        data["created_by"] = principal.username if principal else "system"


BREACHES.before_save = _breach_rules
BREACHES.after_create = lambda db, record_id, principal: _after_breach_create(db, record_id)


def breach_state(db, breach):
    due = deadline(db, breach)
    now = datetime.now(timezone.utc)
    notified = _ts(breach["authority_notified_at"])
    remaining = (due - now).total_seconds() / 3600
    late = (notified > due) if notified else (now > due and breach["notify_decision"] != "not_required")
    return {"deadline": due.isoformat(timespec="minutes"), "remaining_hours": round(remaining, 1),
            "late": bool(late), "open": breach["status"] != "closed",
            "needs_action": breach["notify_decision"] == "pending" or (breach["notify_decision"] == "notify" and not notified)}


def breach_context(c):
    authz.check(c.principal, BREACHES, "read")
    breach = crud.get(c.db, BREACHES, c.params["id"])
    return {**breach, **breach_state(c.db, breach)}


def breaches_open(c):
    authz.check(c.principal, BREACHES, "read")
    out = []
    for b in rows(c.db, "SELECT * FROM tdr_privacy_breaches WHERE status<>'closed' ORDER BY detected_at"):
        out.append({k: b[k] for k in ("id", "code", "title", "owner", "notify_decision", "status", "detected_at")}
                   | breach_state(c.db, b))
    return out


def _after_breach_create(db, record_id):
    b = crud.get(db, BREACHES, record_id)
    _notify(db, "privacy_breach.detected", f"Kişisel veri ihlali: {b['code']} {b['title']}",
            f"Tespit: {str(b['detected_at'])[:16]}. Kurula bildirim için son: {deadline(db, b).isoformat(timespec='minutes')}.",
            users=[b["owner"], *_admins(db)], link=f"#/r/privacy_breaches/{b['id']}", object_type="privacy_breaches",
            object_id=b["id"], dedupe=f"ihl:{b['id']}:tespit")


@reminder
def breach_reminders(db, app):
    if not app.enabled("risks"):
        return 0
    n = 0
    for b in rows(db, "SELECT * FROM tdr_privacy_breaches WHERE status<>'closed'"):
        st = breach_state(db, b)
        if not st["needs_action"]:
            continue
        stage = "asim" if st["remaining_hours"] < 0 else "24saat" if st["remaining_hours"] < 24 else None
        if stage:
            n += _notify(db, "privacy_breach.deadline", f"KVKK bildirim süresi {'aşıldı' if stage == 'asim' else 'doluyor'}: "
                         f"{b['code']}", f"Son: {st['deadline']} (kalan {st['remaining_hours']} saat).",
                         users=[b["owner"], *_admins(db)], link=f"#/r/privacy_breaches/{b['id']}",
                         object_type="privacy_breaches", object_id=b["id"], dedupe=f"ihl:{b['id']}:{stage}")
    return n


# ------------------------------------------------------------------ RCSA

def _rcsa_rules(db, data, current, principal):
    if current is None:
        data["created_by"] = principal.username if principal else "system"
        data["status"] = "draft"
    elif current["status"] != "draft" and set(data) - {"due_date", "instructions", "updated_at"}:
        raise crud.Conflict("Başlamış öz değerlendirmede yalnızca son tarih ve açıklama değişir")


RCSA_CAMPAIGNS.before_save = _rcsa_rules


def _scope_sql(campaign, alias):
    where, args = [], []
    for col in ("process_id", "org_unit_id", "company_id"):
        if campaign[col]:
            where.append(f"{alias}.{col}=?")
            args.append(campaign[col])
    return (" AND " + " AND ".join(where)) if where else "", args


def rcsa_launch(c):
    authz.require_human(c.principal)
    campaign = crud.get(c.db, RCSA_CAMPAIGNS, c.params["id"])
    authz.check(c.principal, RCSA_CAMPAIGNS, "write")
    if campaign["status"] != "draft":
        raise crud.Conflict("Öz değerlendirme zaten başlamış")
    where, args = _scope_sql(campaign, "r")
    risks = rows(c.db, f"SELECT r.id, r.owner FROM tdr_supplier_risks r WHERE r.status IN ('open','in_treatment'){where}", args)
    controls = []
    if c.app.enabled("grc"):
        cwhere, cargs = [], []
        if campaign["process_id"]:
            cwhere.append("k.id IN (SELECT control_id FROM tdr_control_processes WHERE process_id=?)")
            cargs.append(campaign["process_id"])
        if campaign["org_unit_id"]:
            cwhere.append("k.org_unit_id=?")
            cargs.append(campaign["org_unit_id"])
        controls = rows(c.db, "SELECT k.id, k.owner FROM tdr_controls k WHERE k.active=1 AND k.execution_mode='manual'"
                              + (" AND " + " AND ".join(cwhere) if cwhere else ""), cargs)
    if not risks and not controls:
        raise crud.Invalid("Kapsamda açık risk veya manuel kontrol yok")
    now = utcnow()
    for r in risks:
        c.db.execute("INSERT INTO tdr_rcsa_items (campaign_id, item_type, risk_id, respondent, status, created_at) "
                     "VALUES (?,?,?,?,?,?)", (campaign["id"], "risk", r["id"], r["owner"] or campaign["created_by"], "pending", now))
    for k in controls:
        c.db.execute("INSERT INTO tdr_rcsa_items (campaign_id, item_type, control_id, respondent, status, created_at) "
                     "VALUES (?,?,?,?,?,?)", (campaign["id"], "control", k["id"], k["owner"] or campaign["created_by"],
                                              "pending", now))
    c.db.execute("UPDATE tdr_rcsa_campaigns SET status='open', launched_at=?, updated_at=? WHERE id=?",
                 (now, now, campaign["id"]))
    audit.log(c.db, c.principal, "LAUNCH", "rcsa_campaigns", campaign["id"], {"risks": len(risks), "controls": len(controls)})
    people = sorted({r["owner"] for r in risks if r["owner"]} | {k["owner"] for k in controls if k["owner"]})
    _notify(c.db, "rcsa.assigned", f"Öz değerlendirme: {campaign['title']}", f"Son tarih {campaign['due_date']}. "
            + (campaign["instructions"] or ""), users=people, link="#/my-work", object_type="rcsa_campaigns",
            object_id=campaign["id"])
    return rcsa_context_data(c.db, c.app, campaign["id"])


def _is_respondent(principal, item):
    return item["respondent"] in (principal.username, principal.display_name) or principal.role == "ADMIN"


def rcsa_respond(c):
    authz.require_human(c.principal)
    item = crud.get(c.db, RCSA_ITEMS, c.params["id"])
    if not _is_respondent(c.principal, item):
        raise crud.Forbidden("Bu kalemi yalnızca atanan kişi yanıtlar")
    campaign = crud.get(c.db, RCSA_CAMPAIGNS, item["campaign_id"])
    if campaign["status"] != "open":
        raise crud.Conflict("Öz değerlendirme açık değil")
    body = c.body
    if item["item_type"] == "risk":
        try:
            lk, im = int(body.get("likelihood")), int(body.get("impact"))
        except (TypeError, ValueError):
            raise crud.Invalid("Olasılık ve etki 1–5 olmalı") from None
        if not (1 <= lk <= 5 and 1 <= im <= 5):
            raise crud.Invalid("Olasılık ve etki 1–5 olmalı")
        values = {"likelihood": lk, "impact": im, "effectiveness": None}
    else:
        eff = body.get("effectiveness")
        if eff not in RCSA_ITEMS.enums["effectiveness"]:
            raise crud.Invalid("Kontrol etkinliği seçin")
        values = {"likelihood": None, "impact": None, "effectiveness": eff}
    comment = (body.get("comment") or "").strip()
    if (values.get("effectiveness") in ("ineffective", "not_operating")) and len(comment) < 10:
        raise crud.Invalid("Etkin olmayan kontrol için açıklama gerekli")
    c.db.execute("UPDATE tdr_rcsa_items SET likelihood=?, impact=?, effectiveness=?, comment=?, status='submitted', "
                 "submitted_at=? WHERE id=?", (values["likelihood"], values["impact"], values["effectiveness"],
                                                comment or None, utcnow(), item["id"]))
    audit.log(c.db, c.principal, "RESPOND", "rcsa_items", item["id"], {**values, "comment": comment})
    return crud.get(c.db, RCSA_ITEMS, item["id"])


def rcsa_context_data(db, app, campaign_id):
    campaign = crud.get(db, RCSA_CAMPAIGNS, campaign_id)
    items = rows(db, """SELECT i.*, r.code AS risk_code, r.title AS risk_title, r.likelihood AS official_likelihood,
        r.impact AS official_impact FROM tdr_rcsa_items i LEFT JOIN tdr_supplier_risks r ON r.id=i.risk_id
        WHERE i.campaign_id=? ORDER BY i.item_type DESC, i.id""", (campaign_id,))
    if app.enabled("grc"):
        names = {k["id"]: k for k in rows(db, "SELECT id, code, name FROM tdr_controls")}
        for i in items:
            if i["control_id"] in names:
                i["control_code"], i["control_name"] = names[i["control_id"]]["code"], names[i["control_id"]]["name"]
    for i in items:
        if i["item_type"] == "risk" and i["status"] == "submitted":
            self_score, official = i["likelihood"] * i["impact"], (i["official_likelihood"] or 3) * (i["official_impact"] or 3)
            i["gap"] = self_score - official
    done = sum(1 for i in items if i["status"] == "submitted")
    campaign["items"] = items
    campaign["progress"] = {"total": len(items), "submitted": done, "pct": round(100 * done / len(items), 1) if items else None,
                            "ineffective": sum(1 for i in items if i.get("effectiveness") in ("ineffective", "not_operating")),
                            "divergent": sum(1 for i in items if abs(i.get("gap") or 0) >= 6)}
    return campaign


def rcsa_context(c):
    authz.check(c.principal, RCSA_CAMPAIGNS, "read")
    return rcsa_context_data(c.db, c.app, c.params["id"])


def rcsa_close(c):
    authz.require_human(c.principal)
    campaign = crud.get(c.db, RCSA_CAMPAIGNS, c.params["id"])
    authz.check(c.principal, RCSA_CAMPAIGNS, "write")
    if campaign["status"] != "open":
        raise crud.Conflict("Yalnızca açık öz değerlendirme kapatılır")
    c.db.execute("UPDATE tdr_rcsa_campaigns SET status='closed', closed_at=?, updated_at=? WHERE id=?",
                 (utcnow(), utcnow(), campaign["id"]))
    audit.log(c.db, c.principal, "CLOSE", "rcsa_campaigns", campaign["id"], None)
    return rcsa_context_data(c.db, c.app, campaign["id"])


def rcsa_finding(c):
    """Öz değerlendirmede etkin olmadığı belirtilen kontrol için bulgu (kaynak: öz değerlendirme)."""
    authz.require_human(c.principal)
    item = crud.get(c.db, RCSA_ITEMS, c.params["id"])
    if not c.app.enabled("grc"):
        raise crud.Conflict("Uyum modülü kapalı")
    findings = RESOURCES["findings"]
    authz.check(c.principal, findings, "write")
    if item["item_type"] != "control" or item["effectiveness"] not in ("ineffective", "partially_effective", "not_operating"):
        raise crud.Invalid("Bulgu yalnızca etkin olmayan kontrol için açılır")
    control = crud.get(c.db, RESOURCES["controls"], item["control_id"])
    fid = crud.insert(c.db, findings, {"title": f"Öz değerlendirme: {control['name']} etkin değil"[:300],
                                       "control_id": control["id"], "source": "self_assessment",
                                       "description": item["comment"], "owner": item["respondent"],
                                       "severity": "high" if item["effectiveness"] != "partially_effective" else "medium",
                                       "due_date": (date.today() + timedelta(days=60)).isoformat()}, c.principal)
    audit.log(c.db, c.principal, "CREATE", "findings", fid, {"rcsa_item": item["id"]})
    return 201, {"finding_id": fid}


# ------------------------------------------------------------------ nicel risk (Monte Carlo)

def _pert(rnd, low, mode, high):
    if high <= low:
        return float(low)
    a = 1 + 4 * (mode - low) / (high - low)
    b = 1 + 4 * (high - mode) / (high - low)
    return low + (high - low) * rnd.betavariate(a, b)


def _poisson(rnd, lam):
    if lam <= 0:
        return 0
    if lam > 30:                                            # büyük oranlarda normal yaklaşımı
        return max(0, int(round(rnd.gauss(lam, math.sqrt(lam)))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rnd.random()
        if p <= limit:
            return k
        k += 1


def simulate(inputs, iterations, seed):
    """Yıllık kayıp benzetimi. Dönüş: sıralı yıllık kayıplar listesi."""
    rnd = random.Random(seed)       # nosec B311 - kriptografik değil, tekrarlanabilir benzetim
    f_min, f_mode, f_max = inputs["freq_min"], inputs["freq_likely"], inputs["freq_max"]
    l_min, l_mode, l_max = inputs["loss_min"], inputs["loss_likely"], inputs["loss_max"]
    out = []
    for _ in range(iterations):
        events = _poisson(rnd, _pert(rnd, f_min, f_mode, f_max))
        out.append(sum(_pert(rnd, l_min, l_mode, l_max) for _ in range(events)))
    out.sort()
    return out


def _percentile(values, p):
    if not values:
        return 0.0
    k = min(len(values) - 1, max(0, int(math.ceil(p / 100 * len(values))) - 1))
    return values[k]


def _inputs(body):
    keys = ("freq_min", "freq_likely", "freq_max", "loss_min", "loss_likely", "loss_max")
    try:
        values = {k: float(body.get(k)) for k in keys}
    except (TypeError, ValueError):
        raise crud.Invalid("Sıklık ve kayıp tahminlerinin üçü de sayı olmalı") from None
    if any(v < 0 for v in values.values()):
        raise crud.Invalid("Tahminler negatif olamaz")
    for a, b, c in (("freq_min", "freq_likely", "freq_max"), ("loss_min", "loss_likely", "loss_max")):
        if not values[a] <= values[b] <= values[c]:
            raise crud.Invalid("En az ≤ en olası ≤ en çok olmalı")
    if values["freq_max"] > 365:
        raise crud.Invalid("Yıllık olay sıklığı en çok 365 olabilir")
    return values


def quantify(c):
    authz.require_human(c.principal)
    risks = RESOURCES["supplier_risks"]
    authz.check(c.principal, risks, "write")
    risk = crud.get(c.db, risks, c.params["id"])
    crud.check_scope(c.db, risks, c.principal, risk)
    inputs = _inputs(c.body)
    iterations = min(int(policy(c.db, "quant.iterations", 10000)), 50000)
    seed = int(hashlib.sha256(json.dumps([risk["id"], inputs], sort_keys=True).encode()).hexdigest()[:12], 16)
    losses = simulate(inputs, iterations, seed)
    mean = sum(losses) / len(losses)
    top = losses[-1] or 1
    curve = []                       # kayıp aşım eğrisi: eşik → yıllık aşılma olasılığı
    for i in range(21):
        threshold = top * i / 20
        exceed = sum(1 for v in losses if v > threshold) / len(losses)
        curve.append([round(threshold, 2), round(exceed, 4)])
    result = {"mean_loss": round(mean, 2), "p50": round(_percentile(losses, 50), 2), "p90": round(_percentile(losses, 90), 2),
              "p95": round(_percentile(losses, 95), 2), "p99": round(_percentile(losses, 99), 2),
              "zero_share": round(sum(1 for v in losses if v == 0) / len(losses), 4)}
    run_id = c.db.execute("INSERT INTO tdr_risk_quant_runs (risk_id, inputs_json, iterations, mean_loss, p50, p90, p95, p99, "
                          "zero_share, curve_json, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (risk["id"], json.dumps(inputs), iterations, result["mean_loss"], result["p50"], result["p90"],
                           result["p95"], result["p99"], result["zero_share"], json.dumps(curve), c.principal.username,
                           utcnow())).lastrowid
    c.db.execute("UPDATE tdr_supplier_risks SET ale=?, quantified_at=? WHERE id=?", (result["mean_loss"], utcnow(), risk["id"]))
    audit.log(c.db, c.principal, "QUANTIFY", "supplier_risks", risk["id"], {"inputs": inputs, **result})
    return 201, {"id": run_id, "risk_id": risk["id"], "inputs": inputs, "iterations": iterations, **result, "curve": curve}


def quant_latest(c):
    authz.check(c.principal, RESOURCES["supplier_risks"], "read")
    run = one(c.db, "SELECT * FROM tdr_risk_quant_runs WHERE risk_id=? ORDER BY id DESC LIMIT 1", (c.params["id"],))
    if not run:
        return {"run": None}
    run["inputs"] = json.loads(run.pop("inputs_json"))
    run["curve"] = json.loads(run.pop("curve_json"))
    return {"run": run}


def quant_summary(c):
    """Nicelleştirilmiş riskler: en yüksek beklenen yıllık kayıp ve portföy benzetimi (bağımsızlık varsayımı)."""
    authz.check(c.principal, RESOURCES["supplier_risks"], "read")
    latest = rows(c.db, """SELECT q.* , r.code, r.title, r.company_id, r.risk_level FROM tdr_risk_quant_runs q
        JOIN tdr_supplier_risks r ON r.id=q.risk_id WHERE r.status IN ('open','in_treatment','accepted')
        AND q.id=(SELECT MAX(id) FROM tdr_risk_quant_runs q2 WHERE q2.risk_id=q.risk_id) ORDER BY q.mean_loss DESC""")
    if not latest:
        return {"risks": [], "portfolio": None}
    totals = [0.0] * 4000
    for i, run in enumerate(latest[:25]):
        losses = simulate(json.loads(run["inputs_json"]), 4000, 7919 * (i + 1))
        random.Random(i).shuffle(losses)   # nosec B311 - bağımsız riskleri birleştirmek için karıştırma
        totals = [a + b for a, b in zip(totals, losses)]
    totals.sort()
    portfolio = {"mean": round(sum(totals) / len(totals), 2), "p50": round(_percentile(totals, 50), 2),
                 "p90": round(_percentile(totals, 90), 2), "p95": round(_percentile(totals, 95), 2),
                 "risks": min(len(latest), 25)}
    losses_actual = one(c.db, "SELECT COALESCE(SUM(net_loss),0) AS s FROM tdr_loss_events WHERE occurred_on >= ?",
                        ((date.today() - timedelta(days=365)).isoformat(),))["s"]
    return {"risks": [{k: r[k] for k in ("risk_id", "code", "title", "risk_level", "mean_loss", "p90", "p95", "created_at")}
                      for r in latest[:10]], "portfolio": portfolio, "actual_losses_12m": float(losses_actual or 0)}


def register(app):
    app.route("GET", API + "/privacy_breaches/open", breaches_open)
    app.route("GET", API + "/privacy_breaches/{id}/context", breach_context)
    app.route("POST", API + "/rcsa_campaigns/{id}/launch", rcsa_launch)
    app.route("POST", API + "/rcsa_campaigns/{id}/close", rcsa_close)
    app.route("GET", API + "/rcsa_campaigns/{id}/context", rcsa_context)
    app.route("POST", API + "/rcsa_items/{id}/respond", rcsa_respond)
    app.route("POST", API + "/rcsa_items/{id}/finding", rcsa_finding)
    app.route("POST", API + "/supplier_risks/{id}/quantify", quantify)
    app.route("GET", API + "/supplier_risks/{id}/quant", quant_latest)
    app.route("GET", API + "/risks/quant-summary", quant_summary)


def seed(db):
    for code, (value, description) in DEFAULT_POLICIES.items():
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))
