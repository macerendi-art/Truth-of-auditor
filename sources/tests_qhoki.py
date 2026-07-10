import os, tempfile
from django.test import SimpleTestCase
from openpyxl import Workbook
from sources.parsers.gateways import QHokiParser

def _xlsx(rows):
    wb = Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    wb.save(path)
    return path

HEADER = ["Transaction Date", "Paid Date", "Finished Date", "Settlement Date",
          "Settled At", "Member ID", "Rrn", "NMID", "Transaction ID",
          "Whitelabel Transaction ID", "Status", "Amount", "Downline Fee Amount",
          "Total Amount", "Memo", "Payment Method"]

class QHokiTests(SimpleTestCase):
    def test_ticket_dan_reference(self):
        path = _xlsx([
            HEADER,
            ["2026-07-03 23:59:23", "2026-07-03 23:59:49", "2026-07-03 23:59:51",
             "2026-07-04 08:00:00", "2026-07-04 08:01:55", "Politiku",
             "1q10a0v18001", "", "019f28eb-b15f-7ee2-83ea-ad5cddc9a287", "D6179892",
             "Success", "50000", "650", "49350", "", "qris"],
        ])
        try:
            rows = QHokiParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["ticket_no"], "D6179892")                      # pass 0
        self.assertEqual(r["reference"], "019f28eb-b15f-7ee2-83ea-ad5cddc9a287")  # ref-join
        self.assertEqual(str(r["amount"]), "50000")
        self.assertEqual(str(r["fee"]), "650")
        self.assertEqual(r["username"], "Politiku")

    def test_skip_non_success(self):
        path = _xlsx([HEADER,
            ["2026-07-03 00:00:00", "", "", "", "", "u", "r", "", "uuid", "D1",
             "Pending", "1000", "0", "1000", "", "qris"]])
        try:
            self.assertEqual(QHokiParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)


# Beberapa brand (mis. LBS) mengekspor laporan QRIS-HOKI sebagai CSV quoted,
# bukan xlsx — format kolom identik. Laporan end user 2026-07-10:
# "MUTASI DP QR HOKI hasilnya 0" padahal mutasi aslinya ada.
QHOKI_CSV = (
    '"Transaction Date","Paid Date","Finished Date","Settlement Date",'
    '"Settled At","Member ID",Rrn,NMID,"Transaction ID",'
    '"Whitelabel Transaction ID",Status,Amount,"Downline Fee Amount",'
    '"Total Amount",Memo,"Payment Method"\n'
    '"2026-07-08 11:40:59","2026-07-08 11:41:36","2026-07-08 11:41:38",'
    '"2026-07-08 20:00:00","2026-07-08 20:04:36","wayannn1","00048356","",'
    '"019f3fcc-b15f-7ee2-83ea-ad5cddc9a287","D6200001","Success","35000",'
    '"455","34545","","qris"\n'
)


def _csvfile(text):
    fd, path = tempfile.mkstemp(suffix=".csv"); os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class QHokiCSVTests(SimpleTestCase):
    def test_parse_csv_variant(self):
        path = _csvfile(QHOKI_CSV)
        try:
            rows = QHokiParser().parse(path, flow="dp")
        finally:
            os.remove(path)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["ticket_no"], "D6200001")
        self.assertEqual(r["reference"], "019f3fcc-b15f-7ee2-83ea-ad5cddc9a287")
        self.assertEqual(str(r["amount"]), "35000")
        self.assertEqual(r["username"], "wayannn1")
        self.assertEqual(r["occurred_at"].day, 8)

    def test_terdeteksi_dari_header_csv(self):
        from sources.detect import detect_source
        path = _csvfile(QHOKI_CSV)
        try:
            ranked = detect_source(path, "MUTASI DP QR HOKI LBS 08-07.csv")
        finally:
            os.remove(path)
        self.assertTrue(ranked)
        self.assertEqual(ranked[0]["parser_key"], "qhoki")
        self.assertGreaterEqual(ranked[0]["confidence"], 0.9)

    def test_baris_tanpa_id_dilewati(self):
        # Temuan codex: baris tanpa wl DAN txid (drift header) menghasilkan
        # row_hash yang cuma bergantung nominal -> saling tabrak & terbuang
        # diam-diam. Baris tanpa identitas harus DILEWATI eksplisit.
        path = _xlsx([HEADER,
            ["2026-07-03 00:00:00", "", "", "", "", "u", "r", "", "", "",
             "Success", "1000", "0", "1000", "", "qris"]])
        try:
            self.assertEqual(QHokiParser().parse(path, flow="dp"), [])
        finally:
            os.remove(path)
