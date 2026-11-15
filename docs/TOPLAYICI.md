# Katalog toplayıcısı ve bağlayıcı geliştirme kiti (K-030)

Toplayıcı, veri kaynağının bulunduğu ağda kurumun sunucusunda çalışan küçük bir programdır. Kaynağa salt okunur bir
hesapla bağlanır, **yalnızca meta veriyi** (şema, tablo, kolon, tip, açıklama, anahtar, satır sayısı) okur ve platforma
gönderir. Platform kaynağa bağlanmaz; kaynağın parolası platformda tutulmaz; ham veri platforma gelmez.

```
 Kurum ağı                                              Platform
 ┌──────────────┐  salt okunur   ┌───────────────┐ HTTPS ┌───────────────────────────────┐
 │ Veri kaynağı │ ─────────────▶ │  Toplayıcı    │ ────▶ │ /api/tdr/collector/catalog     │
 │ (HANA, PG …) │  meta veri     │ (.pyz, cron)  │ anahtar│ → içe aktarım, değişiklik     │
 └──────────────┘                └───────────────┘       │   geçmişi, bildirim            │
                                                          └───────────────────────────────┘
```

## Kurulum (ekrandaki adımların özeti)

1. **Toplayıcı ekleyin:** Veri kaynağı → *Otomatik toplama* → *+ Toplayıcı ekle*. Bağlayıcıyı, beklenen sıklığı ve
   kapsamı seçin. Anahtar **yalnızca bir kez** gösterilir; platform anahtarın kendisini saklamaz.
2. **İndirin:** *Toplayıcıyı indir (.pyz)*. Tek dosyadır; Python 3.9 veya üstü yeterlidir.
3. **Anahtarı kaydedin:** Linux'ta `/etc/tedarik/anahtar` (yalnızca toplayıcı hesabı okuyabilsin: `chmod 600`),
   Windows'ta `C:\tedarik\anahtar.txt` (yalnızca hizmet hesabına okuma izni). Anahtarı komut satırına, betiğe veya
   e-postaya yazmayın. Alternatif: `TEDARIK_COLLECTOR_KEY` ortam değişkeni.
4. **Ayar dosyası:** toplayıcı ekranındaki `toplayici.json` örneğini kopyalayın. Parola ve bağlantı dizesi ayar
   dosyasına yazılmaz; ayarda yalnızca ortam değişkeninin adı durur.
5. **Sınayın:** `python3 tedarik-toplayici.pyz dene --ayar toplayici.json`
6. **Zamanlayın:** ekrandaki cron veya Windows Görev Zamanlayıcı satırını kullanın.

## Komutlar

| Komut | İş |
| --- | --- |
| `dene --ayar A` | Platform ve kaynak bağlantısını sınar; kaç tablonun okunabildiğini yazar |
| `topla --ayar A --cikti katalog.json` | Gönderilecek dosyayı yalnızca yerelde yazar (gözden geçirme) |
| `gonder --ayar A [--on-izleme]` | Toplar ve gönderir; ön izleme veri yazmaz |
| `dosya-gonder --ayar A dosya` | Kaynağın kendi dışa aktarımını (CSV, Excel, JSON) gönderir |
| `baglayicilar` | Bağlayıcıları ve ayarlarını listeler |
| `ornek-ayar [bağlayıcı]` | Örnek ayar dosyası yazar |

İngilizce eşdeğerleri: `check`, `collect`, `push`, `push-file`, `connectors`, `example-config`. Çıkış kodu: 0 başarılı,
1 hata (ileti standart hata çıktısında; kaynak tarafındaki hata platforma da bildirilir).

## Ayar dosyası

```json
{
  "platform": "https://grc.ornek.com.tr",
  "key_file": "/etc/tedarik/anahtar",
  "connector": "postgresql",
  "settings": {"dsn_env": "TEDARIK_SOURCE_DSN", "schemas": ["public", "satis"], "row_counts": true},
  "ca_file": null,
  "timeout": 120
}
```

