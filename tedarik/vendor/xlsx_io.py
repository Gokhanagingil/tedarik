# Kaynak: Gokhanagingil/control@7720f4b095a067dbf810dbc1cd25937d88a2ee5f xlsx_io.py. Kopya; uyarlama tedarik/modules/transfer.py içinde. Yamalar: tedarik/vendor/PATCHES.md
"""Minimal secure XLSX reader/writer for KS GRC with bounded parsing.

Excel .xlsx support with inline/shared strings, numeric cells and multiple sheets.
No formulas or macro execution. Workbooks are structured, not rendered.
"""
import io
import re
import zipfile
from defusedxml import ElementTree as ET
from datetime import datetime
from html import escape as xml_escape

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_UPLOAD = 12 * 1024 * 1024
MAX_UNCOMPRESSED = 40 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLS = 60
CELL_LENGTH = 32000


def col_letter(index):
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def clean_text(value):
    value = str(value) if value is not None else ""
    return "".join(ch for ch in value if ch in "\n\r\t" or ord(ch) >= 32)[:CELL_LENGTH]


def spreadsheet_text(value):
    # Excel may treat strings as executable formulas on import/CSV conversion.
    value = clean_text(value)
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def worksheet_xml(rows):
    if len(rows) > MAX_ROWS + 1:
        raise ValueError("Excel sayfasında en fazla 5.000 veri satırı olabilir")
    parts = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="' + X + '"><sheetViews><sheetView workbookViewId="0"/></sheetViews>',
             '<sheetFormatPr defaultRowHeight="18"/><sheetData>']
    for ri, row in enumerate(rows, start=1):
        if len(row) > MAX_COLS:
            raise ValueError("Excel sayfasında en fazla 60 sütun olabilir")
        parts.append(f'<row r="{ri}" ht="{28 if ri == 1 else 20}" customHeight="1">')
        for ci, value in enumerate(row, start=1):
            if value is None:
                continue
            address = col_letter(ci) + str(ri)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                parts.append(f'<c r="{address}" s="{1 if ri == 1 else 0}"><v>{value}</v></c>')
            else:
                txt = xml_escape(spreadsheet_text(value))
                parts.append(f'<c r="{address}" t="inlineStr" s="{1 if ri == 1 else 0}"><is><t xml:space="preserve">{txt}</t></is></c>')
        parts.append('</row>')
    parts.append('</sheetData><autoFilter ref="A1:' + col_letter(len(rows[0]) if rows else 1) + str(max(1,len(rows))) + '"/></worksheet>')
    return "".join(parts).encode("utf-8")


