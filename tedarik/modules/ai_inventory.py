"""Veri yönetişimi Faz 6 — yapay zekâ sistemleri envanteri ve AB Yapay Zekâ Tüzüğü risk sınıflandırması (K-034).
`datagov` modülünün parçasıdır.

- Envanter: kurumun geliştirdiği, satın aldığı veya hizmet olarak kullandığı her yapay zekâ sistemi; amaç, rol (sağlayıcı /
  kullanıcı), tedarikçi, model türü, genel amaçlı modele dayanma, yaşam döngüsü, sahip, süreç, birim, CMDB öğesi.
- Veri bağlantısı: eğitim, girdi, çıktı ve referans verisi katalogdaki veri varlıklarına bağlanır; bağlı tabloda kişisel
  veri varsa sistem kişisel veri işliyor sayılır (işaretsizse açık olarak gösterilir). Soy kütüğü etki analizi değişen
  tablonun yapay zekâ sistemlerini de listeler.
- Risk sınıfı sihirbazla belirlenir (Tüzük (AB) 2024/1689): md. 5 yasaklı uygulamalar → md. 6(1) ve Ek I ürün güvenliği
  bileşeni → Ek III yüksek riskli alanlar ve md. 6(3) istisnası (profil çıkarmada istisna yok) → md. 50 şeffaflık
  yükümlülükleri → asgari risk. Sonuç, dayanak maddeler ve role göre yükümlülük listesi kayda yazılır; sınıf elle
  girilmez. Sınıflandırma hukuki görüş değildir; tüzüğün yayımlanmış metnine dayanan ön değerlendirmedir.
- Açıklar kural olarak hesaplanır (sınıflandırılmamış, yasaklı ve kullanımda, insan gözetimsiz yüksek risk veya otomatik
  karar, şeffaflık bildirimi yok, kişisel veri işliyor ama işleme envanterinde yok, VKED yok, kayıtların saklama süresi
  6 ayın altında, değerlendirme eski). Sağlık kontrolü ve İşlerim bu açıkları kullanır.
- ISO/IEC 42001 eşlemesi lisanslı metin gerektirir; kurum metni standart kütüphanesine aktarınca maddeler kontrollere
  eşlenir (bu modül metni içermez).
"""
import csv
import io
import json
from datetime import date, timedelta

from .. import audit, auth as authz, crud
from ..db import one, rows, utcnow
from ..http import API, Raw
from ..labels import CHOICES
from ..schema import RESOURCES, Resource, fk
from .datagov import M, _qualified

RISK_CLASSES = ("prohibited", "high", "limited", "minimal", "unassessed")
USAGES = ("training", "fine_tuning", "input", "output", "reference")

SYSTEMS = Resource("ai_systems", "Yapay Zekâ Sistemleri", {
    "code": "TEXT UNIQUE", "name": "TEXT NOT NULL", "purpose": "TEXT NOT NULL", "description": "TEXT",
    "role": "TEXT NOT NULL DEFAULT 'deployer'", "source_type": "TEXT NOT NULL DEFAULT 'vendor'",
    "supplier_id": fk("suppliers", False), "model_type": "TEXT", "gpai_based": "INTEGER NOT NULL DEFAULT 0",
    "deployment": "TEXT", "lifecycle": "TEXT NOT NULL DEFAULT 'idea'", "owner": "TEXT", "technical_owner": "TEXT",
    "process_id": fk("processes", False), "org_unit_id": fk("org_units", False), "ci_id": fk("cmdb_cis", False),
    "affected_persons": "TEXT", "risk_class": "TEXT NOT NULL DEFAULT 'unassessed'", "risk_basis": "TEXT",
    "classification_json": "TEXT", "classified_by": "TEXT", "classified_at": "TIMESTAMP",
    "uses_personal_data": "INTEGER NOT NULL DEFAULT 0", "uses_special_data": "INTEGER NOT NULL DEFAULT 0",
    "automated_decision": "INTEGER NOT NULL DEFAULT 0", "human_oversight": "TEXT",
    "transparency_notice": "INTEGER NOT NULL DEFAULT 0", "log_retention_months": "INTEGER",
    "activity_id": fk("processing_activities", False), "dpia_id": fk("dpias", False), "fria_done_on": "DATE",
    "last_evaluated_on": "DATE", "evaluation_summary": "TEXT", "monitoring": "TEXT", "review_date": "DATE",
    "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL", "updated_at": "TIMESTAMP"},
    module=M, code_prefix="YZS", write="write", search=("code", "name", "purpose"),
    readonly=("risk_class", "risk_basis", "classification_json", "classified_by", "classified_at", "created_by"),
    enums={"role": ("provider", "deployer", "provider_deployer", "importer", "distributor"),
           "source_type": ("in_house", "vendor", "open_source"),
           "model_type": ("classical_ml", "deep_learning", "llm", "computer_vision", "speech", "recommendation", "rules", "other"),
           "deployment": ("saas", "cloud", "on_prem", "hybrid", "edge"),
           "lifecycle": ("idea", "development", "pilot", "production", "retired"), "risk_class": RISK_CLASSES})
