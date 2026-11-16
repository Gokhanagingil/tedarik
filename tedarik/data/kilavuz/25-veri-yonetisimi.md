# Veri yönetişimi

> Menü: Veri yönetişimi. Kimler için: veri sahipleri, veri yöneticileri (data steward), teknik sorumlular, raporlama ve analitik ekipleri.

Veri yönetişimi "hangi veri ne anlama geliyor, nerede duruyor, nereden gelip nereye gidiyor, ne kadar doğru ve kimin sorumluluğunda" sorularını yanıtlar. **Platform kaynak sistemlerdeki veriyi taşımaz**: yalnızca meta veri (tablo ve kolon adı, tip, açıklama, anahtar) ve sayılar (satır sayısı, hatalı kayıt sayısı) gelir.

## Roller (veri sorumlulukları)

| Sorumluluk | Ne yapar |
|---|---|
| Veri sahibi | Verinin hesabını verir; terimleri ve erişim taleplerini onaylar. |
| Veri yöneticisi | Tanımları yazar ve günceller, kalite kurallarını izler. |
| Teknik sorumlu | Sistemi işletir; toplayıcıyı kurar, talepleri uygular. |

Sorumluluk tabloda atanmamışsa veri alanından, o da yoksa kaynaktan **devralınır**. **[Sahiplik Matrisi](#/stewardship)** kişi bazında kimin neyden sorumlu olduğunu ve sahipsiz tabloları gösterir; buradan toplu atama yapılır.

## 1. Kaynakları kataloğa almak

1. **Veri Alanları**: Müşteri, Satış, Finans gibi iş alanları; sorumlu birim, veri sahibi ve veri yöneticisi.
2. **Veri Kaynakları → + Veri kaynağı**: SAP HANA, ServiceNow, Dynamics 365, Power BI, PostgreSQL, SQL Server, dosya paylaşımı… Kaynağı veri alanına ve CMDB öğesine bağlayın.
3. Kaynak ekranında **İçe aktar**: platforma göre hazır sorguyu kopyalayıp kaynakta çalıştırın (yalnızca meta veri okur), çıktıyı (CSV, Excel veya JSON) yükleyin, ön izlemeyi kontrol edip uygulayın. Tanınan biçimler: SAP HANA kataloğu ve ABAP sözlüğü, ServiceNow sys_dictionary, Dynamics 365 EntityDefinitions, Power BI, information_schema (PostgreSQL, SQL Server, MySQL, Snowflake, BigQuery, Redshift), Oracle.
4. Yeniden yüklemede iş tanımları korunur; eklenen, kaldırılan ve tipi değişen nesneler değiştirilemez değişiklik geçmişine yazılır ve sahiplere bildirilir.

Elle yükleme yerine **toplayıcı** ile otomatik toplama da yapılabilir (aşağıda).

## 2. Anlam vermek

- **[Veri Kataloğu](#/catalog)**: kaynak → şema → tablo → kolon. Bir kolon iş adı, iş açıklaması veya bağlı sözlük terimi varsa "tanımlı" sayılır.
- **Tablo ekranı**: kolonlar, ilişkiler (yabancı anahtar, SAP kontrol tablosu, ServiceNow referansı), sahiplik, gizlilik sınıfı, kalite, soy kütüğü ve kişisel veri bölümleri. Kolona tıklayınca "bu kolon ne anlama geliyor" paneli açılır.
- **Excel ile toplu tanım:** tablo veya kaynak ekranından kataloğu Excel'e alın, iş adı ve açıklama sütunlarını doldurun, **İş açıklamalarını içe aktar** ile geri yükleyin.

## 3. İş sözlüğü

**[İş Sözlüğü](#/glossary)** kurumun ortak dilidir: her terimin onaylı tanımı, kısaltması, eş anlamlıları, hesaplama kuralı, örneği, sahibi ve kullanıldığı kolonlar.

1. **+ Terim**: tanımı yazın, veri alanını seçin.
2. **Onaya gönder**. Terimin veya veri alanının sahibi ya da veri yöneticisi **Onayla** veya **İade et** der. **Öneren kendi terimini onaylayamaz.**
3. Onaylı terim doğrudan değiştirilmez: **Değişiklik öner** → onay. Her onaylı sürüm değiştirilemez geçmişte kalır; fark görünümü vardır.
4. Kullanımdan kalkan terim **Kullanım dışı bırak** ile işaretlenir.

Terimi kolonlara ve tablolara bağlayın: "bu terim nerede kullanılıyor" sorusunun yanıtı terim ekranında görünür.

## 4. Otomatik toplama (toplayıcı)

**[Toplayıcılar](#/collectors)**: kurum ağında çalışan küçük bir program kaynağın meta verisini okur ve platforma gönderir. Platform kaynağa bağlanmaz, kaynak parolası platformda durmaz.

1. **+ Toplayıcı ekle**: kaynak, bağlayıcı (PostgreSQL, SQLite, SQL sürücüsü, CSV klasörü, OpenLineage), beklenen sıklık, kapsam.
2. **Oluştur ve anahtarı göster**: anahtar **yalnızca bir kez** gösterilir; kopyalayıp toplayıcının ayar dosyasına yazın.
3. **Toplayıcıyı indir (.pyz)**: Python 3.9+ olan bir makinede çalışır, ek paket gerekmez. Ekranda örnek ayar dosyası ve zamanlanmış görev komutları (Linux cron, Windows Görev Zamanlayıcı) hazırdır.
4. Önce `dene` komutuyla bağlantıyı sınayın, sonra zamanlanmış göreve ekleyin.

Geciken veya hata veren toplayıcı teknik sorumluya bildirilir ve İşlerim'e düşer. Bir gönderim kaynaktaki tabloların büyük kısmını kaldırılmış gösteriyorsa (eşik %30) platform gönderimi reddeder; değişiklik gerçekse eşiği geçici olarak yükseltin. Anahtar sızdıysa **Anahtarı yenile**. Teknik ayrıntı `docs/TOPLAYICI.md` belgesindedir.

## 5. Soy kütüğü ve etki analizi

**[Soy Kütüğü](#/lineage)** verinin kaynaktan rapora yolculuğunu tablo ve kolon düzeyinde tutar.

- **+ Bağlantı**: kaynak tablo[.kolon] → hedef tablo[.kolon], tür (doğrudan, dönüşüm, toplama, dolaylı), dönüşüm açıklaması, veri akış işi.
- **Excel/CSV içe aktar**: çok sayıda bağlantı için şablon.
- **dbt manifesti**: dbt projelerinin model bağımlılıkları.
- **OpenLineage alıcısı**: Airflow, Spark ve dbt işlerinden olaylar otomatik gelir.
- **Etki analizi**: bir tablo veya kolon değişirse aşağı akışta etkilenen tablolar, raporlar, süreçler (BİA), KVKK işleme faaliyetleri, kontroller, riskler, yapay zekâ sistemleri ve bildirilecek kişiler. **Etki raporu (CSV)** ve **Sahiplere bildir** ile planlanan değişikliği önceden duyurun.
- **Akış şeması**: soldan sağa görsel akış; düğüme tıklayınca ayrıntı.

## 6. Veri kalitesi

**[Veri Kalitesi](#/quality)**: kurallar verinin bulunduğu yerde çalışır, platforma yalnızca sayılar gelir.

1. **+ Kural** (veya tablo ekranındaki önerilerden tek tıkla): zorunlu, benzersiz, sayısal aralık, desen, izin verilen değerler, referans bütünlüğü, tazelik, satır sayısı, biçim (T.C. kimlik, VKN, IBAN, e-posta, telefon, kart, IPv4); eşik (en düşük geçme %), önem, sahip.
2. Toplayıcı varsa kural her çalışmada kurum ağında çalışır. Yoksa kural ekranındaki SQL'i kaynakta çalıştırıp **Sonuç gir**.
3. Eşiğin altında kalan kural **bulgu ve DÖF açar**; tekrarda bulgunun sayacı artar. Kural bir GRC kontrolüne bağlıysa kontrol test sonucu yazar.
4. Skor kartı: tamlık, geçerlilik, benzersizlik, tutarlılık, güncellik; kaynak ve veri alanı bazında. **Hacim anomalisi** (satır sayısında sıra dışı değişim) **Değerlendir** ile gerekçelendirilir.

## Sağlık kontrolleri

GRC Sağlık Kontrolü veri yönetişimi için de uyarır: sahibi olmayan tablolar, "Gizli" sınıfın altında kalan kişisel veri kolonları, uzun süredir onay bekleyen terimler, geciken toplayıcılar, kopuk soy bağlantıları, başarısız yüksek önemli kalite kuralları.
