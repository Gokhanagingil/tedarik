"""Demo verisinin GRC platformu bölümleri: şirketler, süreç mimarisi, kurumsal risk (ISO 31000), dokümanlar
(ISO 9001 7.5), CMDB ve iş sürekliliği (ISO 22301).

Her bölüm hem boş veritabanında (tam yükleme) hem de önceki sürümle yüklenmiş bir demoda (devam) çalışır:
kayıtları kodla değil adla bulur, kodları sunucu üretir (K-017). Bir bölüm yüklendiğinde iz kaydına
`demo-section` işareti yazılır; aynı bölüm ikinci kez yüklenmez.
"""
import hashlib
import json
import random
from datetime import date, datetime, timedelta, timezone

from . import crud
from .auth import Principal
from .db import one, rows, utcnow
from .schema import RESOURCES

TAG = "Sentetik demo verisi"
TODAY = date.today()
MACHINE = Principal("mcp", "MACHINE", "api_key", "MCP")


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def stamp(days_ago, hour=10):
    moment = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time()).replace(hour=hour, tzinfo=timezone.utc)
    return moment.isoformat(timespec="seconds")


COMPANIES = [  # ad, tür, üst şirket, sektör, ServiceNow şirket adı
    ("Demo Holding A.Ş.", "own", None, "Holding", "Demo Holding"),
    ("Demo Teknoloji A.Ş.", "own", "Demo Holding A.Ş.", "Bilgi teknolojileri ve yönetilen hizmetler", "Demo Teknoloji"),
    ("Demo Ödeme Hizmetleri A.Ş.", "own", "Demo Holding A.Ş.", "Ödeme ve elektronik para hizmetleri", "Demo Odeme"),
    ("Demo Banka A.Ş.", "customer", None, "Bankacılık", "Demo Banka"),
    ("Örnek Sigorta A.Ş.", "customer", None, "Sigortacılık", "Ornek Sigorta"),
    ("Kurgu Perakende A.Ş.", "customer", None, "Perakende", "Kurgu Perakende"),
]

# Süreç haritası (ISO 9001 4.4): ad → (tür, sıra, girdiler, çıktılar, birim adı, üst süreç adı)
PROCESS_MAP = {
    "Stratejik Planlama ve Yönetim Gözden Geçirmesi": ("management", 1, "Kurumsal hedefler, pazar ve düzenleyici beklentiler, performans raporları",
                                                       "Stratejik plan, hedefler, kaynak kararları", None, None),
    "Kurumsal Risk Yönetimi": ("management", 2, "Risk kayıtları, KRİ ölçümleri, denetim bulguları", "Risk profili, işleme planları, iştah beyanı",
                               "Bilgi Güvenliği", None),
    "İç Denetim ve İyileştirme": ("management", 3, "Denetim planı, kontrol test sonuçları", "Denetim raporları, bulgular, DÖF", "Hukuk ve Uyum", None),
    "Uyum Yönetimi": ("management", 4, "Standartlar, mevzuat ve sözleşme yükümlülükleri", "Uygulanabilirlik bildirimi, uyum raporu",
                      "Hukuk ve Uyum", None),
    "Satış ve Sipariş Yönetimi": ("core", 1, "Müşteri talebi, teklif", "Sözleşme, sipariş", "Müşteri Hizmetleri", None),
    "Hizmet Kataloğu": ("core", 2, "Hizmet tasarımı, müşteri ihtiyaçları", "Hizmet tanımları, sahiplik", "Operasyon", None),
    "Hizmet Seviyesi Yönetimi": ("core", 3, "Sözleşme hedefleri, ölçümler", "SLA raporları, iyileştirme talepleri", "Operasyon", None),
    "Olay Yönetimi": ("core", 4, "Kullanıcı ve izleme kayıtları", "Çözülmüş olaylar, bilgi kayıtları", "Müşteri Hizmetleri", None),
    "Major Incident Yönetimi": ("core", 5, "P1 olaylar", "Kriz iletişimi, olay sonrası rapor", "Operasyon", "Olay Yönetimi"),
    "Problem Yönetimi": ("core", 6, "Tekrarlayan olaylar", "Kök neden, bilinen hata kayıtları", "Operasyon", None),
    "Değişiklik Yönetimi": ("core", 7, "Değişiklik talepleri (RFC)", "Onaylı ve uygulanmış değişiklikler", "BT Altyapı ve Operasyon", None),
    "Sürüm ve Dağıtım Yönetimi": ("core", 8, "Onaylı değişiklikler, paketler", "Üretime alınmış sürümler", "Uygulama Geliştirme", None),
    "Güvenli Yazılım Geliştirme": ("core", 9, "İş gereksinimleri", "Test edilmiş yazılım", "Uygulama Geliştirme", None),
    "Ödeme İşlemleri": ("core", 10, "Ödeme talimatları, kart işlemleri", "Takas ve mutabakat kayıtları", "Finans", None),
    "Konfigürasyon Yönetimi": ("support", 1, "Keşif verisi, değişiklikler", "Güncel CMDB, bağımlılık haritası", "BT Altyapı ve Operasyon", None),
    "Varlık Yönetimi": ("support", 2, "Satın alma, keşif", "Varlık envanteri, lisans uyumu", "BT Altyapı ve Operasyon", None),
    "Kapasite Yönetimi": ("support", 3, "Kullanım eğilimleri", "Kapasite planı", "BT Altyapı ve Operasyon", None),
    "Hizmet Sürekliliği": ("support", 4, "BİA sonuçları, risk değerlendirmesi", "Süreklilik planları, tatbikat raporları", "Operasyon", None),
    "Bilgi Güvenliği": ("support", 5, "Tehdit istihbaratı, güvenlik olayları", "Güvenlik önlemleri, olay raporları", "Bilgi Güvenliği", None),
    "Kimlik ve Erişim Yönetimi": ("support", 6, "Erişim talepleri, İK hareketleri", "Yetkilendirilmiş hesaplar, gözden geçirme kayıtları",
                                  "Bilgi Güvenliği", "Bilgi Güvenliği"),
    "Zafiyet Yönetimi": ("support", 7, "Tarama sonuçları, üretici bültenleri", "Yama planı, iyileştirme kayıtları", "Bilgi Güvenliği", "Bilgi Güvenliği"),
    "Günlük/Log Yönetimi": ("support", 8, "Sistem günlükleri", "Saklanan ve izlenen kayıtlar", "Bilgi Güvenliği", "Bilgi Güvenliği"),
    "Tedarikçi Yönetimi": ("support", 9, "İhtiyaç, teklif, performans verisi", "Sözleşmeler, değerlendirmeler, tedarikçi riskleri", "Satın Alma", None),
    "Tedarikçi Performans ve Kanıt Takibi": ("support", 10, "SLA ölçümleri, tedarikçi kanıtları", "Performans raporu", "Satın Alma", "Tedarikçi Yönetimi"),
    "İnsan Kaynakları": ("support", 11, "Personel ihtiyacı", "Yetkin personel, eğitim kayıtları", "İnsan Kaynakları", None),
    "Doküman Yönetimi": ("support", 12, "Doküman talepleri", "Onaylı ve yürürlükte dokümanlar", "Hukuk ve Uyum", None),
    "Finans ve Muhasebe": ("support", 13, "Faturalar, bütçe", "Mali tablolar, ödemeler", "Finans", None),
}

APPETITES = [  # kategori, iştah, tolerans, beyan
    ("strategic", 12, 16, "Büyüme hedefleri için ölçülü risk alınır; stratejik riskler yönetim kurulunca üç ayda bir izlenir."),
    ("operational", 9, 12, "Hizmet kesintilerine düşük toleransımız vardır; kritik hizmetlerde artık risk orta seviyeyi aşmamalıdır."),
    ("financial", 10, 15, "Kur ve maliyet riskleri bütçenin %3'ünü aşmayacak şekilde yönetilir."),
    ("compliance", 6, 8, "Mevzuat ve sözleşme yükümlülüklerine aykırılığa tahammülümüz yoktur."),
    ("legal", 6, 8, "Hukuki uyuşmazlık doğurabilecek riskler hukuk biriminin onayı olmadan kabul edilmez."),
    ("technology", 9, 12, "Destek süresi bitmiş teknoloji yalnızca onaylı istisna ve telafi edici kontrolle kullanılır."),
    ("security", 8, 12, "Bilgi güvenliği risklerinde iştah düşüktür; kritik açıklar 30 gün içinde kapatılır."),
    ("privacy", 6, 8, "Kişisel veri ihlali riskine tahammül edilmez."),
    ("continuity", 8, 12, "Kritik hizmetler BİA'da belirlenen RTO içinde kurtarılabilmelidir."),
    ("supplier", 9, 12, "Kritik tedarikçilerde alternatif ve çıkış planı olmadan risk kabul edilmez."),
]

