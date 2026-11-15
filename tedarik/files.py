"""Yüklenen dosyaların ortak denetimi (kanıt ve doküman): ad, uzantı, boyut, dosya imzası, arşiv bombası.

KS GRC grc_plus._valid_file kurallarıyla aynıdır. İçerik base64 olarak gelir ve veritabanında saklanır.
"""
import base64
import binascii
import io
import re
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from . import crud

FILE_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv", ".json", ".jsonl", ".log", ".xlsx", ".docx",
            ".pptx", ".zip", ".eml", ".xml", ".md"}
MAX_FILE = 12 * 1024 * 1024
SAFE_NAME = re.compile(r"^[^/\\\x00-\x1f]{1,160}$")


def valid_file(filename, binary):
    """KS GRC grc_plus._valid_file kuralları (uzantı, boyut, imza, arşiv bombası)."""
    if not isinstance(filename, str) or not SAFE_NAME.fullmatch(filename) or filename in {".", ".."}:
        raise crud.Invalid("Geçersiz dosya adı")
    extension = Path(filename).suffix.lower()
    if extension not in FILE_EXT:
        raise crud.Invalid("Dosya türüne izin verilmiyor. PDF, Office, resim, metin ve ZIP desteklenir")
    if not 0 < len(binary) <= MAX_FILE:
        raise crud.Invalid("Dosya boyutu 1 bayt – 12 MB arasında olmalı")
    signatures = {".pdf": b"%PDF-", ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
    if extension in signatures and not binary.startswith(signatures[extension]):
        raise crud.Invalid(f"{extension[1:].upper()} dosya imzası doğrulanamadı")
    if extension == ".webp" and (binary[:4] != b"RIFF" or binary[8:12] != b"WEBP"):
        raise crud.Invalid("WebP dosya imzası doğrulanamadı")
    if extension in (".zip", ".xlsx", ".docx", ".pptx"):
        try:
            with ZipFile(io.BytesIO(binary)) as archive:
                infos = archive.infolist()
                if len(infos) > 1200 or sum(i.file_size for i in infos) > 120 * 1024 * 1024:
                    raise crud.Invalid("Arşiv genişletilmiş boyut sınırını aşıyor")
                if any(i.compress_size and i.file_size / i.compress_size > 300 for i in infos):
                    raise crud.Invalid("Şüpheli arşiv sıkıştırma oranı")
                if extension != ".zip" and "[Content_Types].xml" not in archive.namelist():
                    raise crud.Invalid("Office dosyası geçersiz")
        except BadZipFile:
            raise crud.Invalid("Office/ZIP dosyası imzası geçersiz") from None
    if extension in (".txt", ".csv", ".log", ".json", ".jsonl", ".md", ".xml", ".eml") and b"\x00" in binary[:2048]:
        raise crud.Invalid("Metin dosyasının içeriği geçersiz")


def decode(body):
    encoded = body.get("content_base64")
    if not isinstance(encoded, str):
        raise crud.Invalid("content_base64 gerekli")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise crud.Invalid("Geçersiz dosya kodlaması") from None


