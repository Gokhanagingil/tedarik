"""İlk yönetici hesabı (KS GRC bootstrap.py karşılığı). Geçici parola yalnızca standart çıktıya yazılır.

Kullanım (yalnızca TEDARIK_AUTH_MODE=local):
    umask 077
    python -m tedarik.bootstrap create [KULLANICI] > .first-login
    python -m tedarik.bootstrap reset KULLANICI --force > .first-login
Çıktıyı yalnızca yöneticinin okuyabildiği bir dosyaya yönlendirin, ilk girişten sonra silin. CI günlüğüne yazdırmayın.
"""
import sys

from .config import Config
from .db import utcnow
from .http import build
from .session import provision


def run(app, command, username):
    if app.config.auth_mode != "local":
        raise SystemExit("Bu komut yalnızca TEDARIK_AUTH_MODE=local ile kullanılır (Entra'da rol atamasıyla)")
    if not username or not username.isascii() or not all(ch.isalnum() or ch in "_.-" for ch in username):
        raise SystemExit("Geçersiz kullanıcı adı")
    with app.database.connect() as db:
        exists = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
        if exists and command == "create":
            return None
        password = provision(db, username, reset=command == "reset")
        if not password:
            raise RuntimeError("Hesap oluşturulamadı")
        user_id = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
        db.execute("INSERT INTO tdr_user_roles (user_id, role, assigned_by, assigned_at) VALUES (?,?,?,?) "
                   "ON CONFLICT(user_id) DO UPDATE SET role=excluded.role", (user_id, "ADMIN", "bootstrap", utcnow()))
    return password


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    config = Config()
    if len(argv) in (0, 1) or argv[0] not in ("create", "reset"):
        raise SystemExit("Kullanım: python -m tedarik.bootstrap create [KULLANICI] | reset KULLANICI --force")
    command = argv[0]
    username = argv[1] if len(argv) > 1 else config.env.get("TEDARIK_UI_USER", "tdradmin")
    if command == "reset" and argv[2:] != ["--force"]:
        raise SystemExit("Sıfırlama için açıkça --force verin")
    if command == "create" and len(argv) > 2:
        raise SystemExit("Geçersiz create argümanları")
    app = build(config)
    try:
        password = run(app, command, username)
    finally:
        app.close()
    if password is None:
        print("ACCOUNT_ALREADY_EXISTS")
        return
    print("Kullanici adi:", username)
    print("Gecici parola:", password)
    print("Ilk giriste yeni bir parola belirlemeniz gerekecektir.")


if __name__ == "__main__":
    main()
