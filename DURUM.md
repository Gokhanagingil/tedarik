# Durum

Son güncelleme: 2026-11-15 · Aşama: uygulama tedarikçi portalından **GRC platformuna** dönüştü (K-016 – K-020; adı sonra belirlenecek, `TEDARIK_APP_NAME`). Test sunucusu: https://tedarik.204-168-247-101.sslip.io (sentetik demo verisi). KS GRC artık kullanılmıyor (K-016).
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
- Test sunucusunda TLS: sslip.io adı, projeye ait Caddy, 443/TLS-ALPN-01; 80. porttaki uygulamaya dokunulmaz (K-014).
- KS GRC iş modeli bu altyapıda (`grc` modülü); kurumsal ve tedarikçi riskleri tek risk kaydında (K-015).
- KS GRC kullanılmıyor; bu uygulama GRC platformudur (K-016). Kayıt kodları sunucuda üretilir (K-017).
- Kurumsal risk yönetimi ISO 31000'e göre; her risk bir şirkete (kendi şirketimiz / müşteri) bağlı (K-018).
- CMDB: ServiceNow Table API'den salt okunur senkron veya MCP itmesi; CI kuralları kurumsal risk açar (K-019).
- İş sürekliliği ISO 22301'e, doküman yönetimi ISO 9001 7.5'e göre (K-020).
- Portal ServiceNow MCP sunucusuna standart MCP istemcisiyle bağlanabilir (K-021).
- Kısıtlı kanıt yalnızca Yönetici, Denetçi ve yükleyene açık; denetim arşivi (K-022).
- Standart kütüphanesi (yalnızca tam metniyle dağıtılabilenler: NIST), madde ilişkileri, bulgu etkisi, entegre denetim (K-023).
- Entegrasyonlar arayüzden tanımlanır, sırlar şifreli; bildirimler kuyrukla gider (K-024). Yapay zekâ insan onaylı, SDK isteğe bağlı (K-025).
- Güvence ve uyum iş akışları (K-026); olay, kayıp, KVKK ihlali, RCSA, nicel risk, erişim gözden geçirme, kriz, ServiceNow görev (K-027).

## Varsayımlar (Gökhan Bey'in onayıyla)

- Hedef ortam KS GRC'nin kurumsal profiliyle aynı: Docker, TLS sonlandıran ters vekil, tek kiracılı Entra.
- Portalı yalnızca iç kullanıcılar kullanır; anketleri iç kullanıcılar yanıtlar.
- Tek kiracı; içinde birden çok şirket (grup şirketleri ve müşteriler) kayıtlıdır.
- SAP ve Dynamics sütun başlıkları tahminidir (`transfer.py` içindeki `ALIASES`).
- Başlangıç tedarikçi tipleri ve değerlendirme kriterleri öneridir.

## Yapılanlar

