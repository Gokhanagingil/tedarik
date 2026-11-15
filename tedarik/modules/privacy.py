"""Veri yönetişimi Faz 2 — KVKK ve sınıflandırma (K-029). `datagov` modülünün parçasıdır.

- Kişisel veri keşfi: kolon adı, iş adı, kaynaktaki açıklama ve bağlı terim; kategori sözlüğü (anahtar kelimeler) veri
  yönetişimi ofisince düzenlenir. Örnek değer doğrulaması (TCKN, IBAN, kart, e-posta, telefon, IP) verinin bulunduğu yerde
  çalışır (tarayıcı veya `python -m tedarik.pii`); platforma yalnızca sayılar gelir. Sonuç öneridir; veri yöneticisi
  kabul eder veya reddeder. Kabul edilen kategori kolona işlenir, kolonun gizlilik sınıfı en az politikadaki düzeye çıkar.
- İşleme envanteri (VERBİS): faaliyet, amaç, hukuki sebep (KVKK md. 5; özel nitelikli için md. 6), kategoriler, ilgili kişi
  grupları, alıcılar, yurt dışı aktarım (md. 9), saklama kuralı, tedbirler, aydınlatma metni; kolon ve tablolara bağlı;
  veri işleyen tedarikçiler. Eksikler kural olarak hesaplanır.
- Saklama ve imha: kurallar (süre, başlangıç olayı, yöntem, dayanak); periyodik imha en çok politikadaki ay aralığıyla
  (yönetmelik: 6 ay), tamamlanan imha kaydı değiştirilemez.
- Veri varlığı risk puanı: hassasiyet × hacim (etki) ve yönetişim açıkları (olasılık); risk kaydına aktarılabilir.
- Veri talepleri (erişim, maskeleme, anonimleştirme, takma ad, veri çıkarma): talep eden onaylayamaz; kişisel veri için işleme
  faaliyeti (amaç ve hukuki sebep) zorunludur; onayı veri sahibi, uygulamayı teknik sorumlu yapar.
- İlgili kişi başvuruları (md. 11/13): en geç 30 gün; gecikme işaretlenir.
- Veri koruma etki değerlendirmesi (VKED): hazırlayan onaylayamaz.
- KVKK ihlal kaydına etkilenen veri varlıkları bağlanır; kategoriler ve özel nitelik bilgisi önerilir.
"""
import csv
import io
import json
import re
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta, timezone

from .. import audit, auth as authz, crud
from ..db import fold, one, rows, utcnow
from ..http import API, Raw
from ..labels import CHOICES
from ..schema import RESOURCES, Resource, fk
from . import reminder
from .core import policy
from .datagov import COLUMNS, EFFECTIVE, M, SOURCES, TABLES, TERMS, _effective, _ids, _me, _qualified, _same, _writable

PRIVACY_ROLES = {"ADMIN", "SUPPLIER_MANAGER"}
LEGAL_BASES = ("explicit_consent", "law", "vital_interest", "contract", "legal_obligation", "made_public", "legal_claims",
               "legitimate_interest")
SPECIAL_BASES = ("explicit_consent", "law", "vital_interest", "made_public", "legal_claims", "health_services",
                 "employment_social_security", "foundation_members")
TRANSFER = ("none", "adequacy", "standard_contract", "bcr", "undertaking", "incidental")
CLASS_ORDER = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

DEFAULT_POLICIES = {
    "privacy.min_class_personal": ("confidential", "Kişisel veri kolonunun en düşük gizlilik sınıfı (kabul edilen öneri sınıfı yükseltir)."),
    "privacy.min_class_special": ("restricted", "Özel nitelikli kişisel veri kolonunun en düşük gizlilik sınıfı."),
    "privacy.sample_threshold": (0.6, "Örnek doğrulamada öneri için geçerli değer oranı (0–1)."),
    "privacy.disposal_interval_months": (6, "Periyodik imha aralığı (ay). Yönetmelik üst sınırı 6 aydır."),
    "privacy.subject_request_days": (30, "İlgili kişi başvurusunun yanıt süresi (gün). KVKK md. 13: en geç 30 gün."),
    "privacy.transfer_notice_business_days": (5, "Standart sözleşmenin Kurula bildirim süresi (iş günü)."),
    "privacy.risk_volume_buckets": ([1000, 100000, 1000000, 10000000], "Satır sayısına göre hacim puanı sınırları (1–5)."),
}

CATEGORIES = Resource("personal_data_categories", "Kişisel Veri Kategorileri", {
    "name": "TEXT NOT NULL UNIQUE", "special": "INTEGER NOT NULL DEFAULT 0", "description": "TEXT", "keywords": "TEXT",
    "weak_keywords": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1", "sort": "INTEGER", "created_at": "TIMESTAMP NOT NULL",
    "updated_at": "TIMESTAMP"}, module=M, write="manage", search=("name", "keywords"))
