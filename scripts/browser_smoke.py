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
    page.locator("#detail .choices label", has_text="ISO/IEC 27001").locator("input").check()
    page.locator("#detail .choices label", has_text="A.5.19").locator("input").check()
    page.locator("#detailFooter button", has_text="Oluştur").click()
    expect(page.locator("#pageTitle")).to_contain_text("Tedarikçi yönetimi iç denetimi")
    page.locator("#topActions button", has_text="Denetimi başlat").click()
    expect(page.locator("#content")).to_contain_text("Devam ediyor")
    page.locator("#content tr", has_text="Kritik sözleşmelerde denetim hakkı").locator("button", has_text="Test et").click()
    page.locator("#resStatus").select_option("pass")
    page.locator("#modalFooter button", has_text="Sonucu kaydet").click()
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
    go(page, "health", "GRC Sağlık Kontrolü")
    expect(page.locator(".check").first).to_be_visible()
    page.keyboard.press("Control+k")
    page.locator("#palette .pal-input").fill("örnek")
    expect(page.locator(".pal-list li[role=option]", has_text="Örnek Bilişim")).to_be_visible()
    page.keyboard.press("Escape")
    checks.append("grc_platform_ekranlari")
    go(page, "compliance", "Uyum Panosu")
    expect(page.locator("#content")).to_contain_text("Standartlara göre")
    page.screenshot(path=str(out / "05b-uyum-panosu.png"), full_page=True)
    checks.append("grc_uyum_panosu")
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
