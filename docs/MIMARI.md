# Tedarik Portalı Mimarisi

## Amaç

Satın alma iş birimlerine dağılmış durumda. Portal süreci değiştirmez; tedarikçileri, alınan ürün ve hizmetleri, sahiplikleri, performansı ve riskleri tek yerde görünür kılar. Yakın gelecekte süreç tasarlamaya (ihtiyaç girişi, mevcut tedarikçiden seçim, teklif toplama) genişleyebilecek şekilde kurulmuştur.

## İlkeler

1. **KS GRC ile aynı yığın ve kurallar.** İki uygulama birleşebilsin veya tek uygulama gibi davranabilsin diye. Ayrıntı: `UYUM_SOZLESMESI.md`.
2. **Tedarikçi ile ilişki ayrı kayıtlardır.** Tedarikçi tekil tüzel kişidir. Kim, neyi, kimin için, kimin sahipliğinde alıyor bilgisi Angajman kaydındadır.
3. **Segmentasyon her şeyi yönlendirir.** Kritiklik seviyesi (tier) değerlendirme, anket ve risk gözden geçirme sıklığını belirler.
4. **Süreç koda gömülmez.** Adımlar iş akışı tanımında, kurallar politika parametresinde durur.
5. **Kaynak sistem veriyi besler, portal veriyi sahiplenir.** İçe aktarım elle girilmiş alanı ezmez.
6. **Her yazma iz bırakır, hiçbir kayıt silinmez.**

## Katmanlar

```
Tarayıcı (derlemesiz istemci)      MCP uygulaması (ServiceNow, Dynamics)      Excel / CSV
            |                                   |                                |
            +---------------- HTTP: /api/tdr/... (tedarik/http.py) --------------+
                 kimlik -> yetki -> köken denetimi -> tekrar koruması -> işlem
                                        |
        Modüller (tedarik/modules): core · performance · surveys · risks
                                    transfer · dashboard · workflow · sourcing
                                        |
        Ortak kayıt işlemleri (crud.py) · denetim izi (audit.py) · şema kaydı (schema.py)
                                        |
             Veritabanı katmanı (db.py) · şema ve göçler (migrate.py), tdr_ önekli tablolar
                    PostgreSQL (üretim)  |  SQLite, WAL (geliştirme, test)
```

## Modüller

| Modül | Sorumluluk | Varsayılan |
| --- | --- | --- |
| `core` | Birimler, tedarikçi tipleri, ürün/hizmet kataloğu, tedarikçiler, angajmanlar, sorumluluklar, sözleşme referansları, kaynak sistem eşlemeleri | Açık |
| `performance` | SLA tanımı ve ölçümü, kriter bazlı değerlendirme, performans olay günlüğü, scorecard | Açık |
| `surveys` | Anket motoru: memnuniyet, risk ve bağımsız anketler; şablon sürümü, bölüm, koşullu soru, puan, anonimlik, sonuç, risk sinyali | Açık |
| `risks` | Tedarikçi riski, değerlendirme geçmişi, işleme faaliyetleri | Açık |
| `transfer` | İçe aktarma hattı, dışa aktarma | Açık |
| `dashboard` | Pano özet verisi | Açık |
| `workflow` | Genel iş akışı motoru, politika parametreleri | Kapalı |
| `sourcing` | İhtiyaç, aday tedarikçi, teklif; varsayılan kaynak bulma akışı | Kapalı |

Modüller `TEDARIK_MODULES` ile seçilir. Kapalı modülün tablosu ve uç noktası açılmaz. Bir modül üç şey getirir: kaynak tanımları (`Resource`), `register(app)` ile özel uç noktalar, `seed(db)` ile başlangıç verisi.

**Yeni alan eklemek:** ilgili `Resource` tanımına bir satır. Tablo açılışta genişler, uç nokta ve doğrulama kendiliğinden gelir.
**Yeni modül eklemek:** `tedarik/modules/<ad>.py` dosyası ve `config.KNOWN_MODULES` içine adı.

## İstek akışı

