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
        self.context = ssl.create_default_context(cafile=ca_file) if self.instance.startswith("https://") else None
        self.timeout, self.retries, self.sleep = timeout, retries, sleep
        self.requests = 0

    def _get(self, path, params):
        url = f"{self.instance}{path}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": self.auth,
                                                       "User-Agent": "grc-platform-cmdb/1"})
        attempt = 0
        while True:
            attempt += 1
            self.requests += 1
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise ServiceNowError(f"ServiceNow erişimi reddedildi ({exc.code}); hesap ve tablo yetkisini "
                                          "denetleyin") from None
                if exc.code in (429, 500, 502, 503, 504) and attempt <= self.retries:
                    wait = exc.headers.get("Retry-After") if exc.headers else None
                    self.sleep(min(float(wait), 60) if wait and wait.isdigit() else 2 ** attempt)
                    continue
                raise ServiceNowError(f"ServiceNow isteği başarısız ({exc.code}): {path}") from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempt <= self.retries:
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
