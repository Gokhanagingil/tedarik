# Yönetici kılavuzu

> Kimler için: platformu kuran ve yöneten kişiler (rol: Yönetici). Önce "Başlarken" kılavuzunu okuyun.

Yönetici her modülde okur ve yazar. Bu kılavuz yalnızca Yöneticiye özgü işleri anlatır; modüllerin günlük kullanımı modül kılavuzlarındadır.

## İlk kurulum sırası

1. **Şirketler** (Yönetim → Şirketler): kendi grup şirketlerinizi ve risklerini izlediğiniz müşterileri ekleyin. Her risk, BİA, plan ve CMDB öğesi bir şirkete bağlanır.
2. **Birimler** (Yönetim → Birimler): iş birimlerini ekleyin. Birim Kullanıcıları yalnızca atandıkları birimin kayıtlarına yazar.
3. **Süreçler** (Mimari → Süreçler): yönetim, ana ve destek süreçleri. Risk, kontrol, BİA ve dokümanlar sürece bağlanır; Süreç Haritası buradan çizilir.
4. **Kullanıcılar** (Yönetim → Kullanıcılar): hesapları açın, rol ve birim atayın (aşağıda).
5. **Politika Parametreleri** (Yönetim → Politika Parametreleri): değerlendirme sıklıkları, süreler, eşikler. Süreç kuralları kodda değil buradadır.
6. **Entegrasyonlar** (Yönetim → Entegrasyonlar): e-posta, Teams, Entra ID, ServiceNow ve yapay zekâ bağlantıları.
7. **Risk Kriterleri ve Risk İştahı** (Risk yönetimi menüsü): olasılık/etki ölçekleri ve kategori bazında iştah.
8. **Standart Kütüphanesi** (Uyum menüsü): uyacağınız standart ve mevzuatı kurun veya içe aktarın.

## Kullanıcı yönetimi

**Yönetim → Kullanıcılar** ekranında:

- **+ Kullanıcı** ile yerel hesap açın: kullanıcı adı, görünen ad, rol ve birimler. Oluşturunca **geçici parola bir kez gösterilir**; kopyalayıp güvenli bir kanalla iletin. Kullanıcı ilk girişte parolasını değiştirmek zorundadır.
- Bir kullanıcıya tıklayıp rolünü, birimlerini ve e-posta adresini değiştirin. **Hesap aktif** işaretini kaldırmak açık oturumu hemen kapatır.
- **Geçici parola ver:** unutulan parola için. Eski parola ve açık oturumlar geçersiz olur. Kendi hesabınıza veremezsiniz.
- **Erişim süresi / dış denetçi:** hesaba bitiş tarihi verin. "Dış denetçi" işaretli hesap salt okunurdur ve yalnızca atandığı denetimleri görür.

**Kurumsal giriş (Entra ID) açıksa** kullanıcı ilk girişte otomatik açılır; rol Entra uygulama rolünden gelir (`KS.TDR.Admin`, `KS.TDR.SupplierManager`, `KS.TDR.UnitUser`, `KS.TDR.Auditor`, `KS.TDR.Viewer`). Burada yalnızca birim ataması yapılır ve hesap devre dışı bırakılır.

## Rol ve yetki matrisi

**Yönetim → Rol ve Yetki Matrisi** (Kullanıcılar ekranında da düğmesi var) her rolün her kayıt türünde ne yapabildiğini gösterir. Matris çalışan yazılımın yetki tanımlarından hesaplanır, yani her sürümde günceldir; yetki vermez, yalnızca gösterir.

- **Rol kartları:** rolün açıklaması, kullanıcı sayısı, kaç kayıt türüne yazabildiği ve Entra rol adı. Karta tıklamak o rolün sütununu vurgular.
- **Kaynak matrisi:** "Yazar", "Birimine yazar", "Ekler" (değiştirilemez kayıt), "Okur" ve "—" (erişemez). "Yazma yolu" kaydın formla mı, yalnızca iş akışıyla mı değiştiğini gösterir.
- **Görevler ayrılığı:** platformun zorunlu kıldığı dört göz kuralları ve dayanakları.
- **Özel kimlikler:** dış denetçi, MCP anahtarı, veri toplayıcı anahtarı.
- **Rollere göre kullanıcılar** ve **CSV indir**: erişim gözden geçirmelerinde ve denetimde kanıt olarak kullanın.

## Entegrasyonlar

**Yönetim → Entegrasyonlar** ekranında her bağlantı ayrı karttır. Bilgileri girin, **Sına** ile uçtan uca deneyin, sonra etkinleştirin.

