"""Arayüz kabuğu ve statik dosyalar. Görsel dil KS GRC `ui_v2.py` + `ksgrc.js` düzeniyle aynıdır: koyu kenar
menü, ortada aranabilir liste, sağda boyutlandırılabilir detay paneli. Betik ve stil ayrı dosyadır; içerik
güvenlik politikası dış kaynağa ve satır içi betiğe izin vermez (K-010).
"""
from pathlib import Path

from .http import Raw

STATIC = Path(__file__).parent / "static"
TYPES = {"app.js": "application/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8"}

SHELL = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Tedarik Portalı: tedarikçi, angajman, performans, risk ve anket yönetimi">
<title>Tedarik Portalı</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/static/app.css"></head>
<body>
<a class="skip" href="#content">İçeriğe geç</a>
<aside id="sidebar" aria-label="Ana menü">
 <div class="brand">Tedarik <strong>Portalı</strong><small>TEDARİKÇİ · PERFORMANS · RİSK · ANKET</small></div>
 <nav id="nav"></nav>
 <div class="nav-bottom"><div id="identity"></div><button id="signout" type="button">Oturumu kapat</button></div>
</aside>
<main id="main">
 <header id="topline"><div><div id="crumbs"></div><h1 id="pageTitle">Yükleniyor…</h1><div id="pageSub"></div></div>
 <div id="topActions"></div></header>
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
