"""Türkçe alan ve seçim etiketleri: arayüz formları, liste başlıkları, Excel sayfa ve sütun başlıkları buradan gelir
(KS GRC `grc_plus.FIELD_LABELS` ve `CHOICES` karşılığı). Kod tanımlayıcıları İngilizce kalır.

`tests/test_aktarim.py` her kaynağın her alanının ve her seçim değerinin etiketli olduğunu denetler.
"""

FIELDS = {
    "id": "Kayıt No", "code": "Kod", "name": "Ad", "title": "Başlık", "description": "Açıklama",
    "active": "Aktif", "created_at": "Oluşturulma", "updated_at": "Güncellenme", "created_by": "Oluşturan",
    "status": "Durum", "owner": "Sahip", "note": "Not", "comment": "Yorum", "position": "Sıra",
    "kind": "Tür", "category": "Kategori", "version": "Sürüm", "weight": "Ağırlık", "score": "Puan",
    # çekirdek
    "parent_id": "Üst birim", "manager": "Yönetici", "tax_id": "Vergi kimlik no (VKN)", "country": "Ülke",
    "city": "Şehir", "website": "Web sitesi", "tier": "Kritiklik seviyesi", "segment": "Segment",
    "supplier_id": "Tedarikçi", "type_id": "Tedarikçi tipi", "email": "E-posta", "phone": "Telefon",
    "role": "Rol", "is_primary": "Birincil kişi", "source_system": "Kaynak sistem", "external_id": "Harici kimlik",
    "external_name": "Kaynak sistemdeki ad", "last_seen_at": "Son görülme", "catalog_item_id": "Ürün / hizmet",
    "org_unit_id": "Birim", "beneficiary": "Faydalanan", "customer_name": "Müşteri adı",
    "business_owner": "İş sahibi (hesap veren)", "criticality": "Kritiklik", "start_date": "Başlangıç tarihi",
    "end_date": "Bitiş tarihi", "engagement_id": "Angajman", "raci": "RACI", "person": "Kişi",
    "notice_days": "Fesih ihbar süresi (gün)",
    # performans
    "unit": "Birim (ölçü)", "target_value": "Hedef değer", "direction": "Yön", "period": "Dönem",
    "sla_id": "SLA", "period_start": "Dönem başlangıcı", "period_end": "Dönem bitişi",
    "actual_value": "Gerçekleşen değer", "met": "Hedef tuttu", "source": "Kaynak", "recorded_by": "Kaydeden",
    "recorded_at": "Kayıt zamanı", "reviewer": "Değerlendiren", "review_id": "Değerlendirme",
    "criterion_id": "Kriter", "event_type": "Olay türü", "severity": "Önem", "occurred_at": "Olay zamanı",
    "reference": "Referans",
    # risk
    "cause": "Neden", "risk_event": "Risk olayı", "consequence": "İş etkisi", "likelihood": "Olasılık (1–5)",
    "impact": "Etki (1–5)", "appetite": "Risk iştahı eşiği (1–25)", "response_strategy": "Yanıt stratejisi",
    "treatment": "Risk işleme planı", "review_date": "Gözden geçirme tarihi",
    "control_risk_ref": "KS GRC risk kodu", "risk_id": "Risk", "assessed_at": "Değerlendirme zamanı",
    "assessor": "Değerlendiren", "rationale": "Gerekçe", "inherent": "İçsel risk", "mitigation_pct": "Azaltım (%)",
    "residual": "Artık risk", "snapshot": "Anlık görüntü", "assessment_id": "Değerlendirme",
    "from_status": "Önceki durum", "to_status": "Yeni durum", "actor": "Karar veren", "actor_role": "Rolü",
    "decided_at": "Karar zamanı", "exception_rationale": "İştah istisnası gerekçesi", "due_date": "Hedef tarih",
    "priority": "Öncelik", "resolution": "Çözüm", "closed_at": "Kapanış zamanı",
    # anket
    "template_id": "Şablon", "text": "Soru", "required": "Zorunlu", "campaign_id": "Kampanya",
    "respondent": "Yanıtlayan", "answered_at": "Yanıt zamanı", "invitation_id": "Davet", "question_id": "Soru",
    "text_value": "Metin yanıt", "opened_at": "Açılış zamanı", "target_id": "Değerlendirilen",
    "purpose": "Amaç", "intro": "Giriş metni", "outro": "Kapanış metni", "section_id": "Bölüm", "help": "Yardım metni",
    "options_json": "Seçenekler", "show_if_json": "Gösterim koşulu", "risk_category": "Risk kategorisi",
    "risk_threshold": "Risk eşiği (0–100)", "subject": "Değerlendirilen", "audience": "Katılım",
    "anonymous": "Anonim", "min_responses": "Sonuç için en az yanıt", "opens_on": "Açılış tarihi",
    "closes_on": "Kapanış tarihi", "salt": "Anonimlik anahtarı", "response_id": "Yanıt",
    "respondent_key": "Yanıtlayan anahtarı", "started_at": "Başlangıç", "submitted_at": "Gönderim zamanı",
    "value_number": "Sayısal yanıt", "disabled": "Kaldırıldı", "value_text": "Metin yanıt", "values_json": "Seçilenler", "origin_ref": "Kaynak (anket sinyali)",
    "survey_templates.parent_id": "Önceki sürüm", "survey_targets.supplier_id": "Tedarikçi",
    # aktarım ve iz
    "filename": "Dosya adı", "summary_json": "Özet", "batch_id": "Aktarım", "row_no": "Satır",
    "payload_json": "Satır verisi", "action": "İşlem", "message": "Mesaj", "occurred_at_log": "Zaman",
    "auth_type": "Kimlik türü", "method": "İşlem", "object_type": "Kayıt türü", "object_id": "Kayıt no",
    "changes_json": "Değişiklik", "idem_key": "İşlem anahtarı", "route": "Yol", "body_hash": "İçerik özeti",
    "response_json": "Yanıt",
    # kimlik
    "user_id": "Kullanıcı", "assigned_by": "Atayan", "assigned_at": "Atama zamanı",
    # iş akışı ve kaynak bulma
    "definition_json": "Tanım (JSON)", "definition_id": "Tanım", "subject_type": "Konu türü",
    "subject_id": "Konu", "state": "Aşama", "started_by": "Başlatan", "instance_id": "Süreç",
    "from_state": "Önceki aşama", "to_state": "Yeni aşama", "at": "Zaman", "value_json": "Değer (JSON)",
    "requester": "Talep eden", "needed_by": "İhtiyaç tarihi", "workflow_instance_id": "Süreç",
    "need_id": "İhtiyaç", "origin": "Kaynak", "selected": "Seçildi", "amount": "Tutar", "currency": "Para birimi",
    "received_at": "Alınma tarihi", "valid_until": "Geçerlilik sonu", "document_ref": "Belge referansı",
}

