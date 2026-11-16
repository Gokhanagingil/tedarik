"""Veri kalitesi kurallarının SQL karşılığı (K-032). Platform (elle çalıştırma için gösterim) ve toplayıcı (kurum ağında
çalıştırma) aynı üreticiyi kullanır; toplayıcı SQL'i platformdan almaz, kural tanımından kendisi kurar. Yalnızca standart
kitaplık kullanır (toplayıcı paketine `tdr_dq_sql.py` olarak girer).

Ad (şema, tablo, kolon) lehçeye göre tırnaklanır, değişmez değerler kaçışlanır. Sorgular yalnızca sayı döndürür:
`checked` (kontrol edilen satır) ve `failed` (kuralı sağlamayan satır) veya tek bir ölçüm (`measured`: en yeni zaman,
satır sayısı). Değer gerektiren biçim denetimleri (T.C. kimlik, IBAN, kart …) ve regex desteklemeyen lehçelerde desen
denetimi `python` türündedir: toplayıcı kolon değerlerini yerelde okuyup sayar, değerler gönderilmez.
"""
import re

TYPES = ("not_null", "unique", "range", "pattern", "allowed_values", "reference", "freshness", "row_count", "format",
         "custom_sql")
FORMATS = ("tckn", "vkn", "iban", "email", "phone", "card", "ipv4")
DIMENSIONS = {"not_null": "completeness", "unique": "uniqueness", "range": "validity", "pattern": "validity",
              "allowed_values": "validity", "reference": "consistency", "freshness": "timeliness",
              "row_count": "completeness", "format": "validity", "custom_sql": "validity"}
NEEDS_COLUMN = {"not_null", "unique", "range", "pattern", "allowed_values", "reference", "freshness", "format"}
DIALECTS = {"postgresql": "postgres", "redshift": "postgres", "sql_server": "tsql", "oracle": "oracle", "mysql": "mysql",
            "sap_hana": "hana", "snowflake": "snowflake", "bigquery": "bigquery"}
REGEX = {"postgres": "CAST({c} AS TEXT) ~ {p}", "mysql": "{c} REGEXP {p}", "oracle": "REGEXP_LIKE({c}, {p})",
         "snowflake": "REGEXP_LIKE({c}, {p})", "hana": "{c} LIKE_REGEXPR {p}", "bigquery": "REGEXP_CONTAINS(CAST({c} AS STRING), {p})",
         "ansi": "{c} REGEXP {p}"}
TEXT = {"postgres": "CAST({c} AS VARCHAR)", "tsql": "CAST({c} AS NVARCHAR(4000))", "oracle": "CAST({c} AS VARCHAR2(4000))",
        "mysql": "CAST({c} AS CHAR)", "bigquery": "CAST({c} AS STRING)", "hana": "CAST({c} AS NVARCHAR(5000))",
        "snowflake": "CAST({c} AS VARCHAR)", "ansi": "CAST({c} AS TEXT)"}


class RuleError(ValueError):
    """Kural tanımı eksik veya geçersiz (Türkçe ileti)."""


def dialect_of(platform):
    return DIALECTS.get(platform or "", "ansi")


def quote(name, dialect):
    name = str(name)
    if dialect in ("mysql", "bigquery"):
        return "`" + name.replace("`", "``") + "`"
    if dialect == "tsql":
        return "[" + name.replace("]", "]]") + "]"
    return '"' + name.replace('"', '""') + '"'


def table_ref(schema, table, dialect):
    return f"{quote(schema, dialect)}.{quote(table, dialect)}" if schema else quote(table, dialect)


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def number(value, label):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise RuleError(f"{label} sayı olmalı") from None
    return repr(int(n)) if n.is_integer() else repr(n)


