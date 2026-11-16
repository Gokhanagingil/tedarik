"""Rol ve yetki matrisi (Yönetim → Kullanıcılar → Rol ve yetki matrisi). K-035.

Matris elle tutulmaz; çalışan koddaki tanımlardan hesaplanır, bu yüzden her sürümde gerçeği gösterir:
- Kaynak başına okuma: `Resource.read_roles` (boşsa tüm roller okur).
- Kaynak başına yazma: `auth.can_write` — rol listesi (`write_roles`) varsa liste, yoksa seviye (`write`: write/manage/admin).
  Birim Kullanıcısı, kapsamı (`Resource.scope`) tanımlı kaynakta yalnızca kendi biriminin kaydını yazar.
- Yazma yolu: kayıt formu (otomatik oluşturma/güncelleme uç noktası) veya yalnızca iş akışı (onay, test sonucu gibi özel uç
  nokta); değiştirilemez kayıtlar ayrıca işaretlenir.
- Özel kimlikler: dış denetçi (salt okunur, yalnızca atanmış denetimler, süreli), MCP anahtarı (kaynağın `machine` izni),
  toplayıcı anahtarı (yalnızca /collector uç noktaları).
- Görevler ayrılığı kuralları kodda zorunludur; burada dayanaklarıyla listelenir.
Yalnızca Yönetici ve Denetçi görür (erişim tasarımının denetimi). Matris yetki vermez; asıl denetim her istekte sunucudadır.
"""
import csv
import io
from collections import Counter

from . import audit, auth as authz
from .crud import Forbidden
from .db import rows, utcnow
from .http import API, Raw
from .schema import RESOURCES

ROLE_INFO = {
    "ADMIN": "Tüm modüllerde okur ve yazar; kullanıcı, rol, entegrasyon, politika ve çerçeve kütüphanesini yönetir; bulgu riskini "
             "kabul eder.",
    "SUPPLIER_MANAGER": "Tedarikçi, sözleşme, risk, süreç, doküman, KVKK ve veri yönetişimi kayıtlarını yönetir (yönetim seviyesi); "
                        "denetim ve kontrol sonucu yazamaz.",
    "UNIT_USER": "Tüm kayıtları okur; yazma seviyesindeki kayıtları yalnızca kendi biriminin kapsamında açar ve günceller "
                 "(birim ataması Kullanıcılar ekranında).",
    "AUDITOR": "Tüm kayıtları okur; denetim, kontrol sonucu, bulgu ve kanıt kayıtlarını yazar; düzeltici faaliyetin etkinliğini "
               "doğrular. Diğer kayıtlarda salt okunur.",
    "VIEWER": "Salt okunur: kısıtlı kayıtlar (ör. KVKK başvuruları ve ihlalleri) dışında her şeyi görüntüler.",
}
LEVEL_INFO = {"write": "Yazma (Birim Kullanıcısı ve üstü)", "manage": "Yönetim (Tedarikçi Yöneticisi ve üstü)",
              "admin": "Yalnızca Yönetici"}
