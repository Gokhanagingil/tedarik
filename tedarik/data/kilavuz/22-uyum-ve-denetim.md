# Uyum ve denetim

> Menü: Uyum, Denetim. Kimler için: uyum ekibi, kontrol sahipleri, denetçiler, bulgu ve faaliyet sahipleri. Denetimin adım adım yürütülmesi "Denetçi kılavuzu"ndadır.

Uyum modülü "hangi kurala uymamız gerekiyor, bunu hangi kontrolle sağlıyoruz ve kontrol gerçekten işliyor mu" sorularını yanıtlar.

## Yapı taşları

```
Standart / mevzuat  →  Madde  ⇄  Kontrol  →  Test sonucu  →  Bulgu  →  Düzeltici faaliyet (DÖF)
                                    ↕
                   Süreç · Risk · Kontrol hedefi · Doküman · Kanıt
```

| Kavram | Açıklama |
|---|---|
| Standart | ISO/IEC 27001, NIST CSF, KVKK gibi uyulacak çerçeve. Kütüphaneden kurulur veya lisanslı kopyadan içe aktarılır. |
| Madde | Standardın gereksinimi. Kapsam dışı bırakılan madde gerekçe ister (uygulanabilirlik bildirimi). |
| Kontrol | Gereksinimi karşılayan kurum uygulaması: yöntem, sıklık, kritiklik, sahip, beklenen sonuç. Manuel veya otomatik. |
| Kontrol hedefi | Kontrolün hangi riski ele aldığını gösteren hedef. |
| Test sonucu | Kontrolün belirli bir anda işleyip işlemediği: başarılı, başarısız, belirsiz, uygulanamaz. Değiştirilemez. |
| Bulgu | Uyumsuzluk veya zayıflık; denetim, kontrol testi, tatbikat, öz değerlendirme, veri kalitesi gibi kaynaklardan doğar. |
| DÖF | Bulguyu gideren düzeltici/önleyici faaliyet. |

## Uyum Panosu

**[Uyum Panosu](#/compliance)** kapsamdaki her standart için şunları gösterir:

- **Madde kapsaması:** uygulanabilir maddelerin kaçı en az bir kontrole eşlenmiş.
- **Test tamamlanma:** kontrollerin kaçı sıklığına göre zamanında test edilmiş.
- **Başarı:** son test sonuçlarında başarılı oranı.

Bu bir **ön göstergedir**, sertifikasyon veya standart uygunluk kararı değildir.

## Kontrol kütüphanesi

Kontrolleri Yönetici tanımlar (Uyum → Kontroller). Kontrol ekranında **Eşlemeler** ile kontrolü standart maddelerine, süreçlere, kontrol hedeflerine, risklere ve dokümanlara bağlayın. Bir kontrol birden çok standardın maddesine eşlenebilir; böylece tek test birden çok standartta güvence sağlar.

**Otomatik kontroller** portal verisinden (ör. "aktif tedarikçilerin sahibi atanmış mı") veya MCP entegrasyonuyla dış sistemden çalışır. Sonuç "sistem" kaynaklıdır ve sorgu özetini kanıt olarak taşır. Aynı kontrolde açık otomatik bulgu varsa yenisi açılmaz, tekrar sayısı artar.

## Standart kütüphanesi ve çapraz eşleme

**[Standart Kütüphanesi](#/library)** kurulu standartları ve kurulabilir paketleri gösterir. Standart ekranında madde ağacı, uygulanabilirlik ve **Uygulanabilirlik bildirimi (SoA)** (CSV ve yazdırma) bulunur.

Standartlar arası madde ilişkileri (eşdeğer, alt küme, üst küme, kesişir, ilgili) bir maddedeki bulgunun başka hangi standartları etkilediğini gösterir. **Eşleme çalışma alanı** iki standardı yan yana açar; öneriler metin benzerliğine dayanır ve yalnızca siz onaylayınca kaydedilir.

## Yükümlülükler

**[Yükümlülükler](#/obligations)**: mevzuat ve sözleşme yükümlülükleri madde bazında. Uyum durumu eşlenen kontrollerin son sonucundan ve açık bulgulardan türetilir. Mevzuat değişince yükümlülük "inceleniyor" durumuna alınır.

## Politika istisnaları

Bir politikaya geçici olarak uyulamıyorsa **Politika İstisnaları → + Yeni**: gerekçe, kapsam, risk düzeyi, bitiş tarihi (en çok 365 gün). Yüksek ve kritik istisnada **telafi edici kontrol** zorunludur. **Talep eden veya istisnanın sahibi onaylayamaz.** Süresi dolan istisna kendiliğinden kapanır.

## Okundu beyanı

Yönetici bir doküman için **Okundu Beyanı Kampanyası** açar ve hedef birimleri seçer. Kişiler İşlerim'den dokümanı okuyup **Beyan ver** der; beyan değiştirilemez. Kampanya kapanınca sonuç dosyası kanıt olarak kaydedilir.

## Sertifikalar

**Sertifikalar**: belgelendirme kuruluşu, kapsam, geçerlilik ve gözetim denetimi tarihleri. Yaklaşan tarihler GRC Takvimi'nde görünür.

## Bulgular ve düzeltici faaliyetler

| Durum | Kim | Ne yapar |
|---|---|---|
| Bulgu açık | Denetçi / Yönetici | Bulguyu açar, önem ve hedef tarih verir; **Yanıt iste** |
| Yönetim yanıtı | Bulgu sahibi | **Yanıtla**: katılıyorum / kısmen / katılmıyorum ve gerekçe |
| DÖF açık | Faaliyet sahibi | **Çalışmaya başla**, çözümü yazar, **Doğrulamaya gönder** |
| Doğrulama | Denetçi / Yönetici (sahipten farklı) | **Etkinliği doğrula** veya geri gönder |
| Bulgu kapanışı | Denetçi / Yönetici | Açık DÖF kalmayınca kapanış notuyla kapatır |
| Risk kabulü | Yalnızca Yönetici | Bulgu "kabul edildi" |

Yüksek ve kritik bulguda hedef tarih boş bırakılamaz. Kapalı bulgu yeniden açılırken gerekçe yazılır.

## Kanıtlar

**Kanıtlar** kontrolün işlediğini gösteren belgelerdir: başlık, gizlilik (iç, gizli, kısıtlı), geçerlilik dönemi ve dosya. Her dosya yüklemesi değiştirilemez bir sürümdür; SHA-256 özeti saklanır ve her indirmede yeniden doğrulanır. **Kısıtlı** kanıtı yalnızca yükleyen, Denetçi ve Yönetici görür; diğerleri listede görmez.

## Erişim gözden geçirmeleri

1. Denetçi/Yönetici kampanya açar: sistem, kontrol, gözden geçirenler.
2. Liste dosyadan veya **Portal kullanıcılarını yükle** ile gelir.
3. Gözden geçirenler her satır için karar verir; kendi erişimine karar veremez, kaldırma gerekçe ister.
4. Tüm kararlar verilince **Tamamla ve kanıt üret**: sonuç dosyası kontrole kanıt olarak bağlanır. Kaldırma kararlarının uygulanması ayrı işaretlenir (**Uygulandı**).

## Denetim

Denetim yıllık plandan veya doğrudan açılır, kapsamı kontrol başına gruplanır, kanıt talepleri ve test sonuçlarıyla yürür, raporla kapanır. Adımlar "Denetçi kılavuzu"nda. **[Denetim Arşivi](#/archive)** geçmiş denetimleri madde veya konuyla arar.
