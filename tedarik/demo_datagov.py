"""Demo verisinin veri yönetişimi bölümü (K-028). Tüm veriler sentetiktir: tablo ve alan adları ürünlerin yaygın standart
adlarıdır (SAP DD03L, ServiceNow sys_dictionary, Dataverse EntityDefinitions), açıklamalar ve iş tanımları demo için
yazılmıştır; hiçbir gerçek kayıt içerilmez. Kaynaklar gerçek içe aktarım hattından (datagov.parse_catalog ve
apply_structure) geçirilir; böylece demo, ekranlarla birlikte içe aktarımı da sınar. İkinci SAP yüklemesi şema
değişikliği geçmişi üretir."""
import json

from .auth import Principal
from .db import one, utcnow

ADMIN = Principal("selin.aydin", "ADMIN", "system", "Selin Aydın")

DOMAINS = [  # ad, birim adı, sahip, veri yöneticisi, üst alan, açıklama
    ("Müşteri", "Müşteri Hizmetleri", "zeynep.demir", "deniz.koc", None, "Müşteri kimliği, iletişim ve ilişki verileri."),
    ("Satış ve Sipariş", "Operasyon", "kerem.aksoy", "deniz.koc", None, "Satış belgeleri, fiyatlar ve satış analitiği."),
    ("Ürün ve Malzeme", None, None, None, "Satış ve Sipariş", "Malzeme ana verisi ve ürün hiyerarşisi; sahiplik üst alandan devralınır."),
    ("Finans", "Finans", "Ayla Çetin", "selin.aydin", None, "Muhasebe belgeleri, şirket kodları ve finansal raporlama verisi."),
    ("BT Hizmet Yönetimi", "BT Altyapı ve Operasyon", "mehmet.kaya", "kerem.aksoy", None, "Olay, problem, değişiklik ve CMDB verileri."),
    ("İnsan Kaynakları", "İnsan Kaynakları", "Nazlı Er", None, None, "Çalışan kişisel ve özlük verileri."),
]

# SAP ABAP sözlüğü (DD03L + DD02T + DD04T) — tablo: (açıklama, [(alan, tip, uzunluk, ondalık, anahtar, kontrol tablosu, metin)])
SAP = {
    "KNA1": ("Genel müşteri ana verileri", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("KUNNR", "CHAR", 10, 0, "X", "", "Müşteri"),
        ("LAND1", "CHAR", 3, 0, "", "T005", "Ülke anahtarı"), ("NAME1", "CHAR", 35, 0, "", "", "Ad 1"),
        ("NAME2", "CHAR", 35, 0, "", "", "Ad 2"), ("ORT01", "CHAR", 35, 0, "", "", "Kent"),
        ("PSTLZ", "CHAR", 10, 0, "", "", "Posta kodu"), ("STRAS", "CHAR", 35, 0, "", "", "Sokak ve konut numarası"),
        ("TELF1", "CHAR", 16, 0, "", "", "Telefon 1"), ("STCD1", "CHAR", 16, 0, "", "", "Vergi numarası 1"),
        ("STCD2", "CHAR", 11, 0, "", "", "Vergi numarası 2"), ("ERDAT", "DATS", 8, 0, "", "", "Yaratma tarihi"),
        ("KTOKD", "CHAR", 4, 0, "", "T077D", "Müşteri hesap grubu"), ("LOEVM", "CHAR", 1, 0, "", "", "Merkezi silme işareti")]),
    "KNVV": ("Müşteri ana verileri: satış verileri", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("KUNNR", "CHAR", 10, 0, "X", "KNA1", "Müşteri"),
        ("VKORG", "CHAR", 4, 0, "X", "TVKO", "Satış organizasyonu"), ("VTWEG", "CHAR", 2, 0, "X", "TVTW", "Dağıtım kanalı"),
        ("SPART", "CHAR", 2, 0, "X", "TSPA", "Bölüm"), ("KDGRP", "CHAR", 2, 0, "", "T151", "Müşteri grubu"),
        ("WAERS", "CUKY", 5, 0, "", "TCURC", "Para birimi"), ("ZTERM", "CHAR", 4, 0, "", "", "Ödeme koşulu anahtarı")]),
    "VBAK": ("Satış belgesi: başlık verileri", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("VBELN", "CHAR", 10, 0, "X", "", "Satış belgesi"),
        ("ERDAT", "DATS", 8, 0, "", "", "Yaratma tarihi"), ("AUART", "CHAR", 4, 0, "", "TVAK", "Satış belgesi türü"),
        ("VKORG", "CHAR", 4, 0, "", "TVKO", "Satış organizasyonu"), ("KUNNR", "CHAR", 10, 0, "", "KNA1", "Sipariş veren"),
        ("NETWR", "CURR", 15, 2, "", "", "Belge para biriminde net değer"), ("WAERK", "CUKY", 5, 0, "", "TCURC", "Belge para birimi"),
        ("BSTNK", "CHAR", 20, 0, "", "", "Müşteri satınalma siparişi numarası")]),
    "VBAP": ("Satış belgesi: kalem verileri", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("VBELN", "CHAR", 10, 0, "X", "VBAK", "Satış belgesi"),
        ("POSNR", "NUMC", 6, 0, "X", "", "Satış belgesi kalemi"), ("MATNR", "CHAR", 40, 0, "", "MARA", "Malzeme numarası"),
        ("ARKTX", "CHAR", 40, 0, "", "", "Satış siparişi kalemi için kısa metin"), ("KWMENG", "QUAN", 15, 3, "", "", "Kümülatif sipariş miktarı"),
        ("NETWR", "CURR", 15, 2, "", "", "Belge para biriminde net değer"), ("WERKS", "CHAR", 4, 0, "", "T001W", "Üretim yeri")]),
    "MARA": ("Genel malzeme verileri", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("MATNR", "CHAR", 40, 0, "X", "", "Malzeme numarası"),
        ("ERSDA", "DATS", 8, 0, "", "", "Yaratma tarihi"), ("MTART", "CHAR", 4, 0, "", "T134", "Malzeme türü"),
        ("MATKL", "CHAR", 9, 0, "", "T023", "Mal grubu"), ("MEINS", "UNIT", 3, 0, "", "T006", "Temel ölçü birimi"),
        ("BRGEW", "QUAN", 13, 3, "", "", "Brüt ağırlık"), ("ZZESKI", "CHAR", 10, 0, "", "", "Eski malzeme kodu (göç)")]),
    "MAKT": ("Malzeme tanımları", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("MATNR", "CHAR", 40, 0, "X", "MARA", "Malzeme numarası"),
        ("SPRAS", "LANG", 1, 0, "X", "T002", "Dil anahtarı"), ("MAKTX", "CHAR", 40, 0, "", "", "Malzeme tanımı")]),
    "BKPF": ("Muhasebe belgesi başlığı", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("BUKRS", "CHAR", 4, 0, "X", "T001", "Şirket kodu"),
        ("BELNR", "CHAR", 10, 0, "X", "", "Muhasebe belgesi numarası"), ("GJAHR", "NUMC", 4, 0, "X", "", "Mali yıl"),
        ("BLART", "CHAR", 2, 0, "", "T003", "Belge türü"), ("BLDAT", "DATS", 8, 0, "", "", "Belge tarihi"),
        ("BUDAT", "DATS", 8, 0, "", "", "Kayıt tarihi"), ("USNAM", "CHAR", 12, 0, "", "", "Kullanıcı adı"),
        ("WAERS", "CUKY", 5, 0, "", "TCURC", "Para birimi")]),
    "BSEG": ("Muhasebe belgesi kalemi", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("BUKRS", "CHAR", 4, 0, "X", "T001", "Şirket kodu"),
        ("BELNR", "CHAR", 10, 0, "X", "BKPF", "Muhasebe belgesi numarası"), ("GJAHR", "NUMC", 4, 0, "X", "", "Mali yıl"),
        ("BUZEI", "NUMC", 3, 0, "X", "", "Muhasebe belgesindeki kalem numarası"), ("KOART", "CHAR", 1, 0, "", "", "Hesap türü"),
        ("SHKZG", "CHAR", 1, 0, "", "", "Borç/alacak göstergesi"), ("DMBTR", "CURR", 13, 2, "", "", "Ulusal para birimi cinsinden tutar"),
        ("KUNNR", "CHAR", 10, 0, "", "KNA1", "Müşteri numarası"), ("LIFNR", "CHAR", 10, 0, "", "LFA1", "Satıcının hesap numarası"),
        ("HKONT", "CHAR", 10, 0, "", "SKA1", "Genel muhasebe defteri ana hesabı")]),
    "LFA1": ("Satıcı ana verileri", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("LIFNR", "CHAR", 10, 0, "X", "", "Satıcının hesap numarası"),
        ("LAND1", "CHAR", 3, 0, "", "T005", "Ülke anahtarı"), ("NAME1", "CHAR", 35, 0, "", "", "Ad 1"),
        ("ORT01", "CHAR", 35, 0, "", "", "Kent"), ("STCD1", "CHAR", 16, 0, "", "", "Vergi numarası 1"),
        ("STCD2", "CHAR", 11, 0, "", "", "Vergi numarası 2"), ("TELF1", "CHAR", 16, 0, "", "", "Telefon 1"),
        ("KTOKK", "CHAR", 4, 0, "", "T077K", "Satıcı hesap grubu")]),
    "PA0002": ("Personel ana kaydı: kişisel bilgiler (bilgi tipi 0002)", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("PERNR", "NUMC", 8, 0, "X", "PA0003", "Personel numarası"),
        ("SUBTY", "CHAR", 4, 0, "X", "", "Alt tip"), ("ENDDA", "DATS", 8, 0, "X", "", "Bitiş tarihi"),
        ("BEGDA", "DATS", 8, 0, "X", "", "Başlangıç tarihi"), ("NACHN", "CHAR", 40, 0, "", "", "Soyadı"),
        ("VORNA", "CHAR", 40, 0, "", "", "Ad"), ("GBDAT", "DATS", 8, 0, "", "", "Doğum tarihi"),
        ("GESCH", "CHAR", 1, 0, "", "", "Cinsiyet anahtarı"), ("NATIO", "CHAR", 3, 0, "", "T005", "Uyruk"),
        ("FAMST", "CHAR", 1, 0, "", "T502T", "Medeni hal anahtarı")]),
    "ZMUS_SADAKAT": ("Müşteri sadakat puanları (kuruma özel tablo)", [
        ("MANDT", "CLNT", 3, 0, "X", "T000", "Üst birim"), ("KUNNR", "CHAR", 10, 0, "X", "KNA1", "Müşteri"),
        ("DONEM", "NUMC", 6, 0, "X", "", "Dönem (YYYYAA)"), ("PUAN", "DEC", 9, 0, "", "", "Sadakat puanı"),
        ("SEVIYE", "CHAR", 10, 0, "", "", "Sadakat seviyesi")]),
}

