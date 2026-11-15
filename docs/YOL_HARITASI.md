# GRC Platformu — Uzman Değerlendirmesi ve Yol Haritası

Bu belge, platformun bugünkü kapsamını olgun bir kurumsal GRC programının ihtiyaçlarıyla karşılaştırır ve eksikleri
önceliklendirir. Bakış açısı: ISO 31000, ISO/IEC 27001, ISO 22301, ISO 9001, COSO ERM ve COBIT ile çalışan; üç
savunma hattı modelinde birinci hat (süreç sahipleri), ikinci hat (risk, uyum, bilgi güvenliği) ve üçüncü hat (iç
denetim) için araç kuran bir uygulayıcı. Türkiye bağlamı: KVKK, BDDK Bilgi Sistemleri ve Elektronik Bankacılık
Yönetmeliği, SPK ve TCMB ödeme hizmetleri düzenlemeleri; AB'deki müşteriler için NIS2 ve DORA.

Güncel yol haritası artık uygulamanın içindedir: **Yönetim → Yol Haritası** (kaynak: `tedarik/data/roadmap.json`, K-028).
Bu belge ilk uzman değerlendirmesini ve gerekçeleri saklar.

## Durum (2026-11-15)

Aşağıdaki eksiklerden yapılanlar: kanıt talep listesi (PBC), risk bazlı yıllık plan, çalışma kâğıtları ve gözden geçirme
imzası, denetim raporu ve yönetim yanıtı, dış denetçi erişimi, SoA raporu, sertifika takibi, yükümlülük envanteri,
politika istisnaları, okundu beyanı, ortak kontrol çerçevesi ve standartlar arası madde ilişkileri, RCSA, olay ve kayıp
veritabanı, kişisel veri ihlali kaydı (72 saat), nicel risk (Monte Carlo, TL), erişim gözden geçirme kampanyaları,
kriz yönetimi modu, bildirim altyapısı (e-posta, Teams), DÖF → ServiceNow görev eşlemesi, insan onaylı yapay zekâ
yardımı (K-023 – K-027). Veri yönetişimi Faz 1 (veri sözlüğü ve katalog) tamamlandı; Faz 2 KVKK envanteri ve sınıflandırmadır.
Kalanlar: zafiyet bulguları
entegrasyonu, yapılandırılabilir onay akışları, rapor şablonları ve PDF/Excel, denetim izinin dışarıdan doğrulanması,
İngilizce arayüz, Entra gruplarından birim ataması, tedarikçi riskinde dış istihbarat.

## Bugün olanlar (özet)

Kurumsal risk (şirket bazında, kriterler, iştah/tolerans, dönemler, KRİ, değişmez değerlendirme ve kararlar), kontrol
kütüphanesi ve çoklu standart eşlemesi, kontrol hedefleri, denetim yaşam döngüsü, değiştirilemez test sonuçları ve
kanıt sürümleri, denetim arşivi, bulgu → DÖF (görevler ayrılığı), iş sürekliliği (BİA, plan, tatbikat), doküman
yönetimi, süreç haritası, CMDB (Table API ve MCP) ve CI risk kuralları, tedarikçi yönetimi ve anketler, GRC takvimi,
İşlerim, sağlık kontrolü, ilişki haritası, Entra ID + MFA, denetim izi.

## Eksikler — önem sırasıyla

### 1. Güvence (üçüncü hat ve dış denetim)
- **Kanıt talep listesi (PBC — "provided by client").** Denetçi bir denetim için kanıt ister; talep kontrol sahibine
  atanır, son tarih ve durum izlenir, yüklenen kanıt doğrudan denetime ve kontrole bağlanır. Denetim arşivinin doğal
  tamamlayıcısıdır ve denetim haftalarındaki e-posta trafiğini ortadan kaldırır. **En yüksek getirili eksik.**
- **Risk bazlı yıllık denetim planı (audit universe).** Denetlenebilir birimler (süreç, şirket, tedarikçi, uygulama),
  bunların risk puanı ve son denetim tarihine göre önceliklendirilmiş yıllık plan; plan–gerçekleşme takibi.
- **Çalışma kâğıtları ve gözden geçirme imzası.** Test adımı, örneklem, sonuç; ikinci denetçinin gözden geçirme
  onayı (IIA standartları 2340).
- **Denetim raporu üretimi ve yönetim yanıtı.** Bulguya yönetimin yanıtı (kabul, eylem planı, hedef tarih) iş akışı;
  denetim raporunun PDF/DOCX olarak üretimi.
- **Dış denetçi erişimi.** Süreli, kapsamla sınırlı, salt okunur denetçi hesabı (sertifikasyon ve düzenleyici denetimleri).
- **Uygulanabilirlik Bildirimi (SoA) raporu** ve sertifika/gözetim denetimi takibi.

### 2. Uyum (ikinci hat)
- **Yükümlülük envanteri.** Mevzuat ve sözleşme yükümlülükleri (madde bazında), yükümlülük → kontrol → kanıt eşlemesi,
  mevzuat değişikliği etki analizi. Standart maddeleri bugün var; mevzuat yükümlülükleri ayrı bir kayıt türü olmalı.
