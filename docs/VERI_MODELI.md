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

## Anket motoru

Üç kullanım tek motordan: tedarikçi memnuniyeti, tedarikçi risk değerlendirmesi, tedarikçiden bağımsız (genel) anketler.

| Kaynak | Amaç |
| --- | --- |
| `survey_templates` | Şablon: `purpose` (satisfaction, risk, general), giriş ve kapanış metni, `status` (draft, published, retired), `version`, `parent_id` (önceki sürüm). Yayımlanınca donar; değişiklik `POST .../copy` ile yeni sürümde |
| `survey_sections` | Bölümler (sıra, başlık, açıklama) |
| `survey_questions` | Soru: `kind` (scale_1_5, nps_0_10, yes_no, single_choice, multi_choice, text, number, date), `code` (S1, S2…), `required`, `weight`, `options_json` (`[{value, label, score}]`), `show_if_json` (`{"question": "S2", "equals" \| "in" \| "min" \| "max": ...}`), `risk_category`, `risk_threshold` (0–100) |
| `survey_campaigns` | Uygulama: `subject` (none = bağımsız, supplier, engagement), `audience` (invited, all), `anonymous`, `min_responses`, dönem, açılış ve kapanış tarihi, sahip, `status` (draft, open, closed) |
| `survey_targets` | Değerlendirilen tedarikçi veya angajman; toplu ekleme (`{"tier": "critical"}` dahil) |
| `survey_invitations` | Kişi × hedef daveti; `pending`, `answered` |
| `survey_responses` | Yanıt: taslak veya gönderildi, 0–100 puan. Anonimde kişi ve davet bağlantısı tutulmaz; kişi anahtarı kampanyaya özgü tuzla özetlenir |
| `survey_answers` | Soru yanıtı ve 0–100 puanı |

Puan: 1–5 ölçek (v−1)×25, tavsiye v×10, seçimler seçenek puanıyla (olumsuz soruda "Evet" düşük puan alabilir), çoklu seçimde ortalama; yanıt puanı ağırlıklı ortalama. Sonuç: yanıt oranı, genel ve bölüm puanı, soru bazında dağılım, ortalama, NPS, metin yanıtları, tedarikçi bazında puan ve risk sinyali (risk kategorili sorunun hedef ortalaması eşiğin altında). Sinyalden `POST .../risk-signals` ile tedarikçi riski açılır; `supplier_risks.origin_ref` aynı sinyalin ikinci kez risk açmasını önler. Anonim kampanyada yanıt sayısı `min_responses` altındaysa ayrıntı gösterilmez. Başlangıçta iki örnek şablon taslak olarak gelir: "Tedarikçi Memnuniyet Anketi" ve "Tedarikçi Risk Değerlendirme Anketi".

## Risk

Model ve kurallar KS GRC ile aynıdır (ayrıntı: `UYUM_SOZLESMESI.md`).

| Kaynak | Amaç |
| --- | --- |
| `supplier_risks` | Risk kaydı: tedarikçi ve isteğe bağlı angajman; risk ifadesi `cause`, `risk_event`, `consequence`; `likelihood`, `impact` (1-5), `appetite` (1-25), `owner`, `status` (open, in_treatment, accepted, closed), `response_strategy` (mitigate, avoid, transfer, accept), `treatment`, `review_date`, `control_risk_ref` (KS GRC `risks.code`) |
| `risk_assessments` | Değiştirilemez değerlendirme: `assessor`, `rationale`, `inherent`, `mitigation_pct`, `residual`, o anki `appetite` ve riskin anlık görüntüsü (`snapshot`, azaltıcı önlemler dahil) |
| `risk_decisions` | Değiştirilemez karar: kabul, kapanış, yeniden açma; kim, hangi rolle, hangi değerlendirmeye dayanarak, gerekçe ve iştah istisnası gerekçesi |
| `risk_actions` | İşleme faaliyeti: `code`, sahip, hedef tarih, öncelik, durum (open, in_progress, validation, completed, cancelled), çözüm, kapanış zamanı |