- Temel katman: yapılandırma, şema kaydı, veritabanı, ortak kayıt işlemleri, yönlendirici, güvenlik başlıkları, köken denetimi, tekrar koruması, denetim izi.
- Yetki: beş rol, en az yetkili MCP anahtarı. Anonim erişim açılmaz.
- Modüller: `core`, `performance`, `surveys`, `risks`, `grc`, `transfer`, `dashboard` (açık); `workflow`, `sourcing` (kapalı).
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
- **Adım 7 (2026-11-13): Periyodik işler.** `policies` tablosu çekirdeğe taşındı (her kurulumda var). Kritiklik seviyesine göre değerlendirme ve anket sıklığı (`review.cadence_months`, `survey.cadence_months`) ve uyarı süresi politikadır; yönetici arayüzden değiştirir. `GET /api/tdr/schedule` ve "Takvim" ekranı: geciken ve yaklaşan değerlendirme, anket ve risk gözden geçirmeleri; pano uyarıları. Not: hatırlatma e-postası yok (uygulama dışarıya ileti göndermez; KS GRC ile aynı ilke).
- CI düzeltildi: iş akışı dosyasındaki YAML hatası yüzünden adım 3'ten beri CI işleri hiç başlamamıştı. Paketsiz kurulumda Entra modu artık anlaşılır bir hatayla durur.
- **Test sunucusuna kurulum (2026-11-15):** 204.168.247.101 (Hetzner, Ubuntu 24.04). Sunucuda `tedarik-deploy` kullanıcısı (anahtarla giriş, parolasız sudo) açıldı; root girişi yalnızca anahtarla (varsayılan). Docker (Ubuntu paketleri) kuruldu. GitHub Actions "Deploy Tedarik (isolated)" işiyle kuruldu; sunucudaki mevcut nginx (80) ve yerel PostgreSQL (127.0.0.1:5432) uygulamasına dokunulmadı. Uygulama `127.0.0.1:18090`; ilk yönetici `tdradmin`.
- **TLS (2026-11-15, K-014):** `https://tedarik.204-168-247-101.sslip.io`. Let's Encrypt sertifikası (TLS-ALPN-01), HSTS, CSP, Secure çerez. Kurulum işi dışarıdan sertifika, başlık ve anonim 401 denetimi yapar. Sunucudaki diğer uygulama (nginx :80) etkilenmedi.
- **Demo verisi (2026-11-15):** `python -m tedarik.demo` (kurulumda `seed_demo`). Sentetik şirket: 10 birim, 28 ürün/hizmet, 45 tedarikçi (`DMO-` kodlu), 61 angajman, 57 sözleşme, 12 aylık SLA ölçümü, performans olayları ve değerlendirmeler, risk değerlendirme/karar/faaliyetleri, 3 anket kampanyası ve yanıtları; GRC: 3 standart (ISO/IEC 20000-1, CIS v8.1, ISO/IEC 27001 tedarikçi kontrolleri), 37 kontrol, 133 test sonucu, 4 denetim, 12 kanıt (dosyalı), 45 bulgu, 36 DÖF, 8 doküman, risk kataloğu ve 6 kurumsal risk. 9 demo kullanıcısı (her rol); geçici parolaları sunucuda yalnızca root'un okuyabildiği `/opt/tedarik/.demo-users` dosyasında. Yönetici, Kullanıcılar ekranından "Geçici parola ver" ile de yeni parola üretebilir. Demo yalnızca boş (veya yalnızca demo verisi olan) veritabanına yüklenir; iş kuralları uygulamanın kendi işlevleriyle uygulanır.
- **KS GRC taşıması (2026-11-15, K-015):** `tedarik/modules/grc.py`. Çerçeve (standart, madde + uygulanabilirlik bildirimi, süreç, hedef, doküman), kontrol ve eşlemeleri, değiştirilemez kontrol çalışmaları (dondurulmuş tanım, kaynak bilgisi, kanıt sürümü/SHA-256), denetim yaşam döngüsü (kapsam sürüm koruması, plan dondurma), kanıt dosya sürümleri (veritabanında, indirmede bütünlük doğrulaması), bulgu ve DÖF (doğrulama aşaması, görevler ayrılığı), uyum göstergesi (KS GRC anlamı), GRC genel bakış. İç otomatik kontroller portal verisini denetler (6 kural) ve her sabah çalışır (`/etc/cron.d/tedarik-grc`). MCP otomatik kontrol sonucu yazar (`POST /api/tdr/executions`). Tek risk kaydı (göç 1) ve risk kataloğu. Arayüz: Uyum Panosu, kontrol ayrıntısı (sonuç kaydet, şimdi çalıştır, eşlemeler), denetim çalışma alanı, kanıt sürümleri, bulgu ve DÖF akışları; genel bakışta uyum kartları.
- **Canlı kabul testi (2026-11-15):** `scripts/acceptance.py`, kurulum işinde `acceptance` girdisiyle HTTPS adrese karşı çalışır (23 senaryo: TLS ve güvenlik başlıkları, anonim erişim, tarayıcıda giriş ve zorunlu parola değişimi, 35 ekranın hatasız açılması, ana akışlar, hesap açma/sıfırlama, görüntüleyici sınırları, birim kapsamı, kanıt bütünlüğü, denetim → bulgu → DÖF → doğrulama → kapanış, iç otomatik kontrol, uyum göstergesi, risk, XSS, CSRF ve gövde sınırı, giriş hız sınırı, MCP en az yetki ve tekrar koruması, yanıt süreleri, telefon düzeni). Bulup düzelttikleri: telefonda filtre satırı yatay taşıyordu; vekil arkasında giriş hız sınırı tüm kullanıcıları tek adres sayıyordu (TEDARIK_TRUST_PROXY); yavaş ağda önceki ekranın geç yanıtı yeni ekranı eziyordu (yönlendiricide sıra numarası ve bekleyen yeniden çizim; tarayıcı testinde iki gerileme senaryosu). Son çalıştırma: 23/23 geçti (GitHub Actions çalıştırması 43710121994, 2026-11-15). Test sunucusunda "KABUL" işaretli birkaç kayıt (kanıt, bulgu, DÖF, risk, SLA ölçümü) ve devre dışı `kabul.*` hesapları bulunur; `kabul.yonetici` parolası kimsenin bilmediği rastgele bir değerdir.
- **GRC platformu dönüşümü (2026-11-15, K-016 – K-020).** Gökhan Bey'in 13 maddelik isteği:
  1. *Kontroller:* "Uyum ve denetim" menüsünde Kontroller, Kontrol Hedefleri, Denetimler, Bulgular, DÖF, Kanıtlar; kontrol hedefi detayında kontroller, etkinlik oranı ve ele aldığı riskler (eşleme düzenlenir).
  2. *Süreç haritası:* ISO 9001 süreç yaklaşımıyla yeniden çizildi (yönetim, ana değer zinciri, destek); her süreçte risk, kontrol (başarısız sayısı), doküman, BİA ve tedarikçi etiketi; süreç detayında girdi/çıktı, alt süreçler ve tüm bağlar. Süreçler artık çekirdekte (`process_type`, `parent_id`, `position`, `inputs`, `outputs`).
  3. *İlişkiler:* kontrol ↔ hedef ↔ süreç ↔ madde ↔ risk ↔ doküman ↔ bulgu ↔ BİA ↔ CI ↔ tedarikçi bağları; eksikler eklendi: hedef ↔ risk, doküman ↔ madde (`POST /documents/{id}/clauses`), bulgu → madde/süreç/risk/şirket ve kaynak, BİA → uygulama (CI)/tedarikçi/risk, plan → BİA/uygulama/doküman, tatbikat → bulgu. "İlişki Haritası" şemadan otomatik üretilir; "GRC Sağlık Kontrolü" 19 ilişki kuralını denetler (puan ihlal oranıyla).
  4/11. *Kurumsal risk (ISO 31000):* şirket (kendi/müşteri) zorunlu, süreç, birim, tehdit/fırsat, etki alanı, hedef risk, danışılan paydaşlar, kaynak (elle, tedarikçi, anket, CMDB kuralı); risk kriterleri (olasılık/etki ölçekleri), kategori iştahı ve toleransı, değerlendirme dönemleri (ilerleme), KRİ ve değişmez ölçümler, seviye (politika sınırlarıyla), Risk Panosu (ısı haritası, seviye, şirket, kategori, kaynak, dönem, KRİ, en yüksek riskler).
  5. *Menü:* tek sayfa uygulama; menü bir kez kurulur, tıklamada sayfa yenilenmez, kaydırma ve katlanmış gruplar korunur; etkin öğe görünür alana getirilir.
  6. *İş sürekliliği (ISO 22301):* BİA (etki matrisi → MTPD ve kritiklik, RTO ≤ MTPD, RPO, MBCO, uygulama/tedarikçi/risk bağımlılıkları, dört gözle onay), planlar (adımlar dört evrede, kurtarma sırası, kapsadığı BİA'lar, revizyon), tatbikatlar (hedef/gerçekleşen kurtarma süresi, sonuç, alınan dersler, bulgu → DÖF), Süreklilik Panosu.
  7. *GRC Takvimi:* denetim, tatbikat, risk dönemi, risk gözden geçirme ve faaliyet, kontrol testi, DÖF/bulgu hedefleri, doküman/BİA/plan gözden geçirme, kanıt geçerlilik sonu, sözleşme bitişi, anket ve tedarikçi değerlendirmesi; ay ve liste görünümü, tür süzgeci. Ayrıca "İşlerim".
  8. *Dokümanlar (ISO 9001 7.5):* taslak → onayda → yayımlandı → geçersiz; değişiklik özeti, atanmış onaylayan, dört göz, değişmez revizyon ve dosya (SHA-256), gözden geçirme sıklığı, gizlilik, saklama süresi, süreç ve madde bağı.
  9. *Arayüz:* Hetzner esintili açık tema (beyaz kenar menü, kırmızı vurgu), SVG ikonlar, üst çubuk ve Ctrl+K komut paleti (ekran ve kayıt araması), yönetici özeti (karşılama, sağlık puanı, alan kartları, 30 günlük ajanda, öncelikli iyileştirme alanları, ısı haritası), tüm detay panellerinde aynı düzen (durum çipleri, ölçü şeridi, sekmeler). Telefon düzeni denendi.
  10. *CMDB:* `tedarik/servicenow.py` (Table API, sayfalama, artımlı senkron, yeniden deneme), `python -m tedarik.cmdb_sync` (gece görevi), MCP itmesi, CI ilişkileri, CMDB Panosu ve CI detayı; BİA uygulamaları CMDB'den seçilir.
  11. *CI riskleri:* İS destek bitişi, uygulama destek bitişi, kritik yama, 100 günden uzun açık kalma; kural ve şirket başına kurumsal risk, etkilenen CI listesi, müşteri CI'ları müşteri riski olur.
  12. *Kodlar:* tüm kayıt kodları sunucuda üretilir ve değiştirilemez (K-017); içe aktarım ve ilişkiler ad veya kodla çözülür.
  13. *GRC incelemesi:* yukarıdaki ilişki eksikleri tamamlandı; ayrıca denetim kapsamına süreçler eklendi (ISO 9001 9.2; `process_ids`, "Son 12 ayda denetlenmemiş ana süreçler" kontrolü). Sağlık kontrolü 20 ilişki kuralını sürekli denetler.
  - Demo verisi genişledi: 6 şirket (3 grup şirketi, 3 müşteri), 30 süreçlik harita, 10 iştah beyanı, 4 risk dönemi, 10 yeni kurumsal risk (fırsat dahil), 7 KRİ, 39 CI (destek dışı, yama, açık kalma örnekleri), CMDB kural riskleri, 8 BİA, 4 plan, 5 tatbikat, revizyonlu ve dosyalı dokümanlar. Önceki sürümle yüklenmiş demoya bölüm bölüm eklenir (kullanıcılara dokunmaz).
  - Testler: 100 uçtan uca test (SQLite ve PostgreSQL 16), tarayıcı smoke testi (yeni ekranlar dahil) ve yerel kabul provası (23/23, 54 ekran).
  - Test sunucusuna dağıtıldı (commit `124cf98`): mevcut demoya yeni bölümler eklendi, göç 2 ve 3 uygulandı; canlı kabul testi 23/23 geçti, 54 ekran hatasız (GitHub Actions çalıştırması 43725941060, 2026-11-15).
- **Güvenlik, arşiv ve ServiceNow MCP (2026-11-15).** Gökhan Bey'in 4 maddelik isteği:
  1. *Güvenlik taraması:* bandit (orta ve üstü), pip-audit (sabitlenmiş bağımlılıklarda bilinen açık yok), detect-secrets
     (yalnızca incelenmiş yanlış pozitifler, `.secrets.baseline`) ve elle inceleme. Düzeltilenler: kısıtlı kanıt herkese
     açıktı (K-022); tatbikat uç noktası bulgu yazma yetkisini atlıyordu; ServiceNow istemcisi yönlendirmeyi izliyordu
     (Authorization başka sunucuya gidebilirdi) ve yanıt boyutu sınırsızdı; dış bağlantılar istemcide de http(s) ile
     sınırlandı. CI'a kalıcı `security` işi eklendi; CI PostgreSQL imajı özetle sabitlendi.
     *Entra ID + MFA:* PKCE, RS256/JWKS, kiracı, nonce ve Koşullu Erişim kimlik doğrulama bağlamı (`acrs`) zorunluluğu
     doğrulandı; olumsuz senaryo testleri eklendi (bağlamsız, başka kiracı/uygulama, süresi dolmuş, başka anahtarla
     imzalı belirteç). Sunucu Entra moduna geçebilir (`/opt/tedarik/entra.env` + sır dosyası), `python -m tedarik.entra_check`
     Microsoft uç noktalarını ve istemci sırrını gerçek ortamda denetler.
  2. *GRC uzmanı değerlendirmesi:* `docs/YOL_HARITASI.md`.
  3. *Denetim arşivi:* madde kodu (A.5.19, ISO 27001 5.22, 8.3.4) veya konu ile hangi denetimde hangi kontrolün test
     edildiği, sonucu ve o sonuca dondurulmuş kanıt sürümü (SHA-256); denetim dışı izleme sonuçları ve kanıt
     kütüphanesi. Denetim çalışma alanında "Bu kapsamın geçmişi" ve kontrol başına "Geçmiş"; madde ekranından arşive geçiş.
     Demo: önceki yıla ait, kanıtlı ve kapalı bir denetim.
  4. *ServiceNow MCP:* `tedarik/mcp_client.py` (Streamable HTTP, SSE, oturum, bearer veya OAuth istemci kimlik bilgisi);
     CMDB senkronu Table API veya MCP kanalından; "MCP bağlantısını sına" (araç listesi ve örnek kayıt). Sahte MCP
     sunucusuyla uçtan uca test edildi; gerçek sunucu adresi ve kimlik bilgisi bekleniyor.
  - Testler: 107 uçtan uca test (SQLite ve PostgreSQL 16, Entra testleri dahil), tarayıcı smoke testi.
  - Test sunucusuna dağıtıldı (commit `a9e2dd2`); canlı kabul testi 23/23 geçti, 55 ekran hatasız, görüntüleyici kısıtlı
    kanıtları göremiyor (GitHub Actions çalıştırması 43738880070, 2026-11-15).
- **Standartlar, entegrasyonlar ve GRC yol haritası (2026-11-15, K-023 – K-027).** Gökhan Bey'in 3 maddelik isteği:
  1. *Yol haritası maddeleri:* kanıt talepleri (kontrol başına tek talep, mevcut kanıtın yeniden kullanımı, kabul/iade),
     çalışma kâğıtları ve ikinci denetçi gözden geçirmesi, yönetim yanıtı, yazdırılabilir denetim raporu (yönetici özeti
     taslağı), risk bazlı denetim evreni ve yıllık plan, sertifikalar, süreli ve kapsamlı salt okunur dış denetçi hesabı,
     yükümlülük envanteri (KVKK/BDDK/TCMB/sözleşme), politika istisnaları, okundu beyanı, SoA raporu, RCSA, kayıp
     olayları, KVKK ihlal kaydı (72 saat geri sayımı), nicel risk (Monte Carlo, TL), erişim gözden geçirme, kriz modu
     (plan adımlarından görevler, günlük, gerçek olay tatbikatı), DÖF → ServiceNow görev, insan onaylı yapay zekâ
     (risk ifadesi, kanıt → kontrol, rapor özeti). Yönetim → Entegrasyonlar: e-posta (SMTP), Teams (Workflows web
     kancası), Entra ID + MFA, ServiceNow Table API, ServiceNow MCP, Claude; şifreli sırlar ve "Sına". Bildirim kutusu,
     olay → kanal tablosu, günlük iş özeti ve hatırlatmalar (zamanlanmış görev).
  2. *Standartlar:* NIST SP 800-53 Rev. 5.2.0 (1034 madde; 800-53A değerlendirme yöntemleri, 800-53B temel düzeyleri,
     2660 resmî ilişki) ve NIST CSF 2.0 (134 madde) tam metniyle kütüphanede; her kurulumda güncellenir. ISO ailesi,
     TS EN 50600 ve PCI DSS telif/lisans nedeniyle, CIS Controls kayıtlı lisans nedeniyle tam metin olarak bulunamadı ve
     isteğe uygun olarak hiç yüklenmedi; kurumun lisanslı kopyası Excel/CSV/JSON ile içe aktarılır. Madde ilişkileri
     (eşdeğer, alt küme, üst küme, kesişir, ilgili), çapraz eşleme içe aktarımı, metin benzerliğine dayalı öneri ve eşleme
     çalışma alanı; bulgunun başka standartlarda kesin/olası etkilediği maddeler; madde ekranında "ilişkili maddeler,
     ortak kontroller ve bu maddeyi etkileyen açık bulgular"; entegre denetim test planı (kontrol başına tek test ve tek
     kanıt; kontrolsüz ilişkili maddeler tek soru grubu → ortak kontrol). Demo: ISO/IEC 27001, 20000-1, CIS ve NIST
     arasında 36 örnek eşleme ve entegre bir denetim.
  3. *Sadeleştirme:* menü Uyum ve Denetim olarak ayrıldı, tedarikçi ve performans tek grupta; denetim çalışma alanı
     sekmeli (Özet, Test planı, Kanıt talepleri, Çalışma kâğıtları, Bulgular, Kanıtlar, Geçmiş); binlerce maddeye göre
     ağaçlı ve aranabilir madde seçici; büyük referanslarda aranarak seçim; İşlerim'e yeni iş türleri; takvime 8 yeni
     olay türü (yalnızca kaydı olan türler etiket olarak görünür); risk ayrıntısında 8 sekme 6'ya indi; sağlık
     kontrolüne 3 yeni kural; etkin kriz ve KVKK süresi için üst uyarı bandı.
  - Testler: 138 uçtan uca test (SQLite ve PostgreSQL 16), tarayıcı duman testi (89 denetim).
