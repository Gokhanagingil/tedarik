# Dokümanlar ve varlıklar (CMDB)

> Menü: Dokümanlar; Varlıklar (CMDB). Kimler için: politika ve prosedür sahipleri, süreç sahipleri, BT varlık yöneticileri.

## Doküman yönetimi (ISO 9001 7.5)

Politika, prosedür, talimat, form ve kayıtlar burada yönetilir. Her yayın değiştirilemez bir **revizyon** bırakır; böylece hangi tarihte hangi sürümün geçerli olduğu her zaman kanıtlanabilir.

### Yaşam döngüsü

```
Taslak → Onayda → Yayımlandı → (yeni revizyon taslağı) → … → Geçersiz
```

1. **Dokümanlar → + Yeni**: başlık, tür, süreç, birim, sahip, onaylayan, gizlilik, gözden geçirme periyodu.
2. **Dosya yükle**: taslak dosyası (en çok 12 MB). Dosya özeti (SHA-256) saklanır ve her indirmede doğrulanır.
3. **Onaya gönder**: değişiklik özetini yazın (ör. "Yedekleme sıklığı günlüğe çıkarıldı").
4. Onaylayan **Onayla ve yayımla** veya gerekçeyle **Reddet** der. **Hazırlayan kendi dokümanını onaylayamaz.** Dokümana bir onaylayan atanmışsa yalnızca o kişi veya Yönetici onaylar.
5. Yayımlanınca geçerlilik tarihi ve bir sonraki gözden geçirme tarihi atanır. Gözden geçirme zamanı gelen doküman sahibin İşlerim listesine düşer.
6. Değişiklik gerekiyorsa **Yeni revizyon başlat**. Yeni revizyon yayımlanana kadar son yayımlanan revizyon geçerlidir.
7. Artık kullanılmayacak doküman gerekçeyle **Geçersiz kıl**; açıkça "Geçersiz" görünür ve değiştirilemez.

### Okundu beyanı

Çalışanların bir politikayı okuduğunu kanıtlamak için Uyum → Okundu Beyanı Kampanyaları kullanılır (ayrıntı "Uyum ve denetim" kılavuzunda).

### Bağlantılar

Doküman kontrollere (kontrolün dayanağı), standart maddelerine (maddeyi karşılayan doküman) ve süreçlere bağlanır. Süreç Haritası'nda her sürecin dokümanları görünür.

## Varlıklar (CMDB)

CMDB uygulama ve altyapı öğelerini (CI) tutar. Kayıtlar ServiceNow CMDB'den salt okunur senkronla veya MCP entegrasyonuyla gelir; platform ServiceNow'a hiç yazmaz.

### CMDB Panosu

**[CMDB Panosu](#/cmdb)**: CI sayıları, türler, son senkron ve **risk kuralları**:

| Kural | Bulduğu |
|---|---|
| Destek dışı işletim sistemi | Üreticinin destek bitiş tarihi geçmiş İS |
| Destek dışı uygulama | Destek bitiş tarihi geçmiş yazılım |
| Eksik kritik yama | Kritik yama süresi aşılmış sunucular |
| Uzun süre yeniden başlatılmama | Eşikten uzun süredir açık kalan sunucular |

Eşikler Yönetim → Politika Parametreleri'ndedir. Kurallar her senkronun ardından ve Yönetici **Kuralları değerlendir** dediğinde çalışır; kural CI düzeyinde **maruziyet** kaydı açar ve şirket bazında bir kurumsal riskte toplar; etkilenen CI'lar riske bağlanır. Sorun giderilince maruziyet kendiliğinden kapanır.

### CI'lar nerede kullanılır

- **BİA:** sürecin bağlı olduğu uygulamalar CMDB'den seçilir.
- **Süreklilik planı:** kurtarılacak uygulamalar.
- **Risk:** etkilenen CI'lar.
- **Veri kaynakları:** veri kaynağının çalıştığı CI; soy kütüğü etki analizi bu bağdan BİA'lı süreçleri bulur.
- **Yapay zekâ sistemleri:** sistemin CMDB öğesi.

### Senkron

ServiceNow bağlantısı Yönetim → Entegrasyonlar'da tanımlanır. Her senkron değiştirilemez bir çalıştırma kaydı bırakır (Yönetim → CMDB Senkron Çalıştırmaları). MCP sunucusu tanımlıysa Yönetici **MCP bağlantısını sına** ile bağlantıyı veri yazmadan dener.
