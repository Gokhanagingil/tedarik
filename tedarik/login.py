"""Oturum yolları ve kullanıcı yönetimi. Davranış KS GRC `app.py` ile aynıdır:

- `local`: `POST /api/login` (hız sınırlı), ilk girişte zorunlu parola değişimi, `POST /api/logout`.
- `entra`: `/auth/entra/start` -> Microsoft -> `/auth/entra/callback`; yerel parola yolları 403.
- `dev`: giriş yoktur; `/login` ana sayfaya yönlendirir.
- `/api/me` her modda; `/api/tdr/users` yönetici içindir. Entra modunda kullanıcı açılmaz (Entra ataması).
"""
import json
import logging
import re
from urllib.parse import urlparse

from . import accounts, audit, auth as authz, crud, session
from .db import rows, utcnow
from .http import API, Raw, Reply, redirect
from .vendor import identity

USERNAME = re.compile(r"[a-zA-Z0-9_.-]{3,60}")   # KS GRC POST /api/admin/users ile aynı
HTML = "text/html; charset=utf-8"
LOG = logging.getLogger("tedarik")

STYLE = """<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#eef3f9;
color:#1a2940;font:15px system-ui,"Segoe UI",Arial}main{background:#fff;max-width:430px;width:calc(100% - 32px);padding:34px;
border-radius:18px;box-shadow:0 24px 65px #142b4b20}h1{margin:0;font-size:28px}h1 span{color:#168c86}
.muted{color:#64748b;line-height:1.6;margin:12px 0 28px}label{display:block;font-size:13px;font-weight:650;margin-bottom:18px}
input{display:block;width:100%;margin-top:8px;padding:12px;border:1px solid #cbd5e1;border-radius:9px;font:inherit}
button,a.button{display:block;width:100%;text-align:center;background:#2667db;color:#fff;border:0;border-radius:9px;padding:13px;
font:inherit;font-weight:650;cursor:pointer;text-decoration:none}button:disabled{opacity:.6}
.msg{color:#b42318;min-height:22px;margin-top:14px;font-size:13px}footer{font-size:12px;color:#94a3b8;margin-top:26px}</style>"""
BRAND = "<h1>Tedarik<span> Portalı</span></h1>"

LOGIN_PAGE = f"""<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tedarik • Giriş</title>{STYLE}<main>{BRAND}<p class="muted">Tedarikçi, angajman, performans ve risk yönetimi</p>
<form id="login"><label>Kullanıcı adı<input name="username" autocomplete="username" required autofocus></label>
<label>Parola<input type="password" name="password" autocomplete="current-password" required></label>
<button id="submit" type="submit">Oturum aç</button><div id="message" class="msg" role="alert"></div></form>
<footer>Yalnızca yetkili personel</footer></main>
<script>document.getElementById('login').addEventListener('submit',async e=>{{e.preventDefault();
const b=document.getElementById('submit'),m=document.getElementById('message');b.disabled=true;m.textContent='';
try{{const r=await fetch('/api/login',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify(Object.fromEntries(new FormData(e.target)))}});const v=await r.json();
if(!r.ok)throw Error(v.error||'Giriş başarısız');location.replace(v.must_change_password?'/change-password':'/');
}}catch(err){{m.textContent=err.message;b.disabled=false}}}});</script></html>"""

CHANGE_PAGE = f"""<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tedarik • Parola belirle</title>{STYLE}<main>{BRAND}<p class="muted">Geçici parolayı en az 12 karakterli kendi parolanızla değiştirin.</p>
<form id="change"><label>Geçici parola<input name="current_password" type="password" autocomplete="current-password" required></label>
<label>Yeni parola<input name="new_password" type="password" autocomplete="new-password" minlength="12" required></label>
<button type="submit">Parolayı değiştir ve devam et</button><div id="message" class="msg" role="alert"></div></form></main>
<script>document.getElementById('change').addEventListener('submit',async e=>{{e.preventDefault();
try{{const r=await fetch('/api/change-password',{{method:'POST',headers:{{'Content-Type':'application/json'}},
body:JSON.stringify(Object.fromEntries(new FormData(e.target)))}});const v=await r.json();
if(!r.ok)throw Error(v.error||'İşlem başarısız');location.replace('/');
}}catch(err){{document.getElementById('message').textContent=err.message}}}});</script></html>"""

