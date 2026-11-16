# Kişisel veri (KVKK ve GDPR)

> Menü: Kişisel veri (KVKK). Kimler için: veri koruma sorumlusu, uyum ekibi, veri sahipleri, işleme faaliyeti sahipleri.

Bu bölüm 6698 sayılı KVKK ve (AB'de faaliyet varsa) GDPR yükümlülüklerini, veri kataloğuna bağlı olarak yürütür: kişisel veri nerede, hangi amaç ve hukuki sebeple işleniyor, ne kadar saklanıyor, kime aktarılıyor.

## KVKK Panosu

**[KVKK Panosu](#/privacy)**: kişisel veri içeren kolon ve tablolar, işleme faaliyetlerinin açıkları, periyodik imha durumu, süreli işler (başvurular, ihlaller, gözden geçirmeler). Üst düğmeler: **Keşfi çalıştır**, **VERBİS envanteri (Excel)**, **KVKK / GDPR boşluk analizi**, **+ İşleme faaliyeti**.

## 1. Kişisel veriyi bulmak (keşif)

1. **[Kişisel Veri Keşfi](#/discovery)** → **Keşfi çalıştır**: kolon adı, açıklama ve sözlük terimlerinden öneri üretilir (ör. `TCKN` → Kimlik, `CEP_TELEFONU` → İletişim, `SAGLIK_RAPORU` → Sağlık Bilgileri).
2. Öneriyi **Kabul et** veya **Reddet**. Kabul edilen kategori kolona işlenir ve kolonun gizlilik sınıfı en az **Gizli** (özel nitelikli veride **Çok gizli**) olur.
3. **Örnek veriyle doğrulama** (tablo ekranında): örnek değerler bilgisayarınızda veya toplayıcıda kontrol edilir (T.C. kimlik, IBAN, kart, e-posta, telefon, IP); platforma **yalnızca sayılar** gider, değerler gitmez.

Anahtar kelime sözlüğü Yönetim → Kişisel Veri Kategorileri'ndedir.

## 2. İşleme envanteri (VERBİS)

**İşleme Faaliyetleri → + Yeni**: amaç, hukuki sebep (KVKK md. 5; özel nitelikli veride md. 6), kategoriler, ilgili kişi grupları, alıcılar, yurt dışı aktarım (ülke ve mekanizma: yeterlilik, standart sözleşme, BCR…), saklama kuralı, teknik ve idari tedbirler, aydınlatma metni (doküman).

Faaliyet ekranında:

- **+ Tablo bağla / + Kolon bağla:** faaliyetin işlediği veri varlıkları.
- **Veri işleyenleri düzenle:** tedarikçiler ve rolleri (veri işleyen, ortak veri sorumlusu, alıcı), DPA imzalı mı.
- **Açıklar listesi:** hukuki sebep yok, saklama süresi yok, aydınlatma metni yok, aktarım mekanizması yok, standart sözleşme Kurula 5 iş günü içinde bildirilmemiş, VKED gerekli ama onaylı değil… Bağlı kolonlarda envanterde olmayan kategori görünürse **Eksik kategorileri envantere ekle**.
- **VKED başlat:** özel nitelikli veri, profilleme, büyük ölçek, yeni teknoloji veya güvencesiz yurt dışı aktarımda gerekir.

**VERBİS envanteri (Excel)** ile envanteri dışa aktarın.

## 3. Saklama ve imha

- **Saklama ve İmha Kuralları:** süre, başlangıç olayı (ör. "sözleşme sonu"), imha yöntemi (silme, yok etme, anonimleştirme), dayanak. Kuralları tablolara ve faaliyetlere bağlayın.
- **Periyodik İmha** (en çok 6 ayda bir): **+ Yeni** → **Kapsamı oluştur** (saklama kuralı olan tablolar kalem olur) → her kalemde sonuç ve kayıt sayısı → **Tamamla**. Tamamlanan kayıt değiştirilemez ve en az 3 yıl saklanır.

## 4. Veri talepleri

**Veri Talepleri → + Yeni**: erişim, veri çıkarma, maskeleme, anonimleştirme veya takma adlandırma; tablo, istenen kolonlar, amaç ve (kişisel veride zorunlu) işleme faaliyeti.

- Onayı **veri sahibi** verir: **Onayla** veya **Reddet**. **Talep eden onaylayamaz.**
- Teknik sorumlu uyguladıktan sonra **Uygulandı** der ve yöntemi yazar.

## 5. İlgili kişi başvuruları (md. 11)

1. **İlgili Kişi Başvuruları → + Yeni**: başvuru tarihi, kanal, tür (bilgi, erişim, düzeltme, silme, itiraz…), **ad yerine iç referans** (ör. CRM-48213), sorumlu.
2. Son tarih başvuru tarihinden itibaren **30 gün** olarak sistemce atanır. Kalan süre listede ve İşlerim'de görünür.
3. Başvuruda incelenen veri varlıklarını bağlayın; platform kişinin verisinin hangi tablolarda olabileceğini önerir.
4. Yanıtlarken **kimlik doğrulandı** işareti, yanıt tarihi ve yanıt özeti zorunludur.

Bu kayıtları yalnızca Yönetici, Tedarikçi Yöneticisi ve Denetçi görür.

## 6. Kişisel veri ihlalleri (md. 12/5)

1. **Kişisel Veri İhlalleri → + Yeni**: tespit zamanı, açıklama, kategoriler, etkilenen kişi sayısı, sorumlu. Kayıt açılınca sorumluya ve yöneticilere bildirim gider; tüm kullanıcıların ekranında **KVKK İHLALİ** bandı süreyi gösterir.
2. **Bildirim kararı** (72 saat içinde): Kurula bildirilecek mi? Karar **gerekçesiz verilemez ve geri alınamaz**. Süre aşıldıysa gecikme gerekçesi zorunludur.
3. **Kurula bildirildi** (tarih ve referans), gerekirse **İlgililere bildirildi**.
4. Etkilenen veri varlıklarını bağlayın; kategoriler ve özel nitelik bilgisi önerilir.
5. Karar ve önlemler girilmeden ihlal kapanmaz.

## 7. KVKK / GDPR boşluk analizi

**[KVKK / GDPR Boşluk Analizi](#/regulation)** kanun ve tüzüğü madde madde değerlendirir. Metinler resmî kaynaktan alınmıştır (KVKK: mevzuat.gov.tr; GDPR: EUR-Lex). Kurulu değilse Yönetici ekrandan **Kütüphaneden kur** der.

- **Platform göstergeleri** KVKK kayıtlarınızdan her açılışta hesaplanır: hukuki sebepsiz faaliyet, saklama süresiz kişisel veri, gecikmiş imha, mekanizmasız aktarım, aydınlatma metni, DPA'sız veri işleyen, düşük sınıflı kişisel veri, 72 saati aşan ihlal, süresi geçen başvuru, envanter dışı tablo, VKED, insan gözetimsiz otomatik karar. Göstergeye tıklayınca etkilenen kayıtlar bağlantılarıyla açılır.
- Madde durumu: eşlenen kontrollerin son testi ve göstergeler **platform göstergesini**; uyum sorumlusunun **Değerlendir** ile girdiği durum (uyumlu, kısmen, uyumsuz) **madde durumunu** belirler. Kısmen ve uyumsuzda açığı yazmak zorunludur.
- Açık maddeden **Bulgu aç** (Denetçi/Yönetici): sorumlu ve hedef tarih verilirse DÖF de açılır.
- KVKK ve GDPR birlikte kuruluysa **Eşlemeyi kur** ile eşdeğer maddeleri bağlayın; bir kontrol iki mevzuatta birden güvence sağlar.
- Kapsam dışı maddeler (tanımlar, Kurul teşkilatı, cezalar vb.) gerekçesiyle ayrı tutulur; "Kapsam dışı maddeleri göster" ile görünür.

Uyum göstergesi bir ön değerlendirmedir; hukuki görüş yerine geçmez.

## Kim ne yapar

| İş | Yönetici | Tedarikçi Yöneticisi | Birim Kullanıcısı | Denetçi |
|---|---|---|---|---|
| Keşif önerisine karar | ✓ | ✓ | — | — |
| İşleme faaliyeti | ✓ | ✓ | kendi birimi | okur |
| Veri talebi açmak | ✓ | ✓ | kendi birimi | okur |
| İlgili kişi başvurusu, ihlal, VKED | ✓ | ✓ | — | okur |
| Boşluk analizi değerlendirmesi | ✓ | ✓ | — | okur, bulgu açar |
