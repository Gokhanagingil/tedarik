# Durum

Son güncelleme: 2026-11-13 · Aşama: mimari temel tamamlandı, geliştirme Claude Code'da sürecek.
Bu dosya her çalışma oturumunun sonunda güncellenir: kararlar, yapılanlar, sıradaki adımlar.

## Kararlar (özet)

Ayrıntı `docs/KARARLAR.md` içinde.

- KS GRC (`control` reposu) ile aynı yığın: Python 3.12, standart kütüphane, SQLite, derlemesiz istemci.
- Tedarikçi ve Angajman ayrı kayıtlar.
- Tablolar `tdr_` önekli, uç noktalar `/api/tdr` altında.
- Süreçler veri olarak tanımlı; kaynak bulma modülü hazır ama kapalı.
- Entegrasyon: MCP uygulaması REST API'ye yazar.

## Varsayımlar (Gökhan Bey'in onayıyla)

- Hedef ortam KS GRC'nin kurumsal profiliyle aynı: Docker, TLS sonlandıran ters vekil, tek kiracılı Entra.
- Portalı yalnızca iç kullanıcılar kullanır; anketleri iç kullanıcılar yanıtlar.
- Tek şirket (tek kiracı).
- SAP ve Dynamics sütun başlıkları tahminidir (`transfer.py` içindeki `ALIASES`).
- Başlangıç tedarikçi tipleri ve değerlendirme kriterleri öneridir.

## Yapılanlar

- Temel katman: yapılandırma, şema kaydı, veritabanı, ortak kayıt işlemleri, yönlendirici, güvenlik başlıkları, köken denetimi, tekrar koruması, denetim izi.
- Yetki: beş rol, en az yetkili MCP anahtarı. Anonim erişim açılmaz.
- Modüller: `core`, `performance`, `surveys`, `risks`, `transfer`, `dashboard` (açık); `workflow`, `sourcing` (kapalı).
- Testler: 18 uçtan uca test, tamamı geçiyor (`python -m unittest discover -s tests -v`).
- Belgeler: `docs/MIMARI.md`, `docs/VERI_MODELI.md`, `docs/UYUM_SOZLESMESI.md`, `docs/KARARLAR.md`.

## Bilinen eksikler

- **Arayüz yok.** Yalnızca API ve yer tutucu sayfa var.
- **Oturum sağlayıcısı yok.** Yalnızca yerel `dev` modu ve MCP anahtarı çalışır; `local` ve `entra` modları açılışta durur.
- **XLSX yok.** İçe ve dışa aktarma şimdilik CSV (UTF-8, `;` ayraçlı; Excel doğrudan açar).
- **İçe aktarma yalnızca tedarikçi ana verisi için.** Angajman, katalog, sözleşme aktarımları yok.
- **Birim bazlı yazma kapsamı yok.** Birim Kullanıcısı tüm angajmanları değiştirebilir.
- **Dağıtım dosyaları yok** (Dockerfile, compose, yedekleme).
- **Periyodik işler yok** (gözden geçirme hatırlatmaları, kampanya takvimi).
- **KS GRC kısmen incelendi.** Okunmayan dosyalar `docs/UYUM_SOZLESMESI.md` başında listeli.

## Sıradaki adımlar (sırayla)

1. **KS GRC'yi tam oku ve uyumu doğrula.** `control` reposunu yan klasöre klonla. Okunmayan dosyaları incele, `UYUM_SOZLESMESI.md` içindeki "Doğrulanacak" satırlarını kapat, farkları düzelt.
2. **Kimlik aktarımı.** `identity.py` ve `entra_auth.py` dosyalarını `tedarik/vendor/` altına al; `local` ve `entra` modlarını aç; rolleri Entra uygulama rollerine bağla; birim bazlı yazma kapsamını ekle.
3. **Excel.** `xlsx_io.py` aktarımı; XLSX içe ve dışa aktarma; uygulamanın kendi ürettiği içe aktarma şablonu; angajman, katalog ve sözleşme aktarımları; gerçek başlıklarla `ALIASES` doğrulaması.
4. **Arayüz.** KS GRC'nin görsel diliyle: tedarikçi listesi ve filtreler, tedarikçi 360 paneli, angajman, performans, anket, risk ekranları, pano (satır içi SVG grafikler). Her ekran için Playwright duman testi.
5. **Dağıtım.** KS GRC'nin Dockerfile, compose ve yedekleme düzenini uyarla; CI'a gitleaks ekle.
6. **Periyodik işler.** Kritiklik seviyesine göre değerlendirme, anket ve risk gözden geçirme takvimi; geciken işler panosu.
7. **MCP sözleşmesi.** `docs/MCP_SOZLESMESI.md`; KS GRC'ye kanıt akışı için örnek otomatik kontroller.
8. **Kaynak bulma.** Süreç tasarımı onaylanınca `workflow,sourcing` modüllerini aç, ekranlarını yap.

## Gökhan Bey'den beklenenler

- SAP, Dynamics ve dış kaynak yönetim sisteminden örnek dışa aktarım (sütun başlıkları yeterli).
- Tedarikçi tipleri ve iş birimleri listesi.
- Yeni rollerin KS GRC'nin Entra uygulama kaydına mı, ayrı bir kayda mı ekleneceği.
- `tedarik` ve `control` repolarının görünürlüğü (şu an ikisi de herkese açık).
