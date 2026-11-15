"""Model Context Protocol (MCP) istemcisi — Streamable HTTP taşıma katmanı (K-021).

ServiceNow'un MCP sunucusuna (veya kurumun ServiceNow MCP uygulamasına) bağlanıp araç (tool) çağırmak için:
- JSON-RPC 2.0: `initialize` → `notifications/initialized` → `tools/list` / `tools/call`.
- Yanıt `application/json` veya `text/event-stream` (SSE) olabilir; SSE'de istek kimliğiyle eşleşen yanıt alınır.
- Sunucunun verdiği `Mcp-Session-Id` sonraki isteklerde gönderilir; oturum düşerse (404) bir kez yeniden başlatılır.
- Kimlik: sabit bearer belirteci (dosyadan) veya OAuth 2.0 istemci kimlik bilgisi akışı (belirteç süresince saklanır).
- Güvenlik: adres yalnızca ayardan gelir (HTTPS), yönlendirme izlenmez (Authorization başka sunucuya taşınmaz),
  yanıt boyutu ve süresi sınırlıdır; belirteç ve sır günlüğe yazılmaz.
"""
import json
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL = "2025-06-18"
MAX_RESPONSE = 16 * 1024 * 1024
CLIENT_INFO = {"name": "grc-platform", "version": "1.0"}