SYSTEM_TABLES = Resource("ai_system_tables", "Yapay zekâ sisteminin veri varlıkları", {
    "ai_system_id": fk("ai_systems"), "table_id": fk("data_tables"), "usage": "TEXT NOT NULL DEFAULT 'input'", "note": "TEXT",
    "created_by": "TEXT", "created_at": "TIMESTAMP NOT NULL"},
    module=M, unique=(("ai_system_id", "table_id"),), api=(), search=(), enums={"usage": USAGES})


# ------------------------------------------------------------------ sınıflandırma (Tüzük (AB) 2024/1689)

PROHIBITED = {   # md. 5(1)
    "manipulation": ("a", "Bilinçaltı, kasıtlı manipülatif veya aldatıcı tekniklerle kişinin davranışını önemli ölçüde bozarak zarar vermesi muhtemel karar aldırmak"),
    "vulnerability": ("b", "Yaş, engellilik veya sosyal/ekonomik durumdan kaynaklanan kırılganlıkları istismar ederek davranışı bozmak"),
    "social_scoring": ("c", "Kişileri sosyal davranış veya kişisel özelliklere göre puanlayıp ilgisiz bağlamda ya da orantısız olumsuz muamele (sosyal puanlama)"),
    "crime_prediction": ("d", "Yalnızca profil çıkarma veya kişilik özelliklerine dayanarak kişinin suç işleme riskini tahmin etmek"),
    "face_scraping": ("e", "İnternetten veya kamera kayıtlarından hedefsiz yüz görüntüsü toplayarak yüz tanıma veritabanı oluşturmak"),
    "emotion_workplace": ("f", "İş yerinde veya eğitim kurumunda duygu tanıma (tıbbi veya güvenlik amacı hariç)"),
    "biometric_categorisation": ("g", "Biyometrik veriden ırk, siyasi görüş, sendika üyeliği, din, cinsel yaşam veya yönelim çıkaran sınıflandırma"),
    "realtime_biometric": ("h", "Kamuya açık alanda kolluk amacıyla gerçek zamanlı uzaktan biyometrik tanımlama"),
}
ANNEX_III = {   # Ek III
    "biometrics": ("1", "Biyometri: uzaktan biyometrik tanımlama, hassas özelliklere göre biyometrik sınıflandırma, duygu tanıma"),
    "critical_infrastructure": ("2", "Kritik altyapı (dijital altyapı, trafik, su, gaz, ısınma, elektrik) yönetimi ve işletiminde güvenlik bileşeni"),
    "education": ("3", "Eğitim: kabul ve yerleştirme, öğrenme çıktısını değerlendirme, sınavda kopya izleme"),
    "employment": ("4", "İstihdam: işe alım ve aday eleme, terfi, iş akdinin sona ermesi, görev dağıtımı, performans ve davranış izleme"),
    "public_benefits": ("5(a)", "Kamu yardım ve hizmetlerine uygunluğun değerlendirilmesi, verilmesi veya geri alınması"),
    "credit": ("5(b)", "Kişilerin kredi değerliliğinin veya kredi puanının belirlenmesi (dolandırıcılık tespiti hariç)"),
    "insurance": ("5(c)", "Hayat ve sağlık sigortasında risk değerlendirmesi ve fiyatlama"),
    "emergency": ("5(d)", "Acil çağrıların değerlendirilmesi, acil müdahale birimlerinin yönlendirilmesi ve önceliklendirilmesi, acil hasta triyajı"),
    "law_enforcement": ("6", "Kolluk: mağduriyet riski, delil güvenilirliği, suç veya tekrar suç riski, profil çıkarma"),
    "migration": ("7", "Göç, iltica ve sınır kontrolü: risk değerlendirmesi, başvuru inceleme, kişi tespiti"),
    "justice": ("8", "Yargı ve demokratik süreçler: hukuki araştırma ve yorumda yargıya destek, seçim veya oy davranışını etkileme"),
}
DEROGATIONS = {   # md. 6(3)
    "narrow_procedural": "Dar kapsamlı usule ilişkin bir görevi yerine getiriyor",
    "improve_human": "Önceden tamamlanmış bir insan faaliyetinin sonucunu iyileştiriyor",
    "pattern_detection": "Karar örüntülerini veya sapmaları tespit ediyor; uygun insan incelemesi olmadan insan değerlendirmesinin yerini almıyor",
    "preparatory": "Ek III'teki bir değerlendirme için hazırlık görevi görüyor",
}
TRANSPARENCY = {   # md. 50
    "interacts": ("50(1)", "Kişilerle doğrudan etkileşime giriyor (sohbet botu, sesli asistan)"),
    "synthetic": ("50(2)", "Sentetik ses, görüntü, video veya metin üretiyor"),
    "emotion": ("50(3)", "Duygu tanıma veya biyometrik sınıflandırma yapıyor (yasaklı olmayan bağlamda)"),
    "deepfake": ("50(4)", "Gerçek kişi, nesne veya olaya benzeyen derin sahte (deepfake) içerik üretiyor"),
    "public_text": ("50(4)", "Kamuoyunu ilgilendiren konularda yayımlanan metin üretiyor (insan editör denetimi yoksa)"),
}
OBLIGATIONS = {
    "all": [("md. 4", "Yapay zekâ okuryazarlığı: sistemi işleten ve kullanan personelin yeterli bilgi ve beceriye sahip olmasını sağlayın.")],
    "prohibited": [("md. 5", "Yasaklı uygulama: sistem piyasaya arz edilemez, hizmete sunulamaz ve kullanılamaz; kullanımı durdurun.")],
    "high_provider": [
        ("md. 9", "Yaşam döngüsü boyunca risk yönetim sistemi kurun ve belgeleyin."),
        ("md. 10", "Eğitim, doğrulama ve test verisinde veri yönetişimi: temsil, hata ve yanlılık incelemesi."),
        ("md. 11", "Teknik dokümantasyonu (Ek IV) piyasaya arzdan önce hazırlayın ve güncel tutun."),
        ("md. 12", "Olayların otomatik kaydını (log) sağlayın."),
        ("md. 13", "Kullanıcıya şeffaflık ve kullanım talimatı verin."),
        ("md. 14", "Etkili insan gözetimini tasarımda sağlayın."),
        ("md. 15", "Doğruluk, sağlamlık ve siber güvenlik düzeyini belirleyin ve beyan edin."),
        ("md. 17", "Kalite yönetim sistemi kurun."),
        ("md. 43", "Uygunluk değerlendirmesini yapın; AB uygunluk beyanı (md. 47) ve CE işareti (md. 48)."),
        ("md. 49", "Sistemi AB veritabanına kaydedin."),
        ("md. 72", "Piyasaya arz sonrası izleme planı işletin."),
        ("md. 73", "Ciddi olayları piyasa gözetim otoritesine bildirin."),
    ],
    "high_deployer": [
        ("md. 26(1)", "Sistemi sağlayıcının kullanım talimatına uygun kullanın; teknik ve organizasyonel tedbirleri alın."),
        ("md. 26(2)", "İnsan gözetimini yetkin, eğitimli ve yetkili kişilere atayın."),
        ("md. 26(4)", "Kontrolünüzdeki girdi verisinin amaca uygun ve yeterince temsil edici olmasını sağlayın."),
        ("md. 26(5)", "Çalışmayı izleyin; risk veya ciddi olayda sağlayıcıyı ve otoriteyi bilgilendirin, kullanımı askıya alın."),
        ("md. 26(6)", "Otomatik üretilen kayıtları en az 6 ay saklayın."),
        ("md. 26(7)", "İş yerinde kullanmadan önce çalışanları ve temsilcilerini bilgilendirin."),
        ("md. 26(11)", "Hakkında karar verilen kişileri yüksek riskli sistem kullanıldığı konusunda bilgilendirin."),
        ("md. 86", "Kişinin, karara ilişkin açıklama isteme hakkını karşılayacak süreci kurun."),
    ],
    "fria": [("md. 27", "Kullanıma başlamadan önce temel haklara etki değerlendirmesi (FRIA) yapın ve sonucu otoriteye bildirin.")],
    "derogation": [("md. 6(4)", "Ek III kapsamında olup yüksek riskli sayılmadığına ilişkin değerlendirmeyi piyasaya arzdan önce belgeleyin; "
                                "sağlayıcı olarak sistemi kaydedin (md. 49(2)).")],
    "minimal": [("md. 95", "Asgari risk: zorunlu yükümlülük yok; gönüllü davranış kurallarını uygulayabilirsiniz.")],
    "gpai_provider": [("md. 53", "Genel amaçlı model sağlayıcısı: teknik dokümantasyon, alt sağlayıcıya bilgi, telif politikası ve eğitim "
                                 "içeriği özeti.")],
}
TRANSPARENCY_OBLIGATION = {
    "interacts": "Kişilere bir yapay zekâ sistemiyle etkileşimde olduklarını bildirin (bağlamdan açık değilse).",
    "synthetic": "Üretilen içeriği makinece okunabilir biçimde yapay olarak işaretleyin (sağlayıcı).",
    "emotion": "Maruz kalan kişileri sistemin çalıştığı konusunda bilgilendirin; kişisel veriyi KVKK/GDPR'a uygun işleyin.",
    "deepfake": "İçeriğin yapay olarak üretildiğini veya değiştirildiğini açıklayın.",
    "public_text": "Metnin yapay zekâ ile üretildiğini açıklayın (insan editör denetimi ve sorumluluğu yoksa).",
}
TIMELINE = [
    {"date": "2025-02-02", "text": "Yasaklı uygulamalar (md. 5) ve yapay zekâ okuryazarlığı (md. 4) uygulanıyor."},
    {"date": "2025-08-02", "text": "Genel amaçlı yapay zekâ modeli yükümlülükleri ve yaptırımlar uygulanıyor."},
    {"date": "2026-08-02", "text": "Ek III yüksek riskli sistemler ve şeffaflık yükümlülükleri (md. 50) dâhil genel uygulama tarihi."},
    {"date": "2027-08-02", "text": "Ek I kapsamındaki ürünlerin güvenlik bileşeni olan yüksek riskli sistemler (md. 6(1))."},
]
TIMELINE_NOTE = ("Tarihler Tüzüğün yayımlanmış metnine (md. 113) göredir. Uygulama tarihlerini erteleyen değişiklik önerileri "
                 "olabilir; yürürlükteki metni Resmî Gazete'den (EUR-Lex) doğrulayın.")


