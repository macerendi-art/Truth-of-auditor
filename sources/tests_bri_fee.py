"""Fee transfer BRIVA (WD e-wallet via BRI) ditandai 'admin' seperti fee BCA.

Bukti data (mutasi WLG CANTIKA IRSAD 01-10 Jul 2026, 398 baris BRIVA):
182 pasangan (tanggal,SEQ) persis transfer+fee Rp1.000 berdeskripsi identik,
34 transfer tanpa fee, NOL fee yatim, NOL nominal BRIVA lain di bawah 10rb.
"""
import os
import tempfile

from django.test import SimpleTestCase

from sources.parsers.banks import BRIParser

HEADER = ("ID,NOREK,TGL_TRAN,TGL_EFEKTIF,JAM_TRAN,SEQ,DESK_TRAN,"
          "SALDO_AWAL_MUTASI,MUTASI_DEBET,MUTASI_KREDIT,SALDO_AKHIR_MUTASI,"
          "GLSIGN,TRUSER,KODE_TRAN,KODE_TRAN_TELLER,TRREMK,TLBDS1,TLBDS2,REMARK_CUSTOM")

DESC_BRIVA = ("BRIVA30135083144889247NBMBAxxxx Pxxxx "
              "BRIVA 30135083144889247NBMBAxxxx ESB:NBMB:0200200P:174837810133")
DESC_NBMB = "NBMB Cantika Irsad TO OZI FACHMILAN ESB:NBMB:0001500F:168770158106"


def _csv(lines):
    fd, path = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join([HEADER] + lines) + "\n")
    return path


def _row(rid, desc, debet, kredit="0.00", seq="143801"):
    return (f'"{rid}","58801037081508","2026-07-10 23:44:44","2026-07-10 23:44:44",'
            f'"234444","{seq}","{desc}","7173313.00","{debet}","{kredit}",'
            f'"7103313.00","Db","8888079","4","6670","","","",""')


class BrivaFeeTests(SimpleTestCase):
    def _parse(self, lines):
        path = _csv(lines)
        try:
            return BRIParser().parse(path)
        finally:
            os.remove(path)

    def test_pasangan_transfer_dan_fee(self):
        # Kembar identik (SEQ & deskripsi sama), hanya nominal beda:
        # transfer tetap 'wd', fee Rp1.000 jadi 'admin'.
        rows = self._parse([
            _row("1694", DESC_BRIVA, "70000.00"),
            _row("1695", DESC_BRIVA, "1000.00"),
        ])
        self.assertEqual([r["jenis"] for r in rows], ["wd", "admin"])
        self.assertEqual(str(rows[1]["amount"]), "1000.00")  # tetap tersimpan utk audit

    def test_seribu_non_briva_tetap_wd(self):
        # Rp1.000 di transfer biasa (NBMB) bukan fee BRIVA -> jangan disentuh.
        rows = self._parse([_row("10", DESC_NBMB, "1000.00")])
        self.assertEqual(rows[0]["jenis"], "wd")

    def test_briva_kredit_tidak_ditandai(self):
        # Aturan hanya untuk debit; kredit BRIVA (belum pernah terjadi di data)
        # jangan ikut ditandai admin.
        rows = self._parse([_row("11", DESC_BRIVA, "0.00", kredit="1000.00")])
        self.assertEqual(rows[0]["jenis"], "depo")

    def test_nama_penerima_mengandung_kata_briva_tetap_wd(self):
        # Temuan review adversarial: substring saja bisa salah tandai transfer
        # NBMB Rp1.000 ke penerima bernama 'TOKO BRIVA JAYA'. Wajib BRIVA<digit>.
        rows = self._parse([
            _row("12", "NBMB Cantika Irsad TO TOKO BRIVA JAYA ESB:NBMB:0001500F:1", "1000.00"),
        ])
        self.assertEqual(rows[0]["jenis"], "wd")
