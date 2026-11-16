"""Gerçek Chromium ile arayüz duman testi. Geçici SQLite veritabanı ve sentetik veriyle çalışır; hiçbir gerçek
ortama dokunmaz. Her ekran açılır, ana akışlar tıklanarak denenir, tarayıcı konsolunda hata kabul edilmez.

    python scripts/browser_smoke.py [ekran_görüntüsü_klasörü]

Chromium yolu `PLAYWRIGHT_CHROMIUM` ortam değişkeniyle verilebilir (CI'da Playwright'ın kendi tarayıcısı).
"""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(base, method, path, body=None):
    request = urllib.request.Request(base + "/api/tdr/" + path, method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read() or b"null")


def seed(base):
    unit = call(base, "POST", "org_units", {"name": "Bilgi Teknolojileri"})["id"]
    ops = call(base, "POST", "org_units", {"name": "Operasyon"})["id"]
    item = call(base, "POST", "catalog_items", {"name": "Veri merkezi barındırma"})["id"]
    s1 = call(base, "POST", "suppliers", {"name": "Örnek Bilişim A.Ş.", "tier": "critical", "owner": "ayse"})["id"]
    s2 = call(base, "POST", "suppliers", {"name": "Deneme Lojistik Ltd.", "tier": "important"})["id"]
    e1 = call(base, "POST", "engagements", {"supplier_id": s1, "catalog_item_id": item, "org_unit_id": unit,
                                            "business_owner": "ayse", "beneficiary": "customer", "customer_name": "Müşteri A"})["id"]
    call(base, "POST", "engagements", {"supplier_id": s2, "catalog_item_id": item, "org_unit_id": ops})
    call(base, "POST", "contracts", {"supplier_id": s1, "title": "Barındırma sözleşmesi",
                                     "end_date": (date.today() + timedelta(days=40)).isoformat()})
    sla = call(base, "POST", "sla_definitions", {"engagement_id": e1, "name": "Erişilebilirlik", "target_value": 99.5})["id"]
    call(base, "POST", "sla_measurements", {"sla_id": sla, "period_start": date.today().replace(day=1).isoformat(), "actual_value": 99.1})
    call(base, "POST", "performance_events", {"supplier_id": s1, "event_type": "incident", "description": "Kesinti",
                                              "occurred_at": date.today().isoformat()})
    call(base, "POST", "supplier_risks", {"title": "Tek tedarikçiye bağımlılık", "supplier_id": s1, "category": "concentration",
                                          "owner": "ayse", "appetite": 6, "likelihood": 4, "impact": 5, "review_date": "2099-01-01",
                                          "cause": "Alternatif tedarikçi olmadığı için", "risk_event": "kesinti hizmeti durdurabilir",
                                          "consequence": "müşteri taahhüdü aşılabilir"})
    std = call(base, "POST", "standards", {"code": "ISO/IEC 27001", "name": "Bilgi güvenliği", "version": "2022"})["id"]
    for code, title in (("A.5.19", "Tedarikçi ilişkilerinde bilgi güvenliği"), ("A.5.22", "Tedarikçi hizmetlerinin izlenmesi")):
        call(base, "POST", "clauses", {"standard_id": std, "code": code, "title": title})
    call(base, "POST", "controls", {"name": "Tedarikçi sahibi atanmış", "execution_mode": "automatic",
                                    "automation": "supplier.owner", "frequency": "weekly"})


def go(page, key, title):
    page.locator(f'[data-nav="{key}"]').click()
    expect(page.locator("#pageTitle")).to_have_text(title)
    expect(page.locator("#content .empty", has_text="Yükleniyor")).to_have_count(0)