def _selected(values, allowed, label):
    if values in (None, ""):
        return []
    if not isinstance(values, list) or any(v not in allowed for v in values):
        raise crud.Invalid(f"{label}: tanımsız seçenek")
    return sorted(set(values), key=list(allowed).index)


def classify(answers, role="deployer"):
    """Sihirbaz yanıtlarından risk sınıfı, dayanak ve yükümlülükler. Saf işlev (test edilebilir)."""
    if not isinstance(answers, dict):
        raise crud.Invalid("Yanıtlar nesne olmalı")
    prohibited = _selected(answers.get("prohibited"), PROHIBITED, "Yasaklı uygulamalar")
    annex = _selected(answers.get("annex_iii"), ANNEX_III, "Ek III alanları")
    transparency = _selected(answers.get("transparency"), TRANSPARENCY, "Şeffaflık")
    derogation = answers.get("derogation") or None
    if derogation is not None and derogation not in DEROGATIONS:
        raise crud.Invalid("md. 6(3) istisnası tanımsız")
    product, profiling, public = bool(answers.get("product_safety")), bool(answers.get("profiling")), bool(answers.get("public_service"))
    provider = role in ("provider", "provider_deployer")
    deployer = role in ("deployer", "provider_deployer", "importer", "distributor")
    basis, obligations, fria = [], list(OBLIGATIONS["all"]), False
    if prohibited:
        risk = "prohibited"
        basis += [f"md. 5(1)({PROHIBITED[k][0]}): {PROHIBITED[k][1]}" for k in prohibited]
        obligations += OBLIGATIONS["prohibited"]
    else:
        high = False
        if product:
            high = True
            basis.append("md. 6(1) ve Ek I: üçüncü taraf uygunluk değerlendirmesine tabi bir ürünün güvenlik bileşeni veya ürünün kendisi")
        if annex:
            basis += [f"Ek III madde {ANNEX_III[k][0]}: {ANNEX_III[k][1]}" for k in annex]
            if derogation and not profiling:
                basis.append(f"md. 6(3) istisnası: {DEROGATIONS[derogation]}; önemli zarar riski yok, profil çıkarma yok")
                obligations += OBLIGATIONS["derogation"]
            else:
                if derogation and profiling:
                    basis.append("md. 6(3) istisnası uygulanamaz: sistem gerçek kişilerin profilini çıkarıyor")
                high = True
        if high:
            risk = "high"
            if provider:
                obligations += OBLIGATIONS["high_provider"]
            if deployer:
                obligations += OBLIGATIONS["high_deployer"]
                fria = public or bool({"credit", "insurance"} & set(annex))
                if fria:
                    obligations += OBLIGATIONS["fria"]
        elif transparency:
            risk = "limited"
        else:
            risk = "minimal"
    if transparency and risk != "prohibited":
        basis += [f"md. {TRANSPARENCY[k][0]}: {TRANSPARENCY[k][1]}" for k in transparency]
        obligations += [(f"md. {TRANSPARENCY[k][0]}", TRANSPARENCY_OBLIGATION[k]) for k in transparency]
    if risk == "minimal":
        basis.append("Yasaklı uygulama, yüksek riskli alan veya şeffaflık yükümlülüğü tetikleyen kullanım işaretlenmedi")
        obligations += OBLIGATIONS["minimal"]
    if answers.get("gpai_provider"):
        obligations += OBLIGATIONS["gpai_provider"]
    seen, unique = set(), []
    for ref, text in obligations:
        if (ref, text) not in seen:
            seen.add((ref, text))
            unique.append({"ref": ref, "text": text})
    return {"risk_class": risk, "basis": basis, "obligations": unique, "fria_required": fria,
            "answers": {"prohibited": prohibited, "product_safety": product, "annex_iii": annex, "derogation": derogation,
                        "profiling": profiling, "public_service": public, "transparency": transparency,
                        "gpai_provider": bool(answers.get("gpai_provider"))}}