- **Politika istisnaları (muafiyetler).** Gerekçe, telafi edici kontrol, süre, onaylayan ve otomatik bitiş; risk
  kabulüyle ilişki. Denetimlerde en sık sorulan kayıtlardandır.
- **Politika okundu/kabul beyanı (attestation)** ve farkındalık eğitimi kayıtları (ISO 27001 7.3, 7.2).
- **Ortak kontrol çerçevesi içe aktarımı.** Standartlar arası eşleme kütüphaneleri (ISO 27001 ↔ NIST CSF ↔ CIS ↔
  BDDK) ile bir kez test edilen kontrolün birden çok çerçeveye kanıt olması.

### 3. Risk (ikinci hat)
- **Risk ve kontrol öz değerlendirmesi (RCSA).** Süreç sahiplerinin dönemsel öz değerlendirmesi; anket motoru hazır,
  risk ve kontrol kayıtlarına bağlanacak bir kampanya türü yeterli.
- **Olay ve kayıp veritabanı.** Operasyonel olaylar, gerçekleşen kayıp tutarları, kök neden; risk değerlendirmesinin
  gerçek veriyle kalibrasyonu. ITSM'deki büyük olaylar MCP ile beslenebilir.
- **Bilgi güvenliği olayı ve kişisel veri ihlali kaydı.** KVKK 72 saat bildirim süresi, bildirim kararı ve kanıtı.
- **Nicel risk analizi (FAIR, Monte Carlo)** — yönetim kuruluna TL cinsinden beklenen kayıp; ilk aşamada en kritik 10 risk için.
- **Risk eğilimi ve yönetim kurulu raporu.** Dönemler arası karşılaştırma, iştah aşımı trendi, tek sayfalık rapor.
- **Tedarikçi riski derinleştirme.** Dış istihbarat (siber güvenlik puanı, mali puan), dördüncü taraf (alt yüklenici)
  haritası, sözleşme güvenlik maddeleri kontrol listesi, çıkış planı testi.

### 4. BT ve siber güvenlik
- **Erişim gözden geçirme kampanyaları** (Entra grupları ve uygulama rolleri; yöneticinin onay/ret kararı → kanıt).
- **Zafiyet bulguları entegrasyonu** (tarayıcı sonuçlarından CI maruziyeti; CMDB kuralları gibi).
- **Veri envanteri ve sınıflandırma** — planlanan veri yönetişimi modülüyle: veri varlığı, sahibi, sınıfı, işlendiği
  uygulama (CMDB), KVKK işleme envanteri (VERBİS), saklama süresi; BİA'daki "hayati kayıtlar" ile bağ.

### 5. İş sürekliliği
- **Kriz yönetimi modu.** Olay anında planı devreye alma, adım bazında görev takibi, karar ve iletişim günlüğü,
  çağrı ağacı yanıt takibi; olay sonrası raporun tatbikat kaydına dönüşmesi.
- **Kaynak gereksinimleri** (personel, tesis, ekipman, tedarikçi) ve kurtarma stratejisi seçenekleri ile maliyeti.

### 6. Platform
- **Bildirim ve eskalasyon** (e-posta ve Teams): yaklaşan ve geciken işler, onay talepleri; bugün yalnızca uygulama içi.
- **Yapılandırılabilir onay akışları** (workflow modülü hazır, kapalı).
- **Raporlama:** zaman serisi göstergeler, kaydedilebilir rapor şablonları, PDF/Excel çıktısı.
- **Değiştirilmezliğin dışarıdan doğrulanması:** denetim izinin karma zinciri veya zaman damgası (RFC 3161).
- **Entegrasyonlar:** bulgu/DÖF → ServiceNow görev senkronu; Entra gruplarından birim ataması.
- **İngilizce arayüz** (AB müşterileri ve dış denetçiler) ve erişilebilirlik (WCAG 2.1 AA).
- **Yapay zekâ yardımı (insan onaylı):** kanıt–kontrol eşleme önerisi, risk ifadesi kalite denetimi, standart veya
  mevzuat değişikliğinde boşluk analizi, denetim raporu taslağı.

## Önerilen sıra

| Faz | Süre | İçerik | Gerekçe |
| --- | --- | --- | --- |
| 1 | 0–3 ay | Kanıt talep listesi (PBC), bildirimler, politika istisnaları, yükümlülük envanteri, SoA raporu | Denetim ve uyum ekiplerinin günlük yükünü en çok azaltan, mevcut modele küçük eklemeler |
| 2 | 3–6 ay | Veri yönetişimi modülü, olay/kayıp ve KVKK ihlal kaydı, RCSA, erişim gözden geçirme | Düzenleyici beklenti ve veri yönetişimi görüşmesiyle birlikte |
| 3 | 6–9 ay | Risk bazlı denetim planı, çalışma kâğıtları, denetim raporu, dış denetçi erişimi | Üçüncü hattın tüm yaşam döngüsü |
| 4 | 9–12 ay | Nicel risk, kriz yönetimi modu, ServiceNow görev senkronu, yapay zekâ yardımı | Olgunluk artırıcılar |

Her faz bugünkü ilkeleri korur: kayıt silinmez, değerlendirme ve kararlar değişmez, her yazma iz bırakır, kodlar
sunucuda üretilir, kurallar politikada durur.