SN = {  # tablo: (etiket, [(alan, tip, uzunluk, zorunlu, referans, etiket)])
    "incident": ("Olay", [("number", "string", 40, True, None, "Numara"), ("short_description", "string", 160, True, None, "Kısa açıklama"),
                          ("caller_id", "reference", 32, True, "sys_user", "Arayan"), ("priority", "integer", 40, False, None, "Öncelik"),
                          ("impact", "integer", 40, False, None, "Etki"), ("urgency", "integer", 40, False, None, "Aciliyet"),
                          ("state", "integer", 40, False, None, "Durum"), ("assignment_group", "reference", 32, False, "sys_user_group", "Atama grubu"),
                          ("assigned_to", "reference", 32, False, "sys_user", "Atanan"), ("cmdb_ci", "reference", 32, False, "cmdb_ci", "Yapılandırma öğesi"),
                          ("opened_at", "glide_date_time", 40, False, None, "Açılış"), ("resolved_at", "glide_date_time", 40, False, None, "Çözüm zamanı"),
                          ("company", "reference", 32, False, "core_company", "Şirket")]),
    "problem": ("Problem", [("number", "string", 40, True, None, "Numara"), ("short_description", "string", 160, True, None, "Kısa açıklama"),
                            ("priority", "integer", 40, False, None, "Öncelik"), ("state", "integer", 40, False, None, "Durum"),
                            ("cmdb_ci", "reference", 32, False, "cmdb_ci", "Yapılandırma öğesi"), ("known_error", "boolean", 40, False, None, "Bilinen hata"),
                            ("cause_notes", "html", 8000, False, None, "Kök neden notları")]),
    "change_request": ("Değişiklik talebi", [("number", "string", 40, True, None, "Numara"), ("short_description", "string", 160, True, None, "Kısa açıklama"),
                                            ("type", "string", 40, False, None, "Tür"), ("risk", "integer", 40, False, None, "Risk"),
                                            ("state", "integer", 40, False, None, "Durum"), ("start_date", "glide_date_time", 40, False, None, "Planlanan başlangıç"),
                                            ("end_date", "glide_date_time", 40, False, None, "Planlanan bitiş"), ("cmdb_ci", "reference", 32, False, "cmdb_ci", "Yapılandırma öğesi"),
                                            ("requested_by", "reference", 32, False, "sys_user", "Talep eden")]),
    "cmdb_ci": ("Yapılandırma öğesi", [("name", "string", 255, True, None, "Ad"), ("sys_class_name", "sys_class_name", 80, False, None, "Sınıf"),
                                      ("operational_status", "integer", 40, False, None, "Operasyonel durum"), ("owned_by", "reference", 32, False, "sys_user", "Sahibi"),
                                      ("company", "reference", 32, False, "core_company", "Şirket"), ("install_status", "integer", 40, False, None, "Kurulum durumu")]),
    "sys_user": ("Kullanıcı", [("user_name", "string", 40, True, None, "Kullanıcı kimliği"), ("first_name", "string", 50, False, None, "Ad"),
                               ("last_name", "string", 50, False, None, "Soyadı"), ("email", "email", 100, False, None, "E-posta"),
                               ("phone", "ph_number", 40, False, None, "İş telefonu"), ("mobile_phone", "ph_number", 40, False, None, "Cep telefonu"),
                               ("department", "reference", 32, False, "cmn_department", "Departman"), ("active", "boolean", 40, False, None, "Etkin")]),
    "core_company": ("Şirket", [("name", "string", 80, True, None, "Ad"), ("phone", "ph_number", 40, False, None, "Telefon"),
                                ("city", "string", 50, False, None, "Şehir"), ("customer", "boolean", 40, False, None, "Müşteri"),
                                ("vendor", "boolean", 40, False, None, "Tedarikçi")]),
}

D365 = {  # varlık: (etiket, birincil, [(öznitelik, tür, zorunluluk, etiket, hedefler)])
    "account": ("Firma", "accountid", [("accountid", "Uniqueidentifier", "SystemRequired", "Firma", None),
                                        ("name", "String", "ApplicationRequired", "Firma adı", None), ("accountnumber", "String", "None", "Firma numarası", None),
                                        ("telephone1", "String", "None", "Ana telefon", None), ("emailaddress1", "String", "None", "E-posta", None),
                                        ("address1_city", "String", "None", "Şehir", None), ("revenue", "Money", "None", "Yıllık gelir", None),
                                        ("industrycode", "Picklist", "None", "Sektör", None), ("ownerid", "Owner", "SystemRequired", "Sahip", ["systemuser", "team"])]),
    "contact": ("İlgili kişi", "contactid", [("contactid", "Uniqueidentifier", "SystemRequired", "İlgili kişi", None),
                                             ("firstname", "String", "None", "Ad", None), ("lastname", "String", "ApplicationRequired", "Soyadı", None),
                                             ("emailaddress1", "String", "None", "E-posta", None), ("mobilephone", "String", "None", "Cep telefonu", None),
                                             ("birthdate", "DateTime", "None", "Doğum tarihi", None), ("gendercode", "Picklist", "None", "Cinsiyet", None),
                                             ("parentcustomerid", "Customer", "None", "Firma adı", ["account", "contact"])]),
    "opportunity": ("Fırsat", "opportunityid", [("opportunityid", "Uniqueidentifier", "SystemRequired", "Fırsat", None),
                                                ("name", "String", "ApplicationRequired", "Konu", None), ("customerid", "Customer", "None", "Potansiyel müşteri", ["account", "contact"]),
                                                ("estimatedvalue", "Money", "None", "Tahmini gelir", None), ("estimatedclosedate", "DateTime", "None", "Tahmini kapanış tarihi", None),
                                                ("statecode", "State", "SystemRequired", "Durum", None)]),
    "lead": ("Müşteri adayı", "leadid", [("leadid", "Uniqueidentifier", "SystemRequired", "Müşteri adayı", None),
                                         ("fullname", "String", "None", "Ad soyad", None), ("companyname", "String", "None", "Şirket adı", None),
                                         ("emailaddress1", "String", "None", "E-posta", None), ("telephone1", "String", "None", "İş telefonu", None),
                                         ("leadsourcecode", "Picklist", "None", "Aday kaynağı", None)]),
}

