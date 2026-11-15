"""Canlı kabul testi: çalışan bir kuruluma (HTTPS) gerçek kullanıcı gibi bağlanır.

    TDR_BASE=https://... TDR_ADMIN_USER=kabul.yonetici TDR_ADMIN_PASS=<geçici> TDR_MCP_KEY=<anahtar> \
        python scripts/acceptance.py cikti/

- Yönetici geçici parolayla giriş sayfasından girer, parolasını değiştirir (tarayıcıda).
- Yönetici Denetçi, Birim Kullanıcısı ve Görüntüleyici hesaplarını açar (veya geçici parola verir); her biri
  ilk girişte parolasını değiştirir. Parolalar yalnızca bellekte tutulur, hiçbir yere yazılmaz.
- Senaryolar: güvenlik başlıkları ve TLS, yetki sınırları, birim kapsamı, denetim → test → bulgu → DÖF →
  doğrulama → kapanış, iç otomatik kontrol, kanıt yükleme ve bütünlük, risk değerlendirme, MCP en az yetki ve
  tekrar koruması, CSRF ve boyut sınırı, XSS, tüm ekranların tarayıcıda hatasız açılması, dar ekran, yanıt süreleri.
- Yazılan kayıtlar "KABUL" ile işaretlidir. Test sonunda açılan test hesapları devre dışı bırakılır.
Çıktı: <klasör>/sonuc.json, <klasör>/ozet.md ve ekran görüntüleri (yalnızca sentetik demo verisi).
"""
import base64
import json
import os
import secrets
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE = os.environ["TDR_BASE"].rstrip("/")
RUN = os.environ.get("GITHUB_RUN_ID") or str(int(time.time()))
RESULTS, TIMINGS = [], []
STATE = {"page": None, "out": None}
HTTPS = BASE.startswith("https://")      # yerel prova HTTP ile yapılabilir; TLS'e özgü denetimler atlanır


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


