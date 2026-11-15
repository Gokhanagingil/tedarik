"""Demo verisinin standart kütüphanesi, güvence, uyum, olay ve entegrasyon bölümleri (K-023 ve sonrası).

demo_platform.py ile aynı ilkeler: her bölüm boş veritabanında ve önceki sürümle yüklenmiş demoda çalışır, kayıtları
adla veya kodla bulur, bir kez yüklenir. Tüm veriler sentetiktir. Çapraz eşlemeler örnektir; kurumun lisanslı eşleme
tablolarıyla değiştirilmesi beklenir (gerekçe alanında belirtilir).
"""
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


ASSURANCE_SECTIONS = (("standards", "grc"),)
