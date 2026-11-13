# KS GRC ile Uyum Sözleşmesi

Amaç: `tedarik` ile `control` (KS GRC) ileride birleşebilsin veya tek uygulama gibi davranabilsin.

İncelenen KS GRC dosyaları: `README.md`, `app.py`, `requirements.txt`, `docs/DENETIM_VE_RISK.md`.
**Henüz okunmayanlar:** `grc_plus.py`, `risk_management.py`, `identity.py`, `entra_auth.py`, `xlsx_io.py`, `grc_excel.py`, `execution_service.py`, `ui_v2.py`, `ksgrc.js`, `docs/MCP_CONTRACT_AND_ACCEPTANCE.md`, `enterprise/`, `Dockerfile`, compose dosyaları. Aşağıda "Doğrulanacak" yazan satırlar bunlara bağlıdır.

| Konu | KS GRC | Tedarik | Durum |
| --- | --- | --- | --- |
| Dil ve çalışma zamanı | Python 3.12, standart kütüphane HTTP sunucusu, web çatısı yok | Aynı | Uygulandı |
| Veritabanı | SQLite, WAL, `foreign_keys`, `busy_timeout=15000` | Aynı | Uygulandı |
| Bağımlılıklar | Hash ile sabitlenmiş birkaç paket (PyJWT, cryptography, defusedxml) | Şu an sıfır; kimlik ve XLSX aktarımıyla aynı paketler gelecek | Sonraki adım |
| Tablo tanımı | `TABLES` sözlüğü | `Resource` kaydı (aynı fikir, modül bazlı) | Uygulandı |
| Kimlikler | Tamsayı `id`, `code`, `name` | Aynı | Uygulandı |
| Tablo adları | Öneksiz (`controls`, `audits`, ...) | `tdr_` önekli | Uygulandı |
| API kalıbı | `/api/<kaynak>`, `/api/<kaynak>/<id>/context` | `/api/tdr/<kaynak>`, `.../context` | Uygulandı |
| Silme | Yok; durum alanıyla kapatma | Aynı | Uygulandı |
| Hata biçimi | `{"error": "..."}`, Türkçe ileti | Aynı | Uygulandı |
| Makine erişimi | `X-API-Key`, sabit zamanlı karşılaştırma, en az yetki; kurumsal profilde en az 32 karakter | Aynı; 32 karakter her profilde zorunlu | Uygulandı |
| MCP yazma kuralı | Yalnızca `source=mcp` ile, yalnızca izinli kaynağa | Aynı (SLA ölçümü, performans olayı) | Uygulandı |
| Tekrar koruması | `idempotency_key`; farklı içerik 409 | Aynı; tekrar 200 ve `replayed: true` | Uygulandı; alan adları doğrulanacak |
| Güvenlik başlıkları | `nosniff`, `no-store`, `DENY`, `no-referrer`, Permissions-Policy, HSTS | Aynı | Uygulandı |
| İçerik güvenlik politikası | `default-src 'none'`, satır içi blokların SHA-256 özeti | Aynı | Uygulandı |
| Köken denetimi | Oturumlu değişiklikte `Origin` zorunlu ve eşleşmeli | Aynı | Uygulandı |
| Günlükleme | Sorgu dizgisi yazılmaz | Aynı | Uygulandı |
| Yerel kullanıcı ve oturum | Parola özeti, HttpOnly oturum, ilk girişte parola değişimi | Dikiş hazır (`auth.py`); sağlayıcı yok | Sonraki adım: `identity.py` aktarımı |
| Kurumsal giriş | Tek kiracılı Entra, uygulama rolleri | Dikiş hazır | Sonraki adım: `entra_auth.py` aktarımı |
| Roller | ADMIN, AUDITOR, VIEWER | Aynı üçü + SUPPLIER_MANAGER, UNIT_USER | Uygulandı; Entra rol eşlemesi doğrulanacak |
| Risk puanlama | 1-5 × 1-5, iştah 1-25, katkı %20/%40/%60, kısmi yarım, artık = içsel × (1 − katkı) | Aynı | Uygulandı |
| Risk kararı | Kabul ve kapanışta değerlendirme ve gerekçe; iştah üstü kabulü farklı yönetici onaylar | Aynı | Uygulandı |
| Risk kayıtları | Kurumsal risk kaydı ve katalog (içinde tedarikçi şablonu) | Ayrı tablo, `control_risk_ref` ile bağlantı | Uygulandı; tablo ve alan adları doğrulanacak |
| Denetim izi | `grc_plus.log(db, handler, eylem, tablo, id)` | `audit.log(db, principal, eylem, kaynak, id, değişiklik)` | Uygulandı; tablo yapısı doğrulanacak |
| Excel | Çok sayfalı XLSX içe/dışa aktarma (`xlsx_io.py`) | CSV (UTF-8, `;` ayraçlı) | Sonraki adım: `xlsx_io.py` aktarımı |
| Arayüz | Derlemesiz istemci, sağ detay paneli, arama ve filtre | Yer tutucu sayfa | Sonraki adım |
| Ortam değişkenleri | `CONTROL_*` | `TEDARIK_*` (aynı adlandırma) | Uygulandı |
| Dağıtım | Dockerfile, compose, kurumsal profil, yedekleme betiği | Yok | Sonraki adım |
| Testler | `unittest`, Playwright duman testi, gitleaks | `unittest` (18 test) | Kısmen |

## Aktarım kuralı

KS GRC modülleri yeniden yazılmaz. `tedarik/vendor/` altına aynen kopyalanır, dosya başına kaynak commit kimliği yazılır. Gerekli uyarlama ince bir sarmalayıcıda yapılır, kopyalanan dosya değiştirilmez. Birleşme günü `vendor` klasörü silinir, içe aktarmalar KS GRC'nin kendi modüllerine döner.

## Bilinçli farklar

- **Ad alanı:** KS GRC `/api/risks` gibi adları kullanıyor olabilir. Çakışmayı önlemek için tedarik uç noktaları `/api/tdr` altında, risk kaynağı `supplier_risks` adında.
- **Modül yapısı:** KS GRC tek `Handler` ve kanca modülleriyle büyümüş. Tedarik portalı tüm iş birimlerine açılacağı için baştan yönlendirici ve modül kaydı kullanıyor. Davranış sözleşmesi aynı.