def questions():
    return {"prohibited": [{"key": k, "ref": f"md. 5(1)({v[0]})", "text": v[1]} for k, v in PROHIBITED.items()],
            "annex_iii": [{"key": k, "ref": f"Ek III {v[0]}", "text": v[1]} for k, v in ANNEX_III.items()],
            "derogation": [{"key": k, "text": v} for k, v in DEROGATIONS.items()],
            "transparency": [{"key": k, "ref": f"md. {v[0]}", "text": v[1]} for k, v in TRANSPARENCY.items()],
            "timeline": TIMELINE, "timeline_note": TIMELINE_NOTE}


# ------------------------------------------------------------------ açıklar

def _personal_tables(db, system_id):
    return rows(db, """SELECT DISTINCT t.id, t.schema_name, t.name, m.usage,
        SUM(CASE WHEN c.personal_data='special' THEN 1 ELSE 0 END) AS special,
        SUM(CASE WHEN c.personal_data IN ('personal','special') THEN 1 ELSE 0 END) AS personal
        FROM tdr_ai_system_tables m JOIN tdr_data_tables t ON t.id=m.table_id
        LEFT JOIN tdr_data_columns c ON c.table_id=t.id AND c.status='active'
        WHERE m.ai_system_id=? GROUP BY t.id, t.schema_name, t.name, m.usage ORDER BY t.name""", (system_id,))


