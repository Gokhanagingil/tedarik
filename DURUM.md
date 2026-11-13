# Durum

Son güncelleme: 2026-11-13 · Aşama: KS GRC uyumu doğrulandı, PostgreSQL temeli kuruldu; sıradaki iş kimlik aktarımı.
Bu dosya her çalışma oturumunun sonunda güncellenir: kararlar, yapılanlar, sıradaki adımlar.

## Kararlar (özet)

Ayrıntı `docs/KARARLAR.md` içinde.

- KS GRC (`control` reposu) ile aynı kurallar: Python 3.12, web çatısı yok, derlemesiz istemci (K-001).
- Veritabanı: üretimde PostgreSQL, geliştirme ve testte SQLite; kod iki motorda çalışır (K-011, 2026-11-13).
- Tedarikçi ve Angajman ayrı kayıtlar.
- Tablolar `tdr_` önekli, uç noktalar `/api/tdr` altında. İstisna: kimlik tabloları KS GRC ile ortak (K-013).
- Entra rol değerleri `KS.TDR.*`; `entra_auth.py` kopyasına tek, belgelenmiş yama (K-012).
- Süreçler veri olarak tanımlı; kaynak bulma modülü hazır ama kapalı.
- Entegrasyon: MCP uygulaması REST API'ye yazar.

## Varsayımlar (Gökhan Bey'in onayıyla)

- Hedef ortam KS GRC'nin kurumsal profiliyle aynı: Docker, TLS sonlandıran ters vekil, tek kiracılı Entra.
- Portalı yalnızca iç kullanıcılar kullanır; anketleri iç kullanıcılar yanıtlar.
- Tek şirket (tek kiracı).
- SAP ve Dynamics sütun başlıkları tahminidir (`transfer.py` içindeki `ALIASES`).
- Başlangıç tedarikçi tipleri ve değerlendirme kriterleri öneridir.

## Yapılanlar

- Temel katman: yapılandırma, şema kaydı, veritabanı, ortak kayıt işlemleri, yönlendirici, güvenlik başlıkları, köken denetimi, tekrar koruması, denetim izi.
- Yetki: beş rol, en az yetkili MCP anahtarı. Anonim erişim açılmaz.
- Modüller: `core`, `performance`, `surveys`, `risks`, `transfer`, `dashboard` (açık); `workflow`, `sourcing` (kapalı).
- **Adım 1 (2026-11-13): KS GRC tam incelendi** (commit `7720f4b`). `docs/UYUM_SOZLESMESI.md` içindeki "Doğrulanacak" satırları kapatıldı. Düzeltilen farklar:
  - Tekrar koruması: anahtar biçimi `[A-Za-z0-9_.:-]{8,160}`, kanonik JSON özeti, alındı okunmadan önce yazma kilidi (eşzamanlı 8 tekrar tek kayıt üretir).
  - Denetim izi: KS GRC `activity_log` sütun adları (`occurred_at`, `method`, `object_type`, `object_id`, `description`); gizli alanlar maskelenir; anket yanıtı artık iz bırakıyor.
  - Risk: KS GRC alan adları ve kodları (`in_treatment`, `response_strategy`, `review_date`), risk ifadesi (neden, olay, etki), olasılık ve etki risk kaydında, değerlendirme anlık görüntüsü ve o anki iştah, ayrı ve değişmez `risk_decisions` tablosu, değişen riskte yeniden değerlendirme, yeniden açma kuralları, açık faaliyetle kapanış yasağı, iştah üstü kabulü yalnızca farklı bir Yönetici. Faaliyetler KS GRC `actions` yapısında.
  - Hata yanıtı: beklenmeyen hata ve SQL hatası 500 ile, ayrıntı sızdırılmadan.
  - `/api/health` kimlik ister (KS GRC gibi). Birden fazla `Origin` başlığı reddedilir.
- **Adım 2 (2026-11-13): Veritabanı temeli, PostgreSQL** (K-011).
  - `db.py`: motor bağımsız katman. PostgreSQL için bağlantı havuzu (`psycopg-pool`), UTC oturum saati, 30 saniye sorgu sınırı, isteğe bağlı şema (`TEDARIK_DB_SCHEMA`); `?` parametre çevirisi, `RETURNING id` ile eklenen kimlik, danışma kilidi (`db.lock`), ortak hata türleri, iki motorda aynı JSON çıktısı.
  - `schema.py`: tipli alanlar (`DATE`, `TIMESTAMP`, `DECIMAL`); PostgreSQL'de yerel tipler (DATE, TIMESTAMPTZ, NUMERIC(18,2), BIGINT kimlik), SQLite'ta KS GRC ile aynı tipler. Yabancı anahtar dizinleri kendiliğinden.
  - `migrate.py`: bildirimsel eşitleme + sürümlü göç kaydı (`tdr_schema_migrations`), açılış kilit altında, bağımlılık sırasıyla tablo açma; değişmez tablolarda iki motorda tetikleyici; KS GRC ile ortak kimlik tabloları (K-013).
  - Tüm tarih ve zaman alanları doğrulanır, zamanlar UTC'ye çevrilir. SQLite'a özgü SQL kaldırıldı.
  - Türkçe arama düzeltildi: `Örnek`, `ÖRNEK`, `ornek` aynı sonucu verir (önceden ASCII dışı büyük harfle başlayan arama iki motorda da boş dönüyordu). `%` ve `_` artık joker sayılmıyor.
  - `requirements.txt`: psycopg 3.3.9, psycopg-binary 3.3.9, psycopg-pool 3.3.3, typing-extensions 4.16.0; hash ile sabit, temiz ortamda doğrulandı.
  - CI: SQLite (ek paketsiz) ve PostgreSQL 16 matrisi.
