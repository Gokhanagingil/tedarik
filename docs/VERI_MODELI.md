# Veri Modeli

Şemanın tek doğruluk kaynağı koddur: her modüldeki `Resource` tanımları. Bu belge neyin neden var olduğunu anlatır.

Ortak kurallar: tamsayı `id`, `code` ve `name` alanları, UTC ISO zaman damgası, İngilizce durum kodları (etiketler arayüzde Türkçe), tüm tablolar `tdr_` önekli.

## İlişkiler

```
org_units ──┐                      supplier_types
            │                            │ (çoktan çoğa)
catalog_items ──┐                        │
                ├── engagements ──── suppliers ──── source_refs (SAP, CRM, dış kaynak kimlikleri)
org_units ──────┘        │               │
(kullanan birimler)      │               ├── supplier_contacts
                         │               ├── contracts
        sla_definitions ─┤               ├── performance_reviews ── review_scores ── review_criteria
        sla_measurements │               ├── performance_events
        responsibilities ┘               ├── supplier_risks ── risk_assessments, risk_actions
                                         └── survey_campaigns ── survey_invitations ── survey_answers
```

## Çekirdek

| Kaynak | Amaç | Önemli alanlar |
| --- | --- | --- |
| `org_units` | İş birimleri (hiyerarşik) | `parent_id`, `manager` |
| `supplier_types` | Filtreleme için tipler; bir tedarikçi birden çok tipe girebilir | `code`, `name` |
| `catalog_items` | Alınan ürün ve hizmetler | `kind`: product, service |
| `suppliers` | Tekil tüzel kişi | `tax_id` (tekil), `status`, `tier`: critical, important, standard; `segment`: strategic, leverage, bottleneck, routine; `owner` (ilişki sahibi) |
| `engagements` | Kim, neyi, kimden, kimin için alıyor | `supplier_id`, `catalog_item_id`, `org_unit_id` (satın alan birim), `beneficiary`: internal, customer; `customer_name`, `business_owner` (hesap veren), `criticality` |
| `engagement_users` | Angajmanı kullanan diğer birimler | çoktan çoğa |
| `responsibilities` | Ek roller ve RACI | tedarikçiye veya angajmana bağlanır; `role`, `raci`, `person` |
| `contracts` | Sözleşme referansı (asıl kayıt SAP/CRM'de) | `source_system`, `external_id`, `end_date`, `notice_days` |
| `source_refs` | Aynı tedarikçinin farklı sistemlerdeki kimlikleri | (`source_system`, `external_id`) tekil |

Temel amaçların karşılığı:

- Tipe göre filtre: `GET /api/tdr/suppliers?type_id=`
- Ürün/hizmet ve kullanan birim raporu: `GET /api/tdr/reports/usage`
- Şirkete mi müşteriye mi: `engagements.beneficiary`
- Sahiplik: `suppliers.owner`, `engagements.business_owner`, `responsibilities`; panoda sahibi olmayan kayıt sayısı

## Performans

| Kaynak | Amaç |
| --- | --- |
| `sla_definitions` | Angajman bazında hedef; `direction` ile yüksek mi düşük mü iyi |
| `sla_measurements` | Dönemlik ölçüm; `met` sunucuda hesaplanır; (SLA, dönem) tekil |
| `review_criteria` | Ağırlıklı değerlendirme kriterleri (yönetici tanımlar) |
| `performance_reviews`, `review_scores` | Dönemlik değerlendirme, kriter başına 1-5 puan |
| `performance_events` | Olay günlüğü: SLA ihlali, olay, gecikme, eskalasyon, takdir |

## Anket

`survey_templates` → `survey_questions` (1-5 ölçek, NPS 0-10, evet/hayır, metin) → `survey_campaigns` (tedarikçi veya angajman için, draft → open → closed) → `survey_invitations` (iç kullanıcı) → `survey_answers`. Sonuç: yanıt oranı, soru ortalamaları, 0-100 memnuniyet.

## Risk

| Kaynak | Amaç |
| --- | --- |
| `supplier_risks` | Risk kaydı; `category`, `owner`, `appetite` (1-25), `strategy`, `review_due`, `control_risk_ref` (KS GRC risk kaydına bağlantı) |
| `risk_assessments` | Değiştirilemez değerlendirme geçmişi: olasılık × etki, azaltıcı katkı, artık skor, gerekçe, kim yaptı |
| `risk_actions` | İşleme faaliyeti: sahip, hedef tarih, durum |

Hesap KS GRC ile aynıdır: içsel = olasılık × etki; katkı düşük %20, orta %40, yüksek %60, kısmen etkili önlem yarısı, toplam en çok %100; artık = içsel × (1 − katkı). Kabul ve kapanış güncel değerlendirme ve gerekçe ister. İştah üstü kabulü, değerlendirmeyi yapandan farklı bir yönetici onaylar.

## İş akışı ve kaynak bulma (kapalı modüller)

| Kaynak | Amaç |
| --- | --- |
| `workflow_definitions` | Sürüm numaralı süreç tanımı (durumlar, geçişler, korumalar) |
| `workflow_instances`, `workflow_history` | Çalışan süreç ve değiştirilemez geçmişi |
| `policies` | Kural parametreleri, örneğin `sourcing.min_quotes = 3` |
| `needs` | İş ihtiyacı |
| `need_candidates` | Aday tedarikçiler; `origin`: existing, new; `selected` |
| `quotes` | Teklifler |

Varsayılan akış: Taslak → Aday İnceleme → (mevcut tedarikçi seçildiyse) Onay, değilse Teklif Toplama → (en az N teklif) Değerlendirme → (kazanan seçildi) Onay → Tamamlandı.

## Destek tabloları

`audit_log` (denetim izi), `idempotency` (tekrar koruması), `import_batches` ve `import_rows` (aktarım geçmişi).
