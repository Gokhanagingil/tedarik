# Durum

Son güncelleme: 2026-11-13 · Aşama: uygulama ve dağıtım dosyaları hazır; sunucuya kurulum için GitHub'a SSH gizli değerleri bekleniyor.
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
- **Adım 3 (2026-11-13): Kimlik aktarımı.**
  - KS GRC `identity.py` (değiştirilmeden) ve `entra_auth.py` (K-012 yaması, 3 satır) `tedarik/vendor/` altında; test kaynakla farkı denetler. Uyarlama `session.py` içinde: çerez adları, ortam adları, rol listesi.
  - `local` modu: parola girişi, 5 dakikada 8 deneme sınırı, ilk girişte zorunlu parola değişimi, çıkış, `python -m tedarik.bootstrap create` ile ilk yönetici. Roller `tdr_user_roles` tablosunda.
  - `entra` modu: PKCE, MFA bağlamı, `KS.TDR.*` uygulama rolleri; kurumsal modda parola yolları ve kullanıcı açma kapalı; köken yapılandırılmış adresten.
  - Birim kapsamı: Birim Kullanıcısı yalnızca kendi biriminin angajmanına ve ona bağlı kayıtlara yazar (SLA, olay, değerlendirme, risk, faaliyet, ihtiyaç, teklif). Birimler `tdr_user_units`, yönetici atar.
  - `/api/me`, `/api/tdr/users` (liste, açma, güncelleme, devre dışı bırakma; devre dışı hesabın oturumu hemen kapanır). Anonim sayfa isteği `/login` sayfasına yönlenir.
  - Giriş ve parola sayfaları gerçek Chromium'da içerik güvenlik politikası altında denendi.
  - Belge: `docs/KIMLIK.md` (Entra kaydı, roller, davranış).
- **Adım 4 (2026-11-13): Excel.**
  - KS GRC `xlsx_io.py` değiştirilmeden kopyalandı; `defusedxml` aynı hashle.
  - Tek içe aktarma hattı XLSX ve CSV okur; Türkçe başlık ve seçim etiketi anlar; ilişkileri kodla çözer; GG.AA.YYYY ve Excel tarih sayısını tanır; her satır kendi geri alma noktasında (PostgreSQL'de hatalı satır işlemi bozmaz).
  - İçe aktarılabilenler: birimler, tedarikçi tipleri, ürün ve hizmetler, tedarikçiler (kaynak kimliği → kod → VKN → ad benzerliği), angajmanlar, sözleşmeler, SLA tanımları.
  - Uygulamanın ürettiği şablon: "Veri" sayfası (zorunlu sütunlar `*`) ve her sütunun izin verilen değerlerini anlatan "Açıklama" sayfası.
  - Dışa aktarım: kaynak bazında XLSX veya CSV, tüm portal tek çalışma kitabında; Türkçe başlık ve seçim, ilişkiler kodla; formül enjeksiyonu etkisizleştirilir.
  - `/api/tdr/metadata`: Türkçe alan ve seçim etiketleri, tipler, ilişkiler, kişinin yetkisi (arayüzün tek kaynağı). Her alanın etiketli olduğu testle denetlenir.
- **Adım 4a (2026-11-13): Anket motoru** (yeniden tasarlandı).
  - Üç kullanım: tedarikçi memnuniyeti, tedarikçi risk değerlendirmesi, bağımsız (tedarikçiden bağımsız) anketler.
  - Şablon: bölümler, 8 soru türü, ağırlık, seçenek puanı, koşullu gösterim, risk kategorisi ve eşiği; yayımlanınca donar, yeni sürüm kopyalanır; soru sırası tek istekte.
  - Kampanya: konu (yok / tedarikçi / angajman), katılım (davetli / herkes), anonimlik, tarih aralığı; toplu hedef (kritiklik seviyesiyle) ve toplu davet. Açılış şablonu dondurur.
  - Yanıt: "Anketlerim" listesi, taslak kaydetme, zorunlu ve koşullu soru denetimi, gönderilen yanıt değişmez.
  - Sonuç: yanıt oranı, genel, bölüm ve tedarikçi puanı, dağılımlar, NPS, metin yanıtları; anonimlikte en az yanıt eşiği; risk sinyalinden tek adımda tedarikçi riski; tedarikçi 360 için anket geçmişi.
  - İki örnek şablon taslak olarak gelir (öneridir, düzenlenebilir).
- **Adım 5 (2026-11-13): Arayüz.** KS GRC görsel diliyle (koyu kenar menü, aranabilir liste, sağda boyutlandırılabilir detay paneli), derlemesiz, dış kaynaksız, satır içi betik ve stil yok.
  - Genel bakış: göstergeler, "Dikkat gerektirenler" (tıklanınca filtreli liste), satır içi SVG grafikler.
  - Meta veriden üretilen liste, filtre, arama, sıralama, sayfalama, kayıt formu (alan bazında doğrulama ve sunucu hatası gösterimi), detay ve ilişkili kayıtlar; tüm kaynaklar için.
  - Tedarikçi 360: özet ve uyarılar, angajmanlar, son 12 ay göstergeleri, riskler, anket puanları, sözleşmeler, kişiler ve sorumluluklar.
  - Risk: puan kartları, değerlendirme penceresi (canlı artık risk hesabı), kabul, kapanış ve yeniden açma (iştah istisnası uyarısıyla), değerlendirme ve karar zaman çizelgesi.
  - Anket: şablon kurucu (bölüm, soru türü, seçenek puanı, koşul, risk eşiği, sıralama, kaldır/geri al, önizleme, yayımla, yeni sürüm), kampanya (değerlendirilenler, toplu davet, aç/kapat, sonuçlar, risk sinyalinden risk aç), Anketlerim ve yanıt formu (otomatik taslak kaydı, ilerleme, koşullu sorular, eksik soruya kaydırma).
  - Aktarım sihirbazı (tür → dosya → deneme → uygula, sürükle-bırak, şablon indirme), dışa aktarım, kullanıcı yönetimi (geçici parola bir kez gösterilir).
  - Klavye: `/` arama, `Esc` panel ve pencere kapatma, satırlarda Enter. Dar ekran düzeni.
  - `scripts/browser_smoke.py`: gerçek Chromium'da her ekran ve ana akışlar; konsol hatası kabul edilmez. CI'da ayrı iş.
- **Adım 6 (2026-11-13): Dağıtım.** `Dockerfile` (KS GRC düzeni), `deploy/compose.yaml` (PostgreSQL 16 iç ağda, uygulama yalnızca 127.0.0.1:18090, kaynak sınırları, salt okunur, root olmayan), `deploy/deploy.sh` (sırları sunucuda üretir, önce yedek, ilk yönetici, sağlık denetimi, diğer konteynerlerin değişmediğini doğrular), `deploy/backup.sh` (günlük pg_dump, özet, 14 gün), `.github/workflows/deploy.yml` (elle başlatılır, önce testler). Yan yana çalışan ilgisiz bir konteynerle prova edildi: kurulum, güncelleme, yedek, geri yükleme, Docker yeniden başlatması. Belge: `docs/DAGITIM.md`.
- Testler: 60 uçtan uca test; SQLite'ta ve PostgreSQL 16'da tamamı geçiyor. Birim kapsamı ve Entra rol eşlemesi testlerinin hatayı yakaladığı kasıtlı bozmayla doğrulandı.
- Belgeler: `docs/MIMARI.md`, `docs/VERI_MODELI.md`, `docs/UYUM_SOZLESMESI.md`, `docs/KARARLAR.md`.

## Bilinen eksikler

- **CI'daki PostgreSQL imajı özetle sabit değil** (adım 6'da sabitlenecek).
- **PostgreSQL yedekleme ve geri yükleme yok** (adım 6).
- **SAP ve Dynamics başlıkları hâlâ tahmin** (`transfer.py` `ALIASES`); gerçek dışa aktarım bekleniyor. Portalın kendi şablonu bu tahmine bağlı değildir.
- **Entra akışı gerçek kiracıda denenmedi.** Testler sentetik token ve anahtarla; kurumsal kabul testleri KS GRC `docs/ENTRA_ID.md` tablosundaki gibi kiracıda yapılmalı.
- **Sunucuya henüz kurulmadı.** Bu çalışma ortamından sunucuya SSH kapalı; kurulum GitHub Actions ile yapılacak (gizli değerler eklenince).
- **Dışarıya erişim kararı bekleniyor** (alan adı ve TLS); şimdilik yalnızca SSH port yönlendirmesiyle erişilir.
- **CI güvenlik kapıları eksik** (gitleaks, trivy, bandit, pip-audit).
- **Periyodik işler yok** (gözden geçirme hatırlatmaları, kampanya takvimi).