def gaps(db, s, tables=None):
    """Sistemin açıkları: her madde kural, açıklama, önem ve dayanak taşır."""
    tables = _personal_tables(db, s["id"]) if tables is None else tables
    out = []

    def gap(key, text, severity, ref=None):
        out.append({"key": key, "text": text, "severity": severity, "ref": ref})
    active = s["lifecycle"] != "retired"
    risk = s["risk_class"]
    personal = bool(s["uses_personal_data"]) or any(t["personal"] for t in tables)
    if not active:
        return out
    if risk == "unassessed":
        gap("unassessed", "Risk sınıfı belirlenmemiş; sınıflandırma sihirbazını çalıştırın.", "high", "Tüzük md. 6")
    if risk == "prohibited":
        gap("prohibited", "Yasaklı uygulama olarak sınıflandı; sistem kullanılamaz.", "critical", "Tüzük md. 5")
    if not (s["owner"] or "").strip():
        gap("owner", "Sistemin iş sahibi atanmamış.", "medium")
    if risk == "high" and not (s["human_oversight"] or "").strip():
        gap("oversight", "Yüksek riskli sistemde insan gözetimi (kim, nasıl müdahale eder) tanımlı değil.", "high", "Tüzük md. 14, 26(2)")
    if s["automated_decision"] and not (s["human_oversight"] or "").strip():
        gap("automated", "Kişi hakkında otomatik karar veriyor; insan müdahalesi ve itiraz yolu tanımlı değil.", "high",
            "KVKK md. 11(1)(g), GDPR Art. 22")
    if risk == "high" and (s["log_retention_months"] is None or s["log_retention_months"] < 6):
        gap("logs", "Otomatik üretilen kayıtların saklama süresi 6 aydan az veya belirtilmemiş.", "medium", "Tüzük md. 26(6)")
    if risk == "high" and s["role"] in ("deployer", "provider_deployer") and not s["fria_done_on"]:
        cls = json.loads(s["classification_json"] or "{}")
        if cls.get("fria_required"):
            gap("fria", "Temel haklara etki değerlendirmesi (FRIA) yapılmamış.", "high", "Tüzük md. 27")
    if risk in ("high", "limited") and not s["transparency_notice"]:
        gap("transparency", "Kişilere yapay zekâ kullanıldığı bildirilmiyor (bildirim işaretli değil).", "medium",
            "Tüzük md. 50, 26(11)")
    if risk == "high" and (not s["last_evaluated_on"] or str(s["last_evaluated_on"])[:10] < (date.today() - timedelta(days=366)).isoformat()):
        gap("evaluation", "Son 12 ayda doğruluk, sağlamlık ve yanlılık değerlendirmesi kaydı yok.", "medium", "Tüzük md. 9, 15, 26(5)")
    if personal and not s["uses_personal_data"]:
        names = ", ".join(_qualified(t["schema_name"], t["name"]) for t in tables if t["personal"])[:300]
        gap("personal_flag", f"Bağlı veri varlıklarında kişisel veri var ({names}); sistem kişisel veri işliyor olarak işaretli değil.",
            "medium")
    if personal and not s["activity_id"]:
        gap("activity", "Kişisel veri işliyor; işleme envanterinde (VERBİS) faaliyete bağlı değil.", "high", "KVKK md. 16, GDPR Art. 30")
    if personal and (risk == "high" or s["automated_decision"] or s["uses_special_data"]) and not s["dpia_id"]:
        gap("dpia", "Kişisel veri, yüksek risk veya otomatik kararda veri koruma etki değerlendirmesi (VKED) bağlı değil.", "medium",
            "GDPR Art. 35")
    if s["source_type"] == "vendor" and not s["supplier_id"]:
        gap("supplier", "Satın alınan sistemin tedarikçisi seçilmemiş (sözleşme, DPA ve tedarikçi riski izlenemez).", "low")
    if s["lifecycle"] in ("pilot", "production") and not tables:
        gap("data", "Sistemin eğitim veya girdi verisi katalogdaki veri varlıklarına bağlanmamış.", "low", "Tüzük md. 10")
    if s["review_date"] and str(s["review_date"])[:10] < date.today().isoformat():
        gap("review", "Gözden geçirme tarihi geçmiş.", "low")
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return sorted(out, key=lambda g: order[g["severity"]])


