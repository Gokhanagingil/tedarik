"""Veri yönetişimi Faz 3 — otomatik toplama (K-030). `datagov` modülünün parçasıdır.

- Toplayıcı verinin bulunduğu ağda çalışan küçük bir programdır (`tedarik/collector.py`; platformdan tek dosya `.pyz`
  olarak indirilir, yalnızca Python standart kitaplığı gerekir). Kaynağa salt okunur hesapla bağlanır, yalnızca meta veriyi
  okur ve `tedarik.catalog.v1` sözleşmesiyle (veya hazır sorgunun CSV çıktısıyla) platforma iter. Platform kaynağa
  bağlanmaz; kaynağın parolası platformda tutulmaz.
- Kimlik: her toplayıcı tek bir kaynağa bağlıdır ve kendi anahtarını taşır (`X-Collector-Key`). Anahtar yalnızca bir kez
  gösterilir; platformda SHA-256 özeti saklanır. Yenilenebilir ve iptal edilebilir. Anahtar yalnızca /api/tdr/collector/
  uç noktalarını kullanabilir (http.py), başka hiçbir kaydı okuyamaz veya yazamaz.
- Merkezî ayar: kapsam ve örnek doğrulama satır sayısı platformda tutulur; toplayıcı çalışırken bunları platformdan okur.
- Zamanlama kurum tarafındadır (cron, systemd zamanlayıcı, Windows Görev Zamanlayıcı). Platform beklenen sıklığı bilir;
  geciken veya hata bildiren toplayıcıyı teknik sorumluya bildirir, sağlık kontrolünde ve İşlerim'de gösterir.
- Güvenlik eşiği: bir gönderim kaynağın etkin tablolarının eşikten fazlasını "kaldırıldı" yapacaksa reddedilir; yetkisi
  daraltılmış veya yanlış yapılandırılmış bir hesap kataloğu boşaltamaz.
- Değişiklik bildirimi: içe aktarım (dosya veya toplayıcı) şemayı değiştirdiğinde etkilenen tabloların devralınan veri
  sahibine ve veri yöneticisine, kaynağın veri yöneticisine ve teknik sorumlusuna bildirim gider. Kişisel veri, kritik veri,
  sözlük terimi bağı veya onaylı veri seti içeren nesnelerdeki kaldırma ve tip değişikliği "önemli" sayılır.
- Örnek doğrulama (isteğe bağlı): toplayıcı tablo başına sınırlı satırı yerelde okur, K-029 doğrulayıcılarını çalıştırır
  ve yalnızca sayıları gönderir; değerler ağdan çıkmaz.
"""
import hashlib
import io
import json
import secrets
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, MAX_UPLOAD_BODY, Raw
from ..labels import CHOICES
from ..schema import Resource, fk
from . import reminder
from .core import policy
from .datagov import EFF_COLS, EFFECTIVE, M, QUERIES, SCOPES, SOURCES, _notify, _payload, apply_structure, parse_catalog

SCHEDULES = {"hourly": 1, "daily": 24, "weekly": 168, "monthly": 24 * 31, "manual": None}
CONNECTORS = ("postgresql", "sqlite", "sql", "files", "file", "custom")
EVENT_KINDS = ("push", "preview", "error", "rejected")
KEY_PREFIX = "tdrc_"
MAX_SAMPLE_TABLES = 2000
DEFAULT_POLICIES = {
    "datagov.collector_max_removal_pct": (30, "Toplayıcı gönderiminde 'kaldırıldı' sayılabilecek en yüksek tablo oranı (%). "
                                              "Aşan gönderim reddedilir; toplayıcı kaydında ayrıca belirlenebilir."),
    "datagov.collector_overdue_factor": (1.5, "Toplayıcı, beklenen sıklığın bu katı kadar süre veri göndermezse gecikmiş sayılır."),
}

COLLECTORS = Resource("data_collectors", "Toplayıcılar", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "source_id": fk("data_sources"),
    "connector": "TEXT NOT NULL DEFAULT 'postgresql'", "scope": "TEXT NOT NULL DEFAULT 'schemas'",
    "schedule": "TEXT NOT NULL DEFAULT 'daily'", "max_removal_pct": "INTEGER", "sample_rows": "INTEGER NOT NULL DEFAULT 0",
    "description": "TEXT", "status": "TEXT NOT NULL DEFAULT 'active'", "key_hint": "TEXT", "key_created_at": "TIMESTAMP",
    "last_seen_at": "TIMESTAMP", "last_push_at": "TIMESTAMP", "last_result": "TEXT", "last_message": "TEXT",
    "client_version": "TEXT", "client_host": "TEXT", "overdue_notified_at": "TIMESTAMP", "revoked_at": "TIMESTAMP",
    "revoked_by": "TEXT", "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="TPL", write="manage", api=("list", "get", "update"), search=("code", "name", "client_host"),
    readonly=("source_id", "status", "key_hint", "key_created_at", "last_seen_at", "last_push_at", "last_result",
              "last_message", "client_version", "client_host", "overdue_notified_at", "revoked_at", "revoked_by",
              "created_by"),
    enums={"connector": CONNECTORS, "scope": SCOPES, "schedule": tuple(SCHEDULES), "status": ("active", "revoked"),
           "last_result": ("ok", "error", "rejected")})
