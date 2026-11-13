# Kimlik ve Kurumsal Giriş

Tedarik, KS GRC'nin kimlik kodunu kullanır (`tedarik/vendor/`, kaynak `control@7720f4b`). Entra yöneticisinin adımları KS GRC'nin `docs/ENTRA_ID.md` belgesiyle aynıdır; farklar aşağıdadır.

## Entra uygulama kaydı

1. Tek kiracılı **Web** uygulaması; dönüş adresi tam olarak `https://<tedarik-adresi>/auth/entra/callback`. Örtük akış ve public client kapalı. Kapsam `openid profile`, yetkilendirme kodu + PKCE. Graph izni gerekmez.
2. **App roles** (kullanıcı ve gruplara atanabilir), değerler karakter karakter:

   | Değer | Tedarik rolü |
   | --- | --- |
   | `KS.TDR.Admin` | Yönetici |
   | `KS.TDR.SupplierManager` | Tedarikçi Yöneticisi |
   | `KS.TDR.UnitUser` | Birim Kullanıcısı |
   | `KS.TDR.Auditor` | Denetçi (salt okur) |
   | `KS.TDR.Viewer` | Görüntüleyici |

   Birden çok rol atanmışsa en yetkilisi geçerlidir. `KS.GRC.*` rolleri tedarikte yetki vermez. Rollerin KS GRC kaydına mı ayrı kayda mı ekleneceği açık karardır (DURUM.md, "Gökhan Bey'den beklenenler"); kod iki durumda da çalışır.
3. **Enterprise applications → Assignment required = Yes.**
4. MFA'yı zorunlu kılan Conditional Access ilkesine bağlı, yayımlanmış bir **authentication context** (`c1`…`c99`). Token configuration altında ID token için `acrs` isteğe bağlı talebi.
5. İstemci sırrı kurumun sır kasasında; dağıtımda salt okunur dosya olarak bağlanır.

## Uygulama ayarları

| Ayar | Değer |
| --- | --- |
| `TEDARIK_AUTH_MODE` | `entra` |
| `TEDARIK_COOKIE_SECURE` | `1` (zorunlu) |
| `TEDARIK_ENTRA_TENANT_ID`, `TEDARIK_ENTRA_CLIENT_ID` | UUID |
| `TEDARIK_ENTRA_REDIRECT_URI` | Kayıttaki dönüş adresi, karakter karakter aynı |
| `TEDARIK_ENTRA_AUTH_CONTEXT` | ör. `c7` |
| `TEDARIK_ENTRA_CLIENT_SECRET_FILE` | sır dosyası |

Eksik veya çelişkili ayarla uygulama başlamaz. Entra ayarı verilip mod `entra` değilse de başlamaz.

## Davranış

- İlk başarılı girişte hesap kiracı ve nesne kimliğiyle açılır (`entra:<kiracı>:<oid>`); yerel hesapla ad veya e-postayla eşleme yapılmaz.
- Oturum en çok 1 saat ve token süresini aşmaz. Rol değişince aynı kullanıcının önceki oturumu düşer.
- Kurumsal modda parola girişi, parola değişimi ve portaldan kullanıcı açma 403'tür. Yönetici yalnızca birim ataması (`org_unit_ids`) ve hesabı devre dışı bırakma yapar; devre dışı hesabın açık oturumu bir sonraki istekte 401 alır.
- Çerezler `__Host-tdr_session` ve `__Host-tdr_flow`; KS GRC'nin çerezleriyle çakışmaz.

## Birim Kullanıcısı

Birim Kullanıcısı yalnızca kendi biriminin kayıtlarına yazar (MIMARI.md, "Birim kapsamı"). Birimler portalda yönetici tarafından atanır; Entra'dan gelmez. Birimi atanmamış Birim Kullanıcısı okuyabilir ama yazamaz.
