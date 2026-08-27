"""NXPayParser: arah dari ticket D/W, bukan cuma nama file DP/WD."""
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from openpyxl import Workbook

from sources.parsers.gateways import NXPayParser


def _xlsx_nxpay(rows, header_row2=None):
    """Buat xlsx NXPay: baris1 judul, baris2 header, lalu data."""
    wb = Workbook()
    ws = wb.active
    ws.append(["NXPAY Report"])
    ws.append(header_row2 or [
        "Ticket Number", "Username", "Amount", "Admin Fee",
        "Account Title", "Date", "Payment Type", "Status",
    ])
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    import os
    os.close(fd)
    wb.save(path)
    return path


class NXPayArahTicketTests(TestCase):
    """Ticket panel-compatible mengalahkan flow nama berkas yang salah."""

    def tearDown(self):
        for p in getattr(self, "_paths", []):
            Path(p).unlink(missing_ok=True)

    def _parse(self, rows, flow=""):
        path = _xlsx_nxpay(rows)
        self._paths = getattr(self, "_paths", []) + [path]
        return NXPayParser().parse(path, flow=flow)

    def test_ticket_D_jadi_depo_meski_flow_wd(self):
        """File salah-nama WD tapi isinya deposit QR (ticket D…)."""
        rows = [[
            "D2821134", "gelombang340", "1500000.00", "0",
            "QRIS", "8/20/2026 12:07:21 AM", "QR", "Success",
        ]]
        out = self._parse(rows, flow="wd")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["jenis"], "depo")
        self.assertEqual(out[0]["money_delta"], Decimal("1500000"))
        self.assertEqual(out[0]["ticket_no"], "D2821134")

    def test_ticket_W_jadi_wd_meski_flow_dp(self):
        """File salah-nama DP tapi isinya withdrawal bank (ticket W…)."""
        rows = [[
            "W2821885", "takokak01", "-30000000.00", "-3000",
            "BRI", "8/20/2026 1:47:01 PM", "BANK", "Success",
        ]]
        out = self._parse(rows, flow="dp")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["jenis"], "wd")
        self.assertEqual(out[0]["money_delta"], Decimal("-30000000"))
        self.assertEqual(out[0]["amount"], Decimal("30000000"))
        # Header pendek: hanya Admin Fee → fallback; abs
        self.assertEqual(out[0]["fee"], Decimal("3000"))

    def test_agent_fee_diutamakan_atas_admin_fee(self):
        """Acuan commander: kolom Agent Fee (bukan Player Fee / Admin Fee)."""
        header = [
            "Username", "Date", "Ticket Number", "Payment Type", "Account Title",
            "Status", "Amount", "Player Fee", "Agent Fee", "Admin Fee",
            "Player Nett Amount", "Agent Nett Amount", "Ticket Status",
        ]
        rows = [[
            "tonny1781", "8/26/2026 12:00:05 AM", "D2634343", "QR", "QRIS",
            "Success", "200000.00", "0.00", "-2200.00", "-2200.00",
            "200000.00", "197800.00", "Approved",
        ]]
        path = _xlsx_nxpay(rows, header_row2=header)
        self._paths = getattr(self, "_paths", []) + [path]
        out = NXPayParser().parse(path, flow="dp")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["fee"], Decimal("2200"))
        self.assertEqual(out[0]["amount"], Decimal("200000"))
        self.assertEqual(out[0]["jenis"], "depo")

    def test_agent_fee_nol_tidak_jatuh_ke_admin(self):
        """Kolom Agent Fee ada (nilai 0) → pakai 0, jangan ambil Admin Fee."""
        header = [
            "Ticket Number", "Username", "Amount", "Agent Fee", "Admin Fee",
            "Account Title", "Date", "Payment Type", "Status",
        ]
        rows = [[
            "D1", "u", "100000", "0", "-1100",
            "QRIS", "8/26/2026 12:00:00 AM", "QR", "Success",
        ]]
        path = _xlsx_nxpay(rows, header_row2=header)
        self._paths = getattr(self, "_paths", []) + [path]
        out = NXPayParser().parse(path, flow="dp")
        self.assertEqual(out[0]["fee"], Decimal("0"))

    def test_flow_dipakai_bila_ticket_bukan_D_W(self):
        rows = [[
            "X999", "pemain", "10000", "0",
            "QRIS", "8/20/2026 1:00:00 AM", "QR", "Success",
        ]]
        out = self._parse(rows, flow="wd")
        self.assertEqual(out[0]["jenis"], "wd")
        self.assertEqual(out[0]["money_delta"], Decimal("-10000"))

    def test_tanda_amount_bila_ticket_bukan_D_W_dan_flow_kosong(self):
        rows = [[
            "X999", "pemain", "-5000", "0",
            "BCA", "8/20/2026 1:00:00 AM", "BANK", "Success",
        ]]
        out = self._parse(rows, flow="")
        self.assertEqual(out[0]["jenis"], "wd")
        self.assertEqual(out[0]["money_delta"], Decimal("-5000"))