# ------------------------------------------------------------------ kurallar

def _rules(db, data, current, principal):
    merged = {**(current or {}), **data}
    if current is None:
        data["created_by"] = principal.username if principal else "system"
    if merged.get("uses_special_data") and not merged.get("uses_personal_data"):
        data["uses_personal_data"] = 1
    if merged.get("log_retention_months") is not None and not 0 <= merged["log_retention_months"] <= 600:
        raise crud.Invalid("Kayıt saklama süresi 0–600 ay olmalı")
    if merged.get("dpia_id") and merged.get("activity_id"):
        d = one(db, "SELECT activity_id FROM tdr_dpias WHERE id=?", (merged["dpia_id"],))
        if d and d["activity_id"] != merged["activity_id"]:
            raise crud.Invalid("Seçilen VKED başka bir işleme faaliyetine ait")


def _scope(db, record):
    return [record.get("org_unit_id")]


SYSTEMS.before_save = _rules
SYSTEMS.scope = _scope


# ------------------------------------------------------------------ uç noktalar

def _can_write(principal, record=None, db=None):
    if principal.auth_type in ("api_key", "collector") or not authz.can_write(principal, SYSTEMS):
        return False
    if record is not None and principal.role == "UNIT_USER":
        return record.get("org_unit_id") in principal.units
    return True


def _summary(db):
    systems = rows(db, "SELECT * FROM tdr_ai_systems ORDER BY code")
    links = {}
    for t in rows(db, """SELECT m.ai_system_id, t.id, t.schema_name, t.name, m.usage,
            SUM(CASE WHEN c.personal_data='special' THEN 1 ELSE 0 END) AS special,
            SUM(CASE WHEN c.personal_data IN ('personal','special') THEN 1 ELSE 0 END) AS personal
            FROM tdr_ai_system_tables m JOIN tdr_data_tables t ON t.id=m.table_id
            LEFT JOIN tdr_data_columns c ON c.table_id=t.id AND c.status='active'
            GROUP BY m.ai_system_id, t.id, t.schema_name, t.name, m.usage"""):
        links.setdefault(t["ai_system_id"], []).append(t)
    out = []
    for s in systems:
        g = gaps(db, s, links.get(s["id"], []))
        out.append({**s, "gaps": g, "gap_count": len(g), "top_severity": g[0]["severity"] if g else None,
                    "tables": len(links.get(s["id"], [])), "personal": bool(s["uses_personal_data"]) or any(
                        t["personal"] for t in links.get(s["id"], []))})
    return out


def overview(c):
    authz.check(c.principal, SYSTEMS, "read")
    systems = _summary(c.db)
    active = [s for s in systems if s["lifecycle"] != "retired"]
    by_class = {k: sum(1 for s in active if s["risk_class"] == k) for k in RISK_CLASSES}
    suppliers = {r["id"]: r["name"] for r in rows(c.db, "SELECT id, name FROM tdr_suppliers WHERE id IN (SELECT supplier_id FROM "
                                                        "tdr_ai_systems WHERE supplier_id IS NOT NULL)")}
    for s in systems:
        s["supplier_name"] = suppliers.get(s["supplier_id"])
    return {"systems": systems, "by_class": by_class, "active": len(active),
            "gaps": sum(s["gap_count"] for s in active), "personal": sum(1 for s in active if s["personal"]),
            "automated": sum(1 for s in active if s["automated_decision"]),
            "gpai": sum(1 for s in active if s["gpai_based"]), "questions": questions(),
            "can_write": _can_write(c.principal)}


def context(c):
    authz.check(c.principal, SYSTEMS, "read")
    db = c.db
    s = crud.get(db, SYSTEMS, c.params["id"])
    tables = _personal_tables(db, s["id"])
    detail = rows(db, """SELECT m.table_id, m.usage, m.note, t.schema_name, t.name, t.business_name, t.classification,
        t.row_count, ds.id AS source_id, ds.name AS source_name FROM tdr_ai_system_tables m JOIN tdr_data_tables t ON t.id=m.table_id
        JOIN tdr_data_sources ds ON ds.id=t.source_id WHERE m.ai_system_id=? ORDER BY m.usage, ds.name, t.name""", (s["id"],))
    flags = {t["id"]: t for t in tables}
    for d in detail:
        f = flags.get(d["table_id"]) or {}
        d["personal"], d["special"] = f.get("personal") or 0, f.get("special") or 0
    cls = json.loads(s["classification_json"]) if s["classification_json"] else None

    def ref(table, rid, cols="id, code, name"):
        return one(db, f"SELECT {cols} FROM {table} WHERE id=?", (rid,)) if rid else None
    return {"system": s, "gaps": gaps(db, s, tables), "classification": cls, "questions": questions(), "tables": detail,
            "supplier": ref("tdr_suppliers", s["supplier_id"]), "process": ref("tdr_processes", s["process_id"]),
            "org_unit": ref("tdr_org_units", s["org_unit_id"], "id, name"), "ci": ref("tdr_cmdb_cis", s["ci_id"], "id, name"),
            "activity": ref("tdr_processing_activities", s["activity_id"], "id, code, name, legal_basis, status"),
            "dpia": ref("tdr_dpias", s["dpia_id"], "id, code, title, status"),
            "can_write": _can_write(c.principal, s)}


