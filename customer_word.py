"""Small no-dependency DOCX writer for selected customer records."""

from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile


def escape_xml(value):
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def paragraph_xml(text):
    lines = str(text or "").splitlines() or [""]
    runs = []
    for index, line in enumerate(lines):
        if index:
            runs.append("<w:r><w:br/></w:r>")
        runs.append(f"<w:r><w:t xml:space=\"preserve\">{escape_xml(line)}</w:t></w:r>")
    return "<w:p>" + "".join(runs) + "</w:p>"


def cell_xml(value):
    return (
        "<w:tc>"
        "<w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>"
        f"{paragraph_xml(value)}"
        "</w:tc>"
    )


def table_xml(rows, columns):
    header = "<w:tr>" + "".join(cell_xml(label) for _key, label in columns) + "</w:tr>"
    body_rows = []
    for row in rows:
        body_rows.append(
            "<w:tr>"
            + "".join(cell_xml(row.get(key, "")) for key, _label in columns)
            + "</w:tr>"
        )
    borders = """
    <w:tblPr>
      <w:tblBorders>
        <w:top w:val="single" w:sz="4" w:space="0" w:color="999999"/>
        <w:left w:val="single" w:sz="4" w:space="0" w:color="999999"/>
        <w:bottom w:val="single" w:sz="4" w:space="0" w:color="999999"/>
        <w:right w:val="single" w:sz="4" w:space="0" w:color="999999"/>
        <w:insideH w:val="single" w:sz="4" w:space="0" w:color="999999"/>
        <w:insideV w:val="single" w:sz="4" w:space="0" w:color="999999"/>
      </w:tblBorders>
    </w:tblPr>
    """
    return "<w:tbl>" + borders + header + "".join(body_rows) + "</w:tbl>"


def document_xml(rows, columns):
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = [
        paragraph_xml("土地客戶系統 - 選取資料匯出"),
        paragraph_xml(f"匯出時間：{generated_at}"),
        paragraph_xml(f"資料筆數：{len(rows)}"),
        table_xml(rows, columns),
    ]
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {''.join(body)}
    <w:sectPr>
      <w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>
      <w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720" w:header="450" w:footer="450" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""


RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"""


def write_records_docx(file_path, rows, columns):
    rows = [dict(row) for row in rows]
    columns = list(columns)
    with ZipFile(file_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", RELS_XML)
        archive.writestr("word/document.xml", document_xml(rows, columns))
    return len(rows)


def report_document_xml(rows, columns, *, title, header_text="", footer_text=""):
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    body = [paragraph_xml(header_text)] if header_text else []
    body.extend(
        [
            paragraph_xml(title),
            paragraph_xml(f"產生時間：{generated_at}　資料筆數：{len(rows)}"),
            table_xml(rows, columns),
        ]
    )
    if footer_text:
        body.append(paragraph_xml(footer_text))
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {''.join(body)}
    <w:sectPr>
      <w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>
      <w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


def write_report_docx(
    file_path,
    rows,
    columns,
    *,
    title="土地資料報表",
    header_text="",
    footer_text="",
):
    rows = [dict(row) for row in rows]
    columns = list(columns)
    with ZipFile(file_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", RELS_XML)
        archive.writestr(
            "word/document.xml",
            report_document_xml(
                rows,
                columns,
                title=title,
                header_text=header_text,
                footer_text=footer_text,
            ),
        )
    return len(rows)