ENTRA_PAGE = f"""<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tedarik • Kurumsal giriş</title>{STYLE}<main>{BRAND}<p class="muted">Devam etmek için kurum hesabınızla oturum açın.</p>
<a class="button" href="/auth/entra/start">Microsoft ile giriş yap</a><footer>Yalnızca yetkili personel</footer></main></html>"""

ENTRA_SUCCESS = """<!doctype html><html lang="tr"><meta charset="utf-8"><title>Tedarik • Giriş</title>
<p>Kurumsal oturum açıldı. <a href="/">Tedarik Portalı'na devam et</a></p><script>location.replace('/')</script></html>"""

ENTRA_DENIED = f"""<!doctype html><html lang="tr"><meta charset="utf-8"><title>Tedarik • Giriş</title>{STYLE}
<main>{BRAND}<p class="muted">Kurumsal oturum açılamadı. Giriş süresi dolmuş olabilir; tekrar deneyin. Sorun sürerse
yöneticinizden Tedarik uygulama rolünüzü ve MFA ilkesini kontrol etmesini isteyin.</p>
<a class="button" href="/login">Tekrar giriş yap</a></main></html>"""

def page(content, status=200, cookie=None):
    return status, Reply(Raw(content, HTML), {"Set-Cookie": cookie} if cookie else None)


def _credentials(c):
    if len(json.dumps(c.body)) > 8192:
        raise crud.Invalid("Geçersiz istek boyutu")
    return c.body


# ------------------------------------------------------------------ açık yollar

def login_page(c):
    mode = c.app.config.auth_mode
    if mode == "dev":
        return redirect("/")
    return page(ENTRA_PAGE if mode == "entra" else LOGIN_PAGE)


def login(c):
    config = c.app.config
    if config.auth_mode == "entra":
        raise crud.Forbidden("Kurum hesabınızla giriş yapın")
    if config.auth_mode != "local":
        raise crud.NotFound("Bu modda parola girişi yoktur")
    origin = c.headers.get("Origin")   # tarayıcı gönderir; JSON istemcileri göndermeyebilir (KS GRC)
    if origin is not None and origin != c.app.expected_origin(c.headers):
        raise crud.Forbidden("Güvenlik doğrulaması başarısız")
    body = _credentials(c)
    username, password = body.get("username", ""), body.get("password", "")
    if not isinstance(username, str) or not isinstance(password, str):
        raise crud.Invalid("Kullanıcı adı ve parola gerekli")
    if not 1 <= len(username) <= 80 or not 1 <= len(password) <= 1024:
        return 401, {"error": "Kullanıcı adı veya parola yanlış"}
    key = (c.client, username)
    if not c.app.login_limiter.hit(key):
        return 429, {"error": "Çok fazla giriş denemesi; daha sonra tekrar deneyin"}
    account = identity.authenticate(c.db, username, password)
    if not account or not c.db.execute("SELECT 1 FROM tdr_user_roles WHERE user_id=?", (account["id"],)).fetchone():
        return 401, {"error": "Kullanıcı adı veya parola yanlış"}
    token = identity.new_session(c.db, account["id"])
    c.app.login_limiter.clear(key)
    return 200, Reply({"username": account["username"], "must_change_password": bool(account["must_change_password"])},
                      {"Set-Cookie": session.cookie(token, config)})


def entra_host_ok(c):
    return (c.headers.get("Host") or "").lower() == urlparse(c.app.auth.entra.config.redirect).netloc.lower()


def entra_start(c):
    if not entra_host_ok(c):
        raise crud.Invalid("Kurumsal uygulama adresini kullanın")
    destination, flow_cookie = c.app.auth.entra.begin()
    return redirect(destination, flow_cookie)


def entra_callback(c):
    from .vendor import entra_auth
    provider = c.app.auth.entra
    if not entra_host_ok(c):
        raise crud.Invalid("Kurumsal uygulama adresini kullanın")
    try:
        oid, role, expiry, display = provider.finish(c.raw_query, c.headers.get("Cookie", ""))
        c.db.lock("entra:" + oid)
        user_id = identity.entra_account(c.db, provider.config.tenant, oid, display)
        if user_id is None:
            raise entra_auth.Denied("inactive_account")
        token = identity.new_session(c.db, user_id, scope=provider.config.session_scope, role=role, expires=expiry)
    except entra_auth.Denied as exc:
        LOG.warning("Entra oturumu reddedildi (%s)", exc)      # neden kodu gizli bilgi içermez
        return page(ENTRA_DENIED, 403)
    except entra_auth.Unavailable as exc:
        LOG.warning("Entra kullanılamıyor (%s)", exc)
        return 503, {"error": "Kurumsal oturum hizmeti geçici olarak kullanılamıyor"}
    return page(ENTRA_SUCCESS, cookie=session.cookie(token, c.app.config))


