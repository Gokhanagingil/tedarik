# MCP Uygulaması için API Sözleşmesi

KS GRC `docs/MCP_CONTRACT_AND_ACCEPTANCE.md` ile aynı model (K-008): portal kaynak sistemlere bağlanmaz; mevcut MCP uygulaması ServiceNow ve Dynamics'i sorgular, sonucu bu dar REST API'ye yazar. Portal ayrıca KS GRC otomatik kontrolleri için kanıt kaynağıdır.

## Kimlik

HTTPS üzerinden `X-API-Key: <TEDARIK_API_KEY>` (en az 32 karakter; sunucuda `/opt/tedarik/secrets/mcp_api_key`). Anahtarı günlüğe, adrese veya tarayıcı koduna koymayın. Makine kimliği bir rol değildir; yalnızca aşağıdaki işlemleri yapar. Diğer her şey 403'tür: kullanıcı yönetimi, dışa aktarım, içe aktarım, ana veri değişikliği, anket sonuçları, denetim izi.

| Kaynak (`/api/tdr/...`) | Okuma | Yazma |
| --- | --- | --- |
| `org_units`, `supplier_types`, `catalog_items`, `suppliers`, `source_refs`, `engagements`, `contracts`, `sla_definitions`, `supplier_risks`, `risk_assessments` | Evet | Hayır |
| `sla_measurements` | Evet | Evet, yalnızca `"source": "mcp"` |
| `performance_events` | Evet | Evet, yalnızca `"source": "mcp"` |
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