CI_SEED = [
    # ad, sınıf, şirket, kritiklik, ortam, ek alanlar
    ("ITSM Platformu", "business_app", "Demo Teknoloji", "critical", "production", {"owner": "Zeynep Demir", "version": "2026.1"}),
    ("Müşteri Portalı", "business_app", "Demo Teknoloji", "high", "production", {"owner": "Deniz Koç"}),
    ("CRM Uygulaması", "business_app", "Demo Teknoloji", "high", "production", {"owner": "Zeynep Demir"}),
    ("ERP Uygulaması", "business_app", "Demo Teknoloji", "high", "production", {"owner": "Ayla Çetin", "vendor": "Örnek ERP", "version": "7.2",
                                                                                "eos_date": -95}),
    ("Kimlik Yönetimi (IAM)", "business_app", "Demo Teknoloji", "critical", "production", {"owner": "Okan Yıldız"}),
    ("SIEM ve Log Platformu", "business_app", "Demo Teknoloji", "high", "production", {"owner": "Okan Yıldız"}),
    ("Yedekleme Yönetimi", "business_app", "Demo Teknoloji", "critical", "production", {"owner": "Mehmet Kaya"}),
    ("Çağrı Merkezi Uygulaması", "business_app", "Demo Teknoloji", "high", "production", {"owner": "Zeynep Demir"}),
    ("srv-itsm-app01", "server", "Demo Teknoloji", "critical", "production", {"os": "Red Hat Enterprise Linux", "os_version": "9.4", "patch": 12, "boot": 20}),
    ("srv-itsm-db01", "server", "Demo Teknoloji", "critical", "production", {"os": "Oracle Linux", "os_version": "7.9", "os_eos_date": -500, "patch": 20, "boot": 45}),
    ("srv-crm-app01", "server", "Demo Teknoloji", "high", "production", {"os": "Windows Server", "os_version": "2012 R2", "os_eos_date": -1130, "patch": 62, "boot": 180}),
    ("srv-erp-app01", "server", "Demo Teknoloji", "high", "production", {"os": "Windows Server", "os_version": "2016", "patch": 48, "missing": 3, "boot": 30}),
    ("srv-portal-web01", "server", "Demo Teknoloji", "high", "production", {"os": "Ubuntu", "os_version": "22.04 LTS", "patch": 9, "boot": 9}),
    ("srv-portal-web02", "server", "Demo Teknoloji", "high", "production", {"os": "Ubuntu", "os_version": "22.04 LTS", "patch": 9, "boot": 9}),
    ("srv-iam01", "server", "Demo Teknoloji", "critical", "production", {"os": "Red Hat Enterprise Linux", "os_version": "8.10", "patch": 15, "boot": 15}),
    ("srv-siem01", "server", "Demo Teknoloji", "high", "production", {"os": "Red Hat Enterprise Linux", "os_version": "8.10", "patch": 30, "boot": 163}),
    ("srv-bkp01", "server", "Demo Teknoloji", "critical", "production", {"os": "Windows Server", "os_version": "2019", "patch": 21, "boot": 21}),
    ("srv-cc-app01", "server", "Demo Teknoloji", "high", "production", {"os": "Windows Server", "os_version": "2019", "patch": 40, "missing": 2, "boot": 40}),
    ("srv-test-legacy01", "server", "Demo Teknoloji", "low", "test", {"os": "CentOS", "os_version": "7", "os_eos_date": -500, "patch": 300, "boot": 400}),
    ("ITSM Oracle Veritabanı", "database", "Demo Teknoloji", "critical", "production", {"vendor": "Oracle", "version": "12c", "eos_date": -1690, "patch": 25}),
    ("CRM SQL Server", "database", "Demo Teknoloji", "high", "production", {"vendor": "Microsoft SQL Server", "version": "2014", "eos_date": -490, "patch": 70}),
    ("Portal PostgreSQL", "database", "Demo Teknoloji", "high", "production", {"vendor": "PostgreSQL", "version": "16", "patch": 10}),
    ("Ödeme Ağ Geçidi", "business_app", "Demo Odeme", "critical", "production", {"owner": "Ayla Çetin"}),
    ("Dolandırıcılık İzleme", "business_app", "Demo Odeme", "high", "production", {"owner": "Okan Yıldız"}),
    ("srv-pay-app01", "server", "Demo Odeme", "critical", "production", {"os": "Red Hat Enterprise Linux", "os_version": "9.4", "patch": 8, "boot": 8}),
    ("srv-pay-app02", "server", "Demo Odeme", "critical", "production", {"os": "Red Hat Enterprise Linux", "os_version": "9.4", "patch": 8, "boot": 8}),
    ("srv-pay-db01", "server", "Demo Odeme", "critical", "production", {"os": "Red Hat Enterprise Linux", "os_version": "8.10", "patch": 52, "missing": 1, "boot": 52}),
    ("srv-pay-hsmgw01", "server", "Demo Odeme", "critical", "production", {"os": "Red Hat Enterprise Linux", "os_version": "8.10", "patch": 20, "boot": 131}),
    ("Kart İşlem Sistemi (yönetilen hizmet)", "business_app", "Demo Banka", "critical", "production", {"owner": "Müşteri: Demo Banka BT"}),
    ("srv-db-kart01", "server", "Demo Banka", "critical", "production", {"os": "Windows Server", "os_version": "2012 R2", "os_eos_date": -1130, "patch": 33, "boot": 70}),
    ("srv-db-kart02", "server", "Demo Banka", "critical", "production", {"os": "Windows Server", "os_version": "2019", "patch": 41, "missing": 5, "boot": 41}),
    ("Kart Switch Yazılımı", "application", "Demo Banka", "critical", "production", {"vendor": "Örnek Switch", "version": "3.4", "eos_date": -40}),
    ("Poliçe Yönetim Sistemi", "business_app", "Ornek Sigorta", "high", "production", {"owner": "Müşteri: Örnek Sigorta BT"}),
    ("srv-os-pol01", "server", "Ornek Sigorta", "high", "production", {"os": "CentOS", "os_version": "7", "os_eos_date": -500, "patch": 90, "boot": 212}),
    ("Poliçe Oracle Veritabanı", "database", "Ornek Sigorta", "high", "production", {"vendor": "Oracle", "version": "19c", "patch": 28}),
    ("Mağaza Satış Noktası Arka Ofis", "business_app", "Kurgu Perakende", "medium", "production", {"owner": "Müşteri: Kurgu Perakende BT"}),
    ("srv-kp-pos01", "server", "Kurgu Perakende", "medium", "production", {"os": "Ubuntu", "os_version": "18.04 LTS", "os_eos_date": -900, "patch": 80, "boot": 95}),
    ("srv-dr-itsm01", "server", "Demo Teknoloji", "critical", "dr", {"os": "Red Hat Enterprise Linux", "os_version": "9.4", "patch": 14, "boot": 14}),
    ("srv-lab-unmapped01", "server", None, "medium", "production", {"os": "Debian", "os_version": "10", "os_eos_date": -500, "patch": 200, "boot": 300}),
]
CI_RELATIONS = [  # üst (kullanan) → alt (bağımlı olunan)
    ("ITSM Platformu", "srv-itsm-app01"), ("ITSM Platformu", "ITSM Oracle Veritabanı"), ("ITSM Oracle Veritabanı", "srv-itsm-db01"),
    ("CRM Uygulaması", "srv-crm-app01"), ("CRM Uygulaması", "CRM SQL Server"), ("ERP Uygulaması", "srv-erp-app01"),
    ("Müşteri Portalı", "srv-portal-web01"), ("Müşteri Portalı", "srv-portal-web02"), ("Müşteri Portalı", "Portal PostgreSQL"),
    ("Kimlik Yönetimi (IAM)", "srv-iam01"), ("SIEM ve Log Platformu", "srv-siem01"), ("Yedekleme Yönetimi", "srv-bkp01"),
    ("Çağrı Merkezi Uygulaması", "srv-cc-app01"), ("Ödeme Ağ Geçidi", "srv-pay-app01"), ("Ödeme Ağ Geçidi", "srv-pay-app02"),
    ("Ödeme Ağ Geçidi", "srv-pay-db01"), ("Ödeme Ağ Geçidi", "srv-pay-hsmgw01"), ("Dolandırıcılık İzleme", "srv-pay-db01"),
    ("Kart İşlem Sistemi (yönetilen hizmet)", "Kart Switch Yazılımı"), ("Kart İşlem Sistemi (yönetilen hizmet)", "srv-db-kart01"),
    ("Kart İşlem Sistemi (yönetilen hizmet)", "srv-db-kart02"), ("Poliçe Yönetim Sistemi", "srv-os-pol01"),
    ("Poliçe Yönetim Sistemi", "Poliçe Oracle Veritabanı"), ("Mağaza Satış Noktası Arka Ofis", "srv-kp-pos01"),
    ("ITSM Platformu", "srv-dr-itsm01"),
]

# BİA: başlık, süreç, şirket, birim, sahip, MTPD penceresi, duyarlılık (kategori → kayma), RTO, RPO, durum, uygulamalar, tedarikçi hizmetleri
BIAS = [
    ("Olay yönetimi ve servis masası", "Olay Yönetimi", "Demo Teknoloji A.Ş.", "Müşteri Hizmetleri", "zeynep.demir", "h4",
     {"customer": 0, "operational": 0, "reputational": 1, "financial": 2, "legal": 2}, 2, 0.5, "approved",
     ["ITSM Platformu", "Çağrı Merkezi Uygulaması", "Kimlik Yönetimi (IAM)"], ["Çağrı merkezi hizmeti", "Kurumsal MPLS ve internet hattı"]),
    ("Ödeme işlemleri", "Ödeme İşlemleri", "Demo Ödeme Hizmetleri A.Ş.", "Finans", "ayse.yilmaz", "h1",
     {"financial": 0, "customer": 0, "legal": 1, "reputational": 1, "operational": 1}, 0.5, 0, "approved",
     ["Ödeme Ağ Geçidi", "Dolandırıcılık İzleme"], ["Ödeme altyapısı (sanal POS)", "Veri merkezi barındırma (colocation)"]),
    ("Değişiklik ve sürüm yönetimi", "Değişiklik Yönetimi", "Demo Teknoloji A.Ş.", "BT Altyapı ve Operasyon", "mehmet.kaya", "d1",
     {"operational": 0, "customer": 1, "financial": 2, "reputational": 2, "legal": 3}, 8, 4, "approved",
     ["ITSM Platformu"], []),
    ("Güvenlik operasyon merkezi izleme", "Bilgi Güvenliği", "Demo Teknoloji A.Ş.", "Bilgi Güvenliği", "okan.yildiz", "h8",
     {"legal": 0, "reputational": 0, "operational": 1, "customer": 1, "financial": 2}, 4, 1, "approved",
     ["SIEM ve Log Platformu", "Kimlik Yönetimi (IAM)"], ["Güvenlik operasyon merkezi (SOC) izleme"]),
    ("Satış ve sipariş yönetimi", "Satış ve Sipariş Yönetimi", "Demo Teknoloji A.Ş.", "Müşteri Hizmetleri", "zeynep.demir", "d3",
     {"financial": 0, "customer": 1, "operational": 2, "reputational": 2, "legal": 3}, 24, 8, "in_review",
     ["CRM Uygulaması", "ERP Uygulaması"], ["CRM yazılım hizmeti (SaaS)"]),
    ("Hizmet seviyesi yönetimi", "Hizmet Seviyesi Yönetimi", "Demo Teknoloji A.Ş.", "Operasyon", "kerem.aksoy", "d1",
     {"customer": 0, "reputational": 1, "financial": 1, "operational": 2, "legal": 2}, 12, 4, "approved",
     ["ITSM Platformu", "Müşteri Portalı"], ["Kurumsal MPLS ve internet hattı"]),
    ("Problem yönetimi", "Problem Yönetimi", "Demo Teknoloji A.Ş.", "Operasyon", "kerem.aksoy", "w1",
     {"operational": 0, "customer": 1, "reputational": 2, "financial": 3, "legal": 3}, 72, 24, "draft",
     ["ITSM Platformu"], []),
    ("Tedarikçi yönetimi", "Tedarikçi Yönetimi", "Demo Teknoloji A.Ş.", "Satın Alma", "ayse.yilmaz", "w1",
     {"operational": 0, "financial": 1, "legal": 1, "customer": 2, "reputational": 3}, None, None, "draft",
     ["ERP Uygulaması"], []),
]


