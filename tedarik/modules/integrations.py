"""Entegrasyonlar (Yönetim → Entegrasyonlar) ve bildirim kutusu (K-024). Çekirdek modülün parçası.

Tanımlar yapılarak bağlantılar arayüzden kurulur ve sınanır:
- E-posta (SMTP) ve Microsoft Teams (Workflows gelen web kancası): bildirim ve günlük iş özeti (notify.py).
- Entra ID ile giriş ve MFA (Koşullu Erişim kimlik doğrulama bağlamı): ayarlar burada tanımlanır, sınanır
  (OpenID yapılandırması, JWKS, istemci kimlik bilgisi); giriş modu kurulumda seçilir (`auth_mode=entra`) ve
  ortam değişkeni yoksa ayarlar buradan okunur. Eksikse uygulama Entra modunda açılmaz (kapalı başarısızlık).
- ServiceNow CMDB (Table API) ve ServiceNow MCP sunucusu (K-019, K-021): ortam değişkeniyle verilmemişse buradaki
  tanım kullanılır; sınama okuma yapar, yazmaz.
- Yapay zekâ yardımı (Claude API): insan onaylı öneriler (ai.py); kapalıyken kural tabanlı öneriler çalışır.

Ayarlar `settings_json` içinde düz, sırlar `secrets_json` içinde Fernet ile şifreli durur (secretbox.py); sır API'den
geri dönmez. Ortam değişkeniyle (kurulum dosyası) verilen ayar önceliklidir ve arayüzden değiştirilemez.
Yalnızca Yönetici görür ve değiştirir; her değişiklik ve sınama denetim izine yazılır (sır maskeli).
"""
import ipaddress
import json
import re
import smtplib
import ssl
import urllib.error
import urllib.request
from types import SimpleNamespace
from urllib.parse import urlparse

from .. import audit, auth as authz, crud, secretbox
from ..db import one, rows, utcnow
from ..http import API
from ..schema import RESOURCES, Resource

M = "core"
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,24}$")
AI_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")

