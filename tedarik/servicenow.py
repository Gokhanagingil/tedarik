"""ServiceNow Table API istemcisi (salt okur). K-019.

- Yalnızca GET: `/api/now/table/<tablo>`; portal ServiceNow'a hiçbir zaman yazmaz.
- Kimlik: temel kimlik doğrulama (kullanıcı + parola dosyası) veya taşıyıcı belirteç dosyası. Gizli değer dosyadan
  okunur, günlüğe ve hata iletisine yazılmaz.
- `sysparm_display_value=all`: her alan {"value", "display_value"} döner; tarih ve seçim kodu `value`dan, başvuru
  adı (şirket, sahip) `display_value`dan okunur. Tarih biçimi kullanıcı profilinden bağımsızdır.
- Sayfalama `sysparm_limit` / `sysparm_offset`; artımlı okuma `sys_updated_on>=<filigran>^ORDERBYsys_updated_on`.
- 429 ve 5xx yanıtları `Retry-After` gözetilerek en çok 3 kez yeniden denenir; ağ hatası da yeniden denenir.
"""
import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_PAGES = 2000


class ServiceNowError(Exception):
    """Bağlantı, kimlik veya yanıt hatası. İleti gizli bilgi içermez."""


MAX_RESPONSE = 64 * 1024 * 1024     # tek sayfa en çok 64 MB


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Yönlendirme izlenmez: urllib yönlendirmede Authorization başlığını yeni adrese de gönderir."""
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    def __init__(self, instance, user=None, password=None, token=None, ca_file=None, timeout=30, retries=3,
                 sleep=time.sleep):
        self.instance = instance.rstrip("/")
        if token:
            self.auth = "Bearer " + token
        elif user and password:
            self.auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        else:
            raise ServiceNowError("ServiceNow kimlik bilgisi eksik (kullanıcı ve parola veya belirteç)")
        if not self.instance.startswith(("https://", "http://")):
            raise ServiceNowError("ServiceNow adresi https:// ile başlamalı")
        self.context = ssl.create_default_context(cafile=ca_file) if self.instance.startswith("https://") else None
        handlers = [_NoRedirect()] + ([urllib.request.HTTPSHandler(context=self.context)] if self.context else [])
        self.opener = urllib.request.build_opener(*handlers)
        self.timeout, self.retries, self.sleep = timeout, retries, sleep
        self.requests = 0

    def create(self, table, payload):
        """Tek kayıt oluşturur (yalnızca GRC görev eşlemesi, K-027; CMDB'ye yazılmaz). Dönüş: kayıt alanları."""
        if not table.replace("_", "").isalnum():
            raise ServiceNowError("Geçersiz tablo adı")
        return self._get(f"/api/now/table/{table}", {"sysparm_display_value": "false"}, body=payload).get("result", {})

    def record(self, table, sys_id, fields):
        if not table.replace("_", "").isalnum() or not sys_id.isalnum():
            raise ServiceNowError("Geçersiz tablo veya kayıt kimliği")
        return self._get(f"/api/now/table/{table}/{sys_id}", {"sysparm_fields": ",".join(fields),
                                                                "sysparm_display_value": "all"}).get("result", {})

    def _get(self, path, params, body=None):
        url = f"{self.instance}{path}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json", "Authorization": self.auth, "User-Agent": "grc-platform-cmdb/1"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, headers=headers, method="POST" if body is not None else "GET",
                                         data=json.dumps(body).encode("utf-8") if body is not None else None)
        attempt = 0
        while True:
            attempt += 1
            self.requests += 1
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    raw = response.read(MAX_RESPONSE + 1)
                    if len(raw) > MAX_RESPONSE:
                        raise ServiceNowError("ServiceNow yanıtı çok büyük; sayfa boyutunu küçültün")
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code in (401, 403):
                    raise ServiceNowError(f"ServiceNow erişimi reddedildi ({exc.code}); hesap ve tablo yetkisini "
                                          "denetleyin") from None
                if exc.code in (429, 500, 502, 503, 504) and attempt <= self.retries and body is None:
                    wait = exc.headers.get("Retry-After") if exc.headers else None
                    self.sleep(min(float(wait), 60) if wait and wait.isdigit() else 2 ** attempt)
                    continue
                raise ServiceNowError(f"ServiceNow isteği başarısız ({exc.code}): {path}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt <= self.retries and body is None:      # yazma isteği tekrarlanmaz (çift kayıt olmasın)
                    self.sleep(2 ** attempt)
                    continue
                raise ServiceNowError(f"ServiceNow'a bağlanılamadı: {type(exc).__name__}") from None
            except ValueError:
                raise ServiceNowError("ServiceNow yanıtı JSON değil") from None

    def table(self, table, fields, query="", watermark=None, page_size=500):
        """Tablonun kayıtlarını sayfa sayfa üretir. Her kayıt {alan: {"value", "display_value"}}."""
        parts = [query] if query else []
        if watermark:
            parts.append(f"sys_updated_on>={watermark}")
        parts.append("ORDERBYsys_updated_on")
        offset = 0
        for _ in range(MAX_PAGES):
            payload = self._get(f"/api/now/table/{urllib.parse.quote(table)}", {
                "sysparm_query": "^".join(parts), "sysparm_fields": ",".join(sorted(set(fields))),
                "sysparm_display_value": "all", "sysparm_exclude_reference_link": "true",
                "sysparm_limit": page_size, "sysparm_offset": offset})
            rows = payload.get("result")
            if not isinstance(rows, list):
                raise ServiceNowError(f"Beklenmeyen yanıt: {table}")
            yield from rows
            if len(rows) < page_size:
                return
            offset += page_size
        raise ServiceNowError(f"{table}: sayfa sınırı aşıldı ({MAX_PAGES})")


def value(record, field):
    """Alanın ham değeri (sys_id, seçim kodu, UTC tarih)."""
    item = record.get(field)
    if isinstance(item, dict):
        item = item.get("value")
    return item if item not in ("", None) else None


def display(record, field):
    """Alanın görünen değeri (başvurunun adı, seçimin etiketi)."""
    item = record.get(field)
    if isinstance(item, dict):
        item = item.get("display_value") or item.get("value")
    return item if item not in ("", None) else None
