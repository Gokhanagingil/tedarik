# Başlarken

> Kimler için: platformu ilk kez kullanan herkes. Okuma süresi: 10 dakika.

Bu platform kurumun yönetişim, risk ve uyum (GRC) işlerini tek yerde toplar: tedarikçi yönetimi, kurumsal risk yönetimi (ISO 31000), uyum ve denetim, iş sürekliliği (ISO 22301), doküman yönetimi (ISO 9001), varlıklar (CMDB), veri yönetişimi ve kişisel verilerin korunması (KVKK/GDPR). Kayıtlar birbirine bağlıdır: bir risk bir sürece, bir kontrole, bir tedarikçiye ve bir iş etki analizine aynı anda bağlanabilir.

## Giriş

1. Kurumun size verdiği adresi tarayıcıda açın.
2. **Kurumsal giriş açıksa** "Microsoft ile giriş yap" düğmesine basın; Microsoft hesabınız ve çok adımlı doğrulama (MFA) ile girersiniz. Rolünüz Entra ID'deki uygulama rolünden gelir.
3. **Yerel hesap kullanılıyorsa** kullanıcı adınızı ve yöneticinin verdiği geçici parolayı girin. İlk girişte yeni parola belirlemeniz zorunludur; geçici parola bir kez kullanılır.

Üst üste hatalı parola denemesi hesabı kısa süreliğine kilitler. Parolanızı unuttuysanız yöneticiden yeni geçici parola isteyin; yönetici parolanızı göremez, yalnızca yenisini verebilir.

Hesabınızın bir bitiş tarihi olabilir (ör. dış denetçi hesapları). Tarih geçince giriş yapılamaz.

## Ekranın bölümleri

| Bölüm | Ne işe yarar |
|---|---|
| Sol menü | Modüller ve ekranlar. Başlığa tıklayarak grubu açıp kapatabilirsiniz; tercih tarayıcınızda hatırlanır. Yetkiniz olmayan ekranlar görünmez. |
| Üst çubuk | Sayfanın yeri (Genel Bakış / … ), hızlı arama ve sayfaya özel düğmeler. |
| Kırmızı bant | Herkesin bilmesi gereken acil durum (ör. süresi işleyen kişisel veri ihlali). |
| Sağ çekmece | Bir kayda tıkladığınızda ayrıntısı sağda açılır; sayfadan ayrılmadan düzenleyebilirsiniz. |
| Sol alt köşe | Adınız, rolünüz ve **Çıkış**. |

## Her gün kullanacağınız ekranlar