PBI = [("DimMusteri", "MusteriKey", "Int64", "", True), ("DimMusteri", "MusteriNo", "String", "SAP müşteri numarası", False),
       ("DimMusteri", "MusteriAdi", "String", "", False), ("DimMusteri", "Sehir", "String", "", False), ("DimMusteri", "Segment", "String", "", False),
       ("DimUrun", "UrunKey", "Int64", "", True), ("DimUrun", "MalzemeNo", "String", "", False), ("DimUrun", "UrunAdi", "String", "", False),
       ("DimUrun", "UrunGrubu", "String", "", False), ("DimTarih", "Tarih", "DateTime", "", True), ("DimTarih", "Yil", "Int64", "", False),
       ("DimTarih", "Ay", "Int64", "", False), ("FactSatis", "SatisKey", "Int64", "", True), ("FactSatis", "MusteriKey", "Int64", "", False),
       ("FactSatis", "UrunKey", "Int64", "", False), ("FactSatis", "Tarih", "DateTime", "", False),
       ("FactSatis", "NetTutar", "Decimal", "KDV hariç net satış tutarı (TL)", False), ("FactSatis", "Miktar", "Decimal", "", False),
       ("FactSatis", "IndirimTutari", "Decimal", "", False)]

FILES = {"format": "tedarik.catalog.v1", "tables": [
    {"schema": "Pazarlama/Kampanyalar", "name": "kampanya_katilimcilari_2026.xlsx", "object_type": "file", "row_count": 4200, "columns": [
        {"name": "ad"}, {"name": "soyad"}, {"name": "e_posta"}, {"name": "cep_telefonu"}, {"name": "sehir"}, {"name": "kvkk_acik_riza"},
        {"name": "katilim_tarihi"}]},
    {"schema": "Pazarlama/Kampanyalar", "name": "bulten_aboneleri.csv", "object_type": "file", "row_count": 12800, "columns": [
        {"name": "e_posta"}, {"name": "abonelik_tarihi"}, {"name": "iptal_tarihi"}]}]}

SOURCES = [  # ad, platform, alan, CI, sahip, veri yöneticisi, teknik sorumlu, konum, açıklama
    ("SAP S/4HANA Üretim", "sap_hana", "Satış ve Sipariş", "ERP Uygulaması", "Ayla Çetin", None, "mehmet.kaya", "s4p-hana.demo.local (SID S4P)",
     "ERP sistemi; müşteri, satış, malzeme, muhasebe ve İK ana verileri. ABAP sözlüğünden içe aktarıldı."),
    ("ServiceNow ITSM", "servicenow", "BT Hizmet Yönetimi", "ITSM Platformu", "mehmet.kaya", None, "kerem.aksoy", "demo.service-now.com (örnek)",
     "Olay, problem, değişiklik ve CMDB kayıtları. sys_dictionary JSON çıktısından içe aktarıldı."),
    ("Dynamics 365 CRM", "dynamics365", "Müşteri", "CRM Uygulaması", "zeynep.demir", None, "deniz.koc", "demo.crm4.dynamics.com (örnek)",
     "Müşteri ilişkileri: firma, ilgili kişi, fırsat ve müşteri adayı. EntityDefinitions JSON çıktısından içe aktarıldı."),
    ("Power BI — Satış Performans Modeli", "power_bi", "Satış ve Sipariş", None, "kerem.aksoy", None, "deniz.koc", "Satış Analitiği çalışma alanı",
     "Yönetim raporlarını besleyen anlamsal model. INFO.VIEW.COLUMNS() çıktısından içe aktarıldı."),
    ("Pazarlama Dosya Paylaşımı", "file", None, None, None, None, None, "\\\\dosya01\\Pazarlama",
     "Kampanya katılımcı listeleri. Sahibi ve sınıfı atanmamış: veri yönetişimi açığı örneği."),
]

# (tablo, kolon) → (iş adı, açıklama, sınıf, kişisel veri, kritik)
SAP_META = {
    ("KNA1", None): ("Müşteri ana kaydı", "Müşterinin kimlik, adres ve vergi bilgilerinin tutulduğu SAP tablosu. Satış, finans ve CRM bu kayda dayanır.", "confidential", None, None),
    ("KNA1", "KUNNR"): ("Müşteri numarası", None, "internal", "none", 1), ("KNA1", "NAME1"): ("Müşteri adı / unvanı", "Bireysel müşteride ad soyad, kurumsal müşteride unvan.", "confidential", "personal", None),
    ("KNA1", "TELF1"): ("Telefon numarası", None, "confidential", "personal", None), ("KNA1", "STCD1"): ("T.C. kimlik numarası", "Bireysel müşterilerde TCKN bu alanda tutulur.", "restricted", "personal", 1),
    ("KNA1", "STCD2"): ("Vergi kimlik numarası", None, "confidential", "none", None), ("KNA1", "STRAS"): ("Adres", None, "confidential", "personal", None),
    ("KNA1", "ORT01"): ("Şehir", None, "internal", "none", None), ("KNA1", "ERDAT"): ("Kayıt tarihi", None, "internal", "none", None),
    ("VBAK", None): ("Satış siparişi başlığı", "Her satış siparişinin müşteri, tarih ve toplam tutar bilgisi.", "internal", None, None),
    ("VBAK", "VBELN"): ("Satış siparişi numarası", None, None, "none", 1), ("VBAK", "KUNNR"): ("Siparişi veren müşteri", None, None, "none", None),
    ("VBAK", "NETWR"): ("Sipariş net tutarı", None, None, "none", 1), ("VBAK", "ERDAT"): ("Sipariş tarihi", None, None, "none", None),
    ("VBAP", "MATNR"): ("Malzeme numarası", None, None, "none", None), ("VBAP", "NETWR"): ("Kalem net tutarı", None, None, "none", None),
    ("MARA", None): ("Malzeme ana kaydı", None, "internal", None, None), ("MARA", "MATNR"): ("Malzeme numarası", None, None, "none", 1),
    ("BKPF", "BUKRS"): ("Şirket kodu", None, "internal", "none", None), ("BSEG", "DMBTR"): ("Tutar (TL)", None, "confidential", "none", None),
    ("PA0002", None): ("Çalışan kişisel bilgileri", "Çalışanların ad, soyad, doğum tarihi, cinsiyet, uyruk ve medeni hal bilgileri.", "restricted", None, None),
    ("PA0002", "PERNR"): ("Personel numarası", None, None, "personal", 1), ("PA0002", "NACHN"): ("Soyadı", None, None, "personal", None),
    ("PA0002", "VORNA"): ("Ad", None, None, "personal", None), ("PA0002", "GBDAT"): ("Doğum tarihi", None, None, "personal", None),
    ("PA0002", "GESCH"): ("Cinsiyet", None, None, "personal", None), ("PA0002", "NATIO"): ("Uyruk", None, None, "personal", None),
    ("PA0002", "FAMST"): ("Medeni hal", None, None, "personal", None),
}

