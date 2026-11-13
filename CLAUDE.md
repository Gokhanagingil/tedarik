# Bu repoda çalışan yapay zekâ yardımcıları için

Önce `DURUM.md` dosyasını oku; sıradaki adım orada. Oturum sonunda `DURUM.md` dosyasını güncelle.

## Bağlam

Tedarikçi yönetimi portalı. Kardeş uygulama KS GRC (`../control`, GitHub: Gokhanagingil/control). İki uygulama ileride birleşecek; `docs/UYUM_SOZLESMESI.md` bağlayıcıdır. Bir kuralı çiğnemen gerekiyorsa önce `docs/KARARLAR.md` içine yeni karar yaz.

## Kurallar

- Python 3.12, yalnızca standart kütüphane. Yeni bağımlılık eklemeden önce sor.
- KS GRC'de karşılığı olan parçayı yeniden yazma; `tedarik/vendor/` altına aynen kopyala, kaynak commit kimliğini dosya başına yaz.
- Tablolar `tdr_` önekli, uç noktalar `/api/tdr` altında. Silme uç noktası ekleme.
- Yeni tablo `Resource` tanımıyla, yeni kural `before_save` kancasıyla veya iş akışı korumasıyla eklenir. Süreç kuralını koda gömme; `policies` tablosuna koy.
- Her yazma işlemi `audit.log` çağırır. Her yeni uç nokta yetki denetimi yapar (`authz.check` veya `authz.require`).
- Arayüz metinleri ve hata iletileri Türkçe; kod tanımlayıcıları ve durum kodları İngilizce.
- Arayüzde dış kaynak (CDN, yazı tipi, betik) kullanma; içerik güvenlik politikası engeller.
- Her davranış değişikliği testle gelir. Test verisi sentetiktir; gerçek tedarikçi verisini repoya koyma.
- Gizli bilgi (anahtar, parola, gerçek veri) Git'e girmez.

## Komutlar

```
python -m unittest discover -s tests -v          # testler
TEDARIK_AUTH_MODE=dev python app.py              # yerel çalıştırma, http://127.0.0.1:8090
TEDARIK_MODULES=core,workflow,sourcing ...       # kapalı modülleri açmak için
```

## Kalite ölçütü

Kod tek başına yeterli değil: kullanım kolaylığı, görsel kalite, mantık bütünlüğü, testler ve tamamlanmış ürün davranışı birlikte değerlendirilir. Bir işi "bitti" demeden önce çalıştır ve dene.