# ------------------------------------------------------------------ oturumlu yollar

def home(c):
    from .ui import shell
    return shell(c)


def me(c):
    return c.principal.public()


def change_page(c):
    if c.app.config.auth_mode != "local":
        return redirect("/")
    return page(CHANGE_PAGE)


def change_password(c):
    if c.app.config.auth_mode == "entra":
        raise crud.Forbidden("Parolalar Entra ID üzerinden yönetilir")
    if c.principal.auth_type != "session":
        raise crud.Forbidden("Kullanıcı oturumu gerekli")
    body = _credentials(c)
    previous, updated = body.get("current_password"), body.get("new_password")
    if not isinstance(previous, str) or not isinstance(updated, str):
        raise crud.Invalid("Parolalar gerekli")
    if previous == updated:
        raise crud.Invalid("Yeni parola eski paroladan farklı olmalı")
    row = c.db.execute("SELECT password_hash FROM users WHERE id=?", (c.principal.user_id,)).fetchone()
    if not row or not identity.verify_password(previous, row["password_hash"]):
        raise crud.Forbidden("Mevcut parola yanlış")
    c.db.execute("UPDATE users SET password_hash=?, must_change_password=0, updated_at=? WHERE id=?",
                 (identity.hash_password(updated), utcnow(), c.principal.user_id))
    c.db.execute("DELETE FROM auth_sessions WHERE user_id=?", (c.principal.user_id,))
    token = identity.new_session(c.db, c.principal.user_id)
    audit.log(c.db, c.principal, "PASSWORD", "users", c.principal.user_id)
    return 200, Reply({"changed": True}, {"Set-Cookie": session.cookie(token, c.app.config)})


def logout(c):
    if c.principal.auth_type != "session":
        raise crud.Forbidden("Kullanıcı oturumu gerekli")
    identity.revoke(c.db, c.headers.get("Cookie", ""), enterprise=c.app.config.auth_mode == "entra")
    return 200, Reply({"logged_out": True}, {"Set-Cookie": session.cookie("", c.app.config, clear=True)})


# ------------------------------------------------------------------ kullanıcı yönetimi

def _admin(c):
    authz.require_human(c.principal)
    authz.require(c.principal, "admin")