SUBJECT_GROUPS = Resource("data_subject_groups", "İlgili Kişi Grupları", {
    "name": "TEXT NOT NULL UNIQUE", "description": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"}, module=M, write="manage", search=("name",))
Resource("column_categories", "Kolon kişisel veri kategorisi", {
    "column_id": fk("data_columns"), "category_id": fk("personal_data_categories"), "source": "TEXT NOT NULL DEFAULT 'manual'",
    "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL"}, module=M, unique=(("column_id", "category_id"),), api=(), search=())
SUGGESTIONS = Resource("pii_suggestions", "Kişisel Veri Önerileri", {
    "column_id": fk("data_columns"), "category_id": fk("personal_data_categories"), "confidence": "REAL NOT NULL",
    "method": "TEXT NOT NULL", "evidence": "TEXT", "status": "TEXT NOT NULL DEFAULT 'pending'", "decided_by": "TEXT",
    "decided_at": "TIMESTAMP", "decision_note": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, api=("list", "get"), unique=(("column_id", "category_id"),), search=("evidence",), write="manage",
    enums={"method": ("name", "description", "term", "sample", "lineage"), "status": ("pending", "accepted", "rejected")})

RETENTION = Resource("retention_rules", "Saklama ve İmha Kuralları", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "category_id": fk("personal_data_categories", False),
    "legal_reference": "TEXT", "period_value": "INTEGER NOT NULL", "period_unit": "TEXT NOT NULL DEFAULT 'year'",
    "trigger_event": "TEXT NOT NULL", "disposal_method": "TEXT NOT NULL DEFAULT 'deletion'", "owner": "TEXT",
    "description": "TEXT", "active": "INTEGER NOT NULL DEFAULT 1", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="SS", write="manage", search=("code", "name", "legal_reference"),
    enums={"period_unit": ("day", "month", "year"), "disposal_method": ("deletion", "destruction", "anonymization")})

ACTIVITIES = Resource("processing_activities", "İşleme Faaliyetleri (VERBİS)", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "purpose": "TEXT NOT NULL", "description": "TEXT",
    "process_id": fk("processes", False), "org_unit_id": fk("org_units", False), "domain_id": fk("data_domains", False),
    "owner": "TEXT", "legal_basis": "TEXT", "special_legal_basis": "TEXT", "legal_basis_note": "TEXT", "recipients": "TEXT",
    "foreign_transfer": "INTEGER NOT NULL DEFAULT 0", "transfer_countries": "TEXT", "transfer_mechanism": "TEXT",
    "transfer_signed_on": "DATE", "transfer_notified_on": "DATE", "retention_rule_id": fk("retention_rules", False),
    "security_measures": "TEXT", "notice_document_id": fk("documents", False), "profiling": "INTEGER NOT NULL DEFAULT 0",
    "large_scale": "INTEGER NOT NULL DEFAULT 0", "new_technology": "INTEGER NOT NULL DEFAULT 0",
    "status": "TEXT NOT NULL DEFAULT 'draft'", "review_date": "DATE", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="IF", write="write", search=("code", "name", "purpose"),
    enums={"legal_basis": LEGAL_BASES, "special_legal_basis": SPECIAL_BASES, "transfer_mechanism": TRANSFER,
           "status": ("draft", "active", "retired")})
for _name, _col, _target in (("processing_categories", "category_id", "personal_data_categories"),
                             ("processing_subjects", "subject_group_id", "data_subject_groups"),
                             ("processing_columns", "column_id", "data_columns"), ("processing_tables", "table_id", "data_tables")):
    Resource(_name, "İşleme faaliyeti eşlemesi", {"activity_id": fk("processing_activities"), _col: fk(_target)},
             module=M, unique=(("activity_id", _col),), api=(), search=())
Resource("processing_processors", "Veri işleyen / alıcı tedarikçi", {
    "activity_id": fk("processing_activities"), "supplier_id": fk("suppliers"), "role": "TEXT NOT NULL DEFAULT 'processor'",
    "dpa_signed": "INTEGER NOT NULL DEFAULT 0", "note": "TEXT"},
    module=M, unique=(("activity_id", "supplier_id"),), api=(), search=(),
    enums={"role": ("processor", "joint_controller", "recipient")})

DPIAS = Resource("dpias", "Veri Koruma Etki Değerlendirmeleri", {
    "code": "TEXT UNIQUE", "activity_id": fk("processing_activities"), "title": "TEXT NOT NULL", "necessity": "TEXT",
    "risks": "TEXT", "measures": "TEXT", "residual_risk": "TEXT", "decision": "TEXT", "status": "TEXT NOT NULL DEFAULT 'draft'",
    "prepared_by": "TEXT", "submitted_at": "TIMESTAMP", "approver": "TEXT", "approved_at": "TIMESTAMP", "review_note": "TEXT",
    "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="VKED", write_roles=PRIVACY_ROLES, search=("code", "title"),
    readonly=("status", "prepared_by", "submitted_at", "approver", "approved_at", "review_note"),
    enums={"residual_risk": ("low", "medium", "high", "critical"),
           "decision": ("proceed", "proceed_with_measures", "do_not_proceed"),
           "status": ("draft", "in_review", "approved", "rejected")})

DISPOSALS = Resource("disposal_runs", "Periyodik İmha", {
    "code": "TEXT UNIQUE", "title": "TEXT NOT NULL", "planned_date": "DATE NOT NULL", "owner": "TEXT",
    "status": "TEXT NOT NULL DEFAULT 'planned'", "summary": "TEXT", "evidence_id": fk("evidence", False),
    "performed_by": "TEXT", "completed_at": "TIMESTAMP", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="IMH", code_yearly=True, write="manage", search=("code", "title"),
    readonly=("status", "performed_by", "completed_at"),
    enums={"status": ("planned", "in_progress", "completed", "cancelled")})
DISPOSAL_ITEMS = Resource("disposal_items", "Periyodik imha kalemleri", {
    "run_id": fk("disposal_runs"), "table_id": fk("data_tables"), "rule_id": fk("retention_rules", False),
    "method": "TEXT", "outcome": "TEXT NOT NULL DEFAULT 'pending'", "record_count": "INTEGER", "note": "TEXT",
    "updated_by": "TEXT", "updated_at": "TIMESTAMP"},
    module=M, api=("list", "get", "update"), unique=(("run_id", "table_id"),), write="manage", search=("note",),
    readonly=("run_id", "table_id", "updated_by"),
    enums={"method": ("deletion", "destruction", "anonymization"), "outcome": ("pending", "done", "not_needed", "failed")})

REQUESTS = Resource("data_requests", "Veri Talepleri", {
    "code": "TEXT UNIQUE", "kind": "TEXT NOT NULL", "table_id": fk("data_tables"), "org_unit_id": fk("org_units", False),
    "purpose": "TEXT NOT NULL", "activity_id": fk("processing_activities", False), "environment": "TEXT",
    "access_until": "DATE", "requested_by": "TEXT", "status": "TEXT NOT NULL DEFAULT 'requested'", "approver": "TEXT",
    "decided_at": "TIMESTAMP", "decision_note": "TEXT", "fulfilled_by": "TEXT", "fulfilled_at": "TIMESTAMP",
    "fulfillment_note": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="VT", code_yearly=True, write="write", search=("code", "purpose"),
    readonly=("requested_by", "status", "approver", "decided_at", "decision_note", "fulfilled_by", "fulfilled_at",
              "fulfillment_note"),
    enums={"kind": ("access", "extract", "masking", "anonymization", "pseudonymization"),
           "status": ("requested", "approved", "rejected", "fulfilled", "cancelled")})
Resource("data_request_columns", "Talep edilen kolonlar", {"request_id": fk("data_requests"), "column_id": fk("data_columns")},
         module=M, unique=(("request_id", "column_id"),), api=(), search=())

SUBJECT_REQUESTS = Resource("subject_requests", "İlgili Kişi Başvuruları", {
    "code": "TEXT UNIQUE", "received_on": "DATE NOT NULL", "channel": "TEXT NOT NULL DEFAULT 'email'",
    "request_type": "TEXT NOT NULL", "subject_group_id": fk("data_subject_groups", False), "subject_reference": "TEXT",
    "identity_verified": "INTEGER NOT NULL DEFAULT 0", "description": "TEXT NOT NULL", "owner": "TEXT NOT NULL",
    "due_date": "DATE", "status": "TEXT NOT NULL DEFAULT 'received'", "response_date": "DATE", "response_summary": "TEXT",
    "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="IKB", code_yearly=True, write_roles=PRIVACY_ROLES, read_roles=PRIVACY_ROLES | {"AUDITOR"},
    search=("code", "subject_reference"), readonly=("due_date", "created_by"),
    enums={"channel": ("email", "kep", "mail", "notary", "web", "in_person", "other"),
           "request_type": ("info", "access", "purpose", "recipients", "rectification", "erasure", "notify_third_parties",
                            "objection", "compensation", "other"),
           "status": ("received", "in_progress", "answered", "rejected")})
Resource("subject_request_tables", "Başvuruda incelenen veri varlıkları", {
    "request_id": fk("subject_requests"), "table_id": fk("data_tables")},
    module=M, unique=(("request_id", "table_id"),), api=(), search=())

Resource("breach_data_tables", "İhlalden etkilenen veri varlıkları", {
    "breach_id": fk("privacy_breaches"), "table_id": fk("data_tables"), "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL"},
    module=M, unique=(("breach_id", "table_id"),), api=(), search=())
Resource("risk_data_tables", "Riskle ilişkili veri varlıkları", {
    "risk_id": fk("supplier_risks"), "table_id": fk("data_tables"), "created_at": "TIMESTAMP NOT NULL"},
    module=M, unique=(("risk_id", "table_id"),), api=(), search=())

def _today():
    return date.today().isoformat()


def _day(value):
    return str(value)[:10] if value else None


def _notify(db, *args, **kw):
    from .. import notify
    return notify.enqueue(db, *args, **kw)


def _can_read(principal, res):
    return principal.role != "MACHINE" and (not res.read_roles or principal.role in res.read_roles)


def _scope_unit(db, record):
    return {record.get("org_unit_id")}


ACTIVITIES.scope = _scope_unit
REQUESTS.scope = _scope_unit


# ------------------------------------------------------------------ başlangıç verisi

CATEGORY_SEED = [
    ("Kimlik", 0, "Ad, soyad, T.C. kimlik numarası, doğum tarihi ve yeri, cinsiyet, uyruk, medeni hal, imza.",
     "tckn,tc_kimlik,tc_no,tcno,kimlik,kimlik_no,kimlikno,national_id,identity,identity_no,nufus,pasaport,passport,ehliyet,"
     "dogum,dogum_tarihi,birth,birthdate,birth_date,dob,gbdat,cinsiyet,gender,gendercode,gesch,uyruk,nationality,natio,"
     "medeni,medeni_hal,famst,marital,ad_soyad,adsoyad,fullname,full_name,firstname,first_name,lastname,last_name,soyad,"
     "soyadi,surname,vorna,nachn,stcd1", "ad,adi,isim,name,name1,name2"),
    ("İletişim", 0, "Telefon, e-posta, adres, KEP adresi.",
     "telefon,tel,telf,telf1,phone,telephone,telephone1,mobile,mobilephone,mobile_phone,cep,cep_telefonu,gsm,eposta,e_posta,"
     "email,emailaddress,emailaddress1,e_mail,smtp_addr,adres,address,address1,stras,sokak,posta_kodu,postcode,kep",
     "mail,fax,pstlz,zip"),
    ("Lokasyon", 0, "Konum ve hareket bilgisi.", "konum,location,lokasyon,latitude,longitude,gps,koordinat,coordinate",
     "sehir,city,ilce,ort01,address1_city,lat,lon,lng"),
    ("Özlük", 0, "Personel numarası, bordro, izin, performans ve özlük dosyası bilgileri.",
     "personel,personel_no,sicil,sicil_no,pernr,employee_id,employeeid,bordro,payroll,maas,salary,ucret,wage,izin,performans",
     "employee,unvan,departman,department"),
    ("Hukuki İşlem", 0, "Dava, icra ve yazışma bilgileri.", "dava,icra,ihtarname,mahkeme,court,lawsuit", ""),
    ("Müşteri İşlem", 0, "Sipariş, fatura, talep ve şikâyet kayıtları.", "sikayet,complaint,talep_gecmisi,siparis_gecmisi",
     "musteri,customer,kunnr,customerid,caller_id,parentcustomerid"),
    ("Fiziksel Mekân Güvenliği", 0, "Giriş-çıkış ve kamera kayıtları.", "giris_cikis,turnike,ziyaretci,visitor,cctv,kamera", ""),
    ("İşlem Güvenliği", 0, "IP adresi, kullanıcı hesabı, erişim ve işlem kayıtları.",
     "ip,ip_adresi,ip_address,ipaddress,mac_address,user_name,username,kullanici_adi,login,device_id,cihaz_id",
     "user,kullanici,usnam,log,mac"),
    ("Finans", 0, "IBAN, banka hesabı, kart, gelir ve borç bilgileri.",
     "iban,hesap_no,account_no,banka_hesap,kart_no,card_number,pan,kredi_karti,credit_card", "kart,card,banka,bank,gelir,income"),
    ("Mesleki Deneyim", 0, "Eğitim, sertifika, özgeçmiş.", "diploma,egitim,education,sertifika,ozgecmis,resume", "cv"),
    ("Pazarlama", 0, "Alışveriş geçmişi, kampanya, bülten ve çerez bilgileri.",
     "kampanya,campaign,bulten,newsletter,abonelik,subscription,cerez,cookie,ilgi_alani,leadsourcecode", "segment,anket,survey"),
    ("Görsel ve İşitsel Kayıtlar", 0, "Fotoğraf, video ve ses kaydı.",
     "foto,fotograf,photo,image,resim,video,ses_kaydi,voice,recording", ""),
    ("Sağlık Bilgileri", 1, "Sağlık durumu, engellilik, kan grubu, tanı ve rapor bilgileri.",
     "saglik,health,medical,tibbi,tani,diagnosis,hastalik,illness,engelli,disability,kan_grubu,blood_type", ""),
    ("Biyometrik Veri", 1, "Parmak izi, yüz tanıma, retina.", "biyometrik,biometric,parmak_izi,fingerprint,yuz_tanima,face_id,iris,retina", ""),
    ("Genetik Veri", 1, "Genetik ve DNA bilgisi.", "genetik,genetic,dna", ""),
    ("Ceza Mahkûmiyeti ve Güvenlik Tedbirleri", 1, "Adli sicil ve mahkûmiyet bilgisi.", "sabika,adli_sicil,criminal,mahkumiyet", "ceza"),
    ("Din, Mezhep ve Felsefi İnanç", 1, "", "din,religion,mezhep,inanc,belief", ""),
    ("Irk ve Etnik Köken", 1, "", "irk,race,etnik,ethnic", ""),
    ("Siyasi Düşünce", 1, "", "siyasi,political,parti_uyeligi", ""),
    ("Dernek, Vakıf ve Sendika Üyeliği", 1, "", "sendika,union_member,dernek,vakif", ""),
    ("Cinsel Hayat", 1, "", "cinsel,sexual", ""),
    ("Kılık ve Kıyafet", 1, "", "kilik_kiyafet,kiyafet", ""),
]
SUBJECT_SEED = ["Çalışan", "Çalışan Adayı", "Stajyer", "Müşteri", "Potansiyel Müşteri", "Tedarikçi Yetkilisi",
                "Tedarikçi Çalışanı", "Ziyaretçi", "Hissedar / Ortak", "Veli / Vasi / Temsilci", "İş Ortağı Yetkilisi",
                "Ürün veya Hizmet Kullanıcısı"]
DETECTORS = {"tckn": ("T.C. kimlik numarası", "Kimlik"), "iban": ("IBAN", "Finans"), "card": ("kart numarası", "Finans"),
             "email": ("e-posta adresi", "İletişim"), "phone": ("telefon numarası", "İletişim"),
             "ipv4": ("IP adresi", "İşlem Güvenliği")}


def seed(db):
    now = utcnow()
    for order, (name, special, desc, strong, weak) in enumerate(CATEGORY_SEED):
        db.execute("""INSERT INTO tdr_personal_data_categories (name, special, description, keywords, weak_keywords, active,
            sort, created_at) VALUES (?,?,?,?,?,1,?,?) ON CONFLICT DO NOTHING""", (name, special, desc, strong, weak, order, now))
    for name in SUBJECT_SEED:
        db.execute("INSERT INTO tdr_data_subject_groups (name, active, created_at) VALUES (?,1,?) ON CONFLICT DO NOTHING",
                   (name, now))
    for code, (value, description) in DEFAULT_POLICIES.items():
        db.execute("INSERT INTO tdr_policies (code, value_json, description) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                   (code, json.dumps(value), description))


# ------------------------------------------------------------------ kişisel veri keşfi

def _tokens(text):
    raw = re.sub(r"(?<=[a-zçğıöşü0-9])(?=[A-ZÇĞİÖŞÜ])", "_", str(text or ""))
    parts = [p for p in re.split(r"[^a-z0-9]+", fold(raw)) if p]
    out = set(parts)
    out |= {p.rstrip("0123456789") for p in parts if p.rstrip("0123456789")}
    return parts, out


def _keywords(text):
    return [k.strip() for k in fold(text or "").replace(" ", "_").split(",") if k.strip()]


def _match(text, keywords):
    parts, tokens = _tokens(text)
    joined = "_" + "_".join(parts) + "_"
    joined_nodigit = "_" + "_".join(p.rstrip("0123456789") or p for p in parts) + "_"
    for k in keywords:
        if k in tokens or ("_" in k and (f"_{k}_" in joined or f"_{k}_" in joined_nodigit)):
            return k
    return None


def categories(db):
    return rows(db, "SELECT * FROM tdr_personal_data_categories WHERE active=1 ORDER BY COALESCE(sort, 1000), name")


def _upsert_suggestion(db, column_id, category_id, confidence, method, evidence, now, counts):
    if one(db, "SELECT 1 AS x FROM tdr_column_categories WHERE column_id=? AND category_id=?", (column_id, category_id)):
        return
    cur = one(db, "SELECT * FROM tdr_pii_suggestions WHERE column_id=? AND category_id=?", (column_id, category_id))
    if cur is None:
        db.execute("""INSERT INTO tdr_pii_suggestions (column_id, category_id, confidence, method, evidence, status, created_at,
            updated_at) VALUES (?,?,?,?,?,'pending',?,?)""", (column_id, category_id, round(confidence, 2), method, evidence[:500], now, now))
        counts["new"] += 1
    elif cur["status"] == "pending" and confidence > float(cur["confidence"]) + 1e-9:
        db.execute("UPDATE tdr_pii_suggestions SET confidence=?, method=?, evidence=?, updated_at=? WHERE id=?",
                   (round(confidence, 2), method, evidence[:500], now, cur["id"]))
        counts["updated"] += 1


def discover(db, source_id=None):
    """Meta veriden öneri üretir. Zayıf anahtar kelime (ör. 'ad', 'name') yalnızca aynı tabloda güçlü bir eşleşme varsa
    öneri olur; böylece ürün adı gibi kolonlar gürültü yapmaz. Daha önce reddedilen öneri yeniden açılmaz."""
    cats = [(c, _keywords(c["keywords"]), _keywords(c["weak_keywords"])) for c in categories(db)]
    term_cats = {r["column_id"]: r for r in rows(db, """SELECT m.column_id, g.category_id, g.personal_data, g.name
        FROM tdr_term_columns m JOIN tdr_glossary_terms g ON g.id=m.term_id WHERE g.category_id IS NOT NULL
        AND g.status<>'retired'""")}
    where, args = ["c.status='active'", "t.status<>'removed'"], []
    if source_id:
        where.append("t.source_id=?")
        args.append(source_id)
    cols = rows(db, f"""SELECT c.id, c.table_id, c.name, c.business_name, c.technical_description, c.personal_data
        FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id WHERE {' AND '.join(where)}
        ORDER BY c.table_id, c.id""", args)
    found = {}                                # column_id -> [(category, confidence, method, evidence, weak)]
    strong_tables = set()
    for col in cols:
        hits = []
        for cat, strong, weak in cats:
            key = _match(col["name"], strong)
            if key:
                hits.append((cat, 0.85, "name", f"Kolon adı '{col['name']}' → '{key}'", False))
                continue
            text = " ".join(x for x in (col["business_name"], col["technical_description"]) if x)
            key = _match(text, strong) if text else None
            if key:
                hits.append((cat, 0.7, "description", f"Açıklama '{text[:60]}' → '{key}'", False))
                continue
            key = _match(col["name"], weak) or (_match(text, weak) if text else None)
            if key:
                hits.append((cat, 0.45, "name", f"Zayıf eşleşme: '{col['name']}' → '{key}'", True))
        term = term_cats.get(col["id"])
        if term:
            cat = next((c for c, _, _ in cats if c["id"] == term["category_id"]), None)
            if cat:
                hits.append((cat, 0.95, "term", f"Bağlı terim '{term['name']}' bu kategoride", False))
        if any(not h[4] for h in hits):
            strong_tables.add(col["table_id"])
        if hits:
            found[col["id"]] = (col["table_id"], hits)
    now, counts = utcnow(), Counter()
    for column_id, (table_id, hits) in found.items():
        best = {}
        for cat, conf, method, evidence, weak in hits:
            if weak and table_id not in strong_tables:
                continue
            if cat["id"] not in best or conf > best[cat["id"]][1]:
                best[cat["id"]] = (cat, conf, method, evidence)
        for cat, conf, method, evidence in best.values():
            _upsert_suggestion(db, column_id, cat["id"], conf, method, evidence, now, counts)
    # Soy kütüğü (K-031): kategorisi belli kolondan doğrudan veya dönüşümle beslenen kolon aynı kategoride önerilir.
    lineage_where = "AND tt.source_id=?" if source_id else ""
    for r in rows(db, f"""SELECT e.target_column_id, cc.category_id, sc.name AS source_column, st.name AS source_table
            FROM tdr_lineage_edges e JOIN tdr_column_categories cc ON cc.column_id=e.source_column_id
            JOIN tdr_data_columns sc ON sc.id=e.source_column_id JOIN tdr_data_tables st ON st.id=e.source_table_id
            JOIN tdr_data_columns tc ON tc.id=e.target_column_id JOIN tdr_data_tables tt ON tt.id=e.target_table_id
            WHERE e.status='active' AND e.kind IN ('direct','transform') AND tc.status='active' {lineage_where}""",
                  (source_id,) if source_id else ()):
        _upsert_suggestion(db, r["target_column_id"], r["category_id"], 0.9, "lineage",
                           f"Soy kütüğü: {r['source_table']}.{r['source_column']} kolonundan geliyor", now, counts)
    return {"scanned_columns": len(cols), "new": counts["new"], "updated": counts["updated"]}


def discovery_run(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "manage")
    source_id = c.body.get("source_id")
    if source_id is not None:
        crud.get(c.db, SOURCES, int(source_id))
    result = discover(c.db, int(source_id) if source_id else None)
    audit.log(c.db, c.principal, "DISCOVER", "data_sources", source_id or 0, result)
    return result


def _min_class(db, special):
    return policy(db, "privacy.min_class_special" if special else "privacy.min_class_personal",
                  "restricted" if special else "confidential")


def apply_category(db, column, category, principal, source="manual"):
    """Kategoriyi kolona işler: kişisel veri işareti ve en düşük gizlilik sınıfı."""
    db.execute("INSERT INTO tdr_column_categories (column_id, category_id, source, created_by, created_at) VALUES (?,?,?,?,?) "
               "ON CONFLICT DO NOTHING", (column["id"], category["id"], source, principal.username if principal else "system", utcnow()))
    kind = "special" if category["special"] else "personal"
    sets = {}
    if column["personal_data"] != "special" and column["personal_data"] != kind:
        sets["personal_data"] = kind
    floor = _min_class(db, bool(category["special"]))
    table = one(db, "SELECT classification FROM tdr_data_tables WHERE id=?", (column["table_id"],))
    effective = column["classification"] or (table["classification"] if table else None)
    if CLASS_ORDER.get(effective, -1) < CLASS_ORDER.get(floor, 2):
        sets["classification"] = floor
    if sets:
        db.execute(f"UPDATE tdr_data_columns SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?",
                   (*sets.values(), utcnow(), column["id"]))
    return sets


def _decide(c, suggestion, accept, note=None):
    column = crud.get(c.db, COLUMNS, suggestion["column_id"])
    _writable(c, COLUMNS, column)
    if suggestion["status"] != "pending":
        raise crud.Conflict("Öneri zaten sonuçlandırılmış")
    now = utcnow()
    changes = {}
    if accept:
        category = crud.get(c.db, CATEGORIES, suggestion["category_id"])
        changes = apply_category(c.db, column, category, c.principal, source="suggestion")
    c.db.execute("UPDATE tdr_pii_suggestions SET status=?, decided_by=?, decided_at=?, decision_note=?, updated_at=? WHERE id=?",
                 ("accepted" if accept else "rejected", c.principal.username, now, (note or "")[:500] or None, now, suggestion["id"]))
    audit.log(c.db, c.principal, "ACCEPT" if accept else "REJECT", "pii_suggestions", suggestion["id"],
              {"column_id": column["id"], "category_id": suggestion["category_id"], "changes": changes})
    return changes


def suggestion_accept(c):
    s = crud.get(c.db, SUGGESTIONS, c.params["id"])
    return {"changes": _decide(c, s, True)}


def suggestion_reject(c):
    s = crud.get(c.db, SUGGESTIONS, c.params["id"])
    _decide(c, s, False, c.body.get("note") or "Kişisel veri değil")
    return {"ok": True}


def suggestion_bulk(c):
    authz.require_human(c.principal)
    ids = _ids(c.body.get("ids"), "Öneri")
    action = c.body.get("action")
    if action not in ("accept", "reject") or not ids:
        raise crud.Invalid("Öneri seçin ve işlem belirtin")
    out = {"done": 0, "errors": []}
    for sid in ids[:1000]:
        try:
            with c.db.savepoint():
                _decide(c, crud.get(c.db, SUGGESTIONS, sid), action == "accept", c.body.get("note"))
            out["done"] += 1
        except (crud.Invalid, crud.Forbidden, crud.NotFound, crud.Conflict) as exc:
            if len(out["errors"]) < 50:
                out["errors"].append({"id": sid, "message": str(exc)})
    return out


def suggestion_list(c):
    authz.check(c.principal, SUGGESTIONS, "read")
    q = c.query
    where, args = ["c.status='active'"], []
    status = q.get("status") or "pending"
    if status != "all":
        where.append("s.status=?")
        args.append(status)
    if q.get("source_id"):
        where.append("t.source_id=?")
        args.append(int(q["source_id"]))
    if q.get("table_id"):
        where.append("t.id=?")
        args.append(int(q["table_id"]))
    if q.get("min_confidence"):
        where.append("s.confidence >= ?")
        args.append(float(q["min_confidence"]))
    items = rows(c.db, f"""SELECT s.*, k.name AS category_name, k.special, c.name AS column_name, c.business_name,
        c.data_type, c.personal_data, c.classification, t.id AS table_id, t.schema_name, t.name AS table_name,
        sr.id AS source_id, sr.name AS source_name FROM tdr_pii_suggestions s
        JOIN tdr_personal_data_categories k ON k.id=s.category_id JOIN tdr_data_columns c ON c.id=s.column_id
        JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources sr ON sr.id=t.source_id
        WHERE {' AND '.join(where)} ORDER BY sr.name, t.name, s.confidence DESC, c.name LIMIT 1000""", args)
    counts = {r["status"]: r["n"] for r in rows(c.db, "SELECT status, COUNT(*) AS n FROM tdr_pii_suggestions GROUP BY status")}
    return {"items": items, "counts": counts}


def sample_stats(c):
    """Tarayıcıda (veya `python -m tedarik.pii` ile) hesaplanan örnek sayıları: değerler gönderilmez, yalnızca sayılar."""
    table = crud.get(c.db, TABLES, c.params["id"])
    _writable(c, TABLES, table)
    result = apply_sample_stats(c.db, table, c.body.get("columns"), c.principal, c.body.get("sample_size"))
    audit.log(c.db, c.principal, "SAMPLE_STATS", "data_tables", table["id"],
              {"sample_size": c.body.get("sample_size"), "findings": result["findings"]})
    return result


def apply_sample_stats(db, table, columns, principal, sample_size=None):
    """Örnek sayılarından öneri üretir (ekran, `python -m tedarik.pii` ve toplayıcı ortak yolu). Değer almaz."""
    if not isinstance(columns, dict) or not columns or len(columns) > 2000:
        raise crud.Invalid("Kolon istatistikleri bekleniyor")
    threshold = float(policy(db, "privacy.sample_threshold", 0.6))
    cats = {r["name"]: r for r in categories(db)}
    known = {r["name"].lower(): r for r in rows(db, "SELECT id, name FROM tdr_data_columns WHERE table_id=? AND status='active'",
                                                    (table["id"],))}
    now, counts, unknown, findings = utcnow(), Counter(), [], []
    for name, stat in columns.items():
        if not isinstance(stat, dict):
            raise crud.Invalid("Kolon istatistiği geçersiz")
        col = known.get(str(name).strip().lower())
        if col is None:
            unknown.append(str(name)[:80])
            continue
        try:
            non_empty = int(stat.get("non_empty") or 0)
            matches = {str(k): int(v) for k, v in (stat.get("matches") or {}).items()}
        except (TypeError, ValueError):
            raise crud.Invalid("İstatistikler tamsayı olmalı") from None
        if non_empty < 5:
            continue
        for key, hits in matches.items():
            if key not in DETECTORS or hits < 0 or hits > non_empty:
                continue
            ratio = hits / non_empty
            if ratio < threshold:
                continue
            label, cat_name = DETECTORS[key]
            cat = cats.get(cat_name)
            if not cat:
                continue
            evidence = f"Örnek: {non_empty} dolu değerin %{round(100 * ratio)}'i geçerli {label}"
            _upsert_suggestion(db, col["id"], cat["id"], min(0.99, 0.6 + 0.4 * ratio), "sample", evidence, now, counts)
            findings.append({"column": col["name"], "detector": key, "ratio": round(ratio, 3)})
    return {"new": counts["new"], "updated": counts["updated"], "findings": findings, "unknown_columns": unknown[:50]}


def column_categories(c):
    """Kolonun kişisel veri kategorilerini elle belirler (kümeyi değiştirir)."""
    column = crud.get(c.db, COLUMNS, c.params["id"])
    _writable(c, COLUMNS, column)
    ids = _ids(c.body.get("category_ids"), "Kategori")
    cats = {r["id"]: r for r in rows(c.db, f"SELECT * FROM tdr_personal_data_categories WHERE id IN ({','.join('?' * len(ids))})",
                                     ids)} if ids else {}
    if len(cats) != len(ids):
        raise crud.Invalid("Bulunamayan kategori seçildi")
    c.db.execute("DELETE FROM tdr_column_categories WHERE column_id=?", (column["id"],))
    for cid in ids:
        apply_category(c.db, crud.get(c.db, COLUMNS, column["id"]), cats[cid], c.principal)
    if not ids and column["personal_data"] in ("personal", "special"):
        c.db.execute("UPDATE tdr_data_columns SET personal_data='none', updated_at=? WHERE id=?", (utcnow(), column["id"]))
    c.db.execute("UPDATE tdr_pii_suggestions SET status='accepted', decided_by=?, decided_at=?, updated_at=? WHERE column_id=? "
                 f"AND status='pending' AND category_id IN ({','.join('?' * len(ids)) or 'NULL'})",
                 (c.principal.username, utcnow(), utcnow(), column["id"], *ids))
    audit.log(c.db, c.principal, "CATEGORIES", "data_columns", column["id"], {"category_ids": ids})
    return {"category_ids": ids}


# ------------------------------------------------------------------ işleme envanteri

def _activity_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if merged.get("foreign_transfer") and merged.get("status") == "active" and not merged.get("transfer_countries"):
        raise crud.Invalid("Yurt dışı aktarımda alıcı ülkeleri yazın")
    for key, label in (("transfer_signed_on", "Sözleşme tarihi"), ("transfer_notified_on", "Kurula bildirim tarihi"),
                       ("review_date", "Gözden geçirme tarihi")):
        value = merged.get(key)
        if value and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)[:10]):
            raise crud.Invalid(f"{label} geçerli bir tarih olmalı")
    if data.get("status") == "active" and not merged.get("legal_basis"):
        raise crud.Invalid("Faaliyeti etkinleştirmeden önce hukuki sebebi seçin (KVKK md. 5)")


ACTIVITIES.before_save = _activity_rules


def _business_days(start, n):
    d = date.fromisoformat(_day(start))
    added = 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d.isoformat()


def activity_categories(db, activity_id):
    return rows(db, """SELECT k.id, k.name, k.special FROM tdr_processing_categories m JOIN tdr_personal_data_categories k
        ON k.id=m.category_id WHERE m.activity_id=? ORDER BY k.sort, k.name""", (activity_id,))


def linked_column_categories(db, activity_id):
    """Faaliyete bağlı kolonlarda (doğrudan veya tablo üzerinden) görülen kategoriler."""
    return rows(db, """SELECT DISTINCT k.id, k.name, k.special FROM tdr_column_categories cc
        JOIN tdr_personal_data_categories k ON k.id=cc.category_id JOIN tdr_data_columns c ON c.id=cc.column_id
        WHERE c.status='active' AND (c.id IN (SELECT column_id FROM tdr_processing_columns WHERE activity_id=?)
        OR c.table_id IN (SELECT table_id FROM tdr_processing_tables WHERE activity_id=?)) ORDER BY k.name""",
                (activity_id, activity_id))


def activity_gaps(db, a, cats=None, subjects=None):
    """Envanter açıkları: her madde kural, açıklama ve önem taşır."""
    cats = activity_categories(db, a["id"]) if cats is None else cats
    subjects = rows(db, "SELECT subject_group_id FROM tdr_processing_subjects WHERE activity_id=?", (a["id"],)) \
        if subjects is None else subjects
    observed = linked_column_categories(db, a["id"])
    special = any(k["special"] for k in list(cats) + observed)       # bağlı kolonlarda görülen özel nitelik de sayılır
    gaps = []

    def gap(key, text, severity):
        gaps.append({"key": key, "text": text, "severity": severity})
    if not a["legal_basis"]:
        gap("legal_basis", "Hukuki sebep seçilmemiş (KVKK md. 5).", "high")
    elif a["legal_basis"] == "legitimate_interest" and not a["legal_basis_note"]:
        gap("balance_test", "Meşru menfaat dayanağında denge testi açıklaması yok.", "medium")
    if special and not a["special_legal_basis"]:
        gap("special_basis", "Özel nitelikli kişisel veri var, KVKK md. 6 hukuki sebebi seçilmemiş.", "high")
    if not cats:
        gap("categories", "Kişisel veri kategorisi seçilmemiş.", "medium")
    if not subjects:
        gap("subjects", "İlgili kişi grubu seçilmemiş.", "medium")
    if not a["retention_rule_id"]:
        gap("retention", "Saklama süresi (saklama ve imha kuralı) bağlanmamış.", "high")
    if not a["notice_document_id"]:
        gap("notice", "Aydınlatma metni bağlanmamış (KVKK md. 10).", "medium")
    if a["foreign_transfer"]:
        mech = a["transfer_mechanism"]
        if not mech or mech == "none":
            gap("transfer", "Yurt dışı aktarım var, aktarım mekanizması belirlenmemiş (KVKK md. 9).", "high")
        elif mech == "standard_contract":
            if not a["transfer_signed_on"] or not a["transfer_notified_on"]:
                gap("transfer_notice", "Standart sözleşme imza ve Kurula bildirim tarihleri girilmemiş.", "high")
            else:
                limit = _business_days(a["transfer_signed_on"], 5)
                if _day(a["transfer_notified_on"]) > limit:
                    gap("transfer_late", f"Standart sözleşme Kurula geç bildirilmiş (son gün {limit}).", "medium")
    if not a["security_measures"]:
        gap("measures", "Teknik ve idari tedbirler yazılmamış (KVKK md. 12).", "low")
    if dpia_required(a, list(cats) + observed) and not one(db, "SELECT id FROM tdr_dpias WHERE activity_id=? AND status='approved'", (a["id"],)):
        gap("dpia", "Bu faaliyet için onaylı veri koruma etki değerlendirmesi (VKED) yok.", "medium")
    if a["review_date"] and _day(a["review_date"]) < _today():
        gap("review", "Gözden geçirme tarihi geçmiş.", "low")
    missing = [k["name"] for k in observed if k["id"] not in {x["id"] for x in cats}]
    if missing:
        gap("categories_mismatch", "Bağlı kolonlarda envanterde olmayan kategori var: " + ", ".join(missing), "medium")
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(gaps, key=lambda g: order[g["severity"]])


def dpia_required(a, cats):
    return bool(any(k["special"] for k in cats) or a["profiling"] or a["large_scale"] or a["new_technology"] or
                (a["foreign_transfer"] and a["transfer_mechanism"] not in ("adequacy",)))


def activity_context(c):
    authz.check(c.principal, ACTIVITIES, "read")
    db = c.db
    a = crud.get(db, ACTIVITIES, c.params["id"])
    a["categories"] = activity_categories(db, a["id"])
    a["subjects"] = rows(db, """SELECT g.id, g.name FROM tdr_processing_subjects m JOIN tdr_data_subject_groups g
        ON g.id=m.subject_group_id WHERE m.activity_id=? ORDER BY g.name""", (a["id"],))
    a["columns"] = rows(db, """SELECT c.id, c.name, c.business_name, c.personal_data, t.id AS table_id, t.schema_name,
        t.name AS table_name, s.name AS source_name FROM tdr_processing_columns m JOIN tdr_data_columns c ON c.id=m.column_id
        JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources s ON s.id=t.source_id WHERE m.activity_id=?
        ORDER BY s.name, t.name, c.name""", (a["id"],))
    a["tables"] = rows(db, """SELECT t.id, t.schema_name, t.name, t.business_name, s.name AS source_name, t.row_count
        FROM tdr_processing_tables m JOIN tdr_data_tables t ON t.id=m.table_id JOIN tdr_data_sources s ON s.id=t.source_id
        WHERE m.activity_id=? ORDER BY s.name, t.name""", (a["id"],))
    a["processors"] = rows(db, """SELECT p.*, s.code AS supplier_code, s.name AS supplier_name FROM tdr_processing_processors p
        JOIN tdr_suppliers s ON s.id=p.supplier_id WHERE p.activity_id=? ORDER BY s.name""", (a["id"],))
    a["observed_categories"] = linked_column_categories(db, a["id"])
    a["retention_rule"] = one(db, "SELECT * FROM tdr_retention_rules WHERE id=?", (a["retention_rule_id"],)) if a["retention_rule_id"] else None
    a["notice_document"] = one(db, "SELECT id, code, title, status FROM tdr_documents WHERE id=?", (a["notice_document_id"],)) \
        if a["notice_document_id"] else None
    a["dpias"] = rows(db, "SELECT id, code, title, status, residual_risk, decision, approved_at FROM tdr_dpias WHERE activity_id=? "
                          "ORDER BY id DESC", (a["id"],))
    a["dpia_required"] = dpia_required(a, a["categories"] + a["observed_categories"])
    a["gaps"] = activity_gaps(db, a, a["categories"], a["subjects"])
    if a["transfer_mechanism"] == "standard_contract" and a["transfer_signed_on"]:
        a["transfer_notice_deadline"] = _business_days(a["transfer_signed_on"],
                                                       int(policy(db, "privacy.transfer_notice_business_days", 5)))
    try:
        crud.check_scope(db, ACTIVITIES, c.principal, a)
        a["can_edit"] = authz.can_write(c.principal, ACTIVITIES) and c.principal.auth_type != "api_key"
    except crud.Forbidden:
        a["can_edit"] = False
    return a


LINK_KEYS = {"categories": ("tdr_processing_categories", "category_id", "personal_data_categories"),
             "subjects": ("tdr_processing_subjects", "subject_group_id", "data_subject_groups"),
             "columns": ("tdr_processing_columns", "column_id", "data_columns"),
             "tables": ("tdr_processing_tables", "table_id", "data_tables")}


def activity_links(c):
    a = crud.get(c.db, ACTIVITIES, c.params["id"])
    _writable(c, ACTIVITIES, a)
    changed = {}
    for key, (table, col, target) in LINK_KEYS.items():
        if key not in c.body:
            continue
        ids = _ids(c.body[key], key)
        res = RESOURCES[target]
        if ids and len(rows(c.db, f"SELECT id FROM {res.table} WHERE id IN ({','.join('?' * len(ids))})", ids)) != len(ids):
            raise crud.Invalid(f"{res.label}: bulunamayan kayıt seçildi")
        c.db.execute(f"DELETE FROM {table} WHERE activity_id=?", (a["id"],))
        for target_id in ids:
            c.db.execute(f"INSERT INTO {table} (activity_id, {col}) VALUES (?,?)", (a["id"], target_id))
        changed[key] = ids
    if "processors" in c.body:
        items = c.body["processors"]
        if not isinstance(items, list) or len(items) > 200:
            raise crud.Invalid("Veri işleyen listesi bekleniyor")
        c.db.execute("DELETE FROM tdr_processing_processors WHERE activity_id=?", (a["id"],))
        seen = set()
        for it in items:
            sid = int(it.get("supplier_id") or 0)
            if sid in seen:
                continue
            seen.add(sid)
            crud.get(c.db, RESOURCES["suppliers"], sid)
            role = it.get("role") or "processor"
            if role not in ("processor", "joint_controller", "recipient"):
                raise crud.Invalid("Rol veri işleyen, ortak veri sorumlusu veya alıcı olmalı")
            c.db.execute("INSERT INTO tdr_processing_processors (activity_id, supplier_id, role, dpa_signed, note) VALUES (?,?,?,?,?)",
                         (a["id"], sid, role, 1 if it.get("dpa_signed") else 0, (it.get("note") or "")[:500] or None))
        changed["processors"] = sorted(seen)
    if not changed:
        raise crud.Invalid("Değişiklik yok")
    audit.log(c.db, c.principal, "LINK", "processing_activities", a["id"], changed)
    return activity_context(c)


def adopt_observed(c):
    """Bağlı kolonlarda görülen kategorileri faaliyete ekler."""
    a = crud.get(c.db, ACTIVITIES, c.params["id"])
    _writable(c, ACTIVITIES, a)
    added = []
    for k in linked_column_categories(c.db, a["id"]):
        if not one(c.db, "SELECT 1 AS x FROM tdr_processing_categories WHERE activity_id=? AND category_id=?", (a["id"], k["id"])):
            c.db.execute("INSERT INTO tdr_processing_categories (activity_id, category_id) VALUES (?,?)", (a["id"], k["id"]))
            added.append(k["name"])
    audit.log(c.db, c.principal, "LINK", "processing_activities", a["id"], {"categories_added": added})
    return activity_context(c)


VERBIS_HEADERS = ["Kod", "İşleme faaliyeti", "Amaç", "Hukuki sebep (md. 5)", "Hukuki sebep (md. 6)", "Veri kategorileri",
                  "Özel nitelikli", "İlgili kişi grupları", "Alıcı grupları", "Veri işleyenler", "Yurt dışı aktarım",
                  "Ülkeler", "Aktarım mekanizması", "Saklama süresi", "İmha yöntemi", "Teknik ve idari tedbirler",
                  "Aydınlatma metni", "Sorumlu birim", "Sahip", "Durum"]


def _label(resource, name, value):
    if value in (None, ""):
        return ""
    table = CHOICES.get(f"{resource}.{name}") or CHOICES.get(name) or {}
    return table.get(value, value)


def verbis_rows(db):
    out = [VERBIS_HEADERS]
    for a in rows(db, """SELECT a.*, u.name AS unit_name, d.code AS doc_code, d.title AS doc_title FROM tdr_processing_activities a
            LEFT JOIN tdr_org_units u ON u.id=a.org_unit_id LEFT JOIN tdr_documents d ON d.id=a.notice_document_id
            WHERE a.status<>'retired' ORDER BY a.code"""):
        cats = activity_categories(db, a["id"])
        subjects = [r["name"] for r in rows(db, """SELECT g.name FROM tdr_processing_subjects m JOIN tdr_data_subject_groups g
            ON g.id=m.subject_group_id WHERE m.activity_id=? ORDER BY g.name""", (a["id"],))]
        processors = [f"{r['name']} ({_label('processing_processors', 'role', r['role'])})" for r in rows(db, """SELECT s.name,
            p.role FROM tdr_processing_processors p JOIN tdr_suppliers s ON s.id=p.supplier_id WHERE p.activity_id=?""", (a["id"],))]
        rule = one(db, "SELECT * FROM tdr_retention_rules WHERE id=?", (a["retention_rule_id"],)) if a["retention_rule_id"] else None
        out.append([a["code"], a["name"], a["purpose"], _label("processing_activities", "legal_basis", a["legal_basis"]),
                    _label("processing_activities", "special_legal_basis", a["special_legal_basis"]),
                    ", ".join(k["name"] for k in cats), "Evet" if any(k["special"] for k in cats) else "Hayır",
                    ", ".join(subjects), a["recipients"] or "", "; ".join(processors), "Evet" if a["foreign_transfer"] else "Hayır",
                    a["transfer_countries"] or "", _label("processing_activities", "transfer_mechanism", a["transfer_mechanism"]),
                    f"{rule['period_value']} {_label('retention_rules', 'period_unit', rule['period_unit'])} — {rule['trigger_event']}" if rule else "",
                    _label("retention_rules", "disposal_method", rule["disposal_method"]) if rule else "", a["security_measures"] or "",
                    f"{a['doc_code']} {a['doc_title']}" if a["doc_code"] else "", a["unit_name"] or "", a["owner"] or "",
                    _label("processing_activities", "status", a["status"])])
    return out


def verbis_export(c):
    authz.check(c.principal, ACTIVITIES, "read")
    data = verbis_rows(c.db)
    if c.query.get("format") == "xlsx":
        from .transfer import _xlsx
        return 200, Raw(_xlsx().make_xlsx(OrderedDict([("Envanter", data)])),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "kisisel-veri-envanteri.xlsx")
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    for row in data:
        writer.writerow([("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in row])
    return 200, Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "kisisel-veri-envanteri.csv")


# ------------------------------------------------------------------ VKED

def _dpia_rules(db, data, current, principal):
    if current is None and principal is not None:
        data["prepared_by"] = principal.username
    if current and principal is not None and current["status"] in ("in_review", "approved"):
        raise crud.Invalid("Onaydaki veya onaylı VKED değiştirilemez; yeni değerlendirme açın")


DPIAS.before_save = _dpia_rules


def dpia_action(action):
    def handler(c):
        authz.require_human(c.principal)
        authz.check(c.principal, DPIAS, "write")
        d = crud.get(c.db, DPIAS, c.params["id"])
        now = utcnow()
        if action == "submit":
            if d["status"] not in ("draft", "rejected"):
                raise crud.Conflict("VKED taslak değil")
            missing = [label for key, label in (("necessity", "gereklilik ve orantılılık"), ("risks", "riskler"),
                                                ("measures", "önlemler"), ("residual_risk", "artık risk"), ("decision", "karar"))
                       if not d[key]]
            if missing:
                raise crud.Invalid("Onaya göndermeden önce doldurun: " + ", ".join(missing))
            c.db.execute("UPDATE tdr_dpias SET status='in_review', submitted_at=?, review_note=NULL, updated_at=? WHERE id=?",
                         (now, now, d["id"]))
        else:
            if d["status"] != "in_review":
                raise crud.Conflict("Onay bekleyen bir VKED değil")
            if d["prepared_by"] in _me(c.principal):
                raise crud.Forbidden("VKED'yi hazırlayan onaylayamaz (dört göz)")
            if action == "approve":
                c.db.execute("UPDATE tdr_dpias SET status='approved', approver=?, approved_at=?, updated_at=? WHERE id=?",
                             (c.principal.username, now, now, d["id"]))
            else:
                note = (c.body.get("note") or "").strip()
                if len(note) < 5:
                    raise crud.Invalid("İade gerekçesini yazın")
                c.db.execute("UPDATE tdr_dpias SET status='rejected', review_note=?, updated_at=? WHERE id=?", (note, now, d["id"]))
        audit.log(c.db, c.principal, action.upper(), "dpias", d["id"], {"note": c.body.get("note")})
        return crud.get(c.db, DPIAS, d["id"])
    return handler


# ------------------------------------------------------------------ saklama ve periyodik imha

def _disposal_rules(db, data, current, principal):
    if current and principal is not None and current["status"] in ("completed", "cancelled"):
        raise crud.Invalid("Tamamlanan veya iptal edilen imha kaydı değiştirilemez (en az 3 yıl saklanır)")


def _disposal_item_rules(db, data, current, principal):
    run = one(db, "SELECT status FROM tdr_disposal_runs WHERE id=?", ((current or data).get("run_id"),))
    if run and run["status"] in ("completed", "cancelled"):
        raise crud.Invalid("Tamamlanan imha kaydının kalemleri değiştirilemez")
    if principal is not None:
        data["updated_by"] = principal.username
    if data.get("record_count") is not None and data["record_count"] < 0:
        raise crud.Invalid("Kayıt sayısı negatif olamaz")


DISPOSALS.before_save = _disposal_rules
DISPOSAL_ITEMS.before_save = _disposal_item_rules


def disposal_state(db):
    """Son tamamlanan periyodik imha ve bir sonraki son tarih (politikadaki ay aralığı)."""
    months = int(policy(db, "privacy.disposal_interval_months", 6))
    last = one(db, "SELECT id, code, completed_at FROM tdr_disposal_runs WHERE status='completed' ORDER BY completed_at DESC LIMIT 1")
    scope = one(db, """SELECT COUNT(*) AS n FROM tdr_data_tables WHERE status<>'removed' AND retention_rule_id IS NOT NULL""")["n"]
    if last:
        d = date.fromisoformat(_day(last["completed_at"]))
        month = d.month - 1 + months
        y, m = d.year + month // 12, month % 12 + 1
        import calendar
        due = date(y, m, min(d.day, calendar.monthrange(y, m)[1])).isoformat()
    else:
        due = None
    planned = one(db, "SELECT id, code, planned_date, status FROM tdr_disposal_runs WHERE status IN ('planned','in_progress') "
                      "ORDER BY planned_date LIMIT 1")
    return {"interval_months": months, "last": last, "next_due": due, "planned": planned, "tables_in_scope": scope,
            "overdue": bool(scope and due and due < _today()), "unplanned": bool(scope and not last and not planned)}


def disposal_generate(c):
    authz.require_human(c.principal)
    authz.check(c.principal, DISPOSALS, "write")
    run = crud.get(c.db, DISPOSALS, c.params["id"])
    if run["status"] not in ("planned", "in_progress"):
        raise crud.Conflict("Kalem yalnızca açık imha kaydına eklenir")
    added = 0
    for t in rows(c.db, """SELECT t.id, t.retention_rule_id, r.disposal_method FROM tdr_data_tables t JOIN tdr_retention_rules r
            ON r.id=t.retention_rule_id WHERE t.status<>'removed' AND r.active=1"""):
        if not one(c.db, "SELECT 1 AS x FROM tdr_disposal_items WHERE run_id=? AND table_id=?", (run["id"], t["id"])):
            c.db.execute("""INSERT INTO tdr_disposal_items (run_id, table_id, rule_id, method, outcome, updated_by, updated_at)
                VALUES (?,?,?,?,'pending',?,?)""", (run["id"], t["id"], t["retention_rule_id"], t["disposal_method"],
                                                     c.principal.username, utcnow()))
            added += 1
    if run["status"] == "planned":
        c.db.execute("UPDATE tdr_disposal_runs SET status='in_progress', updated_at=? WHERE id=?", (utcnow(), run["id"]))
    audit.log(c.db, c.principal, "GENERATE", "disposal_runs", run["id"], {"added": added})
    return disposal_context(c)


def disposal_complete(c):
    authz.require_human(c.principal)
    authz.check(c.principal, DISPOSALS, "write")
    run = crud.get(c.db, DISPOSALS, c.params["id"])
    if run["status"] not in ("planned", "in_progress"):
        raise crud.Conflict("İmha kaydı açık değil")
    items = rows(c.db, "SELECT outcome FROM tdr_disposal_items WHERE run_id=?", (run["id"],))
    if not items:
        raise crud.Invalid("Önce kapsamdaki tabloları ekleyin")
    if any(i["outcome"] == "pending" for i in items):
        raise crud.Invalid("Bekleyen kalem var: her tablo için sonucu girin")
    summary = (c.body.get("summary") or run["summary"] or "").strip()
    if len(summary) < 10:
        raise crud.Invalid("İmha özetini yazın (ne, hangi yöntemle, kim tarafından imha edildi)")
    now = utcnow()
    c.db.execute("""UPDATE tdr_disposal_runs SET status='completed', summary=?, performed_by=?, completed_at=?, updated_at=?
        WHERE id=?""", (summary, c.principal.username, now, now, run["id"]))
    audit.log(c.db, c.principal, "COMPLETE", "disposal_runs", run["id"], {"items": len(items)})
    return disposal_context(c)


def disposal_context(c):
    authz.check(c.principal, DISPOSALS, "read")
    run = crud.get(c.db, DISPOSALS, c.params["id"])
    run["items"] = rows(c.db, """SELECT i.*, t.schema_name, t.name AS table_name, s.name AS source_name, r.code AS rule_code,
        r.name AS rule_name, r.period_value, r.period_unit, r.trigger_event FROM tdr_disposal_items i
        JOIN tdr_data_tables t ON t.id=i.table_id JOIN tdr_data_sources s ON s.id=t.source_id
        LEFT JOIN tdr_retention_rules r ON r.id=i.rule_id WHERE i.run_id=? ORDER BY s.name, t.name""", (run["id"],))
    run["evidence"] = one(c.db, "SELECT id, code, title FROM tdr_evidence WHERE id=?", (run["evidence_id"],)) if run["evidence_id"] else None
    run["state"] = disposal_state(c.db)
    run["can_edit"] = authz.can_write(c.principal, DISPOSALS) and run["status"] in ("planned", "in_progress")
    return run


# ------------------------------------------------------------------ veri talepleri

def _request_rules(db, data, current, principal):
    if current is None:
        if principal is not None:
            data["requested_by"] = principal.username
            if not data.get("org_unit_id") and principal.role == "UNIT_USER" and len(principal.units) == 1:
                data["org_unit_id"] = next(iter(principal.units))
        table = one(db, "SELECT id FROM tdr_data_tables WHERE id=?", (data.get("table_id"),))
        if not table:
            raise crud.Invalid("Veri tablosu bulunamadı")
        personal = one(db, "SELECT COUNT(*) AS n FROM tdr_data_columns WHERE table_id=? AND status='active' AND "
                           "personal_data IN ('personal','special')", (data["table_id"],))["n"]
        if personal and data.get("kind") in ("access", "extract") and not data.get("activity_id"):
            raise crud.Invalid("Kişisel veri içeren tabloya erişim için işleme faaliyeti (amaç ve hukuki sebep) seçin")
        if data.get("kind") == "access" and not data.get("access_until"):
            raise crud.Invalid("Erişim talebinde bitiş tarihi zorunlu")
        if data.get("access_until") and _day(data["access_until"]) < _today():
            raise crud.Invalid("Erişim bitiş tarihi geçmiş olamaz")
    elif principal is not None and current["status"] != "requested":
        raise crud.Invalid("Sonuçlanan talep değiştirilemez")


REQUESTS.before_save = _request_rules


def _table_people(db, table_id):
    t = crud.get(db, TABLES, table_id)
    _, eff = _effective(db, t)
    return eff


def request_action(action):
    def handler(c):
        authz.require_human(c.principal)
        r = crud.get(c.db, REQUESTS, c.params["id"])
        me, now = _me(c.principal), utcnow()
        eff = _table_people(c.db, r["table_id"])
        note = (c.body.get("note") or "").strip()
        if action in ("approve", "reject"):
            if r["status"] != "requested":
                raise crud.Conflict("Talep onay beklemiyor")
            if r["requested_by"] in me:
                raise crud.Forbidden("Talep eden kendi talebini onaylayamaz")
            if not (c.principal.can("manage") or (eff["owner"] and eff["owner"] in me)):
                raise crud.Forbidden(f"Talebi verinin sahibi ({eff['owner'] or 'atanmamış'}) veya veri yönetişimi yöneticisi onaylar")
            if action == "reject" and len(note) < 5:
                raise crud.Invalid("Ret gerekçesini yazın")
            c.db.execute("UPDATE tdr_data_requests SET status=?, approver=?, decided_at=?, decision_note=?, updated_at=? WHERE id=?",
                         ("approved" if action == "approve" else "rejected", c.principal.username, now, note or None, now, r["id"]))
            if r["requested_by"]:
                _notify(c.db, "data_request.decided", f"Veri talebi {'onaylandı' if action == 'approve' else 'reddedildi'}: {r['code']}",
                        note, users=[r["requested_by"]], link=f"#/r/data_requests/{r['id']}", object_type="data_requests", object_id=r["id"])
        elif action == "fulfill":
            if r["status"] != "approved":
                raise crud.Conflict("Yalnızca onaylı talep uygulanır")
            if not (c.principal.can("manage") or (eff["custodian"] and eff["custodian"] in me)):
                raise crud.Forbidden(f"Talebi teknik sorumlu ({eff['custodian'] or 'atanmamış'}) veya veri yönetişimi yöneticisi uygular")
            if len(note) < 5:
                raise crud.Invalid("Uygulamayı kısaca açıklayın (ör. maskeleme yöntemi, verilen yetki)")
            c.db.execute("""UPDATE tdr_data_requests SET status='fulfilled', fulfilled_by=?, fulfilled_at=?, fulfillment_note=?,
                updated_at=? WHERE id=?""", (c.principal.username, now, note, now, r["id"]))
        elif action == "cancel":
            if r["status"] not in ("requested", "approved"):
                raise crud.Conflict("Talep iptal edilemez")
            if r["requested_by"] not in me and not c.principal.can("manage"):
                raise crud.Forbidden("Talebi yalnızca talep eden iptal eder")
            c.db.execute("UPDATE tdr_data_requests SET status='cancelled', decision_note=?, updated_at=? WHERE id=?",
                         (note or None, now, r["id"]))
        audit.log(c.db, c.principal, action.upper(), "data_requests", r["id"], {"note": note})
        return request_context(c)
    return handler


def request_context(c):
    authz.check(c.principal, REQUESTS, "read")
    r = crud.get(c.db, REQUESTS, c.params["id"])
    t = crud.get(c.db, TABLES, r["table_id"])
    source, eff = _effective(c.db, t)
    r["table"] = {"id": t["id"], "name": _qualified(t["schema_name"], t["name"]), "source": source["name"]}
    r["people"] = {k: eff[k] for k in ("owner", "steward", "custodian")}
    r["columns"] = rows(c.db, """SELECT c.id, c.name, c.personal_data FROM tdr_data_request_columns m
        JOIN tdr_data_columns c ON c.id=m.column_id WHERE m.request_id=? ORDER BY c.name""", (r["id"],))
    r["personal_columns"] = rows(c.db, """SELECT id, name, personal_data FROM tdr_data_columns WHERE table_id=? AND status='active'
        AND personal_data IN ('personal','special') ORDER BY name""", (t["id"],))
    r["activity"] = one(c.db, "SELECT id, code, name, legal_basis FROM tdr_processing_activities WHERE id=?", (r["activity_id"],)) \
        if r["activity_id"] else None
    me = _me(c.principal)
    owner_ok = c.principal.can("manage") or bool(eff["owner"] and eff["owner"] in me)
    r["can"] = {"decide": r["status"] == "requested" and r["requested_by"] not in me and owner_ok,
                "fulfill": r["status"] == "approved" and (c.principal.can("manage") or bool(eff["custodian"] and eff["custodian"] in me)),
                "cancel": r["status"] in ("requested", "approved") and (r["requested_by"] in me or c.principal.can("manage"))}
    return r


def request_columns(c):
    r = crud.get(c.db, REQUESTS, c.params["id"])
    if r["requested_by"] not in _me(c.principal) and not c.principal.can("manage"):
        raise crud.Forbidden("Kolonları talep eden belirler")
    if r["status"] != "requested":
        raise crud.Conflict("Sonuçlanan talep değiştirilemez")
    ids = _ids(c.body.get("column_ids"), "Kolon")
    if ids and len(rows(c.db, f"SELECT id FROM tdr_data_columns WHERE table_id=? AND id IN ({','.join('?' * len(ids))})",
                        [r["table_id"], *ids])) != len(ids):
        raise crud.Invalid("Kolonlar talep edilen tabloya ait olmalı")
    c.db.execute("DELETE FROM tdr_data_request_columns WHERE request_id=?", (r["id"],))
    for cid in ids:
        c.db.execute("INSERT INTO tdr_data_request_columns (request_id, column_id) VALUES (?,?)", (r["id"], cid))
    audit.log(c.db, c.principal, "LINK", "data_requests", r["id"], {"columns": ids})
    return request_context(c)


# ------------------------------------------------------------------ ilgili kişi başvuruları

def _subject_rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if current is None and principal is not None:
        data["created_by"] = principal.username
    if "received_on" in data or current is None:
        received = _day(merged.get("received_on"))
        if received and received > _today():
            raise crud.Invalid("Başvuru tarihi gelecekte olamaz")
        days = int(policy(db, "privacy.subject_request_days", 30))
        data["due_date"] = (date.fromisoformat(received) + timedelta(days=days)).isoformat()
    if merged.get("status") in ("answered", "rejected"):
        if not merged.get("response_date") or not merged.get("response_summary"):
            raise crud.Invalid("Yanıt tarihi ve yanıt özeti olmadan başvuru kapatılamaz")
        if _day(merged["response_date"]) < _day(merged["received_on"]):
            raise crud.Invalid("Yanıt tarihi başvuru tarihinden önce olamaz")
        if merged.get("request_type") in ("access", "erasure", "rectification") and not merged.get("identity_verified") \
                and merged.get("status") == "answered":
            raise crud.Invalid("Kimlik doğrulanmadan bu başvuru yanıtlanamaz (kişisel veri yanlış kişiye verilmesin)")


SUBJECT_REQUESTS.before_save = _subject_rules


def subject_state(record):
    due = _day(record["due_date"])
    closed = record["status"] in ("answered", "rejected")
    end = _day(record["response_date"]) if closed else _today()
    remaining = (date.fromisoformat(due) - date.fromisoformat(_today())).days if due and not closed else None
    return {"late": bool(due and end and end > due), "remaining_days": remaining}


def subject_context(c):
    authz.check(c.principal, SUBJECT_REQUESTS, "read")
    r = crud.get(c.db, SUBJECT_REQUESTS, c.params["id"])
    r.update(subject_state(r))
    r["tables"] = rows(c.db, """SELECT t.id, t.schema_name, t.name, s.name AS source_name FROM tdr_subject_request_tables m
        JOIN tdr_data_tables t ON t.id=m.table_id JOIN tdr_data_sources s ON s.id=t.source_id WHERE m.request_id=?
        ORDER BY s.name, t.name""", (r["id"],))
    return r


def subject_tables(c):
    authz.require_human(c.principal)
    authz.check(c.principal, SUBJECT_REQUESTS, "write")
    r = crud.get(c.db, SUBJECT_REQUESTS, c.params["id"])
    ids = _ids(c.body.get("table_ids"), "Tablo")
    c.db.execute("DELETE FROM tdr_subject_request_tables WHERE request_id=?", (r["id"],))
    for tid in ids:
        crud.get(c.db, TABLES, tid)
        c.db.execute("INSERT INTO tdr_subject_request_tables (request_id, table_id) VALUES (?,?)", (r["id"], tid))
    audit.log(c.db, c.principal, "LINK", "subject_requests", r["id"], {"tables": ids})
    return subject_context(c)


def subject_suggest_tables(c):
    """Başvuru türüne ve ilgili kişi grubuna göre bakılması gereken tablolar: grubu içeren faaliyetlerin tabloları."""
    authz.check(c.principal, SUBJECT_REQUESTS, "read")
    r = crud.get(c.db, SUBJECT_REQUESTS, c.params["id"])
    if not r["subject_group_id"]:
        return []
    return rows(c.db, """SELECT DISTINCT t.id, t.schema_name, t.name, s.name AS source_name FROM tdr_processing_subjects ps
        JOIN tdr_processing_activities a ON a.id=ps.activity_id AND a.status<>'retired'
        JOIN tdr_data_tables t ON t.id IN (SELECT table_id FROM tdr_processing_tables WHERE activity_id=a.id
            UNION SELECT c.table_id FROM tdr_processing_columns pc JOIN tdr_data_columns c ON c.id=pc.column_id WHERE pc.activity_id=a.id)
        JOIN tdr_data_sources s ON s.id=t.source_id WHERE ps.subject_group_id=? AND t.status<>'removed' ORDER BY s.name, t.name""",
                (r["subject_group_id"],))


# ------------------------------------------------------------------ veri varlığı risk puanı

def _volume_score(db, row_count, personal):
    if row_count is None:
        return 3 if personal else 2
    buckets = policy(db, "privacy.risk_volume_buckets", [1000, 100000, 1000000, 10000000])
    return 1 + sum(1 for b in buckets if row_count >= b)


def table_risks(db, table_ids=None):
    """Tablo başına risk puanı: etki = (2 × hassasiyet + hacim) / 3, olasılık = 1 + yönetişim açıkları (en çok 5)."""
    from .risks import level_of
    where, args = ["t.status<>'removed'"], []
    if table_ids is not None:
        if not table_ids:
            return {}
        where.append(f"t.id IN ({','.join('?' * len(table_ids))})")
        args += list(table_ids)
    tables = rows(db, f"""SELECT t.id, t.name, t.schema_name, t.row_count, t.classification, t.retention_rule_id, s.name AS source_name,
        COALESCE(t.owner, d.owner, pd.owner, s.owner) AS eff_owner FROM tdr_data_tables t JOIN tdr_data_sources s ON s.id=t.source_id
        {EFFECTIVE} WHERE {' AND '.join(where)}""", args)
    if not tables:
        return {}
    ids = [t["id"] for t in tables]
    marks = ",".join("?" * len(ids))
    colstats = {r["table_id"]: r for r in rows(db, f"""SELECT table_id,
        SUM(CASE WHEN personal_data='special' THEN 1 ELSE 0 END) AS special,
        SUM(CASE WHEN personal_data IN ('personal','special') THEN 1 ELSE 0 END) AS personal,
        SUM(CASE WHEN is_critical=1 THEN 1 ELSE 0 END) AS critical,
        SUM(CASE WHEN classification IN ('confidential','restricted') THEN 1 ELSE 0 END) AS classified
        FROM tdr_data_columns WHERE status='active' AND table_id IN ({marks}) GROUP BY table_id""", ids)}
    low_class = {r["table_id"] for r in rows(db, f"""SELECT DISTINCT c.table_id FROM tdr_data_columns c JOIN tdr_data_tables t
        ON t.id=c.table_id WHERE c.status='active' AND c.personal_data IN ('personal','special') AND
        COALESCE(c.classification, t.classification, 'public') IN ('public','internal') AND c.table_id IN ({marks})""", ids)}
    covered = {r["table_id"] for r in rows(db, f"""SELECT table_id FROM tdr_processing_tables WHERE table_id IN ({marks})
        UNION SELECT c.table_id FROM tdr_processing_columns pc JOIN tdr_data_columns c ON c.id=pc.column_id
        WHERE c.table_id IN ({marks})""", ids + ids)}
    activity_rule = {r["table_id"] for r in rows(db, f"""SELECT pt.table_id FROM tdr_processing_tables pt JOIN tdr_processing_activities a
        ON a.id=pt.activity_id WHERE a.retention_rule_id IS NOT NULL AND pt.table_id IN ({marks})""", ids)}
    no_dpa = {r["table_id"] for r in rows(db, f"""SELECT DISTINCT pt.table_id FROM tdr_processing_tables pt
        JOIN tdr_processing_processors p ON p.activity_id=pt.activity_id WHERE p.dpa_signed=0 AND p.role='processor'
        AND pt.table_id IN ({marks})""", ids)}
    bad_transfer = {r["table_id"] for r in rows(db, f"""SELECT DISTINCT pt.table_id FROM tdr_processing_tables pt
        JOIN tdr_processing_activities a ON a.id=pt.activity_id WHERE a.foreign_transfer=1 AND
        (a.transfer_mechanism IS NULL OR a.transfer_mechanism='none') AND pt.table_id IN ({marks})""", ids)}
    out = {}
    for t in tables:
        st = colstats.get(t["id"]) or {"special": 0, "personal": 0, "critical": 0, "classified": 0}
        personal = (st["personal"] or 0) > 0
        if st["special"]:
            sensitivity, why = 5, "özel nitelikli kişisel veri"
        elif personal and (st["critical"] or t["classification"] == "restricted"):
            sensitivity, why = 4, "kritik veya çok gizli kişisel veri"
        elif personal:
            sensitivity, why = 3, "kişisel veri"
        elif st["classified"] or t["classification"] in ("confidential", "restricted"):
            sensitivity, why = 2, "gizli veri"
        else:
            sensitivity, why = 1, "kişisel veya gizli veri işaretli değil"
        volume = _volume_score(db, t["row_count"], personal)
        impact = max(1, min(5, round((2 * sensitivity + volume) / 3)))
        factors = [f"Hassasiyet {sensitivity}/5: {why}",
                   f"Hacim {volume}/5: " + (f"{t['row_count']:,} satır".replace(",", ".") if t["row_count"] is not None else "satır sayısı bilinmiyor")]
        gaps = []
        if not t["eff_owner"]:
            gaps.append("veri sahibi yok")
        if personal:
            if t["id"] not in covered:
                gaps.append("işleme envanterinde değil")
            if t["id"] in low_class:
                gaps.append("kişisel veri 'Gizli' sınıfın altında")
            if not t["retention_rule_id"] and t["id"] not in activity_rule:
                gaps.append("saklama süresi yok")
            if t["id"] in no_dpa:
                gaps.append("veri işleyenle sözleşme (DPA) yok")
            if t["id"] in bad_transfer:
                gaps.append("yurt dışı aktarım mekanizmasız")
        likelihood = min(5, 1 + len(gaps))
        score = impact * likelihood
        out[t["id"]] = {"table_id": t["id"], "table": _qualified(t["schema_name"], t["name"]), "source_name": t["source_name"],
                        "impact": impact, "likelihood": likelihood, "score": score, "level": level_of(db, score),
                        "personal": personal, "special": bool(st["special"]), "factors": factors, "gaps": gaps}
    return out


def table_risk(c):
    authz.check(c.principal, TABLES, "read")
    t = crud.get(c.db, TABLES, c.params["id"])
    result = table_risks(c.db, [t["id"]])[t["id"]]
    result["risks"] = rows(c.db, """SELECT r.id, r.code, r.title, r.status, r.risk_level FROM tdr_risk_data_tables m
        JOIN tdr_supplier_risks r ON r.id=m.risk_id WHERE m.table_id=? ORDER BY r.id DESC""", (t["id"],)) \
        if c.app.enabled("risks") else []
    result["activities"] = rows(c.db, """SELECT DISTINCT a.id, a.code, a.name, a.status FROM tdr_processing_activities a WHERE
        a.id IN (SELECT activity_id FROM tdr_processing_tables WHERE table_id=?) OR a.id IN (SELECT pc.activity_id FROM
        tdr_processing_columns pc JOIN tdr_data_columns c ON c.id=pc.column_id WHERE c.table_id=?) ORDER BY a.code""",
                                (t["id"], t["id"]))
    result["retention_rule"] = one(c.db, "SELECT id, code, name, period_value, period_unit, trigger_event FROM tdr_retention_rules "
                                         "WHERE id=?", (t["retention_rule_id"],)) if t.get("retention_rule_id") else None
    result["suggestions"] = one(c.db, """SELECT COUNT(*) AS n FROM tdr_pii_suggestions s JOIN tdr_data_columns c ON c.id=s.column_id
        WHERE c.table_id=? AND s.status='pending'""", (t["id"],))["n"]
    result["column_categories"] = rows(c.db, """SELECT cc.column_id, k.id, k.name, k.special FROM tdr_column_categories cc
        JOIN tdr_personal_data_categories k ON k.id=cc.category_id JOIN tdr_data_columns c ON c.id=cc.column_id
        WHERE c.table_id=? ORDER BY k.name""", (t["id"],))
    return result


def raise_risk(c):
    """Veri varlığı riskini kurumsal risk kaydına aktarır (tablo başına bir açık risk)."""
    if not c.app.enabled("risks"):
        raise crud.Invalid("Risk modülü kapalı")
    risks = RESOURCES["supplier_risks"]
    authz.require_human(c.principal)
    authz.check(c.principal, risks, "write")
    t = crud.get(c.db, TABLES, c.params["id"])
    existing = one(c.db, """SELECT r.id, r.code FROM tdr_risk_data_tables m JOIN tdr_supplier_risks r ON r.id=m.risk_id
        WHERE m.table_id=? AND r.status<>'closed'""", (t["id"],))
    if existing:
        raise crud.Conflict(f"Bu veri varlığı için açık risk var: {existing['code']}")
    score = table_risks(c.db, [t["id"]])[t["id"]]
    source, eff = _effective(c.db, t)
    domain = eff["domain"]
    unit = domain["org_unit_id"] if domain else None
    name = _qualified(t["schema_name"], t["name"])
    risk_id = crud.insert(c.db, risks, {
        "title": f"Veri varlığı riski: {source['name']} / {name}", "category": "privacy",
        "owner": eff["owner"] or c.principal.username, "likelihood": score["likelihood"], "impact": score["impact"],
        "cause": "Yönetişim açıkları: " + (", ".join(score["gaps"]) or "yok"),
        "risk_event": f"{name} tablosundaki verinin yetkisiz erişim, ifşa veya mevzuata aykırı işlenmesi",
        "consequence": "; ".join(score["factors"]), "org_unit_id": unit, "entity_name": source["name"]}, None)
    c.db.execute("INSERT INTO tdr_risk_data_tables (risk_id, table_id, created_at) VALUES (?,?,?)", (risk_id, t["id"], utcnow()))
    audit.log(c.db, c.principal, "RAISE_RISK", "data_tables", t["id"], {"risk_id": risk_id, "score": score["score"]})
    return {"risk_id": risk_id, "code": crud.get(c.db, risks, risk_id)["code"]}


# ------------------------------------------------------------------ KVKK ihlali ↔ veri varlıkları

def breach_assets(c):
    breach = crud.get(c.db, RESOURCES["privacy_breaches"], c.params["id"])
    authz.check(c.principal, RESOURCES["privacy_breaches"], "read")
    tables = rows(c.db, """SELECT t.id, t.schema_name, t.name, t.row_count, s.name AS source_name FROM tdr_breach_data_tables m
        JOIN tdr_data_tables t ON t.id=m.table_id JOIN tdr_data_sources s ON s.id=t.source_id WHERE m.breach_id=?
        ORDER BY s.name, t.name""", (breach["id"],))
    ids = [t["id"] for t in tables]
    cats, groups = [], []
    if ids:
        marks = ",".join("?" * len(ids))
        cats = rows(c.db, f"""SELECT DISTINCT k.id, k.name, k.special FROM tdr_column_categories cc
            JOIN tdr_personal_data_categories k ON k.id=cc.category_id JOIN tdr_data_columns c ON c.id=cc.column_id
            WHERE c.table_id IN ({marks}) AND c.status='active' ORDER BY k.name""", ids)
        groups = rows(c.db, f"""SELECT DISTINCT g.id, g.name FROM tdr_processing_subjects ps JOIN tdr_data_subject_groups g
            ON g.id=ps.subject_group_id WHERE ps.activity_id IN (SELECT activity_id FROM tdr_processing_tables WHERE table_id IN
            ({marks}) UNION SELECT pc.activity_id FROM tdr_processing_columns pc JOIN tdr_data_columns c ON c.id=pc.column_id
            WHERE c.table_id IN ({marks})) ORDER BY g.name""", ids + ids)
    rowsum = sum(t["row_count"] or 0 for t in tables)
    return {"tables": tables, "categories": cats, "special": any(k["special"] for k in cats), "subject_groups": groups,
            "max_rows": max([t["row_count"] or 0 for t in tables] or [0]), "total_rows": rowsum,
            "can_edit": authz.can_write(c.principal, RESOURCES["privacy_breaches"]) and c.principal.auth_type != "api_key"}


def breach_assets_set(c):
    authz.require_human(c.principal)
    breaches = RESOURCES["privacy_breaches"]
    authz.check(c.principal, breaches, "write")
    breach = crud.get(c.db, breaches, c.params["id"])
    ids = _ids(c.body.get("table_ids"), "Tablo")
    c.db.execute("DELETE FROM tdr_breach_data_tables WHERE breach_id=?", (breach["id"],))
    for tid in ids:
        crud.get(c.db, TABLES, tid)
        c.db.execute("INSERT INTO tdr_breach_data_tables (breach_id, table_id, created_by, created_at) VALUES (?,?,?,?)",
                     (breach["id"], tid, c.principal.username, utcnow()))
    audit.log(c.db, c.principal, "LINK", "privacy_breaches", breach["id"], {"data_tables": ids})
    return breach_assets(c)


# ------------------------------------------------------------------ KVKK panosu

def privacy_overview(c):
    authz.check(c.principal, TABLES, "read")
    db = c.db
    pc = one(db, """SELECT SUM(CASE WHEN c.personal_data IN ('personal','special') THEN 1 ELSE 0 END) AS personal,
        SUM(CASE WHEN c.personal_data='special' THEN 1 ELSE 0 END) AS special,
        SUM(CASE WHEN c.personal_data IS NULL THEN 1 ELSE 0 END) AS unassessed, COUNT(*) AS columns
        FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id WHERE c.status='active' AND t.status<>'removed'""")
    uncovered = rows(db, """SELECT c.id, c.name, c.personal_data, t.id AS table_id, t.schema_name, t.name AS table_name,
        s.name AS source_name FROM tdr_data_columns c JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources s
        ON s.id=t.source_id WHERE c.status='active' AND t.status<>'removed' AND c.personal_data IN ('personal','special')
        AND c.id NOT IN (SELECT column_id FROM tdr_processing_columns) AND c.table_id NOT IN (SELECT table_id FROM
        tdr_processing_tables) ORDER BY s.name, t.name, c.name LIMIT 500""")
    matrix = rows(db, """SELECT k.id AS category_id, k.name AS category, k.special, s.id AS source_id, s.name AS source,
        COUNT(DISTINCT cc.column_id) AS n FROM tdr_column_categories cc JOIN tdr_personal_data_categories k ON k.id=cc.category_id
        JOIN tdr_data_columns c ON c.id=cc.column_id JOIN tdr_data_tables t ON t.id=c.table_id JOIN tdr_data_sources s
        ON s.id=t.source_id WHERE c.status='active' AND t.status<>'removed' GROUP BY k.id, k.name, k.special, s.id, s.name""")
    activities = []
    for a in rows(db, "SELECT * FROM tdr_processing_activities WHERE status<>'retired' ORDER BY code"):
        gaps = activity_gaps(db, a)
        activities.append({"id": a["id"], "code": a["code"], "name": a["name"], "status": a["status"], "gaps": gaps,
                           "high": sum(1 for g in gaps if g["severity"] == "high")})
    risks = sorted((r for r in table_risks(db).values() if r["personal"]), key=lambda r: (-r["score"], r["table"]))[:10]
    subjects = []
    if _can_read(c.principal, SUBJECT_REQUESTS):
        for r in rows(db, "SELECT * FROM tdr_subject_requests WHERE status IN ('received','in_progress') ORDER BY due_date"):
            subjects.append({k: r[k] for k in ("id", "code", "request_type", "owner", "received_on", "due_date", "status")}
                            | subject_state(r))
    requests = rows(db, """SELECT r.id, r.code, r.kind, r.status, r.requested_by, t.name AS table_name FROM tdr_data_requests r
        JOIN tdr_data_tables t ON t.id=r.table_id WHERE r.status IN ('requested','approved') ORDER BY r.id""")
    return {
        "columns": {"personal": pc["personal"] or 0, "special": pc["special"] or 0, "unassessed": pc["unassessed"] or 0,
                    "total": pc["columns"] or 0, "uncovered": len(uncovered)},
        "uncovered": uncovered[:50], "matrix": matrix, "activities": activities, "risks": risks,
        "suggestions": one(db, "SELECT COUNT(*) AS n FROM tdr_pii_suggestions WHERE status='pending'")["n"],
        "subject_requests": subjects, "data_requests": requests, "disposal": disposal_state(db),
        "dpias_pending": one(db, "SELECT COUNT(*) AS n FROM tdr_dpias WHERE status='in_review'")["n"],
    }


def risk_list(c):
    authz.check(c.principal, TABLES, "read")
    items = sorted(table_risks(c.db).values(), key=lambda r: (-r["score"], r["table"]))
    if c.query.get("personal") == "1":
        items = [r for r in items if r["personal"]]
    return {"items": items[:200], "total": len(items)}


# ------------------------------------------------------------------ İşlerim, takvim, sağlık kontrolü, hatırlatma

def my_work_items(db, principal):
    me = _me(principal)
    names = sorted(me)
    marks = ",".join("?" * len(names))
    out = {}
    pending = rows(db, "SELECT * FROM tdr_data_requests WHERE status IN ('requested','approved') ORDER BY id")
    to_decide, to_fulfill = [], []
    for r in pending:
        eff = _table_people(db, r["table_id"])
        item = {"id": r["id"], "code": r["code"], "title": f"{_label('data_requests', 'kind', r['kind'])}: {r['purpose'][:80]}",
                "requested_by": r["requested_by"]}
        if r["status"] == "requested" and r["requested_by"] not in me and (eff["owner"] in me or (principal.can("manage") and not eff["owner"])):
            to_decide.append(item)
        if r["status"] == "approved" and (eff["custodian"] in me or (principal.can("manage") and not eff["custodian"])):
            to_fulfill.append(item)
    out["data_requests_to_approve"], out["data_requests_to_fulfill"] = to_decide, to_fulfill
    if principal.role in PRIVACY_ROLES:
        out["subject_requests"] = rows(db, f"""SELECT id, code, request_type AS title, due_date FROM tdr_subject_requests
            WHERE owner IN ({marks}) AND status IN ('received','in_progress') ORDER BY due_date""", names)
        out["dpias_to_approve"] = rows(db, f"""SELECT id, code, title FROM tdr_dpias WHERE status='in_review'
            AND COALESCE(prepared_by,'') NOT IN ({marks})""", names)
    out["disposals"] = rows(db, f"""SELECT id, code, title, planned_date AS due_date FROM tdr_disposal_runs WHERE owner IN ({marks})
        AND status IN ('planned','in_progress') ORDER BY planned_date""", names)
    if principal.can("manage"):
        n = one(db, "SELECT COUNT(*) AS n FROM tdr_pii_suggestions WHERE status='pending'")["n"]
        out["pii_suggestions"] = [{"id": 0, "code": "", "title": f"{n} kişisel veri önerisi karar bekliyor"}] if n else []
    return out


def calendar_events(db, add, readable):
    for r in rows(db, "SELECT id, code, title, planned_date, status FROM tdr_disposal_runs WHERE status IN ('planned','in_progress')"):
        add("disposal", f"{r['code']} {r['title']}", r["planned_date"], None, "disposal_runs", r["id"], r["status"])
    st = disposal_state(db)
    if st["next_due"] and st["last"]:
        add("disposal", f"Periyodik imha son tarihi (son: {st['last']['code']})", st["next_due"], None, "disposal_runs",
            st["last"]["id"], "due")
    if readable("subject_requests"):
        for r in rows(db, "SELECT id, code, request_type, due_date, status FROM tdr_subject_requests WHERE status IN "
                          "('received','in_progress')"):
            add("subject_request", f"{r['code']} {_label('subject_requests', 'request_type', r['request_type'])}", r["due_date"],
                None, "subject_requests", r["id"], r["status"])
    for r in rows(db, "SELECT id, code, name, review_date FROM tdr_processing_activities WHERE status='active' AND review_date IS NOT NULL"):
        add("activity_review", f"{r['code']} {r['name']}", r["review_date"], None, "processing_activities", r["id"], "active")


def health_checks(db, check, count, readable):
    personal = count(db, "SELECT COUNT(*) AS n FROM tdr_data_columns WHERE status='active' AND personal_data IN ('personal','special')")
    out = [
        check("personal_not_in_inventory", "İşleme envanterinde olmayan kişisel veri kolonları",
              "Her kişisel veri bir işleme faaliyetine (amaç, hukuki sebep, saklama süresi) bağlı olmalı (KVKK md. 4, md. 16 VERBİS).",
              "high", rows(db, """SELECT c.id, t.name AS code, c.name AS title FROM tdr_data_columns c JOIN tdr_data_tables t
              ON t.id=c.table_id WHERE c.status='active' AND t.status<>'removed' AND c.personal_data IN ('personal','special')
              AND c.id NOT IN (SELECT column_id FROM tdr_processing_columns) AND c.table_id NOT IN (SELECT table_id FROM
              tdr_processing_tables) ORDER BY t.name, c.name LIMIT 200"""), "data_columns", population=personal),
    ]
    acts = rows(db, "SELECT * FROM tdr_processing_activities WHERE status<>'retired'")
    bad = []
    for a in acts:
        high = [g for g in activity_gaps(db, a) if g["severity"] == "high"]
        if high:
            bad.append({"id": a["id"], "code": a["code"], "title": f"{a['name']} — {high[0]['text']}"})
    out.append(check("activity_gaps", "Yüksek önemli eksiği olan işleme faaliyetleri",
                     "Hukuki sebep, özel nitelikli veri dayanağı, saklama süresi veya yurt dışı aktarım mekanizması eksik.",
                     "high", bad, "processing_activities", population=len(acts)))
    st = disposal_state(db)
    if st["tables_in_scope"]:
        items = []
        if st["overdue"]:
            items.append({"id": st["last"]["id"], "code": st["last"]["code"], "title": f"Son tarih {st['next_due']} geçti"})
        elif st["unplanned"]:
            items.append({"id": 0, "code": "", "title": "Saklama kuralı bağlı tablolar var, periyodik imha hiç planlanmamış"})
        out.append(check("disposal_overdue", "Periyodik imha gecikti veya planlanmadı",
                         f"Yönetmelik gereği periyodik imha en çok {st['interval_months']} ayda bir yapılır.", "high", items,
                         "disposal_runs", population=1))
    if readable("subject_requests"):
        overdue = [r for r in rows(db, "SELECT id, code, request_type AS title, due_date FROM tdr_subject_requests WHERE "
                                       "status IN ('received','in_progress') AND due_date < ?", (_today(),))]
        out.append(check("subject_requests_overdue", "30 günü geçen ilgili kişi başvuruları",
                         "KVKK md. 13: başvuru en geç 30 gün içinde ücretsiz sonuçlandırılır.", "critical", overdue,
                         "subject_requests", population=count(db, "SELECT COUNT(*) AS n FROM tdr_subject_requests")))
    return out


@reminder
def privacy_reminders(db, app):
    if not app.enabled("datagov"):
        return 0
    n = 0
    for r in rows(db, "SELECT * FROM tdr_subject_requests WHERE status IN ('received','in_progress')"):
        st = subject_state(r)
        if st["remaining_days"] is not None and st["remaining_days"] <= 5:
            n += _notify(db, "subject_request.due", f"İlgili kişi başvurusu süresi doluyor: {r['code']}",
                         f"Son gün {_day(r['due_date'])} ({st['remaining_days']} gün).", users=[r["owner"]],
                         link=f"#/r/subject_requests/{r['id']}", object_type="subject_requests", object_id=r["id"],
                         dedupe=f"ikb:{r['id']}:{_today()}")
    return n


def column_privacy(c):
    authz.check(c.principal, COLUMNS, "read")
    col = crud.get(c.db, COLUMNS, c.params["id"])
    return {
        "categories": rows(c.db, """SELECT k.id, k.name, k.special, cc.source FROM tdr_column_categories cc
            JOIN tdr_personal_data_categories k ON k.id=cc.category_id WHERE cc.column_id=? ORDER BY k.name""", (col["id"],)),
        "suggestions": rows(c.db, """SELECT s.id, s.confidence, s.method, s.evidence, k.name AS category_name, k.special
            FROM tdr_pii_suggestions s JOIN tdr_personal_data_categories k ON k.id=s.category_id WHERE s.column_id=?
            AND s.status='pending' ORDER BY s.confidence DESC""", (col["id"],)),
        "activities": rows(c.db, """SELECT DISTINCT a.id, a.code, a.name, a.status FROM tdr_processing_activities a WHERE
            a.id IN (SELECT activity_id FROM tdr_processing_columns WHERE column_id=?) OR a.id IN (SELECT activity_id FROM
            tdr_processing_tables WHERE table_id=?) ORDER BY a.code""", (col["id"], col["table_id"])),
    }


def supplier_privacy(c):
    """Tedarikçi 360: tedarikçinin veri işleyen/alıcı olduğu faaliyetler ve barındırdığı veri kaynakları."""
    authz.check(c.principal, ACTIVITIES, "read")
    sid = c.params["id"]
    activities = rows(c.db, """SELECT a.id, a.code, a.name, a.status, a.foreign_transfer, a.transfer_countries, p.role, p.dpa_signed
        FROM tdr_processing_processors p JOIN tdr_processing_activities a ON a.id=p.activity_id WHERE p.supplier_id=?
        ORDER BY a.code""", (sid,))
    for a in activities:
        a["categories"] = [k["name"] for k in activity_categories(c.db, a["id"])]
    sources = rows(c.db, "SELECT id, code, name, platform FROM tdr_data_sources WHERE supplier_id=? ORDER BY name", (sid,))
    return {"activities": activities, "sources": sources,
            "missing_dpa": sum(1 for a in activities if a["role"] == "processor" and not a["dpa_signed"])}


# ------------------------------------------------------------------ kayıt

def register(app):
    app.route("GET", API + "/datagov/privacy", privacy_overview)
    app.route("GET", API + "/datagov/risk", risk_list)
    app.route("POST", API + "/datagov/discovery/run", discovery_run)
    app.route("GET", API + "/datagov/discovery", suggestion_list)
    app.route("POST", API + "/datagov/discovery/bulk", suggestion_bulk)
    app.route("POST", API + "/pii_suggestions/{id}/accept", suggestion_accept)
    app.route("POST", API + "/pii_suggestions/{id}/reject", suggestion_reject)
    app.route("POST", API + "/data_tables/{id}/sample-stats", sample_stats)
    app.route("GET", API + "/data_tables/{id}/risk", table_risk)
    app.route("POST", API + "/data_tables/{id}/raise-risk", raise_risk)
    app.route("POST", API + "/data_columns/{id}/categories", column_categories)
    app.route("GET", API + "/data_columns/{id}/privacy", column_privacy)
    app.route("GET", API + "/suppliers/{id}/privacy", supplier_privacy)
    app.route("GET", API + "/processing_activities/{id}/context", activity_context)
    app.route("POST", API + "/processing_activities/{id}/links", activity_links)
    app.route("POST", API + "/processing_activities/{id}/adopt-categories", adopt_observed)
    app.route("GET", API + "/datagov/verbis-export", verbis_export)
    for action in ("submit", "approve", "reject"):
        app.route("POST", f"{API}/dpias/{{id}}/{action}", dpia_action(action))
    app.route("GET", API + "/disposal_runs/{id}/context", disposal_context)
    app.route("POST", API + "/disposal_runs/{id}/generate", disposal_generate)
    app.route("POST", API + "/disposal_runs/{id}/complete", disposal_complete)
    for action in ("approve", "reject", "fulfill", "cancel"):
        app.route("POST", f"{API}/data_requests/{{id}}/{action}", request_action(action))
    app.route("GET", API + "/data_requests/{id}/context", request_context)
    app.route("POST", API + "/data_requests/{id}/columns", request_columns)
    app.route("GET", API + "/subject_requests/{id}/context", subject_context)
    app.route("POST", API + "/subject_requests/{id}/tables", subject_tables)
    app.route("GET", API + "/subject_requests/{id}/suggest-tables", subject_suggest_tables)
    if app.enabled("risks"):
        app.route("GET", API + "/privacy_breaches/{id}/data-assets", breach_assets)
        app.route("POST", API + "/privacy_breaches/{id}/data-assets", breach_assets_set)
