# Dağıtım

Hedef: Tedarik Portalı'nı başka uygulamaların da çalıştığı bir Linux sunucusunda, onları etkilemeden çalıştırmak.

## Yalıtım güvenceleri

| Konu | Uygulama |
| --- | --- |
| Dizin | Yalnızca `/opt/tedarik` (sürümler `releases/<commit>`, etkin sürüm `current`, sırlar `secrets/`, yedekler `backups/`) |
| Docker | Compose projesi `tedarik`; konteyner, ağ ve volume adları `tedarik_` önekli. Başka proje, ağ veya volume'a dokunulmaz |
| Ağ | Uygulama yalnızca `127.0.0.1:18090` üzerinde dinler; dışarıya port açılmaz. PostgreSQL dışarıya kapalı iç ağdadır (`internal: true`), portu hiç yayımlanmaz |
| Kaynak | Uygulama 512 MB / 1 CPU / 120 süreç; veritabanı 768 MB / 1 CPU / 200 süreç; günlük dosyaları 3 × 10 MB |
| Güvenlik | Root olmayan kullanıcı (UID 10001), salt okunur kök dosya sistemi, tüm Linux yetenekleri kapalı, `no-new-privileges` |
| Port çakışması | 18090 başka bir süreçteyse kurulum durur (`TEDARIK_PORT` ile başka port seçilir) |
| Denetim | Kurulumdan önce ve sonra diğer tüm konteynerlerin kimliği ve başlama zamanı karşılaştırılır; fark varsa kurulum hata verir |
| Yasak işlemler | Sunucu genelinde `docker system prune`, `docker compose down -v`, başka uygulamanın ters vekil ayarı değiştirilmez |
| Sırlar | `/opt/tedarik/secrets/` (0400): veritabanı, MCP anahtarı, ServiceNow parolası, MCP belirteci veya OAuth sırrı, Entra istemci sırrı; boş dosya "yapılandırılmadı" demektir |
| Cron | Yalnızca kendi dosyaları: `/etc/cron.d/tedarik-backup` (günlük yedek, 02:17), `/etc/cron.d/tedarik-grc` (iç otomatik kontroller, 05:43), `/etc/cron.d/tedarik-cmdb` (CMDB senkronu ve CI risk kuralları, 04:23) |

## İlk kurulum (GitHub Actions ile)

1. Sunucuda dağıtım için bir SSH anahtarı tanımlayın (root veya parolasız `sudo` yetkili kullanıcı). Docker Engine ve Compose v2 kurulu olmalı.
2. GitHub'da `Gokhanagingil/tedarik` → Settings → Environments → `tedarik` ortamını açın ve şu gizli değerleri ekleyin:

   | Ad | Değer |
   | --- | --- |
   | `TEDARIK_SSH_HOST` | Sunucu adresi |
   | `TEDARIK_SSH_USER` | SSH kullanıcısı |
   | `TEDARIK_SSH_KEY` | Özel anahtarın tamamı |
   | `TEDARIK_SSH_KNOWN_HOSTS` | `ssh-keyscan -t ed25519 <adres>` çıktısı (sunucu anahtarını önceden doğrulayın) |

3. Actions → **Deploy Tedarik (isolated)** → Run workflow. Sunucuda Docker yoksa "install_docker" kutusunu işaretleyin; Ubuntu paketlerinden (`docker.io`, `docker-compose-v2`, `docker-buildx`) kurulur. Docker kendi ağ kurallarını ekler; mevcut uygulamaların dinlediği portları değiştirmez. İş önce testleri çalıştırır, sonra kaynağı sunucuya kopyalar ve `deploy/deploy.sh` betiğini çalıştırır.
4. İlk yöneticinin geçici parolası sunucuda yalnızca root'un okuyabildiği `/opt/tedarik/.first-login` dosyasındadır. Okuyun, ilk girişte değiştirin, dosyayı silin. Parolayı CI günlüğüne veya sohbete yapıştırmayın.

Elle kurulum: kaynağı `/opt/tedarik/releases/<ad>` altına çıkarın, `current` bağlantısını oraya yöneltin, `cd /opt/tedarik/current && sh deploy/deploy.sh`.

## Erişim (HTTPS)

