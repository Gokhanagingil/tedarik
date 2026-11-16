# İş sürekliliği (ISO 22301)

> Menü: İş sürekliliği. Kimler için: süreç sahipleri, iş sürekliliği koordinatörü, kriz ekibi.

## Akış

```
Süreç → İş etki analizi (BİA) → Süreklilik planı → Tatbikat → Bulgular ve dersler
                                        ↓
                                  Kriz yönetimi (gerçek olay)
```

**[Süreklilik Panosu](#/bcm)** kritik süreçlerin BİA, plan ve tatbikatla karşılanıp karşılanmadığını gösterir.

## İş etki analizi (BİA)

1. **İş Etki Analizleri → + Yeni BİA**: süreç, şirket, birim, sahip.
2. **Etki matrisini düzenle:** kesintinin etkisini zaman aralıklarına göre (1, 4 ve 8 saat; 1 ve 3 gün; 1 ve 2 hafta; 1 ay) ve etki türlerine göre (finansal, operasyonel, müşteri, itibar, yasal) 1–5 puanlayın.
3. **MTPD** (azami tolere edilebilir kesinti süresi) matristen türetilir. **RTO** (kurtarma süresi hedefi) MTPD'yi aşamaz; **RPO** (kabul edilebilir veri kaybı) ve asgari hizmet seviyesini yazın.
4. Bağımlılıklar: kullanılan uygulamalar (CMDB'den), tedarikçiler, personel, konum, hayati kayıtlar.
5. **Gözden geçirmeye gönder**. **Hazırlayan veya sahibi onaylayamaz**; başka bir yetkili **Onayla** der. Onaylı BİA değişecekse **Revizyona al**.
6. BİA yılda bir gözden geçirilir; tarihi gelen BİA İşlerim'e düşer.

## Süreklilik planları

**İş Sürekliliği Planları → + Yeni**: tür (iş sürekliliği, BT felaket kurtarma, kriz yönetimi, kriz iletişimi, salgın), kapsam, devreye alma ölçütü, kurtarılacak uygulamalar ve adımlar. Adımlar aşamalara ayrılır: **devreye alma, müdahale, kurtarma, normale dönüş**; her adımın sorumlusu ve hedef süresi vardır. Plan da dört gözle onaylanır; onaylı planın adımları değiştirilmez, yeni revizyon açılır.

## Tatbikatlar

1. **+ Tatbikat planla**: plan, tür (masa başı, adım adım gözden geçirme, simülasyon, işlevsel test, tam ölçekli DR testi, çağrı ağacı), senaryo, tarih, hedef kurtarma süresi.
2. Tatbikat günü gerçekleşen süreleri ve gözlemleri girin.
3. **Tatbikatı tamamla**: sonuç (başarılı, kısmen başarılı, başarısız), alınan dersler. Bulgular DÖF'e dönüşür.

## Kriz yönetimi

Gerçek bir kesinti veya kriz olduğunda **İş sürekliliği → [Kriz Yönetimi](#/crisis)**:

1. **Kriz ilan et** (Yönetici ve Tedarikçi Yöneticisi): başlık, etkilenen süreçler, lider. Seçilen planların adımları görev listesine dönüşür.
2. Görev sorumluları kendi görevlerini **Başladım** ve **Tamamlandı** ile ilerletir; geçen süre ekranda görünür.
3. Kararlar ve iletişim **değiştirilemez kriz günlüğüne** yazılır (günlüğe kriz ekibi yazar).
4. **Normale dönüşe geç**, ardından **Krizi kapat**. Kapanışta dersler ve bulgular kaydedilir.

Etkin kriz varken her ekranın üstünde **KRİZ MODU** bandı görünür; banda tıklayarak kriz ekranına dönersiniz.

## İpuçları

- RTO'yu MTPD'den kısa tutun; uygulamaların CMDB'deki kurtarma hedefleriyle karşılaştırın.
- Kritik tedarikçi bağımlılığı varsa tedarikçinin sözleşmesinde süreklilik ve denetim hakkı maddesi olduğundan emin olun (otomatik kontrol bunu izler).
- GRC Sağlık Kontrolü "BİA'sı olmayan ana süreçleri" listeler.