- **[Genel Bakış](#/home):** risk, uyum, süreklilik, doküman, varlık ve tedarikçi alanlarının özeti. Kartlar ilgili ekranı açar.
- **[İşlerim](#/my-work):** size atanmış açık işler — riskler, faaliyetler, bulgular, onay bekleyenler, kanıt talepleri, gözden geçirmeler, anketler. Tarihi geçenler kırmızıdır. Güne buradan başlayın.
- **[GRC Takvimi](#/calendar):** denetimler, tatbikatlar, değerlendirme dönemleri, kontrol testleri ve hedef tarihler tek takvimde.
- **[GRC Sağlık Kontrolü](#/health):** kayıtlar arasındaki eksik bağlar (kontrolsüz yüksek risk, BİA'sı olmayan ana süreç, sahibi olmayan veri tablosu gibi). Her madde nedenini ve etkilenen kayıtları gösterir.
- **[Anketlerim](#/my-surveys):** yanıtlamanız istenen anketler.

## Haritalar

- **[Süreç Haritası](#/process-map)** (Mimari menüsü): yönetim, ana ve destek süreçleri; bir sürece tıklayınca riskleri, kontrolleri, dokümanları ve iş etki analizi açılır.
- **[İlişki Haritası](#/map)**: kayıt türleri (süreç, risk, kontrol, hedef, madde, bulgu, BİA, plan, CI, tedarikçi) ve aralarındaki bağlar. Bir kutunun üzerine gelince bağlı türler vurgulanır; çift tıklama listeyi açar.

## Listeler

Menüdeki kayıt ekranlarının çoğu aynı biçimde çalışır:

- **Arama:** listenin üstündeki kutuya yazın. Klavyede `/` tuşu arama kutusuna atlar.
- **Süzgeçler:** arama kutusunun yanındaki açılır listelerle durum, önem, birim gibi alanlara göre süzün.
- **Sıralama:** sütun başlığına tıklayın.
- **Yeni kayıt:** sağ üstteki **+ Yeni …** düğmesi. Yetkiniz yoksa düğme görünmez.
- **Excel:** yönetim yetkisi olanlar listeyi Excel olarak indirebilir.
- **Kayıt ayrıntısı:** satıra tıklayın; ayrıntı sağ çekmecede veya kendi sayfasında açılır.

## Kayıt formları

- Zorunlu alanlar işaretlidir; eksik alan kaydı engeller ve ileti Türkçe olarak neyin eksik olduğunu söyler.
- **Kayıt kodları (ör. RSK-0001, BLG-2026-0007) sistem tarafından verilir** ve değiştirilemez.
- Kişi alanlarında (sahip, sorumlu, onaylayan) yazmaya başladığınızda kullanıcı dizininden öneri gelir.
- Bazı alanlar yalnızca iş akışıyla değişir (ör. onay durumu, risk sınıfı, kapanış tarihi); formda görünmez veya kilitlidir.
- **Değiştirilemez kayıtlar** vardır: kontrol test sonuçları, risk kararları, doküman revizyonları, tamamlanmış periyodik imha, denetim izi. Bunlar düzeltilmez; yeni kayıtla güncellenir. Bu, denetimde kanıt değeri taşır.

## Hızlı arama

Sağ üstteki **Hızlı arama** düğmesi (veya `Ctrl` + `K`) ekran adlarında ve kayıtlarda arar. Kod (ör. `BLG-2026`), ad veya konu yazın; sonuçtan ilgili ekrana gidin.

## Roller

| Rol | Kısaca |
|---|---|
| Yönetici | Her şeyi okur ve yazar; kullanıcıları, entegrasyonları ve politikaları yönetir. |
| Tedarikçi Yöneticisi | Tedarikçi, sözleşme, risk, süreç, doküman, KVKK ve veri yönetişimi kayıtlarını yönetir. Denetim sonucu yazamaz. |
| Birim Kullanıcısı | Her şeyi okur; yalnızca kendi biriminin kayıtlarını açar ve günceller. |
| Denetçi | Her şeyi okur; denetim, test sonucu, bulgu ve kanıt kayıtlarını yazar. |
| Görüntüleyici | Salt okur; kısıtlı kayıtları (ör. KVKK başvuruları) göremez. |

Rolünüze göre ayrıntılı kılavuz için Yardım ekranındaki **Rol kılavuzları** bölümüne bakın. Hangi rolün hangi kayıtta ne yapabildiğini Yönetici ve Denetçi **Yönetim → Rol ve Yetki Matrisi** ekranında görür.

## Bildirimler

Size bir iş atandığında, süre yaklaştığında veya onayınız gerektiğinde e-posta ve/veya Teams iletisi gider (kurum bu kanalları açtıysa). Her sabah açık işlerinizin özeti gelir. İletideki bağlantı doğrudan ilgili kayda götürür.

## Güvenlik ve kişisel veri

- Ortak bilgisayarda işiniz bitince **Çıkış** yapın.
- Kişisel veri gerektirmeyen alanlara kişisel veri yazmayın. Örneğin ilgili kişi başvurusunda ad yerine iç referans numarası yazın.
- Platform kaynak sistemlerdeki ham veriyi taşımaz; veri yönetişimi ekranlarında yalnızca meta veri (tablo, kolon adı, tip) ve sayılar bulunur.
- Her yazma işlemi kimin, ne zaman, neyi değiştirdiğiyle denetim izine kaydedilir.

## Sık sorulanlar

**Bir düğmeyi göremiyorum.** Rolünüz o işlemi yapmaya yetkili değildir veya kayıt sizin biriminize ait değildir. Gerekirse yöneticinize başvurun.

**"Yalnızca kendi biriminizin kayıtlarını değiştirebilirsiniz" iletisi aldım.** Birim Kullanıcısıysanız kayıttaki birim alanı sizin biriminiz olmalıdır. Birim atamanız eksikse yönetici Kullanıcılar ekranından ekler.

**Kendi hazırladığım kaydı onaylayamıyorum.** Bu bilinçli bir kuraldır (dört göz ilkesi): doküman, BİA, VKED, sözlük terimi, veri talebi, politika istisnası ve denetim planını hazırlayan kişi onaylayamaz.

**Bir kaydı silmek istiyorum.** Platformda silme yoktur; kayıtlar "kullanım dışı", "iptal", "kapatıldı" gibi durumlara alınır. Böylece geçmiş ve denetim izi korunur.

**Tarih ve saat hangi saat diliminde?** Ekranda tarayıcınızın saat dilimiyle gösterilir; sunucuda UTC olarak saklanır.
