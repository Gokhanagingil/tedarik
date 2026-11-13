# Kopya dosyalardaki yamalar

Kaynak: `Gokhanagingil/control@7720f4b095a067dbf810dbc1cd25937d88a2ee5f`. Her dosyanın ilk satırı kaynak commit'i gösterir; geri kalanı kaynakla karşılaştırılabilir:

```
diff <(tail -n +2 tedarik/vendor/identity.py) ../control/identity.py      # fark yok
diff <(tail -n +2 tedarik/vendor/entra_auth.py) ../control/entra_auth.py  # yalnızca aşağıdaki 3 satır
```

`tests/test_kimlik.py` bu iki karşılaştırmayı `../control` klasörü varsa otomatik yapar.

## xlsx_io.py

Yama yok. `tedarik/modules/transfer.py` yalnızca `read_xlsx` ve `make_xlsx` işlevlerini çağırır; sınırlar (12 MB, 5.000 satır, 60 sütun, formül ve makro reddi) KS GRC ile aynıdır.

## identity.py

Yama yok. Uyarlama `tedarik/session.py` içinde, modül değişkenleriyle yapılır:

- `COOKIE_NAME = "tedarik_session"`, `ENTERPRISE_COOKIE = "__Host-tdr_session"`: aynı alan adında KS GRC oturum çerezini ezmemek için.
- KS GRC adını taşıyan HTML sayfaları (`LOGIN_HTML`, `CHANGE_HTML`, `ENTRA_*`) kullanılmaz; tedarik kendi sayfalarını sunar.
- `identity.setup()` çağrılmaz; aynı tablolar `tedarik/migrate.py` içinde iki motor için açılır (K-013).

## entra_auth.py (K-012)

Kabul edilen uygulama rolleri modül değişkenine taşındı; varsayılan değer KS GRC davranışıyla aynıdır.

| Satır | KS GRC | Tedarik |
| --- | --- | --- |
| rol sabitlerinden sonra | yok | `ROLES = (ADMIN, AUDITOR)` |
| `verify`: rol denetimi | `not (ADMIN in roles or AUDITOR in roles)` | `not any(r in roles for r in ROLES)` |
| `verify`: dönen rol | `ADMIN if ADMIN in roles else AUDITOR` | `next(r for r in ROLES if r in roles)` |

Sarmalayıcı (`tedarik/session.py`) `ROLES` değerini tedarik rolleriyle (`KS.TDR.*`) ve `FLOW_COOKIE` değerini `__Host-tdr_flow` ile değiştirir; `configure()` için `TEDARIK_*` adlarını `CONTROL_*` adlarına çevirir. Yama KS GRC'ye geriye uyumlu öneri olarak verilmiştir (UYUM_SOZLESMESI.md, "KS GRC'ye öneriler" 1). KS GRC alırsa yama kalkar.
