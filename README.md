# Tedarik

Tedarikçi yönetimi portalı: tedarikçiler, alınan ürün ve hizmetler, kullanan birimler, sahiplikler, performans, memnuniyet anketleri ve riskler tek yerde. Türkçe. Python 3.12 ve SQLite; ek paket gerektirmez. KS GRC ile aynı yığın ve kurallar.

Durum ve sıradaki adımlar: [DURUM.md](DURUM.md) · Mimari: [docs/MIMARI.md](docs/MIMARI.md)

## Yerel başlangıç

```
export TEDARIK_AUTH_MODE=dev
python app.py
```

Tarayıcı: `http://127.0.0.1:8090`. `dev` modu yalnızca yerel adreste çalışır; ağa açık çalıştırma için oturum sağlayıcısının eklenmesi gerekir (DURUM.md, adım 2). `TEDARIK_AUTH_MODE` verilmezse uygulama başlamaz; anonim erişim yoktur.

## Örnek

```
curl -X POST http://127.0.0.1:8090/api/tdr/suppliers \
  -H 'Content-Type: application/json' -d '{"code":"S1","name":"Örnek Bilişim A.Ş.","tier":"critical"}'
curl 'http://127.0.0.1:8090/api/tdr/suppliers?tier=critical'
curl http://127.0.0.1:8090/api/tdr/dashboard/summary
```

## Testler

```
python -m unittest discover -s tests -v
```

## Yapılandırma

| Değişken | Anlamı | Varsayılan |
| --- | --- | --- |
| `TEDARIK_AUTH_MODE` | `dev`, `local`, `entra` | yok (zorunlu) |
| `TEDARIK_DB` | SQLite dosyası | `tedarik.db` |
| `TEDARIK_HOST`, `PORT` | Dinlenen adres | `127.0.0.1`, `8090` |
| `TEDARIK_MODULES` | Etkin modüller | `core,performance,surveys,risks,transfer,dashboard` |
| `TEDARIK_API_KEY` veya `TEDARIK_API_KEY_FILE` | MCP anahtarı (en az 32 karakter) | yok |
| `TEDARIK_COOKIE_SECURE` | HTTPS arkasında `1` | `0` |
| `TEDARIK_DEV_USER`, `TEDARIK_DEV_ROLE` | Yerel geliştirmede kullanıcı ve rol | `dev`, `ADMIN` |