Hesap: içsel = olasılık × etki; katkı düşük %20, orta %40, yüksek %60, kısmen etkili önlem yarısı, toplam en çok %100; artık = içsel × (1 − katkı). Kabul ve kapanış `PATCH /api/tdr/supplier_risks/{id}` ile `assessment_id` (güncel değerlendirme) ve `decision_rationale` ister; değerlendirmeden sonra risk veya iştah değiştiyse yeniden değerlendirme gerekir. İştah üstü kabulü, değerlendirmeyi yapandan farklı bir Yönetici `exception_rationale` ile onaylar. Kabul edilmiş veya kapalı risk yalnızca gerekçeyle yeniden açılır ve yeni değerlendirme ister. Açık faaliyeti olan risk kapatılamaz.

## Uyum (GRC) — K-015

| Tablo | Amaç | Not |
| --- | --- | --- |
| `tdr_standards`, `tdr_clauses` | Standart ve maddeler (hiyerarşik) | `applicable` + `justification`: uygulanabilirlik bildirimi |
| `tdr_processes`, `tdr_objectives`, `tdr_documents` | Süreç, kontrol hedefi, politika/prosedür | Yürürlükteki doküman onay ister |
| `tdr_controls` | Kontrol kütüphanesi | `automation`: iç otomatik kural anahtarı |
| `tdr_control_{clauses,processes,objectives,risks,documents}` | Kontrol eşlemeleri | Küme olarak değişir (`POST /controls/{id}/links`) |
| `tdr_audits`, `tdr_audit_standards`, `tdr_audit_clauses`, `tdr_audit_processes` | Denetim ve kapsamı (standart, madde, süreç) | `revision` ile eşzamanlı düzenleme koruması |
| `tdr_audit_plan` | Tamamlanınca dondurulan plan | Değiştirilemez |
| `tdr_evidence`, `tdr_evidence_files`, `tdr_evidence_blobs` | Kanıt ve sürümleri | Dosya sürümleri ve içerik değiştirilemez; SHA-256 |
| `tdr_evidence_{controls,audits,clauses}` | Kanıt bağlantıları | |
| `tdr_executions`, `tdr_execution_evidence` | Kontrol çalışmaları | Değiştirilemez; tanım ve kaynak bilgisi JSON olarak dondurulur |
| `tdr_findings`, `tdr_grc_actions` | Bulgu ve düzeltici faaliyet (DÖF) | Doğrulama aşaması, görevler ayrılığı |
| `tdr_risk_catalog` | Risk senaryoları (risks modülü) | Risk kaydı `catalog_id` taşır |

`tdr_supplier_risks` tek risk kaydıdır: `supplier_id` isteğe bağlı, tedarikçisiz riskte `entity_name` zorunlu (göç 1).

## GRC platformu (K-016 – K-020)

Kayıt kodları sunucuda üretilir (`Resource(code_prefix=...)`, `tdr_sequences`, K-017): SRK şirket, BRM birim, SRC süreç,
TED tedarikçi, ANG angajman, SOZ sözleşme, RSK risk, RIF risk faaliyeti, KRI gösterge, RDD-yıl risk dönemi, RIS iştah,
KHD kontrol hedefi, KTL kontrol, DNT-yıl denetim, KNT-yıl kanıt, BLG-yıl bulgu, DOF-yıl DÖF, DOK doküman, CI konfigürasyon
öğesi, BIA iş etki analizi, BSP süreklilik planı, TAT-yıl tatbikat. Standart referansı, madde no ve politika kodu doğal
tanımlayıcıdır, elle girilir.