def make_xlsx(sheets):
    """sheets: ordered mapping of Turkish sheet_name -> [[header,...], [values...]]"""
    if not sheets or len(sheets) > 30:
        raise ValueError("Excel dosyasında 1–30 sayfa olmalı")
    seen = set()
    names = []
    for name in sheets:
        clean = re.sub(r'[:\\/*?\[\]]', "-", name)[:31]
        if not clean or clean in seen:
            raise ValueError("Tekrarlı veya geçersiz Excel sayfa adı")
        seen.add(clean)
        names.append(clean)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=5) as z:
        overrides = ['<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                     '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
        for i in range(1,len(sheets)+1):
            overrides.append(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        z.writestr("[Content_Types].xml", ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'+''.join(overrides)+'</Types>').encode())
        z.writestr("_rels/.rels", ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>').encode())
        book_parts = []
        rel_parts = []
        for i, name in enumerate(names,1):
            safe_name = xml_escape(name)
            book_parts.append(f'<sheet name="{safe_name}" sheetId="{i}" r:id="rId{i}"/>')
            rel_parts.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>')
        z.writestr("xl/workbook.xml", ('<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="'+X+'" xmlns:r="'+R+'"><sheets>'+''.join(book_parts)+'</sheets></workbook>').encode())
        z.writestr("xl/_rels/workbook.xml.rels", ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(rel_parts)+'</Relationships>').encode())
        z.writestr("xl/styles.xml", ('<?xml version="1.0"?><styleSheet xmlns="'+X+'"><fonts count="2"><font><sz val="11"/><name val="Aptos"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF183553"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf numFmtId="0"/></cellStyleXfs><cellXfs count="2"><xf fontId="0" fillId="0"/><xf fontId="1" fillId="1" applyFont="1" applyFill="1"/></cellXfs></styleSheet>').encode())
        for i, rows in enumerate(sheets.values(),1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", worksheet_xml(rows))
    return output.getvalue()


def _read_cell(cell, shared):
    if cell.find("m:f", NS) is not None:
        raise ValueError("Formül içeren dosyalar içe aktarılamaz. Önce değer olarak yapıştırın.")
    type_ = cell.get("t")
    if type_ == "inlineStr":
        return "".join(t.text or "" for t in cell.findall(".//m:t", NS))
    v = cell.find("m:v", NS)
    if v is None:
        return ""
    raw = v.text or ""
    if type_ == "s":
        pos = int(raw)
        if pos < 0 or pos >= len(shared):
            raise ValueError("Excel paylaşılan metin indeksi geçersiz")
        return shared[pos]
    return raw


def _xml_part(archive, name):
    try:
        return ET.fromstring(archive.read(name), forbid_dtd=True)
    except (ET.ParseError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError("Excel XML içeriği geçersiz veya güvenli değil") from exc


def read_xlsx(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_UPLOAD:
        raise ValueError("Excel dosyası en fazla 12 MB olabilir")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Geçerli bir XLSX dosyası seçin")
    with z:
        infos = z.infolist()
        if len(infos) > 250 or sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
            raise ValueError("Excel dosyası boyut sınırını aşıyor")
        if any(i.file_size > 10 * 1024 * 1024 for i in infos):
            raise ValueError("Excel çalışma sayfası çok büyük")
        if any(i.compress_size and i.file_size / i.compress_size > 300 for i in infos):
            raise ValueError("Sıkıştırma oranı olağan dışı")
        names = set(z.namelist())
        if len(names) != len(infos):
            raise ValueError("Excel arşivinde tekrarlı dosya adı")
        if any(i.flag_bits & 1 or i.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} for i in infos):
            raise ValueError("Excel arşivinde desteklenmeyen sıkıştırma veya şifreleme")
        if "xl/workbook.xml" not in names or "xl/_rels/workbook.xml.rels" not in names:
            raise ValueError("Excel çalışma kitabı bulunamadı")
        if any(n.endswith((".bin", ".vbaProject", "vbaProject.bin")) for n in names):
            raise ValueError("Makro içeren çalışma kitapları desteklenmiyor")
        root = _xml_part(z, "xl/workbook.xml")
        relroot = _xml_part(z, "xl/_rels/workbook.xml.rels")
        refs = {r.get("Id"):r.get("Target","") for r in relroot}
        if len(refs) != len(relroot):
            raise ValueError("Excel arşivinde tekrarlı ilişki kimliği")
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared_root = _xml_part(z, "xl/sharedStrings.xml")
            for item in shared_root.findall("m:si", NS):
                shared.append("".join(t.text or "" for t in item.findall(".//m:t", NS)))
        parsed = {}
        parts_seen = set()
        sheets = root.findall(".//m:sheet", NS)
        if not 1 <= len(sheets) <= 30:
            raise ValueError("Excel dosyasında 1–30 sayfa olmalı")
        for sheet in sheets:
            name = sheet.get("name")
            relation = sheet.get("{" + R + "}id")
            target = refs.get(relation)
            if not target:
                raise ValueError("Eksik Excel çalışma sayfası")
            if target.startswith("/"):
                target = target.lstrip("/")
            elif not target.startswith("xl/"):
                target = "xl/" + target
            if ".." in target or target not in names:
                raise ValueError("Geçersiz Excel sayfa yolu")
            if (not name or name in parsed or target in parts_seen
                    or not re.fullmatch(r"xl/worksheets/[^/\\]+\.xml", target)):
                raise ValueError("Geçersiz veya tekrar kullanılan Excel sayfası")
            parts_seen.add(target)
            tree = _xml_part(z, target)
            records = []
            for ri, item in enumerate(tree.findall(".//m:sheetData/m:row", NS)):
                if ri > MAX_ROWS:
                    raise ValueError("Excel sayfasında 5.000'den fazla satır var")
                output = {}
                for cell in item.findall("m:c", NS):
                    address = cell.get("r", "")
                    match = re.fullmatch(r"([A-Z]{1,3})[1-9][0-9]{0,6}", address)
                    if not match:
                        raise ValueError("Excel hücre adresi geçersiz")
                    pos = 0
                    for ch in match.group(1):
                        pos = pos*26+ord(ch)-64
                    if pos > MAX_COLS or pos-1 in output:
                        raise ValueError("Excel sütun sınırı aşıldı")
                    value = _read_cell(cell,shared)
                    if len(value) > CELL_LENGTH:
                        raise ValueError("Excel hücresindeki metin çok uzun")
                    output[pos-1] = value
                if output:
                    cols = [output.get(i,"") for i in range(max(output)+1)]
                    records.append(cols)
            parsed[name] = records
        return parsed
