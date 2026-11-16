# Yapay zekâ envanteri (AB Yapay Zekâ Tüzüğü)

> Menü: Veri yönetişimi → Yapay Zekâ Envanteri. Kimler için: yapay zekâ kullanan birimler, BT, uyum ve veri koruma ekipleri.

Kurumun geliştirdiği, satın aldığı veya hizmet olarak kullandığı her yapay zekâ sistemi burada kayıtlıdır: ne için kullanıldığı, hangi veriyle çalıştığı, AB Yapay Zekâ Tüzüğü'ne (Tüzük (AB) 2024/1689) göre risk sınıfı ve bu sınıfın getirdiği yükümlülükler.

## Neyi kaydetmeliyim?

Kişiler veya iş kararları üzerinde etkisi olan her sistemi: sohbet botları ve sanal asistanlar, aday eleme ve performans değerlendirme araçları, kredi/limit puanlama, fiyatlama, müşteri kaybı tahmini, belge okuma ve sınıflandırma, öneri motorları, görüntü ve ses tanıma, büyük dil modeli kullanan iç araçlar. Satın alınan ve hizmet olarak kullanılanlar da dâhildir.

## 1. Sistem kaydı

**[Yapay Zekâ Envanteri](#/ai) → + Yapay zekâ sistemi**:

| Alan | Örnek |
|---|---|
| Sistem adı, kullanım amacı | "Aday ön eleme asistanı", "Özgeçmişleri ilan kriterlerine göre puanlamak" |
| Kurumun rolü | **Kullanıcı (deployer)**: başkasının sistemini kullanıyorsunuz. **Sağlayıcı**: sistemi geliştirip kendi adınızla sunuyorsunuz. |
| Kaynağı, tedarikçi | Satın alınan / hizmet ise tedarikçiyi seçin (sözleşme, DPA ve tedarikçi riski izlenir). |
| Model türü | Klasik makine öğrenmesi, derin öğrenme, büyük dil modeli, görüntü, ses, öneri, kural tabanlı |
| Yaşam döngüsü | Fikir → geliştirme → pilot → kullanımda → kullanımdan kalktı |
| İş sahibi, teknik sorumlu, birim, süreç, CMDB öğesi | |
| Kişisel veri, özel nitelikli veri, kişi hakkında otomatik karar | İşaretleyin; KVKK/GDPR açıklarını belirler. |
| İnsan gözetimi | "Ret önerileri İK uzmanınca incelenir; aday itiraz edebilir." |
| Şeffaflık bildirimi, kayıt (log) saklama süresi, işleme faaliyeti, VKED, FRIA tarihi, son değerlendirme | |

Birim Kullanıcısı kendi biriminin sistemini kaydedebilir.

## 2. Risk sınıflandırma sihirbazı

Sistem ekranında **Sınıflandır**. Risk sınıfı elle girilmez; yedi adımlık sihirbaz Tüzüğün sırasını izler:

1. **Yasaklı uygulamalar (md. 5):** manipülasyon, kırılganlık istismarı, sosyal puanlama, yalnızca profile dayalı suç tahmini, hedefsiz yüz görüntüsü toplama, iş yerinde/eğitimde duygu tanıma, hassas özelliklere göre biyometrik sınıflandırma, kamuya açık alanda gerçek zamanlı uzaktan biyometrik tanımlama. Biri bile işaretlenirse sistem **yasaklıdır**.
2. **Ürün güvenliği (md. 6(1), Ek I):** sistem üçüncü taraf uygunluk değerlendirmesine tabi bir ürünün güvenlik bileşeni mi?
3. **Yüksek riskli alanlar (Ek III):** biyometri, kritik altyapı, eğitim, istihdam, kamu hizmetlerine uygunluk, kredi değerliliği, hayat/sağlık sigortası, acil çağrılar, kolluk, göç, yargı.
4. **md. 6(3) istisnası:** Ek III alanında olsa da dar kapsamlı usul görevi, tamamlanmış insan işini iyileştirme, örüntü tespiti veya hazırlık görevi ise yüksek riskli sayılmaz — **gerçek kişilerin profilini çıkaran sistemde istisna uygulanmaz.**
5. **Kullanıcı durumu:** kamu kurumu veya kamu hizmeti sunan kuruluş musunuz (temel haklara etki değerlendirmesi)?
6. **Şeffaflık (md. 50):** kişilerle etkileşim (sohbet botu), sentetik içerik, duygu tanıma, derin sahte içerik, kamuya yönelik metin.
7. **Genel amaçlı model sağlayıcısı mısınız?**

**Sınıflandır ve kaydet**: sonuç (yasaklı, yüksek risk, sınırlı risk, asgari risk), **dayanak maddeler** ve kurumun rolüne göre **yükümlülük listesi** kayda yazılır; kim, ne zaman sınıflandırdı görünür. Yanıtlar değiştiğinde yeniden sınıflandırın.

Örnek: "Aday ön eleme asistanı" — Ek III madde 4 (istihdam), profil çıkarıyor → **yüksek risk**; kullanıcı olarak yükümlülükler: insan gözetimi (md. 26(2)), girdi verisinin uygunluğu (26(4)), izleme (26(5)), logları en az 6 ay saklama (26(6)), çalışanları bilgilendirme (26(7)), kişilere bildirim (26(11)), açıklama hakkı (md. 86).

## 3. Veri varlıkları

**Veri varlıkları** ile eğitim, ince ayar, girdi, çıktı ve referans verisini katalogdaki tablolara bağlayın. Sonuçları:

- Bağlı tabloda kişisel veri varsa sistem kişisel veri işliyor sayılır; işaretli değilse açık olarak gösterilir.
- Tablo ekranında "Yapay zekâ sistemleri bu tabloyu kullanıyor" notu çıkar.
- Soy kütüğü **etki analizi** değişen tablonun yapay zekâ sistemlerini ve sahiplerini listeler; şema değişikliği modeli bozmadan önce haber alırsınız.

## 4. Açıklar

Sistem ekranındaki **Açıklar** listesi kural olarak hesaplanır ve dayanağını gösterir: sınıflandırılmamış, yasaklı ve kullanımda, sahipsiz, insan gözetimi yok (yüksek risk veya otomatik karar), FRIA yapılmamış, log saklama 6 aydan az, şeffaflık bildirimi yok, 12 aydır değerlendirme yok, kişisel veri işliyor ama işleme envanterinde değil, VKED bağlı değil, tedarikçi seçilmemiş, veri bağlanmamış, gözden geçirme tarihi geçmiş.

Yüksek önemli açıklar sistem sahibinin **İşlerim** listesine düşer; yasaklı, sınıflandırılmamış, insan gözetimsiz ve envanter dışı sistemler **GRC Sağlık Kontrolü**'nde görünür. KVKK md. 11(1)(g) ve GDPR Art. 22 boşluk analizi göstergesi otomatik karar veren sistemlerden hesaplanır.

## 5. Listeler ve rapor

Envanter ekranında risk sınıfı dağılımı (tıklayarak süzün), arama, "Yalnızca açığı olanlar" süzgeci ve **CSV indir** vardır. Tedarikçi 360'ta **Yapay zekâ** sekmesi tedarikçinin sağladığı sistemleri gösterir.

## Uygulama takvimi

Envanter ekranının altında Tüzüğün uygulama tarihleri (md. 113) gösterilir: yasaklar ve yapay zekâ okuryazarlığı 2 Şubat 2025, genel amaçlı modeller 2 Ağustos 2025, Ek III yüksek risk ve şeffaflık 2 Ağustos 2026, Ek I ürünleri 2 Ağustos 2027. Erteleme önerileri olabileceğinden yürürlükteki metni EUR-Lex'ten doğrulayın.

> Sınıflandırma, Tüzüğün yayımlanmış metnine dayanan bir ön değerlendirmedir; hukuki görüş yerine geçmez. ISO/IEC 42001 eşlemesi kurumun lisanslı metni yüklendiğinde eklenecektir.
