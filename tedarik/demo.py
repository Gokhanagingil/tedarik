"""Sentetik demo verisi: portalı uçtan uca denemek için tutarlı, gerçekçi ama tamamen uydurma bir şirket.

    python -m tedarik.demo            # boş veritabanına yükler; demo kullanıcıların geçici parolalarını yazar

Kurallar
- Hiçbir kayıt gerçek bir firmayı veya kişiyi temsil etmez. Tedarikçi kodları `DMO-` ile başlar, açıklamalar
  "Sentetik demo verisi" der, e-postalar `ornek.test` alan adındadır, VKN'ler rastgeledir.
- Yalnızca tedarikçisi olmayan (boş) bir veritabanına yüklenir; tekrar çalıştırmak bir şey yapmaz.
- Sabit tohumla (seed) üretilir: aynı sürüm her yerde aynı veriyi üretir. Tarihler bugüne göre kaydırılır.
- İş kuralları atlanmaz: risk hesabı, SLA "hedef tuttu" hesabı ve anket puanı uygulamanın kendi işlevleriyle
  yapılır; değiştirilemez tablolara (değerlendirme, karar, anket yanıtı) yalnızca ekleme yapılır.
"""
import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from . import audit, crud
from .auth import Principal
from .config import Config
from .db import one, rows
from .demo_assurance import ASSURANCE_SECTIONS, AssuranceSections
from .demo_datagov import DATAGOV_SECTIONS, DatagovSections
from .demo_platform import SECTIONS as PLATFORM_SECTIONS, PlatformSections
from .schema import RESOURCES

TAG = "Sentetik demo verisi"
SYSTEM = Principal("demo-seed", "ADMIN", "system", "Demo yükleyici")
TODAY = date.today()


def stamp(days_ago, hour=10):
    moment = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).replace(hour=hour, tzinfo=timezone.utc)
    return moment.isoformat(timespec="seconds")


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


UNITS = [("TEK", "Teknoloji Grubu", None, "Selin Aydın"), ("BTA", "BT Altyapı ve Operasyon", "TEK", "Mehmet Kaya"),
         ("UYG", "Uygulama Geliştirme", "TEK", "Deniz Koç"), ("BGV", "Bilgi Güvenliği", "TEK", "Okan Yıldız"),
         ("MHZ", "Müşteri Hizmetleri", None, "Zeynep Demir"), ("OPS", "Operasyon", None, "Kerem Aksoy"),
         ("FIN", "Finans", None, "Ayla Çetin"), ("IKA", "İnsan Kaynakları", None, "Nazlı Er"),
         ("HKK", "Hukuk ve Uyum", None, "Emre Tan"), ("SAT", "Satın Alma", None, "Ayşe Yılmaz")]

# kod, ad, tür, kategori, tedarikçi tipi kodu
CATALOG = [
    ("DC-BAR", "Veri merkezi barındırma (colocation)", "service", "Altyapı", "FACILITY"),
    ("BLT-IAAS", "Bulut altyapı hizmeti (IaaS)", "service", "Bulut", "CLOUD"),
    ("BLT-SAAS-CRM", "CRM yazılım hizmeti (SaaS)", "service", "Bulut", "CLOUD"),
    ("YED-HIZ", "Yedekleme ve felaket kurtarma hizmeti", "service", "Altyapı", "CLOUD"),
    ("SOC", "Güvenlik operasyon merkezi (SOC) izleme", "service", "Bilgi güvenliği", "CONSULT"),
    ("PEN-TEST", "Sızma testi", "service", "Bilgi güvenliği", "CONSULT"),
    ("EPOSTA-GUV", "E-posta güvenliği", "service", "Bilgi güvenliği", "SW"),
    ("ERP-LIS", "ERP lisansı ve bakım", "product", "Yazılım", "SW"),
    ("OFIS-LIS", "Ofis yazılımı lisansları", "product", "Yazılım", "SW"),
    ("DB-LIS", "Veritabanı lisansı ve destek", "product", "Yazılım", "SW"),
    ("YZL-DIS", "Yazılım geliştirme dış kaynak ekibi", "service", "Dış kaynak", "OUTSOURCE"),
    ("TEST-DIS", "Test ve kalite güvence dış kaynak", "service", "Dış kaynak", "OUTSOURCE"),
    ("CAGRI", "Çağrı merkezi hizmeti", "service", "Dış kaynak", "OUTSOURCE"),
    ("NET-BAK", "Ağ cihazları bakım ve destek", "service", "Bakım", "SUPPORT"),
    ("SUN-BAK", "Sunucu ve depolama bakım", "service", "Bakım", "SUPPORT"),
    ("SUN-HW", "Sunucu donanımı", "product", "Donanım", "HW"),
    ("PC-HW", "Dizüstü bilgisayar tedariki", "product", "Donanım", "HW"),
    ("MPLS", "Kurumsal MPLS ve internet hattı", "service", "Telekom", "TELCO"),
    ("MOBIL", "Kurumsal mobil hat", "service", "Telekom", "TELCO"),
    ("KVKK-DAN", "KVKK uyum danışmanlığı", "service", "Danışmanlık", "CONSULT"),
    ("BT-DENETIM", "Bağımsız BT denetimi", "service", "Danışmanlık", "CONSULT"),
    ("KARGO", "Kargo ve kurye", "service", "Lojistik", "SUPPORT"),
    ("ARSIV", "Fiziksel arşiv hizmeti", "service", "Tesis", "FACILITY"),
    ("TEMIZLIK", "Ofis temizlik hizmeti", "service", "Tesis", "FACILITY"),
    ("GUVENLIK", "Fiziksel güvenlik görevlisi", "service", "Tesis", "FACILITY"),
    ("EGITIM", "Kurumsal eğitim", "service", "İnsan kaynakları", "CONSULT"),
    ("SMS", "Toplu SMS ağ geçidi", "service", "Telekom", "TELCO"),
    ("ODEME-GW", "Ödeme altyapısı (sanal POS)", "service", "Finansal hizmet", "CLOUD"),
]

PREFIX = ["Anadolu", "Boğaziçi", "Ege", "Kapadokya", "Marmara", "Toros", "Fırat", "Uludağ", "Akdeniz", "Karadeniz",
          "Trakya", "Erciyes", "Kaçkar", "Nemrut", "Munzur", "Ilgaz", "Palandöken", "Süphan", "Bozdağ", "Köroğlu",
          "Yıldız", "Dicle", "Çoruh", "Sakarya", "Gediz", "Menderes", "Aras", "Kızılırmak", "Yeşilırmak", "Ceyhan"]
SUFFIX = {"FACILITY": ["Veri Merkezi A.Ş.", "Tesis Hizmetleri Ltd. Şti.", "Arşiv Yönetimi A.Ş."],
          "CLOUD": ["Bulut Teknolojileri A.Ş.", "Bilişim Hizmetleri A.Ş.", "Dijital Altyapı A.Ş."],
          "CONSULT": ["Danışmanlık A.Ş.", "Siber Güvenlik Ltd. Şti.", "Denetim ve Danışmanlık A.Ş."],
          "SW": ["Yazılım A.Ş.", "Lisans ve Çözüm Ltd. Şti.", "Teknoloji A.Ş."],
          "OUTSOURCE": ["İnsan Kaynakları ve Dış Kaynak A.Ş.", "Yazılım Hizmetleri A.Ş.", "Çağrı Merkezi A.Ş."],
          "SUPPORT": ["Bilgi Sistemleri Destek Ltd. Şti.", "Lojistik A.Ş.", "Teknik Servis A.Ş."],
          "HW": ["Donanım Dağıtım A.Ş.", "Bilgisayar Sistemleri A.Ş."],
          "TELCO": ["İletişim Hizmetleri A.Ş.", "Telekomünikasyon A.Ş."]}
CITIES = ["İstanbul", "İstanbul", "İstanbul", "Ankara", "Ankara", "İzmir", "Bursa", "Kocaeli", "Antalya", "Eskişehir"]

USERS = [("ayse.yilmaz", "Ayşe Yılmaz", "SUPPLIER_MANAGER", ["SAT"]),
         ("mehmet.kaya", "Mehmet Kaya", "UNIT_USER", ["BTA"]),
         ("deniz.koc", "Deniz Koç", "UNIT_USER", ["UYG"]),
         ("okan.yildiz", "Okan Yıldız", "UNIT_USER", ["BGV"]),
         ("zeynep.demir", "Zeynep Demir", "UNIT_USER", ["MHZ"]),
         ("kerem.aksoy", "Kerem Aksoy", "UNIT_USER", ["OPS"]),
         ("can.ozturk", "Can Öztürk", "AUDITOR", []),
         ("elif.sahin", "Elif Şahin", "VIEWER", []),
         ("selin.aydin", "Selin Aydın", "ADMIN", [])]


COMMENTS = ["Aylık hizmet raporları daha düzenli ve zamanında gelmeli.", "İletişim hızlı ve çözüm odaklı.",
            "Yoğun dönemlerde yanıt süresi belirgin şekilde uzuyor.", "Fatura kalemleri sözleşme kalemleriyle eşleşmiyor.",
            "Teknik ekip yetkin ama müşteri temsilcisi sık değişiyor.", "Değişiklik taleplerinde onay süreci uzun.",
            "Kesinti bildirimleri geç yapılıyor; proaktif bilgilendirme bekliyoruz.",
            "Yerinde destek ekibi çok iyi; uzaktan destek kalitesi aynı seviyede değil.",
            "Sözleşme dışı taleplere esnek yaklaşıyorlar.", "Kök neden analizi raporları yüzeysel kalıyor.",
            "Güvenlik açıkları için yama takvimini paylaşmıyorlar.", "Hizmet seviyesi toplantıları verimli geçiyor."]