Kurulum işinde `domain` verilirse (test sunucusu: `tedarik.204-168-247-101.sslip.io`, K-014) yalnızca bu projeye ait Caddy ters vekili 443'ü açar ve Let's Encrypt sertifikasını 443 üzerinden (TLS-ALPN-01) alır; 80. porttaki başka uygulamaya dokunulmaz. Alan adı sunucuda `/opt/tedarik/settings.env` dosyasında saklanır, sonraki kurulumlar aynı adla çalışır. Kurulum işi sonunda sertifikayı, güvenlik başlıklarını ve anonim erişimin 401 döndüğünü dışarıdan denetler.

Vekil arkasında uygulama `TEDARIK_TRUST_PROXY=1` ile çalışır: giriş hız sınırı Caddy'nin yazdığı `X-Forwarded-For` (gerçek istemci adresi) ile uygulanır. Bu ayar yalnızca uygulamanın önünde kendi vekilimiz varken açılır.

## ServiceNow CMDB bağlantısı (K-019, isteğe bağlı)

Portal ServiceNow Table API'sini salt okunur kullanıcıyla okur (`cmdb_ci_business_app`, `cmdb_ci_appl`, `cmdb_ci_server`,
`cmdb_ci_db_instance`, `cmdb_rel_ci`; sayfalı, `sys_updated_on` ile artımlı). Bağlantı yoksa CMDB verisi MCP ile itilir
(`docs/MCP_SOZLESMESI.md`, Akış 5) ve gece görevi yalnızca risk kurallarını çalıştırır.

1. ServiceNow'da `cmdb_read` (ve ilişki tablosu için okuma) yetkili, etkileşimsiz bir hizmet hesabı açın.
2. Kurulumu `TEDARIK_SN_INSTANCE=https://<kurum>.service-now.com` ve `TEDARIK_SN_USER=<hesap>` ile çalıştırın (ayarlar
   `/opt/tedarik/servicenow.env` dosyasında saklanır; adres `https://` ile başlamalıdır).
3. Parolayı yalnızca sunucuda yazın: `sudo sh -c 'umask 077; printf %s "<parola>" > /opt/tedarik/secrets/sn_password'`
   ve uygulamayı yeniden başlatın (`docker compose -p tedarik restart app`). Parola Git'e, CI günlüğüne ve arayüze girmez.
4. Sunucunun ServiceNow adresine HTTPS (443) ile çıkabildiğini doğrulayın; CMDB Panosu'ndan "ServiceNow'dan senkronize et".

**ServiceNow MCP sunucusu (K-021).** Table API yerine (veya Table API açılamıyorsa) kurumun ServiceNow MCP sunucusu
kullanılabilir. `/opt/tedarik/servicenow.env` dosyasına `TEDARIK_SN_MCP_URL=https://<mcp-uç-noktası>` yazın ve
kimlik bilgisini seçin: sabit belirteç için `/opt/tedarik/secrets/sn_mcp_token`; OAuth istemci kimlik bilgisi için
ayrıca `TEDARIK_SN_MCP_TOKEN_URL=https://<kurum>.service-now.com/oauth_token.do`, `TEDARIK_SN_MCP_CLIENT_ID=<istemci>`
ve `/opt/tedarik/secrets/sn_mcp_client_secret`. Kurulumu yeniden çalıştırın; CMDB Panosu'nda "MCP bağlantısını sına"
sunucuya bağlanır, araçları listeler ve `cmdb.mcp` politikasındaki araçla tek kayıt okur. Araç adı veya argümanları
farklıysa politikayı düzeltin.

Alan ve değer eşlemesi (`cmdb.servicenow`) ile kural eşikleri (`cmdb.rules`: kapsam ortamı, yama 35 gün, yeniden başlatma
100 gün, uyarı günleri) Politika Parametreleri'nden değişir. Özel alanlar (ör. `u_os_end_of_support`, `u_last_patch_date`)
kurumun CMDB'sindeki adlarla eşlenmelidir.

## Kurumsal giriş: Entra ID ve MFA

Entra uygulama kaydı ve Koşullu Erişim ayarları `docs/KIMLIK.md` içindedir. Sunucuda:

1. `/opt/tedarik/entra.env` (root, 0600): `TEDARIK_ENTRA_TENANT_ID=<kiracı GUID>`, `TEDARIK_ENTRA_CLIENT_ID=<istemci GUID>`,
   `TEDARIK_ENTRA_AUTH_CONTEXT=c1` (MFA isteyen Koşullu Erişim ilkesinin hedeflediği kimlik doğrulama bağlamı).