def exercise(page, out, base, errors):
    checks = []
    page.goto(base + "/")
    expect(page.locator("#pageTitle")).to_have_text("Genel Bakış")
    expect(page.locator(".metric").first).to_be_visible()
    page.screenshot(path=str(out / "01-genel-bakis.png"), full_page=True)
    checks.append("dashboard")
    for key in [b.get_attribute("data-nav") for b in page.locator("[data-nav]").all()]:
        page.locator(f'[data-nav="{key}"]').click()
        expect(page.locator("#pageTitle")).not_to_have_text("Yükleniyor…")
        expect(page.locator("#pageTitle")).not_to_have_text("Bir sorun oluştu")
        expect(page.locator("#content .notice.bad")).to_have_count(0)
        checks.append("ekran:" + key)
    # yavaş ağ: önceki ekranın geç gelen yanıtı yeni ekranı ezmemeli
    page.route("**/api/tdr/users", lambda route: (time.sleep(1.5), route.continue_()))
    page.route("**/api/tdr/suppliers?*", lambda route: (time.sleep(2.5), route.continue_()))
    page.locator('[data-nav="users"]').click()
    page.locator('[data-nav="r/suppliers"]').click()      # tedarikçi listesi, kullanıcılar yanıtından sonra gelir
    page.wait_for_timeout(4500)
    page.unroute("**/api/tdr/suppliers?*")
    expect(page.locator("#pageTitle")).to_have_text("Tedarikçiler")
    expect(page.locator("#content")).to_contain_text("Örnek Bilişim")
    expect(page.locator("#content")).not_to_contain_text("Son giriş")
    page.unroute("**/api/tdr/users")
    checks.append("eski_cizim_korumasi")
    go(page, "schedule", "Takvim")
    expect(page.locator("#content")).to_contain_text("Değerlendirme ve anket takvimi")
    checks.append("takvim")
    # tedarikçi 360
    go(page, "r/suppliers", "Tedarikçiler")
    page.locator("#tableSearch").fill("örnek")
    expect(page.locator("[data-row]")).to_have_count(1)
    page.locator("[data-row]").first.click()
    expect(page.locator("#detail")).to_have_class("open")
    expect(page.locator("#detailKicker")).to_contain_text("Tedarikçi 360")
    for tab in ["Angajmanlar", "Riskler", "Anketler", "Sözleşmeler", "Kişiler", "Özet"]:
        page.locator("#detail .tab", has_text=tab).click()
    page.screenshot(path=str(out / "02-tedarikci-360.png"), full_page=True)
    page.keyboard.press("Escape")
    expect(page.locator("#detail")).not_to_have_class("open")
    checks.append("tedarikci_360")
    # form ile yeni kayıt ve doğrulama
    page.locator("#topActions button", has_text="Yeni").click()
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#detail .field.invalid").first).to_be_visible()
    page.locator('#detail [name="name"]').fill("Arayüz Tedarikçisi")
    page.locator('#detail [name="tier"]').select_option("critical")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#detailTitle")).to_have_text("Arayüz Tedarikçisi")
    checks.append("form_dogrulama_ve_kayit")
    page.keyboard.press("Escape")
    # risk değerlendirme
    go(page, "r/supplier_risks", "Risk Kaydı")
    page.locator("[data-row]").first.click()
    page.locator("#detailFooter button", has_text="Değerlendir").click()
    page.locator("#modal button", has_text="+ Önlem ekle").click()
    page.locator("#modal .mitigation-row input").fill("Yedek tedarikçiyle çerçeve sözleşme")
    page.locator("#modal .mitigation-row select").first.select_option("high")
    expect(page.locator("#modal .score-preview")).to_contain_text("Artık 8")
    page.locator("#assessRationale").fill("Yedek tedarikçi görüşmeleri tamamlandı")
    page.locator("#modalFooter button", has_text="Değerlendirmeyi kaydet").click()
    expect(page.locator("#toast")).to_contain_text("Değerlendirildi")
    expect(page.locator("#detail")).to_contain_text("İçsel 20 → artık 8")
    page.screenshot(path=str(out / "03-risk.png"), full_page=True)
    page.keyboard.press("Escape")
    checks.append("risk_degerlendirme")
    # uyum (GRC): manuel kontrol, eşleme, test sonucu -> bulgu -> DÖF -> doğrulama; otomatik kontrol; denetim; pano
    go(page, "r/controls", "Kontroller")
    page.locator("#topActions button", has_text="Yeni").click()
    page.locator('#detail [name="name"]').fill("Kritik sözleşmelerde denetim hakkı")
    page.locator('#detail [name="criticality"]').select_option("high")
    page.locator('#detail [name="owner"]').fill("dev")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#detailKicker")).to_have_text("Kontrol")
    page.locator("#detailFooter button", has_text="Eşlemeler").click()
    page.locator("#modal label", has_text="A.5.19").locator("input").check()
    page.locator("#modalFooter button", has_text="Eşlemeleri kaydet").click()
    expect(page.locator("#detail")).to_contain_text("A.5.19")
    page.locator("#detailFooter button", has_text="Sonuç kaydet").click()
    page.locator("#resStatus").select_option("fail")
    page.locator("#resDetails").fill("2 sözleşmede denetim hakkı maddesi yok")
    page.locator("#modalFooter button", has_text="Sonucu kaydet").click()
    expect(page.locator("#toast")).to_contain_text("bulgu açıldı")
    page.locator("#detail .tab", has_text="Bulgular").click()
    page.locator("#detail .mini li").first.click()
    expect(page.locator("#detailKicker")).to_have_text("Bulgu")
    page.locator("#detail button", has_text="+ DÖF").click()
    page.locator('#detail [name="title"]').fill("Sözleşme ek protokolü")
    page.locator('#detail [name="owner"]').fill("ayse")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    page.locator("#detail .mini li", has_text="Sözleşme ek protokolü").click()
    page.locator("#detailFooter button", has_text="Doğrulamaya gönder").click()
    page.locator("#trNote").fill("Ek protokol imzalandı")
    page.locator("#modalFooter button", has_text="Gönder").click()
    page.locator("#detailFooter button", has_text="Etkinliği doğrula").click()
    page.locator("#trNote").fill("İmzalı protokol incelendi")
    page.locator("#modalFooter button", has_text="Doğrula ve tamamla").click()
    expect(page.locator("#detail")).to_contain_text("İmzalı protokol incelendi")
    page.screenshot(path=str(out / "04-dof.png"), full_page=True)
    page.keyboard.press("Escape")
    checks.append("grc_test_bulgu_dof")
    go(page, "r/controls", "Kontroller")
    page.locator("[data-row]", has_text="Tedarikçi sahibi atanmış").click()
    page.locator("#detailFooter button", has_text="Şimdi çalıştır").click()
    expect(page.locator("#toast")).to_contain_text("Kontrol")
    page.keyboard.press("Escape")
    checks.append("grc_ic_otomatik")
    go(page, "r/audits", "Denetimler")
    page.locator("#topActions button", has_text="Yeni").click()
    page.locator('#detail [name="name"]').fill("Tedarikçi yönetimi iç denetimi")
    page.locator("#detail .picker .searchbar").fill("A.5.19")                 # madde seçici (ağaç + arama)
    page.locator("#detail .tree-row", has_text="A.5.19").locator("input").check()
    expect(page.locator("#detail .picker-summary")).to_contain_text("1 madde seçildi")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#pageTitle")).to_contain_text("Tedarikçi yönetimi iç denetimi")
    page.locator("#topActions button", has_text="Denetimi başlat").click()
    expect(page.locator("#content")).to_contain_text("Devam ediyor")
    page.locator("#content .tab", has_text="Test planı").click()            # entegre test planı: kontrol başına tek test
    card = page.locator(".test-card", has_text="Kritik sözleşmelerde denetim hakkı")
    card.locator("button", has_text="Test et").click()
    page.locator("#resStatus").select_option("pass")
    page.locator("#modalFooter button", has_text="Sonucu kaydet").click()
    expect(page.locator(".test-card", has_text="Kritik sözleşmelerde denetim hakkı")).to_contain_text("Başarılı")
    page.locator("#content .tab", has_text="Özet").click()
    expect(page.locator("#content")).to_contain_text("%100")
    page.screenshot(path=str(out / "05-denetim.png"), full_page=True)
    checks.append("grc_denetim")
    # GRC platformu ekranları: risk panosu, süreklilik (BİA → etki matrisi → onaya gönder), takvim, sağlık, haritalar, palet
    go(page, "risk", "Risk Panosu")
    expect(page.locator("#content .heat")).to_be_visible()
    page.screenshot(path=str(out / "06-risk-panosu.png"), full_page=True)
    go(page, "r/processes", "Süreçler")
    page.locator("#topActions button", has_text="Yeni").click()
    page.locator('#detail [name="name"]').fill("Ödeme işlemleri")
    page.locator('#detail [name="process_type"]').select_option("core")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#detailKicker")).to_have_text("Süreç")
    page.locator("#detail button", has_text="+ BİA").click()
    page.locator('#detail [name="rto_hours"]').fill("2")
    page.locator('#detail [name="rpo_hours"]').fill("1")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#detailKicker")).to_have_text("İş etki analizi")
    page.locator("#detail .tab", has_text="Etki matrisi").click()
    page.locator("#detail button", has_text="Etki matrisini düzenle").click()
    page.locator('#modal select[data-cat="financial"][data-win="h4"]').select_option("4")
    expect(page.locator('#modal select[data-cat="financial"][data-win="m1"]')).to_have_value("4")   # sonraki hücreler yükselir
    page.locator("#modalFooter button", has_text="Kaydet").click()
    expect(page.locator("#toast")).to_contain_text("Etki matrisi kaydedildi")
    page.locator("#detail .tab", has_text="Özet").click()
    expect(page.locator("#detail .stat-strip")).to_contain_text("4 saat")
    page.locator("#detailFooter button", has_text="Onaya gönder").click()
    expect(page.locator("#detail .chips")).to_contain_text("Onayda")
    page.screenshot(path=str(out / "07-bia.png"), full_page=True)
    page.keyboard.press("Escape")
    checks.append("bia_etki_matrisi_ve_onaya_gonderim")
    go(page, "process-map", "Süreç Haritası")
    expect(page.locator(".band.core .proc", has_text="Ödeme işlemleri")).to_be_visible()
    go(page, "map", "İlişki Haritası")
    expect(page.locator(".map-box.sel")).to_have_count(1)
    go(page, "calendar", "GRC Takvimi")
    expect(page.locator(".cal .day").first).to_be_visible()
    if page.locator(".type-chip").count():                       # yalnızca kaydı olan türler; süzgeç geri alınabilir
        page.locator(".type-chip").first.click()
        page.get_by_role("button", name="Tümünü göster").click()
        expect(page.locator(".type-chip.on")).to_have_count(page.locator(".type-chip").count())
    go(page, "health", "GRC Sağlık Kontrolü")
    expect(page.locator(".check").first).to_be_visible()
    page.keyboard.press("Control+k")
    page.locator("#palette .pal-input").fill("örnek")
    expect(page.locator(".pal-list li[role=option]", has_text="Örnek Bilişim")).to_be_visible()
    page.keyboard.press("Escape")
    checks.append("grc_platform_ekranlari")
    go(page, "archive", "Denetim Arşivi")                       # madde koduyla geçmiş denetim ve kanıt araması
    page.locator(".archive-q").fill("A.5.19")
    page.locator(".archive-q").press("Enter")
    expect(page.locator(".archive-audit").first).to_contain_text("Tedarikçi yönetimi iç denetimi")
    expect(page.locator(".archive-table").first).to_contain_text("Kritik sözleşmelerde denetim hakkı")
    page.screenshot(path=str(out / "05c-denetim-arsivi.png"), full_page=True)
    checks.append("denetim_arsivi")
    go(page, "compliance", "Uyum Panosu")
    expect(page.locator("#content")).to_contain_text("Standartlara göre")
    page.screenshot(path=str(out / "05b-uyum-panosu.png"), full_page=True)
    checks.append("grc_uyum_panosu")
    # standart kütüphanesi: NIST CSF 2.0 kurulumu ve standart tarayıcısı (K-023)
    go(page, "library", "Standart Kütüphanesi")
    page.locator(".lib-card", has_text="NIST CSF").locator("button", has_text="Kur").click()
    expect(page.locator("#toast")).to_contain_text("134 yeni")
    page.locator(".lib-card", has_text="NIST CSF").locator("button", has_text="Aç").click()
    expect(page.locator("#pageTitle")).to_have_text("NIST CSF 2.0")
    page.locator(".tree-open", has_text="GV.SC Cybersecurity Supply Chain").first.click()   # işlevler açık gelir
    expect(page.locator(".tree-open", has_text="GV.SC-07").first).to_be_visible()
    page.locator(".tree-open", has_text="GV.SC-07").first.click()
    expect(page.locator("#detailTitle")).to_contain_text("GV.SC-07")
    page.screenshot(path=str(out / "05d-standart.png"))
    page.keyboard.press("Escape")
    checks.append("standart_kutuphanesi")
    # güvence, uyum, olay ve yönetim ekranları (K-024 – K-027): boş veride de hatasız açılmalı
    for key, title in (("obligations", "Yükümlülük Envanteri"), ("audit-plan", "Denetim Planı"), ("crisis", "Kriz Yönetimi"),
                       ("integrations", "Entegrasyonlar"), ("notifications", "Bildirimler"),
                       ("r/evidence_requests", "Kanıt Talepleri"), ("r/policy_exceptions", "Politika İstisnaları"),
                       ("r/attestation_campaigns", "Okundu Beyanı Kampanyaları"), ("r/certifications", "Sertifikalar"),
                       ("r/access_reviews", "Erişim Gözden Geçirmeleri"), ("r/privacy_breaches", "Kişisel Veri İhlalleri"),
                       ("r/rcsa_campaigns", "Öz Değerlendirme (RCSA)"), ("r/loss_events", "Kayıp Olayları")):
        go(page, key, title)
    checks.append("guvence_uyum_olay_ekranlari")
    # veri yönetişimi (K-028): kaynak → sihirbazla içe aktarım → katalog → kolon anlamı → terim → kolona bağlama
    go(page, "datagov", "Veri Yönetişimi")
    expect(page.locator("#content")).to_contain_text("üç adımda")
    page.locator("#topActions button", has_text="+ Veri kaynağı").click()
    expect(page.locator("#detailTitle")).to_have_text("Yeni: Veri Kaynakları")
    page.locator('#detail [name="name"]').fill("SAP S/4HANA Test")
    page.locator('#detail [name="platform"]').select_option("sap_hana")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#pageTitle")).to_have_text("SAP S/4HANA Test")
    ddic = Path(tempfile.mkdtemp()) / "dd03l.csv"
    ddic.write_text("TABNAME,FIELDNAME,POSITION,DATATYPE,LENG,KEYFLAG,DDTEXT,SCRTEXT_L\n"
                    "KNA1,KUNNR,0001,CHAR,000010,X,Genel müşteri ana verileri,Müşteri\n"
                    "KNA1,STCD1,0002,CHAR,000016,,Genel müşteri ana verileri,Vergi numarası 1\n"
                    "VBAK,VBELN,0001,CHAR,000010,X,Satış belgesi başlık,Satış belgesi\n", encoding="utf-8")
    page.locator("#topActions button", has_text="İçe aktar").click()
    page.locator("#impFile").set_input_files(str(ddic))
    page.locator("#impSchema").fill("SAPABAP1")
    page.locator("#modalFooter button", has_text="Ön izle").click()
    expect(page.locator("#modal")).to_contain_text("SAP ABAP sözlüğü")
    page.locator("#modal button", has_text="İçe aktar").last.click()
    expect(page.locator("#toast")).to_contain_text("İçe aktarıldı")
    expect(page.locator("#content")).to_contain_text("SAPABAP1")
    page.locator("#content tr", has_text="SAPABAP1").click()
    expect(page.locator("#pageTitle")).to_have_text("Veri Kataloğu")
    page.locator("#content tr", has_text="KNA1").click()
    expect(page.locator("#pageTitle")).to_contain_text("KNA1")
    page.locator("table.columns tr", has_text="STCD1").click()
    expect(page.locator("#detail .meaning")).to_contain_text("Vergi numarası 1")       # kaynak açıklaması, iş tanımı yok
    page.locator("#detailFooter button", has_text="Düzenle").click()
    expect(page.locator("#detailTitle")).to_have_text("Kolon: STCD1")
    page.locator('#detail [name="business_name"]').fill("T.C. kimlik numarası")
    page.locator('#detail [name="personal_data"]').select_option("personal")
    page.locator('#detail [name="classification"]').select_option("restricted")
    page.locator("#detailFooter button", has_text="Kaydet").click()
    expect(page.locator("#detailTitle")).to_contain_text("T.C. kimlik numarası")
    page.screenshot(path=str(out / "08-veri-katalogu.png"))
    page.keyboard.press("Escape")
    go(page, "glossary", "İş Sözlüğü")
    page.locator("#topActions button", has_text="+ Terim").click()
    expect(page.locator("#detailTitle")).to_have_text("Yeni: İş Sözlüğü")
    page.locator('#detail [name="name"]').fill("T.C. kimlik numarası")
    page.locator('#detail [name="abbreviation"]').fill("TCKN")
    page.locator('#detail [name="definition"]').fill("Türkiye Cumhuriyeti vatandaşlarına verilen 11 haneli kimlik numarası.")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#pageTitle")).to_have_text("T.C. kimlik numarası")
    page.locator("#content button", has_text="+ Kolon bağla").click()
    page.locator("#modal input[type=search]").fill("STCD")
    page.locator("#modal .pick-results li", has_text="STCD1").click()
    page.locator("#modalFooter button", has_text="Bağla").click()
    expect(page.locator("#content")).to_contain_text("STCD1")
    page.locator("#topActions button", has_text="Onaya gönder").click()
    expect(page.locator("#content")).to_contain_text("Onay bekliyor")
    page.screenshot(path=str(out / "08b-is-sozlugu.png"), full_page=True)
    go(page, "stewardship", "Sahiplik Matrisi")
    go(page, "roadmap", "Yol Haritası")
    expect(page.locator(".rm-phase").first).to_be_visible()
    checks.append("veri_yonetisimi")
    # KVKK (K-029): keşif → öneri kabulü → yerel örnek doğrulama (değer gönderilmez) → işleme faaliyeti → başvuru
    go(page, "privacy", "KVKK Panosu")
    page.locator("#topActions button", has_text="Keşfi çalıştır").click()
    expect(page.locator("#toast")).to_contain_text("kolon tarandı")
    go(page, "discovery", "Kişisel Veri Keşfi")
    expect(page.locator("#content tr", has_text="STCD1").first).to_be_visible()
    page.locator("#content tr", has_text="STCD1").first.locator("button", has_text="Kabul").click()
    expect(page.locator("#toast")).to_contain_text("Kabul edildi")
    sample = Path(tempfile.mkdtemp()) / "ornek.csv"
    sample.write_text("KUNNR;STCD1\n" + "".join(f"000{i:07d};10000000146\n" for i in range(12)), encoding="utf-8")
    go(page, "catalog", "Veri Kataloğu")
    page.locator("#content tr", has_text="KNA1").click()
    page.locator(".pv-panel button", has_text="Örnek veriyle doğrula").click()
    page.locator("#smpFile").set_input_files(str(sample))
    expect(page.locator("#modal")).to_contain_text("yalnızca aşağıdaki sayılar")
    page.locator("#modal button", has_text="Sayıları gönder").click()
    expect(page.locator("#toast")).to_contain_text("öneri")
    go(page, "privacy", "KVKK Panosu")
    page.locator("#topActions button", has_text="+ İşleme faaliyeti").click()
    expect(page.locator("#detailTitle")).to_contain_text("İşleme Faaliyetleri")
    page.locator('#detail [name="name"]').fill("Müşteri ilişkileri yönetimi")
    page.locator('#detail [name="purpose"]').fill("Sözleşme ilişkisinin yürütülmesi")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#pageTitle")).to_have_text("Müşteri ilişkileri yönetimi")
    expect(page.locator("#content")).to_contain_text("Envanter eksikleri")
    page.screenshot(path=str(out / "09-isleme-faaliyeti.png"), full_page=True)
    go(page, "r/subject_requests", "İlgili Kişi Başvuruları")
    page.locator("#topActions button", has_text="+ Yeni").click()
    expect(page.locator("#detailTitle")).to_have_text("Yeni ilgili kişi başvurusu")
    page.locator('#detail [name="request_type"]').select_option("access")
    page.locator('#detail [name="description"]').fill("Hangi verilerimin işlendiğini öğrenmek istiyorum")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#detail .countdown")).to_contain_text("30 gün kaldı")
    page.keyboard.press("Escape")
    for key, title in (("r/data_requests", "Veri Talepleri"), ("r/dpias", "Veri Koruma Etki Değerlendirmeleri"),
                       ("r/retention_rules", "Saklama ve İmha Kuralları"), ("r/disposal_runs", "Periyodik İmha")):
        go(page, key, title)
    checks.append("kvkk")
    # Otomatik toplama (K-030): toplayıcı ekle → anahtar bir kez görünür → gerçek toplayıcı HTTP ile gönderir → "Çalışıyor"
    go(page, "r/data_sources", "Veri Kaynakları")
    page.locator("[data-row]", has_text="SAP S/4HANA Test").click()
    expect(page.locator("#pageTitle")).to_have_text("SAP S/4HANA Test")
    page.locator(".tab", has_text="Otomatik toplama").click()
    page.locator("#content button", has_text="+ Toplayıcı ekle").click()
    page.locator("#modal input[name=tplConnector][value=files]").check()
    page.locator("#modalFooter button", has_text="Oluştur ve anahtarı göster").click()
    expect(page.locator("#modal")).to_contain_text("yalnızca şimdi gösteriliyor")
    key = page.locator("#tplKey").input_value()
    page.locator("#modalFooter button", has_text="Anahtarı kaydettim").click()
    expect(page.locator("#content")).to_contain_text("İlk gönderim bekleniyor")
    folder = Path(tempfile.mkdtemp())
    (folder / "kampanya_listesi.csv").write_text("katilimci_no;eposta;sehir\n1;kisi1@ornek.test;Ankara\n", encoding="utf-8")
    config = folder.parent / f"{folder.name}.json"
    config.write_text(json.dumps({"platform": base, "connector": "files", "settings": {"path": str(folder), "schema": "paylasim"}}),
                      encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "tedarik.collector", "gonder", "--ayar", str(config)], cwd=ROOT, timeout=120,
                         env={**os.environ, "TEDARIK_COLLECTOR_KEY": key}, capture_output=True, text=True)
    if run.returncode:
        raise SystemExit("Toplayıcı gönderemedi: " + run.stderr)
    page.reload()
    expect(page.locator("#content")).to_contain_text("Çalışıyor")
    expect(page.locator("#content")).to_contain_text("1 tablo, 3 kolon")
    page.screenshot(path=str(out / "09b-toplayici.png"), full_page=True)
    go(page, "collectors", "Toplayıcılar")
    checks.append("otomatik_toplama")
    # Soy kütüğü (K-031): bağlantı ekle → etki analizi → akış şeması
    go(page, "lineage", "Soy Kütüğü")
    expect(page.locator("#content")).to_contain_text("Soy kütüğünü üç yoldan kurun")
    page.locator("#topActions button", has_text="+ Bağlantı").click()
    page.locator("#lnSrc").fill("KNA1")
    page.locator("#modal .pick-results li", has_text="KNA1").first.click()
    expect(page.locator("#lnSrcCol")).to_be_enabled()
    page.locator("#lnSrcCol").select_option(label="KUNNR")
    page.locator("#lnDst").fill("kampanya")
    page.locator("#modal .pick-results li", has_text="kampanya_listesi").first.click()
    expect(page.locator("#lnDstCol")).to_be_enabled()
    page.locator("#lnDstCol").select_option(label="katilimci_no")
    page.locator("#lnKind").select_option("transform")
    page.locator("#lnTr").fill("Müşteri numarası katılımcı numarasına eşlenir")
    page.locator("#modalFooter button", has_text="Ekle").click()
    expect(page.locator("#toast")).to_contain_text("Bağlantı eklendi")
    expect(page.locator("#content")).to_contain_text("katilimci_no")
    page.locator("#content li", has_text="etki analizi").first.click()
    expect(page.locator("#pageTitle")).to_contain_text("Etki analizi")
    expect(page.locator("#content")).to_contain_text("kampanya_listesi")
    page.locator("#topActions button", has_text="Akış şeması").click()
    expect(page.locator("svg.flow .flow-node")).to_have_count(2)
    page.locator("svg.flow .flow-node").last.click()
    expect(page.locator(".flow-detail")).to_contain_text("Tabloya git")
    page.screenshot(path=str(out / "09c-akis-semasi.png"), full_page=True)
    checks.append("soy_kutugu")
    # Veri kalitesi (K-032): kural ekle → SQL → sonuç gir → bulgu ve DÖF
    go(page, "quality", "Veri Kalitesi")
    expect(page.locator("#content")).to_contain_text("Veri kalitesini üç adımda")
    page.locator("#topActions button", has_text="+ Kural").click()
    page.locator("#dqTable").fill("KNA1")
    page.locator("#modal .pick-results li", has_text="KNA1").first.click()
    expect(page.locator("#dqTableCol")).to_be_enabled()
    page.locator("#dqTableCol").select_option(label="KUNNR")
    page.locator("#dqKind").select_option("not_null")
    page.locator("#modalFooter button", has_text="Ekle").click()
    expect(page.locator("#pageTitle")).to_have_text("KUNNR boş olmamalı")
    expect(page.locator("#content")).to_contain_text("IS NULL")
    page.locator("#topActions button", has_text="Sonuç gir").click()
    page.locator("#dqChecked").fill("100")
    page.locator("#dqFailed").fill("3")
    page.locator("#modalFooter button", has_text="Kaydet").click()
    expect(page.locator("#toast")).to_contain_text("bulgu ve DÖF açıldı")
    expect(page.locator("#content")).to_contain_text("BLG-")
    page.screenshot(path=str(out / "09d-kalite-kurali.png"), full_page=True)
    go(page, "quality", "Veri Kalitesi")
    expect(page.locator("#content")).to_contain_text("KUNNR boş olmamalı")
    checks.append("veri_kalitesi")
    # anket kurucu
    go(page, "r/survey_templates", "Anket Şablonları")
    page.locator("[data-row]", has_text="Tedarikçi Memnuniyet").click()
    expect(page.locator("#pageTitle")).to_have_text("Tedarikçi Memnuniyet Anketi")
    page.locator("#topActions button", has_text="Önizle").click()
    page.locator("#modal .scale button", has_text="4").first.click()
    expect(page.locator("#modal .scale button.on")).to_have_count(1)
    page.locator("#modalFooter button", has_text="Kapat").click()
    page.locator("button", has_text="+ Soru ekle").click()
    page.locator("#qText").fill("Faturalama doğruluğundan memnun musunuz?")
    page.locator("#qKind").select_option("single_choice")
    rows = page.locator("#modal .option-row")
    rows.nth(0).locator("input").first.fill("Evet, her zaman")
    rows.nth(0).locator("input").nth(1).fill("100")
    rows.nth(1).locator("input").first.fill("Bazen hata oluyor")
    rows.nth(1).locator("input").nth(1).fill("30")
    page.locator("#modalFooter button", has_text="Ekle").click()
    expect(page.locator("#content")).to_contain_text("Faturalama doğruluğundan")
    page.screenshot(path=str(out / "04-anket-kurucu.png"), full_page=True)
    checks.append("anket_kurucu")
    # kampanya
    page.locator("#topActions button", has_text="Kampanya başlat").click()
    expect(page.locator("#detailTitle")).to_have_text("Yeni anket kampanyası")
    page.locator('#detail [name="name"]').fill("4. çeyrek memnuniyet")
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#pageTitle")).to_have_text("4. çeyrek memnuniyet")
    page.locator("button", has_text="Tüm kritik tedarikçiler").click()
    expect(page.locator("#toast")).to_contain_text("eklendi")
    page.locator(".tab", has_text="Davetliler").click()
    page.locator("button", has_text="+ Davet et").click()
    page.locator("#modal textarea").fill("dev")
    page.locator("#modalFooter button", has_text="Davet et").click()
    expect(page.locator("#toast")).to_contain_text("davet oluşturuldu")
    page.locator("#topActions button", has_text="Kampanyayı aç").click()
    page.locator("#modalFooter button", has_text="Aç").click()
    expect(page.locator("#toast")).to_contain_text("Kampanya açıldı")
    checks.append("kampanya")
    # yanıtlama: taslak otomatik kayıt, koşul, zorunlu soru, gönderim
    go(page, "my-surveys", "Anketlerim")
    page.locator("#content button", has_text="Başla").first.click()
    expect(page.locator(".question").first).to_be_visible()
    page.locator("button", has_text="Yanıtı gönder").click()
    expect(page.locator(".question.missing").first).to_be_visible()
    for question in page.locator(".question").all():
        if question.locator(".scale button").count():
            question.locator(".scale button").nth(3).click()
        elif question.locator(".choices input").count():
            question.locator(".choices input").first.check()
    expect(page.locator(".save-state")).to_contain_text("Kaydedildi", timeout=5000)
    page.screenshot(path=str(out / "05-anket-yanit.png"), full_page=True)
    page.reload()
    expect(page.locator(".scale button.on").first).to_be_visible()      # taslak korunur
    page.locator("button", has_text="Yanıtı gönder").click()
    expect(page.locator(".thanks")).to_contain_text("Teşekkürler")
    checks.append("anket_yanit")
    page.goto(base + "/#/r/survey_campaigns")
    page.locator("[data-row]", has_text="4. çeyrek memnuniyet").click()
    expect(page.locator("#content")).to_contain_text("Genel puan")
    expect(page.locator("#content")).to_contain_text("Tedarikçi bazında")
    page.screenshot(path=str(out / "06-anket-sonuc.png"), full_page=True)
    checks.append("anket_sonuc")
    # aktarım
    go(page, "transfer", "Aktarım")
    page.locator(".type-card", has_text="Birimler").click()
    csv = Path(tempfile.mkdtemp()) / "birimler.csv"
    csv.write_text("Ad;Yönetici\r\nBilgi Teknolojileri;mehmet\r\nFinans;\r\n", encoding="utf-8-sig")   # kod sunucuda üretilir
    page.locator("#importFile").set_input_files(str(csv))
    page.locator("button", has_text="Dene (kayıt yazmaz)").click()
    expect(page.locator("#content")).to_contain_text("Deneme sonucu")
    expect(page.locator("#content")).to_contain_text("Yeni: 1")
    page.locator("button", has_text="Uygula").click()
    expect(page.locator("#content")).to_contain_text("Uygulandı")
    page.screenshot(path=str(out / "07-aktarim.png"), full_page=True)
    checks.append("aktarim")
    # dar ekran
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base + "/#/r/suppliers")
    page.locator("[data-row]").first.click()
    expect(page.locator("#detail")).to_have_class("open")
    page.wait_for_timeout(400)                  # panel açılış animasyonu
    page.screenshot(path=str(out / "08-mobil.png"), full_page=True)
    checks.append("mobil")
    return checks


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "verification")
    out.mkdir(parents=True, exist_ok=True)
    temp = tempfile.mkdtemp()
    port = free_port()
    env = {**os.environ, "TEDARIK_AUTH_MODE": "dev", "TEDARIK_DB": os.path.join(temp, "smoke.db"), "PORT": str(port),
           "TEDARIK_DEV_USER": "dev", "TEDARIK_DEV_ROLE": "ADMIN", "TEDARIK_DATABASE_URL": ""}
    server = subprocess.Popen([sys.executable, str(ROOT / "app.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/health")
                break
            except OSError:
                time.sleep(0.1)
        seed(base)
        errors = []
        with sync_playwright() as p:
            launch = {"executable_path": os.environ["PLAYWRIGHT_CHROMIUM"]} if os.environ.get("PLAYWRIGHT_CHROMIUM") else {}
            browser = p.chromium.launch(**launch)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="tr-TR")
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            checks = exercise(page, out, base, errors)
            browser.close()
        if errors:
            raise SystemExit("Tarayıcı konsol hataları:\n" + "\n".join(errors))
        print(json.dumps({"checks": checks, "screenshots": str(out)}, ensure_ascii=False, indent=1))
    finally:
        server.terminate()
        server.wait(5)


if __name__ == "__main__":
    main()
