"""Arayüzden girilen entegrasyon sırlarının şifrelenmesi (K-024).

Sır (SMTP parolası, Teams web kancası, istemci sırrı, API anahtarı) veritabanında Fernet ile şifreli durur
(AES-128-CBC + HMAC-SHA256, `cryptography` paketi; Entra için zaten sabitlenmiş bağımlılık). Anahtar veritabanında
değil, sunucudaki ayrı bir dosyadadır (`TEDARIK_SECRET_KEY_FILE`; kurulum betiği üretir, yalnızca root okur ve
konteynere sır olarak bağlanır). Veritabanı yedeği tek başına sırları açığa çıkarmaz.

Anahtar veya paket yoksa sır kaydedilemez (açık hata); dosyayla verilen sırlar (`*_FILE`) her durumda çalışır.
Sır API'den hiçbir zaman geri dönmez; yalnızca "kayıtlı mı" bilgisi döner.
"""
from pathlib import Path


class SecretsUnavailable(RuntimeError):
    pass


def _fernet(config):
    path = getattr(config, "secret_key_file", "")
    if not path:
        raise SecretsUnavailable("Sır saklama anahtarı yapılandırılmamış (TEDARIK_SECRET_KEY_FILE); "
                                 "sırları sunucuda dosyayla verin veya anahtarı tanımlayın")
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise SecretsUnavailable("Sır şifrelemesi için cryptography paketi gerekli (requirements.txt)") from None
    try:
        key = Path(path).read_bytes().strip()
        return Fernet(key)
    except (OSError, ValueError):
        raise SecretsUnavailable("Sır saklama anahtarı okunamadı veya geçersiz") from None


def available(config):
    try:
        _fernet(config)
        return True
    except SecretsUnavailable:
        return False


def seal(config, value):
    return _fernet(config).encrypt(str(value).encode("utf-8")).decode("ascii")


def unseal(config, token):
    from cryptography.fernet import InvalidToken
    try:
        return _fernet(config).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise SecretsUnavailable("Kayıtlı sır çözülemedi (anahtar değişmiş olabilir); sırrı yeniden girin") from None


def generate_key():
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")