```
companies (kendi şirketimiz / müşteri, hiyerarşik)
   │
   ├── supplier_risks ── risk_assessments (değişmez, cycle_id) ── risk_decisions (değişmez)
   │      │   ├── risk_actions        ├── kris ── kri_values (değişmez)
   │      │   ├── risk_cis ── cmdb_cis ── cmdb_relations, ci_exposures (kural maruziyeti)
   │      │   ├── control_risks ── controls ── control_{clauses,processes,objectives,documents}
   │      │   └── objective_risks ── objectives ── processes
   │      └── process_id ── processes (yönetim / ana / destek, hiyerarşik)
   ├── risk_cycles (dönemsel değerlendirme), risk_appetites (kategori iştahı/toleransı), risk_criteria (ölçekler)
   ├── bias ── bia_impacts (kategori × süre), bia_applications ── cmdb_cis, bia_suppliers, bia_risks
   │     └── bc_plan_bias ── bc_plans ── bc_plan_steps, bc_plan_applications, bc_exercises ── bc_exercise_findings ── findings
   ├── cmdb_cis (ServiceNow'dan senkron veya MCP ile itilir)
   └── findings (kaynak: denetim, kontrol testi, tatbikat, ...; clause_id, process_id, risk_id)
documents ── document_revisions (değişmez), document_files + document_blobs (değişmez, SHA-256), document_clauses
```

| Kaynak | Amaç | Önemli alanlar |
| --- | --- | --- |
| `companies` | Riskin, BİA'nın, planın, CI'ın ait olduğu şirket | `kind`: own, customer; `parent_id`; `servicenow_ref` (CMDB eşlemesi) |
| `processes` | ISO 9001 süreç haritası | `process_type`: management, core, support; `parent_id`, `position`, `inputs`, `outputs`, `owner` |
| `supplier_risks` | Kurumsal risk kaydı (ISO 31000) | `company_id` (zorunlu; seçilmezse `core.default_company`), `process_id`, `org_unit_id`, `risk_type`: threat/opportunity, `source`, `impact_area`, `target_likelihood/impact`, `consulted`; özet: `inherent_score`, `residual_score`, `risk_level`, `last_assessed_at` |
| `risk_criteria`, `risk_appetites`, `risk_cycles` | Risk kriterleri, kategori iştahı ve toleransı, değerlendirme dönemleri | Dönem ilerlemesi dönem içindeki değerlendirmelerden hesaplanır |
| `kris`, `kri_values` | Anahtar risk göstergeleri ve ölçümleri | Durum eşiklerle sunucuda hesaplanır; MCP ölçüm yazar |
| `cmdb_cis`, `cmdb_relations`, `cmdb_sync_runs` | Konfigürasyon öğeleri, bağımlılıklar, değişmez senkron kayıtları | Kaynaktan gelen alanlar senkronla güncellenir; `company_id`, `supplier_id`, `description` yereldir |
| `ci_exposures`, `risk_cis` | Kural maruziyetleri (os_eos, app_eos, patch, uptime) ve riskten etkilenen CI'lar | Kural riskleri (rule × şirket) `origin_ref = cmdb:{kural}:{şirket}` ile tekildir |
| `bias`, `bia_impacts`, `bia_applications`, `bia_suppliers`, `bia_risks` | İş etki analizi (ISO 22301 8.2.2) | MTPD ve kritiklik etki matrisinden; RTO ≤ MTPD; onay dört göz |
| `bc_plans`, `bc_plan_steps`, `bc_plan_applications`, `bc_plan_bias` | Süreklilik ve felaket kurtarma planları (8.4) | Onaylı plan değişmez, revizyonla sürüm artar |
| `bc_exercises`, `bc_exercise_findings` | Tatbikatlar (8.5) | Tamamlanınca sonuç ve alınan dersler zorunlu; hedef aşıldıysa "başarılı" olamaz |
| `documents`, `document_revisions`, `document_files`, `document_clauses` | Dokümante edilmiş bilgi (ISO 9001 7.5) | taslak → onayda → yayımlandı → geçersiz; her yayın değişmez bir revizyon |

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

`audit_log` (denetim izi; KS GRC `activity_log` ile aynı sütun adları), `idempotency` (tekrar koruması), `import_batches` ve `import_rows` (aktarım geçmişi).
