# Mimari Kararlar

Her karar: bağlam, karar, sonuç. Yeni karar sona eklenir; eskisi değişirse "Yerini aldı: K-0xx" notu düşülür.

## K-001 KS GRC ile aynı teknoloji yığını
**Bağlam.** İlk öneri NestJS, React ve PostgreSQL idi. KS GRC ise Python 3.12, standart kütüphane HTTP sunucusu, SQLite ve derlemesiz istemciyle çalışıyor. İki uygulamanın birleşebilmesi isteniyor.
**Karar.** Tedarik portalı KS GRC ile aynı yığını kullanır. Yeni bağımlılık ancak yeni bir kararla eklenir.
**Sonuç.** Birleşme mekanik bir iş olur, tedarik zinciri riski düşük kalır. Bedeli: çatıların hazır sunduğu parçalar (yönlendirme, doğrulama) küçük ortak modüller olarak elde yazıldı.
*Veritabanı ve bağımlılık kısmının yerini aldı: K-011 (PostgreSQL).*

## K-002 Tedarikçi ve Angajman ayrımı
**Bağlam.** Aynı tedarikçiden farklı birimler farklı şeyler alıyor; bir kısmı şirkete, bir kısmı müşteriye sunuluyor.
**Karar.** Tedarikçi tekil tüzel kişidir (VKN ile). Birim, ürün/hizmet, faydalanan (şirket veya müşteri) ve hesap veren kişi Angajman kaydındadır. SLA, risk, anket ve sorumluluk angajmana bağlanır, tedarikçi kartında özetlenir.
**Sonuç.** "Hangi birim neyi kimden alıyor" ve "müşteriye sunulan hizmetler" tek sorguyla raporlanır.

## K-003 `tdr_` tablo öneki ve `/api/tdr` ad alanı
**Bağlam.** KS GRC'nin tabloları ve uç noktaları öneksiz; tam birleşmede ad çakışması olur.
**Karar.** Tüm tablolar `tdr_` ile başlar, tüm uç noktalar `/api/tdr` altındadır. Risk kaynağının adı `supplier_risks`'tir.
**Sonuç.** İki veritabanı tek dosyada, iki API tek sunucuda çakışmadan durabilir.

## K-004 Bildirimsel kaynak kaydı ve modüller
**Bağlam.** Portal büyüyecek; KS GRC'de tek `Handler` içinde uzayan koşul zincirleri bakım yükü oluşturuyor.
**Karar.** Her tablo bir `Resource` tanımıdır; liste, okuma, ekleme, güncelleme, doğrulama, yetki ve denetim izi bu tanımdan üretilir. Özel davranış modülün `register` işlevinde ve `before_save` kancasında yaşar. Modüller ortam değişkeniyle açılıp kapanır.
**Sonuç.** Yeni alan bir satır, yeni modül bir dosyadır.

