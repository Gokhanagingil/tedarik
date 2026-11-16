# Denetçi kılavuzu

> Kimler için: iç denetçiler, uyum testlerini yapanlar ve dış denetçiler (rol: Denetçi).

Denetçi tüm kayıtları okur; denetim, kontrol testi sonucu, bulgu, kanıt ve kanıt talebi, sertifika, erişim gözden geçirme ve denetim evreni kayıtlarını yazar. Düzeltici faaliyetin etkinliğini doğrular. Diğer kayıtlarda (tedarikçi, risk, doküman vb.) salt okurdur.

## Denetim yaşam döngüsü

### 1. Yıllık plan

**Denetim → [Denetim Planı](#/audit-plan)** risk bazlı yıllık iç denetim planıdır. Denetim evrenindeki birimler (süreç, şirket, tedarikçi, uygulama, yönetim sistemi) öncelik puanına göre sıralanır:

- doğal risk (8–40) + bağlı en yüksek açık risk (0–30) + açık bulgular (0–15) + son denetimden geçen süre (0–15).

Plan kalemlerini seçin, planı onaya gönderin. **Planı hazırlayan onaylayamaz**; başka bir yetkili **Planı onayla** der. Plan kalemleri **Denetim aç** ile denetime dönüşür ve gerçekleşme izlenir.

### 2. Denetimi kurmak

Denetim ekranında kapsamı belirleyin: standartlar ve maddeler, süreçler, tedarikçi (tedarikçi denetimiyse). **Kapsamı oluştur** kapsamdaki maddeleri kontrol başına gruplar: her kontrol bir kez test edilir ve sonucu eşlendiği tüm standart maddelerine sayılır (entegre denetim). Kontrolü olmayan maddeler ilişkilerine göre soru gruplarına ayrılır.

**Denetimi başlat** ile denetim "devam ediyor" olur. Çalışma alanında aynı kapsamın önceki denetimleri ve kontrol başına geçmiş sonuçlar görünür.

### 3. Kanıt istemek

- **Plan kontrolleri için kanıt iste** veya kontrol satırından **Kanıt iste**. Talep kontrol başına açılır ve kanıtın sayılacağı tüm standart maddelerini listeler; böylece aynı kanıt farklı standartlar için tekrar istenmez.
- Kişi yeni dosya yükler veya mevcut güncel kanıtı gösterir. Siz **Kabul et** veya gerekçeyle **İade et**.
- İncelenmemiş teslim varken denetim tamamlanamaz.

### 4. Test etmek ve sonuç yazmak

Kontrol satırında sonucu kaydedin: **başarılı, başarısız, belirsiz, uygulanamaz**; örneklem büyüklüğü, istisna sayısı, açıklama ve kanıt. Sonuç **değiştirilemez** kayıttır: kontrolün o anki tanımı ve kanıt sürümleri (SHA-256) sonuçla birlikte dondurulur. Yanlış sonuç girdiyseniz yeni bir sonuç kaydedin; eski kayıt iz olarak kalır.

Otomatik kontroller (portal verisinden veya MCP ile) **Otomatik kontrolleri çalıştır** ile çalışır; sonuçları "sistem" kaynaklıdır.

### 5. Çalışma kâğıtları

**+ Çalışma kâğıdı**: test adımları, örneklem, sonuç. Kâğıdı hazırlayandan **farklı bir denetçi** gözden geçirir (IIA 2340); gözden geçirilmiş kâğıt değişmez. Politika açıksa gözden geçirilmemiş kâğıt denetimin tamamlanmasını engeller.

### 6. Bulgular

Başarısız sonuçtan veya **+ Bulgu** ile bulgu açın: başlık, önem, madde, kontrol, sahip, hedef tarih. Yüksek ve kritik bulguda hedef tarih zorunludur.

- **Yanıt iste:** bulgu sahibinden yönetim yanıtı istenir (katılıyorum / kısmen / katılmıyorum ve gerekçe).
- **Bulgu etkisi:** bulgunun maddesi ve kontrolünün eşlendiği maddeler doğrudan; eşdeğer ve kapsayan maddeler kesin; kesişen ve ilgili maddeler olası etkilenir. Bulgu ekranında hangi standartların hangi maddelerinin etkilendiğini görürsünüz.
- Bulgu, açık düzeltici faaliyeti varken kapanmaz; kapatmak için kapanış notu gerekir. Bulgu riskinin kabulü yalnızca Yöneticidedir.

### 7. Düzeltici faaliyetin (DÖF) etkinliğini doğrulamak

Sahip faaliyeti "doğrulama"ya gönderdiğinde İşlerim'e düşer. Etkinliği inceleyin ve **Etkinliği doğrula** veya geri gönderin. **Faaliyet sahibi kendi faaliyetini doğrulayamaz.**

### 8. Rapor ve tamamlama

**Rapor** düğmesi denetim raporunu değiştirilemez kayıtlardan üretir: kapsam, sonuçlar, bulgular, görüş. Yönetici özetini düzenleyin (yapay zekâ açıksa **Özet taslağı oluştur**), **Yazdır / PDF** ile çıktı alın. **Tamamla** denetimin planını dondurur.

## Denetim arşivi

**Denetim → [Denetim Arşivi](#/archive)**: madde kodu (ör. `A.5.19`, `8.3.4`) veya konu (ör. "yedekleme", "erişim") yazın. Hangi denetimde hangi kontrolün test edildiğini, sonucunu ve sunulan kanıt sürümünü görürsünüz. Arşiv yalnızca okur.

## Uyum çalışmaları

- **Uyum Panosu:** kontrol testlerine dayalı kapsama, test tamamlanma ve başarı oranı. Sertifikasyon kararı değil, ön göstergedir.
- **Uygulanabilirlik Bildirimi (SoA):** standart ekranından; CSV ve yazdırma.
- **Sertifikalar:** belge, kapsam, geçerlilik ve gözetim denetimi tarihleri.
- **Erişim gözden geçirmeleri:** kampanya açın, listeyi dosyadan veya portal kullanıcılarından yükleyin; kararlar tamamlanınca sonuç dosyası kanıt olarak kontrole bağlanır.
- **KVKK / GDPR Boşluk Analizi:** maddelerin durumunu okursunuz ve açık maddeden **Bulgu aç** dersiniz (değerlendirmeyi uyum sorumlusu girer).

## Erişim tasarımını denetlemek

**Yönetim → Rol ve Yetki Matrisi** her rolün her kayıt türündeki yetkisini, görevler ayrılığı kurallarını ve rollere göre kullanıcıları gösterir. **CSV indir** ile çalışma kâğıdınıza kanıt olarak ekleyin. Denetim izi (Yönetim → Denetim İzi) her yazma işlemini değiştirilemez biçimde tutar.

## Dış denetçi hesabı

Dış denetçi işaretli hesaplar:

- **Salt okunurdur**; hiçbir kaydı yazamaz.
- **Yalnızca atandığı denetimleri**, bunların kanıtlarını ve bulgularını görür; diğer denetimler görünmez.
- Hesabın bitiş tarihi vardır; tarih geçince giriş yapılamaz.
- Rol ve yetki matrisini göremez.