class PlatformSections:
    """Seeder'a eklenen GRC platformu bölümleri (self.db, self.ids, self.add, self.enabled Seeder'dan gelir)."""

    # -------------------------------------------------------------- yardımcılar
    def _done(self, section):
        return bool(one(self.db, "SELECT id FROM tdr_audit_log WHERE actor='demo-seed' AND object_type='demo-section' "
                                 "AND object_id=? LIMIT 1", (section,)))

    def _mark(self, section):
        from . import audit
        from .demo import SYSTEM
        audit.log(self.db, SYSTEM, "SEED", "demo-section", section, None, description=f"{TAG}: {section}")

    def _by(self, table, column, value):
        row = one(self.db, f"SELECT id FROM tdr_{table} WHERE {column}=? ORDER BY id LIMIT 1", (value,))
        return row["id"] if row else None

    def _unit(self, name):
        return self._by("org_units", "name", name) if name else None

    def _process(self, name):
        return self._by("processes", "name", name)

    def _company(self, name):
        return self._by("companies", "name", name)

    def _risk(self, title, company=None):
        sql, args = "SELECT id FROM tdr_supplier_risks WHERE title=?", [title]
        if company:
            sql += " AND company_id=?"
            args.append(company)
        row = one(self.db, sql + " ORDER BY id LIMIT 1", tuple(args))
        return row["id"] if row else None

    def _supplier_for(self, item_name):
        row = one(self.db, """SELECT e.supplier_id, e.id FROM tdr_engagements e JOIN tdr_catalog_items c ON c.id=e.catalog_item_id
            JOIN tdr_suppliers s ON s.id=e.supplier_id WHERE c.name=? ORDER BY CASE s.tier WHEN 'critical' THEN 0
            WHEN 'important' THEN 1 ELSE 2 END, e.id LIMIT 1""", (item_name,))
        return (row["supplier_id"], row["id"]) if row else (None, None)

    def _assess(self, risk_id, assessor, rationale, mitigation, days_ago):
        from .modules import risks as R
        risk = crud.get(self.db, RESOURCES["supplier_risks"], risk_id)
        weight = "high" if mitigation >= 0.5 else "medium" if mitigation >= 0.3 else "low"
        mitigations = [{"title": "Mevcut kontroller", "weight": weight, "effectiveness": "effective"}] if mitigation else []
        total, credits = R.contribution(mitigations)
        return R.record_assessment(self.db, risk, assessor, rationale + " " + TAG, total, credits, stamp(days_ago))

    # -------------------------------------------------------------- şirketler (K-018)
    def companies(self):
        db, ids = self.db, {}
        own = one(db, "SELECT id FROM tdr_companies WHERE kind='own' ORDER BY id LIMIT 1")
        for name, kind, parent, sector, sn in COMPANIES:
            data = {"name": name, "kind": kind, "parent_id": ids.get(parent), "sector": sector, "country": "Türkiye",
                    "servicenow_ref": sn, "description": TAG,
                    "tax_id": str(self.rnd.randint(1000000000, 9999999999))}
            if name == "Demo Teknoloji A.Ş." and own:
                sets = ", ".join(f"{k}=?" for k in data)
                db.execute(f"UPDATE tdr_companies SET {sets}, updated_at=? WHERE id=?", (*data.values(), utcnow(), own["id"]))
                ids[name] = own["id"]
            else:
                ids[name] = self.add("companies", data)
        self.ids["company"] = ids
        for name in ("Demo Banka A.Ş.", "Örnek Sigorta A.Ş.", "Kurgu Perakende A.Ş."):
            db.execute("UPDATE tdr_engagements SET customer_company_id=? WHERE customer_name=?", (ids[name], name))
        # müşteriye sunulan hizmetlerden doğan tedarikçi riskleri ilgili müşteriye aittir
        for r in rows(db, """SELECT DISTINCT r.id, e.customer_company_id FROM tdr_supplier_risks r JOIN tdr_engagements e
                ON e.supplier_id=r.supplier_id WHERE e.beneficiary='customer' AND e.customer_company_id IS NOT NULL"""):
            if self.rnd.random() < 0.35:
                db.execute("UPDATE tdr_supplier_risks SET company_id=? WHERE id=?", (r["customer_company_id"], r["id"]))

    # -------------------------------------------------------------- süreç mimarisi (ISO 9001 4.4)
    def architecture(self):
        db = self.db
        # KS GRC senaryosundaki ikinci "Tedarikçi Yönetimi" alt süreç olarak adlandırılır
        dup = rows(db, "SELECT id, description FROM tdr_processes WHERE name='Tedarikçi Yönetimi' ORDER BY id")
        if len(dup) > 1:
            for p in dup:
                if "performans" in (p["description"] or "").lower():
                    db.execute("UPDATE tdr_processes SET name=? WHERE id=?", ("Tedarikçi Performans ve Kanıt Takibi", p["id"]))
        for name in PROCESS_MAP:
            if not self._process(name):
                kind = PROCESS_MAP[name][0]
                self.add("processes", {"name": name, "process_type": kind, "description": TAG,
                                       "owner": {"management": "Selin Aydın", "core": "Kerem Aksoy"}.get(kind, "Mehmet Kaya")})
        for name, (kind, position, inputs, outputs, unit, parent) in PROCESS_MAP.items():
            db.execute("UPDATE tdr_processes SET process_type=?, position=?, inputs=?, outputs=?, org_unit_id=COALESCE(?, org_unit_id), "
                       "parent_id=? WHERE name=?", (kind, position, inputs, outputs, self._unit(unit),
                                                    self._process(parent) if parent else None, name))
        # haritada yer almayan eski senaryo süreçleri destek süreci sayılır
        db.execute("UPDATE tdr_processes SET process_type='support', position=COALESCE(position, 99) WHERE position IS NULL")
        # kontrol hedeflerinin süreç ve sahipleri
        for name, process, owner in (
                ("CI envanteri eksiksiz ve izlenebilir olmalı", "Konfigürasyon Yönetimi", "Mehmet Kaya"),
                ("Üretim değişiklikleri yetkilendirilip iz bırakmalı", "Değişiklik Yönetimi", "Mehmet Kaya"),
                ("Müşteri hizmet seviyeleri ölçülmeli ve sapmalar yönetilmeli", "Hizmet Seviyesi Yönetimi", "Kerem Aksoy"),
                ("Olay ve problem kayıtları zamanında işlenmeli", "Olay Yönetimi", "Zeynep Demir"),
                ("Varlıkların güvenli konfigürasyonu ve yamaları doğrulanmalı", "Zafiyet Yönetimi", "Okan Yıldız"),
                ("Kritik hizmetlerde geri dönüş ve kurtarma mümkün olmalı", "Hizmet Sürekliliği", "Kerem Aksoy"),
                ("Erişimler, günlükler ve güvenlik olayları izlenmeli", "Bilgi Güvenliği", "Okan Yıldız"),
                ("Tedarikçi yükümlülüklerinin yerine geldiği doğrulanmalı", "Tedarikçi Yönetimi", "Ayşe Yılmaz"),
                ("Denetim kapsamı, kanıt ve düzeltici faaliyet izlenebilmeli", "İç Denetim ve İyileştirme", "Emre Tan"),
                ("Sipariş ve mali onay iş akışları kontrol edilebilmeli", "Satış ve Sipariş Yönetimi", "Ayla Çetin"),
                ("Kritik tedarikçiler periyodik olarak izlenmeli ve riskleri yönetilmeli", "Tedarikçi Yönetimi", "Ayşe Yılmaz")):
            db.execute("UPDATE tdr_objectives SET process_id=?, owner=? WHERE name=?", (self._process(process), owner, name))

    def audit_scope(self):
        """Denetimlerin kapsadığı süreçler: kapsam maddelerine eşli kontrollerin süreçleri (ISO 9001 9.2)."""
        self.db.execute("""INSERT INTO tdr_audit_processes (audit_id, process_id) SELECT DISTINCT ac.audit_id, cp.process_id
            FROM tdr_audit_clauses ac JOIN tdr_control_clauses cc ON cc.clause_id=ac.clause_id
            JOIN tdr_control_processes cp ON cp.control_id=cc.control_id ON CONFLICT DO NOTHING""")

    def audit_archive(self):
        """Denetim arşivi için önceki yılın tamamlanmış denetimi: sonuçlar ve o sonuçlara dondurulmuş kanıt sürümleri."""
        from .modules import grc as G
        db, r = self.db, random.Random(20261117)
        auditor = Principal("can.ozturk", "AUDITOR", "system", "Can Öztürk")
        machine = MACHINE
        year = TODAY.year - 1
        if one(db, "SELECT id FROM tdr_audits WHERE code=?", (f"DNT-{year}-0001",)):
            return
        clause_ids = [x["id"] for x in rows(db, """SELECT cl.id FROM tdr_clauses cl JOIN tdr_standards s ON s.id=cl.standard_id
            WHERE s.code='ISO/IEC 27001' AND cl.code IN ('A.5.19','A.5.20','A.5.21','A.5.22','A.5.23')""")]
        if not clause_ids:
            return
        std_id = one(db, "SELECT id FROM tdr_standards WHERE code='ISO/IEC 27001'")["id"]
        start, end = 395, 380
        audit_id = db.execute(
            "INSERT INTO tdr_audits (code, name, kind, audit_objective, scope, planned_start, planned_end, actual_start, "
            "lead_auditor, auditors, auditees, status, revision, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"DNT-{year}-0001", f"Tedarikçi ilişkileri iç denetimi — {year} (ISO/IEC 27001 Ek A 5.19–5.23)", "internal",
             "Tedarikçi güvenlik gereksinimlerinin sözleşmelere yansıması ve izlenmesinin etkinliği.",
             "Kritik ve önemli tedarikçiler; sözleşme, erişim, izleme ve değişiklik süreçleri. " + TAG, day(-start), day(-end),
             day(-start), "Can Öztürk", "Can Öztürk, Okan Yıldız", "Satın Alma, Bilgi Güvenliği", "in_progress", 0,
             stamp(start + 20))).lastrowid
        db.execute("INSERT INTO tdr_audit_standards (audit_id, standard_id) VALUES (?,?)", (audit_id, std_id))
        for cid in clause_ids:
            db.execute("INSERT INTO tdr_audit_clauses (audit_id, clause_id) VALUES (?,?)", (audit_id, cid))
        documents = [("Tedarikçi sözleşmeleri güvenlik maddesi örneklemi", "sozlesme-orneklem.csv",
                      b"sozlesme,guvenlik_maddesi,denetim_hakki\nSOZ-1,var,var\nSOZ-2,var,yok\n", "confidential"),
                     ("Tedarikçi erişim listesi gözden geçirme tutanağı", "erisim-gozden-gecirme.pdf",
                      b"%PDF-1.4\n% Sentetik demo: erisim gozden gecirme tutanagi\n%%EOF\n", "internal"),
                     ("Kritik tedarikçi performans değerlendirme raporları", "performans-raporlari.pdf",
                      b"%PDF-1.4\n% Sentetik demo: performans raporlari\n%%EOF\n", "internal"),
                     ("Bulut sağlayıcı sızma testi raporu (kısıtlı)", "sizma-testi.pdf",
                      b"%PDF-1.4\n% Sentetik demo: sizma testi raporu\n%%EOF\n", "restricted")]
        evidence = []
        for title, name, content, conf in documents:
            eid = crud.insert(db, RESOURCES["evidence"], {"title": title, "description": TAG, "confidentiality": conf,
                                                          "period_start": day(-start - 365), "period_end": day(-start)}, auditor)
            db.execute("UPDATE tdr_evidence SET created_at=? WHERE id=?", (stamp(start - 2), eid))
            G.store_file(db, eid, name, content, "can.ozturk", stamp(start - 2))
            evidence.append(eid)
            for cid in clause_ids[:3]:
                db.execute("INSERT INTO tdr_evidence_clauses (evidence_id, clause_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                           (eid, cid))
            db.execute("INSERT INTO tdr_evidence_audits (evidence_id, audit_id) VALUES (?,?)", (eid, audit_id))
        for n, link in enumerate(sorted({p["control_id"] for p in G.planned_controls(db, audit_id)})):
            control = crud.get(db, RESOURCES["controls"], link)
            if not control["active"]:
                continue
            failed = n % 4 == 1
            body = {"control_id": link, "audit_id": audit_id, "status": "fail" if failed else "pass",
                    "executed_at": stamp(start - 3 - n % 8, 10 + n % 6), "sample_size": 20, "exceptions": 2 if failed else 0,
                    "details": ("Örneklemdeki 20 sözleşmeden 2'sinde denetim hakkı maddesi yok." if failed else
                                "Örneklemde istisna bulunmadı; kanıt dosyası incelendi."),
                    "evidence_ids": [evidence[n % len(evidence)], evidence[(n + 1) % len(evidence)]]}
            if control["execution_mode"] == "automatic" and not control["automation"]:
                body.update(source="mcp", provenance={"collection_status": "complete", "query": "approved-query:arsiv:v1"})
                G.record_execution(db, machine, body)
            else:                                    # iç otomatik kontrolü denetçi örneklemle yeniden uyguladı
                G.record_execution(db, auditor, body)
        for link in G.planned_controls(db, audit_id):
            db.execute("INSERT INTO tdr_audit_plan (audit_id, clause_id, control_id) VALUES (?,?,?) ON CONFLICT DO NOTHING",
                       (audit_id, link["clause_id"], link["control_id"]))
        db.execute("UPDATE tdr_audits SET status='closed', actual_end=?, opinion='partially_effective', conclusion=?, "
                   "plan_captured_at=? WHERE id=?", (day(-end), "Sözleşme güvenlik maddeleri büyük ölçüde mevcut; iki "
                   "sözleşmede denetim hakkı eksikti, DÖF ile tamamlandı.", stamp(end), audit_id))
        for f in rows(db, "SELECT id FROM tdr_findings WHERE audit_id=?", (audit_id,)):
            db.execute("UPDATE tdr_findings SET status='closed', closure_note=?, closed_at=?, owner='ayse.yilmaz', "
                       "created_at=? WHERE id=?", ("Sözleşme ek protokolleri imzalandı; yeniden test başarılı.",
                                                   stamp(end - 60), stamp(start - 5), f["id"]))
        db.execute("INSERT INTO tdr_audit_processes (audit_id, process_id) SELECT ?, id FROM tdr_processes WHERE name "
                   "IN ('Tedarikçi Yönetimi', 'Bilgi Güvenliği') ON CONFLICT DO NOTHING", (audit_id,))

    # -------------------------------------------------------------- kurumsal risk (ISO 31000)
    def erm(self):
        db, r = self.db, self.rnd
        company = {n: self._company(n) for n, *_ in COMPANIES}
        tech = company["Demo Teknoloji A.Ş."] or one(db, "SELECT id FROM tdr_companies WHERE kind='own' ORDER BY id LIMIT 1")["id"]
        for category, appetite, tolerance, statement in APPETITES:
            if not one(db, "SELECT id FROM tdr_risk_appetites WHERE category=?", (category,)):
                self.add("risk_appetites", {"category": category, "appetite": appetite, "tolerance": tolerance,
                                            "statement": statement, "approved_by": "Yönetim Kurulu", "approved_on": day(-200),
                                            "review_date": day(165)})
        # mevcut riskleri süreç, birim ve etki alanıyla zenginleştir
        process_for = {"security": "Bilgi Güvenliği", "continuity": "Hizmet Sürekliliği", "privacy": "Bilgi Güvenliği",
                       "operational": "Değişiklik Yönetimi", "concentration": "Tedarikçi Yönetimi", "exit": "Tedarikçi Yönetimi",
                       "financial": "Tedarikçi Yönetimi", "compliance": "Tedarikçi Yönetimi", "performance": "Tedarikçi Yönetimi"}
        area_for = {"security": "information", "privacy": "information", "continuity": "operational", "financial": "financial",
                    "compliance": "legal", "performance": "customer", "concentration": "operational", "exit": "operational"}
        catalog_process = {"Yetkisiz üretim değişikliği": "Değişiklik Yönetimi", "Yedekten geri dönüş": "Hizmet Sürekliliği",
                           "Kritik yamada gecikme": "Zafiyet Yönetimi", "Eksik hizmet bağımlılıkları": "Konfigürasyon Yönetimi",
                           "Veri merkezi kapasitesi": "Kapasite Yönetimi", "Kanıtlarda kişisel veri": "İç Denetim ve İyileştirme"}
        unit_for = {"Bilgi Güvenliği": "Bilgi Güvenliği", "Hizmet Sürekliliği": "Operasyon", "Tedarikçi Yönetimi": "Satın Alma",
                    "Değişiklik Yönetimi": "BT Altyapı ve Operasyon", "Zafiyet Yönetimi": "Bilgi Güvenliği",
                    "Konfigürasyon Yönetimi": "BT Altyapı ve Operasyon", "Kapasite Yönetimi": "BT Altyapı ve Operasyon",
                    "İç Denetim ve İyileştirme": "Hukuk ve Uyum"}
        for risk in rows(db, "SELECT id, title, category, likelihood, impact FROM tdr_supplier_risks WHERE process_id IS NULL"):
            process = catalog_process.get(risk["title"]) or process_for.get(risk["category"])
            if not process:
                continue
            target_l = max(1, risk["likelihood"] - r.choice([1, 2]))
            target_i = max(1, risk["impact"] - r.choice([0, 1]))
            db.execute("UPDATE tdr_supplier_risks SET process_id=?, org_unit_id=COALESCE(org_unit_id, ?), impact_area=COALESCE(impact_area, ?), "
                       "target_likelihood=COALESCE(target_likelihood, ?), target_impact=COALESCE(target_impact, ?), "
                       "consulted=COALESCE(consulted, ?) WHERE id=?",
                       (self._process(process), self._unit(unit_for.get(process)), area_for.get(risk["category"], "operational"),
                        target_l, target_i, "Süreç sahibi, Bilgi Güvenliği, İç Denetim", risk["id"]))
        # değerlendirme dönemleri: kapanmış yarıyıl + açık dönem (kendi şirketimiz) + müşteri dönemi
        closed = self.add("risk_cycles", {"name": "Kurumsal risk değerlendirmesi — önceki dönem", "company_id": tech,
                                          "period_start": day(-245), "period_end": day(-66), "status": "open",
                                          "owner": "Okan Yıldız", "scope": "Tüm kurumsal ve tedarikçi riskleri",
                                          "description": TAG}, created_days_ago=250)
        # önceki dönemin değerlendirmeleri (geçmiş tarihli; riskin güncel özetini değiştirmez)
        for risk in rows(db, "SELECT id, created_at FROM tdr_supplier_risks WHERE company_id=? AND status IN "
                             "('open','in_treatment','accepted') ORDER BY id", (tech,)):
            created_ago = (TODAY - date.fromisoformat(str(risk["created_at"])[:10])).days
            if created_ago > 75 and r.random() < 0.85:
                self._assess(risk["id"], r.choice(["okan.yildiz", "ayse.yilmaz"]), "Dönemsel kurumsal risk değerlendirmesi.",
                             r.choice([0, 0.2, 0.4]), r.randint(70, min(created_ago - 2, 240)))
        db.execute("UPDATE tdr_risk_cycles SET status='closed' WHERE id=?", (closed,))
        self.add("risk_cycles", {"name": "Kurumsal risk değerlendirmesi — içinde bulunulan dönem", "company_id": tech,
                                 "period_start": day(-65), "period_end": day(50), "status": "open", "owner": "Okan Yıldız",
                                 "scope": "Tüm kurumsal, tedarikçi ve CMDB kaynaklı riskler; süreç sahipleriyle atölye çalışmaları",
                                 "description": TAG}, created_days_ago=66)
        if company["Demo Banka A.Ş."]:
            self.add("risk_cycles", {"name": "Demo Banka yönetilen hizmet risk gözden geçirmesi",
                                     "company_id": company["Demo Banka A.Ş."], "period_start": day(-20), "period_end": day(40),
                                     "status": "open", "owner": "Kerem Aksoy",
                                     "scope": "Sözleşme kapsamındaki altyapı ve uygulamalar", "description": TAG}, created_days_ago=21)
        self.add("risk_cycles", {"name": "Kurumsal risk değerlendirmesi — sonraki dönem", "company_id": tech,
                                 "period_start": day(51), "period_end": day(230), "status": "planned", "owner": "Okan Yıldız",
                                 "description": TAG})
        # yeni kurumsal riskler (fırsatlar dahil)
        new = [
            # başlık, kategori, şirket, süreç, tür, O, E, hedefO, hedefE, sahip, etki alanı, neden, olay, sonuç, yanıt, gözden geçirme
            ("Bulut dönüşümünde yetkin personel eksikliği", "people", "Demo Teknoloji A.Ş.", "İnsan Kaynakları", "threat", 4, 3, 2, 3,
             "selin.aydin", "people", "Bulut mimarisi yetkinliği olan personel piyasada az olduğu için",
             "dönüşüm projeleri planlanan sürede tamamlanamayabilir", "maliyet artışı ve müşteri taahhütlerinde gecikme yaşanabilir", "mitigate", 40),
            ("Yapay zekâ destekli olay sınıflandırma ile çözüm süresinin kısalması", "operational", "Demo Teknoloji A.Ş.", "Olay Yönetimi",
             "opportunity", 3, 4, None, None, "zeynep.demir", "customer", "Olay kayıtları yeterli olgunluk ve hacme ulaştığı için",
             "otomatik sınıflandırma ile ilk yanıt süresi kısalabilir", "SLA başarısı ve müşteri memnuniyeti artabilir", "exploit", 60),
            ("Kur artışının lisans maliyetlerine etkisi", "financial", "Demo Teknoloji A.Ş.", "Finans ve Muhasebe", "threat", 4, 3, 3, 2,
             "ayse.yilmaz", "financial", "Lisans sözleşmeleri döviz cinsinden olduğu için", "kur artışı bütçeyi aşabilir",
             "kârlılık düşebilir ve yatırımlar ertelenebilir", "transfer", 25),
            ("Kişisel verilerin saklama süresinin aşılması", "privacy", "Demo Teknoloji A.Ş.", "Doküman Yönetimi", "threat", 3, 4, 2, 3,
             "okan.yildiz", "legal", "Kayıtlar için saklama ve imha takvimi uygulanmadığı için", "kişisel veriler gereğinden uzun tutulabilir",
             "idari para cezası ve itibar kaybı oluşabilir", "mitigate", -8),
            ("Ödeme işlemlerinde dolandırıcılık artışı", "operational", "Demo Ödeme Hizmetleri A.Ş.", "Ödeme İşlemleri", "threat", 4, 5, 2, 4,
             "ayse.yilmaz", "financial", "Yeni kanal açılışlarında dolandırıcılık kuralları güncellenmediği için",
             "sahte işlemler onaylanabilir", "doğrudan mali kayıp ve düzenleyici yaptırım oluşabilir", "mitigate", 20),
            ("Düzenleyici raporların gecikmesi", "compliance", "Demo Ödeme Hizmetleri A.Ş.", "Ödeme İşlemleri", "threat", 2, 4, 1, 4,
             "selin.aydin", "legal", "Raporlama manuel veri derlemeye dayandığı için", "rapor süresinde iletilemeyebilir",
             "idari yaptırım uygulanabilir", "mitigate", 35),
            ("Kart işlem sisteminde sözleşmesel RTO'nun aşılması", "continuity", "Demo Banka A.Ş.", "Hizmet Sürekliliği", "threat", 3, 5, 2, 4,
             "kerem.aksoy", "customer", "Felaket kurtarma ortamı ana ortamla eş kapasitede olmadığı için",
             "olağanüstü durumda hizmet 4 saatlik sözleşme hedefinde kurtarılamayabilir", "sözleşme cezası ve müşteri kaybı oluşabilir",
             "mitigate", 15),
            ("Poliçe sistemi veritabanı kapasite yetersizliği", "technology", "Örnek Sigorta A.Ş.", "Kapasite Yönetimi", "threat", 3, 3, 2, 3,
             "mehmet.kaya", "operational", "Yıl sonu yenileme döneminde işlem hacmi iki katına çıktığı için",
             "veritabanı yanıt süreleri uzayabilir", "müşteri işlemleri gecikebilir", "mitigate", 50),
            ("Mağaza sistemlerinde destek dışı işletim sistemi", "technology", "Kurgu Perakende A.Ş.", "Varlık Yönetimi", "threat", 4, 3, 2, 3,
             "mehmet.kaya", "information", "Müşteri yenileme bütçesini onaylamadığı için", "yamalanamayan açıklar istismar edilebilir",
             "mağaza satışları kesintiye uğrayabilir", "accept", 30),
            ("Tedarik zincirinde yazılım bileşeni bütünlüğünün bozulması", "security", "Demo Teknoloji A.Ş.", "Güvenli Yazılım Geliştirme",
             "threat", 2, 5, 1, 5, "deniz.koc", "information", "Açık kaynak bağımlılıkları imza ve köken doğrulamasından geçmediği için",
             "kötü amaçlı bir bileşen ürüne girebilir", "müşteri ortamlarında güvenlik ihlali oluşabilir", "mitigate", 45),
        ]
        self.ids["erm"] = {}
        for (title, category, company_name, process, kind, like, imp, tl, ti, owner, area, cause, event, consequence,
             strategy, review) in new:
            company_id = company.get(company_name) or tech
            if self._risk(title, company_id):
                continue
            risk_id = self.add("supplier_risks", {
                "title": title, "category": category, "company_id": company_id, "process_id": self._process(process),
                "risk_type": kind, "likelihood": like, "impact": imp, "target_likelihood": tl, "target_impact": ti,
                "owner": owner, "impact_area": area, "cause": cause, "risk_event": event, "consequence": consequence,
                "response_strategy": strategy, "entity_name": process, "review_date": day(review),
                "consulted": "Süreç sahibi, Risk Yönetimi, Hukuk ve Uyum", "description": TAG,
                "treatment": "İşleme faaliyetleri risk kaydında izlenir."}, created_days_ago=r.randint(70, 200))
            self.ids["erm"][title] = risk_id
            if title.startswith("Mağaza"):
                continue                               # değerlendirilmemiş risk (sağlık kontrolünde görünür)
            self._assess(risk_id, r.choice(["okan.yildiz", "selin.aydin"]), "Süreç sahibiyle atölye çalışması.",
                         r.choice([0.2, 0.4]), r.randint(5, 55))
            if kind == "threat":
                db.execute("UPDATE tdr_supplier_risks SET status='in_treatment' WHERE id=?", (risk_id,))
                self.add("risk_actions", {"risk_id": risk_id, "title": {
                    "people": "Bulut yetkinlik programı ve işe alım planı", "financial": "Kur riskine karşı TL fiyatlı sözleşme müzakeresi",
                    "privacy": "Saklama ve imha takviminin uygulanması", "compliance": "Düzenleyici raporların otomasyonu",
                    "continuity": "DR ortamı kapasitesinin artırılması ve yıllık geçiş testi",
                    "technology": "Kapasite artışı ve performans testleri", "security": "Bağımlılık imza doğrulaması (SBOM)"}.get(
                    category, "Dolandırıcılık kurallarının güncellenmesi"), "owner": owner, "due_date": day(r.choice([-6, 25, 60, 90])),
                    "priority": "high" if like * imp >= 15 else "medium", "status": r.choice(["open", "in_progress"]),
                    "description": TAG})
        # KRİ'ler
        machine_kri = []
        kris = [
            ("Kritik yaması 35 günü aşan üretim sunucusu", "Kritik yamada gecikme", "adet", "higher_worse", 3, 6, "okan.yildiz",
             [2, 2, 3, 4, 5, 4, 6, 7], True),
            ("Başarısız yedekleme işi oranı", "Yedekten geri dönüş", "%", "higher_worse", 2, 5, "mehmet.kaya",
             [0.8, 1.1, 1.4, 0.9, 2.3, 1.8, 1.2, 1.6], True),
            ("Onaysız üretim değişikliği", "Yetkisiz üretim değişikliği", "adet", "higher_worse", 1, 3, "mehmet.kaya",
             [0, 1, 0, 0, 2, 1, 0, 0], False),
            ("Veri merkezi kapasite kullanımı", "Veri merkezi kapasitesi", "%", "higher_worse", 75, 85, "mehmet.kaya",
             [68, 70, 71, 73, 74, 77, 79, 81], True),
            ("Dolandırıcılık işlem oranı (binde)", "Ödeme işlemlerinde dolandırıcılık artışı", "‰", "higher_worse", 0.8, 1.5,
             "ayse.yilmaz", [0.4, 0.5, 0.6, 0.6, 0.9, 1.1, 0.9, 0.7], True),
            ("Kilit pozisyonlarda yedeklilik oranı", "Bulut dönüşümünde yetkin personel eksikliği", "%", "lower_worse", 70, 50,
             "selin.aydin", [78, 76, 72, 69, 66, 64, 62, 61], False),
            ("DR kurtarma testinde gerçekleşen süre", "Kart işlem sisteminde sözleşmesel RTO'nun aşılması", "dakika", "higher_worse", 200, 240,
             "kerem.aksoy", [210, 230, 255, 290], False),
        ]
        for name, risk_title, unit, direction, amber, red, owner, values, from_mcp in kris:
            risk_id = self._risk(risk_title)
            if not risk_id or one(db, "SELECT id FROM tdr_kris WHERE name=?", (name,)):
                continue
            kri_id = self.add("kris", {"risk_id": risk_id, "name": name, "unit": unit, "direction": direction,
                                       "threshold_amber": amber, "threshold_red": red, "owner": owner,
                                       "frequency": "quarterly" if len(values) < 6 else "monthly",
                                       "description": ("Kaynak: ITSM/izleme sistemleri, MCP ile aylık iletilir. " if from_mcp else "")
                                       + TAG})
            step = 91 if len(values) < 6 else 30
            first = TODAY.replace(day=1) - timedelta(days=step * len(values))
            for k, value in enumerate(values):
                period = (first + timedelta(days=step * (k + 1))).replace(day=1)
                crud.insert(db, RESOURCES["kri_values"], {"kri_id": kri_id, "period": period.isoformat(), "value": value,
                                                          "note": None}, MACHINE if from_mcp else None)
            if from_mcp:
                machine_kri.append(kri_id)
        # kontrol hedefi ↔ risk eşlemeleri
        if self.enabled("grc"):
            for objective, titles in (
                    ("Varlıkların güvenli konfigürasyonu ve yamaları doğrulanmalı", ["Kritik yamada gecikme", "Destek süresi biten bileşen"]),
                    ("Kritik hizmetlerde geri dönüş ve kurtarma mümkün olmalı", ["Yedekten geri dönüş",
                                                                                 "Kart işlem sisteminde sözleşmesel RTO'nun aşılması"]),
                    ("Üretim değişiklikleri yetkilendirilip iz bırakmalı", ["Yetkisiz üretim değişikliği"]),
                    ("CI envanteri eksiksiz ve izlenebilir olmalı", ["Eksik hizmet bağımlılıkları"]),
                    ("Müşteri hizmet seviyeleri ölçülmeli ve sapmalar yönetilmeli", ["Veri merkezi kapasitesi",
                                                                                     "Poliçe sistemi veritabanı kapasite yetersizliği"]),
                    ("Tedarikçi yükümlülüklerinin yerine geldiği doğrulanmalı", ["Tek tedarikçiye bağımlılık", "Felaket kurtarma testinin yapılmaması"]),
                    ("Sipariş ve mali onay iş akışları kontrol edilebilmeli", ["Ödeme işlemlerinde dolandırıcılık artışı"])):
                objective_id = self._by("objectives", "name", objective)
                for title in titles:
                    for risk in rows(db, "SELECT id FROM tdr_supplier_risks WHERE title=? ORDER BY id LIMIT 3", (title,)):
                        if objective_id:
                            db.execute("INSERT INTO tdr_objective_risks (objective_id, risk_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                                       (objective_id, risk["id"]))
            # yeni riskleri kontrollere bağla
            for title, control in (("Ödeme işlemlerinde dolandırıcılık artışı", "Dynamics sipariş dönüşümlerinin onay adımları"),
                                   ("Kişisel verilerin saklama süresinin aşılması", "Merkezi log saklama ve kaynak kapsaması"),
                                   ("Kart işlem sisteminde sözleşmesel RTO'nun aşılması", "Kritik hizmetler için geri yükleme testi"),
                                   ("Tedarik zincirinde yazılım bileşeni bütünlüğünün bozulması", "Release geri dönüş planı ve dağıtım doğrulaması")):
                risk_id, control_id = self._risk(title), self._by("controls", "name", control)
                if risk_id and control_id:
                    db.execute("INSERT INTO tdr_control_risks (control_id, risk_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                               (control_id, risk_id))

    # -------------------------------------------------------------- dokümanlar (ISO 9001 7.5)
    def _file(self, doc_id, name, content, by, days_ago):
        digest = hashlib.sha256(content).hexdigest()
        file_id = self.db.execute("INSERT INTO tdr_document_files (document_id, file_name, file_size, mime_type, sha256, uploaded_by, "
                                  "uploaded_at) VALUES (?,?,?,?,?,?,?)",
                                  (doc_id, name, len(content), "application/pdf", digest, by, stamp(days_ago))).lastrowid
        self.db.execute("INSERT INTO tdr_document_blobs (file_id, content) VALUES (?,?)", (file_id, content))
        return file_id, digest

    def _publish(self, doc_id, history, months=12):
        """history: [(özet, hazırlayan, onaylayan, kaç gün önce)] — revizyonlar ve dosyaları sırayla yazılır."""
        db = self.db
        doc = one(db, "SELECT * FROM tdr_documents WHERE id=?", (doc_id,))
        start = doc["current_revision"] or 0
        for k, (summary, prepared, approved, ago) in enumerate(history, start=start + 1):
            name = "".join(ch if ch.isalnum() else "-" for ch in doc["title"].lower())[:50].strip("-") + f"-rev{k}.pdf"
            content = (f"%PDF-1.4\n% {TAG}: {doc['title']} — Rev. {k}\n% {summary}\n%%EOF\n").encode("utf-8")
            file_id, digest = self._file(doc_id, name, content, prepared, ago + 2)
            db.execute("INSERT INTO tdr_document_revisions (document_id, revision, change_summary, prepared_by, approved_by, approved_at, "
                       "effective_date, file_id, file_name, sha256) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (doc_id, k, summary, prepared, approved, stamp(ago), day(-ago), file_id, name, digest))
            last = (k, approved, ago)
        k, approved, ago = last
        db.execute("UPDATE tdr_documents SET status='published', current_revision=?, version=?, effective_date=?, approved_by=?, "
                   "approved_on=?, review_date=?, review_period_months=?, prepared_by=?, pending_change=NULL, draft_file_id=NULL "
                   "WHERE id=?", (k, f"Rev. {k}", day(-ago), approved, day(-ago), day(round(months * 30.44) - ago), months,
                                  history[-1][1], doc_id))

    def documents(self):
        db = self.db
        owners = {"Tedarikçi Yönetimi Politikası": ("Tedarikçi Yönetimi", "ayse.yilmaz", "selin.aydin"),
                  "Tedarikçi Bilgi Güvenliği Gereksinimleri Prosedürü": ("Bilgi Güvenliği", "okan.yildiz", "selin.aydin"),
                  "Değişiklik Yönetimi Prosedürü": ("Değişiklik Yönetimi", "mehmet.kaya", "selin.aydin"),
                  "Olay ve Problem Yönetimi Prosedürü": ("Olay Yönetimi", "zeynep.demir", "kerem.aksoy"),
                  "Tedarikçi Erişim Yönetimi Talimatı": ("Kimlik ve Erişim Yönetimi", "okan.yildiz", "selin.aydin"),
                  "Sözleşme Güvenlik ve Denetim Hakkı Maddeleri": ("Tedarikçi Yönetimi", "ayse.yilmaz", "selin.aydin"),
                  "Bulut Hizmeti Kullanım Rehberi": ("Bilgi Güvenliği", "mehmet.kaya", "okan.yildiz"),
                  "İş Sürekliliği ve Felaket Kurtarma Prosedürü": ("Hizmet Sürekliliği", "kerem.aksoy", "selin.aydin")}
        for title, (process, owner, approver) in owners.items():
            db.execute("UPDATE tdr_documents SET process_id=?, approver=?, owner=COALESCE(?, owner), org_unit_id=COALESCE(org_unit_id, "
                       "(SELECT org_unit_id FROM tdr_processes WHERE id=?)) WHERE title=?",
                       (self._process(process), approver, owner, self._process(process), title))
        # yürürlükteki dokümanlara dosyalı revizyon geçmişi
        for title, extra in (("Tedarikçi Yönetimi Politikası", [("Kritiklik seviyeleri ve gözden geçirme sıklığı eklendi", "ayse.yilmaz", "selin.aydin", 40)]),
                             ("Değişiklik Yönetimi Prosedürü", [("Acil değişiklik sonrası gözden geçirme adımı eklendi", "mehmet.kaya", "selin.aydin", 75)]),
                             ("İş Sürekliliği ve Felaket Kurtarma Prosedürü", [])):
            doc = one(db, "SELECT * FROM tdr_documents WHERE title=?", (title,))
            if doc and doc["status"] == "published" and extra:
                self._publish(doc["id"], extra)
        # yeni dokümanlar: taslak, onayda, yürürlükte, geçersiz, kayıt
        new = [
            ("Kurumsal Risk Yönetimi Politikası", "policy", "Kurumsal Risk Yönetimi", "okan.yildiz", "selin.aydin", "published",
             [("İlk yayın", "okan.yildiz", "selin.aydin", 300), ("ISO 31000 risk kriterleri ve iştah beyanı eklendi", "okan.yildiz", "selin.aydin", 35)], 12, None),
            ("Risk Değerlendirme Prosedürü", "procedure", "Kurumsal Risk Yönetimi", "okan.yildiz", "selin.aydin", "published",
             [("İlk yayın", "okan.yildiz", "selin.aydin", 380)], 12, None),
            ("İş Etki Analizi Talimatı", "instruction", "Hizmet Sürekliliği", "kerem.aksoy", "selin.aydin", "published",
             [("İlk yayın", "kerem.aksoy", "selin.aydin", 120)], 24, None),
            ("Doküman ve Kayıt Kontrolü Prosedürü", "procedure", "Doküman Yönetimi", "ayse.yilmaz", "selin.aydin", "published",
             [("İlk yayın", "ayse.yilmaz", "selin.aydin", 410)], 12, None),
            ("Yama Yönetimi Prosedürü", "procedure", "Zafiyet Yönetimi", "okan.yildiz", "selin.aydin", "in_review",
             [("İlk yayın", "okan.yildiz", "selin.aydin", 330)], 12, "Kritik yamalar için 30 gün hedefi ve istisna onayı eklendi"),
            ("Kriz İletişim Planı Şablonu", "form", "Hizmet Sürekliliği", "kerem.aksoy", "selin.aydin", "draft", [], 12, None),
            ("Erişim Gözden Geçirme Formu", "form", "Kimlik ve Erişim Yönetimi", "okan.yildiz", "selin.aydin", "published",
             [("İlk yayın", "okan.yildiz", "selin.aydin", 200)], 24, None),
            ("Eski Yedekleme Talimatı", "instruction", "Hizmet Sürekliliği", "mehmet.kaya", "selin.aydin", "obsolete",
             [("İlk yayın", "mehmet.kaya", "selin.aydin", 900)], 12, None),
            ("Tatbikat Kayıtları", "record", "Hizmet Sürekliliği", "kerem.aksoy", "selin.aydin", "published",
             [("Kayıt sınıfı tanımlandı", "kerem.aksoy", "selin.aydin", 150)], 12, None),
        ]
        for title, category, process, owner, approver, status, history, months, pending in new:
            if one(db, "SELECT id FROM tdr_documents WHERE title=?", (title,)):
                continue
            doc_id = self.add("documents", {
                "title": title, "category": category, "process_id": self._process(process), "owner": owner, "approver": approver,
                "review_period_months": months, "confidentiality": "confidential" if category == "record" else "internal",
                "retention_years": 10 if category == "record" else None, "description": TAG}, created_days_ago=(history[0][3] + 10) if history else 12)
            if history:
                self._publish(doc_id, history, months)
            if status == "in_review":
                file_id, _ = self._file(doc_id, "yama-yonetimi-proseduru-taslak.pdf",
                                        f"%PDF-1.4\n% {TAG}: {title} taslak\n%%EOF\n".encode(), owner, 3)
                db.execute("UPDATE tdr_documents SET status='in_review', pending_change=?, draft_file_id=?, prepared_by=? WHERE id=?",
                           (pending, file_id, owner, doc_id))
            elif status == "draft":
                db.execute("UPDATE tdr_documents SET prepared_by=? WHERE id=?", (owner, doc_id))
            elif status == "obsolete":
                db.execute("UPDATE tdr_documents SET status='obsolete' WHERE id=?", (doc_id,))
        # dokümanın karşıladığı standart maddeleri
        if self.enabled("grc"):
            for title, clauses in (("Tedarikçi Yönetimi Politikası", ["5.19", "5.20", "5.22"]),
                                   ("Tedarikçi Bilgi Güvenliği Gereksinimleri Prosedürü", ["5.19", "5.20", "5.21"]),
                                   ("Değişiklik Yönetimi Prosedürü", ["8.5"]), ("Doküman ve Kayıt Kontrolü Prosedürü", ["7.5"]),
                                   ("İş Sürekliliği ve Felaket Kurtarma Prosedürü", ["8.7", "5.30"])):
                doc_id = self._by("documents", "title", title)
                for code in clauses:
                    for clause in rows(db, "SELECT id FROM tdr_clauses WHERE code=? ORDER BY id LIMIT 2", (code,)):
                        if doc_id:
                            db.execute("INSERT INTO tdr_document_clauses (document_id, clause_id) VALUES (?,?) ON CONFLICT DO NOTHING",
                                       (doc_id, clause["id"]))

    # -------------------------------------------------------------- CMDB (K-019)
    def cmdb(self):
        from .modules import cmdb as C
        db, r = self.db, self.rnd
        counts = {"created": 0, "updated": 0, "unchanged": 0, "stale": 0, "relations": 0, "requests": 0}
        lookup = C._company_lookup(db)
        started, now = utcnow(), utcnow()
        sys_ids = {}
        for name, klass, company, criticality, env, extra in CI_SEED:
            sys_id = "%032x" % r.getrandbits(128)
            sys_ids[name] = sys_id
            item = {"name": name, "ci_class": klass, "environment": env, "business_criticality": criticality,
                    "operational_status": "operational", "owner": extra.get("owner"), "os": extra.get("os"),
                    "os_version": extra.get("os_version"), "vendor": extra.get("vendor"), "version": extra.get("version"),
                    "support_group": {"server": "Sunucu Operasyon", "database": "Veritabanı Yönetimi"}.get(klass, "Uygulama Destek"),
                    "sn_class": {"business_app": "cmdb_ci_business_app", "application": "cmdb_ci_appl", "server": "cmdb_ci_server",
                                 "database": "cmdb_ci_db_instance"}[klass],
                    "location": "İstanbul VM-1" if env != "dr" else "Ankara VM-2"}
            if "os_eos_date" in extra:
                item["os_eos_date"] = day(extra["os_eos_date"])
            if "eos_date" in extra:
                item["eos_date"] = day(extra["eos_date"])
            if "patch" in extra:
                item["last_patch_date"] = day(-extra["patch"])
                item["missing_critical_patches"] = extra.get("missing", 0)
            if "boot" in extra:
                item["last_boot_at"] = stamp(extra["boot"], 3)
            if klass == "server":
                item["fqdn"] = f"{name}.demo.ornek.test"
                item["ip_address"] = f"10.{20 + r.randint(0, 9)}.{r.randint(1, 250)}.{r.randint(2, 250)}"
            company_id = lookup.get(company.lower()) if company else None
            C.upsert_ci(db, sys_id, item, "mcp", company_id, now, counts)
        for parent, child in CI_RELATIONS:
            C._relation(db, sys_ids[parent], sys_ids[child], "Depends on::Used by", "%032x" % r.getrandbits(128), now)
            counts["relations"] += 1
        db.execute("UPDATE tdr_cmdb_cis SET description=? WHERE source='mcp' AND description IS NULL", (TAG,))
        # tedarikçi bağlantıları (yerel alan): veritabanı lisansı ve sunucu bakım hizmetleri
        db_supplier, _ = self._supplier_for("Veritabanı lisansı ve destek")
        hw_supplier, _ = self._supplier_for("Sunucu ve depolama bakım")
        if db_supplier:
            db.execute("UPDATE tdr_cmdb_cis SET supplier_id=? WHERE ci_class='database'", (db_supplier,))
        if hw_supplier:
            db.execute("UPDATE tdr_cmdb_cis SET supplier_id=? WHERE ci_class='server' AND source='mcp'", (hw_supplier,))
        C._record_run(db, started, "success", "push", "mcp", "mcp", counts, [], None)
        from .demo import SYSTEM
        C.evaluate_rules(db, SYSTEM)
        # CMDB kuralının açtığı risklere süreç, değerlendirme ve faaliyet
        for risk in rows(db, "SELECT * FROM tdr_supplier_risks WHERE origin_ref LIKE 'cmdb:%' ORDER BY id"):
            rule = risk["origin_ref"].split(":")[1]
            process = {"patch": "Zafiyet Yönetimi", "uptime": "Zafiyet Yönetimi"}.get(rule, "Varlık Yönetimi")
            db.execute("UPDATE tdr_supplier_risks SET process_id=?, org_unit_id=?, target_likelihood=?, target_impact=?, "
                       "owner=?, consulted=? WHERE id=?",
                       (self._process(process), self._unit("Bilgi Güvenliği"), 2, max(1, risk["impact"] - 1), "okan.yildiz",
                        "Sunucu Operasyon, Uygulama sahipleri", risk["id"]))
            if r.random() < 0.7:
                self._assess(risk["id"], "okan.yildiz", "CMDB kuralı sonrası etki analizi; telafi edici kontroller dikkate alındı.",
                             r.choice([0.2, 0.4]), r.randint(2, 20))
                db.execute("UPDATE tdr_supplier_risks SET status='in_treatment', response_strategy='mitigate' WHERE id=?", (risk["id"],))
                self.add("risk_actions", {"risk_id": risk["id"], "owner": "mehmet.kaya", "priority": "high",
                                          "title": {"os_eos": "Destek dışı işletim sistemlerinin yükseltme planı",
                                                    "app_eos": "Ürün sürüm yükseltmesi veya genişletilmiş destek alımı",
                                                    "patch": "Kritik yamaların bakım penceresinde uygulanması",
                                                    "uptime": "Planlı yeniden başlatma takvimi"}[rule],
                                          "due_date": day(r.choice([-4, 21, 45])), "status": "open", "description": TAG})
        # elle bağlanan CI'lar
        for title, names in (("Yedekten geri dönüş", ["Yedekleme Yönetimi", "srv-bkp01", "srv-dr-itsm01"]),
                             ("Kart işlem sisteminde sözleşmesel RTO'nun aşılması", ["Kart İşlem Sistemi (yönetilen hizmet)", "srv-db-kart01"]),
                             ("Poliçe sistemi veritabanı kapasite yetersizliği", ["Poliçe Oracle Veritabanı"]),
                             ("Ödeme işlemlerinde dolandırıcılık artışı", ["Dolandırıcılık İzleme"]),
                             ("Mağaza sistemlerinde destek dışı işletim sistemi", ["srv-kp-pos01"])):
            risk_id = self._risk(title)
            for name in names:
                ci = self._by("cmdb_cis", "name", name)
                if risk_id and ci:
                    db.execute("INSERT INTO tdr_risk_cis (risk_id, ci_id, link_source) VALUES (?,?,'manual') ON CONFLICT DO NOTHING",
                               (risk_id, ci))

    # -------------------------------------------------------------- iş sürekliliği (ISO 22301)
    def continuity(self):
        from .modules import continuity as B
        db, r = self.db, self.rnd
        windows = list(B.WINDOWS)
        bia_ids = {}
        for (title, process, company, unit, owner, mtpd, shift, rto, rpo, status, apps, services) in BIAS:
            k = windows.index(mtpd)
            bia_id = self.add("bias", {
                "title": title + " BİA", "process_id": self._process(process), "company_id": self._company(company),
                "org_unit_id": self._unit(unit), "owner": owner, "rto_hours": rto, "rpo_hours": rpo,
                "description": TAG, "peak_periods": "Ay sonu ve yıl sonu kapanış dönemleri", "min_staff": r.randint(2, 8),
                "locations": "İstanbul merkez ofis; alternatif: Ankara ofis ve uzaktan çalışma",
                "vital_records": "Süreç prosedürleri, müşteri sözleşmeleri, sistem yapılandırma kayıtları",
                "workaround": "Kritik işlemler için elle kayıt formu ve telefonla bildirim",
                "mbco": "Kritik müşterilere asgari hizmet; diğer talepler sıraya alınır",
                "review_date": day(r.choice([90, 180, 240]) if status == "approved" else 30)}, created_days_ago=r.randint(60, 200))
            bia_ids[title] = bia_id
            for category in B.IMPACT_CATEGORIES:
                s = shift.get(category, 2)
                for i, window in enumerate(windows):
                    level = min(5, max(1, i - k + 4 - s))
                    db.execute("INSERT INTO tdr_bia_impacts (bia_id, category, time_window, level, note) VALUES (?,?,?,?,?)",
                               (bia_id, category, window, level, None))
            mtpd_hours, criticality = B.derive(db, bia_id)
            db.execute("UPDATE tdr_bias SET mtpd_hours=?, criticality=?, prepared_by=? WHERE id=?", (mtpd_hours, criticality, owner, bia_id))
            if status == "approved":
                db.execute("UPDATE tdr_bias SET status='approved', approved_by='selin.aydin', approved_at=? WHERE id=?",
                           (stamp(r.randint(20, 50)), bia_id))
            elif status == "in_review":
                db.execute("UPDATE tdr_bias SET status='in_review' WHERE id=?", (bia_id,))
            for name in apps:
                ci = self._by("cmdb_cis", "name", name)
                if ci:
                    db.execute("INSERT INTO tdr_bia_applications (bia_id, ci_id, required_rto_hours, note) VALUES (?,?,?,?) "
                               "ON CONFLICT DO NOTHING", (bia_id, ci, rto, "Süreç bu uygulama olmadan yürütülemez"))
            for service in services:
                supplier, engagement = self._supplier_for(service)
                if supplier:
                    db.execute("INSERT INTO tdr_bia_suppliers (bia_id, supplier_id, engagement_id, note) VALUES (?,?,?,?) "
                               "ON CONFLICT DO NOTHING", (bia_id, supplier, engagement, service))
        for title, risks in (("Ödeme işlemleri", ["Ödeme işlemlerinde dolandırıcılık artışı", "Düzenleyici raporların gecikmesi"]),
                             ("Olay yönetimi ve servis masası", ["Yedekten geri dönüş"]),
                             ("Güvenlik operasyon merkezi izleme", ["Kritik yamada gecikme"])):
            for title_r in risks:
                risk_id = self._risk(title_r)
                if risk_id and bia_ids.get(title):
                    db.execute("INSERT INTO tdr_bia_risks (bia_id, risk_id) VALUES (?,?) ON CONFLICT DO NOTHING", (bia_ids[title], risk_id))
        # planlar
        doc = self._by("documents", "title", "İş Sürekliliği ve Felaket Kurtarma Prosedürü")
        tech, pay = self._company("Demo Teknoloji A.Ş."), self._company("Demo Ödeme Hizmetleri A.Ş.")
        plans = [
            ("Kurumsal İş Sürekliliği Planı", "bcp", tech, "kerem.aksoy", "approved", "2.1", 160,
             ["Olay yönetimi ve servis masası", "Değişiklik ve sürüm yönetimi", "Güvenlik operasyon merkezi izleme", "Hizmet seviyesi yönetimi"],
             ["ITSM Platformu", "Kimlik Yönetimi (IAM)", "Çağrı Merkezi Uygulaması"]),
            ("Veri Merkezi Felaket Kurtarma Planı", "drp", tech, "mehmet.kaya", "approved", "3.0", -12,
             ["Olay yönetimi ve servis masası"], ["Kimlik Yönetimi (IAM)", "ITSM Platformu", "Müşteri Portalı", "Yedekleme Yönetimi"]),
            ("Ödeme Hizmetleri Süreklilik Planı", "bcp", pay, "ayse.yilmaz", "approved", "1.2", 200,
             ["Ödeme işlemleri"], ["Ödeme Ağ Geçidi", "Dolandırıcılık İzleme"]),
            ("Kriz İletişim Planı", "communication", tech, "kerem.aksoy", "draft", "0.9", 60, [], []),
        ]
        steps = {
            "activation": [("Olayın değerlendirilmesi ve kriz ekibinin çağrılması", "Kriz yöneticisi", 15),
                           ("Planın devreye alınma kararı", "Kriz yöneticisi", 30)],
            "response": [("Paydaşlara ilk bildirim (müşteriler, düzenleyici, çalışanlar)", "Kurumsal iletişim", 60),
                         ("Alternatif çalışma yerine ve uzaktan çalışmaya geçiş", "Operasyon", 120)],
            "recovery": [("Kritik uygulamaların kurtarma sırasına göre ayağa kaldırılması", "BT Altyapı", 180),
                         ("Veri bütünlüğü ve işlem mutabakatı kontrolü", "Uygulama sahipleri", 240)],
            "resumption": [("Normal operasyona dönüş ve geri geçiş", "Operasyon", 480),
                           ("Olay sonrası değerlendirme ve plan güncellemesi", "Süreklilik yöneticisi", 2880)]}
        plan_ids = {}
        for title, kind, company, owner, status, version, review, bias, apps in plans:
            plan_id = self.add("bc_plans", {
                "title": title, "plan_type": kind, "company_id": company, "owner": owner, "version": version,
                "scope": "Kapsamdaki BİA'larda kritik bulunan süreçler ve bağımlı uygulamalar",
                "activation_criteria": "Kritik hizmetin MTPD'nin yarısını aşacak kesinti beklentisi veya ana yerleşkenin kullanılamaması",
                "strategy": "Ankara ikincil veri merkezine geçiş; personel için uzaktan çalışma ve alternatif ofis",
                "team": "Kriz yöneticisi, BT altyapı, operasyon, kurumsal iletişim, hukuk",
                "communication": "Çağrı ağacı, kriz iletişim kanalı, müşteri bilgilendirme şablonları. " + TAG,
                "document_id": doc if kind in ("bcp", "drp") else None, "review_date": day(review)},
                created_days_ago=r.randint(200, 400))
            plan_ids[title] = plan_id
            for bia in bias:
                if bia_ids.get(bia):
                    db.execute("INSERT INTO tdr_bc_plan_bias (plan_id, bia_id) VALUES (?,?) ON CONFLICT DO NOTHING", (plan_id, bia_ids[bia]))
            for order, name in enumerate(apps, start=1):
                ci = self._by("cmdb_cis", "name", name)
                if ci:
                    self.add("bc_plan_applications", {"plan_id": plan_id, "ci_id": ci, "recovery_order": order,
                                                      "target_rto_hours": [1, 2, 4, 8][min(order - 1, 3)]})
            position = 0
            for phase, items in steps.items():
                for action, responsible, minutes in items:
                    position += 1
                    self.add("bc_plan_steps", {"plan_id": plan_id, "phase": phase, "position": position, "action": action,
                                               "responsible": responsible, "target_minutes": minutes})
            if status == "approved":
                db.execute("UPDATE tdr_bc_plans SET status='approved', prepared_by=?, approved_by='selin.aydin', approved_at=? WHERE id=?",
                           (owner, stamp(r.randint(30, 120)), plan_id))
            else:
                db.execute("UPDATE tdr_bc_plans SET prepared_by=? WHERE id=?", (owner, plan_id))
        # tatbikatlar
        auditor = "can.ozturk"
        exercises = [
            ("İkincil veri merkezine geçiş tatbikatı", "functional", "Veri Merkezi Felaket Kurtarma Planı", -75, "completed",
             240, 290, "partially_successful", "Kimlik yönetimi sunucusunun DR kopyası güncel değildi; geçiş 50 dakika gecikti. "
             "Çağrı ağacında iki numara güncel değildi.",
             [("DR ortamında IAM yapılandırması güncel değil", "high"), ("Çağrı ağacı iletişim bilgileri güncel değil", "medium")]),
            ("Fidye yazılımı masa başı tatbikatı", "tabletop", "Kurumsal İş Sürekliliği Planı", -160, "completed", None, None,
             "successful", "Karar noktaları netti; hukuk biriminin bildirim süreleri plana eklendi.", []),
            ("Ödeme ağ geçidi yedek siteye geçiş simülasyonu", "simulation", "Ödeme Hizmetleri Süreklilik Planı", 24, "planned",
             None, None, None, None, []),
            ("Çağrı ağacı testi", "call_tree", "Kriz İletişim Planı", 9, "planned", None, None, None, None, []),
            ("Yıllık tam ölçekli süreklilik tatbikatı", "full_scale", "Kurumsal İş Sürekliliği Planı", 118, "planned",
             None, None, None, None, []),
        ]
        for title, kind, plan, offset, status, target, achieved, outcome, lessons, findings in exercises:
            data = {"title": title, "exercise_type": kind, "plan_id": plan_ids[plan], "planned_date": day(offset),
                    "scenario": {"functional": "Birincil veri merkezinde enerji kesintisi; kritik uygulamalar ikincil merkeze taşınır.",
                                 "tabletop": "Fidye yazılımı dosya sunucularını şifreledi; yedeklerin bütünlüğü belirsiz.",
                                 "simulation": "Ödeme ağ geçidi birincil sitede yanıt vermiyor; trafik yedek siteye yönlendirilir.",
                                 "call_tree": "Mesai dışı kriz bildirimi; ekibe 30 dakika içinde ulaşılmalı.",
                                 "full_scale": "Ana yerleşke 3 gün kullanılamıyor; tüm kritik süreçler alternatif yerden yürütülür."}[kind],
                    "objectives": "RTO hedeflerinin doğrulanması, ekip rollerinin ve iletişimin sınanması",
                    "facilitator": "Kerem Aksoy", "participants": "BT Altyapı, Operasyon, Bilgi Güvenliği, Kurumsal İletişim",
                    "target_recovery_minutes": target}
            if status == "completed":
                data.update({"status": "completed", "actual_date": day(offset), "achieved_recovery_minutes": achieved,
                             "outcome": outcome, "lessons_learned": lessons, "report": TAG})
            exercise_id = self.add("bc_exercises", data, created_days_ago=max(1, -offset + 30) if offset < 0 else 20)
            for text, severity in findings:
                finding_id = self.add("findings", {"title": text, "source": "exercise", "severity": severity, "status": "open",
                                                   "owner": "mehmet.kaya", "due_date": day(r.choice([-10, 20, 40])),
                                                   "process_id": self._process("Hizmet Sürekliliği"), "company_id": tech,
                                                   "description": f"{title} sırasında tespit edildi. {TAG}"}, created_days_ago=-offset)
                db.execute("UPDATE tdr_findings SET created_by=? WHERE id=?", (auditor, finding_id))
                db.execute("INSERT INTO tdr_bc_exercise_findings (exercise_id, finding_id) VALUES (?,?)", (exercise_id, finding_id))

    # -------------------------------------------------------------- son düzeltmeler
    def finalize_risks(self):
        """Doğrudan yazılan değerlendirmelerden sonra özet puanlar (artık puan, seviye) güncellenir."""
        from .modules import risks as R
        db = self.db
        for risk in rows(db, """SELECT r.id, r.likelihood, r.impact, (SELECT a.residual FROM tdr_risk_assessments a WHERE a.risk_id=r.id
                ORDER BY a.assessed_at DESC, a.id DESC LIMIT 1) AS residual, (SELECT a.assessed_at FROM tdr_risk_assessments a
                WHERE a.risk_id=r.id ORDER BY a.assessed_at DESC, a.id DESC LIMIT 1) AS assessed FROM tdr_supplier_risks r"""):
            residual = float(risk["residual"]) if risk["residual"] is not None else None
            score = residual if residual is not None else risk["likelihood"] * risk["impact"]
            db.execute("UPDATE tdr_supplier_risks SET inherent_score=?, residual_score=?, last_assessed_at=?, risk_level=? WHERE id=?",
                       (risk["likelihood"] * risk["impact"], residual, risk["assessed"], R.level_of(db, score), risk["id"]))
        db.execute("""UPDATE tdr_supplier_risks SET source=CASE WHEN origin_ref LIKE 'survey:%' THEN 'survey'
            WHEN origin_ref LIKE 'cmdb:%' THEN 'cmdb_rule' WHEN supplier_id IS NOT NULL THEN 'supplier' ELSE 'manual' END""")


SECTIONS = (("companies", "core"), ("architecture", "core"), ("erm", "risks"), ("documents", "documents"),
            ("cmdb", "cmdb"), ("continuity", "continuity"), ("audit_scope", "grc"), ("audit_archive", "grc"))