TERMS = [  # ad, kısaltma, eş anlamlılar, alan, tanım, ek alanlar, durum
    ("Müşteri", None, "Cari (eski kullanım)", "Müşteri", "Kurumla en az bir sözleşme veya satış siparişi ilişkisi bulunan gerçek veya tüzel kişi.",
     {"example": "Demo Perakende A.Ş., bireysel abone", "review_date": 120}, "approved"),
    ("Müşteri numarası", "Müşteri no", "Müşteri kodu, KUNNR, accountnumber", "Müşteri",
     "Müşteriyi tüm sistemlerde tekil tanımlayan, SAP'de üretilen 10 haneli kod. CRM ve raporlama sistemleri bu kodu taşır.",
     {"format_rule": "10 hane, yalnızca rakam; baştaki sıfırlar korunur", "example": "0001004512", "is_critical": 1, "classification": "internal",
      "review_date": 200}, "approved"),
    ("Aktif müşteri", None, "Etkin müşteri", "Müşteri", "Son 12 ayda en az bir faturalanmış satış siparişi bulunan müşteri.",
     {"calculation": "COUNT(DISTINCT KUNNR) — VBAK.ERDAT son 12 ay içinde ve fatura durumu 'faturalandı'", "review_date": 90}, "approved"),
    ("T.C. kimlik numarası", "TCKN", "Kimlik no", "Müşteri", "Türkiye Cumhuriyeti vatandaşlarına verilen 11 haneli kimlik numarası.",
     {"format_rule": "11 hane, ilk hane 0 olamaz, son iki hane algoritmik doğrulama", "classification": "restricted", "personal_data": "personal",
      "is_critical": 1, "source_reference": "6698 sayılı KVKK md. 3 (kişisel veri)", "review_date": 300}, "approved"),
    ("Vergi kimlik numarası", "VKN", "Vergi no", "Finans", "Tüzel kişilere ve şahıs işletmelerine vergi dairesince verilen 10 haneli numara.",
     {"format_rule": "10 hane, yalnızca rakam", "classification": "confidential", "review_date": 250}, "approved"),
    ("E-posta adresi", None, "E-posta", "Müşteri", "Kişiye veya kuruma elektronik ileti göndermek için kullanılan adres.",
     {"classification": "confidential", "personal_data": "personal", "format_rule": "RFC 5322 biçimi", "review_date": 180}, "approved"),
    ("Telefon numarası", None, "Cep telefonu, iş telefonu", "Müşteri", "Kişiye veya kuruma ulaşmak için kullanılan telefon numarası.",
     {"classification": "confidential", "personal_data": "personal", "format_rule": "E.164, ör. +90 5xx xxx xx xx", "review_date": 180}, "approved"),
    ("Doğum tarihi", None, None, "İnsan Kaynakları", "Kişinin doğduğu gün; yaş ve yasal yükümlülük hesaplarında kullanılır.",
     {"classification": "restricted", "personal_data": "personal", "review_date": 365}, "approved"),
    ("Satış siparişi", None, "Sipariş", "Satış ve Sipariş", "Müşterinin ürün veya hizmet talebini fiyat, miktar ve teslim koşullarıyla kayda alan satış belgesi.",
     {"review_date": 160}, "approved"),
    ("Sipariş net tutarı", None, "Net değer, NETWR", "Satış ve Sipariş", "Satış siparişi kalemlerinin indirimler düşüldükten sonraki, vergiler hariç toplam tutarı.",
     {"calculation": "SUM(VBAP.NETWR) — belge para biriminde; raporlamada TL'ye günlük kurla çevrilir", "is_critical": 1, "review_date": 160}, "approved"),
    ("Malzeme numarası", None, "Ürün kodu, MATNR", "Ürün ve Malzeme", "Malzemeyi veya satılabilir ürünü SAP'de tekil tanımlayan kod.",
     {"format_rule": "En çok 40 karakter", "review_date": 220}, "approved"),
    ("Şirket kodu", None, "BUKRS", "Finans", "Bağımsız bilanço hazırlanan en küçük örgütsel birim.", {"review_date": 400}, "approved"),
    ("Olay", None, "Incident, arıza", "BT Hizmet Yönetimi", "Bir BT hizmetinin plansız kesintisi veya kalitesinin düşmesi.",
     {"source_reference": "ISO/IEC 20000-1:2018 madde 8.6.1", "review_date": -10}, "approved"),
    ("Öncelik", None, "Priority", "BT Hizmet Yönetimi", "Olayın çözüm sırasını belirleyen derece; etki ve aciliyetten türetilir.",
     {"calculation": "Etki (1–3) × aciliyet (1–3) matrisi: P1 kritik … P4 düşük", "review_date": -5}, "approved"),
    ("Yapılandırma öğesi", "CI", "Configuration item", "BT Hizmet Yönetimi", "Bir hizmeti sunmak için yönetilmesi gereken bileşen: sunucu, uygulama, veritabanı, ağ cihazı.",
     {"review_date": 210}, "approved"),
    ("Değişiklik talebi", None, "RFC, change", "BT Hizmet Yönetimi", "BT hizmetlerinde ekleme, değiştirme veya kaldırma için onaylanması gereken resmî talep.",
     {"review_date": 210}, "approved"),
    ("Personel numarası", None, "Sicil no, PERNR", "İnsan Kaynakları", "Çalışanı İK sistemlerinde tekil tanımlayan numara.",
     {"personal_data": "personal", "classification": "confidential", "review_date": 365}, "approved"),
    ("Satış fırsatı", None, "Fırsat, opportunity", "Müşteri", "Henüz siparişe dönüşmemiş, tahmini değeri ve kapanış tarihi olan potansiyel satış.",
     {"review_date": 150}, "approved"),
    ("Müşteri yaşam boyu değeri", "CLV", None, "Müşteri", "Bir müşterinin ilişki süresi boyunca kuruma bırakması beklenen net katkının bugünkü değeri.",
     {"calculation": "Σ (yıllık brüt kâr × elde tutma oranı^t) / (1 + iskonto oranı)^t"}, "in_review"),
    ("Brüt kâr marjı", None, None, "Finans", "Satış gelirinden satılan malın maliyeti düşüldükten sonra kalan tutarın satış gelirine oranı.",
     {"calculation": "(Net satış − SMM) / Net satış"}, "returned"),
    ("Kampanya katılım oranı", None, None, None, "Kampanyaya davet edilenlerden katılım formunu dolduranların oranı.", {}, "draft"),
    ("Cari hesap", None, None, "Finans", "Eskiden müşteri ve satıcılar için ortak kullanılan terim.", {}, "retired"),
]

LINKS = {  # terim → [(kaynak, tablo, kolon veya None)]
    "Müşteri": [("SAP S/4HANA Üretim", "KNA1", None), ("Dynamics 365 CRM", "account", None), ("Power BI — Satış Performans Modeli", "DimMusteri", None)],
    "Müşteri numarası": [("SAP S/4HANA Üretim", "KNA1", "KUNNR"), ("SAP S/4HANA Üretim", "KNVV", "KUNNR"), ("SAP S/4HANA Üretim", "VBAK", "KUNNR"),
                         ("SAP S/4HANA Üretim", "BSEG", "KUNNR"), ("Dynamics 365 CRM", "account", "accountnumber"),
                         ("Power BI — Satış Performans Modeli", "DimMusteri", "MusteriNo")],
    "T.C. kimlik numarası": [("SAP S/4HANA Üretim", "KNA1", "STCD1")],
    "Vergi kimlik numarası": [("SAP S/4HANA Üretim", "KNA1", "STCD2"), ("SAP S/4HANA Üretim", "LFA1", "STCD2")],
    "E-posta adresi": [("Dynamics 365 CRM", "account", "emailaddress1"), ("Dynamics 365 CRM", "contact", "emailaddress1"),
                       ("Dynamics 365 CRM", "lead", "emailaddress1"), ("ServiceNow ITSM", "sys_user", "email")],
    "Telefon numarası": [("SAP S/4HANA Üretim", "KNA1", "TELF1"), ("SAP S/4HANA Üretim", "LFA1", "TELF1"), ("Dynamics 365 CRM", "account", "telephone1"),
                         ("Dynamics 365 CRM", "contact", "mobilephone"), ("ServiceNow ITSM", "sys_user", "mobile_phone"), ("ServiceNow ITSM", "sys_user", "phone")],
    "Doğum tarihi": [("SAP S/4HANA Üretim", "PA0002", "GBDAT"), ("Dynamics 365 CRM", "contact", "birthdate")],
    "Satış siparişi": [("SAP S/4HANA Üretim", "VBAK", None)],
    "Sipariş net tutarı": [("SAP S/4HANA Üretim", "VBAK", "NETWR"), ("Power BI — Satış Performans Modeli", "FactSatis", "NetTutar")],
    "Malzeme numarası": [("SAP S/4HANA Üretim", "MARA", "MATNR"), ("SAP S/4HANA Üretim", "MAKT", "MATNR"), ("SAP S/4HANA Üretim", "VBAP", "MATNR"),
                         ("Power BI — Satış Performans Modeli", "DimUrun", "MalzemeNo")],
    "Şirket kodu": [("SAP S/4HANA Üretim", "BKPF", "BUKRS"), ("SAP S/4HANA Üretim", "BSEG", "BUKRS")],
    "Olay": [("ServiceNow ITSM", "incident", None)], "Öncelik": [("ServiceNow ITSM", "incident", "priority"), ("ServiceNow ITSM", "problem", "priority")],
    "Yapılandırma öğesi": [("ServiceNow ITSM", "cmdb_ci", None), ("ServiceNow ITSM", "incident", "cmdb_ci")],
    "Değişiklik talebi": [("ServiceNow ITSM", "change_request", None)], "Personel numarası": [("SAP S/4HANA Üretim", "PA0002", "PERNR")],
    "Satış fırsatı": [("Dynamics 365 CRM", "opportunity", None)],
}