| Bağlantı | Ne sağlar |
|---|---|
| E-posta (SMTP) | Atama, süre ve onay bildirimleri; günlük iş özeti. |
| Microsoft Teams | Kanal bildirimleri (Workflows web kancası). |
| Entra ID + MFA | Kurumsal giriş ve çok adımlı doğrulama. |
| ServiceNow (Table API veya MCP) | CMDB senkronu (salt okunur). |
| Yapay zekâ | Risk ifadesi, eşleme ve rapor taslağı önerileri (insan onaylı). |

Parola ve anahtarlar şifreli saklanır, ekranda bir daha gösterilmez. Sunucu kurulum dosyasıyla verilmiş bir bağlantı arayüzden değiştirilemez.

## Bildirimler

**Yönetim → Bildirimler** gönderim kutusudur: bekleyen, gönderilen ve hata alan iletiler. İletiler 10 dakikada bir gönderilir. Bir ileti hata aldıysa kanal ayarını Entegrasyonlar'da düzeltip yeniden deneyin.

## Politika parametreleri

**Yönetim → Politika Parametreleri** süreç kurallarını tutar: tedarikçi değerlendirme ve anket sıklıkları, uyarı süreleri, KVKK başvuru süresi (30 gün), periyodik imha aralığı (en çok 6 ay), veri kalitesi eşikleri gibi. Değerler JSON biçimindedir; açıklama sütunu her değerin anlamını yazar. Değişiklik denetim izine girer.

## Ana veri ekranları

Yönetim menüsündeki diğer ekranlar: **Tedarikçi Tipleri**, **Değerlendirme Kriterleri**, **Kişisel Veri Kategorileri** (KVKK keşif sözlüğü), **İlgili Kişi Grupları**, **İçe Aktarım Kayıtları**, **CMDB Senkron Çalıştırmaları**.

## Toplu aktarım

**Yönetim → Aktarım** Excel (XLSX) veya CSV ile içe ve dışa aktarır:

1. Kayıt türünü seçin, **Şablonu indir** ile başlıkları alın.
2. Dosyayı yükleyin ve **Dene (kayıt yazmaz)** ile sonucu görün: kaç kayıt eklenecek, güncellenecek, hangi satırlarda hata var.
3. Sonuç doğruysa **Uygula**.

Var olan kayıtta yalnızca boş alanlar doldurulur; platformda girilmiş değer korunur. Kodlar yalnızca var olan kaydı bulmak için okunur. **Tüm portal (tek Excel)** bütün verinin yedeğini tek dosyada verir.

## Standart kütüphanesi

**Uyum → Standart Kütüphanesi**:

- **Kur:** tam metniyle dağıtılabilen paketler (NIST SP 800-53, NIST CSF 2.0, KVKK, GDPR). Kaynak adresi ve dosya özeti (SHA-256) kayıtlıdır; yeni sürüm gelince düğme **Güncelle** olur ve kurumun uygulanabilirlik kararları korunur.
- **Lisanslı metni içe aktar:** ISO, TS EN, PCI DSS, CIS gibi telifli standartları kurumun lisanslı kopyasından Excel/CSV ile yükleyin. Kısmi metin yüklemeyin.
- Kurulan standart başvuru amaçlıdır; uyum panosunda sayılması için standart ekranında **Uyum kapsamına al**'a basın.
- **Çapraz eşleme içe aktar** ve **Eşleme çalışma alanı:** standartlar arası madde ilişkileri.

## Denetim izi

**Yönetim → Denetim İzi** her yazma işlemini kim, ne zaman, hangi kayıtta, neyi değiştirdi bilgisiyle gösterir. Kayıtlar değiştirilemez; gizli alanlar maskelenir. Denetçi ve Tedarikçi Yöneticisi de okuyabilir.

## Yol haritası

**Yönetim → Yol Haritası** platformun modül ve faz bazında planını gösterir. "Bilgi bekleniyor" maddeleri kurumdan bilgi veya onay gelince ilerler. **+ Kurum maddesi** ile kendi isteklerinizi ekleyebilirsiniz.

## Yalnızca Yöneticinin yapabildikleri

- Bulgu riskini kabul etmek (bulgu durumu "Kabul edildi").
- Kontrol ve kontrol hedefi kütüphanesini düzenlemek.
- CMDB öğelerini elle düzenlemek; şirket, birim, süreç ve politika ana verisi.
- Risk iştahı ve risk kriterleri.
- Okundu beyanı kampanyaları.

## Kontrol listesi: aylık

- [GRC Sağlık Kontrolü](#/health) ekranındaki yüksek önemli maddeleri gözden geçirin.
- Bildirimler kutusunda hata alan ileti var mı bakın.
- Rol ve yetki matrisinden rollere göre kullanıcıları indirip ayrılan çalışanları devre dışı bırakın.
- Süresi dolacak dış denetçi hesaplarını kontrol edin.
