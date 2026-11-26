# Veri dökümü (test sunucusu demo verisi)

`hetzner-demo.json.gz`, test sunucusundaki verinin motor bağımsız dökümüdür (biçim `tedarik.data.v1`, K-037). Veri sentetiktir: demo üreticisinin oluşturduğu kayıtlar ve kabul testlerinin (KABUL işaretli) kayıtları.

**Dökümde olmayanlar:** kullanıcı hesapları ve parolalar, oturumlar, kullanıcı rol/birim/erişim süresi/dış denetçi atamaları, tekrar koruma önbelleği, entegrasyon ayar ve sırları, toplayıcı anahtarları, bildirim kutusu. Kayıtlardaki kişi alanları (sahip, sorumlu, oluşturan) kullanıcı adı olarak metin hâlinde kalır.

## Şirket sunucusuna yükleme

Yükleme yalnızca **boş** bir kuruluma yapılır (uygulama kurulmuş ve en az bir kez açılmış, ama tedarikçi, risk, denetim gibi iş kaydı girilmemiş olmalı). Önce yükleyin, sonra kullanıcıları açın.

Docker kurulumunda (`deploy/deploy.sh`), depo klasöründe:

```bash
gunzip -c veri-dokumu/hetzner-demo.json.gz | sudo docker exec -i tedarik-app-1 python -m tedarik.dataio import -
```

Docker olmadan (uygulamanın ortam değişkenleriyle):

```bash
python -m tedarik.dataio import veri-dokumu/hetzner-demo.json.gz
```

Ardından yönetici hesabı (geçici parola yalnızca ekrana yazılır, ilk girişte değiştirilir):

```bash
sudo docker exec tedarik-app-1 python -m tedarik.bootstrap create grc.yonetici
```

Demo kayıtlarında sorumlu olarak geçen kişiler (ör. `selin.aydin`, `zeynep.demir`) hesap olarak gelmez. Aynı kullanıcı adlarıyla Yönetim → Kullanıcılar ekranından hesap açarsanız İşlerim ve bildirimler bu kişilere göre çalışır.

Yükleme tek işlemdir: hata olursa hiçbir şey yazılmaz. Kimlikler ve kayıt bağlantıları korunur; yeni kayıtların kodları kaldığı yerden devam eder.
