"""Uyum (GRC): KS GRC'nin (control@7720f4b) iş modeli bu altyapıda. K-015.

Kavramlar ve KS GRC karşılıkları
- Çerçeve: standart (standards) → madde (clauses, hiyerarşik, uygulanabilirlik bildirimi/SoA alanlarıyla),
  süreç (processes), kontrol hedefi (objectives), doküman (documents).
- Kontrol (controls): manuel veya otomatik; yaklaşım, sıklık, kritiklik, test yöntemi, beklenen sonuç.
  Kontrol ↔ madde / süreç / hedef / risk / doküman eşlemeleri ayrı bağlantı tablolarındadır.
- Kontrol çalışması (executions): değiştirilemez. Kontrol tanımı ve eşlemeleri o anki haliyle
  `definition_json` içinde dondurulur; kaynak bilgisi `provenance_json` içindedir; bağlı kanıtların sürümü ve
  SHA-256 özeti ayrı ve değiştirilemez satırlarda saklanır (KS GRC execution_service).
  Kurallar: aktif kontrol; sonuçlandırılmış denetime çalışma eklenemez; zaman saat dilimli ve gelecekte değil;
  veri toplama eksik/hatalıysa (collection_status partial/error) sonuç yalnızca "belirsiz" olabilir;
  MCP yalnızca otomatik kontrole "mcp" kaynaklı sonuç yazar; başarısız sonuç bulgu açar.
- İç otomatik kontroller (bu altyapıya özgü): kontrolün `automation` alanı portal verisi üzerinde tanımlı bir
  kuralı seçer (ör. kritik tedarikçi değerlendirmeleri zamanında mı). Çalıştırma, sorgu sonucunun özetini
  kanıt olarak saklar. Aynı kontrol için açık otomatik bulgu varsa yenisi açılmaz, tekrar sayısı artar.
- Denetim (audits): kapsam standart + madde seçimidir; her standart için en az bir madde (başlarken).
  Denetim tamamlanınca planlanan kontrol listesi dondurulur (audit_plan); sonuçlandırılmış denetim yeniden
  açılamaz, kapsamı değişmez. Eşzamanlı kapsam düzenlemesi `expected_revision` ile korunur.
- Kanıt (evidence): dosya sürümleri değiştirilemez; içerik veritabanında (yedekle birlikte taşınır), her
  indirmede SHA-256 yeniden doğrulanır. Dosya imzası ve arşiv bombası denetimi KS GRC ile aynıdır.
- Bulgu (findings) ve düzeltici faaliyet (grc_actions, DÖF): faaliyet "doğrulama" aşamasından geçer; etkinliği
  faaliyet sahibinden farklı bir Yönetici veya Denetçi doğrular. Açık faaliyeti olan bulgu kapanmaz.
- Uyum göstergesi (compliance): KS GRC ile aynı anlam. Her kontrolün en son çalışması sayılır; denetim
  seçiliyse yalnızca o denetimin çalışmaları. Tamamlanma belirsiz/uygulanamaz sonucu saymaz. Sertifikasyon
  kararı değildir.
"""
import hashlib
import json
import mimetypes
import re
from datetime import date, datetime, timedelta, timezone

from .. import audit, auth as authz, crud, files
from ..db import one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY, Raw, guard_readonly
from ..schema import RESOURCES, Resource, fk
from .core import PROCESSES, policy, supplier_units
from .grc_library import link_rules

M = "grc"
REQUIRES = ("risks", "documents")
LIBRARY = {"ADMIN"}                                       # çerçeve ve kontrol kütüphanesi
ASSURANCE = {"ADMIN", "AUDITOR"}                          # denetim, test sonucu, bulgu
CONTRIBUTORS = {"ADMIN", "AUDITOR", "SUPPLIER_MANAGER", "UNIT_USER"}   # kanıt ve düzeltici faaliyet
RESULTS = ("pass", "fail", "inconclusive", "not_applicable")
FREQUENCY_DAYS = {"continuous": 1, "daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92, "semiannual": 183,
                  "yearly": 366, "on_demand": None}
CLOSED_AUDIT = ("completed", "closed", "cancelled")
DISCLAIMER = "Kontrol ve kanıta dayalı ön gösterge; sertifikasyon veya standart uygunluğu kararı değildir."

