"""Penggabungan pasangan SWITCHING BCA (transfer antar-bank bi-fast/online).

BCA memecah tiap transfer antar-bank jadi baris 'TRF <nama> <kode> MYBCA' bernilai
NET (bruto - 6.500) + baris fee 'BIAYA TXN ... MYBCA' Rp6.500. Panel mencatat
BRUTO, jadi kedua baris digabung jadi satu WD bruto agar nominal cocok.
"""
from decimal import Decimal

from django.test import SimpleTestCase

from sources.parsers.bca_pdf import _merge_switching, SWITCHING_TRF_RE


def _row(jenis, md, desc, amount=None, cp=""):
    amt = Decimal(abs(md)) if amount is None else Decimal(amount)
    return {
        "source_type": "bank", "jenis": jenis, "amount": amt,
        "money_delta": Decimal(md), "fee": Decimal("0"), "bonus": Decimal("0"),
        "counterparty": cp, "description": desc, "occurred_at": None,
        "raw": {}, "row_hash": f"h{md}{desc[:6]}",
    }


class SwitchingNameRegexTests(SimpleTestCase):
    def test_nama_menempel_ke_kode(self):
        m = SWITCHING_TRF_RE.search("TRF JENEVA PRINCESS ON535 MYBCA 95271 SWITCHING DB")
        self.assertEqual(m.group(1).strip(), "JENEVA PRINCESS ON")

    def test_nama_dengan_spasi(self):
        m = SWITCHING_TRF_RE.search("TRF FERY BRAHARZA 535 MYBCA 95271 SWITCHING DB")
        self.assertEqual(m.group(1).strip(), "FERY BRAHARZA")

    def test_bukan_switching_none(self):
        self.assertIsNone(SWITCHING_TRF_RE.search("TRSF E-BANKING 300000.00NOER ALPIAN"))


class MergeSwitchingTests(SimpleTestCase):
    def test_pasangan_digabung_jadi_bruto(self):
        rows = [
            _row("admin", -6500, "BIAYA TXN KE 535 JENEVA PRINCESS ONMYBCA 95271 SWITCHING DB"),
            _row("wd", -93500, "TRF JENEVA PRINCESS ON535 MYBCA 95271 SWITCHING DB"),
        ]
        out = _merge_switching(rows)
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["money_delta"], Decimal("-100000"))
        self.assertEqual(r["amount"], Decimal("100000"))
        self.assertEqual(r["fee"], Decimal("6500"))
        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(r["counterparty"], "JENEVA PRINCESS ON")

    def test_fery_bruto_409rb(self):
        rows = [
            _row("admin", -6500, "BIAYA TXN KE 535 FERY BRAHARZA MYBCA 95271 SWITCHING DB"),
            _row("wd", -402500, "TRF FERY BRAHARZA 535 MYBCA 95271 SWITCHING DB"),
        ]
        out = _merge_switching(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["money_delta"], Decimal("-409000"))
        self.assertEqual(out[0]["counterparty"], "FERY BRAHARZA")

    def test_baris_biasa_tidak_terpengaruh(self):
        rows = [
            _row("wd", -300000, "TRSF E-BANKING 300000.00NOER ALPIAN", cp="NOER ALPIAN"),
            _row("depo", 500000, "SETORAN TUNAI"),
        ]
        out = _merge_switching(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual([r["counterparty"] for r in out], ["NOER ALPIAN", ""])

    def test_biaya_txn_tanpa_trf_lolos_apa_adanya(self):
        rows = [_row("admin", -6500, "BIAYA TXN KE 535 X MYBCA 95271 SWITCHING DB")]
        out = _merge_switching(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["jenis"], "admin")

    def test_dua_pasangan_berurutan(self):
        rows = [
            _row("admin", -6500, "BIAYA TXN KE 535 AGUS SETIAWAN MYBCA 95271 SWITCHING DB"),
            _row("wd", -74500, "TRF AGUS SETIAWAN 535 MYBCA 95271 SWITCHING DB"),
            _row("admin", -6500, "BIAYA TXN KE 535 RIZA ISKANDAR MYBCA 95271 SWITCHING DB"),
            _row("wd", -373500, "TRF RIZA ISKANDAR 535 MYBCA 95271 SWITCHING DB"),
        ]
        out = _merge_switching(rows)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["money_delta"], Decimal("-81000"))
        self.assertEqual(out[1]["money_delta"], Decimal("-380000"))