| Alan | Açıklama |
| --- | --- |
| `platform` | Platform adresi; `https://` zorunlu (yalnızca `127.0.0.1`/`localhost` için `http://`) |
| `key_file` / `key_env` | Anahtar dosyası veya ortam değişkeni (varsayılan `TEDARIK_COLLECTOR_KEY`) |
| `connector`, `settings` | Bağlayıcı ve ayarları (aşağıda) |
| `plugins` | Kurumun bağlayıcı dosyaları (`--eklenti` ile de verilir) |
| `ca_file` | Kurum içi sertifika otoritesi kullanılıyorsa CA dosyası |
| `scope`, `sample_rows`, `default_schema` | İsteğe bağlı yerel geçersiz kılma; normalde platformdaki toplayıcı kaydından gelir |

### Yerleşik bağlayıcılar

| Bağlayıcı | Ne okur | Gerekenler |
| --- | --- | --- |
| `postgresql` | Tablo, görünüm, kolon, açıklama, birincil/yabancı anahtar, tahmini satır | `psycopg` (toplayıcı makinesine); `dsn_env`, `schemas`, `exclude_schemas`, `row_counts` |
| `sqlite` | Tablo, görünüm, kolon, anahtar, satır sayısı | Ek paket yok; `path`, `schema` |
| `sql` | Hazır katalog sorgusunun sonucu (CSV olarak gider) | Kaynağın DB-API sürücüsü: `driver` (`hdbcli.dbapi`, `pyodbc`, `oracledb`, `pymysql`, `snowflake.connector`), `connect_env` (JSON bağlantı bilgisi) veya `dsn_env`; `preset` + `replace` veya `query` / `query_file` |
| `files` | Klasördeki CSV dosyaları; tipler yerelde çıkarılır | `path`, `pattern`, `schema`, `recursive`, `infer_rows` |
| (komut) `dosya-gonder` | Kaynağın kendi zamanlanmış dışa aktarımı | — |

`sql` bağlayıcısının hazır sorguları (`hana_catalog`, `sap_ddic`, `mssql_columns`, `oracle_columns`, `mysql_columns`,
`snowflake_columns`, `redshift_columns`, `pg_columns`) kaynağın platformunda tanımlıdır ve toplayıcıya platformdan gelir.
Sorgudaki `<ŞEMA_1>` gibi yer tutucular `replace` ile doldurulmadan sorgu çalışmaz.

Örnek (SAP HANA):

```json
{"platform": "https://grc.ornek.com.tr", "key_file": "/etc/tedarik/anahtar", "connector": "sql",
 "settings": {"driver": "hdbcli.dbapi", "connect_env": "TEDARIK_SOURCE_CONNECT", "preset": "hana_catalog",
              "replace": {"<ŞEMA_1>": "SATIS", "<ŞEMA_2>": "FINANS"}}}
```

```
export TEDARIK_SOURCE_CONNECT='{"address": "hana.ornek.local", "port": 30015, "user": "GRC_KATALOG", "password": "…"}'
```

## Örnek doğrulama (isteğe bağlı)

Toplayıcı kaydında "örnek doğrulama satırı" 0'dan büyükse toplayıcı her tablodan en çok o kadar satırı **yerelde** okur;
T.C. kimlik numarası (algoritma), IBAN (mod 97), kart (Luhn), e-posta, telefon ve IPv4 doğrulayıcılarını çalıştırır ve
platforma yalnızca kolon başına "dolu değer" ve "geçerli bulunan" sayılarını gönderir. Değerler ağdan çıkmaz. Sonuç,
Kişisel Veri Keşfi ekranında "Örnek değer" yöntemli öneri olur. Görünümler örneklenmez.

## Güvenlik kuralları

- Anahtar tek bir kaynağa bağlıdır; yalnızca o kaynağa katalog gönderebilir, platformdaki başka hiçbir kaydı okuyamaz.
- Anahtar yenilenince eskisi hemen geçersiz olur; iptal edilen toplayıcı yeniden etkinleştirilemez.
- Gönderim, kaynağın etkin tablolarının eşikten fazlasını (varsayılan %30) "kaldırıldı" yapacaksa reddedilir. Değişiklik
  gerçekse eşiği toplayıcı kaydından geçici olarak yükseltin.
- Kaynak hesabı yalnızca katalog okuma yetkisiyle açılmalıdır; PostgreSQL bağlayıcısı oturumu ayrıca salt okunur yapar.

## Kendi bağlayıcınızı yazmak

Bağlayıcı tek bir Python sınıfıdır. `collect()` tablo sözlükleri üretir; yardımcılar sözleşmeyi doğru kurar.

