# Kullanım kılavuzları

Kılavuzlar uygulamayla birlikte dağıtılır ve uygulama içinde **Genel → Kullanım Kılavuzu** ekranından okunur. Her ekranda sağ üstteki **?** düğmesi (veya `?` tuşu) o ekranın kılavuz bölümünü açar; **Tümünü yazdır / PDF** tüm kılavuzu tek belge olarak verir. Kaynak dosyalar `tedarik/data/kilavuz/` altındadır (K-036).

| Kılavuz | Dosya |
|---|---|
| Başlarken | [00-baslarken.md](../tedarik/data/kilavuz/00-baslarken.md) |
| Yönetici | [10-yonetici.md](../tedarik/data/kilavuz/10-yonetici.md) |
| Tedarikçi Yöneticisi | [11-tedarikci-yoneticisi.md](../tedarik/data/kilavuz/11-tedarikci-yoneticisi.md) |
| Birim Kullanıcısı | [12-birim-kullanicisi.md](../tedarik/data/kilavuz/12-birim-kullanicisi.md) |
| Denetçi (ve dış denetçi) | [13-denetci.md](../tedarik/data/kilavuz/13-denetci.md) |
| Görüntüleyici | [14-goruntuleyici.md](../tedarik/data/kilavuz/14-goruntuleyici.md) |
| Tedarikçi yönetimi | [20-tedarikci-yonetimi.md](../tedarik/data/kilavuz/20-tedarikci-yonetimi.md) |
| Risk yönetimi (ISO 31000) | [21-risk-yonetimi.md](../tedarik/data/kilavuz/21-risk-yonetimi.md) |
| Uyum ve denetim | [22-uyum-ve-denetim.md](../tedarik/data/kilavuz/22-uyum-ve-denetim.md) |
| İş sürekliliği (ISO 22301) | [23-is-surekliligi.md](../tedarik/data/kilavuz/23-is-surekliligi.md) |
| Dokümanlar ve varlıklar (CMDB) | [24-dokuman-ve-cmdb.md](../tedarik/data/kilavuz/24-dokuman-ve-cmdb.md) |
| Veri yönetişimi | [25-veri-yonetisimi.md](../tedarik/data/kilavuz/25-veri-yonetisimi.md) |
| Kişisel veri (KVKK ve GDPR) | [26-kvkk.md](../tedarik/data/kilavuz/26-kvkk.md) |
| Yapay zekâ envanteri | [27-yapay-zeka.md](../tedarik/data/kilavuz/27-yapay-zeka.md) |
| Sık sorulanlar ve sorun giderme | [30-sss.md](../tedarik/data/kilavuz/30-sss.md) |

## Yazım kuralları

- Ekran, menü ve düğme adları uygulamadaki Türkçe metinle birebir aynıdır (kalın yazılır).
- Uygulama içi bağlantı `[Ad](#/rota)` biçimindedir; dış bağlantı kullanılmaz (düz metne çevrilir).
- Desteklenen biçim: `#`–`####` başlık, paragraf, `-` ve `1.` liste (bir alt düzey), tablo, `>` not, kod bloğu, **kalın**, `kod`.
- İlk `>` satırı kılavuzun özetidir ("Kimler için: …").
- Örnek veriler sentetiktir; gerçek kişi, tedarikçi veya kayıt yazılmaz.
- Bir ekranın davranışı veya düğme adı değişirse ilgili kılavuz aynı değişiklikte güncellenir. Bağlama duyarlı yardım eşlemesi (`tedarik/help.py` → `CONTEXT`) ve kılavuz içi bağlantılar `tests/test_kilavuz.py` ile denetlenir.
