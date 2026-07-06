import io, os, tempfile, zipfile
from django.test import SimpleTestCase
from sources.parsers.base import read_xlsx_rows, _raw_xlsx_rows

_CT = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
_RELS = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
_WB = '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
_WBR = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
# Sheet TANPA <dimension> (mereplikasi exporter COR): inline strings.
_SHEET = ('<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
          '<row r="1"><c r="A1" t="inlineStr"><is><t>Transaction ID</t></is></c><c r="B1" t="inlineStr"><is><t>Amount</t></is></c></row>'
          '<row r="2"><c r="A2" t="inlineStr"><is><t>abc-123</t></is></c><c r="B2" t="inlineStr"><is><t>50000</t></is></c></row>'
          '</sheetData></worksheet>')

def _make_nodim_xlsx():
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml", _WB)
        z.writestr("xl/_rels/workbook.xml.rels", _WBR)
        z.writestr("xl/worksheets/sheet1.xml", _SHEET)
    return path

class XlsxSafeTests(SimpleTestCase):
    def test_raw_reader_membaca_inline_strings(self):
        path = _make_nodim_xlsx()
        try:
            rows = _raw_xlsx_rows(path)
        finally:
            os.remove(path)
        self.assertEqual(rows[0][:2], ["Transaction ID", "Amount"])
        self.assertEqual(rows[1][:2], ["abc-123", "50000"])

    def test_read_xlsx_rows_tahan_tanpa_dimension(self):
        path = _make_nodim_xlsx()
        try:
            headers, dicts = read_xlsx_rows(path, header_row=1)
        finally:
            os.remove(path)
        self.assertEqual(len(dicts), 1)
        self.assertEqual(dicts[0]["Transaction ID"], "abc-123")
        self.assertEqual(str(dicts[0]["Amount"]), "50000")