2. İstemci sırrı: `sudo sh -c 'umask 077; printf %s "<sır>" > /opt/tedarik/secrets/entra_client_secret'`.
3. Kurulumu `domain` ile çalıştırın. Dönüş adresi `https://<alan adı>/auth/entra/callback` olur. Betik yerel yönetici
   açmaz ve `python -m tedarik.entra_check` ön denetimini çalıştırır: ayarlar, Microsoft OpenID yapılandırması, imza
   anahtarları ve istemci sırrının geçerliliği (belirteç alınıp atılır) denetlenir; Entra yöneticisinin doğrulaması
   gereken maddeler listelenir.
4. Entra modunda parola girişi kapalıdır; canlı kabul testi (`acceptance`) yerel parolalı hesaplarla çalıştığından bu
   modda kullanılmaz. Yerel moda dönmek için `entra.env` dosyasını kaldırıp kurulumu yeniden çalıştırın.

### Entra ayarlarını arayüzden tanımlama (K-024)

`entra.env` dosyası yerine ayarlar Yönetim → Entegrasyonlar → "Entra ID ile giriş ve MFA" kartında da tanımlanabilir
(kiracı, istemci, MFA bağlamı; istemci sırrı şifreli saklanır). Önce yerel modda tanımlayıp "Sına" ile doğrulayın,
sonra kurulum işini `auth_mode=entra` ile çalıştırın; seçim sunucuda `/opt/tedarik/auth.env` dosyasında saklanır.
Tanım eksikse uygulama Entra modunda açılmaz ve kurulum sağlık denetiminde durur; yerel moda dönmek için `auth_mode=local`.

## Entegrasyon sırları, bildirimler ve standart kütüphanesi (K-023 – K-025)

- **Sır anahtarı:** kurulum betiği `/opt/tedarik/secrets/app_secret_key` (Fernet anahtarı) üretir; arayüzden girilen
  parola, belirteç ve web kancaları bu anahtarla şifrelenip veritabanında saklanır. Anahtar yedeğe girmez; yedekten
  geri yüklemede aynı anahtar korunmazsa sırlar arayüzden yeniden girilir.
- **Uygulama adresi:** `TEDARIK_PUBLIC_URL=https://<alan adı>` bildirim bağlantıları ve Entra dönüş adresi için
  kurulumda kendiliğinden ayarlanır.
- **Bildirimler:** `/etc/cron.d/tedarik-notify` 10 dakikada bir kuyruğu gönderir (`python -m tedarik.notify deliver`),
  her sabah 07:41'de (TSİ) iş özeti ve hatırlatmaları oluşturur (`... digest`). E-posta ve Teams Yönetim →
  Entegrasyonlar'da tanımlanır; olay → kanal eşlemesi Yönetim → Bildirimler'dedir.
- **Standart kütüphanesi:** her kurulumda `python -m tedarik.standards_cli install` NIST SP 800-53 Rev. 5.2.0 ve
  NIST CSF 2.0 paketlerini kurar veya günceller; kurumun uygulanabilirlik kararları ve eşlemeleri korunur.
- **ServiceNow görev eşlemesi (isteğe bağlı):** Sistem parametrelerinde `servicenow.tasks` (`enabled`, `table`,
  `assignment_group`). Hizmet hesabının yalnızca görev tablosuna yazma yetkisi olmalı; CMDB'ye yazılmaz.
- **Yapay zekâ:** Claude SDK paketi (`anthropic`) requirements.txt'e onayla eklenecek; o zamana kadar kural tabanlı
  öneriler çalışır.

## Demo verisi ve kabul testi