- Yönetici geçici parola verebilir (`POST /api/tdr/users/{id}/reset-password`, yalnızca yerel hesap, kendi hesabı hariç).
- Testler: 78 uçtan uca test (GRC 15, demo 2 dahil); SQLite'ta, PostgreSQL 16'da ve paketsiz Python'da geçiyor. Tarayıcı testi GRC akışını da yürütüyor (kontrol → eşleme → başarısız sonuç → bulgu → DÖF → doğrulama; iç otomatik kontrol; denetim; uyum panosu).
- Önceki test sayısı: 61 uçtan uca test; SQLite'ta ve PostgreSQL 16'da tamamı geçiyor. Birim kapsamı ve Entra rol eşlemesi testlerinin hatayı yakaladığı kasıtlı bozmayla doğrulandı.
- Belgeler: `docs/MIMARI.md`, `docs/VERI_MODELI.md`, `docs/UYUM_SOZLESMESI.md`, `docs/KARARLAR.md`.

## Bilinen eksikler

- **SAP ve Dynamics başlıkları hâlâ tahmin** (`transfer.py` `ALIASES`); gerçek dışa aktarım bekleniyor. Portalın kendi şablonu bu tahmine bağlı değildir.
- **Entra akışı gerçek kiracıda denenmedi.** Testler sentetik token ve anahtarla; kurumsal kabul testleri KS GRC `docs/ENTRA_ID.md` tablosundaki gibi kiracıda yapılmalı.
- **Test adresi sslip.io üzerinde** (üçüncü taraf DNS); kurumsal kullanım için kurum alan adı gerekir (K-014).
- **KS GRC verisinin taşınması yapılmadı:** iş modeli taşındı; KS GRC'deki gerçek kayıtları (standart eşlemeleri, kontroller, denetimler, kanıt dosyaları) aktaracak içe aktarım henüz yok.
- **Konteyner imajı taraması (trivy) yok;** bandit, pip-audit ve sır taraması CI'da.
- **ServiceNow bağlantısı gerçek kurumda denenmedi:** bağlayıcı sahte sunucuyla test edildi; özel alan adları (`u_os_end_of_support` vb.) kurumun CMDB'sine göre eşlenmeli. Test sunucusundaki CI'lar sentetik MCP itmesidir.
- **E-posta ve Teams bağlantıları tanımlanmadı:** altyapı ve sınama hazır; kurumun SMTP sunucusu/gönderici hesabı ve
  Teams kanalı web kancası girilince bildirimler gider.