def classify_route(c):
    authz.require_human(c.principal)
    authz.check(c.principal, SYSTEMS, "write")
    db = c.db
    s = crud.get(db, SYSTEMS, c.params["id"])
    crud.check_scope(db, SYSTEMS, c.principal, s)
    result = classify(c.body.get("answers") or {}, s["role"])
    now = utcnow()
    stored = {**result, "classified_by": c.principal.username, "classified_at": now}
    db.execute("""UPDATE tdr_ai_systems SET risk_class=?, risk_basis=?, classification_json=?, classified_by=?, classified_at=?,
        updated_at=? WHERE id=?""", (result["risk_class"], "\n".join(result["basis"])[:4000], json.dumps(stored, ensure_ascii=False),
                                     c.principal.username, now, now, s["id"]))
    audit.log(db, c.principal, "CLASSIFY", "ai_systems", s["id"], {"from": s["risk_class"], "to": result["risk_class"],
                                                                     "answers": result["answers"]})
    return result


def tables_route(c):
    """Sistemin veri varlıklarını verilen listeyle eşitler: [{table_id, usage, note}]."""
    authz.require_human(c.principal)
    authz.check(c.principal, SYSTEMS, "write")
    db = c.db
    s = crud.get(db, SYSTEMS, c.params["id"])
    crud.check_scope(db, SYSTEMS, c.principal, s)
    items = c.body.get("items")
    if not isinstance(items, list) or len(items) > 200:
        raise crud.Invalid("items: en çok 200 veri varlığı listesi olmalı")
    wanted = {}
    for it in items:
        tid = it.get("table_id") if isinstance(it, dict) else None
        usage = (it or {}).get("usage") or "input"
        if type(tid) is not int or usage not in USAGES:
            raise crud.Invalid("Her kalemde table_id (tamsayı) ve geçerli kullanım gerekli")
        if not one(db, "SELECT 1 AS x FROM tdr_data_tables WHERE id=? AND status<>'removed'", (tid,)):
            raise crud.Invalid(f"Veri varlığı bulunamadı: {tid}")
        wanted[tid] = (usage, str(it.get("note") or "").strip()[:500] or None)
    current = {r["table_id"]: r for r in rows(db, "SELECT * FROM tdr_ai_system_tables WHERE ai_system_id=?", (s["id"],))}
    now = utcnow()
    for tid in set(current) - set(wanted):
        db.execute("DELETE FROM tdr_ai_system_tables WHERE ai_system_id=? AND table_id=?", (s["id"], tid))
    for tid, (usage, note) in wanted.items():
        if tid in current:
            if (current[tid]["usage"], current[tid]["note"]) != (usage, note):
                db.execute("UPDATE tdr_ai_system_tables SET usage=?, note=? WHERE ai_system_id=? AND table_id=?",
                           (usage, note, s["id"], tid))
        else:
            db.execute("INSERT INTO tdr_ai_system_tables (ai_system_id, table_id, usage, note, created_by, created_at) "
                       "VALUES (?,?,?,?,?,?)", (s["id"], tid, usage, note, c.principal.username, now))
    db.execute("UPDATE tdr_ai_systems SET updated_at=? WHERE id=?", (now, s["id"]))
    audit.log(db, c.principal, "LINK", "ai_systems", s["id"], {"tables": {str(k): v[0] for k, v in wanted.items()}})
    c.params = {"id": s["id"]}
    return context(c)


def table_systems(c):
    authz.check(c.principal, SYSTEMS, "read")
    crud.get(c.db, RESOURCES["data_tables"], c.params["id"])
    return rows(c.db, """SELECT s.id, s.code, s.name, s.risk_class, s.lifecycle, s.owner, m.usage FROM tdr_ai_system_tables m
        JOIN tdr_ai_systems s ON s.id=m.ai_system_id WHERE m.table_id=? ORDER BY s.code""", (c.params["id"],))


