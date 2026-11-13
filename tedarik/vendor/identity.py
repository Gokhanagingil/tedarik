# Kaynak: Gokhanagingil/control@7720f4b095a067dbf810dbc1cd25937d88a2ee5f identity.py. Kopya; uyarlama tedarik/session.py içinde. Yamalar: tedarik/vendor/PATCHES.md
"""Account storage and sessions bound to their issuing authentication policy."""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie, CookieError

COOKIE_NAME = "control_grc_session"
ENTERPRISE_COOKIE = "__Host-ksgrc_session"
ITERATIONS = 600_000
SESSION_HOURS = 12

def now():
    return datetime.now(timezone.utc)

def setup(db):
    fields = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
    for name, definition in (
        ("password_hash", "TEXT"),
        ("must_change_password", "INTEGER NOT NULL DEFAULT 1"),
        ("last_login_at", "TEXT"),
    ):
        if name not in fields:
            db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    db.execute("""CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    session_fields = {r["name"] for r in db.execute("PRAGMA table_info(auth_sessions)")}
    for name, definition in (("auth_scope", "TEXT NOT NULL DEFAULT 'local'"), ("app_role", "TEXT")):
        if name not in session_fields:
            db.execute(f"ALTER TABLE auth_sessions ADD COLUMN {name} {definition}")
    db.execute("""CREATE TABLE IF NOT EXISTS entra_subjects (
        tenant TEXT NOT NULL, oid TEXT NOT NULL, user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
        PRIMARY KEY(tenant, oid)
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS auth_sessions_expiry ON auth_sessions(expires_at)")

def hash_password(password):
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValueError("Parola en az 12 karakter olmalı")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "$".join(("pbkdf2_sha256", str(ITERATIONS),
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("=")))

def verify_password(password, stored):
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256" or not 100_000 <= int(iterations) <= 1_000_000:
            return False
        salt_bytes = base64.urlsafe_b64decode(salt + "=" * (-len(salt) % 4))
        expected = base64.urlsafe_b64decode(digest + "=" * (-len(digest) % 4))
        calculated = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, int(iterations))
        return hmac.compare_digest(calculated, expected)
    except (ValueError, TypeError):
        return False

def provision(db, username, password, reset=False):
    if not isinstance(username, str) or not 1 <= len(username) <= 80:
        raise ValueError("Geçerli kullanıcı adı gerekli")
    if username.startswith("entra:"):
        raise ValueError("Kurumsal hesaplar Entra ID üzerinden yönetilir")
    user = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if user and not reset:
        return False
    encoded = hash_password(password)
    if user:
        db.execute("""UPDATE users SET password_hash=?, must_change_password=1, is_active=1,
             updated_at=? WHERE id=?""", (encoded, now().isoformat(), user["id"]))
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user["id"],))
    else:
        db.execute("""INSERT INTO users (username, email, display_name, is_active, created_at,
            password_hash, must_change_password) VALUES (?, NULL, ?, 1, ?, ?, 1)""",
            (username, "GRC Yönetim", now().isoformat(), encoded))
    return True

def authenticate(db, username, password):
    record = db.execute("""SELECT id, username, display_name, is_active, password_hash,
        must_change_password FROM users WHERE username=?""", (username,)).fetchone()
    if not record or not record["is_active"] or not verify_password(password, record["password_hash"]):
        return None
    db.execute("UPDATE users SET last_login_at=? WHERE id=?", (now().isoformat(), record["id"]))
    return dict(record)

def entra_account(db, tenant, oid, display):
    """Link only on immutable tenant/object IDs. Do not match local names or emails."""
    row = db.execute("""SELECT u.id, u.is_active FROM entra_subjects e JOIN users u ON u.id=e.user_id
        WHERE e.tenant=? AND e.oid=?""", (tenant, oid)).fetchone()
    timestamp = now().isoformat()
    if row:
        if not row["is_active"]:
            return None
        db.execute("UPDATE users SET last_login_at=? WHERE id=?", (timestamp, row["id"]))
        return row["id"]
    username = f"entra:{tenant}:{oid}"
    user_id = db.execute("""INSERT INTO users(username,display_name,created_at,last_login_at,must_change_password)
        VALUES(?,?,?,?,0)""", (username, display, timestamp, timestamp)).lastrowid
    db.execute("INSERT INTO entra_subjects(tenant,oid,user_id) VALUES(?,?,?)", (tenant,oid,user_id))
    return user_id