class McpError(Exception):
    """İleti kullanıcıya gösterilebilir; sır içermez."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _opener(ca_file=None, https=True):
    handlers = [_NoRedirect()]
    if https:
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=ca_file)))
    return urllib.request.build_opener(*handlers)


class OAuthClientCredentials:
    """OAuth 2.0 istemci kimlik bilgisi akışı (ör. ServiceNow `oauth_token.do`); belirteç süresi dolana dek saklanır."""

    def __init__(self, token_url, client_id, client_secret, scope=None, opener=None, timeout=20):
        if not token_url.startswith(("https://", "http://")):
            raise McpError("OAuth belirteç adresi https:// ile başlamalı")
        self.token_url, self.client_id, self.client_secret, self.scope = token_url, client_id, client_secret, scope
        self.opener, self.timeout = opener or _opener(https=token_url.startswith("https://")), timeout
        self.token, self.expires, self.lock = None, 0.0, threading.Lock()

    def __call__(self, force=False):
        with self.lock:
            if self.token and not force and time.monotonic() < self.expires:
                return self.token
            form = {"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret}
            if self.scope:
                form["scope"] = self.scope
            request = urllib.request.Request(self.token_url, data=urllib.parse.urlencode(form).encode(),
                                             headers={"Content-Type": "application/x-www-form-urlencoded",
                                                      "Accept": "application/json"})
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    body = json.loads(response.read(1048577))
            except urllib.error.HTTPError as exc:
                exc.close()
                raise McpError(f"OAuth belirteci alınamadı (HTTP {exc.code}); istemci kimliği ve sırrı denetleyin") from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                raise McpError(f"OAuth belirteç adresine erişilemedi: {exc}") from None
            token = body.get("access_token")
            if not isinstance(token, str) or not token:
                raise McpError("OAuth yanıtında access_token yok")
            self.token = token
            self.expires = time.monotonic() + max(30, int(body.get("expires_in", 1800)) - 60)
            return token


class McpClient:
    def __init__(self, url, token=None, token_provider=None, ca_file=None, timeout=60, opener=None):
        if not url.startswith(("https://", "http://")):
            raise McpError("MCP sunucu adresi https:// ile başlamalı")
        self.url, self.timeout = url, timeout
        self.token, self.token_provider = token, token_provider
        self.opener = opener or _opener(ca_file, https=url.startswith("https://"))
        self.session, self.protocol, self.server = None, None, None
        self.next_id, self.requests = 0, 0

    # ------------------------------------------------------------------ taşıma
    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "User-Agent": "grc-platform-mcp/1"}
        token = self.token_provider() if self.token_provider else self.token
        if token:
            headers["Authorization"] = "Bearer " + token
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.protocol:
            headers["MCP-Protocol-Version"] = self.protocol
        return headers

    def _send(self, message):
        request = urllib.request.Request(self.url, data=json.dumps(message).encode(), headers=self._headers(),
                                         method="POST")
        self.requests += 1
        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                if self.token_provider and exc.code == 401:
                    self.token_provider(force=True)
                raise McpError(f"MCP sunucusu kimlik doğrulamayı reddetti (HTTP {exc.code}); belirteci ve yetkiyi "
                               "denetleyin") from None
            if exc.code == 404 and self.session:
                raise _SessionLost() from None
            if 300 <= exc.code < 400:
                raise McpError(f"MCP sunucusu yönlendirme döndü (HTTP {exc.code}); doğrudan MCP uç noktasını "
                               "yapılandırın") from None
            raise McpError(f"MCP isteği başarısız (HTTP {exc.code})") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise McpError(f"MCP sunucusuna erişilemedi: {getattr(exc, 'reason', exc)}") from None
        with response:
            session = response.headers.get("Mcp-Session-Id")
            if session and len(session) <= 512 and session.isascii():
                self.session = session
            if response.status == 202 or "id" not in message:
                return None
            kind = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if kind == "text/event-stream":
                return self._from_stream(response, message["id"])
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise McpError("MCP yanıtı çok büyük; sayfa boyutunu küçültün")
        try:
            body = json.loads(raw)
        except ValueError:
            raise McpError("MCP yanıtı JSON değil") from None
        for item in body if isinstance(body, list) else [body]:
            if isinstance(item, dict) and item.get("id") == message["id"]:
                return item
        raise McpError("MCP yanıtında istek kimliği bulunamadı")

    def _from_stream(self, response, wanted):
        """SSE akışından istek kimliğiyle eşleşen JSON-RPC yanıtını okur (sunucu bildirimleri atlanır)."""
        total, data = 0, []
        for line in response:
            total += len(line)
            if total > MAX_RESPONSE:
                raise McpError("MCP yanıtı çok büyük; sayfa boyutunu küçültün")
            line = line.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line == "" and data:
                try:
                    item = json.loads("\n".join(data))
                except ValueError:
                    item = None
                data = []
                if isinstance(item, dict) and item.get("id") == wanted and ("result" in item or "error" in item):
                    return item
        raise McpError("MCP akışı yanıt gelmeden kapandı")

    def _call(self, method, params=None, retry=True):
        self.next_id += 1
        message = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            message["params"] = params
        try:
            reply = self._send(message)
        except _SessionLost:
            if not retry or method == "initialize":
                raise McpError("MCP oturumu sona erdi") from None
            self.session = None
            self.initialize()
            return self._call(method, params, retry=False)
        if "error" in reply:
            error = reply["error"] if isinstance(reply["error"], dict) else {}
            raise McpError(f"MCP hatası ({error.get('code')}): {str(error.get('message'))[:300]}")
        return reply.get("result") or {}

    # ------------------------------------------------------------------ protokol
    def initialize(self):
        result = self._call("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT_INFO})
        self.protocol = str(result.get("protocolVersion") or PROTOCOL)[:20]
        self.server = {"info": result.get("serverInfo") or {}, "protocol": self.protocol,
                       "capabilities": sorted((result.get("capabilities") or {}).keys())}
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return self.server

    def ensure(self):
        if self.protocol is None:
            self.initialize()

    def list_tools(self):
        self.ensure()
        tools, cursor = [], None
        for _ in range(50):
            result = self._call("tools/list", {"cursor": cursor} if cursor else {})
            tools += [t for t in result.get("tools", []) if isinstance(t, dict) and t.get("name")]
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name, arguments):
        """Aracı çağırır; yapılandırılmış içerik varsa onu, yoksa metin içeriğini (JSON ise çözülmüş) döner."""
        self.ensure()
        result = self._call("tools/call", {"name": name, "arguments": arguments})
        texts = [c.get("text", "") for c in result.get("content", []) if isinstance(c, dict) and c.get("type") == "text"]
        if result.get("isError"):
            raise McpError(f"MCP aracı hata döndü: {' '.join(texts)[:300] or 'ayrıntı yok'}")
        if "structuredContent" in result:
            return result["structuredContent"]
        joined = "\n".join(texts).strip()
        try:
            return json.loads(joined) if joined else None
        except ValueError:
            return joined

    def close(self):
        if not self.session:
            return
        request = urllib.request.Request(self.url, headers=self._headers(), method="DELETE")
        try:
            self.opener.open(request, timeout=5).close()
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        self.session = None


class _SessionLost(Exception):
    pass


# ------------------------------------------------------------------ ServiceNow tablosu MCP aracı üzerinden

def _template(value, values):
    """Argüman şablonu: "{table}" gibi tek yer tutucu değerin tipini korur (ör. liste), metin içinde metne çevrilir."""
    if isinstance(value, str):
        if value.startswith("{") and value.endswith("}") and value[1:-1] in values:
            return values[value[1:-1]]
        for key, item in values.items():
            value = value.replace("{" + key + "}", item if isinstance(item, str) else json.dumps(item))
        return value
    if isinstance(value, dict):
        return {k: _template(v, values) for k, v in value.items()}
    if isinstance(value, list):
        return [_template(v, values) for v in value]
    return value


def _records(result, path):
    data = result
    for part in [p for p in (path or "").split(".") if p]:
        data = data.get(part) if isinstance(data, dict) else None
    if isinstance(data, dict):
        for key in ("result", "records", "items", "data", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    raise McpError("MCP aracı kayıt listesi döndürmedi; cmdb.mcp politikasındaki records_path ayarını denetleyin")


class McpTableSource:
    """`servicenow.Client.table` ile aynı arayüz: CMDB senkronu REST yerine MCP aracını kullanır."""

    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    @property
    def requests(self):
        return self.client.requests

    def table(self, table, fields, query="", watermark=None, page_size=200):
        parts = [query] if query else []
        if watermark:
            parts.append(f"sys_updated_on>={watermark}")
        parts.append("ORDERBYsys_updated_on")
        size = int(self.settings.get("page_size") or page_size)
        tool = self.settings.get("tool") or "query_table"
        template = self.settings.get("arguments") or DEFAULT_SETTINGS["arguments"]
        offset = 0
        while True:
            values = {"table": table, "query": "^".join(parts), "fields": ",".join(fields), "fields_list": list(fields),
                      "limit": size, "offset": offset}
            from .servicenow import ServiceNowError
            try:
                page = _records(self.client.call_tool(tool, _template(template, values)), self.settings.get("records_path"))
            except McpError as exc:
                raise ServiceNowError(str(exc)) from None
            yield from page
            if len(page) < size:
                return
            offset += size
            if offset > 500000:
                raise ServiceNowError("MCP sayfalama sınırı aşıldı")


DEFAULT_SETTINGS = {
    "tool": "query_table",
    "arguments": {"table_name": "{table}", "query": "{query}", "fields": "{fields}", "limit": "{limit}",
                  "offset": "{offset}", "display_value": "all"},
    "records_path": "",
    "page_size": 200,
}
