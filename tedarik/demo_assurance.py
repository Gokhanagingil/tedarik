"""Demo verisinin standart kütüphanesi, güvence, uyum, olay ve entegrasyon bölümleri (K-023 ve sonrası).

demo_platform.py ile aynı ilkeler: her bölüm boş veritabanında ve önceki sürümle yüklenmiş demoda çalışır, kayıtları
adla veya kodla bulur, bir kez yüklenir. Tüm veriler sentetiktir. Çapraz eşlemeler örnektir; kurumun lisanslı eşleme
tablolarıyla değiştirilmesi beklenir (gerekçe alanında belirtilir).
"""
from datetime import date

from .auth import Principal
from .db import one, rows, utcnow

DEMO_LINK = "Demo eşlemesi (örnek): kurumunuzun lisanslı eşleme tablosuyla doğrulayın."
DEMO_LICENSE = "Demo verisi: yalnızca madde numarası ve kısa Türkçe başlık; standardın tam metni değildir."

# (standart, madde) ↔ (standart, madde), ilişki — sentetik örnek çapraz eşlemeler
CROSSWALK = [
    (("ISO/IEC 27001", "A.5.19"), ("NIST CSF", "GV.SC-01"), "intersects"),
    (("ISO/IEC 27001", "A.5.19"), ("NIST CSF", "GV.SC-06"), "intersects"),
    (("ISO/IEC 27001", "A.5.20"), ("NIST CSF", "GV.SC-05"), "equivalent"),
    (("ISO/IEC 27001", "A.5.21"), ("NIST CSF", "GV.SC-09"), "intersects"),
    (("ISO/IEC 27001", "A.5.22"), ("NIST CSF", "GV.SC-07"), "intersects"),
    (("ISO/IEC 27001", "A.5.31"), ("NIST CSF", "GV.OC-03"), "equivalent"),
    (("ISO/IEC 27001", "A.5.30"), ("NIST CSF", "ID.IM-04"), "intersects"),
    (("ISO/IEC 27001", "A.5.19"), ("NIST SP 800-53", "SR-1"), "intersects"),
    (("ISO/IEC 27001", "A.5.21"), ("NIST SP 800-53", "SR-3"), "intersects"),
    (("ISO/IEC 27001", "A.5.22"), ("NIST SP 800-53", "SR-6"), "intersects"),
    (("ISO/IEC 27001", "A.5.23"), ("NIST SP 800-53", "SA-9"), "intersects"),
    (("ISO/IEC 27001", "A.5.30"), ("NIST SP 800-53", "CP-2"), "intersects"),
    (("ISO/IEC 27001", "A.5.34"), ("NIST SP 800-53", "PT-1"), "intersects"),
    (("ISO/IEC 27001", "A.8.30"), ("NIST SP 800-53", "SA-4"), "intersects"),
    (("ISO/IEC 27001", "A.5.22"), ("ISO/IEC 20000-1", "8.3.4"), "subset"),
    (("ISO/IEC 27001", "A.5.19"), ("ISO/IEC 20000-1", "8.3.4"), "intersects"),
    (("ISO/IEC 27001", "A.5.30"), ("ISO/IEC 20000-1", "8.7.2"), "intersects"),
    (("ISO/IEC 20000-1", "8.6.1"), ("NIST CSF", "RS.MA-01"), "intersects"),
    (("ISO/IEC 20000-1", "8.2.5"), ("NIST CSF", "ID.AM-01"), "intersects"),
    (("ISO/IEC 20000-1", "8.5.1"), ("NIST SP 800-53", "CM-3"), "intersects"),
    (("CIS Controls", "1.1"), ("NIST SP 800-53", "CM-8"), "intersects"),
    (("CIS Controls", "1.1"), ("ISO/IEC 20000-1", "8.2.5"), "intersects"),
    (("CIS Controls", "4.1"), ("ISO/IEC 20000-1", "8.2.6"), "intersects"),
    (("CIS Controls", "4.3"), ("NIST SP 800-53", "AC-11"), "equivalent"),
    (("CIS Controls", "5.1"), ("NIST SP 800-53", "AC-2"), "intersects"),
    (("CIS Controls", "6.5"), ("NIST SP 800-53", "IA-2(1)"), "equivalent"),
    (("CIS Controls", "7.1"), ("NIST SP 800-53", "RA-5"), "intersects"),
    (("CIS Controls", "11.2"), ("NIST SP 800-53", "CP-9"), "intersects"),
    (("CIS Controls", "11.5"), ("NIST SP 800-53", "CP-9(1)"), "equivalent"),
    (("CIS Controls", "11.1"), ("ISO/IEC 20000-1", "8.7.2"), "intersects"),
    (("CIS Controls", "14.1"), ("NIST SP 800-53", "AT-2"), "intersects"),
    (("CIS Controls", "15.1"), ("ISO/IEC 27001", "A.5.19"), "intersects"),
    (("CIS Controls", "15.2"), ("ISO/IEC 27001", "A.5.19"), "intersects"),
    (("CIS Controls", "17.1"), ("ISO/IEC 20000-1", "8.6.1"), "intersects"),
    (("CIS Controls", "17.1"), ("NIST SP 800-53", "IR-8"), "intersects"),
    (("CIS Controls", "18.2"), ("NIST SP 800-53", "CA-8"), "intersects"),
]