STANDARDS = Resource("standards", "Standartlar", {
    "code": "TEXT NOT NULL", "name": "TEXT NOT NULL", "version": "TEXT", "issuer": "TEXT", "description": "TEXT",
    "active": "INTEGER NOT NULL DEFAULT 1", "library_key": "TEXT", "license": "TEXT", "language": "TEXT",
    "source_url": "TEXT", "source_sha256": "TEXT", "published": "DATE", "installed_at": "TIMESTAMP",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, unique=(("code", "version"),), write_roles=LIBRARY,
    readonly=("library_key", "source_sha256", "installed_at"))

CLAUSE_TYPES = ("family", "control", "enhancement", "function", "category", "subcategory", "clause", "annex",
                "requirement", "article")
CLAUSES = Resource("clauses", "Maddeler", {
    "standard_id": fk("standards"), "code": "TEXT NOT NULL", "title": "TEXT NOT NULL",
    "parent_id": fk("clauses", False), "clause_type": "TEXT", "description": "TEXT", "guidance": "TEXT",
    "assessment": "TEXT", "tags": "TEXT", "position": "INTEGER", "applicable": "INTEGER NOT NULL DEFAULT 1",
    "justification": "TEXT"},
    module=M, unique=(("standard_id", "code"),), search=("code", "title"), write_roles=LIBRARY,
    indexes=(("standard_id", "position"),), enums={"clause_type": CLAUSE_TYPES})

# Standartlar arası madde ilişkisi (çapraz eşleme, K-023). Yön: from → to. Küme ilişkisi NIST IR 8477 anlamında:
# equivalent (aynı gereksinim), subset (from, to'nun alt kümesi: from ihlali to'yu da ihlal eder), superset,
# intersects (kısmen örtüşür), related (ilgili, bilgi amaçlı). Silinmez; yanlış ilişki pasifleştirilir.
CLAUSE_LINKS = Resource("clause_links", "Madde İlişkileri", {
    "from_clause_id": fk("clauses", cascade=True), "to_clause_id": fk("clauses", cascade=True),
    "relation": "TEXT NOT NULL DEFAULT 'intersects'", "source": "TEXT NOT NULL DEFAULT 'manual'",
    "rationale": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1", "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, unique=(("from_clause_id", "to_clause_id"),), search=("rationale",), write_roles=LIBRARY,
    readonly=("created_by",), indexes=(("to_clause_id",),),
    enums={"relation": ("equivalent", "subset", "superset", "intersects", "related"),
           "source": ("official", "crosswalk", "manual", "suggested")})

OBJECTIVES = Resource("objectives", "Kontrol Hedefleri", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "description": "TEXT",
    "process_id": fk("processes", False), "owner": "TEXT"},
    module=M, code_prefix="KHD", write_roles=LIBRARY)

CONTROLS = Resource("controls", "Kontroller", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "description": "TEXT",
    "execution_mode": "TEXT NOT NULL DEFAULT 'manual'", "nature": "TEXT NOT NULL DEFAULT 'detective'",
    "frequency": "TEXT NOT NULL DEFAULT 'on_demand'", "criticality": "TEXT NOT NULL DEFAULT 'medium'",
    "method_type": "TEXT NOT NULL DEFAULT 'inspection'", "method": "TEXT", "expected_result": "TEXT",
    "owner": "TEXT", "org_unit_id": fk("org_units", False), "automation": "TEXT",
    "active": "INTEGER NOT NULL DEFAULT 1", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="KTL", write_roles=LIBRARY, machine="r",
    enums={"execution_mode": ("manual", "automatic"),
           "nature": ("preventive", "detective", "corrective", "directive", "compensating"),
           "frequency": tuple(FREQUENCY_DAYS), "criticality": ("low", "medium", "high", "critical"),
           "method_type": ("query", "sampling", "inspection", "interview", "observation")})

LINKS = {   # kontrol eşlemeleri: istek anahtarı -> (tablo kaynağı, hedef sütun, hedef kaynak)
    "clauses": ("control_clauses", "clause_id", "clauses"),
    "processes": ("control_processes", "process_id", "processes"),
    "objectives": ("control_objectives", "objective_id", "objectives"),
    "risks": ("control_risks", "risk_id", "supplier_risks"),
    "documents": ("control_documents", "document_id", "documents"),
}
for _name, (_table, _col, _target) in LINKS.items():
    Resource(_table, "Kontrol eşlemesi", {"control_id": fk("controls", cascade=True), _col: fk(_target, cascade=True)},
             module=M, unique=(("control_id", _col),), api=(), search=())

Resource("objective_risks", "Kontrol hedefinin ele aldığı riskler", {
    "objective_id": fk("objectives", cascade=True), "risk_id": fk("supplier_risks", cascade=True)},
    module=M, unique=(("objective_id", "risk_id"),), api=(), search=())

Resource("document_clauses", "Dokümanın karşıladığı maddeler", {
    "document_id": fk("documents", cascade=True), "clause_id": fk("clauses", cascade=True)},
    module=M, unique=(("document_id", "clause_id"),), api=(), search=())

AUDITS = Resource("audits", "Denetimler", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "kind": "TEXT NOT NULL DEFAULT 'internal'",
    "supplier_id": fk("suppliers", False), "company_id": fk("companies", False), "audit_objective": "TEXT",
    "scope": "TEXT",
    "planned_start": "DATE", "planned_end": "DATE", "actual_start": "DATE", "actual_end": "DATE",
    "lead_auditor": "TEXT", "auditors": "TEXT", "auditees": "TEXT", "status": "TEXT NOT NULL DEFAULT 'planned'",
    "conclusion": "TEXT", "opinion": "TEXT", "revision": "INTEGER NOT NULL DEFAULT 0",
    "plan_captured_at": "TIMESTAMP", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="DNT", code_yearly=True, write_roles=ASSURANCE, api=("list", "get"), readonly=("revision", "plan_captured_at"),
    enums={"kind": ("internal", "external", "certification", "supplier"),
           "status": ("planned", "in_progress", "completed", "closed", "cancelled"),
           "opinion": ("effective", "partially_effective", "ineffective")})
Resource("audit_standards", "Denetim standardı", {"audit_id": fk("audits", cascade=True), "standard_id": fk("standards")},
         module=M, unique=(("audit_id", "standard_id"),), api=(), search=())
Resource("audit_clauses", "Denetim maddesi", {"audit_id": fk("audits", cascade=True), "clause_id": fk("clauses")},
         module=M, unique=(("audit_id", "clause_id"),), api=(), search=())
Resource("audit_processes", "Denetlenen süreç", {"audit_id": fk("audits", cascade=True), "process_id": fk("processes")},
         module=M, unique=(("audit_id", "process_id"),), api=(), search=())   # ISO 9001 9.2: süreç bazlı denetim programı
Resource("audit_plan", "Dondurulmuş denetim planı", {
    "audit_id": fk("audits"), "clause_id": fk("clauses"), "control_id": fk("controls")},
    module=M, unique=(("audit_id", "clause_id", "control_id"),), api=(), search=(), immutable=True)

EVIDENCE = Resource("evidence", "Kanıtlar", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "description": "TEXT", "reference_url": "TEXT",
    "source": "TEXT NOT NULL DEFAULT 'manual'", "confidentiality": "TEXT NOT NULL DEFAULT 'internal'",
    "status": "TEXT NOT NULL DEFAULT 'current'", "period_start": "DATE", "period_end": "DATE", "expires_at": "DATE",
    "supplier_id": fk("suppliers", False), "org_unit_id": fk("org_units", False),
    "file_name": "TEXT", "file_size": "INTEGER", "mime_type": "TEXT", "hash_sha256": "TEXT",
    "current_version": "INTEGER", "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="KNT", code_yearly=True, search=("code", "title"), write_roles=CONTRIBUTORS, machine="r",
    readonly=("file_name", "file_size", "mime_type", "hash_sha256", "current_version", "created_by"),
    enums={"source": ("manual", "mcp", "system"), "confidentiality": ("internal", "confidential", "restricted"),
           "status": ("current", "expired", "archived")})
FILES = Resource("evidence_files", "Kanıt Dosya Sürümleri", {
    "evidence_id": fk("evidence"), "version": "INTEGER NOT NULL", "file_name": "TEXT NOT NULL",
    "file_size": "INTEGER NOT NULL", "mime_type": "TEXT NOT NULL", "sha256": "TEXT NOT NULL",
    "uploaded_by": "TEXT NOT NULL", "uploaded_at": "TIMESTAMP NOT NULL"},
    module=M, unique=(("evidence_id", "version"),), api=("list",), search=("file_name",), immutable=True)
Resource("evidence_blobs", "Kanıt dosya içeriği", {"file_id": fk("evidence_files"), "content": "BLOB NOT NULL"},
         module=M, unique=(("file_id",),), api=(), search=(), immutable=True)
EVIDENCE_LINKS = {
    "controls": ("evidence_controls", "control_id", "controls"),
    "audits": ("evidence_audits", "audit_id", "audits"),
    "clauses": ("evidence_clauses", "clause_id", "clauses"),
}
for _name, (_table, _col, _target) in EVIDENCE_LINKS.items():
    Resource(_table, "Kanıt bağlantısı", {"evidence_id": fk("evidence", cascade=True), _col: fk(_target, cascade=True)},
             module=M, unique=(("evidence_id", _col),), api=(), search=())

EXECUTIONS = Resource("executions", "Kontrol Sonuçları", {
    "control_id": fk("controls"), "audit_id": fk("audits", False), "status": "TEXT NOT NULL",
    "source": "TEXT NOT NULL DEFAULT 'manual'", "details": "TEXT", "sample_size": "INTEGER", "exceptions": "INTEGER",
    "executed_at": "TIMESTAMP NOT NULL", "recorded_at": "TIMESTAMP NOT NULL", "recorded_by": "TEXT NOT NULL",
    "definition_json": "TEXT NOT NULL", "provenance_json": "TEXT NOT NULL"},
    module=M, api=("list", "get"), search=("details",), write_roles=ASSURANCE, machine="r", immutable=True,
    indexes=(("control_id", "executed_at"),),
    enums={"status": RESULTS, "source": ("manual", "mcp", "system")})
Resource("execution_evidence", "Çalışmaya bağlı kanıt sürümleri", {
    "execution_id": fk("executions"), "evidence_id": fk("evidence"), "version": "INTEGER", "sha256": "TEXT",
    "file_name": "TEXT"},
    module=M, unique=(("execution_id", "evidence_id"),), api=("list",), search=(), immutable=True)

FINDINGS = Resource("findings", "Bulgular", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "control_id": fk("controls", False),
    "execution_id": fk("executions", False), "audit_id": fk("audits", False), "supplier_id": fk("suppliers", False),
    "source": "TEXT NOT NULL DEFAULT 'audit'", "clause_id": fk("clauses", False), "process_id": fk("processes", False),
    "risk_id": fk("supplier_risks", False), "company_id": fk("companies", False),
    "description": "TEXT", "severity": "TEXT NOT NULL DEFAULT 'medium'", "status": "TEXT NOT NULL DEFAULT 'open'",
    "owner": "TEXT", "due_date": "DATE", "root_cause": "TEXT", "closure_note": "TEXT",
    "recurrence": "INTEGER NOT NULL DEFAULT 1", "last_seen_at": "TIMESTAMP", "closed_at": "TIMESTAMP",
    "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="BLG", code_yearly=True, search=("code", "title"), write_roles=ASSURANCE,
    readonly=("execution_id", "recurrence", "last_seen_at", "closed_at", "created_by"),
    enums={"severity": ("low", "medium", "high", "critical"),
           "status": ("open", "in_progress", "closed", "accepted"),
           "source": ("audit", "control_test", "exercise", "self_assessment", "external", "incident")})

ACTIONS = Resource("grc_actions", "Düzeltici Faaliyetler", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "finding_id": fk("findings", False),
    "control_id": fk("controls", False), "description": "TEXT", "owner": "TEXT NOT NULL",
    "org_unit_id": fk("org_units", False), "due_date": "DATE NOT NULL", "priority": "TEXT NOT NULL DEFAULT 'medium'",
    "status": "TEXT NOT NULL DEFAULT 'open'", "resolution": "TEXT", "verified_by": "TEXT",
    "verification_note": "TEXT", "closed_at": "TIMESTAMP", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"},
    module=M, code_prefix="DOF", code_yearly=True, search=("code", "title"), write_roles=CONTRIBUTORS, readonly=("verified_by", "closed_at"),
    enums={"priority": ("low", "medium", "high", "critical"),
           "status": ("open", "in_progress", "validation", "completed", "cancelled")})


# ------------------------------------------------------------------ kurallar ve kapsam

def _date(value, label):
    if value in (None, ""):
        return None
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except (TypeError, ValueError):
        raise crud.Invalid(f"{label} geçerli bir YYYY-AA-GG tarihi olmalı") from None
    return value


def _control_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if merged.get("automation") and merged["automation"] not in AUTOMATIONS:
        raise crud.Invalid("Tanımsız otomatik kural: " + str(merged["automation"]))
    if merged.get("automation") and merged.get("execution_mode") != "automatic":
        raise crud.Invalid("İç otomatik kural yalnızca otomatik kontrolde seçilir")


def _clause_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if merged.get("parent_id"):
        parent = crud.get(db, CLAUSES, merged["parent_id"])
        if parent["standard_id"] != merged["standard_id"] or (current and parent["id"] == current["id"]):
            raise crud.Invalid("Üst madde aynı standarda ait başka bir madde olmalı")
    if merged.get("applicable") == 0 and not (merged.get("justification") or "").strip():
        raise crud.Invalid("Uygulanabilir olmayan madde için gerekçe yazın (uygulanabilirlik bildirimi)")


def _evidence_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    for key, label in (("period_start", "Dönem başlangıcı"), ("period_end", "Dönem bitişi"),
                       ("expires_at", "Geçerlilik sonu")):
        _date(merged.get(key), label)
    if merged.get("period_start") and merged.get("period_end") and merged["period_end"] < merged["period_start"]:
        raise crud.Invalid("Kanıt dönem bitişi başlangıçtan önce olamaz")
    if merged.get("reference_url") and not re.match(r"^https?://", merged["reference_url"]):
        raise crud.Invalid("Referans bağlantısı http:// veya https:// ile başlamalı")
    if current is None:
        data.setdefault("created_by", principal.username if principal else "system")
        if principal and principal.role == "MACHINE":
            data["source"] = "mcp"


def _evidence_scope(db, record):
    units = {record.get("org_unit_id")}
    if record.get("supplier_id"):
        units |= supplier_units(db, record["supplier_id"])
    return units


def _finding_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    _date(merged.get("due_date"), "Hedef tarih")
    if merged.get("severity") in ("high", "critical") and merged.get("status") in ("open", "in_progress") \
            and not merged.get("due_date") and current is not None and "due_date" in data:
        raise crud.Invalid("Yüksek ve kritik bulguda hedef tarih boş bırakılamaz")
    if current is None:
        data.setdefault("created_by", principal.username if principal else "system")
        data.setdefault("last_seen_at", utcnow())
        return
    if data.get("status") and data["status"] != current["status"]:
        target = data["status"]
        if current["status"] in ("closed", "accepted") and target in ("open", "in_progress"):
            if not (data.get("closure_note") or "").strip():
                raise crud.Invalid("Bulguyu yeniden açarken gerekçeyi kapanış notuna yazın")
            data["closed_at"] = None
        if target == "closed":
            if not (merged.get("closure_note") or "").strip():
                raise crud.Invalid("Bulguyu kapatmak için kapanış notu gerekli")
            pending = one(db, "SELECT COUNT(*) AS n FROM tdr_grc_actions WHERE finding_id=? AND status NOT IN "
                              "('completed','cancelled')", (current["id"],))["n"]
            if pending:
                raise crud.Conflict(f"Bulgunun {pending} açık düzeltici faaliyeti var; önce tamamlanmalı")
            data["closed_at"] = utcnow()
        if target == "accepted":
            if not principal or principal.role != "ADMIN":
                raise crud.Forbidden("Bulgu riskini yalnızca Yönetici kabul edebilir")
            if not (merged.get("closure_note") or "").strip():
                raise crud.Invalid("Risk kabul gerekçesini kapanış notuna yazın")
            data["closed_at"] = utcnow()


def _action_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    _date(merged.get("due_date"), "Hedef tarih")
    if not merged.get("finding_id") and not merged.get("control_id"):
        raise crud.Invalid("Düzeltici faaliyet bir bulguya veya kontrole bağlanır")
    if merged.get("finding_id"):
        finding = crud.get(db, FINDINGS, merged["finding_id"])
        if current is None and finding["status"] in ("closed", "accepted"):
            raise crud.Conflict("Kapalı bulguya faaliyet eklenemez; önce bulguyu yeniden açın")
        if not merged.get("control_id") and finding["control_id"]:
            data["control_id"] = finding["control_id"]
    if current is None:
        if merged.get("status", "open") not in ("open", "in_progress"):
            raise crud.Invalid("Yeni faaliyet açık veya üzerinde çalışılıyor durumunda başlar")
        return
    if current["status"] in ("completed", "cancelled") and set(data) - {"verification_note"}:
        raise crud.Conflict("Tamamlanmış veya iptal edilmiş faaliyet değiştirilemez")
    target = data.get("status")
    if target and target != current["status"]:
        if target == "validation" and not (merged.get("resolution") or "").strip():
            raise crud.Invalid("Doğrulamaya göndermek için yapılanları çözüm açıklamasına yazın")
        if target == "completed":
            if current["status"] != "validation":
                raise crud.Conflict("Faaliyet önce doğrulamaya gönderilir; etkinlik doğrulandıktan sonra tamamlanır")
            if not principal or principal.role not in ASSURANCE:
                raise crud.Forbidden("Etkinliği yalnızca Yönetici veya Denetçi doğrular")
            if principal.username == current["owner"]:
                raise crud.Forbidden("Faaliyet sahibi kendi faaliyetinin etkinliğini doğrulayamaz")
            if not (merged.get("verification_note") or "").strip():
                raise crud.Invalid("Doğrulama notu gerekli (etkinlik nasıl doğrulandı)")
            data["verified_by"] = principal.username
            data["closed_at"] = utcnow()
        if target == "cancelled":
            if not principal or principal.role not in ASSURANCE:
                raise crud.Forbidden("Faaliyeti yalnızca Yönetici veya Denetçi iptal eder")
            if not (merged.get("verification_note") or "").strip():
                raise crud.Invalid("İptal gerekçesini doğrulama notuna yazın")
            data["closed_at"] = utcnow()


def _action_scope(db, record):
    units = {record.get("org_unit_id")}
    if record.get("control_id"):
        control = one(db, "SELECT org_unit_id FROM tdr_controls WHERE id=?", (record["control_id"],))
        units.add(control["org_unit_id"] if control else None)
    return units


def evidence_filter(principal, alias=""):
    """Kısıtlı kanıt (ör. sızma testi raporu) bilmesi gereken kişilere açıktır: Yönetici, Denetçi ve yükleyen.
    (SQL koşulu, parametreler) döner; ayrıcalıklı rolde koşul yoktur."""
    if principal is None or principal.role in ASSURANCE:
        return "1=1", ()
    p = alias + "." if alias else ""
    return f"({p}confidentiality <> 'restricted' OR {p}created_by = ?)", (principal.username,)


def evidence_visible(principal, evidence):
    return (principal is None or principal.role in ASSURANCE or evidence.get("confidentiality") != "restricted"
            or evidence.get("created_by") == principal.username)


def _hidden_evidence_ids(principal):
    if principal is None or principal.role in ASSURANCE:
        return None
    return ("evidence_id NOT IN (SELECT id FROM tdr_evidence WHERE confidentiality='restricted' AND "
            "COALESCE(created_by,'') <> ?)", (principal.username,))


EVIDENCE.row_filter = lambda principal: evidence_filter(principal)
EVIDENCE.can_read = evidence_visible
FILES.row_filter = _hidden_evidence_ids
CONTROLS.before_save = _control_rules
CLAUSES.before_save = _clause_rules
CLAUSE_LINKS.before_save = link_rules
EVIDENCE.before_save = _evidence_rules
EVIDENCE.scope = _evidence_scope
FINDINGS.before_save = _finding_rules
ACTIONS.before_save = _action_rules
ACTIONS.scope = _action_scope


# ------------------------------------------------------------------ kontrol bağlamı ve eşlemeler

def _ids(value, label):
    if not isinstance(value, list) or any(type(i) is not int or i <= 0 for i in value) or len(value) > 500:
        raise crud.Invalid(f"{label}: pozitif tam sayı listesi olmalı")
    return sorted(set(value))


def control_links(db, control_id):
    out = {}
    for key, (table, col, target) in LINKS.items():
        res = RESOURCES[target]
        out[key] = rows(db, f"SELECT t.* FROM {res.table} t JOIN tdr_{table} m ON m.{col}=t.id "
                            f"WHERE m.control_id=? ORDER BY t.id", (control_id,))
    return out


def set_links(c):
    control = crud.get(c.db, CONTROLS, c.params["id"])
    authz.check(c.principal, CONTROLS, "write")
    changed = {}
    for key, (table, col, target) in LINKS.items():
        if key not in c.body:
            continue
        ids = _ids(c.body[key], key)
        res = RESOURCES[target]
        if ids:
            found = {r["id"] for r in rows(c.db, f"SELECT id FROM {res.table} WHERE id IN "
                                                 f"({','.join('?' * len(ids))})", ids)}
            if found != set(ids):
                raise crud.Invalid(f"{res.label}: bulunamayan kayıt seçildi")
        before = {r[col] for r in rows(c.db, f"SELECT {col} FROM tdr_{table} WHERE control_id=?", (control["id"],))}
        c.db.execute(f"DELETE FROM tdr_{table} WHERE control_id=?", (control["id"],))   # küme yerine koyma
        for target_id in ids:
            c.db.execute(f"INSERT INTO tdr_{table} (control_id, {col}) VALUES (?,?)", (control["id"], target_id))
        changed[key] = {"added": sorted(set(ids) - before), "removed": sorted(before - set(ids))}
    audit.log(c.db, c.principal, "LINK", CONTROLS.name, control["id"], changed)
    return control_context_data(c.db, control["id"])


def latest_execution(db, control_id, audit_id=None):
    sql = "SELECT * FROM tdr_executions WHERE control_id=?" + (" AND audit_id=?" if audit_id else "")
    return one(db, sql + " ORDER BY executed_at DESC, id DESC LIMIT 1",
               (control_id, audit_id) if audit_id else (control_id,))


def test_state(control, last):
    """Sıklığa göre test durumu: due (yapılması gerekiyor), ok, overdue, none (ihtiyaca göre)."""
    days = FREQUENCY_DAYS.get(control["frequency"])
    if not control["active"]:
        return {"state": "inactive", "due_on": None}
    if days is None:
        return {"state": "on_demand", "due_on": None}
    if not last:
        return {"state": "never", "due_on": None}
    executed = _as_date(last["executed_at"])
    due = executed + timedelta(days=days)
    return {"state": "overdue" if due < date.today() else "ok", "due_on": due.isoformat()}


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def control_context_data(db, control_id, principal=None):
    control = crud.get(db, CONTROLS, control_id)
    control.update(control_links(db, control_id))
    control["executions"] = rows(db, "SELECT id, status, source, executed_at, recorded_by, audit_id, details "
                                     "FROM tdr_executions WHERE control_id=? ORDER BY executed_at DESC, id DESC "
                                     "LIMIT 25", (control_id,))
    last = control["executions"][0] if control["executions"] else None
    control["latest"] = last
    control["test"] = test_state(control, last)
    control["findings"] = rows(db, "SELECT * FROM tdr_findings WHERE control_id=? ORDER BY "
                                   "CASE WHEN status IN ('open','in_progress') THEN 0 ELSE 1 END, id DESC LIMIT 50",
                               (control_id,))
    control["actions"] = rows(db, "SELECT * FROM tdr_grc_actions WHERE control_id=? ORDER BY due_date", (control_id,))
    visible, args = evidence_filter(principal, "e")
    control["evidence"] = rows(db, "SELECT e.* FROM tdr_evidence e JOIN tdr_evidence_controls m ON m.evidence_id=e.id "
                                   f"WHERE m.control_id=? AND {visible} ORDER BY e.id DESC", (control_id, *args))
    control["automation_info"] = AUTOMATIONS.get(control["automation"], {}).get("label") if control["automation"] else None
    return control


def control_context(c):
    authz.check(c.principal, CONTROLS, "read")
    return control_context_data(c.db, c.params["id"], c.principal)


def automations(c):
    authz.check(c.principal, CONTROLS, "read")
    return [{"value": k, "label": v["label"], "description": v["description"], "module": v["module"]}
            for k, v in AUTOMATIONS.items()]


# ------------------------------------------------------------------ kontrol çalışmaları

def _timestamp(value):
    if value in (None, ""):
        return utcnow()
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise crud.Invalid("Kontrol zamanı saat dilimli ISO 8601 olmalı ve gelecekte olmamalı") from None
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def record_execution(db, principal, data, source=None):
    """KS GRC execution_service.record + app._execute_base kuralları. (sonuç, bulgu) kimlikleri döner."""
    allowed = {"control_id", "audit_id", "status", "details", "executed_at", "provenance", "evidence_ids",
               "evidence_versions", "severity", "sample_size", "exceptions", "source"}
    extra = set(data) - allowed
    if extra:
        raise crud.Invalid("Bilinmeyen alan: " + ", ".join(sorted(extra)))
    if type(data.get("control_id")) is not int:
        raise crud.Invalid("Geçerli kontrol gerekli")
    db.lock(f"control:{data['control_id']}")
    control = one(db, "SELECT * FROM tdr_controls WHERE id=?", (data["control_id"],))
    if not control or not control["active"]:
        raise crud.Invalid("Aktif ve geçerli kontrol gerekli")
    machine = principal.role == "MACHINE"
    source = source or ("mcp" if machine else data.get("source") or "manual")
    if machine and (source != "mcp" or control["execution_mode"] != "automatic"):
        raise crud.Forbidden("MCP yalnızca otomatik kontrole MCP kaynaklı sonuç yazabilir")
    if not machine and source == "mcp":
        raise crud.Invalid("MCP kaynaklı sonucu yalnızca MCP anahtarı yazar")
    if source == "system" and data.get("source"):
        raise crud.Invalid("Sistem kaynaklı sonuç yalnızca iç otomatik çalıştırmayla oluşur")
    audit_id = data.get("audit_id")
    if audit_id is not None:
        audit_row = one(db, "SELECT status FROM tdr_audits WHERE id=?", (audit_id,)) if type(audit_id) is int else None
        if not audit_row:
            raise crud.Invalid("Geçerli denetim gerekli")
        if audit_row["status"] in CLOSED_AUDIT:
            raise crud.Conflict("Sonuçlandırılmış denetime yeni kontrol çalışması eklenemez")
    status = data.get("status")
    if status not in RESULTS:
        raise crud.Invalid("Geçersiz kontrol sonucu (pass, fail, inconclusive, not_applicable)")
    provenance = data.get("provenance", {})
    if not isinstance(provenance, dict) or len(json.dumps(provenance)) > 32768:
        raise crud.Invalid("provenance en fazla 32 KB JSON nesnesi olmalı")
    collection = provenance.get("collection_status")
    if collection is not None and collection not in ("complete", "partial", "error"):
        raise crud.Invalid("collection_status complete, partial veya error olmalı")
    if collection in ("partial", "error") and status != "inconclusive":
        raise crud.Invalid("Eksik veya hatalı veri toplama yalnızca belirsiz sonuç olarak kaydedilebilir")
    if status == "fail" and not (data.get("details") or "").strip():
        raise crud.Invalid("Başarısız sonuç için test sonucunu (bulguyu) açıklayın")
    for key in ("sample_size", "exceptions"):
        if data.get(key) is not None and (type(data[key]) is not int or data[key] < 0):
            raise crud.Invalid("Örnek ve istisna sayısı negatif olmayan tam sayı olmalı")
    if data.get("sample_size") is not None and (data.get("exceptions") or 0) > data["sample_size"]:
        raise crud.Invalid("İstisna sayısı örnek büyüklüğünü aşamaz")
    if data.get("severity") is not None and data["severity"] not in FINDINGS.enums["severity"]:
        raise crud.Invalid("Geçersiz bulgu önemi")
    executed_at = _timestamp(data.get("executed_at"))
    ids = data.get("evidence_ids", [])
    versions = data.get("evidence_versions", {})
    if not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids):
        raise crud.Invalid("evidence_ids pozitif tam sayı listesi olmalı")
    if not isinstance(versions, dict) or set(versions) - {str(i) for i in ids}:
        raise crud.Invalid("Sürüm seçimi yalnızca bağlı kanıtları içerebilir")
    snapshots = []
    for evidence_id in sorted(set(ids)):
        ev = one(db, "SELECT * FROM tdr_evidence WHERE id=?", (evidence_id,))
        if not ev:
            raise crud.Invalid("Kanıt bulunamadı")
        version = versions.get(str(evidence_id))
        if version is not None and (type(version) is not int or version < 1):
            raise crud.Invalid("Kanıt sürümü pozitif tam sayı olmalı")
        if ev["current_version"]:
            version = version or ev["current_version"]
            file = one(db, "SELECT * FROM tdr_evidence_files WHERE evidence_id=? AND version=?", (evidence_id, version))
            if not file:
                raise crud.Invalid("Seçilen kanıt dosyası veya sürümü bulunamadı")
            snapshots.append((evidence_id, version, file["sha256"], file["file_name"]))
        elif version is not None:
            raise crud.Invalid("Dosyasız kanıtta sürüm seçilemez")
        else:
            snapshots.append((evidence_id, None, None, None))
    definition = dict(control)
    definition.update({k: [{"id": r["id"], "code": r.get("code"), "title": r.get("title") or r.get("name")}
                           for r in v] for k, v in control_links(db, control["id"]).items()})
    now = utcnow()
    execution_id = db.execute(
        "INSERT INTO tdr_executions (control_id, audit_id, status, source, details, sample_size, exceptions, "
        "executed_at, recorded_at, recorded_by, definition_json, provenance_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (control["id"], audit_id, status, source, (data.get("details") or "")[:20000], data.get("sample_size"),
         data.get("exceptions"), executed_at, now, principal.username,
         json.dumps(definition, ensure_ascii=False, default=str), json.dumps(provenance, ensure_ascii=False))).lastrowid
    for evidence_id, version, sha, name in snapshots:
        db.execute("INSERT INTO tdr_execution_evidence (execution_id, evidence_id, version, sha256, file_name) "
                   "VALUES (?,?,?,?,?)", (execution_id, evidence_id, version, sha, name))
        db.execute("INSERT INTO tdr_evidence_controls (evidence_id, control_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                   (evidence_id, control["id"]))
        if audit_id:
            db.execute("INSERT INTO tdr_evidence_audits (evidence_id, audit_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                       (evidence_id, audit_id))
    finding_id, repeated = None, False
    if status == "fail":
        severity = data.get("severity") or control["criticality"]
        if source in ("system", "mcp"):
            existing = one(db, "SELECT id FROM tdr_findings WHERE control_id=? AND status IN ('open','in_progress') "
                               "AND COALESCE(audit_id,0)=? AND created_by IN ('system','mcp') ORDER BY id LIMIT 1",
                           (control["id"], audit_id or 0))
            if existing:
                db.execute("UPDATE tdr_findings SET recurrence=recurrence+1, last_seen_at=?, description=?, "
                           "updated_at=? WHERE id=?", (now, (data.get("details") or "")[:20000], now, existing["id"]))
                finding_id, repeated = existing["id"], True
        if finding_id is None:
            due = (date.today() + timedelta(days={"critical": 15, "high": 30, "medium": 60, "low": 90}[severity]))
            finding_id = db.execute(
                "INSERT INTO tdr_findings (code, title, control_id, execution_id, audit_id, description, severity, "
                "status, owner, due_date, recurrence, last_seen_at, created_by, created_at, source) "
                "VALUES (?,?,?,?,?,?,?,'open',?,?,1,?,?,?,'control_test')",
                (crud.next_code(db, FINDINGS), f"{control['name']} — test başarısız",
                 control["id"], execution_id, audit_id, data.get("details") or "", severity, control["owner"],
                 due.isoformat(), now, "system" if source == "system" else principal.username if not machine else "mcp",
                 now)).lastrowid
    audit.log(db, principal, "EXECUTE", CONTROLS.name, control["id"],
              {"execution_id": execution_id, "status": status, "source": source, "finding_id": finding_id})
    return {"execution_id": execution_id, "finding_id": finding_id, "finding_repeated": repeated}


def create_execution(c):
    if c.principal.role != "MACHINE":      # MCP: yalnızca otomatik kontrole "mcp" sonucu (record_execution)
        authz.check(c.principal, EXECUTIONS, "write")
    return 201, record_execution(c.db, c.principal, c.body)


def execution_context(c):
    authz.check(c.principal, EXECUTIONS, "read")
    record = crud.get(c.db, EXECUTIONS, c.params["id"])
    record["definition"] = json.loads(record.pop("definition_json"))
    record["provenance"] = json.loads(record.pop("provenance_json"))
    record["evidence"] = rows(c.db, "SELECT x.*, e.code, e.title, e.confidentiality, e.created_by FROM "
                                    "tdr_execution_evidence x JOIN tdr_evidence e ON e.id=x.evidence_id "
                                    "WHERE x.execution_id=?", (record["id"],))
    for ev in record["evidence"]:                  # kısıtlı kanıtın varlığı ve özeti görünür, içeriği görünmez
        if not evidence_visible(c.principal, ev):
            ev.update(title="Kısıtlı kanıt", file_name=None, restricted=True)
    record["control"] = one(c.db, "SELECT id, code, name, active FROM tdr_controls WHERE id=?", (record["control_id"],))
    record["finding"] = one(c.db, "SELECT id, code, status FROM tdr_findings WHERE execution_id=?", (record["id"],))
    return record


# ------------------------------------------------------------------ iç otomatik kontroller (portal verisi)

def _today():
    return date.today().isoformat()


def _rule_supplier_owner(db, app):
    items = rows(db, "SELECT code, name FROM tdr_suppliers WHERE status='active' AND (owner IS NULL OR owner='') "
                     "ORDER BY code")
    checked = one(db, "SELECT COUNT(*) AS n FROM tdr_suppliers WHERE status='active'")["n"]
    return checked, items, "Aktif tedarikçilerin ilişki sahibi atanmış"


def _rule_reviews(db, app):
    months = int(policy(db, "review.cadence_months", {}).get("critical", 6))
    limit = (date.today() - timedelta(days=round(months * 30.44))).isoformat()
    items = rows(db, """SELECT s.code, s.name, MAX(r.period_end) AS last_review FROM tdr_suppliers s
        LEFT JOIN tdr_performance_reviews r ON r.supplier_id=s.id
        WHERE s.status='active' AND s.tier='critical' GROUP BY s.id, s.code, s.name
        HAVING MAX(r.period_end) IS NULL OR MAX(r.period_end) < ? ORDER BY s.code""", (limit,))
    checked = one(db, "SELECT COUNT(*) AS n FROM tdr_suppliers WHERE status='active' AND tier='critical'")["n"]
    return checked, items, f"Kritik tedarikçiler son {months} ayda değerlendirilmiş"


def _rule_risk_reviews(db, app):
    items = rows(db, """SELECT r.code, r.title, r.review_date FROM tdr_supplier_risks r
        WHERE r.status IN ('open','in_treatment') AND (r.review_date < ? OR NOT EXISTS
        (SELECT 1 FROM tdr_risk_assessments a WHERE a.risk_id=r.id)) ORDER BY r.code""", (_today(),))
    checked = one(db, "SELECT COUNT(*) AS n FROM tdr_supplier_risks WHERE status IN ('open','in_treatment')")["n"]
    return checked, items, "Açık riskler değerlendirilmiş ve gözden geçirme tarihi geçmemiş"


def _rule_contracts(db, app):
    horizon = (date.today() + timedelta(days=90)).isoformat()
    items = rows(db, """SELECT c.code, c.title, c.end_date FROM tdr_contracts c
        LEFT JOIN tdr_engagements e ON e.id=c.engagement_id JOIN tdr_suppliers s ON s.id=c.supplier_id
        WHERE c.status='active' AND c.end_date BETWEEN ? AND ?
        AND COALESCE(e.business_owner, s.owner, '')='' ORDER BY c.end_date""", (_today(), horizon))
    checked = one(db, "SELECT COUNT(*) AS n FROM tdr_contracts WHERE status='active' AND end_date BETWEEN ? AND ?",
                  (_today(), horizon))["n"]
    return checked, items, "90 gün içinde biten sözleşmelerin sorumlusu belli"


def _rule_sla(db, app):
    items = []
    definitions = rows(db, "SELECT d.id, d.code, d.name, e.code AS engagement FROM tdr_sla_definitions d "
                           "JOIN tdr_engagements e ON e.id=d.engagement_id WHERE d.active=1 ORDER BY d.id")
    for d in definitions:
        last = rows(db, "SELECT met FROM tdr_sla_measurements WHERE sla_id=? ORDER BY period_start DESC LIMIT 2",
                    (d["id"],))
        if len(last) == 2 and not any(m["met"] for m in last):
            items.append({"code": f"{d['engagement']}/{d['code']}", "name": d["name"]})
    return len(definitions), items, "Hiçbir SLA art arda iki dönem hedefi kaçırmamış"


def _rule_surveys(db, app):
    months = int(policy(db, "survey.cadence_months", {}).get("critical", 12))
    limit = (datetime.now(timezone.utc) - timedelta(days=round(months * 30.44))).isoformat(timespec="seconds")
    items = rows(db, """SELECT s.code, s.name FROM tdr_suppliers s WHERE s.status='active' AND s.tier='critical'
        AND NOT EXISTS (SELECT 1 FROM tdr_survey_targets t JOIN tdr_survey_responses r ON r.target_id=t.id
        WHERE t.supplier_id=s.id AND r.status='submitted' AND r.submitted_at >= ?) ORDER BY s.code""", (limit,))
    checked = one(db, "SELECT COUNT(*) AS n FROM tdr_suppliers WHERE status='active' AND tier='critical'")["n"]
    return checked, items, f"Kritik tedarikçiler son {months} ayda ankete konu olmuş"


AUTOMATIONS = {
    "supplier.owner": {"label": "Aktif tedarikçilerin ilişki sahibi var", "module": "core", "fn": _rule_supplier_owner,
                       "description": "Sahibi olmayan aktif tedarikçi varsa başarısız."},
    "supplier.reviews": {"label": "Kritik tedarikçi değerlendirmeleri zamanında", "module": "performance",
                         "fn": _rule_reviews,
                         "description": "Politikadaki sıklıkta değerlendirilmemiş kritik tedarikçi varsa başarısız."},
    "supplier.risk_reviews": {"label": "Açık riskler değerlendirilmiş ve güncel", "module": "risks",
                              "fn": _rule_risk_reviews,
                              "description": "Değerlendirmesi olmayan veya gözden geçirme tarihi geçmiş açık risk varsa "
                                             "başarısız."},
    "supplier.contracts": {"label": "Biten sözleşmelerin sorumlusu belli", "module": "core", "fn": _rule_contracts,
                           "description": "90 gün içinde biten ve iş sahibi/ilişki sahibi olmayan sözleşme varsa "
                                          "başarısız."},
    "supplier.sla": {"label": "SLA hedefleri art arda kaçırılmıyor", "module": "performance", "fn": _rule_sla,
                     "description": "Son iki dönemi hedefi tutmayan SLA varsa başarısız."},
    "supplier.surveys": {"label": "Kritik tedarikçiler periyodik ankete konu", "module": "surveys",
                         "fn": _rule_surveys,
                         "description": "Politikadaki sıklıkta anket yanıtı olmayan kritik tedarikçi varsa başarısız."},
}


def run_automation(db, app, control, principal, audit_id=None):
    rule = AUTOMATIONS[control["automation"]]
    started = utcnow()
    if not app.enabled(rule["module"]):
        provenance = {"rule": control["automation"], "rule_version": 1, "collection_status": "error",
                      "error": f"{rule['module']} modülü kapalı", "started_at": started}
        return record_execution(db, principal, {"control_id": control["id"], "status": "inconclusive",
                                                "audit_id": audit_id, "provenance": provenance,
                                                "details": "Veri kaynağı modülü kapalı; sonuç belirsiz."},
                                source="system")
    checked, items, statement = rule["fn"](db, app)
    body = json.dumps(items, ensure_ascii=False, sort_keys=True, default=str)
    provenance = {"rule": control["automation"], "rule_version": 1, "collection_status": "complete",
                  "query": f"tedarik:{control['automation']}", "checked": checked, "exceptions": len(items),
                  "result_sha256": hashlib.sha256(body.encode()).hexdigest(), "items": items[:50],
                  "started_at": started, "finished_at": utcnow()}
    if items:
        listed = ", ".join(str(i.get("code")) for i in items[:10]) + (" …" if len(items) > 10 else "")
        details = f"{statement}: {checked} kayıttan {len(items)} istisna ({listed})."
    else:
        details = f"{statement}: {checked} kayıt denetlendi, istisna yok."
    return record_execution(db, principal, {
        "control_id": control["id"], "audit_id": audit_id, "status": "fail" if items else "pass",
        "details": details, "provenance": provenance, "sample_size": checked, "exceptions": len(items)},
        source="system")


def run_control(c):
    authz.require_human(c.principal)
    authz.check(c.principal, EXECUTIONS, "write")
    control = crud.get(c.db, CONTROLS, c.params["id"])
    if not control["automation"]:
        raise crud.Invalid("Bu kontrolün iç otomatik kuralı yok; sonucu elle veya MCP ile kaydedin")
    if not control["active"]:
        raise crud.Invalid("Pasif kontrol çalıştırılamaz")
    audit_id = c.body.get("audit_id")
    return 201, run_automation(c.db, c.app, control, c.principal, audit_id)


def run_all(db, app, principal):
    results = []
    for control in rows(db, "SELECT * FROM tdr_controls WHERE active=1 AND automation IS NOT NULL ORDER BY code"):
        results.append({"code": control["code"], **run_automation(db, app, control, principal)})
    return results


def run_all_route(c):
    authz.require_human(c.principal)
    authz.check(c.principal, EXECUTIONS, "write")
    return {"results": run_all(c.db, c.app, c.principal)}


# ------------------------------------------------------------------ kanıt dosyaları

def store_file(db, evidence_id, filename, binary, username, uploaded_at=None):
    files.valid_file(filename, binary)
    db.lock(f"evidence:{evidence_id}")
    row = one(db, "SELECT COALESCE(MAX(version), 0) AS v FROM tdr_evidence_files WHERE evidence_id=?", (evidence_id,))
    version = row["v"] + 1
    digest = hashlib.sha256(binary).hexdigest()
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_id = db.execute("INSERT INTO tdr_evidence_files (evidence_id, version, file_name, file_size, mime_type, "
                         "sha256, uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
                         (evidence_id, version, filename, len(binary), mime, digest, username,
                          uploaded_at or utcnow())).lastrowid
    db.execute("INSERT INTO tdr_evidence_blobs (file_id, content) VALUES (?,?)", (file_id, binary))
    db.execute("UPDATE tdr_evidence SET file_name=?, file_size=?, mime_type=?, hash_sha256=?, current_version=?, "
               "updated_at=? WHERE id=?", (filename, len(binary), mime, digest, version, utcnow(), evidence_id))
    return {"evidence_id": evidence_id, "version": version, "size": len(binary), "sha256": digest,
            "file_name": filename}


def _evidence_links(db, evidence_id, body, replace):
    for key, (table, col, target) in EVIDENCE_LINKS.items():
        if key not in body:
            continue
        ids = _ids(body[key], key)
        res = RESOURCES[target]
        if ids and len(rows(db, f"SELECT id FROM {res.table} WHERE id IN ({','.join('?' * len(ids))})", ids)) != len(ids):
            raise crud.Invalid(f"{res.label}: bulunamayan kayıt seçildi")
        if replace:
            db.execute(f"DELETE FROM tdr_{table} WHERE evidence_id=?", (evidence_id,))
        for target_id in ids:
            db.execute(f"INSERT INTO tdr_{table} (evidence_id, {col}) VALUES (?,?) ON CONFLICT DO NOTHING",
                       (evidence_id, target_id))


def upload_evidence(c):
    """Yeni kanıt + ilk dosya sürümü (KS GRC POST /api/evidence/upload)."""
    if c.principal.role != "MACHINE":      # MCP kanıt yükleyebilir (KS GRC), kaynak "mcp" olarak işaretlenir
        authz.check(c.principal, EVIDENCE, "write")
    body = dict(c.body)
    binary = files.decode(body)
    filename = body.pop("file_name", None) or "kanit.json"
    body.pop("content_base64", None)
    links = {k: body.pop(k) for k in list(body) if k in EVIDENCE_LINKS}
    guard_readonly(EVIDENCE, body)
    files.valid_file(filename, binary)
    evidence_id = crud.insert(c.db, EVIDENCE, body, c.principal)
    _evidence_links(c.db, evidence_id, links, replace=False)
    result = store_file(c.db, evidence_id, filename, binary, c.principal.username)
    audit.log(c.db, c.principal, "UPLOAD", EVIDENCE.name, evidence_id,
              {"version": result["version"], "sha256": result["sha256"], "file_name": filename})
    return 201, {"id": evidence_id, **result}


def _visible_evidence(c):
    evidence = crud.get(c.db, EVIDENCE, c.params["id"])
    if not evidence_visible(c.principal, evidence):
        raise crud.NotFound("Kanıt bulunamadı")
    return evidence


def add_version(c):
    evidence = _visible_evidence(c)
    if c.principal.role != "MACHINE":
        authz.check(c.principal, EVIDENCE, "write")
        crud.check_scope(c.db, EVIDENCE, c.principal, evidence)
    if evidence["status"] == "archived":
        raise crud.Conflict("Arşivlenmiş kanıta yeni sürüm eklenemez")
    filename = c.body.get("file_name") or evidence["file_name"] or "kanit.json"
    result = store_file(c.db, evidence["id"], filename, files.decode(c.body), c.principal.username)
    audit.log(c.db, c.principal, "UPLOAD", EVIDENCE.name, evidence["id"],
              {"version": result["version"], "sha256": result["sha256"], "file_name": filename})
    return 201, result


def download(c):
    authz.check(c.principal, EVIDENCE, "read")
    if c.principal.role == "MACHINE":
        raise crud.Forbidden("MCP anahtarı kanıt dosyası indiremez")
    _visible_evidence(c)
    file = one(c.db, "SELECT * FROM tdr_evidence_files WHERE evidence_id=? AND version=?",
               (c.params["id"], c.params["version"]))
    if not file:
        raise crud.NotFound("Kanıt dosyası bulunamadı")
    blob = one(c.db, "SELECT content FROM tdr_evidence_blobs WHERE file_id=?", (file["id"],))
    content = bytes(blob["content"]) if blob else b""
    if hashlib.sha256(content).hexdigest() != file["sha256"]:
        raise crud.Conflict("Kanıt dosyasının bütünlük doğrulaması başarısız")
    audit.log(c.db, c.principal, "DOWNLOAD", EVIDENCE.name, file["evidence_id"], {"version": file["version"]})
    return Raw(content, "application/octet-stream", file["file_name"])


def evidence_links_route(c):
    evidence = _visible_evidence(c)
    authz.check(c.principal, EVIDENCE, "write")
    crud.check_scope(c.db, EVIDENCE, c.principal, evidence)
    _evidence_links(c.db, evidence["id"], c.body, replace=True)
    audit.log(c.db, c.principal, "LINK", EVIDENCE.name, evidence["id"], c.body)
    return evidence_context_data(c.db, evidence["id"])


def evidence_context_data(db, evidence_id):
    item = crud.get(db, EVIDENCE, evidence_id)
    item["files"] = rows(db, "SELECT * FROM tdr_evidence_files WHERE evidence_id=? ORDER BY version DESC", (evidence_id,))
    for key, (table, col, target) in EVIDENCE_LINKS.items():
        res = RESOURCES[target]
        item[key] = rows(db, f"SELECT t.* FROM {res.table} t JOIN tdr_{table} m ON m.{col}=t.id WHERE m.evidence_id=? "
                             "ORDER BY t.id", (evidence_id,))
    item["executions"] = rows(db, """SELECT x.id, x.status, x.executed_at, x.audit_id, c.code AS control_code,
        v.version FROM tdr_execution_evidence v JOIN tdr_executions x ON x.id=v.execution_id
        JOIN tdr_controls c ON c.id=x.control_id WHERE v.evidence_id=? ORDER BY x.executed_at DESC""", (evidence_id,))
    item["expiring"] = bool(item["expires_at"] and str(item["expires_at"]) <= (
        date.today() + timedelta(days=int(policy(db, "grc.evidence_warning_days", 30)))).isoformat())
    return item


def evidence_context(c):
    authz.check(c.principal, EVIDENCE, "read")
    _visible_evidence(c)
    return evidence_context_data(c.db, c.params["id"])


# ------------------------------------------------------------------ denetimler

def _validate_audit(audit_row):
    if not isinstance(audit_row.get("name"), str) or not audit_row["name"].strip():
        raise crud.Invalid("Denetim adı gerekli")
    for key, label in (("planned_start", "Planlanan başlangıç"), ("planned_end", "Planlanan bitiş"),
                       ("actual_start", "Gerçekleşen başlangıç"), ("actual_end", "Gerçekleşen bitiş")):
        _date(audit_row.get(key), label)
    for start, end in (("planned_start", "planned_end"), ("actual_start", "actual_end")):
        if audit_row.get(start) and audit_row.get(end) and str(audit_row[end]) < str(audit_row[start]):
            raise crud.Invalid("Bitiş tarihi başlangıçtan önce olamaz")
    status = audit_row.get("status", "planned")
    if audit_row.get("actual_end") and not audit_row.get("actual_start"):
        raise crud.Invalid("Gerçekleşen bitiş için gerçekleşen başlangıç gerekli")
    if status == "planned" and audit_row.get("actual_start"):
        raise crud.Invalid("Planlanan denetimde gerçekleşen tarih bulunamaz")
    if status == "in_progress" and audit_row.get("actual_end"):
        raise crud.Invalid("Devam eden denetimde gerçekleşen bitiş bulunamaz")
    if status in ("in_progress", "completed", "closed") and not audit_row.get("actual_start"):
        raise crud.Invalid("Bu durum için gerçekleşen başlangıç gerekli")
    if status in ("completed", "closed"):
        if not audit_row.get("actual_end"):
            raise crud.Invalid("Tamamlanan denetimde gerçekleşen bitiş gerekli")
        if not (audit_row.get("conclusion") or "").strip() or not audit_row.get("opinion"):
            raise crud.Invalid("Tamamlanan denetimde sonuç yazısı ve genel görüş gerekli")
    if audit_row.get("kind") == "supplier" and not audit_row.get("supplier_id"):
        raise crud.Invalid("Tedarikçi denetiminde tedarikçi seçilmeli")


def audit_scope(db, audit_id):
    return ({r["standard_id"] for r in rows(db, "SELECT standard_id FROM tdr_audit_standards WHERE audit_id=?", (audit_id,))},
            {r["clause_id"] for r in rows(db, "SELECT clause_id FROM tdr_audit_clauses WHERE audit_id=?", (audit_id,))})


def _check_scope(db, audit_row, standards, clauses):
    if standards:
        found = rows(db, f"SELECT id FROM tdr_standards WHERE id IN ({','.join('?' * len(standards))})", sorted(standards))
        if len(found) != len(standards):
            raise crud.Invalid("Seçilen standart bulunamadı")
    members = {}
    if clauses:
        members = {r["id"]: r["standard_id"] for r in rows(
            db, f"SELECT id, standard_id FROM tdr_clauses WHERE id IN ({','.join('?' * len(clauses))})", sorted(clauses))}
    if set(members) != clauses or not set(members.values()) <= standards:
        raise crud.Invalid("Her madde seçilen standartlardan birine ait olmalı")
    if audit_row["status"] in ("in_progress", "completed", "closed"):
        if standards - set(members.values()):
            raise crud.Invalid("Her standart için en az bir kapsam maddesi seçin")
        if not standards and not (audit_row.get("scope") or "").strip():
            raise crud.Invalid("Standartsız denetimde iç kapsamı açıklayın")


def planned_controls(db, audit_id):
    """Dondurulmuş plan varsa o; yoksa kapsam maddelerine bugün eşli aktif kontroller (KS audit_planned_mappings)."""
    frozen = rows(db, "SELECT DISTINCT clause_id, control_id FROM tdr_audit_plan WHERE audit_id=?", (audit_id,))
    if frozen or one(db, "SELECT plan_captured_at FROM tdr_audits WHERE id=?", (audit_id,))["plan_captured_at"]:
        return frozen
    return rows(db, """SELECT DISTINCT ac.clause_id, cc.control_id FROM tdr_audit_clauses ac
        JOIN tdr_control_clauses cc ON cc.clause_id=ac.clause_id JOIN tdr_controls c ON c.id=cc.control_id AND c.active=1
        WHERE ac.audit_id=?""", (audit_id,))


def _save_audit(c, audit_id=None):
    authz.require_human(c.principal)
    authz.check(c.principal, AUDITS, "write")
    body = dict(c.body)
    guard_readonly(AUDITS, {k: v for k, v in body.items() if k != "expected_revision"})
    previous = crud.get(c.db, AUDITS, audit_id) if audit_id else None
    if previous:
        c.db.lock(f"audit:{audit_id}")
        previous = crud.get(c.db, AUDITS, audit_id)
    old_st, old_cl = audit_scope(c.db, audit_id) if previous else (set(), set())
    standards, clauses = old_st, old_cl
    scope_change = "standard_ids" in body or "clause_ids" in body
    if scope_change:
        if previous and not ("standard_ids" in body and "clause_ids" in body):
            raise crud.Invalid("Kapsam güncellemesinde standart ve madde listeleri birlikte gerekli")
        clauses = set(_ids(body.pop("clause_ids", []), "Maddeler"))
        if "standard_ids" in body:
            standards = set(_ids(body.pop("standard_ids"), "Standartlar"))
        else:
            standards = {r["standard_id"] for r in rows(
                c.db, f"SELECT DISTINCT standard_id FROM tdr_clauses WHERE id IN ({','.join('?' * len(clauses))})",
                sorted(clauses))} if clauses else set()
    process_ids = None
    if "process_ids" in body:
        process_ids = set(_ids(body.pop("process_ids"), "Süreçler"))
        if process_ids and len(rows(c.db, f"SELECT id FROM tdr_processes WHERE id IN ({','.join('?' * len(process_ids))})",
                                    sorted(process_ids))) != len(process_ids):
            raise crud.Invalid("Seçilen süreç bulunamadı")
    old_processes = {r["process_id"] for r in rows(c.db, "SELECT process_id FROM tdr_audit_processes WHERE audit_id=?",
                                                    (audit_id,))} if previous else set()
    revision = body.pop("expected_revision", None)
    if previous and (scope_change or revision is not None) and revision != previous["revision"]:
        raise crud.Conflict("Denetim değişmiş olabilir. Kaydı yenileyip tekrar deneyin.")
    unknown = set(body) - set(AUDITS.fields)
    if unknown:
        raise crud.Invalid("Geçersiz denetim alanları: " + ", ".join(sorted(unknown)))
    data = crud.clean(body)
    if not previous:
        data["code"] = crud.next_code(c.db, AUDITS)
    crud.validate(AUDITS, data, partial=bool(previous))
    merged = {"status": "planned", "kind": "internal", **(previous or {}), **data}
    if previous and previous["status"] in CLOSED_AUDIT:
        if merged["status"] != previous["status"] and (previous["status"], merged["status"]) != ("completed", "closed"):
            raise crud.Conflict("Sonuçlandırılmış denetim tekrar açılamaz")
        if (old_st, old_cl) != (standards, clauses) or merged.get("scope") != previous["scope"] or \
                (process_ids is not None and process_ids != old_processes):
            raise crud.Conflict("Sonuçlandırılmış denetimin kapsamı değiştirilemez")
    _validate_audit(merged)
    _check_scope(c.db, merged, standards, clauses)
    now = utcnow()
    if previous:
        data["updated_at"] = now
        sets = ", ".join(f"{k}=?" for k in data)
        c.db.execute(f"UPDATE tdr_audits SET {sets}{', ' if sets else ''}revision=revision+1 WHERE id=?",
                     (*data.values(), audit_id))
    else:
        data["created_at"] = now
        audit_id = c.db.execute(f"INSERT INTO tdr_audits ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                                tuple(data.values())).lastrowid
    if (standards, clauses) != (old_st, old_cl):
        c.db.execute("DELETE FROM tdr_audit_clauses WHERE audit_id=?", (audit_id,))
        c.db.execute("DELETE FROM tdr_audit_standards WHERE audit_id=?", (audit_id,))
        for sid in sorted(standards):
            c.db.execute("INSERT INTO tdr_audit_standards (audit_id, standard_id) VALUES (?,?)", (audit_id, sid))
        for cid in sorted(clauses):
            c.db.execute("INSERT INTO tdr_audit_clauses (audit_id, clause_id) VALUES (?,?)", (audit_id, cid))
    if process_ids is not None and process_ids != old_processes:
        c.db.execute("DELETE FROM tdr_audit_processes WHERE audit_id=?", (audit_id,))
        for pid in sorted(process_ids):
            c.db.execute("INSERT INTO tdr_audit_processes (audit_id, process_id) VALUES (?,?)", (audit_id, pid))
    if merged["status"] in CLOSED_AUDIT and (not previous or previous["status"] not in CLOSED_AUDIT):
        for link in planned_controls(c.db, audit_id):
            c.db.execute("INSERT INTO tdr_audit_plan (audit_id, clause_id, control_id) VALUES (?,?,?)",
                         (audit_id, link["clause_id"], link["control_id"]))
        c.db.execute("UPDATE tdr_audits SET plan_captured_at=? WHERE id=?", (now, audit_id))
    audit.log(c.db, c.principal, "UPDATE" if previous else "CREATE", AUDITS.name, audit_id,
              {**{k: v for k, v in data.items() if k not in ("created_at", "updated_at")},
               "standards_added": sorted(standards - old_st), "standards_removed": sorted(old_st - standards),
               "clauses_added": sorted(clauses - old_cl), "clauses_removed": sorted(old_cl - clauses),
               "processes": sorted(process_ids) if process_ids is not None else None})
    return audit_context_data(c.db, audit_id, c.principal)


def create_audit(c):
    return 201, _save_audit(c)


def update_audit(c):
    return _save_audit(c, c.params["id"])


def audit_context_data(db, audit_id, principal=None):
    item = crud.get(db, AUDITS, audit_id)
    standards, clauses = audit_scope(db, audit_id)
    item["standards"] = rows(db, "SELECT s.* FROM tdr_standards s JOIN tdr_audit_standards a ON a.standard_id=s.id "
                                 "WHERE a.audit_id=? ORDER BY s.code", (audit_id,))
    item["clauses"] = rows(db, "SELECT c.id, c.code, c.title, c.standard_id FROM tdr_clauses c JOIN tdr_audit_clauses a "
                               "ON a.clause_id=c.id WHERE a.audit_id=? ORDER BY c.standard_id, c.code", (audit_id,))
    item["processes"] = rows(db, "SELECT p.id, p.code, p.name, p.process_type FROM tdr_processes p JOIN tdr_audit_processes a "
                                 "ON a.process_id=p.id WHERE a.audit_id=? ORDER BY p.code", (audit_id,))
    plan = planned_controls(db, audit_id)
    planned_ids = sorted({p["control_id"] for p in plan})
    tested = {r["control_id"] for r in rows(db, "SELECT DISTINCT control_id FROM tdr_executions WHERE audit_id=?",
                                            (audit_id,))}
    ids = sorted(set(planned_ids) | tested)
    controls = rows(db, f"SELECT * FROM tdr_controls WHERE id IN ({','.join('?' * len(ids))}) ORDER BY code", ids) if ids else []
    clause_codes = {}
    for p in plan:
        clause_codes.setdefault(p["control_id"], []).append(p["clause_id"])
    counts = {r: 0 for r in RESULTS}
    counts["untested"] = 0
    for control in controls:
        last = latest_execution(db, control["id"], audit_id)
        control["result"] = last["status"] if last else "untested"
        control["result_at"] = last["executed_at"] if last else None
        control["execution_id"] = last["id"] if last else None
        control["planned"] = control["id"] in planned_ids
        control["clause_ids"] = clause_codes.get(control["id"], [])
        if control["planned"]:
            counts[control["result"]] += 1
    item["controls"] = controls
    item["counts"] = counts
    planned_n = len(planned_ids)
    completed = counts["pass"] + counts["fail"]
    item["progress"] = {"planned": planned_n, "completed": completed,
                        "completion_pct": round(100 * completed / planned_n, 1) if planned_n else None,
                        "pass_pct": round(100 * counts["pass"] / completed, 1) if completed else None}
    item["findings"] = rows(db, """SELECT f.*, c.code AS control_code FROM tdr_findings f
        LEFT JOIN tdr_controls c ON c.id=f.control_id WHERE f.audit_id=? ORDER BY f.id DESC""", (audit_id,))
    scope_ids = ids or [0]
    item["other_open_findings"] = rows(db, f"""SELECT f.*, c.code AS control_code FROM tdr_findings f
        LEFT JOIN tdr_controls c ON c.id=f.control_id WHERE COALESCE(f.audit_id,0)<>? AND f.status IN ('open','in_progress')
        AND f.control_id IN ({','.join('?' * len(scope_ids))}) ORDER BY f.id DESC""", (audit_id, *scope_ids))
    visible, args = evidence_filter(principal, "e")
    item["evidence"] = rows(db, "SELECT e.* FROM tdr_evidence e JOIN tdr_evidence_audits m ON m.evidence_id=e.id "
                                f"WHERE m.audit_id=? AND {visible} ORDER BY e.id DESC", (audit_id, *args))
    return item


def audit_context(c):
    authz.check(c.principal, AUDITS, "read")
    return audit_context_data(c.db, c.params["id"], c.principal)


def finding_context(c):
    authz.check(c.principal, FINDINGS, "read")
    finding = crud.get(c.db, FINDINGS, c.params["id"])
    finding["actions"] = rows(c.db, "SELECT * FROM tdr_grc_actions WHERE finding_id=? ORDER BY due_date", (finding["id"],))
    finding["control"] = one(c.db, "SELECT id, code, name, owner FROM tdr_controls WHERE id=?", (finding["control_id"],)) \
        if finding["control_id"] else None
    if finding["execution_id"]:
        execution = crud.get(c.db, EXECUTIONS, finding["execution_id"])
        execution["provenance"] = json.loads(execution.pop("provenance_json"))
        execution.pop("definition_json")
        finding["execution"] = execution
    else:
        finding["execution"] = None
    finding["clause"] = one(c.db, """SELECT cl.id, cl.code, cl.title, s.code AS standard_code, s.version AS standard_version
        FROM tdr_clauses cl JOIN tdr_standards s ON s.id=cl.standard_id WHERE cl.id=?""", (finding["clause_id"],)) \
        if finding["clause_id"] else None
    from .grc_library import finding_impact_data
    finding["impact"] = finding_impact_data(c.db, finding)
    return finding


# ------------------------------------------------------------------ uyum göstergesi ve pano

def compliance_data(db, standard=None, process=None, audit_id=None):
    params = []
    where = []
    if process:
        where.append("EXISTS (SELECT 1 FROM tdr_control_processes p WHERE p.control_id=c.id AND p.process_id=?)")
        params.append(process)
    if audit_id:
        crud.get(db, AUDITS, audit_id)
        plan = planned_controls(db, audit_id)
        if standard:
            allowed = {r["id"] for r in rows(db, "SELECT id FROM tdr_clauses WHERE standard_id=?", (standard,))}
            plan = [p for p in plan if p["clause_id"] in allowed]
        ids = sorted({p["control_id"] for p in plan}) or [0]
        where.append(f"c.id IN ({','.join('?' * len(ids))})")
        params += ids
    else:
        where.append("c.active=1")
        if standard:
            where.append("EXISTS (SELECT 1 FROM tdr_control_clauses cc JOIN tdr_clauses cl ON cl.id=cc.clause_id "
                         "WHERE cc.control_id=c.id AND cl.standard_id=?)")
            params.append(standard)
    candidates = rows(db, "SELECT c.id, c.code, c.name, c.frequency, c.criticality, c.execution_mode, c.owner, c.active "
                          "FROM tdr_controls c WHERE " + " AND ".join(where) + " ORDER BY c.code", params)
    counts = {r: 0 for r in RESULTS}
    counts["untested"] = 0
    overdue = 0
    for control in candidates:
        last = latest_execution(db, control["id"], audit_id)
        status = last["status"] if last else "untested"
        counts[status] += 1
        control.update({"status": status, "executed_at": last["executed_at"] if last else None,
                        "execution_id": last["id"] if last else None, "audit_id": last["audit_id"] if last else None})
        control["test"] = test_state(control, last)
        overdue += control["test"]["state"] in ("overdue", "never")
    n = len(candidates)
    completed = counts["pass"] + counts["fail"]
    clause_count = mapped = None
    if audit_id or standard:
        clause_sql = "SELECT id FROM tdr_clauses cl WHERE applicable=1"
        clause_params = []
        if standard:
            clause_sql += " AND standard_id=?"
            clause_params.append(standard)
        if audit_id:
            clause_sql += " AND id IN (SELECT clause_id FROM tdr_audit_clauses WHERE audit_id=?)"
            clause_params.append(audit_id)
        clause_ids = [r["id"] for r in rows(db, clause_sql, clause_params)]
        clause_count = len(clause_ids)
        if audit_id:
            mapped_set = {p["clause_id"] for p in planned_controls(db, audit_id)}
        else:
            mapped_set = {r["clause_id"] for r in rows(db, "SELECT cc.clause_id FROM tdr_control_clauses cc JOIN "
                                                           "tdr_controls c ON c.id=cc.control_id WHERE c.active=1")}
        if process:
            in_process = {r["control_id"] for r in rows(db, "SELECT control_id FROM tdr_control_processes WHERE process_id=?",
                                                        (process,))}
            source = planned_controls(db, audit_id) if audit_id else rows(
                db, "SELECT cc.clause_id, cc.control_id FROM tdr_control_clauses cc JOIN tdr_controls c ON c.id=cc.control_id "
                    "WHERE c.active=1")
            mapped_set = {p["clause_id"] for p in source if p["control_id"] in in_process}
        mapped = len(set(clause_ids) & mapped_set)
    return {"filter": {"standard_id": standard, "process_id": process, "audit_id": audit_id},
            "total_controls": n, "completed": completed, "pending": n - completed,
            "completion_pct": round(100 * completed / n, 1) if n else None,
            "pass_pct": round(100 * counts["pass"] / completed, 1) if completed else None,
            "indicative_pct": round(100 * counts["pass"] / n, 1) if n else None,
            "counts": counts, "overdue_tests": overdue, "clause_count": clause_count, "mapped_clauses": mapped,
            "framework_coverage_pct": round(100 * mapped / clause_count, 1) if clause_count else None,
            "evaluation_type": "Denetim bazlı test" if audit_id else "Çapraz kapsam ön değerlendirmesi",
            "disclaimer": DISCLAIMER, "controls": candidates}


def _positive(query, name):
    value = query.get(name)
    if not value:
        return None
    if not value.isdigit() or int(value) <= 0:
        raise crud.Invalid("Filtre kimliği pozitif sayı olmalı")
    return int(value)


def compliance(c):
    authz.check(c.principal, CONTROLS, "read")
    return compliance_data(c.db, _positive(c.query, "standard_id"), _positive(c.query, "process_id"),
                           _positive(c.query, "audit_id"))


def overview(c):
    authz.check(c.principal, CONTROLS, "read")
    db = c.db
    today = _today()
    warn = (date.today() + timedelta(days=int(policy(db, "grc.evidence_warning_days", 30)))).isoformat()
    summary = compliance_data(db)
    findings = rows(db, "SELECT severity AS key, COUNT(*) AS count FROM tdr_findings WHERE status IN ('open','in_progress') "
                        "GROUP BY severity")
    standards = []
    for s in rows(db, "SELECT id, code, name, version FROM tdr_standards WHERE active=1 ORDER BY code"):
        data = compliance_data(db, standard=s["id"])
        standards.append({**s, "controls": data["total_controls"], "completion_pct": data["completion_pct"],
                          "pass_pct": data["pass_pct"], "framework_coverage_pct": data["framework_coverage_pct"],
                          "clause_count": data["clause_count"], "mapped_clauses": data["mapped_clauses"]})
    return {
        "controls": {k: summary[k] for k in ("total_controls", "completed", "completion_pct", "pass_pct",
                                              "indicative_pct", "counts", "overdue_tests")},
        "findings_open": sum(f["count"] for f in findings), "findings_by_severity": findings,
        "findings_overdue": one(db, "SELECT COUNT(*) AS n FROM tdr_findings WHERE status IN ('open','in_progress') "
                                    "AND due_date < ?", (today,))["n"],
        "actions_overdue": one(db, "SELECT COUNT(*) AS n FROM tdr_grc_actions WHERE status IN ('open','in_progress') "
                                   "AND due_date < ?", (today,))["n"],
        "actions_validation": one(db, "SELECT COUNT(*) AS n FROM tdr_grc_actions WHERE status='validation'")["n"],
        "evidence_expiring": one(db, "SELECT COUNT(*) AS n FROM tdr_evidence WHERE status='current' AND expires_at <= ?",
                                 (warn,))["n"],
        "documents_review_due": one(db, "SELECT COUNT(*) AS n FROM tdr_documents WHERE status='active' AND review_date <= ?",
                                    (today,))["n"],
        "audits_active": rows(db, "SELECT id, code, name, status, planned_end, kind FROM tdr_audits WHERE status IN "
                                  "('planned','in_progress') ORDER BY planned_start"),
        "standards": standards, "disclaimer": DISCLAIMER,
    }


# ------------------------------------------------------------------ kayıt

def register(app):
    from . import grc_archive, grc_library
    grc_library.register(app)
    app.route("GET", API + "/assurance/search", grc_archive.search)
    app.route("GET", API + "/audits/{id}/history", grc_archive.audit_history)
    app.route("GET", API + "/controls/{id}/context", control_context)
    app.route("POST", API + "/controls/{id}/links", set_links)
    app.route("POST", API + "/controls/{id}/run", run_control)
    app.route("POST", API + "/grc/run-automatic", run_all_route)
    app.route("GET", API + "/grc/automations", automations)
    app.route("POST", API + "/executions", create_execution)
    app.route("GET", API + "/executions/{id}/context", execution_context)
    app.route("POST", API + "/evidence/upload", upload_evidence, max_body=MAX_UPLOAD_BODY)
    app.route("POST", API + "/evidence/{id}/files", add_version, max_body=MAX_UPLOAD_BODY)
    app.route("GET", API + "/evidence/{id}/files/{version}", download)
    app.route("POST", API + "/evidence/{id}/links", evidence_links_route)
    app.route("GET", API + "/evidence/{id}/context", evidence_context)
    app.route("POST", API + "/audits", create_audit)
    app.route("PATCH", API + "/audits/{id}", update_audit)
    app.route("GET", API + "/audits/{id}/context", audit_context)
    app.route("GET", API + "/findings/{id}/context", finding_context)
    app.route("GET", API + "/grc/compliance", compliance)
    app.route("GET", API + "/grc/overview", overview)


DEFAULT_POLICIES = {
    "grc.evidence_warning_days": (30, "Kanıt geçerlilik sonu bu kadar gün içinde ise uyarı verilir."),
}


def seed(db):
    for code, (value, description) in DEFAULT_POLICIES.items():
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))
