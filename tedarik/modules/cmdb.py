"""CMDB: konfigürasyon öğeleri (CI), ilişkileri ve CI kaynaklı riskler. K-019.

Besleme
- Çekme: ServiceNow Table API (salt okur), `cmdb.servicenow` politikasındaki tablo ve alan eşlemesiyle; artımlı
  (filigran: son başarılı çalıştırmadaki en büyük `sys_updated_on`) veya tam. Tam senkronda görülmeyen ServiceNow
  CI'ı silinmez, "eski" (stale) işaretlenir.
- İtme: MCP uygulaması `POST /api/tdr/cmdb/cis/bulk` ile `sys_id` anahtarlı toplu yazar.
- Her senkron değiştirilemez bir çalıştırma kaydı bırakır (sayılar, hata özeti, filigran).
ServiceNow'dan gelen alanlar portalda değiştirilmez; yerel alanlar (şirket eşlemesi, tedarikçi, açıklama) düzenlenir.

CI risk kuralları (`cmdb.rules` politikası; varsayılan yalnızca üretim ortamı ve çalışır durumdaki CI'lar):
- os_eos: işletim sistemi destek bitişi geçmiş (veya uyarı süresi içinde)
- app_eos: uygulama / ürün destek bitişi geçmiş
- patch: kritik yama eksik veya son yama tarihinden bu yana gün sınırı aşılmış
- uptime: son yeniden başlatmadan bu yana gün sınırı aşılmış (ör. 100 gün)
Her (CI, kural) için bir maruziyet kaydı açılır veya kapanır. Açık maruziyetler şirket bazında tek bir kurumsal
riskte toplanır (kaynak "CMDB kuralı"); etkilenen CI'lar riske bağlanır. Risk puanı ilk açılışta en kritik etkilenen
CI'a göre önerilir; sonrasında değerlendirme risk sahibindedir (ISO 31000). Etkilenen CI kalmayan risk, sağlık
kontrolünde "kapatmayı değerlendirin" olarak görünür.
"""
import json
from datetime import date, datetime, timedelta, timezone

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API
from ..schema import RESOURCES, Resource, fk
from pathlib import Path
from urllib.parse import urlparse

from ..mcp_client import DEFAULT_SETTINGS as MCP_DEFAULTS
from ..servicenow import Client, ServiceNowError, display, value
from .core import policy

M = "cmdb"
REQUIRES = ("risks",)
CLASSES = ("business_app", "application", "server", "database", "network", "cloud", "other")
LOCAL_FIELDS = {"company_id", "supplier_id", "description"}
SYNCED = ("name", "ci_class", "sn_class", "environment", "operational_status", "business_criticality", "owner",
          "support_group", "os", "os_version", "version", "vendor", "os_eos_date", "eos_date", "last_patch_date",
          "missing_critical_patches", "last_boot_at", "ip_address", "fqdn", "location")

