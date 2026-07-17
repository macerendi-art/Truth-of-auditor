"""Parser gateway RafflesPay varian XLSX (BBS): DP satu-header, WD dua-tingkat."""
import os
import tempfile

from django.test import SimpleTestCase
from openpyxl import Workbook


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


class ReadXlsxGridTests(SimpleTestCase):
    def test_grid_mentah_semua_baris(self):
        from sources.parsers.base import read_xlsx_grid
        path = _xlsx([["A", "B"], ["", "sub"], [1, 2]])
        try:
            grid = read_xlsx_grid(path)
        finally:
            os.remove(path)
        self.assertEqual(len(grid), 3)
        self.assertEqual(grid[0][0], "A")
        self.assertEqual(grid[1][1], "sub")
        self.assertEqual(grid[2][1], 2)