Resource("collector_keys", "Toplayıcı anahtarları", {
    "collector_id": fk("data_collectors"), "key_hash": "TEXT NOT NULL UNIQUE", "created_by": "TEXT",
    "created_at": "TIMESTAMP NOT NULL"}, module=M, api=(), search=(), unique=(("collector_id",),))
EVENTS = Resource("collector_events", "Toplayıcı çalıştırmaları", {
    "collector_id": fk("data_collectors"), "kind": "TEXT NOT NULL", "message": "TEXT", "import_id": fk("catalog_imports", False),
    "counts_json": "TEXT", "connector": "TEXT", "client_version": "TEXT", "client_host": "TEXT",
    "created_at": "TIMESTAMP NOT NULL"},
    module=M, api=("list",), immutable=True, search=("message",), enums={"kind": EVENT_KINDS})


def _collector_rules(db, data, current, principal):
    if data.get("max_removal_pct") is not None and not 0 <= int(data["max_removal_pct"]) <= 100:
        raise crud.Invalid("Kaldırma eşiği 0 ile 100 arasında olmalı")
    if data.get("sample_rows") is not None and not 0 <= int(data["sample_rows"]) <= 10000:
        raise crud.Invalid("Örnek satır sayısı 0 ile 10.000 arasında olmalı")
    if current and current["status"] == "revoked":
        raise crud.Conflict("İptal edilmiş toplayıcı değiştirilemez; yeni toplayıcı ekleyin")


COLLECTORS.before_save = _collector_rules


# ------------------------------------------------------------------ anahtar ve kimlik

def _hash(key):
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _new_key(db, collector_id, principal):
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    now = utcnow()
    if one(db, "SELECT 1 AS x FROM tdr_collector_keys WHERE collector_id=?", (collector_id,)):
        db.execute("UPDATE tdr_collector_keys SET key_hash=?, created_by=?, created_at=? WHERE collector_id=?",
                   (_hash(key), principal.username, now, collector_id))
    else:
        db.execute("INSERT INTO tdr_collector_keys (collector_id, key_hash, created_by, created_at) VALUES (?,?,?,?)",
                   (collector_id, _hash(key), principal.username, now))
    db.execute("UPDATE tdr_data_collectors SET key_hint=?, key_created_at=?, updated_at=? WHERE id=?",
               (f"{key[:9]}…{key[-4:]}", now, now, collector_id))
    return key


def resolve_key(db, key):
    """Kimlik doğrulama (auth.py): etkin toplayıcının kaydı veya None. Anahtarın kendisi saklanmaz, özeti aranır."""
    if not key.startswith(KEY_PREFIX) or len(key) > 200:
        return None
    return one(db, """SELECT c.id, c.code, c.name, c.source_id FROM tdr_collector_keys k
        JOIN tdr_data_collectors c ON c.id=k.collector_id WHERE k.key_hash=? AND c.status='active'""", (_hash(key),))


def _machine(c):
    """Toplayıcı uç noktaları yalnızca toplayıcı anahtarıyla çağrılır."""
    if c.principal.auth_type != "collector" or not c.principal.collector_id:
        raise crud.Forbidden("Bu uç nokta toplayıcı anahtarı ister")
    col = one(c.db, "SELECT * FROM tdr_data_collectors WHERE id=?", (c.principal.collector_id,))
    if not col or col["status"] != "active":
        raise crud.Forbidden("Toplayıcı iptal edilmiş")
    return col


def _client(body):
    info = body.get("client") if isinstance(body.get("client"), dict) else {}
    return {k: str(info.get(k) or "")[:100] or None for k in ("version", "connector", "host")}


# ------------------------------------------------------------------ durum ve gecikme