def _user(c, user_id):
    row = c.db.execute("SELECT id, username, display_name, email, is_active, created_at, last_login_at "
                       "FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise crud.NotFound("Kullanıcı bulunamadı")
    user = dict(row)
    role = c.db.execute("SELECT role FROM tdr_user_roles WHERE user_id=?", (user_id,)).fetchone()
    user["role"] = role["role"] if role else None
    user["org_unit_ids"] = [r["org_unit_id"] for r in c.db.execute(
        "SELECT org_unit_id FROM tdr_user_units WHERE user_id=? ORDER BY org_unit_id", (user_id,)).fetchall()]
    user["kind"] = "entra" if user["username"].startswith("entra:") else "local"
    return user


def _set_role(c, user_id, role):
    if role not in authz.ROLES:
        raise crud.Invalid("role şunlardan biri olmalı: " + ", ".join(authz.ROLES))
    c.db.execute("INSERT INTO tdr_user_roles (user_id, role, assigned_by, assigned_at) VALUES (?,?,?,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, assigned_by=excluded.assigned_by, "
                 "assigned_at=excluded.assigned_at", (user_id, role, c.principal.username, utcnow()))


def _set_units(c, user_id, ids):
    if not isinstance(ids, list) or any(type(i) is not int for i in ids):
        raise crud.Invalid("org_unit_ids tamsayı listesi olmalı")
    c.db.execute("DELETE FROM tdr_user_units WHERE user_id=?", (user_id,))
    for unit in sorted(set(ids)):
        c.db.execute("INSERT INTO tdr_user_units (user_id, org_unit_id, assigned_by, assigned_at) VALUES (?,?,?,?)",
                     (user_id, unit, c.principal.username, utcnow()))


def list_users(c):
    _admin(c)
    return [_user(c, r["id"]) for r in rows(c.db, "SELECT id FROM users ORDER BY id")]


def create_user(c):
    _admin(c)
    if c.app.config.auth_mode == "entra":
        raise crud.Forbidden("Kullanıcı atamalarını Entra ID üzerinden yapın")
    body = dict(c.body)
    username = body.pop("username", "")
    if not isinstance(username, str) or not USERNAME.fullmatch(username):
        raise crud.Invalid("Kullanıcı adı 3–60 karakter (harf, rakam, . _ -) olmalı")
    unknown = set(body) - {"display_name", "role", "org_unit_ids"}
    if unknown:
        raise crud.Invalid("Bilinmeyen alan: " + ", ".join(sorted(unknown)))
    display = body.get("display_name")
    if display is not None and (not isinstance(display, str) or not 1 <= len(display.strip()) <= 160):
        raise crud.Invalid("display_name 1–160 karakter olmalı")
    if c.db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
        raise crud.Conflict("Bu kullanıcı adı zaten kullanılıyor")
    password = session.provision(c.db, username, display.strip() if display else None)
    user_id = c.db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    _set_role(c, user_id, body.get("role"))
    _set_units(c, user_id, body.get("org_unit_ids", []))
    audit.log(c.db, c.principal, "CREATE", "users", user_id,
              {"username": username, "role": body.get("role"), "org_unit_ids": body.get("org_unit_ids", [])})
    return 201, {**_user(c, user_id), "temporary_password": password, "must_change_password": True}


def update_user(c):
    _admin(c)
    user_id = c.params["id"]
    current = _user(c, user_id)
    body = c.body
    allowed = {"is_active", "display_name", "email", "role", "org_unit_ids"}
    if not body or set(body) - allowed:
        raise crud.Invalid("Güncellenebilir alanlar: " + ", ".join(sorted(allowed)))
    fields = {}
    if "is_active" in body:
        if body["is_active"] not in (0, 1, True, False):
            raise crud.Invalid("Aktiflik 0 veya 1 olmalı")
        if not body["is_active"] and user_id == c.principal.user_id:
            raise crud.Invalid("Kendi hesabınızı devre dışı bırakamazsınız")
        fields["is_active"] = int(bool(body["is_active"]))
    for key in ("display_name", "email"):
        if key in body:
            if body[key] is not None and (not isinstance(body[key], str) or len(body[key]) > 254):
                raise crud.Invalid(f"{key} metin olmalı")
            fields[key] = body[key]
    if fields:
        c.db.execute("UPDATE users SET " + ", ".join(f"{k}=?" for k in fields) + ", updated_at=? WHERE id=?",
                     (*fields.values(), utcnow(), user_id))
    if fields.get("is_active") == 0:
        c.db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))   # açık oturum hemen kapanır
    if "role" in body:
        if c.app.config.auth_mode == "entra" or current["kind"] == "entra":
            raise crud.Forbidden("Kurumsal kullanıcının rolü Entra uygulama rolüyle verilir")
        _set_role(c, user_id, body["role"])
    if "org_unit_ids" in body:
        _set_units(c, user_id, body["org_unit_ids"])
    audit.log(c.db, c.principal, "UPDATE", "users", user_id, body)
    return _user(c, user_id)


def directory(c):
    """Davet ve sahip seçimi için etkin kullanıcıların adı ve görünen adı (parola, rol bilgisi yok)."""
    authz.require_human(c.principal)
    authz.require(c.principal, "write")
    return rows(c.db, "SELECT username, display_name FROM users WHERE is_active=1 ORDER BY display_name, username")


def register(app):
    app.route("GET", API + "/directory", directory)
    app.login_limiter = session.LoginLimiter()
    app.route("GET", "/login", login_page, public=True)
    app.route("POST", "/api/login", login, public=True)
    if app.auth.entra:
        app.route("GET", "/auth/entra/start", entra_start, public=True)
        app.route("GET", session.CALLBACK, entra_callback, public=True)
    app.route("GET", "/", home)
    app.route("GET", "/index.html", home)
    app.route("GET", "/api/me", me)
    app.route("GET", "/change-password", change_page)
    app.route("POST", "/api/change-password", change_password)
    app.route("POST", "/api/logout", logout)
    app.route("GET", API + "/users", list_users)
    app.route("POST", API + "/users", create_user)
    app.route("PATCH", API + "/users/{id}", update_user)
    assert accounts.USER_ROLES   # kaynak kaydı http içe aktarımında yapılır
