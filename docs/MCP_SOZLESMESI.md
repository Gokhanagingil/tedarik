# MCP Uygulaması için API Sözleşmesi

KS GRC `docs/MCP_CONTRACT_AND_ACCEPTANCE.md` ile aynı model (K-008): portal kaynak sistemlere bağlanmaz; mevcut MCP uygulaması ServiceNow ve Dynamics'i sorgular, sonucu bu dar REST API'ye yazar. Portal ayrıca KS GRC otomatik kontrolleri için kanıt kaynağıdır.

## Kimlik

HTTPS üzerinden `X-API-Key: <TEDARIK_API_KEY>` (en az 32 karakter; sunucuda `/opt/tedarik/secrets/mcp_api_key`). Anahtarı günlüğe, adrese veya tarayıcı koduna koymayın. Makine kimliği bir rol değildir; yalnızca aşağıdaki işlemleri yapar. Diğer her şey 403'tür: kullanıcı yönetimi, dışa aktarım, içe aktarım, ana veri değişikliği, anket sonuçları, denetim izi.

| Kaynak (`/api/tdr/...`) | Okuma | Yazma |
| --- | --- | --- |
| `org_units`, `supplier_types`, `catalog_items`, `suppliers`, `source_refs`, `engagements`, `contracts`, `sla_definitions`, `supplier_risks`, `risk_assessments` | Evet | Hayır |
| `sla_measurements` | Evet | Evet, yalnızca `"source": "mcp"` |
| `controls`, `executions`, `evidence` (GRC) | Evet | `executions`: yalnızca otomatik kontrole `"source": "mcp"`; `evidence/upload` |
| `performance_events` | Evet | Evet, yalnızca `"source": "mcp"` |
| `cmdb_cis`, `cmdb_relations`, `ci_exposures`, `risk_cis`, `companies` | Evet | `POST /api/tdr/cmdb/cis/bulk` (CMDB itmesi, Akış 5) |
| `kris`, `kri_values` | Evet | `kri_values`: kaynak otomatik `"mcp"` olur (Akış 6) |
| `/api/health` | 200 | — |
| `/api/tdr/schedule` (takvim: geciken değerlendirme, anket ve risk gözden geçirmeleri) | Evet | — |

Listeler süzülebilir (`?supplier_id=3`, `?status=active`, `?end_date__lte=2026-12-31`, `?order=-id`, `?limit=1000&offset=0`).

## Akış 1: SLA ölçümü yazma (kaynak: ServiceNow)

1. `GET /api/tdr/sla_definitions?active=1`: ölçülecek SLA'lar, hedef, yön (`higher_better` / `lower_better`), dönem.
2. Kaynak sistemde dönemin değerini hesaplayın. Eksik veya hatalı veri toplama ölçüm değildir; yazmayın, insan incelemesine aktarın.
3. `POST /api/tdr/sla_measurements`:

```json
{"sla_id": 4, "period_start": "2026-10-01", "actual_value": 99.62, "source": "mcp",
 "note": "approved-query:availability:v2", "idempotency_key": "mcp-sla-4-2026-10"}
```

   `met` (hedef tuttu mu) sunucuda hesaplanır. (SLA, dönem) tekildir; aynı dönem ikinci kez 409 döner.
4. Yeniden deneme: aynı `idempotency_key` ve aynı içerik 200 + `"replayed": true` döner; farklı içerik 409. Anahtar biçimi `[A-Za-z0-9_.:-]{8,160}` (KS GRC ile aynı).

## Akış 2: Performans olayı yazma

`POST /api/tdr/performance_events`:

```json
{"supplier_id": 3, "engagement_id": 7, "event_type": "sla_breach", "severity": "high",
 "occurred_at": "2026-11-02T14:05:00+03:00", "description": "P1 olay hedef sürede çözülmedi",
 "reference": "INC0012345", "source": "mcp", "idempotency_key": "mcp-event-INC0012345"}
```

`event_type`: `sla_breach`, `incident`, `delivery_delay`, `escalation`, `praise`, `other`. Zaman saat dilimli ISO 8601 olmalı; UTC'ye çevrilerek saklanır.

## Akış 3: Tedarikçi eşleme (okuma)

Kaynak sistem kimliğiyle portal tedarikçisini bulmak için `GET /api/tdr/source_refs?source_system=servicenow&external_id=<kimlik>` → `supplier_id`. Yeni tedarikçiyi MCP açmaz; ana veri Excel aktarımı veya Tedarikçi Yöneticisi ile girilir (K-007).