- Testler: 30 uçtan uca test; SQLite'ta ve PostgreSQL 16'da tamamı geçiyor.
- Belgeler: `docs/MIMARI.md`, `docs/VERI_MODELI.md`, `docs/UYUM_SOZLESMESI.md`, `docs/KARARLAR.md`.

## Bilinen eksikler

- **Arayüz yok.** Yalnızca API ve yer tutucu sayfa var.
- **Oturum sağlayıcısı yok.** Yalnızca yerel `dev` modu ve MCP anahtarı çalışır; `local` ve `entra` modları açılışta durur.
- **CI'daki PostgreSQL imajı özetle sabit değil** (adım 6'da sabitlenecek).
- **PostgreSQL yedekleme ve geri yükleme yok** (adım 6).
- **XLSX yok.** İçe ve dışa aktarma şimdilik CSV (UTF-8, `;` ayraçlı; Excel doğrudan açar).
- **İçe aktarma yalnızca tedarikçi ana verisi için.** Angajman, katalog, sözleşme aktarımları yok.
- **Birim bazlı yazma kapsamı yok.** Birim Kullanıcısı tüm angajmanları değiştirebilir.
- **Dağıtım dosyaları yok** (Dockerfile, compose, yedekleme).
- **Periyodik işler yok** (gözden geçirme hatırlatmaları, kampanya takvimi).
- **Türkçe alan etiketleri yok** (KS GRC `/api/metadata` karşılığı).

## Sıradaki adımlar (sırayla)

1. ~~**KS GRC'yi tam oku ve uyumu doğrula.**~~ Tamamlandı (2026-11-13).
2. ~~**Veritabanı temeli: PostgreSQL** (K-011).~~ Tamamlandı (2026-11-13).
3. **Kimlik aktarımı.** `identity.py` ve `entra_auth.py` dosyalarını `tedarik/vendor/` altına al (K-012, K-013); `local` ve `entra` modlarını aç; rolleri Entra uygulama rollerine bağla; birim bazlı yazma kapsamını ekle; giriş hız sınırı; `/api/me`.
4. **Excel.** `xlsx_io.py` aktarımı; XLSX içe ve dışa aktarma; Türkçe alan etiketleri (`/api/tdr/metadata`); uygulamanın kendi ürettiği içe aktarma şablonu; angajman, katalog ve sözleşme aktarımları; gerçek başlıklarla `ALIASES` doğrulaması.
5. **Arayüz.** KS GRC'nin görsel diliyle (`ui_v2.py` + `ksgrc.js` düzeni): tedarikçi listesi ve filtreler, tedarikçi 360 paneli, angajman, performans, anket, risk ekranları, pano (satır içi SVG grafikler). Her ekran için Playwright duman testi.
6. **Dağıtım.** KS GRC'nin Dockerfile, compose ve yedekleme düzenini PostgreSQL ile uyarla (`pg_dump` tabanlı yedek, geri yükleme denetimi); CI'a gitleaks, trivy, bandit, pip-audit ekle.
7. **Periyodik işler.** Kritiklik seviyesine göre değerlendirme, anket ve risk gözden geçirme takvimi; geciken işler panosu.
8. **MCP sözleşmesi.** `docs/MCP_SOZLESMESI.md`; KS GRC'ye kanıt akışı için örnek otomatik kontroller.
9. **Kaynak bulma.** Süreç tasarımı onaylanınca `workflow,sourcing` modüllerini aç, ekranlarını yap.

## Gökhan Bey'den beklenenler

- SAP, Dynamics ve dış kaynak yönetim sisteminden örnek dışa aktarım (sütun başlıkları yeterli).
- Tedarikçi tipleri ve iş birimleri listesi.
- Yeni rollerin (`KS.TDR.*`) KS GRC'nin Entra uygulama kaydına mı, ayrı bir kayda mı ekleneceği.
- `tedarik` ve `control` repolarının görünürlüğü (şu an ikisi de herkese açık).
- Üretim PostgreSQL'inin nerede çalışacağı: kurumun yönetilen PostgreSQL hizmeti mi, aynı sunucuda konteyner mi; sürüm (öneri 16 veya üzeri) ve yedekleme sorumlusu.