def new_session(db, user_id, *, scope="local", role=None, expires=None):
    secret = secrets.token_urlsafe(36)
    token_hash = hashlib.sha256(secret.encode("ascii")).hexdigest()
    created = now()
    db.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (created.isoformat(),))
    expiry = created + timedelta(hours=SESSION_HOURS)
    if expires is not None:
        expiry = min(expiry, datetime.fromtimestamp(expires, timezone.utc), created + timedelta(hours=1))
        db.execute("DELETE FROM auth_sessions WHERE user_id=? AND auth_scope=? AND app_role<>?",
                   (user_id, scope, role))
    db.execute("""INSERT INTO auth_sessions(token_hash,user_id,created_at,expires_at,auth_scope,app_role)
        VALUES(?,?,?,?,?,?)""", (token_hash, user_id, created.isoformat(), expiry.isoformat(), scope, role))
    return secret

def read_session(db, header, *, scope="local"):
    if not header:
        return None
    try:
        cookies = SimpleCookie()
        cookies.load(header)
        cookie = cookies.get(COOKIE_NAME if scope == "local" else ENTERPRISE_COOKIE)
        if not cookie:
            return None
        token = cookie.value
        if not 10 < len(token) < 150:
            return None
        hash_value = hashlib.sha256(token.encode("ascii")).hexdigest()
        record = db.execute("""SELECT u.id,u.username,u.display_name,u.is_active,
          u.must_change_password,a.expires_at,a.app_role FROM auth_sessions a
          JOIN users u ON u.id=a.user_id WHERE a.token_hash=? AND a.auth_scope=?""", (hash_value, scope)).fetchone()
        if not record or not record["is_active"] or record["expires_at"] <= now().isoformat():
            return None
        return dict(record)
    except (ValueError, UnicodeError, CookieError):
        return None

def revoke(db, header, *, enterprise=False):
    try:
        cookies = SimpleCookie()
        cookies.load(header or "")
        cookie = cookies.get(ENTERPRISE_COOKIE if enterprise else COOKIE_NAME)
        if cookie:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?",
                (hashlib.sha256(cookie.value.encode("ascii")).hexdigest(),))
    except (ValueError, UnicodeError, CookieError):
        pass

def session_cookie(value, *, secure=True, clear=False, enterprise=False):
    name = ENTERPRISE_COOKIE if enterprise else COOKIE_NAME
    parts = [f"{name}={value}", "Path=/", "HttpOnly", "SameSite=Strict"]
    if secure:
        parts.append("Secure")
    parts.append("Max-Age=0" if clear else f"Max-Age={3600 if enterprise else SESSION_HOURS * 3600}")
    return "; ".join(parts)