def sap_ddic(changed=False):
    lines = ["TABNAME,FIELDNAME,POSITION,DATATYPE,LENG,DECIMALS,KEYFLAG,NOTNULL,CHECKTABLE,DDTEXT,SCRTEXT_L"]
    for table, (text, fields) in SAP.items():
        if changed and table == "ZMUS_SADAKAT":
            continue
        rows = list(fields)
        if changed and table == "KNA1":
            rows.append(("ZZKVKKONAY", "CHAR", 1, 0, "", "", "KVKK açık rıza işareti"))
        if changed and table == "MARA":
            rows = [r for r in rows if r[0] != "ZZESKI"]
        for pos, (field, kind, length, dec, key, check, label) in enumerate(rows, start=1):
            if changed and (table, field) == ("VBAK", "NETWR"):
                length = 17
            lines.append(",".join([table, field, f"{pos:04d}", kind, f"{length:06d}", f"{dec:06d}", key, key, check,
                                   f'"{text}"', f'"{label}"']))
    return "\n".join(lines) + "\n"


def sn_dictionary():
    result = []
    for table, (label, fields) in SN.items():
        result.append({"name": {"value": table, "display_value": table}, "element": {"value": "", "display_value": ""},
                       "column_label": {"value": label, "display_value": label}, "internal_type": {"value": "collection", "display_value": "Collection"}})
        result.append({"name": {"value": table, "display_value": table}, "element": {"value": "sys_id", "display_value": "sys_id"},
                       "column_label": {"value": "Sys ID", "display_value": "Sys ID"}, "internal_type": {"value": "GUID", "display_value": "Sys ID (GUID)"},
                       "max_length": {"value": "32", "display_value": "32"}, "mandatory": {"value": "false", "display_value": "false"}})
        for name, kind, length, mandatory, ref, flabel in fields:
            result.append({"name": {"value": table, "display_value": table}, "element": {"value": name, "display_value": name},
                           "column_label": {"value": flabel, "display_value": flabel}, "internal_type": {"value": kind, "display_value": kind},
                           "max_length": {"value": str(length), "display_value": str(length)},
                           "mandatory": {"value": "true" if mandatory else "false", "display_value": "true" if mandatory else "false"},
                           "reference": {"value": ref or "", "display_value": ref or ""}})
    return json.dumps({"result": result}, ensure_ascii=False)


def d365_entities():
    def label(text):
        return {"LocalizedLabels": [{"Label": text, "LanguageCode": 1055}], "UserLocalizedLabel": {"Label": text, "LanguageCode": 1055}}
    value = []
    for name, (text, primary, attrs) in D365.items():
        value.append({"LogicalName": name, "SchemaName": name.capitalize(), "DisplayName": label(text), "PrimaryIdAttribute": primary,
                      "Attributes": [{"LogicalName": a, "AttributeType": kind, "DisplayName": label(alabel), "RequiredLevel": {"Value": level},
                                      "IsPrimaryId": a == primary, **({"Targets": targets} if targets else {})}
                                     for a, kind, level, alabel, targets in attrs] +
                                    [{"LogicalName": "createdbyname", "AttributeType": "String", "AttributeOf": "createdby"}]})
    return json.dumps({"value": value}, ensure_ascii=False)


def pbi_columns():
    lines = ["[Table],[Name],[DataType],[Description],[IsKey],[IsNullable]"]
    for table, column, kind, desc, key in PBI:
        lines.append(f"{table},{column},{kind},{desc},{'True' if key else 'False'},{'False' if key else 'True'}")
    return "\n".join(lines) + "\n"


DATAGOV_SECTIONS = (("datagov", "datagov"), ("privacy", "datagov"))