def build(rule, dialect):
    """rule: {type, schema, table, column, params, ref_schema, ref_table, ref_column}. Dönüş: (sql, biçim).
    biçim: counts (checked, failed), measured (tek değer), python (kolon değerleri; toplayıcı yerelde sayar)."""
    kind = rule.get("type")
    if kind not in TYPES:
        raise RuleError("Bilinmeyen kural türü")
    p = rule.get("params") or {}
    if kind == "custom_sql":
        sql = str(p.get("sql") or "").strip().rstrip(";")
        if not re.match(r"(?is)^\s*(select|with)\b", sql):
            raise RuleError("Özel SQL kuralı SELECT veya WITH ile başlamalı ve checked, failed kolonlarını döndürmeli")
        return sql, "counts"
    t = table_ref(rule.get("schema"), rule["table"], dialect)
    if kind == "row_count":
        return f"SELECT COUNT(*) AS measured FROM {t}", "measured"
    if kind in NEEDS_COLUMN and not rule.get("column"):
        raise RuleError("Bu kural türü için kolon seçin")
    c = quote(rule.get("column") or "", dialect)
    if kind == "not_null":
        empty = f" OR {TEXT.get(dialect, TEXT['ansi']).format(c=c)} = ''" if p.get("empty_is_null") else ""
        return f"SELECT COUNT(*) AS checked, SUM(CASE WHEN {c} IS NULL{empty} THEN 1 ELSE 0 END) AS failed FROM {t}", "counts"
    if kind == "unique":
        return f"SELECT COUNT({c}) AS checked, COUNT({c}) - COUNT(DISTINCT {c}) AS failed FROM {t}", "counts"
    if kind == "range":
        low = number(p["min"], "En küçük değer") if p.get("min") not in (None, "") else None
        high = number(p["max"], "En büyük değer") if p.get("max") not in (None, "") else None
        if low is None and high is None:
            raise RuleError("Aralık için en küçük veya en büyük değer gerekli")
        cond = " OR ".join(x for x in (f"{c} < {low}" if low is not None else "", f"{c} > {high}" if high is not None else "") if x)
        return f"SELECT COUNT({c}) AS checked, SUM(CASE WHEN {cond} THEN 1 ELSE 0 END) AS failed FROM {t}", "counts"
    if kind == "allowed_values":
        values = [str(v) for v in (p.get("values") or []) if str(v).strip()]
        if not values:
            raise RuleError("İzin verilen değerleri girin")
        listed = ", ".join(literal(v) for v in values[:500])
        expr = TEXT.get(dialect, TEXT["ansi"]).format(c=c)
        return (f"SELECT COUNT({c}) AS checked, SUM(CASE WHEN {c} IS NOT NULL AND {expr} NOT IN ({listed}) THEN 1 ELSE 0 END) "
                f"AS failed FROM {t}"), "counts"
    if kind == "pattern":
        pattern = str(p.get("pattern") or "")
        if not pattern:
            raise RuleError("Desen (düzenli ifade) gerekli")
        try:
            re.compile(pattern)
        except re.error:
            raise RuleError("Desen geçerli bir düzenli ifade değil") from None
        if dialect not in REGEX:
            return f"SELECT {c} AS value FROM {t} WHERE {c} IS NOT NULL", "python"
        anchored = literal(f"^({pattern})$".replace("\\", "\\\\") if dialect == "bigquery" else f"^({pattern})$")
        test = REGEX[dialect].format(c=c, p=anchored)
        return f"SELECT COUNT({c}) AS checked, SUM(CASE WHEN {c} IS NOT NULL AND NOT ({test}) THEN 1 ELSE 0 END) AS failed FROM {t}", "counts"
    if kind == "format":
        if p.get("format") not in FORMATS:
            raise RuleError("Biçim seçin (T.C. kimlik, VKN, IBAN, e-posta, telefon, kart, IPv4)")
        return f"SELECT {c} AS value FROM {t} WHERE {c} IS NOT NULL", "python"
    if kind == "reference":
        if not rule.get("ref_table") or not rule.get("ref_column"):
            raise RuleError("Referans tablo ve kolon gerekli")
        r = table_ref(rule.get("ref_schema"), rule["ref_table"], dialect)
        rc = quote(rule["ref_column"], dialect)
        return (f"SELECT COUNT(x.{c}) AS checked, SUM(CASE WHEN x.{c} IS NOT NULL AND y.{rc} IS NULL THEN 1 ELSE 0 END) "
                f"AS failed FROM {t} x LEFT JOIN (SELECT DISTINCT {rc} FROM {r}) y ON y.{rc} = x.{c}"), "counts"
    if kind == "freshness":
        return f"SELECT MAX({c}) AS measured FROM {t}", "measured"
    raise RuleError("Bilinmeyen kural türü")


def is_vkn(value):
    """Vergi kimlik numarası (10 hane, GİB algoritması)."""
    s = str(value).strip()
    if not re.fullmatch(r"\d{10}", s):
        return False
    d = [int(ch) for ch in s]
    total = 0
    for i in range(9):
        t = (d[i] + 9 - i) % 10
        v = (t * 2 ** (9 - i)) % 9
        if t != 0 and v == 0:
            v = 9
        total += v
    return (10 - total % 10) % 10 == d[9]


def python_check(rule, values, pii):
    """Değerleri yerelde sayar. pii: K-029 doğrulayıcı modülü. Dönüş: (checked, failed)."""
    p = rule.get("params") or {}
    if rule["type"] == "pattern":
        rx = re.compile(str(p.get("pattern") or ""))
        test = lambda v: bool(rx.fullmatch(v))     # noqa: E731
    else:
        fn = is_vkn if p.get("format") == "vkn" else pii.DETECTORS.get(p.get("format"))
        if fn is None:
            raise RuleError("Bilinmeyen biçim")
        test = fn
    checked = failed = 0
    for v in values:
        if v is None:
            continue
        text = str(v).strip()
        if not text:
            continue
        checked += 1
        if not test(text):
            failed += 1
    return checked, failed