LOGIN_HTML = r"""<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KS GRC • Giriş</title>
<style>*{box-sizing:border-box}body{margin:0;background:#eef3f9;color:#1a2940;font:15px system-ui,Segoe UI,Arial;min-height:100vh;display:grid;place-items:center}
.panel{background:#fff;max-width:430px;width:calc(100% - 30px);padding:35px;border-radius:18px;box-shadow:0 24px 65px #142b4b20}
h1{margin:0;font-size:30px}h1 span{color:#2563eb}.muted{color:#64748b;line-height:1.6;margin:12px 0 30px}
label{display:block;font-size:13px;font-weight:650;margin-bottom:18px}input{display:block;width:100%;margin-top:8px;padding:12px;border:1px solid #cbd5e1;border-radius:9px;font:inherit}
button{background:#2563eb;color:white;border:0;border-radius:9px;padding:13px 18px;width:100%;font:inherit;font-weight:650;cursor:pointer}
button:disabled{opacity:.6}.msg{color:#b42318;min-height:24px;margin-top:15px;font-size:13px}footer{font-size:12px;color:#94a3b8;margin-top:27px}</style>
<div class="panel"><h1>KS<span> GRC</span></h1><p class="muted">Denetim, kontrol ve kanıt yönetimi<br>GRC ekibi giriş alanı</p>
<form id="login"><label>Kullanıcı adı<input name="username" autocomplete="username" required autofocus></label>
<label>Parola<input type="password" name="password" autocomplete="current-password" required></label>
<button id="submit" type="submit">Oturum aç</button><div id="message" class="msg" role="alert"></div></form><footer>KS GRC • Yalnızca yetkili personel</footer></div>
<script>document.getElementById('login').addEventListener('submit',async e=>{
e.preventDefault();const button=document.getElementById('submit');button.disabled=true;
document.getElementById('message').textContent='';const data=Object.fromEntries(new FormData(e.target));
try{const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
const result=await r.json();if(!r.ok)throw Error(result.error||'Giriş başarısız');
location.replace(result.must_change_password?'/change-password':'/');
}catch(err){document.getElementById('message').textContent=err.message;button.disabled=false}
});</script></html>"""

CHANGE_HTML = r"""<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KS GRC • Parola belirle</title>
<style>body{font:15px system-ui,Segoe UI,Arial;background:#eef3f9;color:#19324f;min-height:100vh;display:grid;place-items:center}
main{background:white;padding:35px;border-radius:14px;max-width:470px;width:90%;box-shadow:0 20px 50px #142b4b1b}
input{box-sizing:border-box;width:100%;padding:12px;border:1px solid #cbd5e1;border-radius:8px;margin:7px 0 17px}button{background:#2563eb;color:white;border:0;border-radius:8px;padding:13px;width:100%;cursor:pointer}
label{font-weight:600}p{color:#64748b}#msg{color:#b42318}</style>
<main><h2>İlk giriş: Parolanı değiştir</h2><p>Geçici parolayı en az 12 karakterli kendi parolanla değiştir.</p>
<form id="form"><label>Geçici parola<input name="current_password" type="password" autocomplete="current-password" required></label>
<label>Yeni parola<input name="new_password" type="password" autocomplete="new-password" minlength="12" required></label>
<button type="submit">Parolayı değiştir ve devam et</button><p id="msg" role="alert"></p></form></main>
<script>document.getElementById('form').onsubmit=async e=>{
e.preventDefault();const body=Object.fromEntries(new FormData(e.target));
try{const r=await fetch('/api/change-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const data=await r.json();if(!r.ok)throw Error(data.error||'İşlem başarısız');location.replace('/');
}catch(err){document.getElementById('msg').textContent=err.message}};</script></html>"""


ENTRA_SUCCESS = """<!doctype html><html lang="tr"><meta charset="utf-8"><title>KS GRC • Giriş</title>
<p>Kurumsal oturum açıldı. <a href="/">KS GRC'ye devam et</a></p>
<script>location.replace('/')</script></html>"""

ENTRA_DENIED = """<!doctype html><html lang="tr"><meta charset="utf-8"><title>KS GRC • Giriş</title>
<h1>Kurumsal oturum açılamadı</h1><p>Giriş süresi dolmuş olabilir. Tekrar deneyin.
Sorun sürerse yöneticinizden Entra rolünüzü ve MFA ilkesini kontrol etmesini isteyin.</p>
<p><a href="/login">Tekrar giriş yap</a></p></html>"""


ENTRA_LOGIN = """<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KS GRC • Kurumsal giriş</title><style>body{font:16px system-ui;color:#19324f;background:#eef3f9;min-height:95vh;display:grid;place-items:center}
main{padding:2.5rem;background:white;border-radius:1rem;max-width:26rem}a{display:inline-block;padding:.8rem 1.2rem;background:#2155b0;color:white;border-radius:.5rem;text-decoration:none}
p{line-height:1.55}</style><main><h1>KS GRC</h1><p>Denetim, kontrol ve kanıt yönetimine erişmek için kurum hesabınızla oturum açın.</p>
<a href="/auth/entra/start">Microsoft ile giriş yap</a></main></html>"""