SPECIAL = [
    {"identity": "Dış denetçi", "role": "AUDITOR", "text": "Denetçi rolüyle açılır, ancak salt okunurdur: yalnızca atandığı "
     "denetimleri, bunların kanıt ve bulgularını görür; hesabın bitiş tarihi zorunludur, süresi geçince oturum açamaz (K-026)."},
    {"identity": "MCP anahtarı", "role": "MACHINE", "text": "Rol değildir. Yalnızca kaynakta açıkça izin verilen okuma/yazmayı "
     "yapar (matristeki MCP sütunu); kanıt dosyası indiremez, yalnızca otomatik kontrole sonuç yazabilir."},
    {"identity": "Toplayıcı anahtarı", "role": "COLLECTOR", "text": "Tek bir veri kaynağına bağlıdır; yalnızca katalog, kalite "
     "sonucu ve OpenLineage olayı gönderir (/api/tdr/collector). Hiçbir kaydı okuyamaz veya yazamaz (K-030)."},
]
SEGREGATION = [   # (modül, kural, dayanak)
    ("grc", "Bulgu riskini yalnızca Yönetici kabul eder.", "Bulgu durumu 'Risk kabul edildi'"),
    ("grc", "Düzeltici faaliyet sahibi kendi faaliyetinin etkinliğini doğrulayamaz; doğrulamayı Yönetici veya Denetçi yapar.",
     "ISO 9001 10.2, IIA 2500"),
    ("grc", "Denetim planını hazırlayan onaylayamaz.", "Dört göz"),
    ("grc", "Politika istisnasını talep eden veya istisna sahibi onaylayamaz.", "Dört göz"),
    ("risks", "Risk iştahı istisnasını değerlendirmeyi yapandan farklı bir yönetici onaylar.", "ISO 31000, COSO ERM"),
    ("risks", "Erişim gözden geçirmede kişi kendi erişimi hakkında karar veremez; kararı atanan gözden geçiren verir.",
     "ISO/IEC 27001 A.5.18"),
    ("documents", "Hazırlayan kendi dokümanını onaylayamaz; onaylayan atanmışsa yalnızca o kişi veya Yönetici onaylar.",
     "ISO 9001 7.5.2"),
    ("continuity", "BİA ve iş sürekliliği planını hazırlayan veya sahibi onaylayamaz.", "ISO 22301 8.2, 8.4"),
    ("datagov", "Sözlük terimini öneren onaylayamaz; onay terimin veya veri alanının sahibi ya da yöneticisindedir.", "DAMA-DMBOK"),
    ("datagov", "Veri talebini (erişim, maskeleme, veri çıkarma) talep eden onaylayamaz; onay veri sahibindedir.", "KVKK md. 12"),
    ("datagov", "Veri koruma etki değerlendirmesini (VKED) hazırlayan onaylayamaz.", "GDPR Art. 35"),
    ("datagov", "Toplayıcı anahtarı bir kez gösterilir; platformda yalnızca özeti saklanır.", "K-030"),
]
MODULE_LABELS = {
    "core": "Çekirdek", "performance": "Tedarikçi performansı", "surveys": "Anketler", "risks": "Kurumsal risk",
    "documents": "Doküman yönetimi", "grc": "Uyum ve denetim (GRC)", "cmdb": "CMDB", "continuity": "İş sürekliliği",
    "transfer": "Aktarım", "dashboard": "Panolar", "insights": "Analiz", "datagov": "Veri yönetişimi ve KVKK",
    "workflow": "İş akışı", "sourcing": "Kaynak bulma",
}
HIDDEN = {"idempotency", "evidence_blobs", "sequences"}
# Yalnızca sistemin yazdığı izler (kullanıcı eylemlerinin yan ürünü); hiçbir rol doğrudan yazmaz.
SYSTEM_RECORDS = {"audit_log", "cmdb_sync_runs", "import_rows", "catalog_imports", "catalog_changes", "collector_events",
                  "lineage_events", "dq_profiles", "dq_table_stats", "execution_evidence", "glossary_term_versions",
                  "document_revisions"}
ROLE_ORDER = ("ADMIN", "SUPPLIER_MANAGER", "UNIT_USER", "AUDITOR", "VIEWER")


def _allowed(principal):
    authz.require_human(principal)
    if principal.role not in ("ADMIN", "AUDITOR") or principal.external:
        raise Forbidden("Rol ve yetki matrisini yalnızca Yönetici ve Denetçi görüntüler")


def _write_path(res):
    if res.name in SYSTEM_RECORDS:
        return "system"
    if res.immutable:
        return "immutable"
    if "create" in res.api or "update" in res.api:
        return "form"
    return "workflow"


def cell(res, role):
    """Bir rolün kaynaktaki erişimi: read (bool) ve write: full | unit | append | none."""
    probe = authz.Principal("matris", role, "session")
    read = not res.read_roles or role in res.read_roles
    write = authz.can_write(probe, res) and res.name not in SYSTEM_RECORDS
    if not write:
        level = "none"
    elif res.immutable:
        level = "append"
    elif role == "UNIT_USER" and res.scope is not None:
        level = "unit"
    else:
        level = "full"
    return {"read": read, "write": level}


