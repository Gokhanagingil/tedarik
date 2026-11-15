"""Arayüz kabuğu ve statik dosyalar: beyaz kenar menü (daraltılabilir gruplar), üst çubukta arama (Ctrl+K), ortada
liste veya pano, sağda boyutlandırılabilir detay paneli. Betik ve stil ayrı dosyadır; içerik
güvenlik politikası dış kaynağa ve satır içi betiğe izin vermez (K-010).
"""
from pathlib import Path

from .http import Raw

STATIC = Path(__file__).parent / "static"
TYPES = {"app.js": "application/javascript; charset=utf-8", "pages.js": "application/javascript; charset=utf-8",
         "grc.js": "application/javascript; charset=utf-8", "admin.js": "application/javascript; charset=utf-8",
         "assurance.js": "application/javascript; charset=utf-8",
         "app.css": "text/css; charset=utf-8"}

SHELL = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="GRC platformu: kurumsal risk, uyum ve denetim, iş sürekliliği, doküman ve tedarikçi yönetimi">
<title>GRC Platformu</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/static/app.css"></head>
<body>
<a class="skip" href="#content">İçeriğe geç</a>
<aside id="sidebar" aria-label="Ana menü">
 <div class="brand"><span class="mark" aria-hidden="true"><svg viewBox="0 0 24 24" class="icon"><path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z"/><path d="M9 12l2 2 4-4"/></svg></span>
  <span><span id="brandName">GRC Platformu</span><small>Risk · Uyum · Süreklilik</small></span></div>
 <nav id="nav"></nav>
 <div class="nav-bottom"><span class="avatar" id="avatar" aria-hidden="true"></span><div id="identity"></div>
  <button id="signout" type="button" title="Oturumu kapat">Çıkış</button></div>
</aside>
<main id="main">
 <div id="topbar"><button id="menuToggle" type="button" aria-label="Menüyü aç"><svg viewBox="0 0 24 24" class="icon"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>
  <div id="crumbs"></div>
  <button id="searchOpen" type="button" aria-label="Ara (Ctrl+K)"><svg viewBox="0 0 24 24" class="icon"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg><span>Kayıt veya sayfa ara…</span><kbd>Ctrl K</kbd></button></div>
 <header id="topline"><div><h1 id="pageTitle">Yükleniyor…</h1><div id="pageSub"></div></div><div id="topActions"></div></header>
 <div id="content" tabindex="-1" aria-live="polite"><div class="panel skeleton">İçerik hazırlanıyor…</div></div>
</main>
<aside id="detail" aria-label="Kayıt ayrıntısı" aria-hidden="true" inert>
 <div id="detailResize" role="separator" tabindex="0" aria-orientation="vertical" aria-label="Panel genişliği"
  title="Sürükleyerek genişliği değiştirin; çift tıklama varsayılana döndürür"></div>
 <header class="detail-head"><div><div id="detailKicker"></div><h2 id="detailTitle">Kayıt</h2></div>
  <button class="btn secondary small" id="closeDetail" type="button" aria-label="Paneli kapat">Kapat ✕</button></header>
 <div id="detailContent" class="detail-content"></div>
 <footer id="detailFooter" class="detail-footer"></footer>
</aside>
<div id="modalBack" class="hidden"><div id="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
 <header><h2 id="modalTitle"></h2><button type="button" class="btn ghost" id="modalClose" aria-label="Kapat">✕</button></header>
 <div id="modalBody"></div><footer id="modalFooter"></footer></div></div>
<div id="toast" role="status" aria-live="assertive"></div>
<script src="/static/app.js" defer></script>
<script src="/static/pages.js" defer></script>
<script src="/static/grc.js" defer></script>
<script src="/static/admin.js" defer></script>
<script src="/static/assurance.js" defer></script>
</body></html>"""


def shell(c):
    return 200, Raw(SHELL, "text/html; charset=utf-8")


def static(name):
    def serve(c):
        return 200, Raw((STATIC / name).read_text("utf-8"), TYPES[name])
    return serve


def register(app):
    for name in TYPES:
        app.route("GET", "/static/" + name, static(name))