class AssuranceSections:
    """Seeder'a karışan bölümler (demo.py). self.db, self.add ve demo_platform yardımcıları kullanılır."""

    def _clause(self, standard, code):
        row = one(self.db, """SELECT cl.id FROM tdr_clauses cl JOIN tdr_standards s ON s.id=cl.standard_id
            WHERE s.code=? AND cl.code=? ORDER BY s.id DESC LIMIT 1""", (standard, code))
        return row["id"] if row else None

    def standards(self):
        """NIST kütüphanesi (başvuru), demo standartlarının lisans notu, örnek çapraz eşlemeler, entegre denetim."""
        from .demo_platform import TAG, day, stamp
        from .modules import grc_library as L
        db = self.db
        admin = Principal("selin.aydin", "ADMIN", "system", "Selin Aydın")
        for _name, package in L.packages():
            L.install_package(db, package, admin, library_key=package.get("key"))
        db.execute("UPDATE tdr_standards SET license=? WHERE library_key IS NULL AND license IS NULL", (DEMO_LICENSE,))
        now = utcnow()
        for (sa, ca), (sb, cb), relation in CROSSWALK:
            a, b = self._clause(sa, ca), self._clause(sb, cb)
            if a and b and not L.find_link(db, a, b):
                db.execute("INSERT INTO tdr_clause_links (from_clause_id, to_clause_id, relation, source, rationale, active, "
                           "created_by, created_at) VALUES (?,?,?,?,?,1,?,?)", (a, b, relation, "crosswalk", DEMO_LINK,
                                                                               "selin.aydin", now))
        # entegre denetim: tedarikçi yönetimi, ISO/IEC 27001 + ISO/IEC 20000-1 + CIS 15 (tek test, çok standart)
        scope = [("ISO/IEC 27001", c) for c in ("A.5.19", "A.5.20", "A.5.21", "A.5.22", "A.5.23", "A.5.31")] + \
                [("ISO/IEC 20000-1", c) for c in ("8.3.3", "8.3.4", "8.7.2")] + [("CIS Controls", c) for c in ("15.1", "15.2")]
        ids = [cid for cid in (self._clause(s, c) for s, c in scope) if cid]
        if not ids or one(db, "SELECT id FROM tdr_audits WHERE name LIKE ?", ("Entegre tedarikçi yönetimi denetimi%",)):
            return
        from . import crud
        from .schema import RESOURCES
        audit_id = crud.insert(db, RESOURCES["audits"], {
            "name": "Entegre tedarikçi yönetimi denetimi — ISO/IEC 27001, ISO/IEC 20000-1, CIS 15",
            "kind": "internal", "audit_objective": "Üç standardın tedarikçi gereksinimlerini tek denetimde, ortak kontrollerle "
                                                    "ve tek kanıt setiyle değerlendirmek.",
            "scope": "Tedarikçi yaşam döngüsü: seçim, sözleşme, izleme, süreklilik. " + TAG,
            "planned_start": day(12), "planned_end": day(26), "lead_auditor": "Can Öztürk", "auditors": "Can Öztürk, Deniz Aksu",
            "auditees": "Satın Alma, Bilgi Güvenliği, Operasyon"})
        db.execute("UPDATE tdr_audits SET created_at=? WHERE id=?", (stamp(3), audit_id))
        standards = {r["standard_id"] for r in rows(db, f"SELECT standard_id FROM tdr_clauses WHERE id IN "
                                                         f"({','.join('?' * len(ids))})", ids)}
        for sid in sorted(standards):
            db.execute("INSERT INTO tdr_audit_standards (audit_id, standard_id) VALUES (?,?)", (audit_id, sid))
        for cid in ids:
            db.execute("INSERT INTO tdr_audit_clauses (audit_id, clause_id) VALUES (?,?)", (audit_id, cid))
        db.execute("""INSERT INTO tdr_audit_processes (audit_id, process_id) SELECT DISTINCT ?, cp.process_id
            FROM tdr_control_clauses cc JOIN tdr_control_processes cp ON cp.control_id=cc.control_id
            WHERE cc.clause_id IN (""" + ",".join("?" * len(ids)) + ") ON CONFLICT DO NOTHING", (audit_id, *ids))


    # -------------------------------------------------------------- güvence ve uyum (K-026)
    def assurance(self):
        """Kanıt talepleri, çalışma kâğıtları, yönetim yanıtları, denetim evreni ve planları, sertifikalar."""
        from . import crud
        from .demo_platform import TAG, day, stamp
        from .modules import assurance as A, grc as G
        from .schema import RESOURCES
        db = self.db
        auditor = Principal("can.ozturk", "AUDITOR", "system", "Can Öztürk")
        admin = Principal("selin.aydin", "ADMIN", "system", "Selin Aydın")
        audit_row = one(db, "SELECT * FROM tdr_audits WHERE status='in_progress' ORDER BY id LIMIT 1")
        if audit_row:
            plan = G.planned_controls(db, audit_row["id"])
            controls = list(dict.fromkeys(p["control_id"] for p in plan))[:6]
            people = ["okan.yildiz", "kerem.aksoy", "zeynep.demir", "mehmet.kaya", "okan.yildiz", "kerem.aksoy"]
            states = ["accepted", "submitted", "rejected", "requested", "requested", "accepted"]
            for i, (cid, who, state) in enumerate(zip(controls, people, states)):
                k = crud.get(db, RESOURCES["controls"], cid)
                rid = crud.insert(db, A.REQUESTS, {"title": f"Kanıt: {k['name']}"[:300],
                                                   "description": A._request_text(db, k, audit_row["id"]),
                                                   "audit_id": audit_row["id"], "control_id": cid, "assignee": who,
                                                   "due_date": day(-3 if state == "requested" and i == 3 else 7 + i)}, auditor)
                if state == "requested":
                    continue
                evidence_id = crud.insert(db, RESOURCES["evidence"], {
                    "title": f"{k['name']} — dönem kayıtları", "description": TAG, "created_by": who,
                    "period_start": day(-120), "period_end": day(-5)}, None)
                G.store_file(db, evidence_id, f"kanit-{k['code'].lower()}.txt",
                             f"Sentetik kanit: {k['code']} {TAG}\n".encode("utf-8"), who)
                G._evidence_links(db, evidence_id, {"controls": [cid], "audits": [audit_row["id"]]}, replace=False)
                db.execute("UPDATE tdr_evidence_requests SET status=?, evidence_id=?, response_note=?, submitted_at=?, "
                           "reviewed_by=?, reviewed_at=?, review_note=? WHERE id=?",
                           (state, evidence_id, "Dönem kayıtları ektedir.", stamp(2),
                            None if state == "submitted" else "can.ozturk", None if state == "submitted" else stamp(1),
                            "Ağustos ayı kayıtları eksik; tam dönemi ekleyin." if state == "rejected" else None, rid))
            for title, state, result in (("Değişiklik onay örneklemesi", "reviewed", "pass"),
                                         ("Olay eskalasyon süreleri", "ready", "fail"),
                                         ("Kapasite planı gözden geçirmesi", "draft", None)):
                wid = crud.insert(db, A.WORKPAPERS, {
                    "audit_id": audit_row["id"], "control_id": controls[0] if controls else None, "title": title,
                    "objective": "Kontrolün tasarım ve işleyiş etkinliğini doğrulamak.",
                    "procedure": "1. Dönem kayıtlarından rastgele 25 örnek seçildi.\n2. Her örnekte onay ve zaman damgası incelendi.\n"
                                 "3. Sapmalar sahibiyle görüşülerek doğrulandı.",
                    "sample": "Son çeyrek kayıtları", "sample_size": 25, "exceptions_found": 0 if result == "pass" else 3,
                    "result": result, "conclusion": None if not result else ("Kontrol etkin." if result == "pass" else
                                                                            "3 örnekte eskalasyon süresi aşılmış.")},
                    auditor)
                if state in ("ready", "reviewed"):
                    db.execute("UPDATE tdr_workpapers SET status=?, prepared_at=?, reviewer=?, reviewed_at=?, review_note=? "
                               "WHERE id=?", (state, stamp(3), "selin.aydin" if state == "reviewed" else None,
                                              stamp(1) if state == "reviewed" else None,
                                              "Örneklem yeterli." if state == "reviewed" else None, wid))
        # yönetim yanıtları
        open_findings = rows(db, "SELECT id, owner FROM tdr_findings WHERE status IN ('open','in_progress') AND owner IS NOT NULL "
                                 "AND response_status IS NULL ORDER BY id DESC LIMIT 4")
        answers = [("agreed", "Bulguya katılıyoruz. Süreç adımları güncellenecek ve otomatik uyarı kurulacak; hedef 60 gün."),
                   ("partially_agreed", "Kısmen katılıyoruz: iki örnek planlı bakım penceresindedir; diğerleri için eğitim verilecek."),
                   ("pending", None), ("disagreed", "Katılmıyoruz: ilgili kayıtlar müşteri onaylı istisna kapsamındadır (ek yazışma).")]
        for f, (status, text) in zip(open_findings, answers):
            db.execute("UPDATE tdr_findings SET response_status=?, management_response=?, response_due=?, responded_by=?, "
                       "responded_at=? WHERE id=?", (status, text, day(10), f["owner"] if text else None,
                                                     stamp(2) if text else None, f["id"]))
        # denetim evreni ve planlar
        universe = []
        for name, kind, rating, freq in (("Olay Yönetimi", "process", 5, 12), ("Değişiklik Yönetimi", "process", 5, 12),
                                         ("Ödeme İşlemleri", "process", 5, 12), ("Konfigürasyon Yönetimi", "process", 3, 24),
                                         ("Güvenli Yazılım Geliştirme", "process", 4, 18), ("Kurumsal Risk Yönetimi", "process", 3, 24)):
            proc = one(db, "SELECT id FROM tdr_processes WHERE name=?", (name,))
            universe.append(crud.insert(db, A.UNIVERSE, {"name": name, "entity_type": kind, "process_id": proc["id"] if proc else None,
                                                         "inherent_rating": rating, "frequency_months": freq}, auditor))
        for s_row in rows(db, "SELECT id, name FROM tdr_suppliers WHERE tier='critical' ORDER BY id LIMIT 3"):
            universe.append(crud.insert(db, A.UNIVERSE, {"name": s_row["name"], "entity_type": "supplier", "supplier_id": s_row["id"],
                                                         "inherent_rating": 4, "frequency_months": 12}, auditor))
        for c_row in rows(db, "SELECT id, name FROM tdr_companies WHERE kind='own' ORDER BY id"):
            universe.append(crud.insert(db, A.UNIVERSE, {"name": c_row["name"] + " — genel BT kontrolleri", "entity_type": "company",
                                                         "company_id": c_row["id"], "inherent_rating": 3, "frequency_months": 24}, auditor))
        std = one(db, "SELECT id FROM tdr_standards WHERE code='ISO/IEC 27001'")
        if std:
            universe.append(crud.insert(db, A.UNIVERSE, {"name": "Bilgi güvenliği yönetim sistemi (ISO/IEC 27001)",
                                                         "entity_type": "standard", "standard_id": std["id"],
                                                         "inherent_rating": 4, "frequency_months": 12}, auditor))
        year = date.today().year
        current = crud.insert(db, A.PLANS, {"year": year, "title": f"{year} yılı iç denetim planı", "capacity_days": 220,
                                            "notes": TAG}, auditor)
        quarters = ("Q1", "Q2", "Q3", "Q4")
        audits = rows(db, "SELECT id FROM tdr_audits WHERE code LIKE ? ORDER BY id", (f"DNT-{year}-%",))
        for i, uid in enumerate(universe[:6]):
            db.execute("INSERT INTO tdr_audit_plan_items (plan_id, universe_id, quarter, audit_id, status, priority_score, "
                       "planned_days, rationale, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (current, uid, quarters[i % 4], audits[i]["id"] if i < len(audits) else None,
                        "deferred" if i == 5 else "planned", 80 - 6 * i, 15, "Onaylı plan kalemi (demo)", stamp(300)))
        db.execute("UPDATE tdr_audit_plans SET status='approved', approved_by='selin.aydin', approved_at=? WHERE id=?",
                   (stamp(320), current))
        crud.insert(db, A.PLANS, {"year": year + 1, "title": f"{year + 1} yılı iç denetim planı (taslak)", "capacity_days": 240,
                                  "notes": "Öncelikli birimleri ekleyip onaya sunun."}, auditor)
        # sertifikalar
        for title, std_code, body, no, issued, expires, surveillance in (
                ("ISO/IEC 27001:2022 sertifikası", "ISO/IEC 27001", "Örnek Belgelendirme A.Ş.", "DEMO-27001-001", -1025, 70, 40),
                ("ISO/IEC 20000-1:2018 sertifikası", "ISO/IEC 20000-1", "Örnek Belgelendirme A.Ş.", "DEMO-20000-014", -400, 695, 120),
                ("ISO 22301:2019 sertifikası", None, "Kurgu Sertifikasyon Ltd.", "DEMO-22301-007", -200, 895, 165)):
            s_id = one(db, "SELECT id FROM tdr_standards WHERE code=?", (std_code,)) if std_code else None
            crud.insert(db, A.CERTIFICATIONS, {"title": title, "standard_id": s_id["id"] if s_id else None,
                                               "company_id": self._by("companies", "name", "Demo Teknoloji A.Ş."),
                                               "certification_body": body, "certificate_no": no, "scope": "Yönetilen BT hizmetleri; " + TAG,
                                               "issued_on": day(issued), "expires_on": day(expires), "next_surveillance": day(surveillance),
                                               "owner": "selin.aydin"}, admin)

    def compliance(self):
        """Yükümlülük envanteri, politika istisnaları ve okundu beyanı kampanyası."""
        from . import crud
        from .demo_platform import TAG, day, stamp
        from .modules import compliance as C
        db = self.db
        admin = Principal("selin.aydin", "ADMIN", "system", "Selin Aydın")
        clause = lambda code: self._clause("ISO/IEC 27001", code)
        control = lambda name: (one(db, "SELECT id FROM tdr_controls WHERE name LIKE ? ORDER BY id LIMIT 1", (f"%{name}%",)) or {}).get("id")
        items = [
            ("Kişisel verilerin güvenliği için teknik ve idari tedbirler", "law", "6698 sayılı KVKK", "Madde 12/1", "kvkk", "critical",
             "Veri sorumlusu, kişisel verilerin hukuka aykırı işlenmesini ve erişilmesini önlemek, muhafazasını sağlamak için "
             "uygun güvenlik düzeyini temin eden tedbirleri alır (özet).", ["Yönetici hesaplarına erişim", "zafiyet taraması"], ["A.5.34"]),
            ("Kişisel veri ihlalinin Kurula ve ilgiliye bildirimi", "law", "6698 sayılı KVKK ve Kurul kararı 2019/10", "Madde 12/5",
             "kvkk", "critical", "İşlenen verilerin hukuka aykırı yollarla elde edilmesi hâlinde en kısa sürede (Kurul kararıyla en geç "
             "72 saat) ilgiliye ve Kurula bildirilir (özet).", ["Güvenlik olayı bildirim"], ["A.5.34"]),
            ("Kişisel verilerin yurt dışına aktarımı", "law", "6698 sayılı KVKK", "Madde 9", "kvkk", "high",
             "Yurt dışına aktarım yeterlilik kararı, uygun güvenceler veya istisnai hâllere dayanır (özet).", [], ["A.5.23"]),
            ("Dış hizmet alımında risk değerlendirmesi ve denetim hakkı", "regulation",
             "Bankaların Bilgi Sistemleri ve Elektronik Bankacılık Hizmetleri Hakkında Yönetmelik", "Dış hizmet alımı hükümleri",
             "bddk", "high", "Bankaya hizmet veren olarak sözleşmeyle üstlenilen: hizmet öncesi risk değerlendirmesi, denetim hakkı, "
             "veri lokalizasyonu ve süreklilik gereklilikleri (müşteri Demo Banka A.Ş.) (özet).",
             ["sözleşmelerinde güvenlik ve denetim hakkı", "dönemsel performans"], ["A.5.20", "A.5.22"]),
            ("Ödeme hizmetlerinde bilgi sistemleri yönetimi", "regulation",
             "Ödeme ve Elektronik Para Kuruluşlarının Bilgi Sistemleri Yönetimine İlişkin Yönetmelik", "Genel hükümler", "tcmb", "high",
             "Bilgi sistemleri süreklilik, erişim yönetimi, olay yönetimi ve dış hizmet gereklilikleri (Demo Ödeme Hizmetleri A.Ş.) (özet).",
             ["geri yükleme testi", "P1/P2 olaylarında"], ["A.5.30"]),
            ("Aylık hizmet seviyesi raporu", "contract", "Demo Banka A.Ş. hizmet sözleşmesi", "Ek-2 madde 4", "customer", "medium",
             "Her ay 5. iş gününe kadar SLA gerçekleşme raporu paylaşılır (sentetik sözleşme).", ["SLA hedeflerinin"], []),
            ("Yıllık bağımsız sızma testi raporu paylaşımı", "contract", "Örnek Sigorta A.Ş. çerçeve sözleşmesi", "Madde 11.3",
             "customer", "medium", "Yılda bir bağımsız sızma testi yapılır, yönetici özeti müşteriyle paylaşılır (sentetik sözleşme).",
             ["İnternete açık varlıklarda zafiyet"], []),
        ]
        for title, kind, source, article, reg, crit, desc, ctl_names, clause_codes in items:
            oid = crud.insert(db, C.OBLIGATIONS, {"title": title, "source_type": kind, "source": source, "article": article,
                                                  "regulator": reg, "criticality": crit, "description": desc + " " + TAG,
                                                  "owner": "selin.aydin", "review_date": day(120)}, admin)
            for cid in dict.fromkeys(filter(None, (control(n) for n in ctl_names))):
                db.execute("INSERT INTO tdr_obligation_controls (obligation_id, control_id) VALUES (?,?)", (oid, cid))
            for clid in dict.fromkeys(filter(None, (clause(cc) for cc in clause_codes))):
                db.execute("INSERT INTO tdr_obligation_clauses (obligation_id, clause_id) VALUES (?,?)", (oid, clid))
        # politika istisnaları
        policy_doc = self._by("documents", "title", "Tedarikçi Erişim Yönetimi Talimatı")
        mfa = control("Yönetici hesaplarına erişim")
        unit = self._by("org_units", "name", "BT Altyapı ve Operasyon") or None
        for title, scope, status, start, end, risk, approver in (
                ("Eski muhasebe sunucusunda MFA uygulanamaması", "Muhasebe eski sunucusu (2027 Q1 geçiş)", "approved", -170, 10, "high", "selin.aydin"),
                ("Tedarikçi VPN hesabında ortak kullanıcı", "Karadeniz Veri Merkezi bakım ekibi", "requested", 0, 60, "medium", None),
                ("Yedekleme ajanı için yerel yönetici hakkı", "Yedekleme sunucuları", "expired", -400, -35, "medium", "selin.aydin")):
            eid = crud.insert(db, C.EXCEPTIONS, {"title": title, "document_id": policy_doc, "control_id": mfa, "scope": scope,
                                                 "justification": "Üretici desteği ve geçiş planı nedeniyle geçici. " + TAG,
                                                 "compensating_controls": "Ağ yalıtımı, oturum kaydı ve haftalık erişim gözden geçirmesi",
                                                 "risk_level": risk, "owner": "okan.yildiz", "org_unit_id": unit,
                                                 "start_date": day(start), "end_date": day(end) if end > start else day(start + 30)},
                              Principal("okan.yildiz", "SUPPLIER_MANAGER", "system", "Okan Yıldız"))
            if status != "requested":
                db.execute("UPDATE tdr_policy_exceptions SET status=?, approver=?, decided_at=?, decision_note=? WHERE id=?",
                           (status, approver, stamp(-start if start < 0 else 1), "Telafi edici kontroller yeterli; süre sonunda kapanır.", eid))
        # okundu beyanı
        doc = one(db, "SELECT id, current_revision FROM tdr_documents WHERE title='Tedarikçi Yönetimi Politikası'")
        if doc:
            camp = crud.insert(db, C.CAMPAIGNS, {"title": "Tedarikçi Yönetimi Politikası — yıllık okundu beyanı", "document_id": doc["id"],
                                                 "statement": "Politikayı okudum, anladım ve kendi sorumluluk alanımda uygulayacağım.",
                                                 "audience": "all", "due_date": day(14)}, admin)
            users = rows(db, "SELECT username, display_name FROM users WHERE is_active=1 ORDER BY username")
            for i, u in enumerate(users):
                db.execute("INSERT INTO tdr_attestations (campaign_id, username, display_name, status, acknowledged_at, revision, "
                           "created_at) VALUES (?,?,?,?,?,?,?)", (camp, u["username"], u["display_name"],
                                                                  "acknowledged" if i % 3 else "pending", stamp(3 - i % 3) if i % 3 else None,
                                                                  doc["current_revision"], stamp(5)))
            db.execute("UPDATE tdr_attestation_campaigns SET status='open', revision=?, launched_at=? WHERE id=?",
                       (doc["current_revision"], stamp(5), camp))


    # -------------------------------------------------------------- olay, kayıp, ihlal, RCSA, nicel risk (K-027)
    def incidents(self):
        import json as _json
        from datetime import datetime, timedelta, timezone
        from . import crud
        from .demo_platform import TAG, day, stamp
        from .modules import incidents as I
        db = self.db
        admin = Principal("selin.aydin", "ADMIN", "system", "Selin Aydın")
        risks = rows(db, "SELECT id, code, title, company_id, process_id, category FROM tdr_supplier_risks WHERE status IN "
                         "('open','in_treatment') ORDER BY COALESCE(residual_score, inherent_score) DESC, id LIMIT 8")
        losses = (("Ödeme ağ geçidinde 3 saatlik kesinti", "systems", -40, 420000, 0, "INC0019811"),
                  ("Tedarikçi faturasında mükerrer ödeme", "execution_process", -75, 86000, 86000, None),
                  ("Sahte tedarikçi e-postasıyla ödeme talebi (önlendi)", "external_fraud", -20, 0, 0, None),
                  ("Yedekleme ajanı hatası nedeniyle veri kaybı", "systems", -120, 150000, 20000, "INC0017302"),
                  ("SLA ihlali nedeniyle müşteri cezai şartı", "clients_products", -60, 275000, 0, None),
                  ("Sunucu odası klima arızası", "physical_assets", -200, 64000, 30000, None),
                  ("Yanlış konfigürasyonla yayımlanan sürüm", "execution_process", -15, 98000, 0, "INC0020144"),
                  ("Çağrı merkezi personel devri nedeniyle hizmet aksaması", "employment", -95, 45000, 0, None))
        for i, (title, kind, ago, gross, rec, ref) in enumerate(losses):
            r = risks[i % len(risks)] if risks else {}
            crud.insert(db, I.LOSS_EVENTS, {"title": title, "event_type": kind, "occurred_on": day(ago), "discovered_on": day(ago + 1),
                                            "gross_loss": gross, "recovery": rec, "near_miss": 1 if gross == 0 else 0,
                                            "risk_id": r.get("id"), "company_id": r.get("company_id"), "process_id": r.get("process_id"),
                                            "external_ref": ref, "source": "servicenow" if ref else "manual",
                                            "status": "closed" if ago < -90 else "analysis",
                                            "root_cause": "Kök neden analizi tamamlandı; kalıcı çözüm DÖF ile izleniyor." if ago < -90 else None,
                                            "description": TAG}, admin)
        estimates = ((0.2, 0.5, 2, 300000, 1500000, 9000000), (1, 3, 8, 20000, 90000, 600000), (0.05, 0.15, 0.5, 2000000, 8000000, 40000000),
                     (2, 6, 15, 5000, 25000, 150000), (0.1, 0.3, 1, 500000, 2500000, 12000000))
        for r, (a, b, c, d, e, f) in zip(risks, estimates):
            inputs = {"freq_min": a, "freq_likely": b, "freq_max": c, "loss_min": d, "loss_likely": e, "loss_max": f}
            losses_sim = I.simulate(inputs, 10000, 1000 + r["id"])
            mean = sum(losses_sim) / len(losses_sim)
            top = losses_sim[-1] or 1
            curve = [[round(top * k / 20, 2), round(sum(1 for v in losses_sim if v > top * k / 20) / len(losses_sim), 4)] for k in range(21)]
            db.execute("INSERT INTO tdr_risk_quant_runs (risk_id, inputs_json, iterations, mean_loss, p50, p90, p95, p99, zero_share, "
                       "curve_json, created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (r["id"], _json.dumps(inputs), 10000, round(mean, 2), round(I._percentile(losses_sim, 50), 2),
                        round(I._percentile(losses_sim, 90), 2), round(I._percentile(losses_sim, 95), 2),
                        round(I._percentile(losses_sim, 99), 2), round(sum(1 for v in losses_sim if v == 0) / len(losses_sim), 4),
                        _json.dumps(curve), "selin.aydin", stamp(4)))
            db.execute("UPDATE tdr_supplier_risks SET ale=?, quantified_at=? WHERE id=?", (round(mean, 2), stamp(4), r["id"]))
        now = datetime.now(timezone.utc)
        company = self._by("companies", "name", "Demo Ödeme Hizmetleri A.Ş.")
        crud.insert(db, I.BREACHES, {"title": "Müşteri bildirim listesinin yanlış alıcıya e-postalanması", "company_id": company,
                                     "owner": "selin.aydin", "detected_at": (now - timedelta(hours=40)).isoformat(timespec="seconds"),
                                     "occurred_at": (now - timedelta(hours=44)).isoformat(timespec="seconds"),
                                     "description": "Toplu bilgilendirme e-postası yanlış dağıtım listesiyle gönderildi. " + TAG,
                                     "data_categories": "Ad soyad, e-posta, müşteri numarası", "subjects_count": 312,
                                     "subject_groups": "Kurumsal müşteri yetkilileri", "consequences": "Kimlik avı riski",
                                     "measures": "Alıcıdan silme teyidi istendi; dağıtım listesi kilitlendi."}, admin)
        closed = crud.insert(db, I.BREACHES, {"title": "Kayıp dizüstü bilgisayar (şifreli disk)", "company_id": company, "owner": "okan.yildiz",
                                              "detected_at": (now - timedelta(days=60)).isoformat(timespec="seconds"),
                                              "description": "Saha ekibine ait şifreli dizüstü bilgisayar kayboldu. " + TAG,
                                              "data_categories": "İş iletişim bilgileri", "subjects_count": 40}, admin)
        db.execute("UPDATE tdr_privacy_breaches SET notify_decision='not_required', decision_rationale=?, decided_by='selin.aydin', "
                   "decided_at=?, status='closed', measures=? WHERE id=?",
                   ("Disk tam şifreli (BitLocker), anahtar cihazda değil; kişiler için risk düşük.", stamp(59),
                    "Cihaz uzaktan kilitlendi, hesaplar sıfırlandı.", closed))
        # RCSA
        proc = one(db, "SELECT id FROM tdr_processes WHERE name='Olay Yönetimi'")
        camp = crud.insert(db, I.RCSA_CAMPAIGNS, {"title": f"{date.today().year} 2. yarıyıl öz değerlendirmesi — Olay Yönetimi",
                                                  "period": f"{date.today().year}-H2", "process_id": proc["id"] if proc else None,
                                                  "due_date": day(12), "instructions": "Risklerinizi ve kontrollerinizin son 6 aydaki işleyişini değerlendirin."},
                           admin)
        items = rows(db, "SELECT id, owner FROM tdr_supplier_risks WHERE status IN ('open','in_treatment')"
                         + (" AND process_id=?" if proc else "") + " LIMIT 4", (proc["id"],) if proc else ())
        controls = rows(db, "SELECT k.id, k.owner FROM tdr_controls k JOIN tdr_control_processes m ON m.control_id=k.id "
                            "WHERE m.process_id=? AND k.execution_mode='manual' LIMIT 3", (proc["id"],)) if proc else []
        for i, r in enumerate(items):
            db.execute("INSERT INTO tdr_rcsa_items (campaign_id, item_type, risk_id, respondent, status, likelihood, impact, comment, "
                       "submitted_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                       (camp, "risk", r["id"], r["owner"] or "zeynep.demir", "submitted" if i < 2 else "pending",
                        4 if i == 0 else 2 if i == 1 else None, 4 if i == 0 else 3 if i == 1 else None,
                        "Hafta sonu vardiyasında eskalasyon gecikiyor" if i == 0 else None, stamp(1) if i < 2 else None, stamp(3)))
        for i, k in enumerate(controls):
            db.execute("INSERT INTO tdr_rcsa_items (campaign_id, item_type, control_id, respondent, status, effectiveness, comment, "
                       "submitted_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                       (camp, "control", k["id"], "zeynep.demir", "submitted" if i < 2 else "pending",
                        ("partially_effective" if i == 0 else "effective") if i < 2 else None,
                        "Gece vardiyasında ikinci onay atlanabiliyor" if i == 0 else None, stamp(1) if i < 2 else None, stamp(3)))
        db.execute("UPDATE tdr_rcsa_campaigns SET status='open', launched_at=? WHERE id=?", (stamp(3), camp))

    def access_and_crisis(self):
        """Erişim gözden geçirme (tamamlanmış ve açık) ve geçmiş bir kriz (gerçek olay tatbikatıyla)."""
        from . import crud
        from .demo_platform import TAG, day, stamp
        from .modules import access_reviews as AR, crisis as CR
        from .modules.grc import store_file
        db = self.db
        admin = Principal("selin.aydin", "ADMIN", "system", "Selin Aydın")
        if self.enabled("grc"):
            ctl = (one(db, "SELECT id FROM tdr_controls WHERE name LIKE '%Yönetici hesaplarına erişim%' LIMIT 1") or {}).get("id")
            accounts = [("a.yilmaz", "Ayşe Yılmaz", "DBA"), ("m.kaya", "Mehmet Kaya", "Sunucu yöneticisi"),
                        ("eski.personel", "Ayrılan Personel", "Domain Admin"), ("svc_backup", "Yedekleme hizmet hesabı", "Backup Operator"),
                        ("k.aksoy", "Kerem Aksoy", "Sunucu yöneticisi"), ("tedarikci.bakim", "Tedarikçi bakım hesabı", "VPN + yerel yönetici")]
            done = crud.insert(db, AR.REVIEWS, {"title": "Yönetici hesapları — üçüncü çeyrek gözden geçirmesi", "system": "Active Directory (ayrıcalıklı gruplar)",
                                                "control_id": ctl, "reviewer": "okan.yildiz", "due_date": day(-20)}, admin)
            open_ = crud.insert(db, AR.REVIEWS, {"title": "Yönetici hesapları — dördüncü çeyrek gözden geçirmesi", "system": "Active Directory (ayrıcalıklı gruplar)",
                                                 "control_id": ctl, "reviewer": "okan.yildiz", "due_date": day(9)}, admin)
            for review, finished in ((done, True), (open_, False)):
                for j, (acc, person, ent) in enumerate(accounts):
                    decision = ("revoke" if acc in ("eski.personel",) else "modify" if acc == "tedarikci.bakim" else "keep") if finished else "pending"
                    db.execute("INSERT INTO tdr_access_review_items (review_id, account, person, entitlement, last_login, decision, comment, "
                               "decided_by, decided_at, remediated, remediated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                               (review, acc, person, ent, day(-j * 7), decision,
                                "Ayrılmış çalışan" if decision == "revoke" else "Yalnızca bakım penceresinde etkin olsun" if decision == "modify" else None,
                                "okan.yildiz" if finished else None, stamp(25) if finished else None, 1 if finished and decision == "revoke" else 0,
                                stamp(22) if finished and decision == "revoke" else None, stamp(30)))
            evidence_id = crud.insert(db, RESOURCES_EVIDENCE(), {"title": "Erişim gözden geçirmesi — Active Directory (Q3)", "source": "system",
                                                                 "confidentiality": "confidential", "description": TAG}, None)
            store_file(db, evidence_id, "erisim-gozden-gecirme-q3.csv", "Hesap;Karar\na.yilmaz;Kalsın\n".encode("utf-8"), "okan.yildiz")
            if ctl:
                db.execute("INSERT INTO tdr_evidence_controls (evidence_id, control_id) VALUES (?,?) ON CONFLICT DO NOTHING", (evidence_id, ctl))
            db.execute("UPDATE tdr_access_reviews SET status='completed', launched_at=?, completed_at=?, evidence_id=? WHERE id=?",
                       (stamp(30), stamp(24), evidence_id, done))
            db.execute("UPDATE tdr_access_reviews SET status='open', launched_at=? WHERE id=?", (stamp(2), open_))
        if self.enabled("continuity"):
            plan = one(db, "SELECT id, code FROM tdr_bc_plans WHERE status='approved' ORDER BY id LIMIT 1")
            if plan:
                incident = crud.insert(db, CR.INCIDENTS, {"title": "Birincil veri merkezinde enerji kesintisi", "severity": "critical",
                                                          "status": "closed", "description": "Trafo arızası nedeniyle birincil veri merkezi 3 saat enerjisiz kaldı. " + TAG,
                                                          "commander": "Kerem Aksoy", "declared_by": "kerem.aksoy",
                                                          "declared_at": stamp(140, 2)}, admin)
                db.execute("INSERT INTO tdr_bc_incident_plans (incident_id, plan_id) VALUES (?,?)", (incident, plan["id"]))
                for step in rows(db, "SELECT * FROM tdr_bc_plan_steps WHERE plan_id=? ORDER BY position", (plan["id"],)):
                    db.execute("INSERT INTO tdr_bc_incident_tasks (incident_id, plan_id, phase, position, action, responsible, target_minutes, "
                               "status, done_at, done_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                               (incident, plan["id"], step["phase"], step["position"], step["action"], step["responsible"],
                                step["target_minutes"], "done", stamp(140, 4), "kerem.aksoy", stamp(140, 2)))
                for hour, kind, text in ((2, "status", "Kriz ilan edildi; DR planı devreye alındı."),
                                         (2, "decision", "Kritik hizmetlerin ikincil merkeze geçişine karar verildi."),
                                         (3, "communication", "Müşterilere ve BDDK'ya ön bilgilendirme yapıldı."),
                                         (5, "status", "Enerji geri geldi; hizmetler birincil merkeze döndü.")):
                    db.execute("INSERT INTO tdr_bc_incident_log (incident_id, kind, text, author, logged_at) VALUES (?,?,?,?,?)",
                               (incident, kind, text, "kerem.aksoy", stamp(140, hour)))
                exercise = crud.insert(db, RESOURCES_EXERCISES(), {"title": "Gerçek olay: Birincil veri merkezinde enerji kesintisi",
                                                                   "exercise_type": "real_incident", "plan_id": plan["id"],
                                                                   "scenario": "Trafo arızası", "planned_date": day(-140), "actual_date": day(-140),
                                                                   "status": "completed", "facilitator": "Kerem Aksoy",
                                                                   "achieved_recovery_minutes": 185, "outcome": "successful",
                                                                   "lessons_learned": "Jeneratör yakıt tedarik sözleşmesi 24 saate çıkarılmalı.",
                                                                   "report": "Kritik hizmetler 45 dakikada ikincil merkezden sürdürüldü."}, None)
                db.execute("UPDATE tdr_bc_incidents SET closed_at=?, recovered_at=?, summary=?, lessons_learned=?, exercise_id=? WHERE id=?",
                           (stamp(140, 6), stamp(140, 5), "Kritik hizmetler 45 dakikada ikincil merkezden sürdürüldü; 3 saat sonra normale dönüldü.",
                            "Jeneratör yakıt tedarik sözleşmesi 24 saate çıkarılmalı.", exercise, incident))


def RESOURCES_EVIDENCE():
    from .schema import RESOURCES
    return RESOURCES["evidence"]


def RESOURCES_EXERCISES():
    from .schema import RESOURCES
    return RESOURCES["bc_exercises"]


ASSURANCE_SECTIONS = (("standards", "grc"), ("assurance", "grc"), ("compliance", "grc"), ("incidents", "risks"),
                      ("access_and_crisis", "core"))