# Seçim etiketleri: önce kaynağa özgü (kaynak.alan), yoksa alan adına göre ortak.
CHOICES = {
    "status": {"active": "Aktif", "prospect": "Aday", "suspended": "Askıda", "offboarding": "Çıkış sürecinde",
               "terminated": "Sona erdi", "planned": "Planlandı", "ending": "Sona eriyor", "ended": "Sona erdi",
               "draft": "Taslak", "expiring": "Süresi doluyor", "expired": "Süresi doldu", "open": "Açık",
               "in_treatment": "Aksiyon alınıyor", "accepted": "Kabul edildi", "closed": "Kapalı",
               "in_progress": "Üzerinde çalışılıyor", "validation": "Etkinlik doğrulaması",
               "completed": "Tamamlandı", "cancelled": "İptal", "pending": "Bekliyor", "answered": "Yanıtlandı",
               "published": "Yayında", "retired": "Kullanımdan kalktı", "submitted": "Gönderildi"},
    "tier": {"critical": "Kritik", "important": "Önemli", "standard": "Standart"},
    "segment": {"strategic": "Stratejik", "leverage": "Kaldıraç", "bottleneck": "Darboğaz", "routine": "Rutin"},
    "source_system": {"sap": "SAP", "crm": "CRM (Dynamics)", "outsourcing": "Dış kaynak yönetimi",
                      "servicenow": "ServiceNow", "manual": "Elle"},
    "beneficiary": {"internal": "Şirket içi", "customer": "Müşteri"},
    "criticality": {"critical": "Kritik", "high": "Yüksek", "medium": "Orta", "low": "Düşük"},
    "severity": {"critical": "Kritik", "high": "Yüksek", "medium": "Orta", "low": "Düşük"},
    "priority": {"critical": "Kritik", "high": "Yüksek", "medium": "Orta", "low": "Düşük"},
    "raci": {"R": "Sorumlu (R)", "A": "Hesap veren (A)", "C": "Danışılan (C)", "I": "Bilgilendirilen (I)"},
    "role": {"relationship_owner": "İlişki sahibi", "contract_owner": "Sözleşme sahibi",
             "service_owner": "Hizmet sahibi", "technical_owner": "Teknik sahip", "security": "Bilgi güvenliği",
             "finance": "Finans", "legal": "Hukuk", "other": "Diğer", "ADMIN": "Yönetici",
             "SUPPLIER_MANAGER": "Tedarikçi Yöneticisi", "UNIT_USER": "Birim Kullanıcısı", "AUDITOR": "Denetçi",
             "VIEWER": "Görüntüleyici"},
    "kind": {"product": "Ürün", "service": "Hizmet"},
    "unit": {"percent": "Yüzde", "hours": "Saat", "minutes": "Dakika", "count": "Adet"},
    "direction": {"higher_better": "Yüksek daha iyi", "lower_better": "Düşük daha iyi"},
    "period": {"monthly": "Aylık", "quarterly": "Üç aylık", "yearly": "Yıllık"},
    "source": {"manual": "Elle", "import": "İçe aktarım", "mcp": "MCP"},
    "event_type": {"sla_breach": "SLA ihlali", "incident": "Olay / kesinti", "delivery_delay": "Teslim gecikmesi",
                   "escalation": "Eskalasyon", "praise": "Takdir", "other": "Diğer"},
    "category": {"continuity": "Süreklilik", "security": "Bilgi güvenliği", "compliance": "Uyum",
                 "financial": "Finansal", "concentration": "Yoğunlaşma (bağımlılık)", "performance": "Performans",
                 "privacy": "Kişisel veri", "reputation": "İtibar", "exit": "Çıkış"},
    "response_strategy": {"mitigate": "Azalt", "avoid": "Kaçın", "transfer": "Devret / paylaş", "accept": "Kabul et"},
    "origin": {"existing": "Mevcut tedarikçi", "new": "Yeni tedarikçi"},
    "purpose": {"satisfaction": "Memnuniyet", "risk": "Risk değerlendirme", "general": "Genel (bağımsız)"},
    "subject": {"none": "Yok (bağımsız anket)", "supplier": "Tedarikçi", "engagement": "Angajman"},
    "audience": {"invited": "Yalnızca davetliler", "all": "Tüm kullanıcılar"},
    "survey_questions.kind": {"scale_1_5": "1–5 ölçek", "nps_0_10": "Tavsiye (0–10)", "yes_no": "Evet / Hayır",
                              "single_choice": "Tek seçim", "multi_choice": "Çoklu seçim", "text": "Metin",
                              "number": "Sayı", "date": "Tarih"},
}


CHOICES["risk_category"] = CHOICES["category"]


def field(name, resource=None):
    return FIELDS.get(f"{resource}.{name}") or FIELDS.get(name) or name.replace("_", " ").capitalize()


def choice(resource, name, value):
    table = CHOICES.get(f"{resource}.{name}") or CHOICES.get(name) or {}
    return table.get(value, value)