## Akış 4: Otomatik kontrol sonucu yazma (GRC modülü, K-015)

KS GRC `POST /api/executions` ile aynı alanlar: `POST /api/tdr/executions`

```json
{"control_id": 12, "status": "fail", "source": "mcp", "details": "1.246 sunucudan 5'i CMDB'de yok",
 "executed_at": "2026-11-15T06:00:00Z", "sample_size": 1246, "exceptions": 5, "severity": "high",
 "provenance": {"collection_status": "complete", "query": "approved-query:cmdb:v1", "reference": "sys_id: ..."},
 "evidence_ids": [7], "idempotency_key": "mcp-ctl-12-2026-11-15"}
```

- Yalnızca `execution_mode=automatic` kontrole ve yalnızca `"source": "mcp"` ile yazılır; aksi 403.
- `collection_status` `partial` veya `error` ise sonuç yalnızca `inconclusive` olabilir. Zaman saat dilimli olmalı ve gelecekte olmamalı.
- Başarısız sonuç bulgu açar; aynı kontrolde açık MCP bulgusu varsa yeni bulgu açılmaz, tekrar sayısı artar.
- Kanıt yükleme: `POST /api/tdr/evidence/upload` (`title`, `file_name`, `content_base64`, `controls: [id]`); kaynak "mcp" olarak işaretlenir. MCP anahtarı kanıt dosyası indiremez.
- Okuma: `GET /api/tdr/controls?execution_mode=automatic&active=1`, `GET /api/tdr/executions?control_id=`.

Portal kendi verisi üzerindeki kontrolleri ayrıca iç kuralla çalıştırır (`POST /api/tdr/controls/{id}/run`, `POST /api/tdr/grc/run-automatic`; yalnızca kullanıcı oturumu). Aşağıdaki tablo, KS GRC ayrı uygulama olarak kaldığı sürece geçerlidir.

## Akış 5: CMDB itmesi (K-019)

Portal ServiceNow'a doğrudan bağlanabilir (`TEDARIK_SN_INSTANCE`, salt okunur Table API, gece senkronu). Doğrudan bağlantı
kurulamıyorsa MCP aynı veriyi iter. `POST /api/tdr/cmdb/cis/bulk` (en çok 5000 öğe, 20000 ilişki; 8 MB):

```json
{"items": [{"sys_id": "9f3c...", "name": "srv-itsm-db01", "ci_class": "server", "company": "Demo Teknoloji",
            "environment": "production", "operational_status": "operational", "business_criticality": "critical",
            "os": "Oracle Linux", "os_version": "7.9", "os_eos_date": "2024-12-31", "last_patch_date": "2026-10-20",
            "missing_critical_patches": 2, "last_boot_at": "2026-07-01T03:00:00Z", "fqdn": "srv-itsm-db01.ornek"}],
 "relations": [{"parent": "<uygulama sys_id>", "child": "<sunucu sys_id>", "type": "Depends on::Used by", "sys_id": "..."}]}
```

- `sys_id` tekil anahtardır; aynı öğe ikinci kez gelirse güncellenir, değişmeyen sayılır. Öğe başına hata diğerlerini durdurmaz (`errors`).
- `ci_class`: `business_app`, `application`, `server`, `database`, `network`, `cloud`, `other`. `company`, şirketin adı veya `servicenow_ref` değeriyle eşlenir; eşlenmeyen CI'dan risk açılmaz (sağlık kontrolünde görünür).
- Her itme değişmez bir `cmdb_sync_runs` kaydı bırakır ve CI risk kurallarını çalıştırır: destek süresi bitmiş işletim sistemi (`os_eos`) ve uygulama (`app_eos`), eksik veya gecikmiş kritik yama (`patch`, varsayılan 35 gün), uzun süre yeniden başlatılmama (`uptime`, varsayılan 100 gün). Kural ve şirket başına tek kurumsal risk açılır ve etkilenen CI'lar riske bağlanır; eşikler `cmdb.rules` politikasındadır.

## Akış 6: Anahtar risk göstergesi ölçümü

`GET /api/tdr/kris?active=1` → göstergeler, eşikler ve yön. `POST /api/tdr/kri_values`:

```json
{"kri_id": 3, "period": "2026-11-01", "value": 7, "note": "approved-query:patch-age:v1", "idempotency_key": "mcp-kri-3-2026-11"}
```

Durum (yeşil, sarı, kırmızı) eşiklere göre sunucuda hesaplanır; (gösterge, dönem) tekildir; ölçüm değiştirilemez.