def resources(app):
    out = []
    for res in RESOURCES.values():
        if res.name in HIDDEN or not res.api or not app.enabled(res.module):
            continue
        out.append({"name": res.name, "label": res.label, "module": res.module,
                    "module_label": MODULE_LABELS.get(res.module, res.module),
                    "level": None if res.write_roles else res.write, "role_list": sorted(res.write_roles) if res.write_roles else None,
                    "path": _write_path(res), "unit_scoped": res.scope is not None,
                    "restricted_read": bool(res.read_roles), "machine": res.machine or "",
                    "roles": {r: cell(res, r) for r in ROLE_ORDER}})
    order = list(MODULE_LABELS)
    out.sort(key=lambda r: (order.index(r["module"]) if r["module"] in order else 99, r["label"]))
    return out


def _users(db, app):
    """Etkin kullanıcıların rolü: yerel modda rol tablosu, Entra modunda son oturumdaki uygulama rolü."""
    users = rows(db, "SELECT id, username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username")
    if app.config.auth_mode == "entra":
        latest = {}
        for r in rows(db, "SELECT user_id, app_role, created_at FROM auth_sessions ORDER BY created_at"):
            latest[r["user_id"]] = authz.ENTRA_ROLES.get(r["app_role"])
        roles = latest
    else:
        roles = {r["user_id"]: r["role"] for r in rows(db, "SELECT user_id, role FROM tdr_user_roles")}
    external = {r["user_id"] for r in rows(db, "SELECT user_id FROM tdr_user_access WHERE external=1")}
    units = Counter(r["user_id"] for r in rows(db, "SELECT user_id FROM tdr_user_units"))
    out = []
    for u in users:
        out.append({"username": u["username"], "display_name": u["display_name"] or u["username"], "role": roles.get(u["id"]),
                    "external": u["id"] in external, "units": units.get(u["id"], 0)})
    return out


def matrix(c):
    _allowed(c.principal)
    res = resources(c.app)
    users = _users(c.db, c.app)
    if c.query.get("format") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Modül", "Kaynak", "Yazma yolu", "Birim kapsamı", "MCP"] + [authz.ROLES[r] for r in ROLE_ORDER])
        path = {"form": "Kayıt formu", "workflow": "Yalnızca iş akışı", "immutable": "Değiştirilemez kayıt (yalnızca eklenir)",
                "system": "Sistem kaydı"}
        text = {"full": "Okur, yazar", "unit": "Okur, kendi birimine yazar", "append": "Okur, ekler (değiştiremez)", "none": "Okur"}
        for r in res:
            w.writerow([r["module_label"], r["label"], path[r["path"]], "Evet" if r["unit_scoped"] else "Hayır",
                        {"r": "Okur", "rw": "Okur, yazar"}.get(r["machine"], "Yok")] +
                       [text[r["roles"][k]["write"]] if r["roles"][k]["read"] else "Erişemez" for k in ROLE_ORDER])
        audit.log(c.db, c.principal, "EXPORT", "role_matrix", None, {"resources": len(res)})
        return 200, Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "rol-yetki-matrisi.csv")
    counts = Counter(u["role"] for u in users)
    roles = [{"code": r, "label": authz.ROLES[r], "level": authz.LEVELS[r], "description": ROLE_INFO[r],
              "entra_role": next((k for k, v in authz.ENTRA_ROLES.items() if v == r), None), "users": counts.get(r, 0),
              "external": sum(1 for u in users if u["role"] == r and u["external"]),
              "readable": sum(1 for x in res if x["roles"][r]["read"]),
              "writable": sum(1 for x in res if x["roles"][r]["write"] != "none")} for r in ROLE_ORDER]
    modules = [{"code": m, "label": MODULE_LABELS.get(m, m)} for m in dict.fromkeys(x["module"] for x in res)]
    return {"roles": roles, "resources": res, "modules": modules, "levels": LEVEL_INFO, "special": SPECIAL,
            "segregation": [{"module": m, "module_label": MODULE_LABELS.get(m, m), "rule": t, "basis": b}
                            for m, t, b in SEGREGATION if c.app.enabled(m)],
            "users": users, "unassigned": sum(1 for u in users if u["role"] not in authz.ROLES),
            "auth_mode": c.app.config.auth_mode, "generated_at": utcnow()}


def register(app):
    app.route("GET", API + "/roles/matrix", matrix)
