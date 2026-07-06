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