- **Telifli standart metinleri yok:** ISO ailesi, TS EN 50600, PCI DSS ve CIS lisanslı kopyadan içe aktarılmalı; resmî
  çapraz eşleme tabloları (ör. NIST OLIR, ISO 27001 ↔ 27701) da kurum kopyasından içe aktarılmalı.
- **Claude SDK paketi kurulu değil:** yapay zekâ önerileri kural tabanlı çalışıyor; `anthropic` paketinin
  requirements.txt'e (sürüm ve hash ile) eklenmesi onay bekliyor.
- **Veri yönetişimi modülü** henüz yok (Gökhan Bey ayrıca konuşmak istiyor).

## Sıradaki adımlar (sırayla)

1. ~~**KS GRC'yi tam oku ve uyumu doğrula.**~~ Tamamlandı (2026-11-13).
2. ~~**Veritabanı temeli: PostgreSQL** (K-011).~~ Tamamlandı (2026-11-13).
3. ~~**Kimlik aktarımı.**~~ Tamamlandı (2026-11-13).
4. ~~**Excel.**~~ Tamamlandı (2026-11-13). Kalan: gerçek SAP/Dynamics başlıklarıyla `ALIASES` doğrulaması.
4a. ~~**Anket motoru**~~ Tamamlandı (2026-11-13). Not: anket tabloları değişti; eski iskelet veritabanı varsa silinip yeniden açılmalı (üretim verisi yok).
5. ~~**Arayüz.**~~ Tamamlandı (2026-11-13).
6. ~~**Dağıtım.**~~ Tamamlandı (2026-11-13). Kalan: CI'a gitleaks, trivy, bandit, pip-audit; kalıcı alan adı ve TLS.
7. ~~**Periyodik işler.**~~ Tamamlandı (2026-11-13).
8. ~~**MCP sözleşmesi.**~~ Tamamlandı (2026-11-13): `docs/MCP_SOZLESMESI.md`. Kalan: KS GRC tarafında örnek kontrollerin tanımlanması.
9. ~~**TLS, demo verisi, KS GRC taşıması.**~~ Tamamlandı (2026-11-15).
10. ~~**GRC platformu dönüşümü** (13 madde).~~ Tamamlandı (2026-11-15).
10a0. ~~**Güvenlik taraması, Entra MFA, denetim arşivi, ServiceNow MCP istemcisi.**~~ Tamamlandı (2026-11-15).
10a. **ServiceNow bağlantısı:** kurum adresi, salt okunur hizmet hesabı, özel alan eşlemesi; ilk senkron ve kural eşiklerinin kurumla belirlenmesi.
10b. **Veri yönetişimi modülü:** kapsam görüşmesi (veri sahipliği, sınıflandırma, KVKK envanteri, veri kalitesi kuralları).
10c. **KS GRC veri aktarımı:** KS GRC Excel dışa aktarımını (standart, madde, süreç, hedef, kontrol, eşleme, denetim) içe aktarım hattına ekle; kanıt dosyaları için KS GRC yedeğinden SHA-256 doğrulamalı aktarım.
11. ~~**Yol haritası Faz 1–4** (`docs/YOL_HARITASI.md`).~~ Büyük ölçüde tamamlandı (2026-11-15, K-023 – K-027); kalanlar yol haritası belgesinde. Ayrıca konteyner imajı taraması (trivy).
12. **Kaynak bulma.** Süreç tasarımı onaylanınca `workflow,sourcing` modüllerini aç, ekranlarını yap.