`App.dispatch` saf bir işlevdir; testler soket açmadan çalışır. Sıra: kimlik çözümü, yol eşleme, gövde sınırı (2 MB), köken denetimi, tekrar koruması (`idempotency_key`), işlem, denetim izi, tek işlemde (transaction) kayıt. Hata yanıtı her zaman `{"error": "..."}` biçimindedir: 400 doğrulama, 401 kimlik, 403 yetki, 404 bulunamadı, 409 çakışma veya kural ihlali, 413 gövde sınırı.

## Yetki modeli

| Rol | Seviye | Yapabildiği |
| --- | --- | --- |
| `VIEWER` Görüntüleyici | okuma | Tüm kayıtları görür (denetim izi hariç) |
| `AUDITOR` Denetçi | okuma | Tüm kayıtları ve denetim izini görür |
| `UNIT_USER` Birim Kullanıcısı | yazma | Angajman, SLA ölçümü, olay, değerlendirme, risk, anket yanıtı, ihtiyaç ve teklif girer |
| `SUPPLIER_MANAGER` Tedarikçi Yöneticisi | yönetim | Tedarikçi ana verisi, katalog, anket, içe/dışa aktarma, onaylar |
| `ADMIN` Yönetici | tam | Birimler, tipler, kriterler, iş akışı tanımları, politikalar |

MCP anahtarı rol değildir. Yalnızca kaynağın açıkça izin verdiği işlemi yapar: ana veriyi okur, SLA ölçümü ve performans olayını `source=mcp` ile yazar. Ana veriyi değiştiremez, toplu dışa aktarım yapamaz.

**Birim kapsamı.** Birim Kullanıcısı yalnızca kendi biriminin kayıtlarına yazar; okuma herkese açıktır (portalın amacı görünürlük). Angajmanın sahibi satın alan birimdir (`org_unit_id`). SLA tanımı ve ölçümü, risk faaliyeti, değerlendirme puanı, aday tedarikçi ve teklif kapsamını üst kaydından alır. Angajmana bağlı olmayan tedarikçi düzeyindeki olay, risk veya değerlendirme, kullanıcının biriminin o tedarikçiyle angajmanı varsa yazılabilir. Kayıt başka birime taşınamaz. Kapsam `Resource.scope` ile tanımlanır ve `crud` katmanında her yazmada denetlenir. Kullanıcının birimleri `tdr_user_units` tablosundadır; yönetici `PATCH /api/tdr/users/{id}` ile atar.

**Oturum.** KS GRC `identity.py` ve `entra_auth.py` kopyalarıyla (`tedarik/vendor/`, K-012, K-013). Çerez adları KS GRC'den farklıdır; iki uygulama aynı alan adında birbirinin oturumunu ezmez.

## Veri aktarımı

Tek hat: oku (XLSX veya CSV), başlıkları kanonik alanlara eşle, her satırı mevcut kayıtla eşleştir, uygula. Başlıklar alan adı, Türkçe etiket veya kaynak sistem takma adıyla tanınır; seçimlerde kod veya Türkçe etiket, ilişkilerde hedef kaydın kodu verilir. Her kayıt türü için uygulama kendi şablonunu üretir (`GET /api/tdr/import/templates/<kaynak>`: "Veri" ve alan açıklamalı "Açıklama" sayfası). İçe aktarılabilenler: birimler, tedarikçi tipleri, ürün ve hizmetler, tedarikçiler, angajmanlar, sözleşmeler, SLA tanımları. Her satır kendi geri alma noktasında işlenir; hatalı satır diğerlerini bozmaz. Dışa aktarım tek kaynak (`/api/tdr/export/<kaynak>?format=xlsx|csv`) veya çok sayfalı çalışma kitabı (`/api/tdr/export`) olarak alınır; başlıklar ve seçimler Türkçe, ilişkiler kodla. Eşleştirme sırası: (kaynak sistem, harici kimlik), sonra VKN, sonra ad benzerliği. Ad benzerliği otomatik birleştirmez, "inceleme" olarak işaretler. `dry_run` ile önce sonuç görülür. Her aktarım ve her satırın sonucu saklanır. Excel dosyaları, MCP ve ileride konnektörler aynı hattı kullanır.