## Akış 7: Portal, ServiceNow MCP sunucusuna bağlanır (K-021)

Yukarıdaki akışlarda MCP uygulaması portala yazar. Portal ayrıca bir **MCP istemcisi** olarak ServiceNow'un MCP
sunucusuna bağlanıp CMDB'yi okuyabilir (Streamable HTTP, JSON-RPC 2.0, protokol `2025-06-18`):

1. `POST <TEDARIK_SN_MCP_URL>` `initialize` → sunucunun döndürdüğü `Mcp-Session-Id` sonraki isteklerde gönderilir;
   ardından `notifications/initialized`.
2. `tools/list` (sayfalı): "MCP bağlantısını sına" ekranı araçları ve parametrelerini listeler.
3. `tools/call` ile `cmdb.mcp` politikasındaki araç çağrılır. Varsayılan şablon:

```json
{"tool": "query_table",
 "arguments": {"table_name": "{table}", "query": "{query}", "fields": "{fields}", "limit": "{limit}",
               "offset": "{offset}", "display_value": "all"},
 "records_path": "", "page_size": 200}
```

   `{query}` ServiceNow kodlu sorgusudur (`install_status!=7^sys_updated_on>=…^ORDERBYsys_updated_on`), `{fields}`
   virgüllü alan listesi, `{fields_list}` liste. Araç kayıt listesini `structuredContent` veya JSON metin içeriği olarak
   döndürmelidir (`result`, `records`, `items` anahtarları ya da `records_path` ile). Kayıtlar Table API biçiminde
   (`{"value", "display_value"}`) veya düz değerle olabilir.
4. Kimlik: `Authorization: Bearer` — sabit belirteç (`/opt/tedarik/secrets/sn_mcp_token`) veya OAuth 2.0 istemci kimlik
   bilgisi (`TEDARIK_SN_MCP_TOKEN_URL`, örn. `https://<kurum>.service-now.com/oauth_token.do`, istemci kimliği ve
   `/opt/tedarik/secrets/sn_mcp_client_secret`). 401'de belirteç yenilenir; oturum düşerse (404) bir kez yeniden açılır.
5. Senkron gece görevinde (`python -m tedarik.cmdb_sync`) veya CMDB Panosu'ndan çalışır; her çalıştırma
   `cmdb_sync_runs` kaydında `source = mcp` olarak görünür. Portal MCP üzerinden ServiceNow'a yazmaz.

## KS GRC için kanıt (örnek otomatik kontroller)

KS GRC'deki otomatik kontroller portal API'sini okuyarak `POST /api/executions` ile sonuç yazar (KS GRC sözleşmesi). Önerilen kontroller:

| KS GRC kontrolü | Portal sorgusu | Başarısız sayılacak durum |
| --- | --- | --- |
| Kritik tedarikçiler periyodik değerlendirildi (ISO 27001 A.5.22, ISO 20000 8.3.4) | `GET /api/tdr/schedule` (`summary.review_overdue`, `items[].tier`) | Değerlendirmesi gecikmiş kritik tedarikçi var |
| Kritik tedarikçi riskleri değerlendirildi | `GET /api/tdr/supplier_risks?status=open` + `GET /api/tdr/risk_assessments?risk_id=` | Açık risk için değerlendirme yok veya gözden geçirme tarihi geçti |
| Sözleşme bitişleri izleniyor | `GET /api/tdr/contracts?status=active&end_date__lte=<bugün+90>` | 90 gün içinde biten ve sahibi olmayan sözleşme |
| SLA hedefleri izleniyor | `GET /api/tdr/sla_measurements?met=0` (dönem süzgeciyle) | Ardışık iki dönem hedef tutmadı |

Kanıt olarak sorgu adresi, yanıtın SHA-256 özeti ve kayıt sayısı `provenance` alanına yazılır. Sorgu başarısızsa `collection_status: "error"` ve yalnızca `inconclusive` (KS GRC kuralı).

## Kabul

`tests/test_tedarik.py` (`test_mcp_anahtari_en_az_yetki`, tekrar koruması ve eşzamanlılık testleri) bu sözleşmenin portal tarafını sentetik veriyle sınar. Canlı ServiceNow/Dynamics sorgusu, MCP uygulamasının adaptörü ve kaynak veri kalitesi bu testlerle kabul edilmiş sayılmaz; işletmeci bir SLA'yı uçtan uca çalıştırıp kaynak kayıt → ölçüm → pano bağını karşılaştırmalıdır.
