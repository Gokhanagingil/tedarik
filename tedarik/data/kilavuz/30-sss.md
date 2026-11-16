# Sık sorulanlar ve sorun giderme

> Kimler için: herkes. Sorununuz burada yoksa yöneticinize başvurun.

## Giriş ve hesap

**Giriş yapamıyorum, "Giriş başarısız" diyor.**
Kullanıcı adınızı kontrol edin. Üst üste 8 hatalı denemeden sonra 5 dakika beklemeniz gerekir. Parolanızı unuttuysanız yöneticiden geçici parola isteyin.

**Hesabımın süresi doldu.**
Bitiş tarihi olan hesaplar (ör. dış denetçi) tarih geçince açılmaz. Yöneticiniz Kullanıcılar → Erişim süresi ekranından uzatabilir.

**Kurumsal girişte (Microsoft) "yetkiniz yok" görüyorum.**
Entra ID'de size uygulama rolü atanmamış olabilir. BT biriminden `KS.TDR.*` rollerinden birinin atanmasını isteyin.

**Şirket ağından açılmıyor, "Access Blocked" / "Web Page Blocked" sayfası çıkıyor.**
Kurumun güvenlik duvarı sınıflandırılmamış adresleri engelliyor olabilir. BT biriminden adresin izin listesine alınmasını isteyin; kurum alan adı altında bir adres kullanıldığında sorun genelde ortadan kalkar.

## Yetki

**Bir düğme veya menü görünmüyor.**
Rolünüz o işlemi yapmaya yetkili değildir. Hangi rolün ne yapabildiğini Yönetici ve Denetçi Rol ve Yetki Matrisi'nde görür.

**"Yalnızca kendi biriminizin kayıtlarını değiştirebilirsiniz."**
Birim Kullanıcısı yalnızca atandığı birimin kaydına yazar. Kayıttaki birimi kontrol edin veya yöneticiden birim ataması isteyin.

**"Bu işlem yalnızca kullanıcı oturumuyla yapılabilir."**
İşlem bir entegrasyon anahtarıyla değil, oturum açmış bir kişiyle yapılmalıdır (onaylar, kararlar).

**Kendi kaydımı onaylayamıyorum.**
Dört göz ilkesi: hazırlayan veya öneren onaylayamaz. Başka bir yetkiliye yönlendirin.

## Kayıtlar

**Kaydı nasıl silerim?**
Silme yoktur. Durumu "iptal", "kullanım dışı", "kapatıldı" veya "geçersiz" yapın; geçmiş ve denetim izi korunur.

**Kodu değiştirmek istiyorum.**
Kayıt kodları sistemce verilir ve değişmez. Kaynak sistemdeki numarayı kaydın açıklamasına veya varsa referans alanına yazın.

**Yanlış bir test sonucu / değerlendirme girdim.**
Bu kayıtlar değiştirilemez. Doğru değerle yeni bir sonuç veya değerlendirme girin; açıklamada düzeltme olduğunu belirtin. Eski kayıt iz olarak kalır.

**Dosya yükleyemiyorum.**
En büyük dosya 12 MB'tır. Kabul edilen türler: PDF, Word, Excel, PowerPoint, resim (PNG, JPG, WEBP), metin, CSV, JSON, XML, e-posta (.eml) ve ZIP. Uzantısı içeriğiyle uyuşmayan dosya reddedilir. Büyük belgeleri PDF olarak küçültün veya ZIP'leyin.

**"Zorunlu alan eksik" iletisi aldım.**
İletide eksik alanların adı yazar. Bazı alanlar duruma göre zorunlu olur (ör. yüksek önemli bulguda hedef tarih, kısmen uyumlu değerlendirmede açıklama).

## Aktarım

**Excel'den yüklediğim değer kaydı değiştirmedi.**
Aktarım var olan kayıtta yalnızca boş alanları doldurur; platformda girilmiş değeri korur. Değiştirmek için kaydı ekrandan düzenleyin.

**İçe aktarımda bazı satırlar hata verdi.**
**Dene (kayıt yazmaz)** sonucundaki satır numarası ve iletiyi okuyun; düzeltip yeniden deneyin. Hatalı satırlar yazılmaz, doğru satırlar uygulanır.

## Bildirimler

**E-posta gelmiyor.**
Kullanıcı kaydınızda e-posta adresi olmalı ve kurum e-posta bağlantısını açmış olmalıdır. İletiler 10 dakikada bir gönderilir.

## Veri yönetişimi

**Toplayıcı "kaldırma eşiği aşıldı" hatası veriyor.**
Gönderim kaynaktaki tabloların büyük kısmını kaldırılmış gösteriyor; çoğunlukla toplayıcı hesabının yetkisi veya kapsam ayarı değişmiştir. Değişiklik gerçekse toplayıcı kaydında eşiği geçici olarak yükseltin.

**Toplayıcı anahtarını kaybettim.**
Anahtar bir kez gösterilir ve platformda saklanmaz. Toplayıcı ekranında **Anahtarı yenile** ile yenisini alın; eskisi geçersiz olur.

**Kalite kuralı "çalışmadı" görünüyor.**
Toplayıcı kuralı çalıştıramamıştır (tablo adı değişmiş, yetki yok). Kural ekranındaki ileti nedeni yazar. Toplayıcı yoksa SQL'i kaynakta çalıştırıp sonucu elle girin.

## Kişisel veri

**İlgili kişi başvurusuna ad yazmalı mıyım?**
Hayır. Veri en aza indirme ilkesi gereği iç referans (ör. müşteri numarası) yazın.

**İhlal kaydında karar verdim, yanlışmış.**
Bildirim kararı geri alınamaz. Gerekçe ve önlem alanlarına durumu yazın; gerekiyorsa Kurula ek bildirim yapın ve tarihini girin.
