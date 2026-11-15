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


class Seeder:
    def __init__(self, db, app):
        self.db, self.app, self.rnd = db, app, random.Random(20261115)
        self.ids = {}

    def enabled(self, module):
        return self.app.enabled(module)

    def add(self, res, data, created_days_ago=None):
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
        types = {t["code"]: t["id"] for t in rows(self.db, "SELECT id, code FROM tdr_supplier_types")}
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
        templates = {t["code"]: t["id"] for t in rows(self.db, "SELECT id, code FROM tdr_survey_templates")}
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

    def run(self):
        self.core()
        self.performance()
        self.risks()
        self.surveys()
        passwords = self.users()
        audit.log(self.db, SYSTEM, "SEED", "demo", None,
                  {"suppliers": len(self.suppliers), "engagements": len(self.engagements)}, description=TAG)
        return passwords


def seed(app):
    with app.database.connect() as db:
        db.lock("demo-seed")
        if one(db, "SELECT id FROM tdr_suppliers WHERE code LIKE 'DMO-%' LIMIT 1"):
            return None
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
    print("Demo verisi yüklendi (sentetik). Demo kullanıcılar ilk girişte parolalarını değiştirir:")
    for username, name, role, password in passwords:
        print(f"{username}\t{name}\t{role}\t{password}")


if __name__ == "__main__":
    sys.exit(main())