## Entegrasyon

Portal kaynak sistemlere doğrudan bağlanmaz. KS GRC'deki modelin aynısı: MCP uygulaması ServiceNow ve Dynamics'i sorgular, sonucu portalın REST API'sine yazar. Ters yönde portal KS GRC için kanıt kaynağıdır: "kritik tedarikçilerin yıllık değerlendirmesi yapıldı mı" gibi otomatik kontroller portal API'sinden beslenebilir.

## KS GRC ile birleşme yolu

1. **Bugün:** iki ayrı uygulama, aynı kurallar.
2. **Tek uygulama gibi:** ters vekil arkasında aynı alan adı, ortak Entra oturumu, ortak üst menü.
3. **Tam birleşme:** `tedarik` paketi KS GRC'ye modül olarak takılır. Tablolar `tdr_` önekli, uç noktalar `/api/tdr` altında olduğu için çakışma olmaz.

## Arayüz yaklaşımı (sonraki aşama)

Derleme gerektirmeyen tarayıcı istemcisi, KS GRC'nin görsel diliyle: solda menü, ortada aranabilir ve filtrelenebilir liste, sağda detay paneli. İçerik güvenlik politikası dış kaynağa izin vermediği için grafikler satır içi SVG olarak çizilir, dış kütüphane yüklenmez. Pano tek uç noktadan (`/api/tdr/dashboard/summary`) beslenir. İş akışı düğmeleri `actions` listesinden üretilir; süreç değişince arayüz değişmez.

## Standart eşlemesi

| Çerçeve | Portaldaki karşılığı |
| --- | --- |
| ITIL tedarikçi yönetimi pratiği | Tedarikçi kaydı, segmentasyon, performans izleme, sözleşme referansı |
| ISO/IEC 20000-1 madde 8.3.4 | Tedarikçi ve angajman kaydı, SLA ölçümü, periyodik değerlendirme kanıtı |
| ISO/IEC 27001:2022 A.5.19 – A.5.22 | Tedarikçi envanteri, kritiklik, risk kaydı, izleme ve gözden geçirme geçmişi |
| ISO 22301 | Kritik tedarikçi ve süreklilik riskleri (`continuity`, `concentration`, `exit`) |
| ISO 37500, ISO 44001 | Sahiplik ve sorumluluk kaydı, ilişki yönetimi, çıkış riski |

## Ölçek ve sınırlar

Üretim veritabanı PostgreSQL'dir (K-011): eşzamanlı yazıcılar, bağlantı havuzu (`TEDARIK_DB_POOL_SIZE`), yerel tipler (DATE, TIMESTAMPTZ, NUMERIC, BIGINT kimlik), yabancı anahtar dizinleri, değişmez tablolar için tetikleyici, aynı kayıt için danışma kilidi (`db.lock`). SQLite yerel geliştirme ve test içindir; tek yazıcıyla çalışır.

Motor bağımsızlık kuralları (CLAUDE.md'de de yazılı): SQL'de parametre `?`; tarih hesabı Python'da (`db.today()`), SQL'de `date('now')` yok; çakışmada `ON CONFLICT DO NOTHING`; metin arama `tdr_fold()` ile (Türkçe harf katlama); toplamda `SUM(CASE WHEN ...)`; birleştirmede `db.group_concat()`. Tarih ve zaman alanları uygulamada doğrulanır ve UTC ISO 8601 metnine normalleşir; iki motorun JSON çıktısı aynıdır.

Şema iki katmanlıdır (`migrate.py`): `Resource` tanımlarından bildirimsel eşitleme (yeni tablo, yeni boş bırakılabilir alan, dizin, tetikleyici) ve veri dönüştüren adımlar için sürümlü göç kaydı (`tdr_schema_migrations`). Zorunlu veya tekil yeni alan kendiliğinden eklenmez; açık göç ister. Açılış kilit altında yapılır; birden çok süreç aynı anda başlayabilir.

Listeler sayfa başına en çok 1000 kayıt döner.