class DatagovSections:
    """Seeder'a karışan bölüm (demo.py)."""

    def datagov(self):
        from . import crud
        from .demo_platform import day
        from .modules import datagov as D
        db = self.db
        if one(db, "SELECT id FROM tdr_data_sources WHERE name=?", (SOURCES[0][0],)):
            return
        domains = {}
        for name, unit, owner, steward, parent, desc in DOMAINS:
            unit_id = self._by("org_units", "name", unit) if unit else None
            domains[name] = self.add("data_domains", {"name": name, "org_unit_id": unit_id, "owner": owner, "steward": steward,
                                                      "parent_id": domains.get(parent), "description": desc})
        sources = {}
        for name, platform, domain, ci, owner, steward, custodian, location, desc in SOURCES:
            sources[name] = self.add("data_sources", {"name": name, "platform": platform, "domain_id": domains.get(domain),
                                                      "ci_id": self._by("cmdb_cis", "name", ci) if ci else None, "owner": owner,
                                                      "steward": steward, "custodian": custodian, "location": location,
                                                      "description": desc, "environment": "production"})
        files = {"SAP S/4HANA Üretim": ("dd03l_dd02t_dd04t.csv", sap_ddic(), "SAPHANADB"),
                 "ServiceNow ITSM": ("sys_dictionary.json", sn_dictionary(), ""),
                 "Dynamics 365 CRM": ("EntityDefinitions.json", d365_entities(), ""),
                 "Power BI — Satış Performans Modeli": ("info_view_columns.csv", pbi_columns(), "Satış Performans Modeli"),
                 "Pazarlama Dosya Paylaşımı": ("dosya_paylasimi.json", json.dumps(FILES, ensure_ascii=False), "")}
        for name, (filename, text, schema) in files.items():
            source = crud.get(db, D.SOURCES, sources[name])
            D.apply_structure(db, source, D.parse_catalog(filename, text.encode("utf-8"), schema), scope="tables",
                              principal=ADMIN, filename=filename)

        def table(source, name):
            row = one(db, "SELECT * FROM tdr_data_tables WHERE source_id=? AND name=?", (sources[source], name))
            return row

        def column(source, tname, cname):
            t = table(source, tname)
            return one(db, "SELECT * FROM tdr_data_columns WHERE table_id=? AND name=?", (t["id"], cname)) if t else None
        # iş açıklamaları, sınıflar ve sahiplik
        for (tname, cname), (bname, desc, cls, personal, critical) in SAP_META.items():
            values = {k: v for k, v in (("business_name", bname), ("description", desc), ("classification", cls),
                                        ("personal_data", personal), ("is_critical", critical)) if v is not None}
            target = column("SAP S/4HANA Üretim", tname, cname) if cname else table("SAP S/4HANA Üretim", tname)
            if cname is None:
                values.pop("personal_data", None)
                values.pop("is_critical", None)
            crud.update(db, D.COLUMNS if cname else D.TABLES, target["id"], values, None)
        for tname, domain in (("PA0002", "İnsan Kaynakları"), ("BKPF", "Finans"), ("BSEG", "Finans"), ("MARA", "Ürün ve Malzeme"),
                              ("MAKT", "Ürün ve Malzeme"), ("KNA1", "Müşteri"), ("KNVV", "Müşteri")):
            crud.update(db, D.TABLES, table("SAP S/4HANA Üretim", tname)["id"], {"domain_id": domains[domain]}, None)
        crud.update(db, D.TABLES, table("SAP S/4HANA Üretim", "KNA1")["id"], {"certified": 1, "steward": "deniz.koc"}, None)
        for tname in ("DimMusteri", "FactSatis"):
            crud.update(db, D.TABLES, table("Power BI — Satış Performans Modeli", tname)["id"],
                        {"certified": 1, "classification": "internal"}, None)
        for tname, cls in (("account", "confidential"), ("contact", "confidential"), ("lead", "confidential"), ("opportunity", "internal")):
            crud.update(db, D.TABLES, table("Dynamics 365 CRM", tname)["id"], {"classification": cls}, None)
        crud.update(db, D.TABLES, table("ServiceNow ITSM", "sys_user")["id"], {"classification": "confidential",
                                                                                "business_name": "BT kullanıcı dizini"}, None)
        for source, tname, cname, personal in (
                ("Dynamics 365 CRM", "contact", "firstname", "personal"), ("Dynamics 365 CRM", "contact", "lastname", "personal"),
                ("Dynamics 365 CRM", "contact", "emailaddress1", "personal"), ("Dynamics 365 CRM", "contact", "mobilephone", "personal"),
                ("Dynamics 365 CRM", "contact", "birthdate", "personal"), ("Dynamics 365 CRM", "contact", "gendercode", "personal"),
                ("Dynamics 365 CRM", "lead", "fullname", "personal"), ("Dynamics 365 CRM", "lead", "emailaddress1", "personal"),
                ("ServiceNow ITSM", "sys_user", "email", "personal"), ("ServiceNow ITSM", "sys_user", "mobile_phone", "personal"),
                ("ServiceNow ITSM", "sys_user", "first_name", "personal"), ("ServiceNow ITSM", "sys_user", "last_name", "personal"),
                ("Pazarlama Dosya Paylaşımı", "kampanya_katilimcilari_2026.xlsx", "ad", "personal"),
                ("Pazarlama Dosya Paylaşımı", "kampanya_katilimcilari_2026.xlsx", "soyad", "personal"),
                ("Pazarlama Dosya Paylaşımı", "kampanya_katilimcilari_2026.xlsx", "e_posta", "personal"),
                ("Pazarlama Dosya Paylaşımı", "kampanya_katilimcilari_2026.xlsx", "cep_telefonu", "personal"),
                ("Pazarlama Dosya Paylaşımı", "bulten_aboneleri.csv", "e_posta", "personal")):
            crud.update(db, D.COLUMNS, column(source, tname, cname)["id"], {"personal_data": personal}, None)
        crud.update(db, D.COLUMNS, column("Dynamics 365 CRM", "contact", "gendercode")["id"],
                    {"description": "Cinsiyet bilgisi; kampanya hedeflemesinde kullanılmamalı (veri en aza indirme)."}, None)
        # iş sözlüğü: onaylı terimler sürüm kaydıyla, bekleyen öneri, iade ve kullanım dışı örnekleri
        now, ids = utcnow(), {}
        for name, abbr, syn, domain, definition, extra, status in TERMS:
            values = {"name": name, "abbreviation": abbr, "synonyms": syn, "definition": definition, "domain_id": domains.get(domain),
                      **{k: v for k, v in extra.items() if k != "review_date"}}
            dom = next((d for d in DOMAINS if d[0] == domain), None)
            values["owner"], values["steward"] = (dom[2], dom[3]) if dom else (None, None)
            if "review_date" in extra:
                values["review_date"] = day(extra["review_date"])
            term_id = self.add("glossary_terms", values, created_days_ago=60)
            ids[name] = term_id
            db.execute("UPDATE tdr_glossary_terms SET created_by='deniz.koc' WHERE id=?", (term_id,))
            approver = (dom[2] if dom and dom[2] else None) or "selin.aydin"
            approver = approver if approver in ("zeynep.demir", "kerem.aksoy", "mehmet.kaya", "selin.aydin") else "selin.aydin"
            if status in ("approved", "retired"):
                db.execute("""UPDATE tdr_glossary_terms SET status='approved', version=1, submitted_by='deniz.koc', submitted_at=?,
                    approved_by=?, approved_at=? WHERE id=?""", (now, approver, now, term_id))
                D._version(db, crud.get(db, D.TERMS, term_id), "İlk onay", "deniz.koc", approver)
            elif status == "in_review":
                db.execute("UPDATE tdr_glossary_terms SET status='in_review', submitted_by='deniz.koc', submitted_at=? WHERE id=?",
                           (now, term_id))
            elif status == "returned":
                db.execute("UPDATE tdr_glossary_terms SET review_note=? WHERE id=?",
                           ("Hesaplamada iskonto ve iadelerin nasıl ele alındığını ekleyin; SMM kaynağını belirtin.", term_id))
        db.execute("UPDATE tdr_glossary_terms SET parent_id=? WHERE id=?", (ids["Müşteri"], ids["Aktif müşteri"]))
        db.execute("UPDATE tdr_glossary_terms SET status='retired', replaced_by_id=?, review_note=? WHERE id=?",
                   (ids["Müşteri"], "Müşteri ve satıcı için ayrı terimler kullanılıyor.", ids["Cari hesap"]))
        db.execute("""UPDATE tdr_glossary_terms SET pending_json=?, pending_by='deniz.koc', pending_note=?, pending_at=? WHERE id=?""",
                   (json.dumps({"definition": "Son 12 ayda en az bir faturalanmış satış siparişi veya yürürlükte sözleşmesi bulunan müşteri.",
                                "calculation": "COUNT(DISTINCT KUNNR) — son 12 ayda faturalanmış sipariş VEYA aktif sözleşme"}, ensure_ascii=False),
                    "Abonelik müşterileri sipariş açmadan hizmet alıyor; sözleşmesi aktif olanlar da aktif sayılmalı.", now, ids["Aktif müşteri"]))
        # Müşteri teriminin ikinci sürümü (örnek kullanım notu)
        db.execute("UPDATE tdr_glossary_terms SET version=2, example=? WHERE id=?", ("Demo Perakende A.Ş., bireysel abone, kamu kurumu", ids["Müşteri"]))
        D._version(db, crud.get(db, D.TERMS, ids["Müşteri"]), "Kamu kurumları örneğe eklendi", "deniz.koc", "zeynep.demir")
        for a, b in (("Müşteri", "Satış fırsatı"), ("Müşteri numarası", "Müşteri"), ("Satış siparişi", "Sipariş net tutarı"), ("Olay", "Öncelik")):
            x, y = sorted((ids[a], ids[b]))
            db.execute("INSERT INTO tdr_term_relations (term_id, related_id) VALUES (?,?) ON CONFLICT DO NOTHING", (x, y))
        for term, targets in LINKS.items():
            for source, tname, cname in targets:
                if cname:
                    col = column(source, tname, cname)
                    if col:
                        db.execute("INSERT INTO tdr_term_columns (term_id, column_id, created_by, created_at) VALUES (?,?,?,?) "
                                   "ON CONFLICT DO NOTHING", (ids[term], col["id"], "deniz.koc", now))
                else:
                    t = table(source, tname)
                    if t:
                        db.execute("INSERT INTO tdr_term_tables (term_id, table_id, created_by, created_at) VALUES (?,?,?,?) "
                                   "ON CONFLICT DO NOTHING", (ids[term], t["id"], "deniz.koc", now))
        # ikinci SAP yüklemesi: eklenen alan, kaldırılan alan ve tablo, tipi değişen alan
        sap = crud.get(db, D.SOURCES, sources["SAP S/4HANA Üretim"])
        D.apply_structure(db, sap, D.parse_catalog("dd03l_dd02t_dd04t.csv", sap_ddic(changed=True).encode("utf-8"), "SAPHANADB"),
                          scope="schemas", principal=ADMIN, filename="dd03l_dd02t_dd04t_2.csv")
        kvkk = column("SAP S/4HANA Üretim", "KNA1", "ZZKVKKONAY")
        if kvkk:
            crud.update(db, D.COLUMNS, kvkk["id"], {"business_name": "KVKK açık rıza işareti", "personal_data": "personal"}, None)

    # -------------------------------------------------------------- KVKK ve sınıflandırma (K-029)
    def privacy(self):
        from . import crud
        from .demo_platform import day, stamp
        from .modules import privacy as P
        db = self.db
        if one(db, "SELECT id FROM tdr_processing_activities LIMIT 1"):
            return
        P.seed(db)
        cats = {r["name"]: r for r in P.categories(db)}
        groups = {r["name"]: r["id"] for r in db.execute("SELECT id, name FROM tdr_data_subject_groups").fetchall()}

        def src(name):
            row = one(db, "SELECT id FROM tdr_data_sources WHERE name=?", (name,))
            return row["id"] if row else None

        def tbl(source, name):
            row = one(db, "SELECT * FROM tdr_data_tables WHERE source_id=? AND name=?", (src(source), name))
            return row
        if not tbl("SAP S/4HANA Üretim", "KNA1"):
            return
        for term, cat in (("T.C. kimlik numarası", "Kimlik"), ("E-posta adresi", "İletişim"), ("Telefon numarası", "İletişim"),
                          ("Doğum tarihi", "Kimlik"), ("Personel numarası", "Özlük")):
            db.execute("UPDATE tdr_glossary_terms SET category_id=? WHERE name=?", (cats[cat]["id"], term))
        P.discover(db)
        company = tbl("ServiceNow ITSM", "core_company")
        if company:                       # yanlış pozitif örneği: kurumsal şirket telefonu kişisel veri değil
            db.execute("""UPDATE tdr_pii_suggestions SET status='rejected', decided_by='deniz.koc', decided_at=?, decision_note=?
                WHERE status='pending' AND column_id IN (SELECT id FROM tdr_data_columns WHERE table_id=?)""",
                       (stamp(19), "Kurumsal şirket iletişim bilgisi; kişisel veri değil", company["id"]))
        pazarlama = src("Pazarlama Dosya Paylaşımı")
        admin = Principal("zeynep.demir", "UNIT_USER", "system", "Zeynep Demir")
        for sgg in db.execute("""SELECT s.id, s.column_id, s.category_id, s.confidence, t.source_id FROM tdr_pii_suggestions s
                JOIN tdr_data_columns c ON c.id=s.column_id JOIN tdr_data_tables t ON t.id=c.table_id WHERE s.status='pending'""").fetchall():
            if sgg["source_id"] == pazarlama or float(sgg["confidence"]) < 0.7:
                continue
            column = crud.get(db, RESOURCES_COLUMNS(), sgg["column_id"])
            P.apply_category(db, column, crud.get(db, P.CATEGORIES, sgg["category_id"]), admin, source="suggestion")
            db.execute("UPDATE tdr_pii_suggestions SET status='accepted', decided_by='deniz.koc', decided_at=?, updated_at=? WHERE id=?",
                       (stamp(20), stamp(20), sgg["id"]))
        first = one(db, """SELECT s.id FROM tdr_pii_suggestions s JOIN tdr_personal_data_categories k ON k.id=s.category_id
            WHERE s.status='pending' AND k.name='Müşteri İşlem' ORDER BY s.id LIMIT 1""")
        if first:
            db.execute("UPDATE tdr_pii_suggestions SET status='rejected', decided_by='deniz.koc', decided_at=?, decision_note=? WHERE id=?",
                       (stamp(19), "Kurumsal müşteri kodu; tek başına kişiyi tanımlamıyor", first["id"]))
        note = "Örnek süre (sentetik demo): kurumunuzun saklama ve imha politikasıyla ve hukuk birimiyle doğrulayın."
        rules = {}
        for key, name, value, unit, trigger, method, ref in (
                ("musteri", "Müşteri ana verisi ve sözleşme kayıtları", 10, "year", "Sözleşme ilişkisinin sona ermesi", "deletion", "Örnek: TTK md. 82"),
                ("muhasebe", "Muhasebe belgeleri", 10, "year", "Mali yılın sonu", "destruction", "Örnek: TTK md. 82, VUK md. 253"),
                ("ozluk", "Çalışan özlük kayıtları", 10, "year", "İş ilişkisinin sona ermesi", "destruction", "Örnek: iş mevzuatı ve zamanaşımı süreleri"),
                ("pazarlama", "Pazarlama izinli iletişim listeleri", 2, "year", "Kampanya bitişi veya rızanın geri alınması", "destruction",
                 "Örnek: kurum saklama ve imha politikası"),
                ("bt", "BT kullanıcı ve işlem kayıtları", 2, "year", "Kaydın oluşması", "deletion", "Örnek: 5651 sayılı Kanun ve kurum politikası")):
            rules[key] = self.add("retention_rules", {"name": name, "period_value": value, "period_unit": unit, "trigger_event": trigger,
                                                      "disposal_method": method, "legal_reference": ref, "description": note,
                                                      "owner": "selin.aydin"})
        for source, name, rule in (("SAP S/4HANA Üretim", "KNA1", "musteri"), ("SAP S/4HANA Üretim", "KNVV", "musteri"),
                                   ("SAP S/4HANA Üretim", "BKPF", "muhasebe"), ("SAP S/4HANA Üretim", "BSEG", "muhasebe"),
                                   ("SAP S/4HANA Üretim", "PA0002", "ozluk"), ("Dynamics 365 CRM", "account", "musteri"),
                                   ("Dynamics 365 CRM", "contact", "musteri"), ("Dynamics 365 CRM", "lead", "pazarlama"),
                                   ("Pazarlama Dosya Paylaşımı", "bulten_aboneleri.csv", "pazarlama"),
                                   ("ServiceNow ITSM", "sys_user", "bt"), ("ServiceNow ITSM", "incident", "bt")):
            t = tbl(source, name)
            if t:
                db.execute("UPDATE tdr_data_tables SET retention_rule_id=? WHERE id=?", (rules[rule], t["id"]))
        crm_supplier = one(db, "SELECT id FROM tdr_suppliers WHERE name LIKE ? ORDER BY id LIMIT 1", ("%Bulut%",))
        mail_supplier = one(db, "SELECT id FROM tdr_suppliers WHERE id<>? ORDER BY id DESC LIMIT 1", ((crm_supplier or {}).get("id", 0),))
        unit = lambda n: self._by("org_units", "name", n)       # noqa: E731
        acts = {}
        specs = [
            ("crm", {"name": "Müşteri ilişkileri yönetimi (CRM)", "purpose": "Müşteriyle sözleşme ilişkisinin kurulması ve yürütülmesi, "
                     "taleplerin karşılanması", "org_unit_id": unit("Müşteri Hizmetleri"), "owner": "zeynep.demir",
                     "legal_basis": "contract", "recipients": "Grup şirketleri; yetkili kamu kurum ve kuruluşları",
                     "foreign_transfer": 1, "transfer_countries": "İrlanda (bulut veri merkezi)", "transfer_mechanism": "standard_contract",
                     "transfer_signed_on": "2026-02-02", "transfer_notified_on": "2026-02-05", "retention_rule_id": rules["musteri"],
                     "security_measures": "Rol tabanlı erişim, şifreleme (aktarımda ve depoda), erişim kayıtları, yıllık sızma testi",
                     "large_scale": 1, "status": "active", "review_date": day(120)},
             ["Kimlik", "İletişim", "Müşteri İşlem"], ["Müşteri", "Potansiyel Müşteri"],
             [("Dynamics 365 CRM", "account"), ("Dynamics 365 CRM", "contact"), ("SAP S/4HANA Üretim", "KNA1"), ("SAP S/4HANA Üretim", "KNVV"),
              ("Power BI — Satış Performans Modeli", "DimMusteri")], [(crm_supplier, "processor", 1)]),
            ("satis", {"name": "Satış ve faturalama", "purpose": "Siparişlerin alınması, faturalandırılması ve muhasebeleştirilmesi",
                       "org_unit_id": unit("Finans"), "owner": "Ayla Çetin", "legal_basis": "legal_obligation",
                       "recipients": "Gelir İdaresi Başkanlığı; bağımsız denetçi", "retention_rule_id": rules["muhasebe"],
                       "security_measures": "Görevler ayrılığı, onay akışı, değişiklik kaydı", "status": "active"},
             ["Müşteri İşlem", "Finans"], ["Müşteri"], [("SAP S/4HANA Üretim", "VBAK"), ("SAP S/4HANA Üretim", "VBAP"),
                                                        ("SAP S/4HANA Üretim", "BKPF"), ("SAP S/4HANA Üretim", "BSEG")], []),
            ("ik", {"name": "Bordro ve özlük yönetimi", "purpose": "İş sözleşmesinin ifası, bordro ve yasal bildirimler",
                    "org_unit_id": unit("İnsan Kaynakları"), "owner": "Nazlı Er", "legal_basis": "legal_obligation",
                    "special_legal_basis": "employment_social_security", "recipients": "SGK; bankalar (maaş ödemesi)",
                    "retention_rule_id": rules["ozluk"], "security_measures": "İK dışı erişim kapalı, yedekler şifreli", "status": "active"},
             ["Kimlik", "Özlük"], ["Çalışan"], [("SAP S/4HANA Üretim", "PA0002")], []),
            ("pazarlama", {"name": "Pazarlama kampanyaları ve e-bülten", "purpose": "Ürün ve hizmet tanıtımı, kampanya duyuruları",
                           "org_unit_id": unit("Operasyon"), "owner": "kerem.aksoy", "legal_basis": "explicit_consent",
                           "recipients": "E-posta gönderim hizmeti sağlayıcısı", "foreign_transfer": 1,
                           "transfer_countries": "ABD (e-posta gönderim hizmeti)", "transfer_mechanism": "none", "profiling": 1,
                           "retention_rule_id": rules["pazarlama"], "status": "active"},
             ["İletişim", "Pazarlama"], ["Müşteri", "Potansiyel Müşteri"],
             [("Pazarlama Dosya Paylaşımı", "bulten_aboneleri.csv"), ("Dynamics 365 CRM", "lead")], [(mail_supplier, "processor", 0)]),
            ("bt", {"name": "BT hizmet masası ve kullanıcı yönetimi", "purpose": "Kullanıcı hesaplarının yönetimi, olay ve taleplerin çözümü",
                    "org_unit_id": unit("BT Altyapı ve Operasyon"), "owner": "mehmet.kaya", "legal_basis": "legitimate_interest",
                    "legal_basis_note": "Denge testi: hizmet sürekliliği ve güvenlik menfaati; yalnızca iş iletişim bilgileri, sınırlı erişim.",
                    "retention_rule_id": rules["bt"], "security_measures": "Merkezi kimlik yönetimi, MFA, kayıt izleme", "status": "draft"},
             ["Kimlik", "İletişim", "İşlem Güvenliği"], ["Çalışan", "Tedarikçi Çalışanı"],
             [("ServiceNow ITSM", "sys_user"), ("ServiceNow ITSM", "incident")], []),
        ]
        for key, values, cat_names, group_names, tables, processors in specs:
            aid = self.add("processing_activities", values, created_days_ago=40)
            acts[key] = aid
            for n in cat_names:
                db.execute("INSERT INTO tdr_processing_categories (activity_id, category_id) VALUES (?,?)", (aid, cats[n]["id"]))
            for n in group_names:
                db.execute("INSERT INTO tdr_processing_subjects (activity_id, subject_group_id) VALUES (?,?)", (aid, groups[n]))
            for source, name in tables:
                t = tbl(source, name)
                if t:
                    db.execute("INSERT INTO tdr_processing_tables (activity_id, table_id) VALUES (?,?)", (aid, t["id"]))
            for supplier, role, dpa in processors:
                if supplier:
                    db.execute("INSERT INTO tdr_processing_processors (activity_id, supplier_id, role, dpa_signed) VALUES (?,?,?,?)",
                               (aid, supplier["id"], role, dpa))
        dpia = self.add("dpias", {"activity_id": acts["crm"], "title": "VKED: CRM ve yurt dışı bulut barındırma",
                                  "necessity": "Müşteri ilişkisinin yürütülmesi için gerekli; veri en aza indirildi.",
                                  "risks": "Yurt dışı aktarımda yetkisiz erişim; büyük ölçekli müşteri verisi",
                                  "measures": "Standart sözleşme, şifreleme, erişim kayıtları, AB bölgesinde barındırma",
                                  "residual_risk": "medium", "decision": "proceed_with_measures"})
        db.execute("UPDATE tdr_dpias SET status='approved', prepared_by='ayse.yilmaz', submitted_at=?, approver='selin.aydin', approved_at=? "
                   "WHERE id=?", (stamp(30), stamp(28), dpia))
        dpia2 = self.add("dpias", {"activity_id": acts["pazarlama"], "title": "VKED: kampanya hedefleme ve profilleme",
                                   "necessity": "Açık rızalı abonelere ilgi alanına göre içerik", "risks": "Profilleme; yurt dışı aktarım güvencesiz",
                                   "measures": "Aktarım mekanizması belirlenecek; segmentler anonimleştirilecek",
                                   "residual_risk": "high", "decision": "proceed_with_measures"})
        db.execute("UPDATE tdr_dpias SET status='in_review', prepared_by='ayse.yilmaz', submitted_at=? WHERE id=?", (stamp(3), dpia2))
        # periyodik imha: tamamlanan (5 ay önce) ve planlanan
        run = self.add("disposal_runs", {"title": "2026 1. dönem periyodik imha", "planned_date": day(-152), "owner": "mehmet.kaya"})
        for t in db.execute("SELECT id, retention_rule_id FROM tdr_data_tables WHERE retention_rule_id IS NOT NULL ORDER BY id").fetchall():
            method = one(db, "SELECT disposal_method FROM tdr_retention_rules WHERE id=?", (t["retention_rule_id"],))["disposal_method"]
            done = t["id"] % 3 != 0
            db.execute("""INSERT INTO tdr_disposal_items (run_id, table_id, rule_id, method, outcome, record_count, note, updated_by,
                updated_at) VALUES (?,?,?,?,?,?,?,?,?)""", (run, t["id"], t["retention_rule_id"], method, "done" if done else "not_needed",
                                                         (t["id"] * 37) % 900 + 20 if done else 0,
                                                         None if done else "Süresi dolan kayıt yok", "mehmet.kaya", stamp(150)))
        db.execute("""UPDATE tdr_disposal_runs SET status='completed', summary=?, performed_by='mehmet.kaya', completed_at=? WHERE id=?""",
                   ("Saklama süresi dolan müşteri, pazarlama ve BT kayıtları silindi veya yok edildi; tutanak imzalandı (sentetik).",
                    stamp(150), run))
        self.add("disposal_runs", {"title": "2026 2. dönem periyodik imha", "planned_date": day(25), "owner": "mehmet.kaya"})
        # veri talepleri
        contact, kna1, pa = tbl("Dynamics 365 CRM", "contact"), tbl("SAP S/4HANA Üretim", "KNA1"), tbl("SAP S/4HANA Üretim", "PA0002")
        r1 = self.add("data_requests", {"kind": "masking", "table_id": contact["id"], "purpose": "UAT ortamına maskeli kopya (sürüm testi)",
                                        "environment": "UAT", "org_unit_id": unit("Uygulama Geliştirme")}, created_days_ago=12)
        db.execute("""UPDATE tdr_data_requests SET requested_by='deniz.koc', status='fulfilled', approver='zeynep.demir', decided_at=?,
            decision_note='Maskeli kopya uygun', fulfilled_by='deniz.koc', fulfilled_at=?, fulfillment_note=? WHERE id=?""",
                   (stamp(11), stamp(9), "Ad, soyad, e-posta ve telefon tutarlı takma değerlerle değiştirildi", r1))
        r2 = self.add("data_requests", {"kind": "access", "table_id": kna1["id"], "purpose": "Dolandırıcılık analizi için müşteri ana "
                                        "verisine süreli salt okunur erişim", "activity_id": acts["crm"], "access_until": day(30),
                                        "org_unit_id": unit("Bilgi Güvenliği")}, created_days_ago=2)
        db.execute("UPDATE tdr_data_requests SET requested_by='okan.yildiz' WHERE id=?", (r2,))
        r3 = self.add("data_requests", {"kind": "extract", "table_id": pa["id"], "purpose": "Eğitim planlaması için çalışan listesi",
                                        "activity_id": acts["ik"], "org_unit_id": unit("Operasyon")}, created_days_ago=6)
        db.execute("""UPDATE tdr_data_requests SET requested_by='kerem.aksoy', status='rejected', approver='selin.aydin', decided_at=?,
            decision_note=? WHERE id=?""", (stamp(5), "Ad soyad yerine personel numarası ve birim yeterli (veri en aza indirme).", r3))
        # ilgili kişi başvuruları
        lead = tbl("Dynamics 365 CRM", "lead")
        for days_ago, kind, channel, group, ref, status, verified, extra in (
                (40, "access", "email", "Müşteri", "CRM-48213", "answered", 1,
                 {"response_date": day(-26), "response_summary": "İşlenen veriler ve amaçlar KEP ile bildirildi."}),
                (12, "erasure", "kep", "Potansiyel Müşteri", "WEB-2026-1187", "in_progress", 1, {}),
                (27, "info", "web", "Çalışan Adayı", "IK-ADAY-0412", "received", 0, {})):
            sid = self.add("subject_requests", {"received_on": day(-days_ago), "request_type": kind, "channel": channel,
                                                "subject_group_id": groups[group], "subject_reference": ref, "identity_verified": verified,
                                                "description": "Sentetik demo başvurusu", "owner": "ayse.yilmaz"})
            db.execute("UPDATE tdr_subject_requests SET status=?, response_date=?, response_summary=? WHERE id=?",
                       (status, extra.get("response_date"), extra.get("response_summary"), sid))
            if kind == "erasure" and lead:
                db.execute("INSERT INTO tdr_subject_request_tables (request_id, table_id) VALUES (?,?)", (sid, lead["id"]))
        breach = one(db, "SELECT id FROM tdr_privacy_breaches WHERE title LIKE ?", ("Müşteri bildirim listesinin%",))
        if breach:
            for t in (contact, tbl("Dynamics 365 CRM", "account")):
                if t:
                    db.execute("INSERT INTO tdr_breach_data_tables (breach_id, table_id, created_by, created_at) VALUES (?,?,?,?) "
                               "ON CONFLICT DO NOTHING", (breach["id"], t["id"], "selin.aydin", utcnow()))
        # en riskli veri varlığını risk kaydına aktar
        kampanya = tbl("Pazarlama Dosya Paylaşımı", "kampanya_katilimcilari_2026.xlsx")
        if kampanya and self.enabled("risks"):
            from .schema import RESOURCES
            score = P.table_risks(db, [kampanya["id"]])[kampanya["id"]]
            risk = crud.insert(db, RESOURCES["supplier_risks"], {
                "title": "Veri varlığı riski: Pazarlama Dosya Paylaşımı / kampanya_katilimcilari_2026.xlsx", "category": "privacy",
                "owner": "kerem.aksoy", "likelihood": score["likelihood"], "impact": score["impact"],
                "cause": "Yönetişim açıkları: " + ", ".join(score["gaps"]),
                "risk_event": "Sahipsiz paylaşımdaki kişisel verinin yetkisiz erişim veya ifşası",
                "consequence": "; ".join(score["factors"]), "entity_name": "Pazarlama Dosya Paylaşımı"}, None)
            db.execute("INSERT INTO tdr_risk_data_tables (risk_id, table_id, created_at) VALUES (?,?,?)", (risk, kampanya["id"], utcnow()))


def RESOURCES_COLUMNS():
    from .modules.datagov import COLUMNS
    return COLUMNS
