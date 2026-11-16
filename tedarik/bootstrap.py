"""İlk yönetici hesabı (KS GRC bootstrap.py karşılığı). Geçici parola yalnızca standart çıktıya yazılır.

Kullanım (yalnızca TEDARIK_AUTH_MODE=local):
    umask 077
    python -m tedarik.bootstrap create [KULLANICI] > .first-login
    python -m tedarik.bootstrap reset KULLANICI --force > .first-login
    printf '%s' "$PAROLA" | python -m tedarik.bootstrap set KULLANICI --password-stdin
Çıktıyı yalnızca yöneticinin okuyabildiği bir dosyaya yönlendirin, ilk girişten sonra silin. CI günlüğüne yazdırmayın.
`set`: başlangıç parolasını standart girdiden alır (komut satırına ve çıktıya yazılmaz); hesap yoksa açar, varsa parolasını
değiştirir; hesap Yönetici olur, etkinleştirilir ve ilk girişte parola değişimi zorunludur. Kurulum işinde GitHub gizli
değeriyle kullanılır (docs/DAGITIM.md).
"""
import sys

from . import audit
from .auth import Principal
from .config import Config
from .db import utcnow
from .http import build
from .session import provision
from .vendor import identity

SYSTEM = Principal("bootstrap", "ADMIN", "system", "Kurulum komutu")


def run(app, command, username, password=None):
    """create/reset: geçici parola üretir ve döndürür. set: verilen parolayı yazar, True döndürür (parolayı döndürmez)."""
    if app.config.auth_mode != "local":
        raise SystemExit("Bu komut yalnızca TEDARIK_AUTH_MODE=local ile kullanılır (Entra'da rol atamasıyla)")
    if not username or len(username) > 80 or not username.isascii() or \
            not all(ch.isalnum() or ch in "_.-" for ch in username):
        raise SystemExit("Geçersiz kullanıcı adı")
    with app.database.connect() as db:
        exists = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if exists and command == "create":
            return None
        if command == "set":
            try:
                identity.provision(db, username, password, reset=True)
            except ValueError as error:
                raise SystemExit(str(error)) from None
            db.execute("UPDATE users SET is_active=1, display_name=COALESCE(display_name, ?), updated_at=? WHERE username=?",
                       (username, utcnow(), username))
            result = True
        else:
            result = provision(db, username, reset=command == "reset")
            if not result:
                raise RuntimeError("Hesap oluşturulamadı")
        user_id = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        db.execute("INSERT INTO tdr_user_roles (user_id, role, assigned_by, assigned_at) VALUES (?,?,?,?) "
                   "ON CONFLICT(user_id) DO UPDATE SET role=excluded.role", (user_id, "ADMIN", "bootstrap", utcnow()))
        if command == "set":    # kurulum yöneticisi süreli veya dış denetçi hesabı olamaz
            db.execute("DELETE FROM tdr_user_access WHERE user_id=?", (user_id,))
        audit.log(db, SYSTEM, "BOOTSTRAP", "users", user_id, {"command": command, "username": username, "role": "ADMIN",
                                                             "existed": bool(exists)})
    return result


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    config = Config()
    usage = "Kullanım: python -m tedarik.bootstrap create [KULLANICI] | reset KULLANICI --force | set KULLANICI --password-stdin"
    if not argv or argv[0] not in ("create", "reset", "set") or (argv[0] != "create" and len(argv) < 2):
        raise SystemExit(usage)
    command = argv[0]
    username = argv[1] if len(argv) > 1 else config.env.get("TEDARIK_UI_USER", "tdradmin")
    if command == "reset" and argv[2:] != ["--force"]:
        raise SystemExit("Sıfırlama için açıkça --force verin")
    if command == "create" and len(argv) > 2:
        raise SystemExit("Geçersiz create argümanları")
    secret = None
    if command == "set":
        if argv[2:] != ["--password-stdin"]:
            raise SystemExit("Parola yalnızca standart girdiden alınır: --password-stdin")
        secret = sys.stdin.read(2048).rstrip("\r\n")
        if len(secret) < 12:
            raise SystemExit("Başlangıç parolası en az 12 karakter olmalı")
    app = build(config)
    try:
        password = run(app, command, username, secret)
    finally:
        app.close()
    if password is None:
        print("ACCOUNT_ALREADY_EXISTS")
        return
    if command == "set":
        print("Kullanici hazir:", username, "(Yonetici; ilk giriste parola degisimi zorunlu)")
        return
    print("Kullanici adi:", username)
    print("Gecici parola:", password)
    print("Ilk giriste yeni bir parola belirlemeniz gerekecektir.")


if __name__ == "__main__":
    main()
