"""Kişisel veri doğrulayıcıları ve yerel örnek taraması (K-029).

Değerler platforma gönderilmez: tarama verinin bulunduğu yerde (tarayıcıda — datagov.js aynı kuralları uygular — veya bu
komutla kaynağın yanında) çalışır ve yalnızca kolon başına sayılar üretir: dolu değer sayısı ve her doğrulayıcının geçerli
bulduğu değer sayısı. Çıktı "Örnek veriyle doğrula" ekranına yüklenir.

    python -m tedarik.pii dosya.csv [--en-cok 2000] > istatistik.json

Doğrulayıcılar: T.C. kimlik numarası (11 hane, ilk hane 0 değil, 10. ve 11. hane algoritması), IBAN (ISO 13616 mod 97;
TR için 26 karakter), kart numarası (13–19 hane, Luhn), e-posta, Türkiye telefon numarası, IPv4 adresi.
"""
import csv
import io
import json
import re
import sys

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
IPV4 = re.compile(r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$")


def is_tckn(value):
    s = str(value).strip()
    if not re.fullmatch(r"[1-9]\d{10}", s):
        return False
    d = [int(ch) for ch in s]
    if (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def is_iban(value):
    s = re.sub(r"\s", "", str(value)).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    if s.startswith("TR") and len(s) != 26:
        return False
    moved = s[4:] + s[:4]
    digits = "".join(str(int(ch, 36)) for ch in moved)
    return int(digits) % 97 == 1


def is_card(value):
    s = re.sub(r"[\s-]", "", str(value))
    if not re.fullmatch(r"\d{13,19}", s) or len(set(s)) == 1:
        return False
    total = 0
    for i, ch in enumerate(reversed(s)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def is_email(value):
    return bool(EMAIL.match(str(value).strip()))


def is_phone(value):
    s = re.sub(r"[\s().-]", "", str(value))
    return bool(re.fullmatch(r"(\+90|0090|0)?5\d{9}", s) or re.fullmatch(r"(\+90|0090|0)[2-4]\d{9}", s))


def is_ipv4(value):
    return bool(IPV4.match(str(value).strip()))


DETECTORS = {"tckn": is_tckn, "iban": is_iban, "card": is_card, "email": is_email, "phone": is_phone, "ipv4": is_ipv4}


def scan(headers, records, limit=2000):
    """Kolon başına {dolu değer, doğrulayıcı → geçerli sayısı}. Değerin kendisi döndürülmez."""
    stats = {h: {"non_empty": 0, "matches": {k: 0 for k in DETECTORS}} for h in headers if h}
    n = 0
    for row in records:
        if n >= limit:
            break
        n += 1
        for i, h in enumerate(headers):
            if not h or i >= len(row):
                continue
            value = str(row[i]).strip()
            if not value:
                continue
            col = stats[h]
            col["non_empty"] += 1
            for key, fn in DETECTORS.items():
                if fn(value):
                    col["matches"][key] += 1
    for col in stats.values():
        col["matches"] = {k: v for k, v in col["matches"].items() if v}
    return {"sample_size": n, "columns": stats}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Kullanım: python -m tedarik.pii dosya.csv [--en-cok 2000]", file=sys.stderr)
        return 2
    limit = 2000
    if "--en-cok" in args:
        i = args.index("--en-cok")
        limit = int(args[i + 1])
        del args[i:i + 2]
    with open(args[0], encoding="utf-8-sig", newline="") as fh:
        text = fh.read()
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect)
    headers = next(reader, [])
    print(json.dumps(scan(headers, reader, limit), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
