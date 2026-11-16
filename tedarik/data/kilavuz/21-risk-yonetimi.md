# Risk yönetimi (ISO 31000)

> Menü: Risk yönetimi. Kimler için: risk sahipleri, risk yönetimi ekibi, birim yöneticileri.

Kurumun tüm riskleri — operasyonel, bilgi güvenliği, tedarikçi, uyum, CMDB kaynaklı teknik riskler, müşteri riskleri — **tek risk kaydında** tutulur. Her risk bir şirkete (kendi grup şirketimiz veya müşterimiz) bağlıdır; Risk Panosu'nda şirket seçerek ayırabilirsiniz.

## Süreç

| ISO 31000 adımı | Platformda |
|---|---|
| Bağlam ve kriterler | Risk Kriterleri (olasılık/etki ölçekleri), Risk İştahı (kategori bazında) |
| Tanımlama | Risk Kaydı: neden → olay → etki, risk türü (tehdit/fırsat), kategori, şirket, birim, süreç |
| Analiz ve değerlendirme | Değerlendirme: içsel risk, kontrol katkısı, artık risk; iştahla karşılaştırma |
| İşleme | Strateji (azalt, kaçın, paylaş, üstlen, fırsatı değerlendir) ve Risk İşleme Faaliyetleri |
| İzleme ve gözden geçirme | Gözden geçirme tarihi, Risk Değerlendirme Dönemleri, Anahtar Risk Göstergeleri (KRİ) |
| Kayıt ve raporlama | Değiştirilemez değerlendirme ve kararlar, ısı haritası, Risk Panosu |

## Risk açmak

1. **Risk Kaydı → + Yeni** veya **Risk Kataloğu**'ndan bir senaryo seçip **Bu senaryodan risk aç**.
2. Risk ifadesini üç parçada yazın:
   - **Neden:** "Yedekleme işlerinin başarısını izleyen bir kontrol olmaması nedeniyle"
   - **Olay:** "kritik sistem verisinin geri yüklenememesi"
   - **Etki:** "hizmetin 24 saatten uzun kesilmesine ve sözleşme cezalarına yol açabilir."
3. **İfade kalitesi** düğmesi ifadeyi denetler (eksik neden/etki, belirsiz kelimeler) ve öneri verir.
4. Şirket, birim, süreç, kategori, sahip ve tedarikçi (varsa) seçin. Tedarikçisi olmayan risk "etkilenen varlık / hizmet" ister.

## Değerlendirmek

**Değerlendirme gir**: olasılık ve etkiyi (1–5) işaretleyin. Sistem içsel riski, bağlı kontrollerin katkısını ve artık riski hesaplar; artık riski kategorinin iştahıyla karşılaştırır. Her değerlendirme **değiştirilemez** bir kayıttır ve o anki iştahı da saklar; risk değiştikçe yeniden değerlendirilir.

Ölçeklerin kurumunuzdaki anlamı **Risk Kriterleri** ekranındadır (ör. etki 4 için "bir günü aşan kesinti" gibi bir tanım). Değerlendirmeyi kişisel yoruma değil bu tanımlara göre yapın; böylece farklı kişilerin puanları karşılaştırılabilir olur.

## İşlemek

- **Strateji** seçin: azalt, kaçın, paylaş/devret, üstlen (kabul et), fırsatı değerlendir.
- **+ Faaliyet**: sorumlu, hedef tarih, açıklama. Faaliyetler İşlerim'e düşer.
- Riski kontrollerle ilişkilendirin; kontrol testi başarısız olursa risk değerlendirmesi yeniden ele alınmalıdır.
- **Riski kabul et:** gözden geçirme tarihi ister. Artık risk iştahın üzerindeyse kabulü, değerlendirmeyi yapandan **farklı bir Yönetici** onaylar.
- Açık faaliyeti olan risk kapanmaz.

## İzlemek

- **Anahtar Risk Göstergeleri (KRİ):** gösterge, sarı ve kırmızı eşik, ölçüm sıklığı. Ölçüm girildiğinde durum (yeşil/sarı/kırmızı) sistemce hesaplanır ve değiştirilemez. Kırmızı gösterge riskin yeniden değerlendirilmesi gerektiğini bildirir.
- **Risk Değerlendirme Dönemleri:** ör. "2026 2. yarıyıl". Dönem içinde değerlendirilen riskler ilerlemeyi gösterir.
- **Gözden geçirme tarihi** geçen riskler İşlerim ve GRC Sağlık Kontrolü'nde görünür.

## Öz değerlendirme (RCSA)

1. **Öz Değerlendirme (RCSA) → + Yeni**: kapsam (süreç, birim, şirket), son tarih, talimat.
2. **Kampanyayı aç**: kapsamdaki açık riskler ve manuel kontroller sahiplerine atanır.
3. Sahipler riskin olasılık/etkisini ve kontrolün işleyişini değerlendirir.
4. Öz değerlendirme resmî değerlendirmeyle karşılaştırılır; 6 puan ve üzeri sapma işaretlenir. "Etkin değil" denilen kontrol tek adımda bulguya dönüştürülür.
5. **Kampanyayı kapat**.

## Kayıp olayları ve nicel risk

- **Kayıp Olayları:** gerçekleşen operasyonel olaylar (Basel II olay türleri), brüt kayıp, geri kazanım; net kayıp sistemce hesaplanır. Olayı ilgili riske bağlayın.
- **Nicel analiz** (risk ekranında "Nicel ve kayıplar" sekmesi): yıllık olay sıklığı ve olay başı kayıp için en az / en olası / en çok tahmin girin, **Hesapla**. Platform FAIR yaklaşımıyla 10.000 senaryoluk Monte Carlo benzetimi yapar ve beklenen yıllık kaybı ile yüzdelikleri (ör. %95) gösterir. Sonuç değiştirilemez kayıttır; aynı girdi aynı sonucu verir. Risk Panosu'nda en yüksek 25 riskin birleşik (portföy) dağılımı görünür.

## Risk Panosu

**[Risk Panosu](#/risk)**: ısı haritası (hücreye tıklayınca riskler listelenir), iştah aşımları, kategori dağılımı, değerlendirme dönemleri, KRİ durumları. Şirket seçerek kendi şirketlerinizin veya müşterilerinizin risklerini ayırın.

## Diğer modüllerden gelen riskler

- **CMDB:** destek dışı yazılım, eksik kritik yama ve uzun süre yeniden başlatılmayan sunucular şirket bazında risk açar; etkilenen CI'lar riske bağlanır.
- **Anketler:** risk amaçlı anketlerin düşük puanları riske aktarılabilir.
- **Veri yönetişimi:** veri varlığının risk puanı **Risk kaydına aktar** ile riske dönüşür.
