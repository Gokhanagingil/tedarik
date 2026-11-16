# Tedarikçi yönetimi

> Menü: Tedarikçi yönetimi. Kimler için: tedarikçi sahipleri, satın alma, birim sorumluları.

Tedarikçi modülü kimden ne aldığınızı, hizmetin ne kadar iyi verildiğini ve tedarikçinin taşıdığı riskleri izler.

## Temel kavramlar

| Kavram | Anlamı | Örnek |
|---|---|---|
| Tedarikçi | Tekil tüzel kişi. | Örnek Bilişim A.Ş. |
| Ürün ve Hizmet | Satın alınan şeyin katalog tanımı. | Veri merkezi barındırma |
| Angajman | Hangi birim, hangi ürün/hizmeti, hangi tedarikçiden, kimin için (iç birim veya müşteri), kimin sahipliğinde alıyor. | BT Altyapı → barındırma → Örnek Bilişim, sahibi ayse.yilmaz |
| Sözleşme Referansı | Sözleşmenin numarası, tarihleri ve sorumlusu; asıl belge kaynak sistemdedir. | SZL-2026-014, bitiş 31.12.2026 |
| SLA | Angajmana bağlı hizmet seviyesi hedefi. | Erişilebilirlik ≥ %99,9 (aylık) |

## Tedarikçi eklemek

1. **Tedarikçiler → + Yeni Tedarikçi**: ad, vergi numarası, ülke/şehir, sahip.
2. **Kritiklik** seçin: *kritik*, *önemli* veya *standart*. Kritiklik; performans değerlendirmesi, memnuniyet anketi ve risk gözden geçirme sıklığını belirler (sıklıklar Yönetim → Politika Parametreleri'nde).
3. **Segment** (stratejik, kaldıraç, darboğaz, rutin) isteğe bağlıdır.
4. Durum: aday → aktif → askıda / çıkış sürecinde → sonlandırıldı.

## Tedarikçi 360

Tedarikçiye tıklayınca tüm bilgileri tek ekranda görürsünüz: özet, angajmanlar, riskler, anketler, sözleşmeler, kişiler, **kişisel veri** (veri işleyen veya alıcı olduğu KVKK işleme faaliyetleri ve veri işleme sözleşmesi (DPA) durumu) ve **yapay zekâ** (sağladığı yapay zekâ sistemleri).

## Hizmet seviyesi (SLA)

1. **SLA Tanımları → + Yeni**: angajman, ad, birim (%, saat, dakika, adet), hedef, yön (yüksek iyi / düşük iyi), dönem.
2. **SLA Ölçümleri → + Yeni**: dönem başlangıcı ve gerçekleşen değer. "Karşılandı" sistemce hesaplanır. Ölçümler dosyayla (Yönetim → Aktarım) veya MCP entegrasyonuyla da gelebilir.
3. Art arda kaçırılan SLA, uyum modülündeki otomatik kontrolde başarısızlık olarak görünür.

## Performans

- **Performans Olayları:** SLA ihlali, kesinti, gecikme, eskalasyon ve takdir kayıtları.
- **Performans Değerlendirmeleri:** dönem başı ve sonu, kriter bazında puan (kriterler ve ağırlıkları Yönetim → Değerlendirme Kriterleri'nde) ve yorum.
- **[Değerlendirme takvimi](#/schedule):** kritiklik seviyesine göre zamanı gelen ve geciken değerlendirme ve anketler.

## Anketler

1. **Anket Şablonları → + Yeni**: amaç (memnuniyet, risk değerlendirme veya genel) ve sorular. **+ Soru ekle**: 1–5 ölçek, tavsiye (0–10), evet/hayır, tek seçim, çoklu seçim, metin, sayı, tarih. Seçeneklere puan verilebilir; "olumsuz soru" işaretli sorularda "Evet" düşük puan alır. **Önizle** ile katılımcının göreceği formu görün.
2. **Kampanya başlat**: değerlendirilen tedarikçiler, davetliler veya herkese açık katılım, açılış ve kapanış tarihleri.
3. Davetliler **Anketlerim** ekranında yanıtlar; yanıt taslak olarak kaydedilir, gönderildikten sonra değişmez.
4. Kampanya ekranında yanıt oranı ve tedarikçi bazında sonuçlar görünür. Risk amaçlı anketlerde düşük puan risk kaydına aktarılabilir.

Şablon yayımlandıktan sonra değiştirilmez; değişiklik için **Yeni sürüm oluştur**.

## Tedarikçi riski

Tedarikçi riski ayrı bir kayıt değildir: Risk Kaydı'nda tedarikçi seçilen kurumsal risktir. Tedarikçi 360'taki **Riskler** sekmesinden görünür. Ayrıntı "Risk yönetimi" kılavuzundadır.

## Uyum bağlantıları

Tedarikçi yönetimi için tanımlı otomatik kontroller portal verisinden çalışır: aktif tedarikçinin sahibi atanmış mı, kritik tedarikçi değerlendirmesi zamanında mı, tedarikçi riskleri gözden geçirilmiş mi, biten sözleşmenin sorumlusu belli mi, SLA art arda kaçırılıyor mu, kritik tedarikçi ankete konu olmuş mu. Sonuçlar Uyum Panosu'nda görünür.

## Kaynak bulma (kapalı modül)

İş ihtiyaçları ve teklifler ekranları kurumun süreç onayından sonra açılacaktır.