## Sıradaki adımlar (sırayla)

1. ~~**KS GRC'yi tam oku ve uyumu doğrula.**~~ Tamamlandı (2026-11-13).
2. ~~**Veritabanı temeli: PostgreSQL** (K-011).~~ Tamamlandı (2026-11-13).
3. ~~**Kimlik aktarımı.**~~ Tamamlandı (2026-11-13).
4. ~~**Excel.**~~ Tamamlandı (2026-11-13). Kalan: gerçek SAP/Dynamics başlıklarıyla `ALIASES` doğrulaması.
4a. ~~**Anket motoru**~~ Tamamlandı (2026-11-13). Not: anket tabloları değişti; eski iskelet veritabanı varsa silinip yeniden açılmalı (üretim verisi yok).
5. ~~**Arayüz.**~~ Tamamlandı (2026-11-13).
6. ~~**Dağıtım.**~~ Tamamlandı (2026-11-13). Kalan: CI'a gitleaks, trivy, bandit, pip-audit; kalıcı alan adı ve TLS.
7. **Periyodik işler.** Kritiklik seviyesine göre değerlendirme, anket ve risk gözden geçirme takvimi; geciken işler panosu.
8. **MCP sözleşmesi.** `docs/MCP_SOZLESMESI.md`; KS GRC'ye kanıt akışı için örnek otomatik kontroller.
9. **Kaynak bulma.** Süreç tasarımı onaylanınca `workflow,sourcing` modüllerini aç, ekranlarını yap.

## Gökhan Bey'den beklenenler

- SAP, Dynamics ve dış kaynak yönetim sisteminden örnek dışa aktarım (sütun başlıkları yeterli).
- Tedarikçi tipleri ve iş birimleri listesi.
- Yeni rollerin (`KS.TDR.*`) KS GRC'nin Entra uygulama kaydına mı, ayrı bir kayda mı ekleneceği.
- `tedarik` ve `control` repolarının görünürlüğü (şu an ikisi de herkese açık).
- Sunucu (204.168.247.101) için GitHub'da `tedarik` ortamına SSH gizli değerleri (docs/DAGITIM.md) ve kalıcı erişim kararı (alan adı, TLS).
- Üretim PostgreSQL'inin nerede çalışacağı (şimdilik aynı sunucuda yalıtılmış konteyner): kurumun yönetilen PostgreSQL hizmeti mi, aynı sunucuda konteyner mi; sürüm (öneri 16 veya üzeri) ve yedekleme sorumlusu.