def _ts(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def due_at(db, col):
    hours = SCHEDULES.get(col["schedule"])
    if not hours or col["status"] != "active":
        return None
    factor = float(policy(db, "datagov.collector_overdue_factor", 1.5) or 1.5)
    base = _ts(col["last_push_at"]) or _ts(col["key_created_at"]) or _ts(col["created_at"])
    return base + timedelta(hours=max(hours * factor, hours + 1)) if base else None


def state(db, col, now=None):
    """Toplayıcının görünen durumu: iptal, hata, gecikmiş, bekleniyor (hiç göndermedi), çalışıyor."""
    now = now or datetime.now(timezone.utc)
    due = due_at(db, col)
    out = {"due_at": due.isoformat(timespec="seconds") if due else None, "overdue": bool(due and due < now)}
    if col["status"] == "revoked":
        out.update(state="revoked", label="İptal edildi", tone="neutral")
    elif col["last_result"] in ("error", "rejected"):
        out.update(state="error", label="Hata" if col["last_result"] == "error" else "Gönderim reddedildi", tone="bad")
    elif out["overdue"]:
        out.update(state="overdue", label="Gecikti", tone="warn")
    elif not col["last_push_at"]:
        out.update(state="waiting", label="İlk gönderim bekleniyor", tone="neutral")
    else:
        out.update(state="ok", label="Çalışıyor", tone="good")
    return out


def _recipients(db, col):
    source = one(db, "SELECT steward, custodian, owner FROM tdr_data_sources WHERE id=?", (col["source_id"],)) or {}
    return [u for u in dict.fromkeys((source.get("custodian"), source.get("steward"), col["created_by"])) if u]


def _event(db, col, kind, message=None, client=None, import_id=None, counts=None):
    client = client or {}
    now = utcnow()
    db.execute("""INSERT INTO tdr_collector_events (collector_id, kind, message, import_id, counts_json, connector,
        client_version, client_host, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
               (col["id"], kind, (message or "")[:1000] or None, import_id,
                json.dumps(counts, ensure_ascii=False) if counts is not None else None, client.get("connector"),
                client.get("version"), client.get("host"), now))
    sets = {"last_seen_at": now, "client_version": client.get("version") or col["client_version"],
            "client_host": client.get("host") or col["client_host"]}
    if kind == "push":
        sets.update(last_push_at=now, last_result="ok", last_message=(message or "")[:500] or None, overdue_notified_at=None)
    elif kind in ("error", "rejected"):
        sets.update(last_result=kind, last_message=(message or "")[:500])
    db.execute(f"UPDATE tdr_data_collectors SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?",
               (*sets.values(), now, col["id"]))


def _alert(db, col, kind, message):
    title = "Toplayıcı hata bildirdi" if kind == "error" else "Toplayıcı gönderimi reddedildi"
    return _notify(db, "collector.failed", f"{title}: {col['code']} {col['name']}", message,
                   users=_recipients(db, col), link=f"#/collector/{col['id']}", object_type="data_collectors",
                   object_id=col["id"], dedupe=f"tpl-fail:{col['id']}:{kind}:{utcnow()[:10]}")


# ------------------------------------------------------------------ toplayıcı uç noktaları (makine)

def _removal_guard(db, col, source, catalog, scope):
    """Gönderim kaynağın etkin tablolarının eşikten fazlasını kaldıracaksa gerekçeli ileti döner."""
    if scope == "tables":
        return None
    limit = col["max_removal_pct"]
    limit = int(policy(db, "datagov.collector_max_removal_pct", 30) if limit is None else limit)
    if limit >= 100:
        return None
    active = rows(db, "SELECT schema_name, name FROM tdr_data_tables WHERE source_id=? AND status<>'removed'", (source["id"],))
    schemas = {k[0] for k in catalog.tables}
    in_scope = [t for t in active if scope == "full" or t["schema_name"].lower() in schemas]
    removed = [t for t in in_scope if (t["schema_name"].lower(), t["name"].lower()) not in catalog.tables]
    if len(active) < 10 or not removed:
        return None
    pct = round(100 * len(removed) / len(active))
    if pct <= limit:
        return None
    return (f"Gönderim, kaynağın {len(active)} etkin tablosundan {len(removed)} tanesini (%{pct}) kaldırılmış gösteriyor; "
            f"eşik %{limit}. Toplayıcı hesabının yetkisini ve kapsam ayarını denetleyin. Değişiklik gerçekse eşiği "
            "toplayıcı kaydından geçici olarak yükseltin.")


def _sample_stats(db, source, items, principal):
    from .privacy import apply_sample_stats
    if not isinstance(items, list):
        return None
    out = Counter()
    for item in items[:MAX_SAMPLE_TABLES]:
        if not isinstance(item, dict) or not isinstance(item.get("columns"), dict) or not item.get("table"):
            continue
        table = one(db, "SELECT * FROM tdr_data_tables WHERE source_id=? AND LOWER(schema_name)=? AND LOWER(name)=? "
                        "AND status<>'removed'", (source["id"], str(item.get("schema") or "").lower(),
                                                   str(item["table"]).lower()))
        if not table or not item["columns"]:
            continue
        try:
            with db.savepoint():
                result = apply_sample_stats(db, table, item["columns"], principal, item.get("sample_size"))
        except crud.Invalid:
            out["skipped"] += 1
            continue
        out["tables"] += 1
        out["new"] += result["new"]
        out["updated"] += result["updated"]
    return dict(out)


def collector_whoami(c):
    col = _machine(c)
    source = one(c.db, "SELECT id, code, name, platform, status FROM tdr_data_sources WHERE id=?", (col["source_id"],))
    c.db.execute("UPDATE tdr_data_collectors SET last_seen_at=? WHERE id=?", (utcnow(), col["id"]))
    return {"collector": {"code": col["code"], "name": col["name"], "connector": col["connector"], "scope": col["scope"],
                          "schedule": col["schedule"], "sample_rows": col["sample_rows"]},
            "source": source, "format": "tedarik.catalog.v1", "max_upload_bytes": MAX_UPLOAD_BODY,
            "queries": [{"key": q["key"], "title": q["title"], "text": q["text"]} for q in QUERIES.get(source["platform"], [])
                        if q["kind"] == "sql"],
            "server_time": utcnow()}


def collector_push(c):
    col = _machine(c)
    db, body = c.db, c.body
    source = crud.get(db, SOURCES, col["source_id"])
    client = _client(body)
    scope = body.get("scope") or col["scope"]
    dry_run = bool(body.get("dry_run"))
    if source["status"] != "active":
        raise crud.Conflict("Veri kaynağı kullanımdan kalkmış; gönderim kabul edilmez")
    try:
        if scope not in SCOPES:
            raise crud.Invalid("Kapsam tables, schemas veya full olmalı")
        filename, raw = _payload(c)
        catalog = parse_catalog(filename, raw, str(body.get("default_schema") or "").strip()[:128])
        if not catalog.tables:
            raise crud.Invalid("Gönderimde tablo yok; toplayıcı hesabının katalog okuma yetkisini denetleyin")
    except crud.Invalid as exc:
        _event(db, col, "error", f"Gönderim okunamadı: {exc}", client)
        _alert(db, col, "error", f"{source['name']} kaynağından gelen gönderim okunamadı: {exc}")
        return 400, {"error": str(exc)}
    guard = _removal_guard(db, col, source, catalog, scope)
    if guard:
        if not dry_run:
            _event(db, col, "rejected", guard, client)
            _alert(db, col, "rejected", f"{source['name']}: {guard}")
        return 409, {"error": guard, "rejected": True}
    summary = apply_structure(db, source, catalog, scope=scope, dry_run=dry_run, principal=c.principal,
                              filename=filename, collector_id=col["id"])
    if dry_run:
        _event(db, col, "preview", f"{len(catalog.tables)} tablo, {catalog.columns} kolon", client, counts=summary["counts"])
        return summary
    summary["sample"] = _sample_stats(db, source, body.get("sample_stats"), c.principal)
    _event(db, col, "push", f"{len(catalog.tables)} tablo, {catalog.columns} kolon", client, summary["import_id"],
           summary["counts"])
    audit.log(db, c.principal, "COLLECT", "data_sources", source["id"],
              {"collector": col["code"], "format": catalog.format, "scope": scope, "counts": summary["counts"],
               "sample": summary["sample"]})
    return summary


def collector_status(c):
    """Toplayıcı kendi tarafındaki hatayı bildirir (ör. kaynağa bağlanamadı); platform teknik sorumluya iletir."""
    col = _machine(c)
    result = c.body.get("result")
    if result not in ("ok", "error"):
        raise crud.Invalid("Sonuç ok veya error olmalı")
    message = str(c.body.get("message") or "").strip()[:1000]
    client = _client(c.body)
    if result == "error":
        _event(c.db, col, "error", message or "Toplayıcı hata bildirdi", client)
        _alert(c.db, col, "error", message or "Toplayıcı hata bildirdi; toplayıcının çalıştığı makinedeki çıktıyı inceleyin.")
    else:
        c.db.execute("UPDATE tdr_data_collectors SET last_seen_at=? WHERE id=?", (utcnow(), col["id"]))
    return {"ok": True}


# ------------------------------------------------------------------ yönetim uç noktaları (kullanıcı)

def _manage(c):
    authz.require_human(c.principal)
    authz.check(c.principal, COLLECTORS, "write")


def collector_create(c):
    _manage(c)
    source = crud.get(c.db, SOURCES, c.params["id"])
    if source["status"] != "active":
        raise crud.Conflict("Kullanımdan kalkmış kaynağa toplayıcı eklenemez")
    data = {k: c.body.get(k) for k in ("name", "connector", "scope", "schedule", "max_removal_pct", "sample_rows",
                                       "description") if c.body.get(k) not in (None, "")}
    data.setdefault("name", f"{source['name']} toplayıcısı")
    data.update(source_id=source["id"], created_by=c.principal.username, status="active")
    cid = crud.insert(c.db, COLLECTORS, data, c.principal)
    key = _new_key(c.db, cid, c.principal)
    audit.log(c.db, c.principal, "CREATE", "data_collectors", cid, {k: v for k, v in data.items() if k != "created_by"})
    return {"collector": crud.get(c.db, COLLECTORS, cid), "key": key}


def collector_rotate(c):
    _manage(c)
    col = crud.get(c.db, COLLECTORS, c.params["id"])
    if col["status"] != "active":
        raise crud.Conflict("İptal edilmiş toplayıcının anahtarı yenilenemez")
    key = _new_key(c.db, col["id"], c.principal)
    audit.log(c.db, c.principal, "ROTATE_KEY", "data_collectors", col["id"], {"key_hint": f"{key[:9]}…{key[-4:]}"})
    return {"collector": crud.get(c.db, COLLECTORS, col["id"]), "key": key}


def collector_revoke(c):
    _manage(c)
    col = crud.get(c.db, COLLECTORS, c.params["id"])
    if col["status"] != "active":
        raise crud.Conflict("Toplayıcı zaten iptal edilmiş")
    now = utcnow()
    c.db.execute("UPDATE tdr_data_collectors SET status='revoked', revoked_at=?, revoked_by=?, updated_at=? WHERE id=?",
                 (now, c.principal.username, now, col["id"]))
    c.db.execute("UPDATE tdr_collector_keys SET key_hash=? WHERE collector_id=?", ("revoked:" + secrets.token_hex(16), col["id"]))
    audit.log(c.db, c.principal, "REVOKE", "data_collectors", col["id"], {"reason": str(c.body.get("reason") or "")[:300]})
    return {"collector": crud.get(c.db, COLLECTORS, col["id"])}


CONFIG_SETTINGS = {
    "postgresql": {"dsn_env": "TEDARIK_SOURCE_DSN", "schemas": ["public"], "row_counts": True},
    "sqlite": {"path": "/veri/uygulama.db", "row_counts": True},
    "sql": {"driver": "hdbcli.dbapi", "connect_env": "TEDARIK_SOURCE_CONNECT", "preset": "hana_catalog",
            "replace": {"<ŞEMA_1>": "SATIS", "<ŞEMA_2>": "FINANS"}},
    "files": {"path": "/paylasim/veri", "pattern": "*.csv", "schema": "paylasim", "row_counts": True},
    "file": {},
    "custom": {"plugin": "kendi_baglayicim.py", "name": "kendi_baglayicim"},
}
CONNECTOR_NOTES = {
    "postgresql": "psycopg paketi toplayıcı makinesine kurulur (pip install 'psycopg[binary]'). Bağlantı adresi "
                  "TEDARIK_SOURCE_DSN ortam değişkeninde durur; hesap yalnızca katalog okuma yetkisiyle açılır.",
    "sqlite": "Ek paket gerekmez; dosya salt okunur açılır.",
    "sql": "Kaynağın Python sürücüsü toplayıcı makinesine kurulur (SAP HANA: hdbcli, SQL Server: pyodbc, Oracle: oracledb, "
           "MySQL: pymysql, Snowflake: snowflake-connector-python). Bağlantı bilgileri JSON olarak TEDARIK_SOURCE_CONNECT "
           "ortam değişkeninde durur. Sorgu, kaynağın 'Nasıl içe aktarılır' sekmesindeki hazır sorgudur (preset) veya "
           "query_file ile verilen dosyadır.",
    "files": "Klasördeki her CSV bir tablodur; başlık satırı kolonlardır, tipler yerelde örnekten çıkarılır.",
    "file": "Kaynak sistemin kendi zamanlanmış dışa aktarımını (CSV, Excel, JSON) olduğu gibi gönderir: "
            "'dosya-gonder' komutuyla kullanılır.",
    "custom": "Kurumun yazdığı bağlayıcı (Connector sınıfı) --eklenti ile yüklenir; sözleşme belgede (docs/TOPLAYICI.md).",
}
CRON = {"hourly": "0 * * * *", "daily": "30 2 * * *", "weekly": "30 2 * * 1", "monthly": "30 2 1 * *"}
SCHTASKS = {"hourly": "/sc hourly", "daily": "/sc daily /st 02:30", "weekly": "/sc weekly /d MON /st 02:30",
            "monthly": "/sc monthly /d 1 /st 02:30"}


def setup(col, origin):
    """Kurulum yönergesi: ayar dosyası, komutlar ve zamanlama satırları. Anahtar içermez."""
    connector = col["connector"]
    config = {"platform": origin or "https://<platform-adresi>", "key_file": "/etc/tedarik/anahtar",
              "connector": connector if connector not in ("file", "custom") else (
                  "file" if connector == "file" else CONFIG_SETTINGS["custom"]["name"]),
              "settings": {k: v for k, v in CONFIG_SETTINGS.get(connector, {}).items() if k not in ("plugin", "name")}}
    if connector == "custom":
        config["plugins"] = [CONFIG_SETTINGS["custom"]["plugin"]]
    if connector == "file":
        config.pop("settings")
    run = ("dosya-gonder --ayar /etc/tedarik/toplayici.json /disa-aktarim/katalog.csv" if connector == "file"
           else "gonder --ayar /etc/tedarik/toplayici.json")
    unix = f"python3 /opt/tedarik/tedarik-toplayici.pyz {run}"
    win_run = run.replace("/etc/tedarik/", "C:\\tedarik\\").replace("/disa-aktarim/", "C:\\disa-aktarim\\")
    win = f"py C:\\tedarik\\tedarik-toplayici.pyz {win_run}"
    out = {"config": json.dumps(config, ensure_ascii=False, indent=2), "note": CONNECTOR_NOTES.get(connector, ""),
           "check": "python3 /opt/tedarik/tedarik-toplayici.pyz dene --ayar /etc/tedarik/toplayici.json",
           "run": unix, "windows": win}
    if col["schedule"] in CRON:
        out["cron"] = f"{CRON[col['schedule']]}  {unix} >> /var/log/tedarik-toplayici.log 2>&1"
        out["schtasks"] = (f'schtasks /create /tn "Tedarik toplayıcı {col["code"]}" {SCHTASKS[col["schedule"]]} '
                           f'/tr "{win}" /ru SYSTEM')
    return out


def _origin(c):
    host = c.headers.get("Host") if c.headers else None
    if not host:
        return None
    return ("https" if c.app.config.cookie_secure else "http") + "://" + host


def collector_context(c):
    authz.check(c.principal, COLLECTORS, "read")
    col = crud.get(c.db, COLLECTORS, c.params["id"])
    col["source"] = one(c.db, "SELECT id, code, name, platform, steward, custodian FROM tdr_data_sources WHERE id=?",
                        (col["source_id"],))
    col["state"] = state(c.db, col)
    col["events"] = rows(c.db, "SELECT * FROM tdr_collector_events WHERE collector_id=? ORDER BY id DESC LIMIT 50", (col["id"],))
    for e in col["events"]:
        e["counts"] = json.loads(e.pop("counts_json") or "null")
    col["setup"] = setup(col, _origin(c))
    col["can_manage"] = authz.can_write(c.principal, COLLECTORS) and c.principal.auth_type not in ("api_key", "collector")
    col["removal_default"] = policy(c.db, "datagov.collector_max_removal_pct", 30)
    return col


def source_collectors(db, source_id):
    """Kaynak ekranı için toplayıcılar ve durumları."""
    out = rows(db, "SELECT * FROM tdr_data_collectors WHERE source_id=? ORDER BY status, id", (source_id,))
    for col in out:
        col["state"] = state(db, col)
    return out


def collectors_summary(db):
    items = rows(db, "SELECT * FROM tdr_data_collectors WHERE status='active'")
    states = Counter(state(db, col)["state"] for col in items)
    return {"active": len(items), "ok": states["ok"], "overdue": states["overdue"], "error": states["error"],
            "waiting": states["waiting"]}


def collector_list(c):
    authz.check(c.principal, COLLECTORS, "read")
    items = rows(c.db, """SELECT c.*, s.name AS source_name, s.platform FROM tdr_data_collectors c
        JOIN tdr_data_sources s ON s.id=c.source_id ORDER BY s.name, c.code""")
    for col in items:
        col["state"] = state(c.db, col)
    order = {"error": 0, "overdue": 1, "waiting": 2, "ok": 3, "revoked": 4}
    items.sort(key=lambda col: order.get(col["state"]["state"], 5))
    return {"items": items, "summary": collectors_summary(c.db), "can_manage": authz.can_write(c.principal, COLLECTORS)
            and c.principal.auth_type not in ("api_key", "collector")}


def download(c):
    """Toplayıcı tek dosya: Python zipapp (.pyz). İçinde yalnızca toplayıcı ve K-029 doğrulayıcıları vardır; sır yoktur."""
    authz.require_human(c.principal)
    authz.check(c.principal, COLLECTORS, "read")
    base = Path(__file__).resolve().parent.parent
    buf = io.BytesIO()
    buf.write(b"#!/usr/bin/env python3\n")
    with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as z:
        z.writestr("__main__.py", "import sys\nfrom tdr_collector import main\nsys.exit(main())\n")
        z.write(base / "collector.py", "tdr_collector.py")
        z.write(base / "pii.py", "tdr_pii.py")
    audit.log(c.db, c.principal, "DOWNLOAD", "data_collectors", 0, {"file": "tedarik-toplayici.pyz"})
    return 200, Raw(buf.getvalue(), "application/octet-stream", "tedarik-toplayici.pyz")


# ------------------------------------------------------------------ şema değişikliği bildirimi

CHANGE_LABELS = CHOICES["catalog_changes.change"]
IMPORTANT_KINDS = ("column_removed", "type_changed", "table_removed")


def _chunks(values, size=500):
    values = list(values)
    for i in range(0, len(values), size):
        yield values[i:i + size]


def significance(db, changes):
    """Kaldırılan veya tipi değişen nesnede kişisel veri, kritik veri, terim bağı veya onaylı veri seti varsa gerekçeler."""
    flags = {}
    col_ids = {cid for kind, _, _, _, cid in changes if cid and kind in ("column_removed", "type_changed")}
    tab_ids = {tid for kind, _, _, tid, cid in changes if tid and not cid and kind == "table_removed"}
    for chunk in _chunks(col_ids):
        for r in rows(db, f"""SELECT c.id, c.personal_data, c.is_critical, t.certified,
                (SELECT COUNT(*) FROM tdr_term_columns m WHERE m.column_id=c.id) AS terms
                FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id
                WHERE c.id IN ({','.join('?' * len(chunk))})""", chunk):
            reasons = [label for ok, label in ((r["personal_data"] in ("personal", "special"), "kişisel veri"),
                                               (r["is_critical"], "kritik veri"), (r["terms"], "sözlük terimi bağlı"),
                                               (r["certified"], "onaylı veri setinde")) if ok]
            if reasons:
                flags[("column", r["id"])] = reasons
    for chunk in _chunks(tab_ids):
        for r in rows(db, f"""SELECT t.id, t.certified,
                (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.personal_data IN ('personal','special')) AS personal,
                (SELECT COUNT(*) FROM tdr_data_columns c WHERE c.table_id=t.id AND c.is_critical=1) AS critical,
                (SELECT COUNT(*) FROM tdr_term_tables m WHERE m.table_id=t.id) + (SELECT COUNT(*) FROM tdr_term_columns m
                 JOIN tdr_data_columns c ON c.id=m.column_id WHERE c.table_id=t.id) AS terms
                FROM tdr_data_tables t WHERE t.id IN ({','.join('?' * len(chunk))})""", chunk):
            reasons = [label for ok, label in ((r["personal"], "kişisel veri içeriyor"), (r["critical"], "kritik veri içeriyor"),
                                               (r["terms"], "sözlük terimi bağlı"), (r["certified"], "onaylı veri seti")) if ok]
            if reasons:
                flags[("table", r["id"])] = reasons
    return flags


def notify_changes(db, source, import_id, changes):
    """İçe aktarımdaki şema değişikliklerini sahiplere bildirir. Dönüş: kuyruğa yazılan ileti sayısı."""
    mode = source.get("change_notice") or "all"
    if mode == "none" or not changes:
        return 0
    flags = significance(db, changes)
    items = []
    for kind, obj, detail, tid, cid in changes:
        reasons = flags.get(("column", cid)) if cid else flags.get(("table", tid))
        important = bool(reasons) and kind in IMPORTANT_KINDS
        if mode == "important" and not important:
            continue
        items.append({"kind": kind, "object": obj, "detail": detail, "table_id": tid, "important": important,
                      "reasons": reasons or []})
    if not items:
        return 0
    owners = {}
    for chunk in _chunks({i["table_id"] for i in items if i["table_id"]}):
        for r in rows(db, f"""SELECT t.id, {EFF_COLS} FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id
                {EFFECTIVE} WHERE t.id IN ({','.join('?' * len(chunk))})""", chunk):
            owners[r["id"]] = [u for u in (r["eff_owner"], r["eff_steward"]) if u]
    everyone = [u for u in (source.get("steward"), source.get("custodian")) if u]
    per_user = {}
    for item in items:
        for user in dict.fromkeys(owners.get(item["table_id"], []) + everyone):
            per_user.setdefault(user, []).append(item)
    sent = 0
    for user, mine in per_user.items():
        mine.sort(key=lambda i: (not i["important"], i["kind"], i["object"]))
        important = sum(1 for i in mine if i["important"])
        lines = [f"• {CHANGE_LABELS.get(i['kind'], i['kind'])}: {i['object']}" + (f" ({i['detail']})" if i["detail"] else "")
                 + (f" — ÖNEMLİ: {', '.join(i['reasons'])}" if i["important"] else "") for i in mine[:40]]
        if len(mine) > 40:
            lines.append(f"… ve {len(mine) - 40} değişiklik daha")
        subject = f"{source['name']}: {len(mine)} şema değişikliği" + (f", {important} önemli" if important else "")
        body = (f"{source['name']} ({source['code']}) kaynağının son içe aktarımında sorumlu olduğunuz nesnelerde değişiklik "
                "var. Kaldırılan veya tipi değişen kolonları kullanan rapor, süreç ve kontrolleri gözden geçirin.\n\n" +
                "\n".join(lines))
        sent += _notify(db, "catalog.changed", subject, body, users=[user], link=f"#/datasource/{source['id']}",
                        object_type="data_sources", object_id=source["id"], dedupe=f"catalog:{import_id}")
    return sent


# ------------------------------------------------------------------ hatırlatma, sağlık kontrolü, İşlerim

@reminder
def collector_reminders(db, app):
    """Beklenen sürede veri göndermeyen toplayıcı için teknik sorumluya bir kez (yeni gönderim gelene kadar) bildirim."""
    if not app.enabled("datagov"):
        return 0
    n, now = 0, datetime.now(timezone.utc)
    for col in rows(db, "SELECT * FROM tdr_data_collectors WHERE status='active' AND overdue_notified_at IS NULL"):
        due = due_at(db, col)
        if not due or due >= now:
            continue
        last = col["last_push_at"]
        n += _notify(db, "collector.overdue", f"Toplayıcı gecikti: {col['code']} {col['name']}",
                     ("Son gönderim: " + last[:16].replace("T", " ") + " (UTC)." if last else "Toplayıcı henüz hiç veri göndermedi.")
                     + f" Beklenen sıklık: {CHOICES['data_collectors.schedule'].get(col['schedule'], col['schedule'])}. "
                     "Toplayıcının çalıştığı makinedeki zamanlanmış görevi ve çıktısını denetleyin.",
                     users=_recipients(db, col), link=f"#/collector/{col['id']}", object_type="data_collectors",
                     object_id=col["id"], dedupe=f"tpl-late:{col['id']}:{last or 'never'}")
        db.execute("UPDATE tdr_data_collectors SET overdue_notified_at=? WHERE id=?", (utcnow(), col["id"]))
    return n


def health_checks(db, check, count, readable=lambda name: True):
    if not readable("data_collectors"):
        return []
    items = rows(db, """SELECT c.*, s.name AS source_name FROM tdr_data_collectors c JOIN tdr_data_sources s
        ON s.id=c.source_id WHERE c.status='active' ORDER BY c.code""")
    bad = [{"id": col["id"], "code": col["code"], "title": f"{col['source_name']} — {st['label']}"}
           for col in items for st in (state(db, col),) if st["state"] in ("overdue", "error")]
    return [check("collectors_attention", "Gecikmiş veya hata veren toplayıcılar",
                  "Toplayıcı çalışmazsa katalog eskir; şema değişiklikleri ve yeni kişisel veri kolonları görünmez.",
                  "medium", bad, "data_collectors", population=len(items))]


def my_work_items(db, principal, names):
    marks = ",".join("?" * len(names))
    items = rows(db, f"""SELECT c.*, s.name AS source_name FROM tdr_data_collectors c JOIN tdr_data_sources s ON s.id=c.source_id
        WHERE c.status='active' AND (s.custodian IN ({marks}) OR s.steward IN ({marks}) OR c.created_by IN ({marks}))""",
                 (*names, *names, *names))
    return {"collectors_attention": [{"id": col["id"], "code": col["code"], "title": f"{col['source_name']}: {st['label']}",
                                      "state": st["state"]}
                                     for col in items for st in (state(db, col),) if st["state"] in ("overdue", "error")]}


def seed(db):
    for code, (value, description) in DEFAULT_POLICIES.items():
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))


def register(app):
    app.route("GET", API + "/collector/whoami", collector_whoami)
    app.route("POST", API + "/collector/catalog", collector_push, max_body=MAX_UPLOAD_BODY)
    app.route("POST", API + "/collector/status", collector_status)
    app.route("GET", API + "/datagov/collectors", collector_list)
    app.route("GET", API + "/datagov/collector.pyz", download)
    app.route("POST", API + "/data_sources/{id}/collectors", collector_create)
    app.route("GET", API + "/data_collectors/{id}/context", collector_context)
    app.route("POST", API + "/data_collectors/{id}/rotate-key", collector_rotate)
    app.route("POST", API + "/data_collectors/{id}/revoke", collector_revoke)