- `seed_demo` işaretlenirse sentetik demo verisi yüklenir (`python -m tedarik.demo`; yalnızca boş ya da yalnızca demo verisi içeren veritabanına). Önceki sürümle yüklenmiş demoya yeni sürümün bölümleri (şirketler, süreç haritası, kurumsal risk, dokümanlar, CMDB, iş sürekliliği) kullanıcılara ve mevcut kayıtlara dokunmadan eklenir. Demo kullanıcılarının geçici parolaları `/opt/tedarik/.demo-users` dosyasındadır (yalnızca root). Yönetici, Kullanıcılar ekranında "Geçici parola ver" ile yeni parola da üretebilir.
- `acceptance` işaretlenirse kurulumdan sonra `scripts/acceptance.py` canlı adrese karşı çalışır: rol bazlı uçtan uca senaryolar, güvenlik, MCP, yanıt süreleri ve tarayıcı turu. `kabul.yonetici` hesabı geçici parolayla açılır/sıfırlanır; parola ve MCP anahtarı günlükte maskelenir, iş sonunda kabul yöneticisinin parolası yeniden rastgele yapılır. Test, "KABUL" işaretli kayıtlar yazar ve kendi açtığı test hesaplarını devre dışı bırakır. Sonuç, işin özetinde ve `kabul-<çalıştırma>` eserinde (ekran görüntüleri yalnızca sentetik veri).

## Erişim (SSH ile, TLS olmadan)

Uygulama bilerek yalnızca sunucunun içinden erişilebilir. İlk deneme için SSH port yönlendirmesi yeterlidir; dışarıya hiçbir şey açılmaz:

```
ssh -L 18090:127.0.0.1:18090 <kullanıcı>@<sunucu>
```

Tarayıcı: `http://localhost:18090`.

Kalıcı erişim ayrı bir karardır ve sunucudaki diğer uygulamanın ayarlarına dokunmadan yapılmalıdır. Seçenekler:

1. **Ayrı alan adı + kurumsal TLS ters vekili** (önerilen; KS GRC `enterprise/nginx.conf.example` düzeni). Vekil `127.0.0.1:18090` adresine yönlendirir. Ardından `TEDARIK_COOKIE_SECURE=1` ve kurumsal girişte `TEDARIK_AUTH_MODE=entra` (docs/KIMLIK.md).
2. **Yalnızca kurum ağından erişim**: güvenlik duvarında belirli bir porta yalnızca kurum IP'lerine izin veren ayrı bir TLS vekili.

Şifrelenmemiş HTTP üzerinden parola gönderilmemelidir; uygulamayı TLS'siz olarak doğrudan internete açmayın.

## Güncelleme

Aynı GitHub Actions işi. Betik güncellemeden önce veritabanı yedeği alır (`backups/*-pre-deploy.dump`), yeni imajı derler, konteynerleri yeniler, sağlık denetimini (anonim `/api/health` → 401) ve yalıtım karşılaştırmasını yapar. Son 5 sürüm klasörü tutulur. Şema değişiklikleri açılışta kilit altında uygulanır (`tedarik/migrate.py`).

## Yedek ve geri yükleme

- Günlük yedek: `/opt/tedarik/backups/tedarik-<UTC>-daily.dump` (PostgreSQL özel biçimi) ve `.sha256`; 14 günden eskisi silinir. Elle: `sh /opt/tedarik/current/deploy/backup.sh elle`.
- Yedekler aynı diskte durur; **sunucu dışına şifreli kopya** ve saklama politikası işletmecinin sorumluluğundadır. Yedek kişisel veri içerebilir; Git'e veya CI'a yüklenmez.
- Geri yükleme yalnızca **yeni ve boş** bir veritabanına yapılır, mevcut veritabanı ezilmez:

```
sha256sum -c <yedek>.dump.sha256
docker compose -p tedarik -f /opt/tedarik/current/deploy/compose.yaml exec -T db createdb -U tedarik tedarik_geri
docker compose -p tedarik -f /opt/tedarik/current/deploy/compose.yaml exec -T db pg_restore -U tedarik -d tedarik_geri --no-owner < <yedek>.dump
```

  Doğruladıktan sonra `secrets/database_url` içindeki veritabanı adını değiştirip uygulamayı yeniden başlatın. Bu yol prova edilmiştir.

## Durdurma

Yalnızca bu uygulamayı durdurur, veriyi korur:

```
docker compose -p tedarik -f /opt/tedarik/current/deploy/compose.yaml down
```

`down -v` veriyi siler; kullanmayın.

## Prova

2026-11-13'te kurulum, ikinci kurulum (güncelleme), yedek, yedekten boş veritabanına geri yükleme ve Docker yeniden başlatması, yanda çalışan ilgisiz bir konteynerle birlikte denendi; ilgisiz konteynerin kimliği ve başlama zamanı değişmedi.