def export(c):
    authz.check(c.principal, SYSTEMS, "read")
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Kod", "Ad", "Amaç", "Rol", "Kaynak", "Tedarikçi", "Model türü", "Genel amaçlı modele dayanıyor", "Yaşam döngüsü",
                "Sahip", "Risk sınıfı", "Dayanak", "Kişisel veri", "Otomatik karar", "İnsan gözetimi", "Açık sayısı", "Açıklar"])
    lab = lambda key, v: CHOICES.get(f"ai_systems.{key}", CHOICES.get(key, {})).get(v, v or "")   # noqa: E731
    for s in overview(c)["systems"]:
        w.writerow([s["code"], s["name"], s["purpose"], lab("role", s["role"]), lab("source_type", s["source_type"]),
                    s["supplier_name"] or "", lab("model_type", s["model_type"]), "Evet" if s["gpai_based"] else "Hayır",
                    lab("lifecycle", s["lifecycle"]), s["owner"] or "", lab("risk_class", s["risk_class"]),
                    (s["risk_basis"] or "").replace("\n", " | "), "Evet" if s["personal"] else "Hayır",
                    "Evet" if s["automated_decision"] else "Hayır", s["human_oversight"] or "", s["gap_count"],
                    " | ".join(g["text"] for g in s["gaps"])])
    audit.log(c.db, c.principal, "EXPORT", "ai_systems", None, {"format": "csv"})
    return 200, Raw(("﻿" + buf.getvalue()).encode("utf-8"), "text/csv; charset=utf-8", "yapay-zeka-envanteri.csv")


def impact_systems(db, table_ids):
    """Soy kütüğü etki analizi için: tablolardan veri alan yapay zekâ sistemleri."""
    if not table_ids:
        return []
    marks = ",".join("?" * len(table_ids))
    return rows(db, f"""SELECT DISTINCT s.id, s.code, s.name, s.risk_class, s.owner, s.lifecycle FROM tdr_ai_system_tables m
        JOIN tdr_ai_systems s ON s.id=m.ai_system_id WHERE m.table_id IN ({marks}) AND s.lifecycle<>'retired' ORDER BY s.code""",
                table_ids)


def my_work_items(db, principal, names):
    marks = ",".join("?" * len(names))
    soon = (date.today() + timedelta(days=30)).isoformat()
    items = []
    for s in rows(db, f"""SELECT * FROM tdr_ai_systems WHERE lifecycle<>'retired' AND (owner IN ({marks})
            OR technical_owner IN ({marks})) ORDER BY code""", (*names, *names)):
        g = [x for x in gaps(db, s) if x["severity"] in ("critical", "high")]
        due = s["review_date"] and str(s["review_date"])[:10] <= soon
        if g or due:
            items.append({"id": s["id"], "code": s["code"], "title": s["name"],
                          "detail": g[0]["text"] if g else f"Gözden geçirme {str(s['review_date'])[:10]}"})
    return {"ai_systems": items}


def health_checks(db, check, count, readable=lambda name: True):
    if not readable("ai_systems"):
        return []
    population = count(db, "SELECT COUNT(*) AS n FROM tdr_ai_systems WHERE lifecycle<>'retired'")
    active = rows(db, "SELECT * FROM tdr_ai_systems WHERE lifecycle<>'retired' ORDER BY code")
    found = {k: [] for k in ("unassessed", "prohibited", "oversight", "activity")}
    for s in active:
        keys = {g["key"] for g in gaps(db, s)}
        for k in found:
            if k in keys or (k == "oversight" and "automated" in keys):
                found[k].append({"id": s["id"], "code": s["code"], "title": s["name"]})
    return [
        check("ai_prohibited", "Yasaklı uygulama olarak sınıflanan ve kullanımdan kalkmamış yapay zekâ sistemleri",
              "AB Yapay Zekâ Tüzüğü md. 5'teki uygulamalar 2 Şubat 2025'ten beri yasaktır; en yüksek idari para cezası bu gruptadır.",
              "critical", found["prohibited"], "ai_systems", link="ai", population=population),
        check("ai_unassessed", "Risk sınıfı belirlenmemiş yapay zekâ sistemleri",
              "Sınıf belirlenmeden yükümlülükler (insan gözetimi, şeffaflık, kayıt, FRIA) bilinemez.",
              "medium", found["unassessed"], "ai_systems", link="ai", population=population),
        check("ai_oversight", "İnsan gözetimi tanımlanmamış yüksek riskli veya otomatik karar veren yapay zekâ sistemleri",
              "Yüksek riskli sistemde insan gözetimi zorunludur (Tüzük md. 14, 26); kişi hakkında otomatik kararda itiraz ve insan "
              "müdahalesi hakkı vardır (KVKK md. 11, GDPR Art. 22).", "high", found["oversight"], "ai_systems", link="ai",
              population=population),
        check("ai_personal_no_activity", "Kişisel veri işleyip işleme envanterinde olmayan yapay zekâ sistemleri",
              "Yapay zekâ sisteminin kişisel veri işlemesi de bir işleme faaliyetidir; amaç ve hukuki sebep envanterde olmalı.",
              "high", found["activity"], "ai_systems", link="ai", population=population),
    ]


def register(app):
    app.route("GET", API + "/datagov/ai", overview)
    app.route("GET", API + "/datagov/ai/export", export)
    app.route("GET", API + "/ai_systems/{id}/context", context)
    app.route("POST", API + "/ai_systems/{id}/classify", classify_route)
    app.route("POST", API + "/ai_systems/{id}/tables", tables_route)
    app.route("GET", API + "/data_tables/{id}/ai-systems", table_systems)