## Gökhan Bey'den beklenenler

- Veri yönetişimi modülü görüşmesi (sıradaki iş).
- `anthropic` paketinin bağımlılığa eklenmesi onayı (yapay zekâ önerileri için) ve Claude API anahtarı.
- SMTP sunucusu ve gönderici hesabı, Teams bildirim kanalı (Workflows web kancası).
- Lisanslı standart metinleri (ISO 27001/27017/27701/20000-1/9001/14001/22301/45001/50001/10002, TS EN 50600, PCI DSS,
  CIS) ve varsa resmî çapraz eşleme tabloları; içe aktarım şablonu uygulamada.
- Uygulamanın adı (şimdilik "GRC Platformu"; `TEDARIK_APP_NAME` ile değişir).
- ServiceNow örnek adresi ve salt okunur hizmet hesabı **veya** ServiceNow MCP sunucusunun adresi, kimlik doğrulama türü (bearer / OAuth istemci kimlik bilgisi) ve CMDB okuyan aracın adı; CMDB'deki destek bitişi, yama ve açılış alanlarının adları.
- Entra ID için kiracı ve uygulama kaydı (istemci kimliği), MFA'lı Koşullu Erişim ilkesinin bağlamı (c1–c99) ve istemci sırrının sunucuya güvenli aktarımı (`docs/KIMLIK.md`, `docs/DAGITIM.md`).

- SAP, Dynamics ve dış kaynak yönetim sisteminden örnek dışa aktarım (sütun başlıkları yeterli).
- Tedarikçi tipleri ve iş birimleri listesi.
- Yeni rollerin (`KS.TDR.*`) KS GRC'nin Entra uygulama kaydına mı, ayrı bir kayda mı ekleneceği.
- `tedarik` ve `control` repolarının görünürlüğü (şu an ikisi de herkese açık).
- Kalıcı kurumsal adres (alan adı) ve test sunucusunun internete açık kalıp kalmayacağı.
- Üretim PostgreSQL'inin nerede çalışacağı (şimdilik aynı sunucuda yalıtılmış konteyner): kurumun yönetilen PostgreSQL hizmeti mi, aynı sunucuda konteyner mi; sürüm (öneri 16 veya üzeri) ve yedekleme sorumlusu.