class Client:
    def __init__(self, cookie=None, key=None):
        self.cookie, self.key = cookie, key

    def request(self, method, path, body=None, origin=BASE, raw=None, timed=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if origin and method != "GET":
            headers["Origin"] = origin
        if self.cookie:
            headers["Cookie"] = self.cookie
        if self.key:
            headers["X-API-Key"] = self.key
        url = BASE + (path if path.startswith("/") else "/api/tdr/" + path)
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        started = time.perf_counter()
        try:
            with OPENER.open(req, timeout=60) as r:
                status, raw_body, response_headers = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            status, raw_body, response_headers = e.code, e.read(), e.headers
        elapsed = (time.perf_counter() - started) * 1000
        if timed:
            TIMINGS.append({"name": timed, "ms": round(elapsed)})
        cookie = response_headers.get("Set-Cookie")
        if cookie:
            jar = SimpleCookie()
            jar.load(cookie)
            for morsel in jar.values():
                self.cookie = f"{morsel.key}={morsel.value}" if morsel.value else None
        try:
            payload = json.loads(raw_body) if raw_body and "json" in (response_headers.get("Content-Type") or "") else raw_body
        except ValueError:
            payload = raw_body
        return status, payload, response_headers

    def ok(self, method, path, body=None, expect_status=None, **kw):
        status, payload, _ = self.request(method, path, body, **kw)
        if (expect_status and status != expect_status) or (not expect_status and status >= 300):
            raise AssertionError(f"{method} {path} -> {status}: {str(payload)[:300]}")
        return payload


def check(name, fn):
    started = time.perf_counter()
    try:
        detail = fn()
        RESULTS.append({"name": name, "ok": True, "detail": detail or "", "ms": round((time.perf_counter() - started) * 1000)})
        print(f"GEÇTİ  {name}" + (f" — {detail}" if detail else ""))
    except Exception as exc:   # noqa: BLE001 — her senaryo bağımsız raporlanır
        seen = ""
        if STATE["page"] is not None:
            try:
                STATE["page"].screenshot(path=str(STATE["out"] / f"hata-{len(RESULTS) + 1:02d}.png"), full_page=True)
                seen = " | ekranda: " + " ".join(STATE["page"].locator("#main").inner_text(timeout=3000).split())[:400]
            except Exception:   # noqa: BLE001
                pass
        RESULTS.append({"name": name, "ok": False, "detail": f"{type(exc).__name__}: {exc}"[:600] + seen})
        print(f"KALDI  {name} — {RESULTS[-1]['detail'][:900]}")


def expect_status(client, method, path, status, body=None, **kw):
    got = client.request(method, path, body, **kw)[0]
    if got != status:
        raise AssertionError(f"{method} {path}: beklenen {status}, gelen {got}")


def login(username, password):
    """API ile giriş + zorunlu parola değişimi. Yeni parola yalnızca bellekte."""
    client = Client()
    status, payload, _ = client.request("POST", "/api/login", {"username": username, "password": password})
    if status != 200:
        raise AssertionError(f"{username} girişi başarısız: {status} {payload}")
    if payload.get("must_change_password"):
        new = secrets.token_urlsafe(18)
        client.ok("POST", "/api/change-password", {"current_password": password, "new_password": new})
    return client


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "kabul")
    out.mkdir(parents=True, exist_ok=True)
    host = urlparse(BASE).hostname
    anon = Client()
    ctx = {}

    # ------------------------------------------------------------ platform
    def tls():
        if not HTTPS:
            return "HTTP (yerel prova): atlandı"
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=15) as sock, context.wrap_socket(sock, server_hostname=host) as s:
            cert = s.getpeercert()
            version = s.version()
        issuer = dict(x[0] for x in cert["issuer"])
        expires = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days = (expires - datetime.now(timezone.utc)).days
        assert days > 14, f"sertifika {days} gün içinde bitiyor"
        assert version in ("TLSv1.2", "TLSv1.3"), version
        return f"{issuer.get('organizationName')} {issuer.get('commonName')}, {version}, {days} gün geçerli"
    check("TLS sertifikası ve protokol", tls)

    def headers():
        status, _, h = anon.request("GET", "/login")
        assert status == 200
        need = {"Strict-Transport-Security": "max-age=", "Content-Security-Policy": "default-src 'none'",
                "X-Content-Type-Options": "nosniff", "Referrer-Policy": ""}
        if not HTTPS:
            need.pop("Strict-Transport-Security")
        missing = [k for k, v in need.items() if v not in (h.get(k) or "") or h.get(k) is None]
        assert not missing, "eksik başlık: " + ", ".join(missing)
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
        assert "Server" not in h or "Tedarik" in h.get("Server", "") or "Caddy" in h.get("Server", ""), h.get("Server")
        return "HSTS, CSP (frame-ancestors none), nosniff, Referrer-Policy"
    check("Güvenlik başlıkları", headers)

    def anonymous():
        expect_status(anon, "GET", "suppliers", 401)
        expect_status(anon, "GET", "/api/health", 401)
        status, _, h = anon.request("GET", "/")
        assert status in (302, 303) and h.get("Location") == "/login", (status, h.get("Location"))
        expect_status(anon, "GET", "/api/tdr/evidence/1/files/1", 401)
        status, _, _ = anon.request("POST", "/api/login", {"username": "kabul.yok", "password": "x"}, origin="https://kotu.example")
        assert status == 403, status
        return "API 401, sayfa /login'e yönlenir, yabancı kökenden giriş 403"
    check("Anonim erişim kapalı", anonymous)

    # ------------------------------------------------------------ tarayıcı: yönetici girişi ve ekran turu
    pw = sync_playwright().start()
    browser = pw.chromium.launch(**({"executable_path": os.environ["PLAYWRIGHT_CHROMIUM"]} if os.environ.get("PLAYWRIGHT_CHROMIUM") else {}))
    page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="tr-TR")
    STATE.update(page=page, out=out)
    if os.environ.get("TDR_LATENCY_MS"):           # yerel prova: uzak ağ gecikmesini taklit et
        cdp = page.context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": int(os.environ["TDR_LATENCY_MS"]),
                                                     "downloadThroughput": -1, "uploadThroughput": -1})
    console = []
    dialogs = []
    page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console.append(str(e)))
    page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))

    def admin_login():
        page.goto(BASE + "/")
        expect(page).to_have_url(BASE + "/login")
        page.fill('input[name="username"]', os.environ["TDR_ADMIN_USER"])
        page.fill('input[name="password"]', "yanlis-parola-" + RUN)
        page.click("#submit")
        expect(page.locator("#message")).to_contain_text("yanlış")
        page.fill('input[name="password"]', os.environ["TDR_ADMIN_PASS"])
        page.click("#submit")
        page.wait_for_url("**/change-password")
        ctx["admin_password"] = secrets.token_urlsafe(18)
        page.fill('input[name="current_password"]', os.environ["TDR_ADMIN_PASS"])
        page.fill('input[name="new_password"]', ctx["admin_password"])
        page.click("button[type=submit]")
        expect(page.locator("#pageTitle")).to_have_text("Genel Bakış", timeout=20000)
        expect(page.locator(".metric").first).to_be_visible()
        cookie = next(c for c in page.context.cookies() if "session" in c["name"])
        assert (cookie["secure"] or not HTTPS) and cookie["httpOnly"] and cookie["sameSite"] in ("Lax", "Strict"), cookie
        ctx["admin"] = Client(f"{cookie['name']}={cookie['value']}")
        page.screenshot(path=str(out / "01-genel-bakis.png"), full_page=True)
        console.clear()                     # hatalı parola denemesinin 401'i tarayıcı konsoluna düşer (beklenen)
        return f"çerez {cookie['name']}: Secure, HttpOnly, SameSite={cookie['sameSite']}"
    check("Yönetici: hatalı parola, giriş, zorunlu parola değişimi (tarayıcı)", admin_login)
    if "admin" not in ctx:
        return finish(out, browser, pw)
    admin = ctx["admin"]

    def tour():
        slow, pages = [], 0
        keys = [b.get_attribute("data-nav") for b in page.locator("[data-nav]").all()]
        for key in keys:
            started = time.perf_counter()
            page.locator(f'[data-nav="{key}"]').click()
            expect(page.locator("#pageTitle")).not_to_have_text("Yükleniyor…")
            expect(page.locator("#content .empty", has_text="Yükleniyor")).to_have_count(0, timeout=20000)
            expect(page.locator("#pageTitle")).not_to_have_text("Bir sorun oluştu")
            expect(page.locator("#content .notice.bad")).to_have_count(0)
            ms = round((time.perf_counter() - started) * 1000)
            TIMINGS.append({"name": "ekran:" + key, "ms": ms})
            if ms > 3000:
                slow.append(f"{key} {ms} ms")
            pages += 1
        assert not console, "konsol hatası: " + "; ".join(console[:3])
        return f"{pages} ekran açıldı" + (f"; yavaş: {', '.join(slow)}" if slow else "")
    check("Tüm menü ekranları hatasız açılıyor (tarayıcı)", tour)

    def open_list(route, title):
        page.goto(BASE + "/#/" + route)
        expect(page.locator("#pageTitle")).to_have_text(title, timeout=20000)
        expect(page.locator("#content .empty", has_text="Yükleniyor")).to_have_count(0, timeout=20000)
        expect(page.locator("[data-row]").first).to_be_visible(timeout=20000)

    def ui_journeys():
        open_list("r/suppliers", "Tedarikçiler")
        critical = admin.ok("GET", "suppliers?tier=critical&status=active&limit=1")[0]   # kodlar sürüme göre değişir; adla ara
        page.locator("#tableSearch").fill(critical["name"])
        expect(page.locator("[data-row]")).to_have_count(1, timeout=15000)
        page.locator("[data-row]").first.click()
        expect(page.locator("#detailKicker")).to_contain_text("Tedarikçi 360")
        for tab in ("Angajmanlar", "Riskler", "Anketler", "Sözleşmeler", "Özet"):
            page.locator("#detail .tab", has_text=tab).click()
        page.screenshot(path=str(out / "02-tedarikci-360.png"), full_page=True)
        page.keyboard.press("Escape")
        page.goto(BASE + "/#/compliance")
        expect(page.locator("#content")).to_contain_text("Standartlara göre", timeout=20000)
        page.screenshot(path=str(out / "03-uyum-panosu.png"), full_page=True)
        open_list("r/audits", "Denetimler")
        page.locator("[data-row]", has_text="20000-1").first.click()
        expect(page.locator("#content")).to_contain_text("Bu denetimdeki sonuç", timeout=20000)
        page.screenshot(path=str(out / "04-denetim.png"), full_page=True)
        open_list("r/controls", "Kontroller")
        page.locator("[data-row]", has_text="Kritik tedarikçi performans değerlendirmeleri zamanında").click()
        expect(page.locator("#detailKicker")).to_have_text("Kontrol")
        page.locator("#detail .tab", has_text="Sonuçlar").click()
        page.locator("#detail tbody tr").first.click()
        expect(page.locator("#modal")).to_contain_text("Kaynak bilgisi")
        page.screenshot(path=str(out / "05-kontrol-sonucu.png"), full_page=True)
        page.keyboard.press("Escape")
        open_list("r/survey_campaigns", "Anket Kampanyaları")
        page.locator("[data-row]", has_text="ilk yarı").click()
        expect(page.locator("#content")).to_contain_text("Genel puan", timeout=20000)
        page.screenshot(path=str(out / "06-anket-sonuc.png"), full_page=True)
        # GRC platformu: risk panosu, süreklilik, CMDB, takvim, sağlık, süreç ve ilişki haritası, komut paleti
        page.goto(BASE + "/#/risk")
        expect(page.locator("#content .heat")).to_be_visible(timeout=20000)
        page.screenshot(path=str(out / "06b-risk-panosu.png"), full_page=True)
        open_list("r/bias", "İş Etki Analizleri")
        page.locator("[data-row]").first.click()
        page.locator("#detail .tab", has_text="Etki matrisi").click()
        expect(page.locator("#detail .matrix")).to_be_visible()
        page.screenshot(path=str(out / "06c-bia.png"), full_page=True)
        page.keyboard.press("Escape")
        page.goto(BASE + "/#/cmdb")
        expect(page.locator("#content .rule-row").first).to_be_visible(timeout=20000)
        page.goto(BASE + "/#/process-map")
        expect(page.locator(".band.core .proc").first).to_be_visible(timeout=20000)
        page.screenshot(path=str(out / "06d-surec-haritasi.png"), full_page=True)
        page.goto(BASE + "/#/calendar")
        expect(page.locator(".cal .ev").first).to_be_visible(timeout=20000)
        page.goto(BASE + "/#/archive?q=A.5.19")                    # denetim arşivi: madde koduyla geçmiş denetim ve kanıt
        expect(page.locator(".archive-audit").first).to_be_visible(timeout=20000)
        page.screenshot(path=str(out / "06e-denetim-arsivi.png"), full_page=True)
        page.goto(BASE + "/#/home")
        expect(page.locator(".hero")).to_be_visible(timeout=20000)
        page.keyboard.press("Control+k")
        page.locator("#palette .pal-input").fill("risk")
        expect(page.locator(".pal-list li[role=option]").first).to_be_visible()
        page.keyboard.press("Escape")
        assert not console, "; ".join(console[:3])
        return "tedarikçi 360, uyum panosu, denetim, kontrol sonucu, anket sonucu, risk panosu, BİA, CMDB, süreç haritası, takvim, arşiv, palet"
    check("Ana ekran akışları (tarayıcı)", ui_journeys)

    # ------------------------------------------------------------ hesaplar
    def accounts():
        names = {"BTA": "BT Altyapı ve Operasyon", "OPS": "Operasyon"}          # birimler adla bulunur (kodlar sunucuda üretilir)
        by_name = {u["name"]: u["id"] for u in admin.ok("GET", "org_units?limit=100")}
        units = {key: by_name[name] for key, name in names.items()}
        ctx["units"] = units
        users = {u["username"]: u for u in admin.ok("GET", "users")}
        for name, role, unit in (("kabul.denetci", "AUDITOR", None), ("kabul.birim", "UNIT_USER", "BTA"),
                                 ("kabul.izleyici", "VIEWER", None)):
            if name in users:
                admin.ok("PATCH", f"users/{users[name]['id']}", {"is_active": 1, "role": role,
                                                                 "org_unit_ids": [units[unit]] if unit else []})
                reply = admin.ok("POST", f"users/{users[name]['id']}/reset-password", {})
            else:
                reply = admin.ok("POST", "users", {"username": name, "display_name": f"Kabul {role.title()}", "role": role,
                                                   "org_unit_ids": [units[unit]] if unit else []})
            ctx[name] = login(name, reply["temporary_password"])
            ctx[name + ".id"] = reply["id"]
            status, _, _ = Client().request("POST", "/api/login", {"username": name, "password": reply["temporary_password"] + "x"})
            assert status == 401
        return "Denetçi, Birim Kullanıcısı (BTA), Görüntüleyici: açıldı/sıfırlandı, ilk girişte parola değişti"
    check("Yönetici kullanıcı açar; geçici parola ve zorunlu değişim", accounts)
    auditor, unit_user, viewer = ctx.get("kabul.denetci"), ctx.get("kabul.birim"), ctx.get("kabul.izleyici")

    def must_change_enforced():
        temp = admin.ok("POST", f"users/{ctx['kabul.izleyici.id']}/reset-password", {})
        fresh = Client()
        fresh.ok("POST", "/api/login", {"username": "kabul.izleyici", "password": temp["temporary_password"]})
        expect_status(fresh, "GET", "suppliers", 403)
        expect_status(viewer, "GET", "suppliers", 401)              # sıfırlama açık oturumu kapattı
        ctx["kabul.izleyici"] = login("kabul.izleyici", temp["temporary_password"])
        return "parola değişmeden veri erişimi 403; sıfırlama eski oturumu kapatır"
    check("Zorunlu parola değişimi ve oturum iptali", must_change_enforced)
    viewer = ctx.get("kabul.izleyici")

    def viewer_limits():
        assert len(viewer.ok("GET", "suppliers?limit=1000")) >= 45
        expect_status(viewer, "POST", "suppliers", 403, {"name": "KABUL-X"})
        expect_status(viewer, "POST", "executions", 403, {"control_id": 1, "status": "pass"})
        expect_status(viewer, "GET", "users", 403)
        expect_status(viewer, "GET", "audit_log", 403)
        meta = viewer.ok("GET", "metadata")
        assert not meta["resources"]["suppliers"]["can_write"] and not meta["permissions"]["write"]
        restricted = [e for e in admin.ok("GET", "evidence?confidentiality=restricted&limit=200")]
        assert not viewer.ok("GET", "evidence?confidentiality=restricted&limit=200")       # kısıtlı kanıt görünmez
        for e in restricted[:2]:
            expect_status(viewer, "GET", f"evidence/{e['id']}", 404)
            expect_status(viewer, "GET", f"evidence/{e['id']}/files/1", 404)
        return f"okur; tedarikçi, sonuç, kullanıcı ve iz yazamaz/göremez; {len(restricted)} kısıtlı kanıtı göremez"
    check("Görüntüleyici yetki sınırları", viewer_limits)

    def unit_scope():
        bta, ops = ctx["units"]["BTA"], ctx["units"]["OPS"]
        own = unit_user.ok("GET", f"engagements?org_unit_id={bta}&limit=1")[0]
        other = unit_user.ok("GET", f"engagements?org_unit_id={ops}&limit=1")[0]
        unit_user.ok("PATCH", f"engagements/{own['id']}", {"description": (own["description"] or "") [:200] + " [KABUL]"})
        expect_status(unit_user, "PATCH", f"engagements/{other['id']}", 403, {"description": "KABUL"})
        expect_status(unit_user, "PATCH", f"engagements/{own['id']}", 403, {"org_unit_id": ops})
        body = {"title": f"KABUL erişim listesi {RUN}", "file_name": "erisim.csv", "content_base64": base64.b64encode(b"kullanici,yetki\nkabul,okur\n").decode()}
        expect_status(unit_user, "POST", "evidence/upload", 403, {**body, "org_unit_id": ops})
        created = unit_user.ok("POST", "evidence/upload", {**body, "org_unit_id": bta})
        ctx["evidence"] = created
        expect_status(unit_user, "POST", "controls", 403, {"name": "KABUL-C"})
        return f"kendi birimine yazar, başka birime 403; kanıt {created['code'] if 'code' in created else created['id']} yüklendi"
    check("Birim kullanıcısı kapsamı (angajman, kanıt)", unit_scope)

    def evidence_integrity():
        ev = ctx["evidence"]
        status, raw, h = admin.request("GET", f"evidence/{ev['id']}/files/1")
        assert status == 200 and raw == b"kullanici,yetki\nkabul,okur\n", status
        assert "attachment" in (h.get("Content-Disposition") or "")
        assert h.get("Content-Type", "").startswith("application/octet-stream")
        bad = {"title": "KABUL sahte pdf", "file_name": "x.pdf", "content_base64": base64.b64encode(b"MZ-not-pdf").decode(),
               "org_unit_id": ctx["units"]["BTA"]}
        expect_status(unit_user, "POST", "evidence/upload", 400, bad)
        return "indirilen içerik birebir, ek olarak iner (octet-stream); imzası tutmayan PDF reddedilir"
    check("Kanıt dosyası bütünlüğü ve dosya türü denetimi", evidence_integrity)

    # ------------------------------------------------------------ denetim → test → bulgu → DÖF → doğrulama
    def audit_flow():
        audits = auditor.ok("GET", "audits?limit=100")
        audit = next(a for a in audits if a["status"] == "in_progress")
        context = auditor.ok("GET", f"audits/{audit['id']}/context", timed="denetim bağlamı")
        manual = [c for c in context["controls"] if c["planned"] and c["execution_mode"] == "manual" and c["active"] and not c["automation"]]
        control = next((c for c in manual if c["result"] == "untested"), manual[0])
        expect_status(auditor, "POST", "executions", 400, {"control_id": control["id"], "audit_id": audit["id"], "status": "fail"})
        result = auditor.ok("POST", "executions", {"control_id": control["id"], "audit_id": audit["id"], "status": "fail",
                                                   "details": f"KABUL {RUN}: 25 kayıtlık örneklemde 2 istisna",
                                                   "sample_size": 25, "exceptions": 2, "severity": "high",
                                                   "evidence_ids": [ctx["evidence"]["id"]]})
        assert result["finding_id"], result
        run = auditor.ok("GET", f"executions/{result['execution_id']}/context")
        assert run["definition"]["code"] == control["code"] and run["evidence"][0]["sha256"] == ctx["evidence"]["sha256"]
        ctx["finding"], ctx["control"] = result["finding_id"], control
        after = auditor.ok("GET", f"audits/{audit['id']}/context")
        assert any(f["id"] == result["finding_id"] for f in after["findings"])
        expect_status(auditor, "POST", "controls", 403, {"name": "KABUL-C"})
        return f"{audit['code']} / {control['code']}: başarısız sonuç → bulgu {result['finding_id']}; tanım ve kanıt özeti donduruldu"
    check("Denetçi: denetimde test, bulgu, dondurulmuş tanım", audit_flow)

    def capa_flow():
        finding = ctx["finding"]
        action = auditor.ok("POST", "grc_actions", {"title": f"KABUL düzeltici faaliyet {RUN}", "finding_id": finding,
                                                    "owner": "kabul.birim", "org_unit_id": ctx["units"]["BTA"],
                                                    "due_date": date.today().replace(day=28).isoformat()})["id"]
        expect_status(auditor, "PATCH", f"findings/{finding}", 409, {"status": "closed", "closure_note": "erken"})
        expect_status(unit_user, "PATCH", f"grc_actions/{action}", 409, {"status": "completed"})
        unit_user.ok("PATCH", f"grc_actions/{action}", {"status": "validation", "resolution": "Örneklemdeki 2 kayıt düzeltildi"})
        expect_status(unit_user, "PATCH", f"grc_actions/{action}", 403, {"status": "completed", "verification_note": "kendim"})
        done = auditor.ok("PATCH", f"grc_actions/{action}", {"status": "completed", "verification_note": "Yeniden test: istisna yok"})
        assert done["verified_by"] == "kabul.denetci"
        closed = auditor.ok("PATCH", f"findings/{finding}", {"status": "closed", "closure_note": "DÖF etkinliği doğrulandı (kabul testi)"})
        assert closed["status"] == "closed" and closed["closed_at"]
        expect_status(auditor, "PATCH", f"findings/{finding}", 403, {"status": "accepted", "closure_note": "x"})
        return "açık DÖF ile kapanmaz → sahibi doğrulamaya gönderir → kendisi doğrulayamaz → denetçi doğrular → bulgu kapanır"
    check("DÖF: görevler ayrılığı ve bulgu kapanışı", capa_flow)

    def automation():
        control = next(c for c in auditor.ok("GET", "controls?limit=200") if c["automation"] == "supplier.owner")
        result = auditor.ok("POST", f"controls/{control['id']}/run", {})
        run = auditor.ok("GET", f"executions/{result['execution_id']}/context")
        assert run["source"] == "system" and run["provenance"]["collection_status"] == "complete"
        assert len(run["provenance"]["result_sha256"]) == 64
        return f"{run['status']}; {run['provenance']['checked']} kayıt denetlendi, {run['provenance']['exceptions']} istisna"
    check("İç otomatik kontrol portal verisinden çalışır", automation)

    def compliance():
        data = admin.ok("GET", "grc/overview", timed="GRC genel bakış")
        assert len(data["standards"]) >= 3 and data["controls"]["total_controls"] >= 30
        iso = next(s for s in data["standards"] if s["code"] == "ISO/IEC 27001")
        detail = admin.ok("GET", f"grc/compliance?standard_id={iso['id']}", timed="uyum göstergesi")
        assert detail["framework_coverage_pct"] is not None and "sertifikasyon" in detail["disclaimer"]
        expect_status(admin, "GET", "grc/compliance?standard_id=abc", 400)
        return (f"{data['controls']['total_controls']} kontrol, başarı %{data['controls']['pass_pct']}, "
                f"ISO 27001 madde kapsaması %{detail['framework_coverage_pct']}")
    check("Uyum göstergesi", compliance)

    def risk():
        units = admin.ok("GET", "risk_catalog?limit=50")
        template = units[0]
        risk_id = admin.ok("POST", "supplier_risks", {
            "title": f"KABUL <img src=x onerror=alert(1)> {template['title']}", "category": template["category"],
            "entity_name": "Kabul testi hizmeti", "catalog_id": template["id"], "cause": template["cause"],
            "risk_event": template["risk_event"], "consequence": template["consequence"], "likelihood": 4, "impact": 4,
            "appetite": 8, "owner": "kabul.denetci", "review_date": date.today().replace(year=date.today().year + 1).isoformat()})["id"]
        result = admin.ok("POST", f"supplier_risks/{risk_id}/assessments", {"rationale": "Kabul testi değerlendirmesi",
                          "mitigations": [{"title": "Kontrol", "weight": "high"}, {"title": "Prosedür", "weight": "low", "effectiveness": "partial"}]})
        assert abs(result["residual"] - 16 * (1 - 0.7)) < 0.01, result
        ctx["risk_id"] = risk_id
        return f"katalogdan kurumsal risk; içsel 16 → artık {result['residual']:.1f} (iştah 8)"
    check("Risk kaydı: katalogdan kurumsal risk ve değerlendirme", risk)

    def xss():
        page.goto(BASE + f"/#/r/supplier_risks/{ctx['risk_id']}")
        expect(page.locator("#detailTitle")).to_contain_text("<img src=x onerror=alert(1)>", timeout=20000)
        page.wait_for_timeout(800)
        assert not dialogs, dialogs
        assert page.locator("#detail img").count() == 0
        return "HTML olarak yorumlanmadı, betik çalışmadı"
    check("XSS: kullanıcı verisi metin olarak gösterilir (tarayıcı)", xss)

    # ------------------------------------------------------------ istek güvenliği
    def request_security():
        expect_status(admin, "POST", "org_units", 403, {"name": "KABUL"}, origin="https://kotu.example")
        expect_status(admin, "POST", "org_units", 403, {"name": "KABUL"}, origin=None)
        expect_status(admin, "POST", "supplier_risks", 400, {"idempotency_key": "kisa", "code": "x"})
        status = admin.request("POST", "org_units", raw=b'{"name":"' + b"A" * (3 * 1024 * 1024) + b'"}')[0]
        assert status == 413, status
        status, payload, _ = admin.request("GET", "suppliers?limit=abc")
        assert status in (200, 400), status
        status, payload, _ = admin.request("GET", "/api/tdr/../../etc/passwd")
        assert status in (400, 404), status
        return "yabancı veya eksik Origin 403, hatalı işlem anahtarı 400, 3 MB gövde 413, yol geçişi yok"
    check("CSRF, işlem anahtarı, gövde sınırı", request_security)

    def rate_limit():
        probe = Client()
        codes = [probe.request("POST", "/api/login", {"username": f"kabul.yok.{RUN}", "password": "x"})[0] for _ in range(9)]
        assert codes[:8] == [401] * 8 and codes[8] == 429, codes
        status = Client().request("POST", "/api/login", {"username": "kabul.denetci", "password": "yanlis"})[0]
        assert status == 401, status       # başka kullanıcı etkilenmez
        return "8 hatalı denemeden sonra 429; diğer hesaplar etkilenmez"
    check("Giriş hız sınırı (vekil arkasında istemci adresiyle)", rate_limit)

    # ------------------------------------------------------------ MCP
    def mcp():
        key = os.environ.get("TDR_MCP_KEY")
        if not key:
            return "MCP anahtarı verilmedi; atlandı"
        m = Client(key=key)
        expect_status(m, "GET", "/api/health", 200)
        expect_status(m, "GET", "users", 403)
        expect_status(m, "POST", "suppliers", 403, {"name": "KABUL-M"})
        expect_status(m, "GET", "export/suppliers?format=xlsx", 403)
        expect_status(Client(key="yanlis" * 8), "GET", "suppliers", 401)
        sla = m.ok("GET", "sla_definitions?active=1&limit=1")[0]
        period = date.today().replace(day=1).isoformat()
        body = {"sla_id": sla["id"], "period_start": period, "actual_value": 99.71, "source": "mcp",
                "note": "kabul testi", "idempotency_key": f"kabul-sla-{sla['id']}-{period}"}
        status, first, _ = m.request("POST", "sla_measurements", body)
        assert status in (200, 201), (status, first)
        status, again, _ = m.request("POST", "sla_measurements", body)
        assert status == 200 and again.get("replayed"), (status, again)
        assert m.request("POST", "sla_measurements", {**body, "actual_value": 50})[0] == 409
        controls = m.ok("GET", "controls?execution_mode=automatic&limit=200")
        auto = next(c for c in controls if not c["automation"] and c["active"])     # dış (MCP) otomatik kontrol
        manual = next(c for c in m.ok("GET", "controls?execution_mode=manual&limit=200"))
        assert m.request("POST", "executions", {"control_id": manual["id"], "status": "pass", "source": "mcp"})[0] == 403
        assert m.request("POST", "executions", {"control_id": auto["id"], "status": "pass", "source": "mcp",
                                                "provenance": {"collection_status": "partial"}})[0] == 400
        result = m.ok("POST", "executions", {"control_id": auto["id"], "status": "pass", "source": "mcp",
                                            "details": "kabul testi", "provenance": {"collection_status": "complete", "query": "kabul:v1"},
                                            "idempotency_key": f"kabul-exec-{RUN}"})
        replay = m.ok("POST", "executions", {"control_id": auto["id"], "status": "pass", "source": "mcp",
                                            "details": "kabul testi", "provenance": {"collection_status": "complete", "query": "kabul:v1"},
                                            "idempotency_key": f"kabul-exec-{RUN}"})
        assert replay["execution_id"] == result["execution_id"] and replay["replayed"]
        assert m.request("GET", f"evidence/{ctx['evidence']['id']}/files/1")[0] == 403
        return "en az yetki; SLA ölçümü ve otomatik kontrol sonucu yazar, tekrar korumalı; manuel kontrole ve dosyaya erişemez"
    check("MCP anahtarı: en az yetki ve tekrar koruması", mcp)

    # ------------------------------------------------------------ yanıt süreleri ve dar ekran
    def performance():
        for name, path in (("genel bakış özeti", "dashboard/summary"), ("takvim", "schedule"),
                           ("tedarikçi listesi", "suppliers?limit=1000"), ("tedarikçi 360", "suppliers/1/context"),
                           ("SLA ölçümleri", "sla_measurements?limit=1000"), ("risk kaydı", "supplier_risks?limit=1000"),
                           ("bulgular", "findings?limit=1000"), ("kontroller", "controls?limit=1000")):
            for _ in range(3):
                admin.ok("GET", path, timed=name)
        worst = {}
        for t in TIMINGS:
            if not t["name"].startswith("ekran:"):
                worst[t["name"]] = max(worst.get(t["name"], 0), t["ms"])
        slow = {k: v for k, v in worst.items() if v > 1500}
        assert not slow, slow
        return "en yavaş: " + ", ".join(f"{k} {v} ms" for k, v in sorted(worst.items(), key=lambda x: -x[1])[:4])
    check("Yanıt süreleri (uzak istemciden, 1,5 sn sınırı)", performance)

    def mobile():
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(BASE + "/#/compliance")
        expect(page.locator("#content")).to_contain_text("Standartlara göre", timeout=20000)
        page.wait_for_timeout(800)
        width = page.evaluate("document.documentElement.scrollWidth")
        page.screenshot(path=str(out / "07-mobil-uyum.png"), full_page=True)
        open_list("r/suppliers", "Tedarikçiler")
        page.locator("[data-row]").first.click()
        page.wait_for_timeout(500)
        page.screenshot(path=str(out / "08-mobil-tedarikci.png"), full_page=True)
        if width > 400:
            page.goto(BASE + "/#/compliance")
            page.wait_for_timeout(1500)
            offenders = page.evaluate("""() => [...document.querySelectorAll('#main *')].filter(el => {
                const r = el.getBoundingClientRect(), p = el.parentElement && el.parentElement.getBoundingClientRect();
                return r.width > 0 && r.right > 392 && (!p || p.right <= 392); }).slice(0, 6).map(el =>
                el.tagName + '.' + el.className + ' ' + Math.round(el.getBoundingClientRect().right))""")
            raise AssertionError(f"yatay taşma: {width}px; {offenders}")
        return f"390 px genişlikte yatay taşma yok ({width}px)"
    check("Dar ekran (telefon)", mobile)

    def cleanup():
        for name in ("kabul.denetci", "kabul.birim", "kabul.izleyici"):
            if ctx.get(name + ".id"):
                admin.ok("PATCH", f"users/{ctx[name + '.id']}", {"is_active": 0})
        expect_status(ctx["kabul.denetci"], "GET", "suppliers", 401)
        return "test hesapları devre dışı; oturumları kapandı"
    check("Temizlik: test hesapları devre dışı", cleanup)
    finish(out, browser, pw)


def finish(out, browser, pw):
    browser.close()
    pw.stop()
    passed = sum(r["ok"] for r in RESULTS)
    summary = {"base": BASE, "run": RUN, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "passed": passed, "failed": len(RESULTS) - passed, "results": RESULTS, "timings": TIMINGS}
    (out / "sonuc.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [f"# Kabul testi — {BASE}", "", f"{passed}/{len(RESULTS)} senaryo geçti ({summary['at']})", "",
             "| Sonuç | Senaryo | Ayrıntı |", "| --- | --- | --- |"]
    lines += [f"| {'✅' if r['ok'] else '❌'} | {r['name']} | {str(r['detail']).replace('|', '/')} |" for r in RESULTS]
    (out / "ozet.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    print(f"\n{passed}/{len(RESULTS)} senaryo geçti")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
