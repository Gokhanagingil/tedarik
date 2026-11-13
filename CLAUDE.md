# Bu repoda çalışan yapay zekâ yardımcıları için

Önce `DURUM.md` dosyasını oku; sıradaki adım orada. Oturum sonunda `DURUM.md` dosyasını güncelle.

## Bağlam

Tedarikçi yönetimi portalı. Kardeş uygulama KS GRC (`../control`, GitHub: Gokhanagingil/control). İki uygulama ileride birleşecek; `docs/UYUM_SOZLESMESI.md` bağlayıcıdır. Bir kuralı çiğnemen gerekiyorsa önce `docs/KARARLAR.md` içine yeni karar yaz.

## Kurallar

- Python 3.12. Bağımlılıklar `requirements.txt` içinde sürüm ve hashle sabit (PostgreSQL sürücüsü, K-011). Yeni bağımlılık eklemeden önce sor. SQLite ile çalışma ek paket istemez; bunu koru.
- Kod iki motorda çalışır (PostgreSQL üretim, SQLite geliştirme): SQL'de parametre `?`; `date('now')` yerine `db.today()`; `INSERT OR IGNORE` yerine `ON CONFLICT DO NOTHING`; `GROUP_CONCAT` yerine `db.group_concat()`; aramada `tdr_fold()`; mantıksal toplamda `SUM(CASE WHEN ...)`; kilit için `db.lock(ad)`; `PRAGMA` ve `sqlite3` yalnızca `db.py` ve `migrate.py` içinde. Tarih alanı `DATE`, zaman alanı `TIMESTAMP`, para `DECIMAL`.
- Değiştirilemez kayıt (iz, değerlendirme, karar, geçmiş) `Resource(..., immutable=True)` ile tanımlanır; tetikleyiciyi `migrate.py` kurar.
- KS GRC'de karşılığı olan parçayı yeniden yazma; `tedarik/vendor/` altına aynen kopyala, kaynak commit kimliğini dosya başına yaz. Uyarlama sarmalayıcıda (`session.py`); kaçınılmaz yama `vendor/PATCHES.md` içinde ve `[tedarik yaması K-0xx]` işaretiyle.
- Birim Kullanıcısının yazabildiği her yeni kaynak `Resource.scope` tanımlar; özel uç noktada `crud.check_scope` çağrılır.
- Tablolar `tdr_` önekli, uç noktalar `/api/tdr` altında. Silme uç noktası ekleme.
- Yeni tablo `Resource` tanımıyla, yeni kural `before_save` kancasıyla veya iş akışı korumasıyla eklenir. Süreç kuralını koda gömme; `policies` tablosuna koy.
- Her yazma işlemi `audit.log` çağırır. Her yeni uç nokta yetki denetimi yapar (`authz.check` veya `authz.require`).
- Arayüz metinleri ve hata iletileri Türkçe; kod tanımlayıcıları ve durum kodları İngilizce.
- Arayüzde dış kaynak (CDN, yazı tipi, betik) kullanma; içerik güvenlik politikası engeller.
- Her davranış değişikliği testle gelir. Test verisi sentetiktir; gerçek tedarikçi verisini repoya koyma.
- Gizli bilgi (anahtar, parola, gerçek veri) Git'e girmez.

## Komutlar

```
python -m unittest discover -s tests -v          # testler (SQLite)
TEDARIK_TEST_DATABASE_URL=postgresql://... python -m unittest discover -s tests -v   # testler (PostgreSQL)
TEDARIK_AUTH_MODE=dev python app.py              # yerel çalıştırma, http://127.0.0.1:8090
TEDARIK_MODULES=core,workflow,sourcing ...       # kapalı modülleri açmak için
TEDARIK_AUTH_MODE=local python -m tedarik.bootstrap create tdradmin   # ilk yönetici (geçici parola)
```

## Kalite ölçütü

Kod tek başına yeterli değil: kullanım kolaylığı, görsel kalite, mantık bütünlüğü, testler ve tamamlanmış ürün davranışı birlikte değerlendirilir. Bir işi "bitti" demeden önce çalıştır ve dene.