```python
# envanter.py
from tdr_collector import Connector, connector, table, column


@connector
class Envanter(Connector):
    name = "envanter"                                   # ayar dosyasındaki "connector"
    description = "Kurum içi envanter servisi"
    options = {"base_env": "Servis adresini taşıyan ortam değişkeni"}

    def collect(self):
        base = self.secret("base_env", "ENVANTER_URL")  # gizli bilgi ortam değişkeninden
        for t in okuma_islevi(base):                     # kurumun kendi kodu
            yield table("app", t["ad"], description=t.get("aciklama"), row_count=t.get("satir"), columns=[
                column(k["ad"], data_type=k["tip"], length=k.get("uzunluk"), nullable=k.get("bos_olabilir"),
                       primary_key=k.get("anahtar", False), references=k.get("referans"),   # "şema.tablo.kolon"
                       description=k.get("aciklama"))
                for k in t["kolonlar"]])

    def sample(self, schema, name, limit):              # isteğe bağlı: (başlıklar, satırlar) — yalnızca yerelde kullanılır
        return None
```

```
python3 tedarik-toplayici.pyz gonder --ayar toplayici.json --eklenti envanter.py
```

| Yöntem | Zorunlu | İş |
| --- | --- | --- |
| `collect()` | Evet | `table(...)` sözlükleri üretir |
| `sample(schema, name, limit)` | Hayır | Örnek doğrulama için `(başlıklar, satırlar)`; değerler platforma gitmez |
| `export()` | Hayır | Gönderilecek `(dosya adı, içerik)`; varsayılanı `collect()` çıktısını sözleşmeye çevirir |
| `close()` | Hayır | Bağlantıyı kapatır |
| `setting(ad, varsayılan, required)` / `secret(ayar, varsayılan_değişken)` | — | Ayar ve ortam değişkeni okuma |

## Sözleşme: `tedarik.catalog.v1`

```json
{
  "format": "tedarik.catalog.v1",
  "generated_at": "2026-11-15T02:30:00+00:00",
  "connector": "postgresql",
  "tables": [
    {"schema": "satis", "name": "musteri", "object_type": "table", "description": "Müşteri ana verisi", "row_count": 120000,
     "columns": [
       {"name": "id", "position": 1, "data_type": "bigint", "nullable": false, "primary_key": true},
       {"name": "eposta", "position": 2, "data_type": "character varying(200)", "nullable": true,
        "description": "İletişim e-postası"},
       {"name": "bolge_id", "position": 3, "data_type": "integer", "references": "satis.bolge.id"}]}
  ]
}
```

`object_type`: `table`, `view`, `entity`, `semantic_model`, `report`, `file`, `collection`, `other`. Aynı sözleşme
kaynağın ekranından dosya olarak da yüklenebilir.

## OpenLineage alıcısı (K-031)

Soy kütüğü olayları için program kurulmaz: toplayıcı eklerken "OpenLineage alıcısı" seçilir, anahtar Airflow, Spark, dbt
veya Flink'in OpenLineage HTTP aktarımına verilir:

```yaml
transport:
  type: http
  url: https://grc.ornek.com.tr
  endpoint: api/tdr/collector/openlineage
  auth:
    type: api_key
    apiKey: <toplayıcı anahtarı>
```

Veri setleri kataloğa, kaynağın "Soy kütüğü ad alanı" alanındaki değerle (ör. `postgres://dwh-prod:5432`) eşlenir. Olayın
yalnızca veri seti adları ve kolon eşlemesi (`columnLineage`) saklanır.

## Platform uç noktaları (toplayıcı anahtarıyla)

| Uç nokta | İş |
| --- | --- |
| `GET /api/tdr/collector/whoami` | Toplayıcı, kaynak, merkezî ayarlar ve kaynağın hazır sorguları |
| `POST /api/tdr/collector/catalog` | `{filename, content_base64, compressed: "gzip", scope?, dry_run?, sample_stats?, client}` |
| `POST /api/tdr/collector/status` | `{result: "error", message, client}`: yerel hatayı bildirir |
| `POST /api/tdr/collector/openlineage` | OpenLineage RunEvent (veya `{events: [...]}`); yalnızca OpenLineage alıcısı türündeki toplayıcı |

Gövde en çok 18 MB'tır (sıkıştırılmış katalog ~13 MB). Daha büyük kaynakları şemalara bölüp birden çok toplayıcı tanımlayın.
