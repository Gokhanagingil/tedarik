# KS GRC ile Uyum Sözleşmesi

Amaç: `tedarik` ile `control` (KS GRC) ileride birleşebilsin veya tek uygulama gibi davranabilsin.

**İnceleme:** KS GRC `main`, commit `7720f4b095a067dbf810dbc1cd25937d88a2ee5f` (2026-11-13). Depodaki tüm dosyalar okundu: `app.py`, `grc_plus.py`, `risk_management.py`, `execution_service.py`, `identity.py`, `entra_auth.py`, `xlsx_io.py`, `grc_excel.py`, `ui.py`, `ui_v2.py`, `ksgrc.js`, `backup.py`, `bootstrap.py`, `seed_*.py`, `Dockerfile`, `compose.yaml`, `compose.enterprise.yaml`, `enterprise/`, `.github/workflows/`, `scripts/`, `tests/`, `docs/`. Daha önce "Doğrulanacak" olan satırların hepsi kapatıldı. Durum sütunu: **Uygulandı** (aynı davranış, testli), **Bilinçli fark** (gerekçesi aşağıda), **Sonraki adım** (DURUM.md'deki adım numarasıyla).

| Konu | KS GRC (kaynak) | Tedarik | Durum |
| --- | --- | --- | --- |
| Dil ve çalışma zamanı | Python 3.12, `ThreadingHTTPServer`, web çatısı yok (`app.py`) | Aynı | Uygulandı |
| Veritabanı | SQLite, WAL, `foreign_keys=ON`, `busy_timeout=15000` (`app.connect`) | SQLite'ta aynı ayarlar; üretimde PostgreSQL (K-011). Test takımı iki motorda | Uygulandı; PostgreSQL bilinçli fark (K-011) |
| Bağımlılıklar | `requirements.txt`: PyJWT 2.15.1, cryptography 50.0.2, cffi 2.1.1, pycparser 3.12, defusedxml 0.7.1; hash ile sabit, `--only-binary`, Linux CPython 3.12 amd64/arm64 | Kimlik paketleri KS GRC ile aynı satırlar; ek olarak psycopg 3.3.9, psycopg-binary 3.3.9, psycopg-pool 3.3.3, typing-extensions 4.16.0. Temiz ortamda `--require-hashes` ile doğrulandı. defusedxml adım 4'te | Kısmen; kalanı adım 4 |
| Tablo tanımı | `TABLES` ve `grc_plus.SCHEMA` sözlükleri, açılışta `ALTER TABLE ADD COLUMN` | `Resource` kaydı, aynı eklemeli evrim; ek olarak sürümlü göç kaydı (`tdr_schema_migrations`) ve tipli alanlar (DATE, TIMESTAMP, DECIMAL) | Uygulandı |
| Kimlikler | Tamsayı `id`; `code` (tekil), `name`/`title` | Aynı | Uygulandı |
| Tablo adları | Öneksiz (`controls`, `risks`, `activity_log`, ...) | `tdr_` önekli. İstisna: kimlik tabloları (`users`, `auth_sessions`, `entra_subjects`) KS GRC ile aynı ad ve yapıda (K-013) | Uygulandı |
| API kalıbı | `/api/<kaynak>`, `/api/<kaynak>/<id>/context` | `/api/tdr/<kaynak>`, `.../context` | Uygulandı |
| Silme | Uç nokta yok; durum alanıyla kapatma | Aynı | Uygulandı |
| Hata biçimi | `{"error": "..."}`, Türkçe; beklenmeyen hata `500 Beklenmeyen işlem hatası`, ayrıntı sızdırılmaz (`grc_plus._error`) | Aynı; SQL hatası ayrıntısı artık 500 ile gizlenir | Uygulandı (bu adımda düzeltildi) |
| Sağlık uç noktası | `/api/health` kimlik ister; anonim 401 (Dockerfile sağlık denetimi 401'i "ayakta" sayar) | Aynı | Uygulandı (bu adımda düzeltildi) |
| Makine erişimi | `X-API-Key`, `hmac.compare_digest`, en az yetki; kurumsal profilde en az 32 karakter | Aynı; 32 karakter her profilde | Uygulandı |
| MCP yazma kuralı | Yalnızca `source=mcp`, yalnızca izinli uç noktalar; dışa aktarım ve kullanıcı yönetimi yok | Aynı (SLA ölçümü, performans olayı) | Uygulandı |
| Tekrar koruması | Gövdede `idempotency_key`, `^[A-Za-z0-9_.:-]{8,160}$`; kanonik JSON'un SHA-256'sı; alındı okunmadan önce `BEGIN IMMEDIATE`; ilk yanıt 201, tekrar 200 + `replayed: true`, farklı içerik 409 (`execution_service.record`) | Aynı biçim, aynı kanonik JSON, aynı kilit; tüm POST uç noktalarında | Uygulandı (bu adımda düzeltildi: biçim, kilit, eşzamanlılık testi) |
| Güvenlik başlıkları | `nosniff`, `no-store`, `DENY`, `no-referrer`, Permissions-Policy; HSTS yalnızca güvenli çerezde | Aynı | Uygulandı |
| İçerik güvenlik politikası | `default-src 'none'`; satır içi blokların SHA-256 özeti; arayüz betiği ayrı dosya (`/ksgrc.js`, `script-src 'self'`) | Aynı başlık; arayüz de ayrı dosyayla gelecek | Uygulandı; arayüz: adım 5 |
| Köken denetimi | Oturumlu değişiklikte tek `Origin` başlığı zorunlu ve eşleşmeli; Entra'da beklenen köken yönlendirme adresinden gelir ve `Host` aynı olmalı | Aynı | Uygulandı |
| Günlükleme | Sorgu dizgisi yazılmaz (`log_request`) | Aynı | Uygulandı |
| Yerel kullanıcı ve oturum | PBKDF2-SHA256 600.000 tur, 12 saatlik HttpOnly `SameSite=Strict` çerez, ilk girişte parola değişimi, 5 dakikada 8 hatalı denemeden sonra 429 (`identity.py`, `app.handle_login`) | `identity.py` kopyası değiştirilmeden; aynı akış, aynı sınır; `bootstrap` komutu | Uygulandı |
| Kurumsal giriş | Tek kiracılı Entra, PKCE, `acrs` kimlik doğrulama bağlamı zorunlu, uygulama rolleri; oturum en fazla 1 saat (`entra_auth.py`) | `entra_auth.py` kopyası (K-012 yaması); aynı doğrulamalar; kurumsal modda parola yolları ve kullanıcı açma 403 | Uygulandı |
| Çerez adları | `control_grc_session`, `__Host-ksgrc_session`, `__Host-ksgrc_flow` | `tedarik_session`, `__Host-tdr_session`, `__Host-tdr_flow` (aynı alan adında KS GRC oturumunu ezmemek için) | Bilinçli fark; uygulandı |
| Roller | Veritabanında ADMIN, AUDITOR, VIEWER (uygulanmıyor). Entra uygulama rolleri `KS.GRC.Admin`, `KS.GRC.Auditor`. **KS GRC denetçisi kayıt yazar**; yönetim ve Excel yalnızca Admin | Beş rol; tedarik denetçisi salt okur. Entra rol değerleri `KS.TDR.Admin`, `KS.TDR.SupplierManager`, `KS.TDR.UnitUser`, `KS.TDR.Auditor`, `KS.TDR.Viewer` (K-012); birden çok rolde en yetkilisi. `KS.GRC.*` rolleri tedarikte yetki vermez. Yerel modda rol `tdr_user_roles` | Uygulandı |
| Rol eşlemesi kodu | `entra_auth.verify` iki rolü sabit kodlar; başka rol taşıyan token reddedilir | Kopya dosyada 3 satırlık işaretli yama (`tedarik/vendor/PATCHES.md`); test kaynakla farkı denetler | Bilinçli fark; uygulandı |
| Risk puanlama | 1-5 × 1-5, iştah 1-25, katkı %20/%40/%60, kısmi yarım, toplam en çok %100, `Decimal` ile hesap (`risk_management.assess`) | Aynı, `Decimal` ile | Uygulandı |
| Risk ifadesi | `cause`, `risk_event`, `consequence`, `owner`, `entity_name`; olasılık ve etki risk kaydında | Aynı alanlar; etkilenen varlık `supplier_id` ve `engagement_id` | Uygulandı (bu adımda eklendi) |
| Risk durumu ve strateji | `status`: open, in_treatment, accepted, closed; `response_strategy`: mitigate, avoid, transfer, accept; `review_date` | Aynı kodlar ve alan adları | Uygulandı (bu adımda düzeltildi: `treating`, `strategy`, `review_due`) |
| Risk değerlendirmesi | `risk_assessments(assessed_at, assessor, rationale, inherent, residual, appetite, snapshot)`; değiştirilemez | `tdr_risk_assessments`, aynı alanlar ve `mitigation_pct`; güncelleme uç noktası yok | Uygulandı (bu adımda düzeltildi: iştah ve anlık görüntü saklanıyor) |
| Risk kararı | `risk_decisions` ayrı ve değiştirilemez; kabul ve kapanışta güncel değerlendirme kimliği ve gerekçe; değerlendirmeden sonra değişen risk veya iştah reddedilir; kabulde strateji `accept` ve ileri tarihli gözden geçirme; açık faaliyetle kapanış yok; yeniden açmada yalnızca gerekçe ve yeni değerlendirme; iştah üstü kabulü farklı Admin ayrı istisna gerekçesiyle onaylar | `tdr_risk_decisions` ve aynı kurallar. Fark: yerel modda da "farklı kişi" kuralı geçerli; yalnızca `dev` modunda esnetilir | Uygulandı (bu adımda düzeltildi; önceki iskelette eksikti) |
| Risk faaliyetleri | `actions`: code, title, owner, due_date, priority, status (open, in_progress, validation, completed, cancelled), resolution, closed_at; kapalı veya kabul edilmiş riske bağlanamaz (tetikleyici) | `tdr_risk_actions` aynı alanlar ve kural (`before_save`) | Uygulandı (bu adımda düzeltildi) |
| KS GRC risk bağlantısı | Risk kodu tekil (`grc_plus.post`); Excel aktarımı kimlik yerine kodla bağlar (`RISK_REFERENCE_CODES`) | `control_risk_ref` alanı KS GRC `risks.code` değerini taşır | Doğrulandı |
| Denetim izi | `activity_log(actor, method, object_type, object_id, description, occurred_at)`; açıklama 600 karakter; makine için `mcp` | `tdr_audit_log` aynı sütun adları, ek `auth_type` ve `changes_json`; gizli alanlar maskelenir | Uygulandı (bu adımda düzeltildi: sütun adları, maskeleme, anket yanıtında eksik kayıt) |
| Değiştirilemez geçmiş | Risk değerlendirme ve kararlarında veritabanı tetikleyicisi | İki motorda tetikleyici: denetim izi, tekrar koruması, risk değerlendirme ve kararları, iş akışı geçmişi, aktarım satırları, anket yanıtları | Uygulandı |
| Tarih doğrulama | `date.fromisoformat` ve gidiş-dönüş eşitliği; saat dilimli ISO 8601 | Aynı kural tüm `DATE` ve `TIMESTAMP` alanlarında; zaman UTC'ye çevrilir. Fark: yalnızca tarih verilen zaman alanı gece yarısı UTC sayılır | Uygulandı |
| Meta veri | `/api/metadata`: Türkçe alan etiketleri ve seçim etiketleri; arayüz ve Excel başlıkları buradan | Yok | Sonraki adım: 4 ve 5 |
| Excel | Kendi XLSX okuyucu/yazıcısı (`xlsx_io.py`, defusedxml, formül ve makro reddi, 12 MB, 5.000 satır, 60 sütun); Türkçe sayfa ve başlık; kodla ilişki (`grc_excel.py`) | CSV (UTF-8, `;`) | Sonraki adım: 4 |
| Arayüz | `ui_v2.py` kabuk + `ksgrc.js`: koyu kenar menü (244 px), sağda boyutlandırılabilir detay paneli (540 px), kartlar, CSS halka göstergeler, rozetler, `MENU`/`COLUMNS`/`FORM` tabloları | Yer tutucu sayfa | Sonraki adım: 5 |
| Ortam değişkenleri | `CONTROL_*`; `CONTROL_AUTH_MODE` varsayılanı `local` | `TEDARIK_*`; kimlik modu zorunlu, varsayılan yok | Bilinçli fark (daha sıkı) |
| Dağıtım | `python:3.12-alpine` özetle sabit, UID 10001, salt okunur kök, `cap_drop: ALL`, `no-new-privileges`, tmpfs, `127.0.0.1:18080`; kurumsal compose'da dosya tabanlı sırlar, `pids_limit`, `mem_limit`; nginx örneği; `backup.py` | Yok; tedarik `127.0.0.1:18090` kullanacak | Sonraki adım: 6 |
| Testler | `unittest` (77 test), Playwright 1.57.0 duman testi, gitleaks 8.30.1, trivy 0.76.2, bandit, pip-audit, ZAP DAST | `unittest` (45 test, SQLite ve PostgreSQL'de) | Kısmen; adım 5 ve 6 |
| MCP sözleşmesi | `docs/MCP_CONTRACT_AND_ACCEPTANCE.md`: katalog okuma, kanıt yükleme, sonuç yazma, provenance, `collection_status` | Tedarik sözleşmesi yazılacak | Sonraki adım: 8 |

## Aktarım kuralı

KS GRC modülleri yeniden yazılmaz. `tedarik/vendor/` altına aynen kopyalanır, dosya başına kaynak commit kimliği yazılır. Gerekli uyarlama ince bir sarmalayıcıda yapılır, kopyalanan dosya değiştirilmez. Birleşme günü `vendor` klasörü silinir, içe aktarmalar KS GRC'nin kendi modüllerine döner.

İnceleme sonucu aktarılabilirlik:

| Dosya | Aynen kopyalanabilir mi | Not |
| --- | --- | --- |
| `xlsx_io.py` | Evet | Yalnızca `defusedxml` ister; veritabanına dokunmaz |
| `identity.py` | Evet, sarmalayıcıyla (aktarıldı) | Çerez adları modül değişkeni (sarmalayıcı değiştirir). SQL'i SQLite'a özgü (`PRAGMA`, `?`, `lastrowid`); PostgreSQL'de veritabanı katmanının uyum bağlantısıyla çalışır. Giriş sayfaları KS GRC adını taşır; tedarik kendi sayfalarını sunar |
| `entra_auth.py` | Küçük yamayla (aktarıldı) | Rol listesi ve `CONTROL_*` adları sabit. `configure()` ortam sözlüğü aldığı için ad çevirisi sarmalayıcıda yapılır; rol listesi için yama gerekir (K-012) |
| `backup.py` | Hayır | Tablo adları (`audits`, `controls`, `evidence`) ve `control.db` sabit; düzen örnek alınır |
| `grc_excel.py`, `grc_plus.py`, `risk_management.py`, `execution_service.py` | Hayır | `app` modülüne ve KS GRC tablolarına bağlı; kurallar karşılık olarak uygulanır |

## Bilinçli farklar

- **Ad alanı:** KS GRC `/api/risks`, `risks`, `actions` adlarını kullanıyor (doğrulandı). Tedarik uç noktaları `/api/tdr` altında; risk kaynağı `supplier_risks`, faaliyetler `risk_actions`.
- **Modül yapısı:** KS GRC tek `Handler` ve kanca modülleriyle büyümüş. Tedarik portalı tüm iş birimlerine açılacağı için baştan yönlendirici ve modül kaydı kullanıyor. Davranış sözleşmesi aynı.
- **Denetçi rolü:** KS GRC'de denetçi GRC kayıtlarını değiştirir; tedarikte denetçi salt okur (iç denetim bağımsızlığı). Aynı kişiye iki uygulamada farklı roller atanabilir.
- **Tekrar koruması kapsamı:** KS GRC yalnızca kontrol sonucu yazımında uygular; tedarik tüm POST uç noktalarında uygular. Biçim ve davranış aynı.
- **Risk kabulünde aynı kişi:** KS GRC yerel pilotta aynı kişiye izin verir; tedarik yalnızca `dev` modunda izin verir.

## KS GRC'ye öneriler

Birleşmeyi kolaylaştıracak, KS GRC'de geriye uyumlu küçük değişiklikler. Tedarik tarafı bunları beklemeden çalışır.

1. `entra_auth.py`: kabul edilen rol listesini modül değişkenine taşımak (`ROLES = (ADMIN, AUDITOR)`) ve `verify` dönüşünde listedeki ilk eşleşen rolü vermek. Tedarik yaması tam olarak budur (K-012).
2. `identity.py`: giriş, parola ve Entra HTML sayfalarını ayrı modüle almak; böylece dosya ürün adından bağımsız olur.
3. `activity_log` tablosuna `auth_type` sütunu: insan ve makine kayıtlarının ayrımı için.