TYPE_NAMES = {"HW": "Donanım", "SW": "Yazılım ve Lisans", "CLOUD": "Bulut Hizmeti", "CONSULT": "Danışmanlık",
              "OUTSOURCE": "Dış Kaynak Personel", "SUPPORT": "Bakım ve Destek", "TELCO": "Telekom",
              "FACILITY": "Tesis ve Veri Merkezi"}


SECTIONS = PLATFORM_SECTIONS + ASSURANCE_SECTIONS + DATAGOV_SECTIONS


class Seeder(PlatformSections, AssuranceSections, DatagovSections):
    def __init__(self, db, app):
        self.db, self.app, self.rnd = db, app, random.Random(20261115)
        self.ids = {}

    def enabled(self, module):
        return self.app.enabled(module)

    def add(self, res, data, created_days_ago=None):
        if RESOURCES[res].code_prefix:                 # kodu sunucu üretir (K-017); demo da elle kod vermez
            data = {k: v for k, v in data.items() if k != "code"}
        record_id = crud.insert(self.db, RESOURCES[res], data, None)
        if created_days_ago is not None and "created_at" in RESOURCES[res].fields:
            self.db.execute(f"UPDATE {RESOURCES[res].table} SET created_at=? WHERE id=?",
                            (stamp(created_days_ago), record_id))
        return record_id

    # -------------------------------------------------------------- kullanıcılar
    def users(self):
        from .session import provision
        from .db import utcnow
        passwords = []
        for username, name, role, units in USERS:
            if one(self.db, "SELECT id FROM users WHERE username=?", (username,)):
                continue
            password = provision(self.db, username, name)
            user_id = one(self.db, "SELECT id FROM users WHERE username=?", (username,))["id"]
            self.db.execute("INSERT INTO tdr_user_roles (user_id, role, assigned_by, assigned_at) VALUES (?,?,?,?)",
                            (user_id, role, SYSTEM.username, utcnow()))
            for code in units:
                self.db.execute("INSERT INTO tdr_user_units (user_id, org_unit_id, assigned_by, assigned_at) "
                                "VALUES (?,?,?,?)", (user_id, self.ids["unit"][code], SYSTEM.username, utcnow()))
            passwords.append((username, name, role, password))
        return passwords

    # -------------------------------------------------------------- çekirdek
    def core(self):
        r = self.rnd
        self.ids["unit"] = {}
        for code, name, parent, manager in UNITS:
            self.ids["unit"][code] = self.add("org_units", {"code": code, "name": name, "manager": manager,
                                                            "parent_id": self.ids["unit"].get(parent)})
        by_name = {t["name"]: t["id"] for t in rows(self.db, "SELECT id, name FROM tdr_supplier_types")}
        types = {key: by_name[name] for key, name in TYPE_NAMES.items()}
        self.ids["item"] = {}
        for code, name, kind, category, _ in CATALOG:
            self.ids["item"][code] = self.add("catalog_items", {"code": code, "name": name, "kind": kind,
                                                                "category": category, "description": TAG})
        tiers = ["critical"] * 8 + ["important"] * 14 + ["standard"] * 23
        segments = {"critical": ["strategic", "bottleneck"], "important": ["leverage", "strategic", "bottleneck"],
                    "standard": ["routine", "leverage"]}
        owners = ["ayse.yilmaz", "mehmet.kaya", "deniz.koc", "okan.yildiz", "zeynep.demir", "kerem.aksoy"]
        names = set()
        self.suppliers = []
        for i, tier in enumerate(tiers, start=1):
            item = CATALOG[(i * 7) % len(CATALOG)] if tier != "critical" else CATALOG[[0, 1, 4, 3, 10, 12, 17, 27][i - 1]]
            type_code = item[4]
            while True:
                name = f"{r.choice(PREFIX)} {r.choice(SUFFIX[type_code])}"
                if name not in names:
                    names.add(name)
                    break
            status = "active" if i % 15 else r.choice(["prospect", "offboarding", "suspended"])
            supplier_id = self.add("suppliers", {
                "code": f"DMO-{i:03d}", "name": name, "tax_id": str(r.randint(1000000000, 9999999999)),
                "country": "Türkiye", "city": r.choice(CITIES), "website": f"https://{name.split()[0].lower()}.ornek.test",
                "status": status, "tier": tier, "segment": r.choice(segments[tier]),
                "owner": None if i in (17, 33, 41) else r.choice(owners), "description": TAG},
                created_days_ago=r.randint(420, 1100))
            self.db.execute("INSERT INTO tdr_supplier_type_map (supplier_id, type_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                            (supplier_id, types[type_code]))
            if i % 4 == 0:
                extra = r.choice(list(types))
                self.db.execute("INSERT INTO tdr_supplier_type_map (supplier_id, type_id) VALUES (?,?) "
                                "ON CONFLICT DO NOTHING", (supplier_id, types[extra]))
            if i <= 34:
                self.db.execute("INSERT INTO tdr_source_refs (supplier_id, source_system, external_id, external_name, "
                                "last_seen_at) VALUES (?,?,?,?,?)",
                                (supplier_id, "sap", f"{1000000 + i * 37}", name.upper()[:35], stamp(r.randint(1, 30))))
            first = r.choice(["Ahmet", "Burcu", "Cem", "Derya", "Ece", "Fatih", "Gizem", "Hakan", "İpek", "Kaan"])
            last = r.choice(["Arı", "Bulut", "Çınar", "Doğan", "Erdem", "Güneş", "Işık", "Kurt", "Oral", "Polat"])
            self.add("supplier_contacts", {"supplier_id": supplier_id, "name": f"{first} {last}",
                                           "role": "Müşteri temsilcisi", "is_primary": 1,
                                           "email": f"{first.lower()}.{last.lower()}@ornek.test".translate(str.maketrans("çğıöşüİ", "cgiosui")),
                                           "phone": f"+90 212 555 {r.randint(10, 99)} {r.randint(10, 99)}"})
            self.suppliers.append({"id": supplier_id, "tier": tier, "status": status, "item": item, "name": name})
        # angajmanlar: her tedarikçinin ana hizmeti + kritik/önemli olanlarda ek hizmetler
        unit_for = {"Altyapı": "BTA", "Bulut": "BTA", "Bilgi güvenliği": "BGV", "Yazılım": "UYG", "Dış kaynak": "UYG",
                    "Bakım": "BTA", "Donanım": "BTA", "Telekom": "OPS", "Danışmanlık": "HKK", "Lojistik": "OPS",
                    "Tesis": "OPS", "İnsan kaynakları": "IKA", "Finansal hizmet": "FIN"}
        self.engagements = []
        n = 0
        for s in self.suppliers:
            items = [s["item"]] + ([r.choice(CATALOG)] if s["tier"] != "standard" and r.random() < 0.7 else [])
            for item in dict.fromkeys(items):
                n += 1
                unit = unit_for[item[3]] if item[0] != "CAGRI" else "MHZ"
                customer = item[0] in ("CAGRI", "ODEME-GW", "SMS", "BLT-SAAS-CRM") and r.random() < 0.6
                start = -r.randint(200, 1400)
                engagement_id = self.add("engagements", {
                    "code": f"ANG-{n:03d}", "supplier_id": s["id"], "catalog_item_id": self.ids["item"][item[0]],
                    "org_unit_id": self.ids["unit"][unit], "beneficiary": "customer" if customer else "internal",
                    "customer_name": r.choice(["Demo Banka A.Ş.", "Örnek Sigorta A.Ş.", "Kurgu Perakende A.Ş."]) if customer else None,
                    "business_owner": None if n in (9, 27) else r.choice([u[1] for u in USERS[1:6]]),
                    "criticality": {"critical": "critical", "important": r.choice(["high", "medium"]),
                                    "standard": r.choice(["medium", "low"])}[s["tier"]],
                    "status": "active" if s["status"] in ("active", "suspended") else "ending" if s["status"] == "offboarding" else "planned",
                    "start_date": day(start), "description": f"{item[1]}. {TAG}."}, created_days_ago=-start)
                if r.random() < 0.3:
                    others = [u for c, u in self.ids["unit"].items() if c not in (unit, "TEK")]
                    for other in r.sample(others, 2):
                        self.db.execute("INSERT INTO tdr_engagement_users (engagement_id, org_unit_id) VALUES (?,?) "
                                        "ON CONFLICT DO NOTHING", (engagement_id, other))
                self.engagements.append({"id": engagement_id, "supplier": s, "item": item, "unit": unit,
                                         "start": start})
        # sözleşmeler: bitişler yayılır; birkaçı 90 gün içinde, birkaçı süresi geçmiş
        for k, e in enumerate(self.engagements, start=1):
            if e["supplier"]["status"] == "prospect":
                continue
            end = r.choice([-40, 25, 60, 85, 140, 220, 300, 400, 520, 700]) if k % 3 else r.randint(150, 900)
            self.add("contracts", {"code": f"SOZ-{k:03d}", "supplier_id": e["supplier"]["id"], "engagement_id": e["id"],
                                   "title": f"{e['item'][1]} hizmet sözleşmesi", "source_system": "sap",
                                   "external_id": f"4600{k:05d}", "start_date": day(e["start"]), "end_date": day(end),
                                   "notice_days": r.choice([30, 60, 90]),
                                   "status": "expired" if end < 0 else "active"})
            if e["supplier"]["tier"] == "critical" and k % 2:
                self.add("responsibilities", {"engagement_id": e["id"], "role": "service_owner", "raci": "A",
                                              "person": r.choice([u[1] for u in USERS[1:6]]),
                                              "org_unit_id": self.ids["unit"][e["unit"]]})
        for s in self.suppliers[:8]:
            self.add("responsibilities", {"supplier_id": s["id"], "role": "security", "raci": "C", "person": "Okan Yıldız",
                                          "org_unit_id": self.ids["unit"]["BGV"]})

    # -------------------------------------------------------------- performans
    def performance(self):
        if not self.enabled("performance"):
            return
        r = self.rnd
        criteria = {c["code"]: c["id"] for c in rows(self.db, "SELECT id, code FROM tdr_review_criteria")}
        months = [(TODAY.replace(day=1) - timedelta(days=30 * m)).replace(day=1) for m in range(1, 13)]
        for e in self.engagements:
            s = e["supplier"]
            if s["tier"] == "standard" or s["status"] == "prospect":
                continue
            quality = r.uniform(0.75, 0.98)                  # bu tedarikçinin "iyiliği"
            sla = self.add("sla_definitions", {"engagement_id": e["id"], "code": "ERS", "name": "Hizmet erişilebilirliği",
                                               "unit": "percent", "target_value": 99.5 if s["tier"] == "critical" else 99.0,
                                               "direction": "higher_better", "period": "monthly"})
            sla2 = self.add("sla_definitions", {"engagement_id": e["id"], "code": "P1", "name": "Kritik olay çözüm süresi",
                                                "unit": "hours", "target_value": 4, "direction": "lower_better",
                                                "period": "monthly"})
            for month in months:
                if e["start"] > -(TODAY - month).days:
                    continue
                miss = r.random() > quality
                up = round(r.uniform(98.6, 99.45) if miss else r.uniform(99.5, 99.99), 2)
                hours = round(r.uniform(4.5, 9.0) if r.random() > quality + 0.05 else r.uniform(1.0, 3.9), 1)
                for sla_id, value in ((sla, up), (sla2, hours)):
                    measurement = crud.insert(self.db, RESOURCES["sla_measurements"], {
                        "sla_id": sla_id, "period_start": month.isoformat(), "actual_value": value,
                        "source": "mcp" if s["tier"] == "critical" else "import",
                        "note": "Kaynak: ServiceNow (sentetik)"}, None)
                    self.db.execute("UPDATE tdr_sla_measurements SET recorded_at=?, recorded_by=? WHERE id=?",
                                    (stamp((TODAY - month).days - 33), "mcp" if s["tier"] == "critical" else "demo-seed",
                                     measurement))
                if miss:
                    self.add("performance_events", {"supplier_id": s["id"], "engagement_id": e["id"],
                                                    "event_type": "sla_breach", "severity": "high",
                                                    "occurred_at": stamp((TODAY - month).days - r.randint(1, 25)),
                                                    "description": f"Erişilebilirlik hedefi tutmadı (%{up})",
                                                    "reference": f"INC{r.randint(100000, 999999)}", "source": "mcp"})
        kinds = [("incident", "medium", "Planlanmamış kesinti; servis 45 dakika erişilemedi"),
                 ("delivery_delay", "medium", "Teslimat taahhüt edilen tarihten 9 gün sonra yapıldı"),
                 ("escalation", "high", "Çözülmeyen talep yönetim seviyesine eskale edildi"),
                 ("praise", "low", "Yoğun dönemde ek kaynak sağlanarak hizmet aksatılmadı"),
                 ("incident", "critical", "Güvenlik yaması gecikmesi nedeniyle acil bakım gerekti")]
        for _ in range(60):
            s = r.choice([x for x in self.suppliers if x["status"] == "active"])
            kind, severity, text = r.choice(kinds)
            self.add("performance_events", {"supplier_id": s["id"], "event_type": kind, "severity": severity,
                                            "occurred_at": stamp(r.randint(3, 360), r.randint(8, 18)),
                                            "description": text, "source": "manual"})
        # değerlendirmeler: kritikler 6 ayda bir (birkaçı gecikmiş), önemliler yılda bir
        reviewers = ["ayse.yilmaz", "mehmet.kaya", "okan.yildiz"]
        for idx, s in enumerate(self.suppliers):
            if s["status"] != "active" or s["tier"] == "standard":
                continue
            cadence = 182 if s["tier"] == "critical" else 365
            last = r.randint(20, cadence - 10) if idx % 4 else cadence + r.randint(15, 80)   # her 4'ten biri gecikmiş
            for back in (last, last + cadence):
                review = self.add("performance_reviews", {"supplier_id": s["id"], "period_start": day(-back - 90),
                                                          "period_end": day(-back), "comment": "Dönemsel değerlendirme. " + TAG},
                                  created_days_ago=back - 5)
                self.db.execute("UPDATE tdr_performance_reviews SET reviewer=? WHERE id=?", (r.choice(reviewers), review))
                for code, cid in criteria.items():
                    self.add("review_scores", {"review_id": review, "criterion_id": cid,
                                               "score": max(1, min(5, round(r.gauss(3.8, 0.8))))})

    # -------------------------------------------------------------- risk
    def risks(self):
        if not self.enabled("risks"):
            return
        from .modules import risks as R
        r = self.rnd
        scenarios = [
            ("concentration", "Tek tedarikçiye bağımlılık", "Kritik hizmette alternatif tedarikçi bulunmadığı için",
             "tedarikçi kesintisi hizmeti durdurabilir", "müşteriye taahhüt edilen süre aşılabilir"),
            ("continuity", "Felaket kurtarma testinin yapılmaması", "Tedarikçi yıllık DR testini paylaşmadığı için",
             "felaket anında hizmet hedef sürede geri gelmeyebilir", "uzun süreli kesinti ve sözleşme cezası oluşabilir"),
            ("security", "Tedarikçi erişim yetkilerinin gözden geçirilmemesi", "Tedarikçi personeli erişimleri periyodik gözden geçirilmediği için",
             "ayrılan personel sistemlere erişmeye devam edebilir", "yetkisiz erişim ve veri sızıntısı yaşanabilir"),
            ("privacy", "Kişisel verinin yurt dışına aktarımı", "Bulut hizmeti verileri yurt dışı bölgede işlediği için",
             "açık rıza veya taahhütname olmadan aktarım yapılabilir", "KVKK kapsamında idari para cezası doğabilir"),
            ("exit", "Çıkış planının olmaması", "Sözleşmede veri iadesi ve geçiş desteği tanımlanmadığı için",
             "tedarikçi değişiminde veriler geri alınamayabilir", "geçiş uzar ve maliyet artar"),
            ("financial", "Tedarikçinin mali zayıflığı", "Tedarikçinin son iki yıl bilançosu zarar gösterdiği için",
             "tedarikçi faaliyetlerini durdurabilir", "hizmet aniden kesilebilir"),
            ("compliance", "Alt yüklenici kullanımının bildirilmemesi", "Sözleşme alt yüklenici bildirim yükümlülüğü içermediği için",
             "onaysız alt yüklenici veriye erişebilir", "denetimde uygunsuzluk ve itibar kaybı oluşabilir"),
            ("performance", "SLA ihlallerinin tekrarlanması", "Tedarikçi kapasitesi talep artışını karşılamadığı için",
             "erişilebilirlik hedefi art arda tutmayabilir", "müşteri şikâyetleri ve ceza bedeli artabilir"),
        ]
        assessors = ["okan.yildiz", "ayse.yilmaz"]
        n = 0
        for s in self.suppliers:
            if s["tier"] == "standard" and r.random() < 0.85:
                continue
            for category, title, cause, event, consequence in r.sample(scenarios, 2 if s["tier"] == "critical" else 1):
                n += 1
                likelihood, impact = r.randint(2, 5), r.randint(3, 5) if s["tier"] == "critical" else r.randint(2, 4)
                appetite = r.choice([6, 8, 9, 10, 12])
                risk_id = self.add("supplier_risks", {
                    "code": f"TR-{n:03d}", "title": title, "supplier_id": s["id"], "category": category,
                    "description": TAG, "cause": cause, "risk_event": event, "consequence": consequence,
                    "likelihood": likelihood, "impact": impact, "appetite": appetite,
                    "owner": r.choice(["ayse.yilmaz", "okan.yildiz", "mehmet.kaya"]),
                    "response_strategy": "mitigate", "treatment": "Önlemler işleme faaliyetlerinde izlenir.",
                    "review_date": day(r.choice([-25, -5, 30, 60, 120, 180])),
                    "control_risk_ref": "SUPPLIER" if n % 5 == 0 else None}, created_days_ago=r.randint(90, 400))
                risk = crud.get(self.db, RESOURCES["supplier_risks"], risk_id)
                if n % 6 == 0:                       # değerlendirilmemiş açık risk
                    continue
                mitigations = [{"title": t, "weight": r.choice(["low", "medium", "high"]),
                                "effectiveness": r.choice(["effective", "effective", "partial"])}
                               for t in r.sample(["Yedek tedarikçiyle çerçeve sözleşme", "Yıllık yerinde denetim",
                                                  "Sözleşmeye çıkış maddesi eklenmesi", "Erişim gözden geçirme süreci",
                                                  "Teminat mektubu", "Aylık hizmet gözden geçirme toplantısı"], r.randint(0, 2))]
                total, credits = R.contribution(mitigations)
                inherent = likelihood * impact
                residual = float(inherent * (1 - total))
                assessor = r.choice(assessors)
                snapshot = {k: risk.get(k) for k in R.SNAPSHOT}
                snapshot.update({"method": "weighted-v1", "mitigations": credits})
                assessed_ago = r.randint(10, 80)
                assessment_id = self.db.execute(
                    "INSERT INTO tdr_risk_assessments (risk_id, assessed_at, assessor, rationale, inherent, mitigation_pct, "
                    "residual, appetite, snapshot) VALUES (?,?,?,?,?,?,?,?,?)",
                    (risk_id, stamp(assessed_ago), assessor, "Tedarikçi görüşmesi ve sözleşme incelemesine dayanır. " + TAG,
                     inherent, float(total * 100), residual, appetite, json.dumps(snapshot, ensure_ascii=False))).lastrowid
                if n % 4 == 0 and residual <= appetite:      # iştah içinde kabul
                    self.db.execute("UPDATE tdr_supplier_risks SET status='accepted', response_strategy='accept', "
                                    "review_date=? WHERE id=?", (day(r.randint(60, 200)), risk_id))
                    self.db.execute(
                        "INSERT INTO tdr_risk_decisions (risk_id, assessment_id, from_status, to_status, actor, actor_role, "
                        "decided_at, rationale, residual, appetite, review_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (risk_id, assessment_id, "open", "accepted", "selin.aydin", "ADMIN", stamp(assessed_ago - 3),
                         "Artık risk iştah eşiği içinde; mevcut önlemler yeterli bulundu.", residual, appetite,
                         day(r.randint(60, 200))))
                    continue
                if residual > appetite or r.random() < 0.4:
                    self.db.execute("UPDATE tdr_supplier_risks SET status='in_treatment' WHERE id=?", (risk_id,))
                    for k in range(r.randint(1, 2)):
                        due = r.choice([-12, 20, 45, 90])
                        status = r.choice(["open", "in_progress", "completed"]) if due > 0 else "in_progress"
                        action = self.add("risk_actions", {
                            "code": f"RF-{n:03d}-{k + 1}", "risk_id": risk_id,
                            "title": r.choice(["Alternatif tedarikçi için teklif toplanması", "DR test raporunun talep edilmesi",
                                               "Erişim listesinin gözden geçirilmesi", "Sözleşmeye denetim hakkı eklenmesi",
                                               "Veri işleme sözleşmesinin imzalanması"]),
                            "owner": risk["owner"], "due_date": day(due), "priority": r.choice(["medium", "high"]),
                            "status": status, "description": TAG}, created_days_ago=assessed_ago - 2)
                        if status == "completed":
                            self.db.execute("UPDATE tdr_risk_actions SET resolution=? WHERE id=?",
                                            ("Tamamlandı; kanıt dosyası tedarikçi kaydında.", action))

    # -------------------------------------------------------------- anketler
    def surveys(self):
        if not self.enabled("surveys"):
            return
        from .modules import surveys as SV
        r = self.rnd
        templates = {{"satisfaction": "MEMNUNIYET", "risk": "RISK-DEG"}[t["purpose"]]: t["id"]
                     for t in rows(self.db, "SELECT id, purpose FROM tdr_survey_templates WHERE purpose IN "
                                            "('satisfaction','risk') AND version=1")}
        for code in ("MEMNUNIYET", "RISK-DEG"):
            self.db.execute("UPDATE tdr_survey_templates SET status='published' WHERE id=?", (templates[code],))
        people = ["mehmet.kaya", "deniz.koc", "okan.yildiz", "zeynep.demir", "kerem.aksoy", "ayse.yilmaz"]

        def campaign(code, name, template, subject, audience, anonymous, status, opened_ago, closed_ago, targets):
            campaign_id = self.add("survey_campaigns", {
                "code": code, "name": name, "template_id": templates[template], "subject": subject,
                "audience": audience, "anonymous": anonymous, "min_responses": 3, "owner": "ayse.yilmaz",
                "description": TAG, "period_start": day(-opened_ago - 90), "period_end": day(-opened_ago)},
                created_days_ago=opened_ago + 5)
            target_ids = [self.add("survey_targets", {"campaign_id": campaign_id, "supplier_id": s["id"]})
                          for s in targets] or [None]
            self.db.execute("UPDATE tdr_survey_campaigns SET status='open', opened_at=? WHERE id=?",
                            (stamp(opened_ago), campaign_id))
            if status == "closed":       # davetler eklendikten sonra kapatılır (kapalı kampanyaya davet eklenmez)
                self.closing.append((campaign_id, stamp(closed_ago)))
            return crud.get(self.db, RESOURCES["survey_campaigns"], campaign_id), target_ids

        def answer(camp, target_id, username, quality, submitted_ago, invitation=None):
            form = SV.structure(self.db, camp["template_id"])
            values, scored = {}, []
            for q in form["questions"]:
                if q["show_if"] and not SV.visible(q, {x["code"]: values.get(x["id"]) for x in form["questions"]
                                                       if x["id"] in values}):
                    continue
                kind = q["kind"]
                if kind == "scale_1_5":
                    value = max(1, min(5, round(r.gauss(1 + 4 * quality, 0.7))))
                elif kind == "nps_0_10":
                    value = max(0, min(10, round(r.gauss(10 * quality, 1.5))))
                elif kind == "yes_no":
                    good = [o["value"] for o in q["options"] if o["score"] == 100][0]
                    value = good if r.random() < quality else [o["value"] for o in q["options"] if o["value"] != good][0]
                elif kind == "text":
                    if r.random() < 0.5:
                        continue
                    value = r.choice(COMMENTS)
                else:
                    continue
                values[q["id"]] = value
            key = SV._key(camp, username, target_id)
            response_id = self.db.execute(
                "INSERT INTO tdr_survey_responses (campaign_id, target_id, invitation_id, respondent, respondent_key, "
                "status, started_at) VALUES (?,?,?,?,?,'draft',?)",
                (camp["id"], target_id, None if camp["anonymous"] else invitation, None if camp["anonymous"] else username,
                 key, stamp(submitted_ago + 1))).lastrowid
            by_id = {q["id"]: q for q in form["questions"]}
            for qid, value in values.items():
                text, number, many, score = SV.check_value(by_id[qid], value)
                self.db.execute("INSERT INTO tdr_survey_answers (response_id, question_id, value_text, value_number, "
                                "values_json, score) VALUES (?,?,?,?,?,?)",
                                (response_id, qid, text, number, json.dumps(many) if many else None, score))
                if score is not None and by_id[qid]["weight"]:
                    scored.append((by_id[qid]["weight"], score))
            total = sum(w for w, _ in scored)
            final = round(sum(w * s for w, s in scored) / total, 1) if total else None
            self.db.execute("UPDATE tdr_survey_responses SET status='submitted', score=?, submitted_at=? WHERE id=?",
                            (final, stamp(submitted_ago), response_id))

        self.closing = []
        quality = {s["id"]: r.uniform(0.35, 0.95) for s in self.suppliers}
        critical = [s for s in self.suppliers if s["tier"] == "critical" and s["status"] == "active"]
        important = [s for s in self.suppliers if s["tier"] == "important" and s["status"] == "active"][:6]
        # 1) kapanmış memnuniyet kampanyası (davetli)
        camp, targets = campaign("MEM-2026-Y1", "2026 ilk yarı tedarikçi memnuniyeti", "MEMNUNIYET", "supplier",
                                 "invited", 0, "closed", 150, 110, critical + important)
        for target_id, s in zip(targets, critical + important):
            for person in r.sample(people, 4):
                inv = self.add("survey_invitations", {"campaign_id": camp["id"], "respondent": person, "target_id": target_id})
                if r.random() < 0.8:
                    answer(camp, target_id, person, quality[s["id"]], r.randint(112, 145), inv)
                    self.db.execute("UPDATE tdr_survey_invitations SET status='answered', answered_at=? WHERE id=?",
                                    (stamp(r.randint(112, 145)), inv))
        # 2) açık risk değerlendirme kampanyası (davetli, kısmen yanıtlanmış; demo kullanıcılar da yanıtlayabilir)
        camp, targets = campaign("RISK-2026-Q4", "2026 4. çeyrek kritik tedarikçi risk değerlendirmesi", "RISK-DEG",
                                 "supplier", "invited", 0, "open", 12, None, critical)
        self.db.execute("UPDATE tdr_survey_campaigns SET closes_on=? WHERE id=?", (day(25), camp["id"]))
        for target_id, s in zip(targets, critical):
            for person in ("okan.yildiz", "mehmet.kaya", "ayse.yilmaz"):
                inv = self.add("survey_invitations", {"campaign_id": camp["id"], "respondent": person, "target_id": target_id})
                if person != "ayse.yilmaz" and r.random() < 0.7:
                    answer(camp, target_id, person, quality[s["id"]] - 0.15, r.randint(1, 10), inv)
                    self.db.execute("UPDATE tdr_survey_invitations SET status='answered', answered_at=? WHERE id=?",
                                    (stamp(r.randint(1, 10)), inv))
        # 3) bağımsız, anonim iç memnuniyet anketi (herkese açık, kapalı)
        camp, targets = campaign("IC-MEM-2026", "Satın alma süreci iç müşteri memnuniyeti", "MEMNUNIYET", "none",
                                 "all", 1, "closed", 60, 30, [])
        for person in people + ["elif.sahin", "can.ozturk"]:
            answer(camp, None, person, r.uniform(0.5, 0.85), r.randint(31, 58))
        for campaign_id, closed_at in self.closing:
            self.db.execute("UPDATE tdr_survey_campaigns SET status='closed', closed_at=? WHERE id=?",
                            (closed_at, campaign_id))

    # -------------------------------------------------------------- uyum (GRC)
    def grc(self):
        """KS GRC sentetik senaryoları (vendor/ks_grc) + tedarikçi yönetimi kontrolleri, denetimler, kanıt, bulgu, DÖF."""
        if not self.enabled("grc"):
            return
        from pathlib import Path
        from .modules import grc as G
        r = random.Random(20261116)
        base = Path(__file__).parent / "vendor" / "ks_grc"
        catalog = json.loads((base / "catalog.json").read_text(encoding="utf-8"))
        scenario = json.loads((base / "operational_scenarios.json").read_text(encoding="utf-8"))
        if catalog["data_classification"] != "SIMULATED_NON_PRODUCTION" or scenario["classification"] != "SIMULATED":
            raise SystemExit("Yalnızca sentetik KS GRC senaryoları yüklenir")
        admin = Principal("selin.aydin", "ADMIN", "system", "Selin Aydın")
        auditor = Principal("can.ozturk", "AUDITOR", "system", "Can Öztürk")
        machine = Principal("mcp", "MACHINE", "api_key", "MCP")
        db = self.db
        # standartlar ve maddeler
        std, clause = {}, {}
        standards = catalog["standards"] + [{
            "code": "ISO/IEC 27001", "version": "2022", "name": "Bilgi güvenliği yönetim sistemi — tedarikçi ilişkileri",
            "description": "Ek A tedarikçi ilişkileri kontrolleri (kısa Türkçe başlıklar; lisanslı metinle detaylandırılmalıdır).",
            "clauses": [{"code": c, "title": t} for c, t in (
                ("A.5.19", "Tedarikçi ilişkilerinde bilgi güvenliği"), ("A.5.20", "Tedarikçi anlaşmalarında bilgi güvenliği"),
                ("A.5.21", "BİT tedarik zincirinde bilgi güvenliği"), ("A.5.22", "Tedarikçi hizmetlerinin izlenmesi ve değişiklik yönetimi"),
                ("A.5.23", "Bulut hizmetleri kullanımında bilgi güvenliği"), ("A.5.30", "İş sürekliliği için BİT hazırlığı"),
                ("A.5.31", "Yasal ve sözleşmesel gereklilikler"), ("A.5.34", "Kişisel verilerin gizliliği ve korunması"),
                ("A.8.30", "Dış kaynaklı geliştirme"))]}]
        for s in standards:
            sid = self.add("standards", {"code": s["code"], "name": s["name"], "version": s["version"],
                                         "description": s.get("description"), "issuer": s["code"].split()[0].split("/")[0]})
            std[s["code"]] = sid
            for c in s["clauses"]:
                clause[(s["code"], c["code"])] = self.add("clauses", {"standard_id": sid, "code": c["code"], "title": c["title"],
                                                                      "description": c.get("description")})
            for c in s["clauses"]:
                if "." in c["code"] and (s["code"], c["code"].rsplit(".", 1)[0]) in clause:
                    db.execute("UPDATE tdr_clauses SET parent_id=? WHERE id=?",
                               (clause[(s["code"], c["code"].rsplit(".", 1)[0])], clause[(s["code"], c["code"])]))
        # uygulanabilirlik bildirimi: iki CIS maddesi kapsam dışı (gerekçeli)
        for code in ("15.7", "16.14"):
            if ("CIS Controls", code) in clause:
                db.execute("UPDATE tdr_clauses SET applicable=0, justification=? WHERE id=?",
                           ("Kapsamdaki hizmetlerde uygulanmıyor; yıllık gözden geçirilir.", clause[("CIS Controls", code)]))
        prefix = {"ISO": "ISO/IEC 20000-1", "CIS": "CIS Controls"}

        def clause_id(token):
            p, code = token.split(":", 1)
            return clause.get((prefix[p], code))
        proc, obj = {}, {}
        for code, name, owner, description in scenario["processes"] + [
                ["TDR", "Tedarikçi Yönetimi", "Satın Alma", "Tedarikçi seçimi, sözleşme, performans, risk ve çıkış"]]:
            proc[code] = self.add("processes", {"code": code, "name": name, "owner": owner, "description": description,
                                                "org_unit_id": self.ids["unit"]["SAT"] if code == "TDR" else None})
        for code, name in scenario["objectives"] + [["OBJ-TDR", "Kritik tedarikçiler periyodik olarak izlenmeli ve riskleri yönetilmeli"]]:
            obj[code] = self.add("objectives", {"code": code, "name": name})
        # dokümanlar
        documents = {}
        for code, title, category, owner, status, approved_ago, review in (
                ("POL-TDR", "Tedarikçi Yönetimi Politikası", "policy", "Ayşe Yılmaz", "active", 300, 65),
                ("PRS-TDR-GUV", "Tedarikçi Bilgi Güvenliği Gereksinimleri Prosedürü", "procedure", "Okan Yıldız", "active", 400, -20),
                ("PRS-DEG", "Değişiklik Yönetimi Prosedürü", "procedure", "Mehmet Kaya", "active", 200, 165),
                ("PRS-OLAY", "Olay ve Problem Yönetimi Prosedürü", "procedure", "Zeynep Demir", "active", 150, 215),
                ("TLM-ERISIM", "Tedarikçi Erişim Yönetimi Talimatı", "instruction", "Okan Yıldız", "active", 420, -45),
                ("STD-SOZ", "Sözleşme Güvenlik ve Denetim Hakkı Maddeleri", "contract_clause", "Emre Tan", "active", 90, 275),
                ("RHB-BULUT", "Bulut Hizmeti Kullanım Rehberi", "guideline", "Mehmet Kaya", "draft", None, None),
                ("PRS-SUREK", "İş Sürekliliği ve Felaket Kurtarma Prosedürü", "procedure", "Kerem Aksoy", "active", 380, 10)):
            documents[code] = self.add("documents", {
                "code": code, "title": title, "category": category, "owner": owner, "status": status,
                "version": "1." + str(r.randint(0, 4)), "approved_by": "Selin Aydın" if approved_ago else None,
                "approved_on": day(-approved_ago) if approved_ago else None, "review_date": day(review) if review else None,
                "description": TAG})
        from .migrate import _document_lifecycle
        _document_lifecycle(db)                        # K-020: yürürlükteki dokümanlar ilk revizyonla yayımlanır
        # kontroller: KS GRC senaryoları + tedarikçi yönetimi
        ctl = {}
        units = {"automatic": "BTA", "manual": "BGV"}
        for c in scenario["controls"]:
            ctl[c["code"]] = self.add("controls", {
                "code": c["code"], "name": c["name"], "description": c["description"], "execution_mode": c["execution_mode"],
                "nature": c["nature"], "frequency": c["frequency"], "method": c["method"], "expected_result": c["expected_result"],
                "owner": c["owner"], "criticality": c.get("example", {}).get("severity", "medium") if c["example"]["status"] == "fail" else r.choice(["medium", "high"]),
                "method_type": "query" if c["execution_mode"] == "automatic" else r.choice(["sampling", "inspection"]),
                "org_unit_id": self.ids["unit"][units[c["execution_mode"]]]})
            self._link(ctl[c["code"]], "control_clauses", "clause_id", [clause_id(t) for t in c["clauses"]])
            self._link(ctl[c["code"]], "control_processes", "process_id", [proc[p] for p in c["processes"] if p in proc])
            self._link(ctl[c["code"]], "control_objectives", "objective_id", [obj[o] for o in c["objectives"] if o in obj])
        iso27 = lambda *codes: [clause[("ISO/IEC 27001", c)] for c in codes]
        iso20 = lambda *codes: [clause[("ISO/IEC 20000-1", c)] for c in codes if ("ISO/IEC 20000-1", c) in clause]
        supplier_controls = (
            ("TDR-CTL-01", "Aktif tedarikçilerin ilişki sahibi atanmış", "supplier.owner", "weekly", "medium", ("A.5.19",), ("8.3.4",), "POL-TDR"),
            ("TDR-CTL-02", "Kritik tedarikçi performans değerlendirmeleri zamanında", "supplier.reviews", "monthly", "high", ("A.5.22",), ("8.3.4",), "POL-TDR"),
            ("TDR-CTL-03", "Tedarikçi riskleri değerlendirilmiş ve gözden geçirilmiş", "supplier.risk_reviews", "monthly", "high", ("A.5.19", "A.5.21"), ("8.3.4",), "PRS-TDR-GUV"),
            ("TDR-CTL-04", "Biten sözleşmelerin yenileme / çıkış sorumlusu belli", "supplier.contracts", "monthly", "medium", ("A.5.20",), ("8.3.4",), "STD-SOZ"),
            ("TDR-CTL-05", "SLA hedefleri art arda kaçırılmıyor", "supplier.sla", "monthly", "high", ("A.5.22",), ("8.3.3", "8.3.4"), "POL-TDR"),
            ("TDR-CTL-06", "Kritik tedarikçiler periyodik memnuniyet / risk anketine konu", "supplier.surveys", "quarterly", "medium", ("A.5.22",), ("8.3.4",), "POL-TDR"))
        for code, name, rule, freq, crit, c27, c20, doc in supplier_controls:
            ctl[code] = self.add("controls", {
                "code": code, "name": name, "execution_mode": "automatic", "automation": rule, "frequency": freq, "criticality": crit,
                "nature": "detective", "method_type": "query", "owner": "Ayşe Yılmaz", "org_unit_id": self.ids["unit"]["SAT"],
                "method": "Portal verisi üzerinde iç otomatik kural; sorgu sonucu özeti kanıt olarak saklanır.",
                "expected_result": "İstisna olmaması.", "description": TAG})
            self._link(ctl[code], "control_clauses", "clause_id", iso27(*c27) + iso20(*c20))
            self._link(ctl[code], "control_processes", "process_id", [proc["TDR"]])
            self._link(ctl[code], "control_objectives", "objective_id", [obj["OBJ-TDR"]])
            self._link(ctl[code], "control_documents", "document_id", [documents[doc]])
        for code, name, c27, freq in (("TDR-CTL-07", "Kritik tedarikçi sözleşmelerinde güvenlik ve denetim hakkı maddesi", ("A.5.20", "A.5.31"), "yearly"),
                                      ("TDR-CTL-08", "Tedarikçi personeli erişimlerinin üç aylık gözden geçirilmesi", ("A.5.19", "A.5.21"), "quarterly"),
                                      ("TDR-CTL-09", "Bulut tedarikçilerinde veri yerleşimi ve KVKK taahhüdü", ("A.5.23", "A.5.34"), "yearly")):
            ctl[code] = self.add("controls", {
                "code": code, "name": name, "execution_mode": "manual", "frequency": freq, "criticality": "high", "nature": "preventive",
                "method_type": "sampling", "owner": "Okan Yıldız", "org_unit_id": self.ids["unit"]["BGV"],
                "method": "Kritik tedarikçilerden örneklem seçilir; sözleşme, erişim listesi ve taahhütname incelenir.",
                "expected_result": "Örneklemdeki tüm kayıtlar gereksinimi karşılar.", "description": TAG})
            self._link(ctl[code], "control_clauses", "clause_id", iso27(*c27))
            self._link(ctl[code], "control_processes", "process_id", [proc["TDR"]])
            self._link(ctl[code], "control_documents", "document_id", [documents["PRS-TDR-GUV"], documents["TLM-ERISIM"]])
        # risk kataloğu ve kurumsal riskler (tedarikçisiz)
        from .modules import risks as RK
        catalog_ids = {}
        for code, title, category, cause, event, consequence in (
                ("EOS", "Destek süresi biten bileşen", "security", "Üretici desteği sona erdiği için", "kritik bir zafiyet yamalanamayabilir", "hizmette kesinti veya veri ihlali yaşanabilir"),
                ("PATCH", "Kritik yamada gecikme", "security", "Kritik güvenlik yamaları hedef sürede uygulanmadığı için", "bilinen bir zafiyet istismar edilebilir", "müşteri verisinin gizliliği zarar görebilir"),
                ("CHANGE", "Yetkisiz üretim değişikliği", "operational", "Üretim erişimi ile onay yetkisi ayrılmadığı için", "test edilmemiş bir değişiklik devreye alınabilir", "hizmet seviyesi taahhüdü ihlal edilebilir"),
                ("RESTORE", "Yedekten geri dönüş", "continuity", "Geri yükleme provaları temsili veriyle yapılmadığı için", "kritik bir hizmet hedef sürede kurtarılamayabilir", "veri kaybı ve sözleşmesel kesinti oluşabilir"),
                ("SUPPLIER", "Tek tedarikçiye bağımlılık", "supplier", "Kritik hizmette alternatif tedarikçi bulunmadığı için", "tedarikçi kesintisi hizmeti durdurabilir", "müşteriye taahhüt edilen süre aşılabilir"),
                ("CMDB", "Eksik hizmet bağımlılıkları", "operational", "CMDB ilişki bilgileri güncel tutulmadığı için", "değişiklikten etkilenecek bir hizmet gözden kaçabilir", "plansız kesinti yaşanabilir"),
                ("CAPACITY", "Veri merkezi kapasitesi", "continuity", "Kapasite tahmininde büyüme dikkate alınmadığı için", "yoğun dönemde kapasite tükenebilir", "kritik uygulamaların erişilebilirliği düşebilir"),
                ("PRIVACY", "Kanıtlarda kişisel veri", "privacy", "Kanıt toplarken veri minimizasyonu uygulanmadığı için", "gereksiz kişisel veriler denetim paketine girebilir", "kişisel veriler yetkisiz kişilerle paylaşılabilir")):
            catalog_ids[code] = self.add("risk_catalog", {"code": code, "title": title, "category": category, "cause": cause,
                                                          "risk_event": event, "consequence": consequence,
                                                          "likelihood": r.randint(2, 4), "impact": r.randint(3, 5), "description": "KS GRC örnek senaryosu"})
        enterprise = {}
        for n, (code, entity, ctl_codes, like, imp) in enumerate((
                ("CHANGE", "Üretim ortamı (çekirdek bankacılık hizmeti)", ("KS-DEMO-CTL-002", "KS-DEMO-CTL-003"), 3, 4),
                ("RESTORE", "Birincil veri merkezi", ("KS-DEMO-CTL-020", "KS-DEMO-CTL-021"), 2, 5),
                ("PATCH", "Sunucu filosu", ("KS-DEMO-CTL-009", "KS-DEMO-CTL-010"), 4, 4),
                ("CMDB", "Konfigürasyon yönetim veritabanı", ("KS-DEMO-CTL-001",), 3, 3),
                ("CAPACITY", "Veri merkezi altyapısı", ("KS-DEMO-CTL-022",), 2, 4),
                ("PRIVACY", "Denetim kanıt arşivi", ("KS-DEMO-CTL-028",), 2, 3)), start=1):
            row = one(db, "SELECT * FROM tdr_risk_catalog WHERE id=?", (catalog_ids[code],))
            risk_id = self.add("supplier_risks", {
                "code": f"KR-{n:03d}", "title": row["title"], "category": row["category"], "entity_name": entity,
                "catalog_id": row["id"], "cause": row["cause"], "risk_event": row["risk_event"], "consequence": row["consequence"],
                "likelihood": like, "impact": imp, "appetite": 8, "owner": r.choice(["mehmet.kaya", "okan.yildiz"]),
                "response_strategy": "mitigate", "review_date": day(r.choice([-10, 45, 90, 120])), "description": TAG},
                created_days_ago=r.randint(120, 300))
            enterprise[code] = risk_id
            self._link_many("control_risks", "risk_id", risk_id, [ctl[c] for c in ctl_codes if c in ctl])
            risk = crud.get(db, RESOURCES["supplier_risks"], risk_id)
            mitigations = [{"title": f"{c} kontrolü", "weight": "medium", "effectiveness": "effective", "control_ref": c} for c in ctl_codes]
            total, credits = RK.contribution(mitigations)
            snapshot = {k: risk.get(k) for k in RK.SNAPSHOT}
            snapshot.update({"method": "weighted-v1", "mitigations": credits})
            db.execute("INSERT INTO tdr_risk_assessments (risk_id, assessed_at, assessor, rationale, inherent, mitigation_pct, "
                       "residual, appetite, snapshot) VALUES (?,?,?,?,?,?,?,?,?)",
                       (risk_id, stamp(r.randint(15, 60)), "okan.yildiz", "Kontrol test sonuçları ve süreç gözden geçirmesine dayanır. " + TAG,
                        like * imp, float(total * 100), float(like * imp * (1 - total)), 8, json.dumps(snapshot, ensure_ascii=False)))
            db.execute("UPDATE tdr_supplier_risks SET status='in_treatment' WHERE id=?", (risk_id,))
        # tedarikçi risklerini kontrollere bağla
        for code in ("TDR-CTL-03", "TDR-CTL-08"):
            some = [x["id"] for x in rows(db, "SELECT id FROM tdr_supplier_risks WHERE supplier_id IS NOT NULL AND category IN "
                                              "('security','concentration','continuity') ORDER BY id LIMIT 6")]
            self._link_many("control_risks", "risk_id", None, [], control=ctl[code], targets=some)
        # kanıtlar (küçük sentetik dosyalar)
        evidence = {}

        def evid(key, title, file_name, content, ctl_codes, days_ago, expires=None, supplier=None, conf="internal", by="can.ozturk"):
            principal = Principal(by, "AUDITOR", "system", by)
            evidence_id = crud.insert(db, RESOURCES["evidence"], {
                "title": title, "description": TAG, "confidentiality": conf, "supplier_id": supplier,
                "period_start": day(-days_ago - 90), "period_end": day(-days_ago), "expires_at": expires,
                "org_unit_id": self.ids["unit"]["BGV"]}, principal)
            G.store_file(db, evidence_id, file_name, content, by, uploaded_at=stamp(days_ago))
            db.execute("UPDATE tdr_evidence SET created_at=? WHERE id=?", (stamp(days_ago), evidence_id))
            for c in ctl_codes:
                db.execute("INSERT INTO tdr_evidence_controls (evidence_id, control_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                           (evidence_id, ctl[c]))
            evidence[key] = evidence_id
            return evidence_id
        pdf = lambda text: ("%PDF-1.4\n% " + TAG + "\n% " + text + "\n%%EOF\n").encode()
        critical = [s for s in self.suppliers if s["tier"] == "critical"]
        evid("cmdb", "CMDB keşif karşılaştırma çıktısı", "cmdb-kesif.csv", "fqdn,ci_durumu\nsrv-001.ornek.test,eslesti\nsrv-002.ornek.test,eksik\n".encode(), ["KS-DEMO-CTL-001"], 3)
        evid("rfc", "Üretim değişiklik onay örneklemi", "rfc-orneklem.csv", "rfc,onay,test\nCHG0001,evet,evet\nCHG0002,hayir,evet\n".encode(), ["KS-DEMO-CTL-002", "KS-DEMO-CTL-003"], 20)
        evid("erisim", "Tedarikçi personeli erişim gözden geçirme listesi (Q3)", "erisim-gozden-gecirme.csv",
             "tedarikci,kullanici,durum\nDMO-001,ext.user1,kaldirildi\nDMO-003,ext.user7,onaylandi\n".encode(), ["TDR-CTL-08"], 45, conf="confidential")
        evid("sozlesme", "Kritik tedarikçi sözleşme madde incelemesi", "sozlesme-inceleme.pdf", pdf("8 sozlesmeden 6'sinda denetim hakki var"), ["TDR-CTL-07"], 60)
        evid("kvkk", "Bulut tedarikçileri veri yerleşim taahhütleri", "kvkk-taahhut.pdf", pdf("taahhutname ozeti"), ["TDR-CTL-09"], 75, conf="restricted")
        evid("yedek", "Geri yükleme provası raporu", "geri-yukleme.json", json.dumps({"prova": "Q3", "rto_saat": 3.5, "hedef": 4}).encode(), ["KS-DEMO-CTL-020"], 30)
        for n, s in enumerate(critical[:5]):
            evid(f"iso{n}", f"{s['name']} — ISO/IEC 27001 sertifikası", f"iso27001-{n + 1}.pdf", pdf(s["name"] + " sertifika kopyasi"),
                 ["TDR-CTL-07"], r.randint(100, 300), expires=day([12, 25, 140, 260, -5][n]), supplier=s["id"])
        evid("soc2", f"{critical[1]['name']} — SOC 2 Tür II rapor özeti", "soc2-ozet.pdf", pdf("SOC2 ozet"), ["TDR-CTL-08"], 50,
             expires=day(200), supplier=critical[1]["id"], conf="confidential")
        db.execute("UPDATE tdr_evidence SET status='expired' WHERE expires_at < ?", (day(0),))
        # kontrol test geçmişi (KS GRC senaryo sonuçları; MCP ve denetçi)
        for c in scenario["controls"]:
            example = c["example"]
            history = [r.choice(["pass", "pass", "fail"]) for _ in range(r.randint(1, 3))] + [example["status"]]
            freq = G.FREQUENCY_DAYS.get(c["frequency"]) or 30
            for k, status in enumerate(history):
                ago = (len(history) - 1 - k) * min(freq, 30) + r.randint(1, 6)
                if c["code"] in ("KS-DEMO-CTL-015", "KS-DEMO-CTL-018") and k == len(history) - 1:
                    ago += 140                                   # testi gecikmiş manuel kontroller
                body = {"control_id": ctl[c["code"]], "status": status, "executed_at": stamp(ago, r.randint(7, 18)),
                        "details": example["details"] if status == example["status"] else
                        ("Örneklemde istisna bulunmadı." if status == "pass" else "Örneklemde istisna bulundu; ayrıntı kaynak kayıtta."),
                        "sample_size": example.get("checked"), "exceptions": example.get("failed", 0) if status == "fail" else 0}
                if status == "fail":
                    body["severity"] = example.get("severity", "medium")
                links = [evidence[k2] for k2, codes in (("cmdb", ["KS-DEMO-CTL-001"]), ("rfc", ["KS-DEMO-CTL-002", "KS-DEMO-CTL-003"]),
                                                       ("yedek", ["KS-DEMO-CTL-020"])) if c["code"] in codes]
                if links and k == len(history) - 1:
                    body["evidence_ids"] = links
                if c["execution_mode"] == "automatic":
                    body["source"] = "mcp"
                    body["provenance"] = {"collection_status": "complete", "query": "approved-query:" + c["code"].lower() + ":v1",
                                          "source_system": example.get("source_system"), "reference": example.get("reference"),
                                          "checked": example.get("checked"), "failed": example.get("failed")}
                    G.record_execution(db, machine, body)
                else:
                    G.record_execution(db, auditor, body)
        for code in ("TDR-CTL-07", "TDR-CTL-08", "TDR-CTL-09"):
            G.record_execution(db, auditor, {"control_id": ctl[code], "executed_at": stamp(r.randint(20, 70)),
                                             "status": "fail" if code == "TDR-CTL-07" else "pass", "severity": "high",
                                             "details": "8 kritik tedarikçi sözleşmesinden 2'sinde denetim hakkı maddesi yok." if code == "TDR-CTL-07"
                                             else "Örneklemdeki 12 kayıt gereksinimi karşılıyor.", "sample_size": 8 if code == "TDR-CTL-07" else 12,
                                             "exceptions": 2 if code == "TDR-CTL-07" else 0,
                                             "evidence_ids": [evidence[{"TDR-CTL-07": "sozlesme", "TDR-CTL-08": "erisim", "TDR-CTL-09": "kvkk"}[code]]]})
        # iç otomatik kontroller: portal verisinden gerçek sonuç
        for code, *_ in supplier_controls:
            G.run_automation(db, self.app, crud.get(db, RESOURCES["controls"], ctl[code]), admin)
        # denetimler
        audit_ids = {}

        def make_audit(key, name, kind, std_codes, clause_ids, start, end, status, supplier=None, objective=None):
            planned = {"name": name, "kind": kind, "supplier_id": supplier, "audit_objective": objective or "Kontrollerin tasarım ve işleyiş etkinliğini değerlendirmek.",
                       "scope": "Sentetik demo denetimi; gerçek sistem kaydı kullanılmadı.", "planned_start": day(start), "planned_end": day(end),
                       "lead_auditor": "Can Öztürk", "auditors": "Can Öztürk, Elif Şahin (gözlemci)", "auditees": "Satın Alma, BT Altyapı, Bilgi Güvenliği",
                       "code": f"DNT-{TODAY.year}-{len(audit_ids) + 1:04d}", "status": "planned", "created_at": stamp(-start + 20)}
            audit_id = db.execute(f"INSERT INTO tdr_audits ({', '.join(planned)}) VALUES ({', '.join('?' * len(planned))})",
                                  tuple(planned.values())).lastrowid
            for sid in std_codes:
                db.execute("INSERT INTO tdr_audit_standards (audit_id, standard_id) VALUES (?,?)", (audit_id, std[sid]))
            for cid in clause_ids:
                db.execute("INSERT INTO tdr_audit_clauses (audit_id, clause_id) VALUES (?,?)", (audit_id, cid))
            if status != "planned":
                db.execute("UPDATE tdr_audits SET status='in_progress', actual_start=? WHERE id=?", (day(start + 1), audit_id))
            audit_ids[key] = audit_id
            return audit_id

        def test_in_audit(audit_id, fail_rate, coverage):
            for link in {p["control_id"] for p in G.planned_controls(db, audit_id)}:
                control = crud.get(db, RESOURCES["controls"], link)
                if r.random() > coverage:
                    continue
                if control["automation"]:
                    G.run_automation(db, self.app, control, auditor, audit_id)
                    continue
                failed = r.random() < fail_rate
                body = {"control_id": link, "audit_id": audit_id, "status": "fail" if failed else "pass",
                        "executed_at": stamp(r.randint(2, 12), r.randint(9, 17)),
                        "details": "Denetim örnekleminde istisna bulundu." if failed else "Denetim örnekleminde istisna yok.",
                        "sample_size": 25, "exceptions": r.randint(1, 4) if failed else 0}
                if control["execution_mode"] == "automatic":
                    body["source"] = "mcp"
                    body["provenance"] = {"collection_status": "complete", "query": "approved-query:" + control["code"].lower() + ":v1"}
                    G.record_execution(db, machine, body)
                else:
                    G.record_execution(db, auditor, body)
        iso20_all = [cid for (s, _), cid in clause.items() if s == "ISO/IEC 20000-1"]
        cis_all = [cid for (s, code), cid in clause.items() if s == "CIS Controls" and code.split(".")[0] in ("1", "3", "4", "5", "6", "7", "8", "11", "17")]
        a1 = make_audit("iso", "ISO/IEC 20000-1:2018 — 2026 iç denetimi", "internal", ["ISO/IEC 20000-1"], iso20_all, -30, 10, "in_progress")
        test_in_audit(a1, 0.25, 0.7)
        a2 = make_audit("cis", "CIS Controls v8.1 — 2026 Q4 güvenlik kontrol değerlendirmesi", "internal", ["CIS Controls"], cis_all, -24, 15, "in_progress")
        test_in_audit(a2, 0.3, 0.55)
        a3 = make_audit("tdr", "Tedarikçi yönetimi süreç denetimi (ISO/IEC 27001 Ek A 5.19–5.23)", "internal", ["ISO/IEC 27001"],
                        iso27("A.5.19", "A.5.20", "A.5.21", "A.5.22", "A.5.23"), -70, -40, "in_progress")
        test_in_audit(a3, 0.3, 1.0)
        db.execute("UPDATE tdr_audits SET status='completed', actual_end=?, opinion='partially_effective', conclusion=? WHERE id=?",
                   (day(-41), "Tedarikçi izleme kontrolleri büyük ölçüde işliyor; sözleşme maddeleri ve gecikmiş değerlendirmeler için DÖF açıldı.", a3))
        for link in G.planned_controls(db, a3):
            db.execute("INSERT INTO tdr_audit_plan (audit_id, clause_id, control_id) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                       (a3, link["clause_id"], link["control_id"]))
        db.execute("UPDATE tdr_audits SET plan_captured_at=? WHERE id=?", (stamp(41), a3))
        make_audit("sup", f"{critical[0]['name']} — yerinde tedarikçi denetimi", "supplier", ["ISO/IEC 27001"],
                   iso27("A.5.19", "A.5.20", "A.5.22", "A.5.30"), 20, 24, "planned", supplier=critical[0]["id"],
                   objective="Kritik barındırma tedarikçisinin güvenlik ve süreklilik taahhütlerini yerinde doğrulamak.")
        for key, codes in (("sozlesme", ["tdr"]), ("erisim", ["tdr"]), ("cmdb", ["iso", "cis"]), ("rfc", ["iso"])):
            for a in codes:
                db.execute("INSERT INTO tdr_evidence_audits (evidence_id, audit_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                           (evidence[key], audit_ids[a]))
        # bulgular: sahip, kök neden, durum çeşitliliği; DÖF'ler
        findings = rows(db, "SELECT * FROM tdr_findings ORDER BY id")
        owners = ["mehmet.kaya", "okan.yildiz", "ayse.yilmaz", "deniz.koc", "kerem.aksoy"]
        causes = ["Süreç adımı tanımlı ama sahibi belirsiz.", "Otomatik kontrolün beslendiği veri kaynağı eksik.",
                  "Ekip kapasitesi yetersiz; iş yüküne göre önceliklendirilmedi.", "Prosedür güncel uygulamayı yansıtmıyor.",
                  "Tedarikçi sözleşmesinde yükümlülük açıkça yazılmamış."]
        titles = ["Kök neden analizi ve süreç düzeltmesi", "Eksik kayıtların tamamlanması", "Prosedürün güncellenmesi ve eğitim",
                  "Tedarikçiyle sözleşme ek protokolü", "Otomatik kontrol veri kaynağının düzeltilmesi"]
        for k, f in enumerate(findings):
            owner = r.choice(owners)
            db.execute("UPDATE tdr_findings SET owner=?, root_cause=? WHERE id=?", (owner, r.choice(causes), f["id"]))
            plan = k % 5
            if plan == 4:
                continue                                         # açık, faaliyetsiz
            db.execute("UPDATE tdr_findings SET status='in_progress' WHERE id=?", (f["id"],))
            unit = self.ids["unit"][{"mehmet.kaya": "BTA", "okan.yildiz": "BGV", "ayse.yilmaz": "SAT", "deniz.koc": "UYG", "kerem.aksoy": "OPS"}[owner]]
            due = r.choice([-15, -3, 20, 45, 75])
            status = ["open", "in_progress", "validation", "completed"][plan]
            action = db.execute(
                "INSERT INTO tdr_grc_actions (code, title, finding_id, control_id, description, owner, org_unit_id, due_date, priority, status, "
                "resolution, verified_by, verification_note, closed_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"DOF-{TODAY.year}-{k + 1:04d}", r.choice(titles), f["id"], f["control_id"], TAG, owner, unit, day(due),
                 r.choice(["medium", "high"]), status,
                 "Eksik kayıtlar tamamlandı, prosedür güncellendi; kanıt kanıt kaydında." if status in ("validation", "completed") else None,
                 "can.ozturk" if status == "completed" else None,
                 "Yeniden test edildi; 25 kayıtlık örneklemde istisna yok." if status == "completed" else None,
                 stamp(r.randint(1, 10)) if status == "completed" else None, stamp(r.randint(20, 60)))).lastrowid
            if status == "completed" and k % 2 == 0:
                db.execute("UPDATE tdr_findings SET status='closed', closure_note=?, closed_at=? WHERE id=?",
                           ("Düzeltici faaliyet etkinliği doğrulandı.", stamp(r.randint(1, 5)), f["id"]))
        if findings:
            last = findings[-1]
            db.execute("UPDATE tdr_findings SET status='accepted', closure_note=?, closed_at=? WHERE id=? AND status='open'",
                       ("Telafi edici kontrol mevcut; 2027 bütçesine kadar risk kabul edildi (Yönetici kararı).", stamp(3), last["id"]))
        audit.log(db, SYSTEM, "SEED", "grc_demo", None, {"controls": len(ctl), "audits": len(audit_ids)}, description=TAG)

    def _link(self, control_id, table, col, ids):
        for target in dict.fromkeys(i for i in ids if i):
            self.db.execute(f"INSERT INTO tdr_{table} (control_id, {col}) VALUES (?,?) ON CONFLICT DO NOTHING", (control_id, target))

    def _link_many(self, table, col, risk_id, control_ids, control=None, targets=()):
        pairs = [(c, risk_id) for c in control_ids] if control is None else [(control, t) for t in targets]
        for c, t in pairs:
            self.db.execute(f"INSERT INTO tdr_{table} (control_id, {col}) VALUES (?,?) ON CONFLICT DO NOTHING", (c, t))

    def _context(self):
        """Önceki sürümle yüklenmiş demoda kimlikleri veritabanından okur (kodlar sürümler arasında farklıdır)."""
        self.ids["unit"] = {code: one(self.db, "SELECT id FROM tdr_org_units WHERE name=?", (name,))["id"]
                            for code, name, _, _ in UNITS}
        self.suppliers = [{"id": r["id"], "tier": r["tier"], "status": r["status"], "name": r["name"]}
                          for r in rows(self.db, "SELECT * FROM tdr_suppliers WHERE description LIKE ? ORDER BY id", (f"%{TAG}%",))]

    def sections(self):
        added = []
        for name, module in SECTIONS:
            if self.enabled(module) and not self._done(name):
                getattr(self, name)()
                self._mark(name)
                added.append(name)
        self.finalize_risks()
        return added

    def resume(self):
        """Yüklü demoya yeni sürümün bölümlerini ekler; kullanıcılar ve parolaları değişmez."""
        self._context()
        added = []
        if self.enabled("grc") and not one(self.db, "SELECT id FROM tdr_controls LIMIT 1"):
            self.grc()
            added.append("grc")
        added += self.sections()
        if added:
            audit.log(self.db, SYSTEM, "SEED", "demo", None, {"sections": added}, description=TAG)
        return added

    def run(self):
        self.core()
        self.performance()
        self.risks()
        self.companies()
        self._mark("companies")
        self.surveys()
        self.grc()
        self.sections()
        passwords = self.users()
        audit.log(self.db, SYSTEM, "SEED", "demo", None,
                  {"suppliers": len(self.suppliers), "engagements": len(self.engagements)}, description=TAG)
        return passwords


def seed(app):
    """Boş veritabanına demo yükler (parola listesi döner); yüklü demoya eksik bölümleri ekler (bölüm listesi döner)."""
    with app.database.connect() as db:
        db.lock("demo-seed")
        if one(db, "SELECT id FROM tdr_suppliers WHERE description LIKE ? LIMIT 1", (f"%{TAG}%",)):
            added = Seeder(db, app).resume()
            return {"added": added} if added else None
        if one(db, "SELECT id FROM tdr_suppliers LIMIT 1"):
            raise SystemExit("Veritabanında demo dışı tedarikçi var; demo verisi yalnızca boş veritabanına yüklenir")
        return Seeder(db, app).run()


def main():
    from .http import build
    app = build(Config())
    try:
        passwords = seed(app)
    finally:
        app.close()
    if passwords is None:
        print("DEMO_ALREADY_LOADED")
        return
    if isinstance(passwords, dict):
        print("DEMO_SECTIONS_ADDED " + ",".join(passwords["added"]))
        return
    print("Demo verisi yüklendi (sentetik). Demo kullanıcılar ilk girişte parolalarını değiştirir:")
    for username, name, role, password in passwords:
        print(f"{username}\t{name}\t{role}\t{password}")


if __name__ == "__main__":
    sys.exit(main())