## K-005 Risk modeli KS GRC ile aynı, kayıtlar ayrı
**Bağlam.** KS GRC kurumsal risk kaydını ve risk kataloğunu (içinde tedarikçi şablonu) tutuyor.
**Karar.** Tedarikçi riskleri aynı ölçek, aynı katkı hesabı ve aynı karar kurallarıyla portalda tutulur; `control_risk_ref` alanı KS GRC kaydına bağlar.
**Sonuç.** Bugün iki sistem bağımsız çalışır; birleşmede referans alanı yabancı anahtara döner. İki yerde aynı riskin çift kaydı disiplinle önlenmelidir (kurumsal etkisi olan risk KS GRC'de açılır, portalda referans verilir).

## K-006 Süreçler veri olarak tanımlanır
**Bağlam.** Bugün süreç değişmeyecek, yakında tasarlanmak isteniyor (ihtiyaç girişi, mevcut tedarikçiden seçim, en az üç teklif).
**Karar.** Durumlar ve geçişler `workflow_definitions` içinde sürüm numaralı JSON olarak durur. Kurallar adlı koruma işlevleridir, parametreleri `policies` tablosundan gelir. Kaynak bulma modülü bu motorun ilk kullanıcısıdır ve varsayılan olarak kapalıdır.
**Sonuç.** "En az 3 teklif" kuralı kod değişmeden 2 veya 5 yapılabilir; yeni süreç yeni tanımdır. Çalışan süreç, başladığı tanım sürümüyle devam eder.

## K-007 Tek içe aktarma hattı
**Bağlam.** Veri SAP, CRM ve dış kaynak yönetim sisteminden Excel ile gelecek; ileride entegrasyon olacak.
**Karar.** Tüm kaynaklar aynı hattan geçer: kanonik alanlara eşleme, kimlik → VKN → ad sırasıyla eşleştirme, deneme çalıştırması, satır bazında sonuç kaydı. Ad benzerliği otomatik birleştirmez. Kaynak veri yalnızca boş alanları doldurur.
**Sonuç.** Tekrar aktarım çoğaltma üretmez; portalda düzeltilen veri ezilmez. Kaynak sistemde değişen bir değerin portala yansıması için ileride "kaynak öncelikli alanlar" ayarı gerekebilir.

## K-008 Entegrasyon: MCP uygulaması REST API'ye yazar
**Bağlam.** KS GRC kaynak sistemlere doğrudan bağlanmıyor; mevcut MCP uygulaması sorgulayıp REST API'ye yazıyor.
**Karar.** Aynı model. Portal dış sisteme bağlantı açmaz; en az yetkili anahtarla yazılabilen dar bir API sunar.
**Sonuç.** Portalın saldırı yüzeyi küçük kalır, kimlik bilgileri portalda tutulmaz.

## K-009 Silme yok, denetim izi zorunlu
**Karar.** Hiçbir uç nokta kayıt silmez; kayıtlar durum alanıyla kapatılır. Her yazma işlemi `audit_log` tablosuna düşer. Risk değerlendirmeleri ve iş akışı geçmişi değiştirilemez.
**Sonuç.** Denetim kanıtı korunur. Kişisel veri (ilgili kişi kayıtları) için silme veya anonimleştirme ihtiyacı KVKK kapsamında ayrıca ele alınmalıdır.

## K-010 Derlemesiz istemci, dış kaynak yok
**Karar.** Arayüz KS GRC gibi derleme adımı olmadan sunulur. İçerik güvenlik politikası dış betik ve stile izin vermez; grafikler satır içi SVG ile çizilir.
**Sonuç.** Kurulum basit, tedarik zinciri riski düşük. Görsel dil KS GRC'nin `ui_v2.py` ve `ksgrc.js` dosyaları incelendikten sonra kurulacak.

## K-011 PostgreSQL birinci sınıf veritabanı
**Bağlam.** K-001 SQLite'ı KS GRC ile aynı olsun diye seçti; PostgreSQL "sonra geçilebilir" notuyla bırakıldı. Gökhan Bey (2026-11-13) portalın tüm iş birimlerine açılacağını, temelin şimdiden sağlam atılmasını istedi. SQLite tek yazıcıyla çalışır, ağ üzerinden erişilmez, çevrimiçi yedek ve satır kilidi sunmaz; sonradan geçiş, SQL'i ve veri tiplerini SQLite'a göre yazılmış bir kod tabanını yeniden elden geçirmek demektir.
**Karar.** Üretim hedefi PostgreSQL'dir. Veritabanı katmanı iki motoru da destekler: PostgreSQL üretim ve kurumsal profil, SQLite yerel geliştirme, hızlı test ve KS GRC ile tek dosyada birleşme yolu. Uygulama kodu motor bağımsız SQL yazar; motor farkları (`?` parametresi, kimlik sütunu, eklenen kaydın kimliği, tarih işlevleri, kilit, tetikleyici) yalnızca veritabanı katmanındadır. Test takımı her iki motorda çalışır. Sürücü: `psycopg` 3 ve `psycopg-pool`; KS GRC'deki gibi sürüm ve hash ile sabitlenir.
**Sonuç.** K-001'in "yeni bağımlılık yok" kuralının bu kapsamda yerini alır; diğer kısımları geçerlidir. Bedeli: ikinci motorun bakımı ve testi. KS GRC SQLite'ta kaldıkça tam birleşme, tedarik tablolarının KS GRC veritabanına taşınmasıyla değil KS GRC'nin de bu katmana geçmesiyle yapılır; ara aşamada iki uygulama ayrı veritabanında çalışır.

## K-012 Entra uygulama rolleri ve `entra_auth.py` yaması
**Bağlam.** KS GRC `entra_auth.verify` yalnızca `KS.GRC.Admin` ve `KS.GRC.Auditor` rollerini kabul eder; başka rolü olan tokenı reddeder. Tedarikin beş rolü vardır ve KS GRC denetçisi kayıt yazarken tedarik denetçisi salt okur.
**Karar.** Tedarik rol değerleri: `KS.TDR.Admin`, `KS.TDR.SupplierManager`, `KS.TDR.UnitUser`, `KS.TDR.Auditor`, `KS.TDR.Viewer`. `KS.GRC.*` rolleri tedarikte yetki vermez. `entra_auth.py` kopyası tek bir işaretli yamayla alınır: kabul edilen roller modül değişkenidir, `verify` öncelik sırasındaki ilk rolü döndürür. Yama `tedarik/vendor/PATCHES.md` içinde satır satır belgelenir ve KS GRC'ye öneri olarak verilir (UYUM_SOZLESMESI, "KS GRC'ye öneriler" 1).
**Sonuç.** "Kopya dosya değiştirilmez" kuralının tek istisnasıdır. KS GRC öneriyi alırsa yama kalkar. Rollerin aynı Entra uygulama kaydına mı ayrı kayda mı ekleneceği Gökhan Bey'in kararını bekler; kod iki durumda da çalışır.

## K-013 Kimlik tabloları KS GRC ile ortak
**Bağlam.** `identity.py` öneksiz `users`, `auth_sessions`, `entra_subjects` tablolarını kullanır. Tedarikte her tablo `tdr_` önekli olmalıydı (K-003).
**Karar.** Bu üç tablo KS GRC şemasıyla aynı adla ve aynı yapıyla açılır; tam birleşmede ortak kullanıcı tablosu olurlar. Tedarik rolleri ve birim kapsamı ayrı `tdr_user_roles` tablosundadır; KS GRC'nin `roles` ve `user_roles` tablolarına yazılmaz.
**Sonuç.** K-003'ün tek istisnasıdır. Ortak kullanıcı tablosu, iki uygulamanın aynı kişiyi aynı kimlikle görmesini sağlar.