INTEGRATIONS = Resource("integrations", "Entegrasyonlar", {
    "kind": "TEXT NOT NULL UNIQUE", "enabled": "INTEGER NOT NULL DEFAULT 0", "settings_json": "TEXT",
    "secrets_json": "TEXT", "last_test_at": "TIMESTAMP", "last_test_ok": "INTEGER", "last_test_message": "TEXT",
    "updated_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, api=(), search=(), read_roles={"ADMIN"}, write_roles={"ADMIN"})

NOTIFICATIONS = Resource("notifications", "Bildirimler", {
    "channel": "TEXT NOT NULL", "recipient": "TEXT", "username": "TEXT", "event": "TEXT NOT NULL",
    "subject": "TEXT NOT NULL", "body": "TEXT", "link": "TEXT", "object_type": "TEXT", "object_id": "INTEGER",
    "dedupe_key": "TEXT UNIQUE", "status": "TEXT NOT NULL DEFAULT 'queued'", "attempts": "INTEGER NOT NULL DEFAULT 0",
    "last_error": "TEXT", "created_at": "TIMESTAMP NOT NULL", "sent_at": "TIMESTAMP"},
    module=M, api=("list", "get"), search=("subject", "recipient", "event"), read_roles={"ADMIN"},
    write_roles={"ADMIN"}, indexes=(("status", "created_at"),),
    enums={"channel": ("email", "teams"), "status": ("queued", "sent", "failed", "skipped")})


def F(name, label, kind="text", required=False, placeholder="", help="", options=()):
    return {"name": name, "label": label, "type": kind, "required": required, "placeholder": placeholder,
            "help": help, "options": [{"value": v, "label": lab} for v, lab in options]}


def S(name, label, help=""):
    return {"name": name, "label": label, "help": help}


CATALOG = {
    "email": {
        "title": "E-posta (SMTP)", "group": "Bildirim",
        "description": "Görev atamaları, yaklaşan ve geciken işler, onay talepleri ve günlük iş özeti e-postayla gider. "
                       "Microsoft 365 için smtp.office365.com:587 (STARTTLS) ve gönderme yetkili bir posta kutusu.",
        "fields": [F("host", "SMTP sunucusu", required=True, placeholder="smtp.office365.com"),
                   F("port", "Port", "number", True, "587"),
                   F("security", "Bağlantı güvenliği", "select", True,
                     options=(("starttls", "STARTTLS (genellikle 587)"), ("ssl", "SSL/TLS (genellikle 465)"))),
                   F("username", "Kullanıcı adı", placeholder="grc-bildirim@kurum.com.tr"),
                   F("sender", "Gönderen adresi", "email", True, "grc-bildirim@kurum.com.tr"),
                   F("sender_name", "Gönderen adı", placeholder="GRC Platformu"),
                   F("test_recipient", "Sınama alıcısı", "email", help="Sınamada bu adrese deneme e-postası gönderilir.")],
        "secrets": [S("password", "Parola veya uygulama parolası")]},
    "teams": {
        "title": "Microsoft Teams", "group": "Bildirim",
        "description": "Kritik olaylar (kişisel veri ihlali, kriz, süresi dolan istisna) bir Teams kanalına kart olarak "
                       "gönderilir. Kanalda Workflows → \"Bir web kancası isteği alındığında kanala gönder\" akışı "
                       "oluşturup verdiği adresi girin.",
        "fields": [F("channel", "Kanal adı (bilgi amaçlı)", placeholder="GRC Uyarıları")],
        "secrets": [S("webhook_url", "Gelen web kancası adresi", "Adres gizli tutulur; adresi bilen kanala yazabilir.")]},
    "entra": {
        "title": "Entra ID ile giriş ve MFA", "group": "Kimlik",
        "description": "Kurumsal giriş Microsoft Entra ID (OIDC, PKCE) ile yapılır; MFA, Koşullu Erişim kimlik doğrulama "
                       "bağlamıyla (c1–c99) zorunlu tutulur ve belirteçte doğrulanır. Roller Entra uygulama rollerinden "
                       "(KS.TDR.*) gelir. Ayarları girip sınayın; giriş modu kurulumda Entra'ya alınır.",
        "fields": [F("tenant_id", "Kiracı (tenant) kimliği", required=True, placeholder="00000000-0000-0000-0000-000000000000"),
                   F("client_id", "Uygulama (istemci) kimliği", required=True, placeholder="00000000-0000-0000-0000-000000000000"),
                   F("auth_context", "MFA kimlik doğrulama bağlamı", required=True, placeholder="c1",
                     help="Koşullu Erişim ilkesinde MFA isteyen bağlam (c1–c99)."),
                   F("redirect_uri", "Dönüş adresi", placeholder="https://grc.kurum.com.tr/auth/entra/callback",
                     help="Boşsa uygulama adresinden türetilir; Entra uygulama kaydında aynısı olmalı.")],
        "secrets": [S("client_secret", "İstemci sırrı")]},
    "servicenow": {
        "title": "ServiceNow CMDB (Table API)", "group": "Veri kaynağı",
        "description": "CMDB'deki uygulama ve CI'lar salt okunur hizmet hesabıyla gece senkronlanır; CI risk kuralları "
                       "çalışır. Hesaba cmdb_ci* tablolarında okuma yetkisi yeterlidir.",
        "fields": [F("instance", "Örnek adresi", "url", True, "https://kurum.service-now.com"),
                   F("user", "Kullanıcı adı", placeholder="svc_grc_read", help="Bearer belirteci kullanılıyorsa boş bırakın.")],
        "secrets": [S("password", "Parola"), S("token", "Bearer belirteci", "Parola yerine OAuth erişim belirteci.")]},
    "servicenow_mcp": {
        "title": "ServiceNow MCP sunucusu", "group": "Veri kaynağı",
        "description": "CMDB, ServiceNow MCP sunucusunun okuma aracıyla da çekilebilir (Streamable HTTP). Çağrılacak "
                       "aracın adı ve argümanları Sistem parametrelerinde (cmdb.mcp) tanımlıdır.",
        "fields": [F("url", "MCP uç noktası", "url", True, "https://kurum.service-now.com/api/mcp"),
                   F("auth", "Kimlik doğrulama", "select", True,
                     options=(("bearer", "Bearer belirteci"), ("oauth", "OAuth 2.0 istemci kimlik bilgisi"))),
                   F("token_url", "OAuth belirteç adresi", "url", placeholder="https://kurum.service-now.com/oauth_token.do"),
                   F("client_id", "OAuth istemci kimliği"), F("scope", "OAuth kapsamı (isteğe bağlı)")],
        "secrets": [S("token", "Bearer belirteci"), S("client_secret", "OAuth istemci sırrı")]},
    "ai": {
        "title": "Yapay zekâ yardımı (Claude)", "group": "Yardım",
        "description": "Risk ifadesi kalite denetimi, kanıt–kontrol eşleme önerisi, madde eşleme önerisi ve denetim raporu "
                       "taslağı için Claude API. Öneriler hiçbir zaman kendiliğinden uygulanmaz; kullanıcı onaylar. "
                       "Kısıtlı kanıt ve kişisel veri alanları gönderilmez. Kapalıyken kural tabanlı öneriler çalışır.",
        "fields": [F("model", "Model", "select", True, options=tuple((m, m) for m in AI_MODELS)),
                   F("effort", "Düşünme düzeyi", "select", True,
                     options=(("low", "Düşük (hızlı)"), ("medium", "Orta"), ("high", "Yüksek"))),
                   F("data_approval", "Veri işleme onayı", "text", True, placeholder="ör. BGYS kurulu kararı 2026/14",
                     help="Kayıt metinlerinin Anthropic'e gönderilmesine ilişkin kurum onayının referansı.")],
        "secrets": [S("api_key", "API anahtarı")]},
}
DEFAULTS = {"email": {"port": 587, "security": "starttls"}, "servicenow_mcp": {"auth": "bearer"},
            "ai": {"model": "claude-opus-5-5", "effort": "medium"}}


# ------------------------------------------------------------------ okuma ve etkin yapılandırma

def _row(db, kind):
    return one(db, "SELECT * FROM tdr_integrations WHERE kind=?", (kind,))


def env_source(config, kind):
    """Kurulum dosyasıyla (ortam değişkeni) verilmiş bağlantı: arayüz tanımının önüne geçer."""
    env = config.env
    return {"entra": bool(env.get("TEDARIK_ENTRA_TENANT_ID")), "servicenow": bool(config.sn_instance),
            "servicenow_mcp": bool(config.sn_mcp_url)}.get(kind, False)


def settings(db, kind):
    row = _row(db, kind)
    return {**DEFAULTS.get(kind, {}), **(json.loads(row["settings_json"]) if row and row["settings_json"] else {})}


def secret(db, config, kind, name):
    row = _row(db, kind)
    sealed = json.loads(row["secrets_json"]) if row and row["secrets_json"] else {}
    try:
        return secretbox.unseal(config, sealed[name]) if sealed.get(name) else None
    except secretbox.SecretsUnavailable as exc:
        raise crud.Conflict(str(exc)) from None


def enabled(db, kind):
    row = _row(db, kind)
    return bool(row and row["enabled"])


def servicenow_config(db, config):
    """CMDB senkronunun kullanacağı yapılandırma: ortam değişkeni varsa o, yoksa etkin arayüz tanımları."""
    if config.sn_instance or config.sn_mcp_url:
        return config
    out = SimpleNamespace(sn_instance="", sn_user="", sn_password_file="", sn_token_file="", sn_ca_file=None,
                          sn_mcp_url="", sn_mcp_token_file="", sn_mcp_token_url="", sn_mcp_client_id="",
                          sn_mcp_client_secret_file="", sn_mcp_scope=None, sn_password=None, sn_token=None,
                          sn_mcp_token=None, sn_mcp_client_secret=None, env=config.env)
    if enabled(db, "servicenow"):
        s = settings(db, "servicenow")
        out.sn_instance, out.sn_user = s.get("instance", "").rstrip("/"), s.get("user", "")
        out.sn_password, out.sn_token = secret(db, config, "servicenow", "password"), secret(db, config, "servicenow", "token")
    if enabled(db, "servicenow_mcp"):
        s = settings(db, "servicenow_mcp")
        out.sn_mcp_url = s.get("url", "")
        if s.get("auth") == "oauth":
            out.sn_mcp_token_url, out.sn_mcp_client_id = s.get("token_url", ""), s.get("client_id", "")
            out.sn_mcp_scope = s.get("scope") or None
            out.sn_mcp_client_secret = secret(db, config, "servicenow_mcp", "client_secret")
        else:
            out.sn_mcp_token = secret(db, config, "servicenow_mcp", "token")
    return out


def entra_env(db, config):
    """Arayüzde tanımlı Entra ayarlarının entra_auth adlarıyla karşılığı (ortam değişkeni yoksa)."""
    s = settings(db, "entra")
    if not s.get("tenant_id") or not s.get("client_id"):
        return None
    redirect = s.get("redirect_uri") or (config.public_url.rstrip("/") + "/auth/entra/callback" if config.public_url else "")
    return {"TEDARIK_ENTRA_TENANT_ID": s["tenant_id"], "TEDARIK_ENTRA_CLIENT_ID": s["client_id"],
            "TEDARIK_ENTRA_AUTH_CONTEXT": s.get("auth_context", ""), "TEDARIK_ENTRA_REDIRECT_URI": redirect,
            "TEDARIK_ENTRA_CLIENT_SECRET": secret(db, config, "entra", "client_secret") or ""}


def entra_from_db(db, config):
    """Entra modunda ortam değişkeni yoksa sağlayıcı arayüz tanımından kurulur; tanım yoksa açılış durur."""
    from .. import session
    values = entra_env(db, config) if enabled(db, "entra") else None
    if not values:
        raise RuntimeError("Entra modu seçildi ama Entra ayarları yok: kurulum dosyasıyla (entra.env) verin veya "
                           "yerel modda Yönetim → Entegrasyonlar'da tanımlayıp etkinleştirin")
    return session.entra_provider(config, overrides=values)


# ------------------------------------------------------------------ doğrulama

def _https(value, label, allow_http=False):
    parsed = urlparse(value or "")
    if parsed.scheme not in (("https", "http") if allow_http else ("https",)) or not parsed.netloc:
        raise crud.Invalid(f"{label} https:// ile başlayan tam adres olmalı")
    host = parsed.hostname or ""
    try:
        ip = ipaddress.ip_address(host)
        if not allow_http and (ip.is_loopback or ip.is_link_local or ip.is_unspecified):
            raise crud.Invalid(f"{label}: yerel veya bağlantı-yerel adres kullanılamaz")
    except ValueError:
        pass
    return value.rstrip("/")


def _validate(kind, values, config):
    spec = CATALOG[kind]
    out = {}
    for f in spec["fields"]:
        v = values.get(f["name"])
        if isinstance(v, str):
            v = v.strip()
        if v in (None, ""):
            if f["required"]:
                raise crud.Invalid(f"{f['label']} gerekli")
            continue
        if f["type"] == "number":
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise crud.Invalid(f"{f['label']} sayı olmalı") from None
        elif not isinstance(v, str) or len(v) > 500:
            raise crud.Invalid(f"{f['label']} en çok 500 karakterlik metin olmalı")
        if f["options"] and v not in [o["value"] for o in f["options"]]:
            raise crud.Invalid(f"{f['label']} geçersiz")
        if f["type"] == "email" and not EMAIL.match(v):
            raise crud.Invalid(f"{f['label']} geçerli bir e-posta adresi olmalı")
        if f["type"] == "url":
            v = _https(v, f["label"], allow_http=config.env.get("TEDARIK_SN_ALLOW_HTTP") == "1")
        out[f["name"]] = v
    if kind == "email" and not 1 <= out.get("port", 0) <= 65535:
        raise crud.Invalid("Port 1–65535 arasında olmalı")
    if kind == "entra":
        for key in ("tenant_id", "client_id"):
            if not GUID.match(out.get(key, "")):
                raise crud.Invalid(f"{key == 'tenant_id' and 'Kiracı' or 'İstemci'} kimliği GUID biçiminde olmalı")
        if not re.fullmatch(r"c([1-9]|[1-9][0-9])", out.get("auth_context", "")):
            raise crud.Invalid("Kimlik doğrulama bağlamı c1–c99 olmalı")
        if out.get("redirect_uri"):
            out["redirect_uri"] = _https(out["redirect_uri"], "Dönüş adresi")
            if not out["redirect_uri"].endswith("/auth/entra/callback"):
                raise crud.Invalid("Dönüş adresi /auth/entra/callback ile bitmeli")
    if kind == "servicenow_mcp" and out.get("auth") == "oauth" and not (out.get("token_url") and out.get("client_id")):
        raise crud.Invalid("OAuth için belirteç adresi ve istemci kimliği gerekli")
    return out


def _secret_rules(kind, name, value):
    if kind == "teams" and name == "webhook_url":
        _https(value, "Web kancası adresi")
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise crud.Invalid("Sır boş olamaz (en çok 4000 karakter)")
    return value.strip()


# ------------------------------------------------------------------ uç noktalar

def _public(db, config, kind):
    spec = CATALOG[kind]
    row = _row(db, kind)
    sealed = json.loads(row["secrets_json"]) if row and row["secrets_json"] else {}
    from_env = env_source(config, kind)
    state = "env" if from_env else "enabled" if row and row["enabled"] else "configured" if row else "off"
    out = {"kind": kind, "title": spec["title"], "group": spec["group"], "description": spec["description"],
           "fields": spec["fields"], "secrets": [{**s, "set": bool(sealed.get(s["name"]))} for s in spec["secrets"]],
           "settings": settings(db, kind), "enabled": bool(row and row["enabled"]), "state": state,
           "env": from_env, "last_test_at": row["last_test_at"] if row else None,
           "last_test_ok": row["last_test_ok"] if row else None,
           "last_test_message": row["last_test_message"] if row else None,
           "updated_by": row["updated_by"] if row else None, "updated_at": row["updated_at"] if row else None}
    if kind == "entra":
        out["active_login"] = config.auth_mode == "entra"
    if kind == "ai":
        try:
            import anthropic  # noqa: F401  (isteğe bağlı paket; requirements.txt'e eklenmesi onay bekliyor)
            out["sdk"] = True
        except ImportError:
            out["sdk"] = False
    return out


def list_route(c):
    authz.require(c.principal, "admin")
    return {"integrations": [_public(c.db, c.app.config, kind) for kind in CATALOG],
            "secrets_available": secretbox.available(c.app.config), "auth_mode": c.app.config.auth_mode,
            "public_url": c.app.config.public_url}


def save(c):
    """{kind, enabled?, settings?, secrets?: {ad: değer | null}}: null sırrı siler; verilmeyen sır korunur."""
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")
    kind = c.body.get("kind")
    if kind not in CATALOG:
        raise crud.Invalid("Tanımsız entegrasyon")
    if env_source(c.app.config, kind):
        raise crud.Conflict("Bu bağlantı sunucu kurulum dosyasıyla yapılandırılmış; arayüzden değiştirilemez")
    row = _row(c.db, kind)
    current = settings(c.db, kind)
    values = c.body.get("settings")
    new_settings = _validate(kind, {**current, **values}, c.app.config) if isinstance(values, dict) else current
    sealed = json.loads(row["secrets_json"]) if row and row["secrets_json"] else {}
    changed_secrets = []
    for name, value in (c.body.get("secrets") or {}).items():
        if name not in {s["name"] for s in CATALOG[kind]["secrets"]}:
            raise crud.Invalid(f"Tanımsız sır: {name}")
        if value is None:
            sealed.pop(name, None)
        else:
            try:
                sealed[name] = secretbox.seal(c.app.config, _secret_rules(kind, name, value))
            except secretbox.SecretsUnavailable as exc:
                raise crud.Conflict(str(exc)) from None
        changed_secrets.append(name)
    enable = c.body.get("enabled", row["enabled"] if row else 0)
    if enable not in (0, 1, True, False):
        raise crud.Invalid("enabled 0 veya 1 olmalı")
    if enable:
        _validate(kind, new_settings, c.app.config)               # zorunlu alanlar tamam mı
        need = {"teams": ["webhook_url"], "entra": ["client_secret"], "ai": ["api_key"]}.get(kind, [])
        missing = [s for s in need if not sealed.get(s)]
        if kind == "servicenow" and not (sealed.get("password") or sealed.get("token")):
            missing.append("password/token")
        if missing:
            raise crud.Invalid("Etkinleştirmek için sır gerekli: " + ", ".join(missing))
    now = utcnow()
    data = (int(bool(enable)), json.dumps(new_settings, ensure_ascii=False), json.dumps(sealed) if sealed else None,
            c.principal.username, now)
    if row:
        c.db.execute("UPDATE tdr_integrations SET enabled=?, settings_json=?, secrets_json=?, updated_by=?, updated_at=? "
                     "WHERE kind=?", (*data, kind))
    else:
        c.db.execute("INSERT INTO tdr_integrations (enabled, settings_json, secrets_json, updated_by, updated_at, kind, "
                     "created_at) VALUES (?,?,?,?,?,?,?)", (*data, kind, now))
    audit.log(c.db, c.principal, "UPDATE", "integrations", None,
              {"kind": kind, "enabled": bool(enable), "settings": new_settings,
               "secrets_changed": changed_secrets}, description=CATALOG[kind]["title"])
    return _public(c.db, c.app.config, kind)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def post_json(url, payload, timeout=10, opener=None):
    """HTTPS JSON gönderimi (Teams): yönlendirme izlenmez, yanıt en çok 64 KB okunur."""
    if urlparse(url).scheme != "https":
        raise ValueError("Adres HTTPS olmalı")
    opener = opener or urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
    with opener.open(request, timeout=timeout) as response:      # nosec B310 - adres HTTPS ve yöneticiden
        response.read(65536)
        return response.status


def _test_email(db, config, opener):
    from .. import notify
    s = settings(db, "email")
    to = s.get("test_recipient") or s.get("sender")
    notify.send_email(s, secret(db, config, "email", "password"), to, f"{config.app_name}: e-posta sınaması",
                      "Bu ileti GRC platformunun e-posta bağlantısını sınamak için gönderildi.", None)
    return [("ok", "SMTP", f"{s.get('host')}:{s.get('port')} bağlantısı ve oturum açıldı; {to} adresine deneme iletisi gönderildi")]


def _test_teams(db, config, opener):
    from .. import notify
    url = secret(db, config, "teams", "webhook_url")
    if not url:
        return [("fail", "Web kancası", "Adres girilmemiş")]
    status = post_json(url, notify.teams_card(f"{config.app_name}: Teams sınaması",
                                              "Bu kart GRC platformunun Teams bağlantısını sınamak için gönderildi.", None),
                       opener=opener)
    return [("ok", "Teams", f"Kart gönderildi (HTTP {status})")]


def _test_entra(db, config, opener):
    from ..config import Config
    from ..entra_check import check
    values = entra_env(db, config)
    if not values:
        return [("fail", "Ayarlar", "Kiracı ve istemci kimliği girilmemiş")]
    if not values["TEDARIK_ENTRA_REDIRECT_URI"]:
        return [("fail", "Dönüş adresi", "Dönüş adresi girin veya uygulama adresini (TEDARIK_PUBLIC_URL) tanımlayın")]
    env = {k: v for k, v in config.env.items() if not k.startswith("TEDARIK_ENTRA_")}
    probe = Config({**env, **{k: v for k, v in values.items() if v}, "TEDARIK_AUTH_MODE": "entra",
                    "TEDARIK_COOKIE_SECURE": "1"})
    return check(probe, opener=opener)


def _test_servicenow(db, config, opener):
    from .cmdb import servicenow_client
    client = servicenow_client(servicenow_config(db, config))
    record = next(iter(client.table("cmdb_ci_server", ["sys_id", "name"], page_size=1)), None)
    return [("ok", "Table API", "cmdb_ci_server okundu: " + ("örnek kayıt alındı" if record else "kayıt dönmedi"))]


def _test_mcp(db, config, opener):
    from ..mcp_client import McpError
    from .cmdb import mcp_client
    client = mcp_client(servicenow_config(db, config))
    try:
        server = client.initialize()
        tools = client.list_tools()
    except McpError as exc:
        return [("fail", "MCP", str(exc))]
    finally:
        client.close()
    name = (server or {}).get("serverInfo", {}).get("name", "sunucu")
    return [("ok", "Oturum", f"{name}: protokol {client.protocol}"), ("ok", "Araçlar", f"{len(tools)} araç listelendi")]


def _test_ai(db, config, opener):
    from .. import ai
    return ai.test_connection(db, config)


TESTS = {"email": _test_email, "teams": _test_teams, "entra": _test_entra, "servicenow": _test_servicenow,
         "servicenow_mcp": _test_mcp, "ai": _test_ai}


def test(c, opener=None):
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")
    kind = c.body.get("kind")
    if kind not in CATALOG:
        raise crud.Invalid("Tanımsız entegrasyon")
    if not _row(c.db, kind) and not env_source(c.app.config, kind):
        raise crud.Conflict("Önce ayarları kaydedin")
    try:
        steps = TESTS[kind](c.db, c.app.config, opener or getattr(c.app, "integration_opener", None))
    except secretbox.SecretsUnavailable as exc:
        steps = [("fail", "Sır", str(exc))]
    except (crud.Conflict, crud.Invalid) as exc:
        steps = [("fail", "Ayarlar", str(exc))]
    except (OSError, smtplib.SMTPException, ssl.SSLError, ValueError, urllib.error.URLError) as exc:
        steps = [("fail", "Bağlantı", f"{type(exc).__name__}: {str(exc)[:300]}")]
    ok = bool(steps) and all(s[0] != "fail" for s in steps)
    message = "; ".join(f"{t}: {d}" for _s, t, d in steps)[:2000]
    if _row(c.db, kind):
        c.db.execute("UPDATE tdr_integrations SET last_test_at=?, last_test_ok=?, last_test_message=? WHERE kind=?",
                     (utcnow(), int(ok), message, kind))
    audit.log(c.db, c.principal, "TEST", "integrations", None, {"kind": kind, "ok": ok})
    return {"kind": kind, "ok": ok, "steps": [{"status": s, "title": t, "detail": d} for s, t, d in steps]}


def notification_settings(c):
    """Olay → kanal eşlemesi ve kuyruk özeti (Bildirimler ekranı)."""
    authz.require(c.principal, "admin")
    from .. import notify
    counts = {r["status"]: r["n"] for r in rows(c.db, "SELECT status, COUNT(*) AS n FROM tdr_notifications GROUP BY status")}
    return {"events": notify.event_table(c.db), "counts": counts,
            "channels": {k: enabled(c.db, k) for k in ("email", "teams")}}


def save_notification_settings(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")
    from .. import notify
    return notify.save_event_table(c.db, c.principal, c.body.get("events"))


def deliver_now(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")
    from .. import notify
    result = notify.deliver(c.db, c.app)
    audit.log(c.db, c.principal, "SEND", "notifications", None, result)
    return result


def _ai_route(kind):
    def route(c):
        from .. import ai
        authz.require_human(c.principal)
        key = {"risk": "risk_id", "evidence": "evidence_id"}[kind]
        record_id = c.body.get(key)
        if type(record_id) is not int:
            raise crud.Invalid(f"{key} gerekli")
        if kind == "risk":
            authz.check(c.principal, RESOURCES["supplier_risks"], "read")
            return ai.risk_quality(c.db, c.app.config, c.principal, record_id)
        authz.check(c.principal, RESOURCES["evidence"], "read")
        return ai.evidence_controls(c.db, c.app.config, c.principal, record_id)
    return route


def ai_status(c):
    return {"enabled": enabled(c.db, "ai")}


def register(app):
    app.route("GET", API + "/ai/status", ai_status)
    if app.enabled("risks"):
        app.route("POST", API + "/ai/risk-quality", _ai_route("risk"))
    if app.enabled("grc"):
        app.route("POST", API + "/ai/evidence-controls", _ai_route("evidence"))
    app.route("GET", API + "/integrations", list_route)
    app.route("POST", API + "/integrations/save", save)
    app.route("POST", API + "/integrations/test", test)
    app.route("GET", API + "/notifications/settings", notification_settings)
    app.route("POST", API + "/notifications/settings", save_notification_settings)
    app.route("POST", API + "/notifications/deliver", deliver_now)