CIS = Resource("cmdb_cis", "Konfigürasyon Öğeleri", {
    "code": "TEXT NOT NULL UNIQUE", "name": "TEXT NOT NULL", "sys_id": "TEXT UNIQUE", "ci_class": "TEXT NOT NULL",
    "sn_class": "TEXT", "company_id": fk("companies", False), "environment": "TEXT",
    "operational_status": "TEXT NOT NULL DEFAULT 'operational'", "business_criticality": "TEXT",
    "owner": "TEXT", "support_group": "TEXT", "os": "TEXT", "os_version": "TEXT", "version": "TEXT", "vendor": "TEXT",
    "supplier_id": fk("suppliers", False), "os_eos_date": "DATE", "eos_date": "DATE", "last_patch_date": "DATE",
    "missing_critical_patches": "INTEGER", "last_boot_at": "TIMESTAMP", "ip_address": "TEXT", "fqdn": "TEXT",
    "location": "TEXT", "source": "TEXT NOT NULL DEFAULT 'manual'", "last_seen_at": "TIMESTAMP",
    "stale": "INTEGER NOT NULL DEFAULT 0", "description": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, write="admin", code_prefix="CI", machine="r", search=("code", "name", "fqdn", "ip_address", "sys_id"),
    readonly=("sys_id", "sn_class", "source", "last_seen_at", "stale"), indexes=(("ci_class", "environment"),),
    enums={"ci_class": CLASSES, "environment": ("production", "test", "development", "dr"),
           "operational_status": ("operational", "non_operational", "repair", "retired"),
           "business_criticality": ("critical", "high", "medium", "low"),
           "source": ("servicenow", "mcp", "manual")})

RELATIONS = Resource("cmdb_relations", "CI İlişkileri", {
    "parent_id": fk("cmdb_cis", cascade=True), "child_id": fk("cmdb_cis", cascade=True), "rel_type": "TEXT NOT NULL",
    "sys_id": "TEXT UNIQUE", "last_seen_at": "TIMESTAMP"},
    module=M, unique=(("parent_id", "child_id", "rel_type"),), api=("list",), search=("rel_type",), machine="r")

RUNS = Resource("cmdb_sync_runs", "CMDB Senkron Çalıştırmaları", {
    "started_at": "TIMESTAMP NOT NULL", "finished_at": "TIMESTAMP NOT NULL", "status": "TEXT NOT NULL",
    "mode": "TEXT NOT NULL", "source": "TEXT NOT NULL", "triggered_by": "TEXT NOT NULL",
    "created": "INTEGER NOT NULL DEFAULT 0", "updated": "INTEGER NOT NULL DEFAULT 0",
    "unchanged": "INTEGER NOT NULL DEFAULT 0", "stale_marked": "INTEGER NOT NULL DEFAULT 0",
    "relations": "INTEGER NOT NULL DEFAULT 0", "requests": "INTEGER NOT NULL DEFAULT 0",
    "watermark": "TEXT", "errors_json": "TEXT"},
    module=M, api=("list", "get"), search=(), immutable=True, read_roles={"ADMIN", "AUDITOR", "SUPPLIER_MANAGER"},
    enums={"status": ("success", "partial", "failed"), "mode": ("full", "delta", "push"),
           "source": ("servicenow", "mcp")})

EXPOSURES = Resource("ci_exposures", "CI Risk Maruziyetleri", {
    "ci_id": fk("cmdb_cis", cascade=True), "rule": "TEXT NOT NULL", "status": "TEXT NOT NULL DEFAULT 'open'",
    "detail": "TEXT", "detected_at": "TIMESTAMP NOT NULL", "resolved_at": "TIMESTAMP",
    "last_checked_at": "TIMESTAMP NOT NULL", "risk_id": fk("supplier_risks", False)},
    module=M, unique=(("ci_id", "rule"),), api=("list", "get"), search=("detail",), machine="r",
    enums={"rule": ("os_eos", "app_eos", "patch", "uptime"), "status": ("open", "resolved")})

RISK_CIS = Resource("risk_cis", "Riskten Etkilenen CI'lar", {
    "risk_id": fk("supplier_risks", cascade=True), "ci_id": fk("cmdb_cis", cascade=True),
    "link_source": "TEXT NOT NULL DEFAULT 'manual'"},
    module=M, unique=(("risk_id", "ci_id"),), api=("list",), search=(), machine="r",
    enums={"link_source": ("manual", "rule")})

DEFAULT_MAPPING = {
    "tables": [{"table": "cmdb_ci_business_app", "ci_class": "business_app"},
               {"table": "cmdb_ci_appl", "ci_class": "application"},
               {"table": "cmdb_ci_server", "ci_class": "server"},
               {"table": "cmdb_ci_db_instance", "ci_class": "database"}],
    "query": "install_status!=7",
    "fields": {"name": "name", "sn_class": "sys_class_name", "company": "company", "environment": "used_for",
               "operational_status": "operational_status", "business_criticality": "busines_criticality",
               "owner": "owned_by", "support_group": "support_group", "os": "os", "os_version": "os_version",
               "version": "version", "vendor": "manufacturer", "os_eos_date": "u_os_end_of_support",
               "eos_date": "u_end_of_support", "last_patch_date": "u_last_patch_date",
               "missing_critical_patches": "u_missing_critical_patches", "last_boot_at": "u_last_boot",
               "ip_address": "ip_address", "fqdn": "fqdn", "location": "location"},
    "values": {"operational_status": {"1": "operational", "2": "non_operational", "3": "repair", "6": "retired"},
               "business_criticality": {"1 - most critical": "critical", "2 - somewhat critical": "high",
                                        "3 - less critical": "medium", "4 - not critical": "low"},
               "environment": {"Production": "production", "Staging": "test", "QA": "test", "Test": "test",
                               "Development": "development", "Disaster recovery": "dr"}},
    "relations": {"table": "cmdb_rel_ci", "types": ["Depends on::Used by", "Runs on::Runs",
                                                    "Hosted on::Hosts"]},
    "page_size": 500,
}
DEFAULT_RULES = {
    "environments": ["production"],
    "os_eos": {"enabled": True, "classes": ["server"], "warning_days": 0, "likelihood": 4},
    "app_eos": {"enabled": True, "classes": ["business_app", "application", "database"], "warning_days": 0,
                "likelihood": 3},
    "patch": {"enabled": True, "classes": ["server", "database"], "max_days": 35, "likelihood": 4},
    "uptime": {"enabled": True, "classes": ["server"], "max_days": 100, "likelihood": 3},
    "risk_owner": "Bilgi Güvenliği",
}
RULE_TEXT = {
    "os_eos": ("İşletim sistemi destek süresi bitmiş sunucular", "technology",
               "Üretici desteği sona eren işletim sistemleri kullanımda olduğu için",
               "kritik bir güvenlik açığı yamalanamayabilir veya arıza üretici desteği olmadan çözülemeyebilir",
               "hizmet kesintisi, veri ihlali ve düzenleyici uyumsuzluk oluşabilir"),
    "app_eos": ("Destek süresi bitmiş uygulama ve ürünler", "technology",
                "Üretici desteği sona eren uygulama veya ürün sürümleri kullanımda olduğu için",
                "güvenlik ve uyumluluk güncellemeleri alınamayabilir",
                "iş sürekliliği ve bilgi güvenliği zarar görebilir"),
    "patch": ("Kritik yamaları geçilmemiş sistemler", "security",
              "Kritik güvenlik yamaları hedef sürede uygulanmadığı için",
              "bilinen bir açık istismar edilebilir", "veri ihlali veya hizmet kesintisi yaşanabilir"),
    "uptime": ("Uzun süredir yeniden başlatılmamış sunucular", "technology",
               "Sunucular uzun süredir yeniden başlatılmadığı için",
               "çekirdek ve bellek yamaları devreye girmemiş olabilir; plansız yeniden başlatmada sorun çıkabilir",
               "beklenmeyen kesinti ve uzun kurtarma süresi oluşabilir"),
}
IMPACT_BY_CRITICALITY = {"critical": 5, "high": 4, "medium": 3, "low": 2, None: 3}


def _ci_rules(db, data, current, principal):
    if current is not None and current["source"] in ("servicenow", "mcp"):
        locked = set(data) - LOCAL_FIELDS - {"updated_at"}
        if locked:
            raise crud.Conflict("Bu alanlar kaynak sistemden (ServiceNow / MCP) gelir; portalda değiştirilmez: "
                                + ", ".join(sorted(locked)))


CIS.before_save = _ci_rules


# ------------------------------------------------------------------ yazma (senkron ve itme ortak)

def _as_date(text):
    if not text:
        return None
    text = str(text).strip()[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _as_timestamp(text):
    if not text:
        return None
    text = str(text).strip().replace(" ", "T")
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)          # ServiceNow ham tarihleri UTC
    return stamp.astimezone(timezone.utc).isoformat(timespec="seconds")


def _normalize(item):
    """Gelen CI kaydını (MCP veya eşlenmiş ServiceNow) doğrular ve tipine çevirir."""
    out = {}
    for key in SYNCED:
        if key not in item or item[key] in (None, ""):
            continue
        raw = item[key]
        if key in ("os_eos_date", "eos_date", "last_patch_date"):
            raw = _as_date(raw)
        elif key == "last_boot_at":
            raw = _as_timestamp(raw)
        elif key == "missing_critical_patches":
            try:
                raw = max(0, int(float(raw)))
            except (TypeError, ValueError):
                raw = None
        elif key in CIS.enums and raw not in CIS.enums[key]:
            raw = None if key != "ci_class" else "other"
        else:
            raw = str(raw)[:500]
        if raw is not None:
            out[key] = raw
    if not out.get("name"):
        raise crud.Invalid("CI adı gerekli")
    out.setdefault("ci_class", "other")
    return out


def upsert_ci(db, sys_id, item, source, company_id, seen_at, counts):
    data = _normalize(item)
    current = one(db, "SELECT * FROM tdr_cmdb_cis WHERE sys_id=?", (sys_id,))
    data.update({"source": source, "last_seen_at": seen_at, "stale": 0})
    if company_id is not None:
        data["company_id"] = company_id
    if current is None:
        data["sys_id"] = sys_id
        data["code"] = crud.next_code(db, CIS)
        data["created_at"] = seen_at
        db.execute(f"INSERT INTO tdr_cmdb_cis ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                   tuple(data.values()))
        counts["created"] += 1
        return
    changed = {k: v for k, v in data.items() if k not in ("last_seen_at", "stale") and current.get(k) != v
               and str(current.get(k)) != str(v)}
    data["updated_at"] = seen_at if changed else current.get("updated_at")
    sets = ", ".join(f"{k}=?" for k in data)
    db.execute(f"UPDATE tdr_cmdb_cis SET {sets} WHERE id=?", (*data.values(), current["id"]))
    counts["updated" if changed else "unchanged"] += 1


def _company_lookup(db):
    lookup = {}
    for c in rows(db, "SELECT id, name, servicenow_ref FROM tdr_companies WHERE active=1"):
        for key in (c["servicenow_ref"], c["name"]):
            if key:
                lookup[str(key).strip().lower()] = c["id"]
    return lookup


def _relation(db, parent_sys, child_sys, rel_type, sys_id, seen_at):
    ids = {r["sys_id"]: r["id"] for r in rows(db, "SELECT id, sys_id FROM tdr_cmdb_cis WHERE sys_id IN (?,?)",
                                                (parent_sys, child_sys))}
    if parent_sys not in ids or child_sys not in ids:
        return False
    db.execute("""INSERT INTO tdr_cmdb_relations (parent_id, child_id, rel_type, sys_id, last_seen_at) VALUES (?,?,?,?,?)
        ON CONFLICT(parent_id, child_id, rel_type) DO UPDATE SET last_seen_at=excluded.last_seen_at""",
               (ids[parent_sys], ids[child_sys], rel_type[:120], sys_id, seen_at))
    return True


def _record_run(db, started, status, mode, source, who, counts, errors, watermark):
    run_id = db.execute(
        "INSERT INTO tdr_cmdb_sync_runs (started_at, finished_at, status, mode, source, triggered_by, created, updated, "
        "unchanged, stale_marked, relations, requests, watermark, errors_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (started, utcnow(), status, mode, source, who, counts["created"], counts["updated"], counts["unchanged"],
         counts["stale"], counts["relations"], counts["requests"], watermark,
         json.dumps(errors[:50], ensure_ascii=False) if errors else None)).lastrowid
    return run_id


# ------------------------------------------------------------------ ServiceNow senkronu

def servicenow_client(config):
    if not config.sn_instance:
        raise crud.Conflict("ServiceNow bağlantısı yapılandırılmadı (TEDARIK_SN_INSTANCE ve kimlik bilgisi dosyası)")
    try:
        password = getattr(config, "sn_password", None) or (
            Path(config.sn_password_file).read_text(encoding="utf-8").strip() if config.sn_password_file else None)
        token = getattr(config, "sn_token", None) or (
            Path(config.sn_token_file).read_text(encoding="utf-8").strip() if config.sn_token_file else None)
    except OSError:
        raise crud.Conflict("ServiceNow kimlik bilgisi dosyası okunamadı") from None
    return Client(config.sn_instance, user=config.sn_user, password=password, token=token, ca_file=config.sn_ca_file)


def _secret(path, label):
    try:
        return Path(path).read_text(encoding="utf-8").strip() if path else None
    except OSError:
        raise crud.Conflict(f"{label} dosyası okunamadı") from None


def mcp_client(config):
    """ServiceNow MCP sunucusu istemcisi (K-021). Sırlar yalnızca dosyadan ve yalnızca kullanılırken okunur."""
    from ..mcp_client import McpClient, McpError, OAuthClientCredentials
    if not config.sn_mcp_url:
        raise crud.Conflict("ServiceNow MCP bağlantısı yapılandırılmadı (TEDARIK_SN_MCP_URL)")
    try:
        provider = None
        if config.sn_mcp_token_url:
            secret = getattr(config, "sn_mcp_client_secret", None) or _secret(config.sn_mcp_client_secret_file,
                                                                             "MCP istemci sırrı")
            if not secret:
                raise crud.Conflict("MCP OAuth istemci sırrı boş")
            provider = OAuthClientCredentials(config.sn_mcp_token_url, config.sn_mcp_client_id, secret, config.sn_mcp_scope)
        token = (getattr(config, "sn_mcp_token", None) or _secret(config.sn_mcp_token_file, "MCP belirteci")) \
            if not provider else None
        return McpClient(config.sn_mcp_url, token=token, token_provider=provider, ca_file=config.sn_ca_file)
    except McpError as exc:
        raise crud.Conflict(str(exc)) from None


def mcp_settings(db):
    return {**MCP_DEFAULTS, **(policy(db, "cmdb.mcp", {}) or {})}


def sync_servicenow(db, app, principal, full=False, client=None, channel="servicenow"):
    """ServiceNow CMDB senkronu. channel: "servicenow" (Table API) veya "mcp" (ServiceNow MCP sunucusu aracı);
    iki kanalda da eşleme, artımlı senkron, eski kayıt işaretleme ve kurallar aynıdır."""
    mapping = policy(db, "cmdb.servicenow", DEFAULT_MAPPING)
    if client is None and channel == "mcp":
        from ..mcp_client import McpTableSource
        client = McpTableSource(mcp_client(effective(db, app)), mcp_settings(db))
    client = client or servicenow_client(effective(db, app))
    started = utcnow()
    db.lock("cmdb:sync")
    last = one(db, "SELECT watermark FROM tdr_cmdb_sync_runs WHERE source=? AND status='success' "
                   "AND watermark IS NOT NULL ORDER BY id DESC LIMIT 1", (channel,))
    watermark = None if full or not last else last["watermark"]
    mode = "delta" if watermark else "full"
    counts = {"created": 0, "updated": 0, "unchanged": 0, "stale": 0, "relations": 0, "requests": 0}
    errors, newest = [], watermark
    fields_map = mapping.get("fields", {})
    values_map = mapping.get("values", {})
    companies = _company_lookup(db)
    seen = set()
    for table in mapping.get("tables", []):
        wanted = ["sys_id", "sys_updated_on"] + list(fields_map.values())
        try:
            for record in client.table(table["table"], wanted, mapping.get("query", ""), watermark,
                                       int(mapping.get("page_size", 500))):
                sys_id = value(record, "sys_id")
                if not sys_id:
                    continue
                item = {"ci_class": table.get("ci_class", "other")}
                for ours, theirs in fields_map.items():
                    if ours == "company":
                        continue
                    if ours in ("owner", "support_group", "vendor", "location"):
                        item[ours] = display(record, theirs)
                    elif ours in values_map:
                        raw = value(record, theirs)
                        label = display(record, theirs)
                        item[ours] = values_map[ours].get(str(raw)) or values_map[ours].get(str(label))
                    else:
                        item[ours] = value(record, theirs)
                company = None
                if "company" in fields_map:
                    ref = value(record, fields_map["company"])
                    name = display(record, fields_map["company"])
                    company = companies.get(str(ref or "").lower()) or companies.get(str(name or "").lower())
                try:
                    with db.savepoint():
                        upsert_ci(db, sys_id, item, "servicenow", company, started, counts)
                    seen.add(sys_id)
                except (crud.Invalid, ValueError) as exc:
                    errors.append({"table": table["table"], "sys_id": sys_id, "error": str(exc)[:200]})
                updated = value(record, "sys_updated_on")
                if updated and (newest is None or updated > newest):
                    newest = updated
        except ServiceNowError as exc:
            errors.append({"table": table["table"], "error": str(exc)})
    relations = mapping.get("relations")
    if relations and not any("error" in e and "sys_id" not in e for e in errors):
        query = "type.nameIN" + ",".join(relations.get("types", [])) if relations.get("types") else ""
        try:
            for record in client.table(relations.get("table", "cmdb_rel_ci"), ["sys_id", "parent", "child", "type",
                                                                                "sys_updated_on"],
                                       query, watermark, int(mapping.get("page_size", 500))):
                if _relation(db, value(record, "parent"), value(record, "child"), display(record, "type") or "İlişki",
                             value(record, "sys_id"), started):
                    counts["relations"] += 1
        except ServiceNowError as exc:
            errors.append({"table": relations.get("table", "cmdb_rel_ci"), "error": str(exc)})
    table_failed = any("sys_id" not in e for e in errors)
    if mode == "full" and not table_failed:
        stale = [r["id"] for r in rows(db, "SELECT id, sys_id FROM tdr_cmdb_cis WHERE source='servicenow' AND stale=0")
                 if r["sys_id"] not in seen]
        for ci_id in stale:
            db.execute("UPDATE tdr_cmdb_cis SET stale=1 WHERE id=?", (ci_id,))
        counts["stale"] = len(stale)
    counts["requests"] = client.requests
    status = "failed" if table_failed and not seen else "partial" if errors else "success"
    run_id = _record_run(db, started, status, mode, channel, principal.username, counts, errors,
                         newest if status == "success" else watermark)
    audit.log(db, principal, "SYNC", RUNS.name, run_id, {k: counts[k] for k in ("created", "updated", "stale")})
    evaluation = evaluate_rules(db, principal)
    return {"run_id": run_id, "status": status, "mode": mode, **counts, "errors": errors[:10], "rules": evaluation}


def effective(db, app):
    """Ortam değişkeni (kurulum dosyası) veya Yönetim → Entegrasyonlar tanımı (K-024)."""
    from .integrations import servicenow_config
    return servicenow_config(db, app.config)


def default_channel(config):
    return "servicenow" if config.sn_instance else "mcp" if config.sn_mcp_url else None


def sync_route(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")
    channel = c.body.get("channel") or default_channel(effective(c.db, c.app))
    if channel not in ("servicenow", "mcp"):
        raise crud.Conflict("ServiceNow bağlantısı yapılandırılmadı (Table API veya MCP)")
    return {**sync_servicenow(c.db, c.app, c.principal, full=bool(c.body.get("full")), channel=channel), "channel": channel}


def mcp_test(c):
    """MCP bağlantı sınaması: oturum açar, sunucu bilgisini ve araçları listeler; yapılandırılan aracın varlığını ve
    sınama tablosundan tek kayıt alınıp alınamadığını denetler. Yalnızca Yönetici; veri yazmaz."""
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")
    from ..mcp_client import McpError, McpTableSource
    cfg = effective(c.db, c.app)
    client = mcp_client(cfg)
    settings = mcp_settings(c.db)
    out = {"url_host": urlparse(cfg.sn_mcp_url).netloc, "tool": settings["tool"], "steps": [], "tools": []}
    try:
        out["server"] = client.initialize()
        out["steps"].append({"step": "initialize", "ok": True, "detail": f"oturum açıldı, protokol {client.protocol}"})
        tools = client.list_tools()
        out["tools"] = [{"name": t["name"], "description": str(t.get("description") or "")[:300],
                         "parameters": sorted(((t.get("inputSchema") or {}).get("properties") or {}).keys())} for t in tools]
        found = any(t["name"] == settings["tool"] for t in tools)
        out["steps"].append({"step": "tools/list", "ok": found, "detail": f"{len(tools)} araç; yapılandırılan araç "
                             f"'{settings['tool']}' {'var' if found else 'yok (cmdb.mcp politikasında tool adını düzeltin)'}"})
        if found:
            table = str(c.body.get("table") or "cmdb_ci_server")[:80]
            source = McpTableSource(client, {**settings, "page_size": 1})
            sample = next(iter(source.table(table, ["sys_id", "name", "sys_updated_on"])), None)
            name = display(sample, "name") if isinstance(sample, dict) else None
            out["steps"].append({"step": "tools/call", "ok": True, "detail": f"{table}: " + (
                f"örnek kayıt alındı ({str(name)[:60]})" if sample else "araç çalıştı, kayıt dönmedi")})
    except (McpError, ServiceNowError) as exc:
        out["steps"].append({"step": "hata", "ok": False, "detail": str(exc)})
    finally:
        client.close()
    out["ok"] = len(out["steps"]) >= 3 and all(s["ok"] for s in out["steps"])
    audit.log(c.db, c.principal, "TEST", RUNS.name, None, {"mcp_host": out["url_host"], "ok": out["ok"]})
    return out


def push_route(c):
    """MCP itmesi (K-008 yolu): {"items": [{"sys_id", "name", "ci_class", ...}], "relations": [...]}."""
    if c.principal.role != "MACHINE":
        authz.require(c.principal, "admin")
    items, relations = c.body.get("items", []), c.body.get("relations", [])
    if not isinstance(items, list) or not isinstance(relations, list) or len(items) > 5000 or len(relations) > 20000:
        raise crud.Invalid("items (en çok 5000) ve relations (en çok 20000) liste olmalı")
    started = utcnow()
    db = c.db
    db.lock("cmdb:sync")
    counts = {"created": 0, "updated": 0, "unchanged": 0, "stale": 0, "relations": 0, "requests": 0}
    errors = []
    companies = _company_lookup(db)
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not isinstance(item.get("sys_id"), str) or not item["sys_id"].strip():
            errors.append({"index": index, "error": "sys_id gerekli"})
            continue
        company = companies.get(str(item.get("company") or "").strip().lower())
        try:
            with db.savepoint():
                upsert_ci(db, item["sys_id"].strip(), item, "mcp", company, started, counts)
        except (crud.Invalid, ValueError) as exc:
            errors.append({"index": index, "sys_id": item["sys_id"], "error": str(exc)[:200]})
    for rel in relations:
        if isinstance(rel, dict) and _relation(db, rel.get("parent"), rel.get("child"), str(rel.get("type") or "İlişki"),
                                               rel.get("sys_id"), started):
            counts["relations"] += 1
    status = "partial" if errors else "success"
    run_id = _record_run(db, started, status, "push", "mcp", c.principal.username, counts, errors, None)
    audit.log(db, c.principal, "SYNC", RUNS.name, run_id, {k: counts[k] for k in ("created", "updated")})
    evaluation = evaluate_rules(db, c.principal)
    return 201, {"run_id": run_id, "status": status, **counts, "errors": errors[:20], "rules": evaluation}


# ------------------------------------------------------------------ CI risk kuralları

def _hits(ci, rules, today):
    """CI'ın ihlal ettiği kurallar: {kural: açıklama}."""
    found = {}
    if ci["environment"] not in rules.get("environments", ["production"]) or ci["operational_status"] != "operational" \
            or ci["stale"]:
        return found
    for rule, field in (("os_eos", "os_eos_date"), ("app_eos", "eos_date")):
        cfg = rules.get(rule, {})
        if cfg.get("enabled") and ci["ci_class"] in cfg.get("classes", []) and ci[field]:
            end = date.fromisoformat(str(ci[field])[:10])
            if end <= today + timedelta(days=int(cfg.get("warning_days", 0))):
                what = f"{ci['os']} {ci['os_version'] or ''}".strip() if rule == "os_eos" else \
                    f"{ci['vendor'] or ''} {ci['version'] or ''}".strip() or ci["name"]
                found[rule] = f"{what}: destek bitişi {end.isoformat()}" + (" (geçti)" if end < today else " (yaklaşıyor)")
    cfg = rules.get("patch", {})
    if cfg.get("enabled") and ci["ci_class"] in cfg.get("classes", []):
        missing = ci["missing_critical_patches"] or 0
        age = (today - date.fromisoformat(str(ci["last_patch_date"])[:10])).days if ci["last_patch_date"] else None
        if missing > 0 or (age is not None and age > int(cfg.get("max_days", 35))):
            parts = [f"{missing} kritik yama eksik"] if missing else []
            if age is not None and age > int(cfg.get("max_days", 35)):
                parts.append(f"son yama {age} gün önce")
            found["patch"] = ", ".join(parts)
    cfg = rules.get("uptime", {})
    if cfg.get("enabled") and ci["ci_class"] in cfg.get("classes", []) and ci["last_boot_at"]:
        boot = datetime.fromisoformat(str(ci["last_boot_at"]).replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - boot).days
        if days > int(cfg.get("max_days", 100)):
            found["uptime"] = f"{days} gündür yeniden başlatılmadı"
    return found


def evaluate_rules(db, principal):
    """Tüm CI'ları kurallara göre değerlendirir; maruziyetleri ve şirket bazındaki kurumsal riskleri günceller."""
    rules = {**DEFAULT_RULES, **policy(db, "cmdb.rules", {})}
    today, now = date.today(), utcnow()
    risks_res = RESOURCES["supplier_risks"]
    opened = resolved = 0
    open_by_key = {}
    for ci in rows(db, "SELECT * FROM tdr_cmdb_cis"):
        hits = _hits(ci, rules, today)
        existing = {e["rule"]: e for e in rows(db, "SELECT * FROM tdr_ci_exposures WHERE ci_id=?", (ci["id"],))}
        for rule, detail in hits.items():
            row = existing.get(rule)
            if row is None:
                db.execute("INSERT INTO tdr_ci_exposures (ci_id, rule, status, detail, detected_at, last_checked_at) "
                           "VALUES (?,?,'open',?,?,?)", (ci["id"], rule, detail, now, now))
                opened += 1
            elif row["status"] == "resolved":
                db.execute("UPDATE tdr_ci_exposures SET status='open', detail=?, detected_at=?, resolved_at=NULL, "
                           "last_checked_at=? WHERE id=?", (detail, now, now, row["id"]))
                opened += 1
            else:
                db.execute("UPDATE tdr_ci_exposures SET detail=?, last_checked_at=? WHERE id=?", (detail, now, row["id"]))
            open_by_key.setdefault((rule, ci["company_id"]), []).append(ci)
        for rule, row in existing.items():
            if rule not in hits and row["status"] == "open":
                db.execute("UPDATE tdr_ci_exposures SET status='resolved', resolved_at=?, last_checked_at=? WHERE id=?",
                           (now, now, row["id"]))
                resolved += 1
    created = 0
    for (rule, company_id), cis in open_by_key.items():
        if company_id is None:
            continue                                   # şirketi eşlenmemiş CI risk açmaz; sağlık kontrolünde görünür
        ref = f"cmdb:{rule}:{company_id}"
        risk = one(db, "SELECT * FROM tdr_supplier_risks WHERE origin_ref=?", (ref,))
        if risk is None:
            title, category, cause, event, consequence = RULE_TEXT[rule]
            company = one(db, "SELECT name FROM tdr_companies WHERE id=?", (company_id,))
            impact = max(IMPACT_BY_CRITICALITY.get(ci["business_criticality"], 3) for ci in cis)
            risk_id = crud.insert(db, risks_res, {
                "title": f"{title} — {company['name']}"[:300], "category": category, "company_id": company_id,
                "owner": rules.get("risk_owner", "Bilgi Güvenliği"), "likelihood": int(rules.get(rule, {}).get(
                    "likelihood", 3)), "impact": impact, "cause": cause, "risk_event": event,
                "consequence": consequence, "origin_ref": ref, "impact_area": "operational",
                "entity_name": "CMDB konfigürasyon öğeleri (etkilenen CI listesi riske bağlı)",
                "review_date": (today + timedelta(days=30)).isoformat(),
                "description": "CMDB kuralıyla açıldı; etkilenen CI listesi CMDB senkronuyla güncellenir. Puanı risk "
                               "sahibi değerlendirir."})
            audit.log(db, principal, "CREATE", risks_res.name, risk_id, {"origin_ref": ref})
            risk = {"id": risk_id}
            created += 1
        ids = {ci["id"] for ci in cis}
        linked = {r["ci_id"] for r in rows(db, "SELECT ci_id FROM tdr_risk_cis WHERE risk_id=? AND link_source='rule'",
                                           (risk["id"],))}
        for ci_id in ids - linked:
            db.execute("INSERT INTO tdr_risk_cis (risk_id, ci_id, link_source) VALUES (?,?,'rule') ON CONFLICT DO NOTHING",
                       (risk["id"], ci_id))
        for ci_id in linked - ids:
            db.execute("DELETE FROM tdr_risk_cis WHERE risk_id=? AND ci_id=? AND link_source='rule'", (risk["id"], ci_id))
        db.execute(f"UPDATE tdr_ci_exposures SET risk_id=? WHERE rule=? AND status='open' AND ci_id IN "
                   f"({','.join('?' * len(ids))})", (risk["id"], rule, *ids))
    for risk in rows(db, "SELECT id, origin_ref FROM tdr_supplier_risks WHERE origin_ref LIKE 'cmdb:%'"):
        _, rule, company = risk["origin_ref"].split(":")
        if (rule, int(company)) not in open_by_key:
            db.execute("DELETE FROM tdr_risk_cis WHERE risk_id=? AND link_source='rule'", (risk["id"],))
    return {"opened": opened, "resolved": resolved, "risks_created": created,
            "open": one(db, "SELECT COUNT(*) AS n FROM tdr_ci_exposures WHERE status='open'")["n"]}


def evaluate_route(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")
    result = evaluate_rules(c.db, c.principal)
    audit.log(c.db, c.principal, "EVALUATE", EXPOSURES.name, None, result)
    return result


# ------------------------------------------------------------------ bağlam ve durum

def ci_context(c):
    authz.check(c.principal, CIS, "read")
    ci = crud.get(c.db, CIS, c.params["id"])
    ci["parents"] = rows(c.db, """SELECT r.rel_type, p.id, p.code, p.name, p.ci_class FROM tdr_cmdb_relations r
        JOIN tdr_cmdb_cis p ON p.id=r.parent_id WHERE r.child_id=? ORDER BY p.name""", (ci["id"],))
    ci["children"] = rows(c.db, """SELECT r.rel_type, ch.id, ch.code, ch.name, ch.ci_class FROM tdr_cmdb_relations r
        JOIN tdr_cmdb_cis ch ON ch.id=r.child_id WHERE r.parent_id=? ORDER BY ch.name""", (ci["id"],))
    ci["exposures"] = rows(c.db, "SELECT * FROM tdr_ci_exposures WHERE ci_id=? ORDER BY status, rule", (ci["id"],))
    ci["risks"] = rows(c.db, """SELECT r.id, r.code, r.title, r.status, r.risk_level, m.link_source
        FROM tdr_supplier_risks r JOIN tdr_risk_cis m ON m.risk_id=r.id WHERE m.ci_id=? ORDER BY r.code""", (ci["id"],))
    ci["bias"] = rows(c.db, """SELECT b.id, b.code, b.title, b.rto_hours, b.status FROM tdr_bias b
        JOIN tdr_bia_applications a ON a.bia_id=b.id WHERE a.ci_id=? ORDER BY b.code""", (ci["id"],)) \
        if c.app.enabled("continuity") else []
    return ci


def risk_links(c):
    """Riske elle CI bağlar (küme olarak). Kural bağlantıları korunur."""
    risks_res = RESOURCES["supplier_risks"]
    risk = crud.get(c.db, risks_res, c.params["id"])
    authz.check(c.principal, risks_res, "write")
    crud.check_scope(c.db, risks_res, c.principal, risk)
    ids = c.body.get("ci_ids")
    if not isinstance(ids, list) or any(type(i) is not int for i in ids) or len(ids) > 500:
        raise crud.Invalid("ci_ids tam sayı listesi olmalı (en çok 500)")
    if ids and len(rows(c.db, f"SELECT id FROM tdr_cmdb_cis WHERE id IN ({','.join('?' * len(ids))})", ids)) \
            != len(set(ids)):
        raise crud.Invalid("Bulunamayan CI seçildi")
    c.db.execute("DELETE FROM tdr_risk_cis WHERE risk_id=? AND link_source='manual'", (risk["id"],))
    for ci_id in sorted(set(ids)):
        c.db.execute("INSERT INTO tdr_risk_cis (risk_id, ci_id, link_source) VALUES (?,?,'manual') ON CONFLICT DO NOTHING",
                     (risk["id"], ci_id))
    audit.log(c.db, c.principal, "LINK", risks_res.name, risk["id"], {"ci_ids": sorted(set(ids))})
    return {"risk_id": risk["id"], "cis": risk_cis(c.db, risk["id"])}


def risk_cis(db, risk_id):
    return rows(db, """SELECT ci.id, ci.code, ci.name, ci.ci_class, ci.environment, ci.business_criticality, ci.os,
        ci.os_version, m.link_source FROM tdr_cmdb_cis ci JOIN tdr_risk_cis m ON m.ci_id=ci.id WHERE m.risk_id=?
        ORDER BY ci.name""", (risk_id,))


def status(c):
    authz.check(c.principal, CIS, "read")
    cfg = effective(c.db, c.app)
    return {
        "servicenow": {"configured": bool(cfg.sn_instance), "instance": cfg.sn_instance or None,
                       "auth": "token" if cfg.sn_token_file or getattr(cfg, "sn_token", None) else
                       "basic" if cfg.sn_user else None},
        "mcp": {"configured": bool(cfg.sn_mcp_url), "host": urlparse(cfg.sn_mcp_url).netloc or None,
                "auth": "oauth" if cfg.sn_mcp_token_url else "token" if cfg.sn_mcp_url else None,
                "tool": mcp_settings(c.db)["tool"]},
        "channel": default_channel(cfg),
        "counts": rows(c.db, "SELECT ci_class AS key, COUNT(*) AS count FROM tdr_cmdb_cis WHERE stale=0 GROUP BY ci_class"),
        "total": one(c.db, "SELECT COUNT(*) AS n FROM tdr_cmdb_cis WHERE stale=0")["n"],
        "stale": one(c.db, "SELECT COUNT(*) AS n FROM tdr_cmdb_cis WHERE stale=1")["n"],
        "unmapped_company": one(c.db, "SELECT COUNT(*) AS n FROM tdr_cmdb_cis WHERE company_id IS NULL AND stale=0")["n"],
        "exposures": rows(c.db, "SELECT rule AS key, COUNT(*) AS count FROM tdr_ci_exposures WHERE status='open' "
                                "GROUP BY rule"),
        "last_runs": rows(c.db, "SELECT * FROM tdr_cmdb_sync_runs ORDER BY id DESC LIMIT 10")
        if c.principal.role in RUNS.read_roles else [],
        "rules": {**DEFAULT_RULES, **policy(c.db, "cmdb.rules", {})},
    }


def register(app):
    app.route("GET", API + "/cmdb/status", status)
    app.route("POST", API + "/cmdb/sync", sync_route)
    app.route("POST", API + "/cmdb/mcp/test", mcp_test)
    app.route("POST", API + "/cmdb/cis/bulk", push_route, max_body=8 * 1024 * 1024)
    app.route("POST", API + "/cmdb/evaluate", evaluate_route)
    app.route("GET", API + "/cmdb_cis/{id}/context", ci_context)
    app.route("POST", API + "/supplier_risks/{id}/cis", risk_links)


DEFAULT_POLICIES = (
    ("cmdb.servicenow", DEFAULT_MAPPING, "ServiceNow CMDB tablo ve alan eşlemesi. u_ ile başlayan alanlar kurumunuzun "
                                         "özel alan adlarıyla değiştirilmelidir."),
    ("cmdb.rules", DEFAULT_RULES, "CI risk kuralları: ortamlar, sınıflar, gün sınırları, önerilen olasılık, risk sahibi"),
    ("cmdb.mcp", MCP_DEFAULTS, "ServiceNow MCP sunucusu (K-021): CMDB tablosu okuyan aracın adı (tool), argüman şablonu "
                       "({table}, {query}, {fields}, {fields_list}, {limit}, {offset}), kayıt yolu (records_path) ve sayfa "
                       "boyutu (page_size). Boşsa varsayılan: query_table aracı. CMDB Panosu'ndaki 'MCP bağlantısını sına' "
                       "sunucudaki araçları ve parametrelerini listeler."),
)


def seed(db):
    for code, value_, description in DEFAULT_POLICIES:
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value_, ensure_ascii=False), description))
