"""QRIS ZPay (gateway baru) + QR FLYER format vendor (snake_case).

Laporan end user 8 Agustus 2026: ada QRIS baru bernama ZPay, dan laporan QR
Flyer "sudah tidak bisa di-download sendiri, harus minta ke vendor" sehingga
format unduhannya berbeda dan tidak terbaca.

Kegagalan Flyer itu SENYAP dan itu bagian terburuknya: deteksi tetap mengenali
berkasnya lewat nama file, parser lama tak menemukan satu pun kolom yang
dikenalnya, lalu menganggap SEMUA baris sebagai footer — berkas "berhasil"
diunggah dengan 0 baris. Tes di bawah mengunci kedua format hidup berdampingan.

Sisi ZPay menyimpan kegagalan senyap kedua: jam laporan vendor ternyata UTC
sedangkan seluruh aplikasi ini WIB naif. Sampel pertama sempat terbaca seolah
tiketnya tak ada di berkas mana pun — padahal isinya memang milik hari
BERIKUTNYA, dan tanpa geseran +7 jam uangnya tercatat mendahului kreditnya
sehingga jendela tanggal berarah engine memblokir pasangannya. Kelas
`ZPayTest` mengunci geseran itu pada nilai batas berkas nyata.
"""
import csv
import os
import tempfile

from django.test import SimpleTestCase
from openpyxl import Workbook

from sources.detect import detect_source
from sources.parsers.gateways import QRFlyerParser, ZPayParser


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    fd, path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    wb.save(path)
    return path


def _csv(rows):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerows(rows)
    return path


# Header nyata, disalin dari berkas klien 06-08-2026.
FLYER_LAMA = ["Transaction Date", "Settlement Time", "TXN ID", "Client Reference",
              "Customer ID / User Account", "Payment Status", "Transaction Value"]
FLYER_BARU = ["created_date", "client_reference", "transaction_id", "username",
              "status", "trans_date_time", "bot_success_time", "total_amount"]
# Bentuk KETIGA, berkas HKW 01-08-2026 — jam WIB, tanpa geseran.
FLYER_KETIGA = ["RRN", "Transaction Id", "Client Reference", "Username",
                "Amount", "Fee", "Fee Pct", "Created At", "Callback"]
ZPAY = ["Created At", "Paid At", "Order ID", "Payment Method", "Nama Merchant",
        "RRN", "Tiket Number", "User ID", "Nilai", "Fee", "Sub Total",
        "Confirmed Bot At", "Status", "Gateway", "Source", "Status Settled",
        "Waktu Settled"]


def _baris_baru(ticket="D769946", ref="A260806119200001624", user="maxwin255",
                nilai="100000.00", status="1"):
    return ["2026-08-06 00:06:46", ref, ticket, user, status,
            "2026-08-06 00:07:08", "2026-08-06 00:07:12", nilai]


def _baris_zpay(ticket="D770434", order="M25-Pawanghujan7-2wltt1fd501yb",
                nilai="25000", fee="300", sub="24700", status="paid",
                created="2026-08-06 23:52:05", paid="2026-08-06 23:52:24"):
    return [created, paid, order, "QRIS", "M25",
            "190384043890", ticket, "87f032b0-5573-45a6", nilai, fee, sub,
            "2026-08-06 23:52:27", status, "ZETPAY", "embed", "Settled",
            "2026-08-08 09:00:00"]


class FlyerFormatBaruTest(SimpleTestCase):
    def _parse(self, rows, flow="dp"):
        path = _xlsx(rows)
        try:
            return QRFlyerParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_kolom_snake_case_terbaca_penuh(self):
        r = self._parse([FLYER_BARU, _baris_baru()])[0]

        self.assertEqual(r["ticket_no"], "D769946")           # kunci join panel
        self.assertEqual(r["reference"], "A260806119200001624")
        self.assertEqual(r["username"], "maxwin255")
        self.assertEqual(str(r["amount"]), "100000.00")
        self.assertEqual(str(r["money_delta"]), "100000.00")
        self.assertEqual(r["occurred_at"].strftime("%Y-%m-%d %H:%M"), "2026-08-06 00:07")

    def test_bot_success_time_jadi_tanggal_pembukuan(self):
        """Format baru tak punya `Settlement Time`; `bot_success_time` padanannya."""
        r = self._parse([FLYER_BARU, _baris_baru()])[0]

        self.assertEqual(str(r["posted_date"]), "2026-08-06")

    def test_format_LAMA_tidak_berubah_sedikit_pun(self):
        path = _xlsx([FLYER_LAMA,
                      ["2026-07-01 10:00:00", "2026-07-01 12:00:00", "D111", "CR-9",
                       "budi", "SUCCESS", "50000"]])
        try:
            r = QRFlyerParser().parse(path, flow="dp")[0]
        finally:
            os.remove(path)

        self.assertEqual(r["ticket_no"], "D111")
        self.assertEqual(r["reference"], "CR-9")
        self.assertEqual(r["username"], "budi")
        self.assertEqual(str(r["amount"]), "50000")

    def test_row_hash_SAMA_antar_format(self):
        """Berkas yang sama diekspor ulang dalam format baru harus terdeteksi
        duplikat terhadap unggahan format lama — kalau tidak, satu hari bisa
        terhitung dua kali."""
        lama = _xlsx([FLYER_LAMA,
                      ["2026-08-06 00:06:46", "2026-08-06 00:07:12", "D769946",
                       "A260806119200001624", "maxwin255", "1", "100000.00"]])
        baru = _xlsx([FLYER_BARU, _baris_baru()])
        try:
            a = QRFlyerParser().parse(lama, flow="dp")[0]
            b = QRFlyerParser().parse(baru, flow="dp")[0]
        finally:
            os.remove(lama)
            os.remove(baru)

        self.assertEqual(a["row_hash"], b["row_hash"])

    def test_baris_footer_tetap_dilewati(self):
        r = self._parse([FLYER_BARU, _baris_baru(),
                         ["", "", "", "", "", "", "", "GRAND TOTAL"]])

        self.assertEqual(len(r), 1)

    def test_arah_wd_dihormati(self):
        r = self._parse([FLYER_BARU, _baris_baru()], flow="wd")[0]

        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["money_delta"]), "-100000.00")

    def test_bentuk_KETIGA_terbaca_penuh(self):
        """Header HKW 01-08-2026. Sebelumnya bentuk ini lolos SEBAGIAN dan itu
        justru bencananya: `Client Reference` ada sehingga baris tidak dianggap
        footer, lalu 1.519 baris masuk dengan tiket '', Rp0, tanpa tanggal."""
        r = self._parse([FLYER_KETIGA,
                         ["0115000BLP24", "D4632563", "B260801120500000125",
                          "susisai3", 500000, 6000, 1.2,
                          "2026-08-01 00:00:36", "2026-08-01 00:01:01"]])[0]

        self.assertEqual(r["ticket_no"], "D4632563")
        self.assertEqual(r["reference"], "B260801120500000125")
        self.assertEqual(r["username"], "susisai3")
        self.assertEqual(str(r["amount"]), "500000")
        self.assertEqual(str(r["fee"]), "6000")
        self.assertEqual(str(r["posted_date"]), "2026-08-01")   # dari Callback
        self.assertEqual(str(r["occurred_at"]), "2026-08-01 00:00:36")

    def test_bentuk_ketiga_TANPA_geseran_jam(self):
        """Beda dengan ZPay: jam Flyer sudah WIB. Panel HKW menyetujui median
        4 detik setelah `Callback` — geseran apa pun akan merusaknya."""
        r = self._parse([FLYER_KETIGA,
                         ["R1", "D1", "C1", "budi", 50000, 600, 1.2,
                          "2026-08-01 23:59:45", "2026-08-02 00:00:15"]])[0]

        self.assertEqual(str(r["occurred_at"]), "2026-08-01 23:59:45")

    def test_header_tanpa_kolom_tiket_MELEMPAR(self):
        """Kolom kunci hilang = berkas tak bisa dipercaya. Melempar, bukan
        menghasilkan baris kosong yang mengaku data."""
        with self.assertRaises(ValueError) as ctx:
            self._parse([["RRN", "Client Reference", "Username", "Amount"],
                         ["R1", "C1", "budi", 50000]])

        pesan = str(ctx.exception)
        self.assertIn("ticket", pesan)
        self.assertIn("Client Reference", pesan)   # header nyata disebut
        self.assertIn("TXN ID", pesan)             # yang dikenal disebut

    def test_header_tanpa_kolom_nominal_MELEMPAR(self):
        """Penggantian nama SEBAGIAN adalah langkah vendor berikutnya."""
        with self.assertRaises(ValueError) as ctx:
            self._parse([["RRN", "Transaction Id", "Client Reference",
                          "Username", "Nilai Transaksi", "Created At"],
                         ["R1", "D1", "C1", "budi", 50000, "2026-08-01 00:00:36"]])

        self.assertIn("amount", str(ctx.exception))

    def test_row_hash_SAMA_di_bentuk_ketiga(self):
        """Satu transaksi logis, tiga bentuk berkas, satu hash — kalau tidak,
        satu hari bisa terhitung dua kali saat vendor ganti format lagi."""
        lama = self._parse([FLYER_LAMA,
                            ["2026-08-01 00:00:36", "2026-08-01 00:01:01",
                             "D4632563", "B260801120500000125", "susisai3",
                             "SUCCESS", "500000"]])[0]
        ketiga = self._parse([FLYER_KETIGA,
                              ["0115000BLP24", "D4632563", "B260801120500000125",
                               "susisai3", 500000, 6000, 1.2,
                               "2026-08-01 00:00:36", "2026-08-01 00:01:01"]])[0]

        self.assertEqual(lama["row_hash"], ketiga["row_hash"])

    def test_deteksi_bentuk_ketiga(self):
        path = _xlsx([FLYER_KETIGA,
                      ["R1", "D1", "C1", "budi", 50000, 600, 1.2,
                       "2026-08-01 00:00:36", "2026-08-01 00:01:01"]])
        try:
            hasil = detect_source(path, "laporan vendor.xlsx")  # nama TANPA "qris"
        finally:
            os.remove(path)

        self.assertEqual(hasil[0]["parser_key"], "qrflyer")
        self.assertGreaterEqual(hasil[0]["confidence"], 0.9)
        self.assertNotIn("rpay_xlsx", [h["parser_key"] for h in hasil])

    def test_deteksi_format_baru_berkeyakinan_tinggi(self):
        """Tanpa tanda tangan header, berkas ini cuma lolos lewat nama file
        (0,85) — cukup untuk masuk, tidak cukup untuk dipercaya."""
        path = _xlsx([FLYER_BARU, _baris_baru()])
        try:
            hasil = detect_source(path, "laporan vendor.xlsx")   # nama TANPA "qris"
        finally:
            os.remove(path)

        self.assertEqual(hasil[0]["parser_key"], "qrflyer")
        self.assertGreaterEqual(hasil[0]["confidence"], 0.9)


class ZPayTest(SimpleTestCase):
    def _parse(self, rows, flow="dp"):
        path = _csv(rows)
        try:
            return ZPayParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_kunci_dan_nominal(self):
        r = self._parse([ZPAY, _baris_zpay()])[0]

        self.assertEqual(r["source_type"], "gateway")
        self.assertEqual(r["ticket_no"], "D770434")                 # pass 0
        self.assertEqual(r["reference"], "M25-Pawanghujan7-2wltt1fd501yb")
        self.assertEqual(str(r["amount"]), "25000")                 # bruto, spt panel
        self.assertEqual(str(r["fee"]), "300")
        # Paid At 23:52:24 UTC -> 06:52:24 WIB keesokan harinya.
        self.assertEqual(str(r["occurred_at"]), "2026-08-07 06:52:24")

    def test_batas_hari_nyata_utc_ke_wib(self):
        """Baris PERTAMA berkas nyata 06-08-2026: tiket D770355 @ 17:01:23.

        Panel berhenti di D770354 @ 06-Agu 23:59:39 WIB. Hanya dengan geseran
        +7 jam tiket berikutnya jatuh SESUDAHNYA (00:01:23, selisih 1m44d);
        tanpa geseran ia mendahului pendahulunya 7 jam — mustahil.
        """
        r = self._parse([ZPAY, _baris_zpay(ticket="D770355",
                                           created="2026-08-06 17:00:01",
                                           paid="2026-08-06 17:01:23")])[0]

        self.assertEqual(str(r["occurred_at"]), "2026-08-07 00:01:23")
        self.assertEqual(str(r["posted_date"]), "2026-08-07")   # ikut hari WIB

    def test_raw_menyimpan_jam_asli_vendor(self):
        """Jejak audit: yang digeser hanya kolom kanonik, bukan salinan mentah."""
        r = self._parse([ZPAY, _baris_zpay()])[0]

        self.assertEqual(r["raw"]["Paid At"], "2026-08-06 23:52:24")

    def test_row_hash_tak_terpengaruh_jam(self):
        """`row_hash` tak memuat waktu — kalau memuat, koreksi zona waktu ini
        akan membuat berkas yang sama terhitung dua kali."""
        a = self._parse([ZPAY, _baris_zpay(paid="2026-08-06 17:01:23")])[0]
        b = self._parse([ZPAY, _baris_zpay(paid="2026-08-06 23:52:24")])[0]

        self.assertEqual(a["row_hash"], b["row_hash"])

    def test_username_dari_order_id(self):
        r = self._parse([ZPAY, _baris_zpay()])[0]
        self.assertEqual(r["username"], "Pawanghujan7")

    def test_username_bertanda_hubung_tidak_terpotong(self):
        """`split("-")[1]` akan memotong "budi-santoso" jadi "budi"."""
        r = self._parse([ZPAY, _baris_zpay(order="M25-budi-santoso-9xzq")])[0]

        self.assertEqual(r["username"], "budi-santoso")

    def test_paid_DAN_settled_sama_sama_uang(self):
        """Satu daur hidup: `paid` = dibayar, `settled` = dananya sudah cair.

        Versi pertama hanya menerima "paid" dan menelan bulat-bulat 69 baris
        "settled" berkas 06-08-2026 — yang justru terbukti cocok dgn panel 69/69.
        """
        rows = self._parse([ZPAY,
                            _baris_zpay(ticket="D1", status="paid"),
                            _baris_zpay(ticket="D2", status="settled"),
                            _baris_zpay(ticket="D3", status="pending"),
                            _baris_zpay(ticket="D4", status="expired")])

        self.assertEqual([r["ticket_no"] for r in rows], ["D1", "D2"])

    def test_semua_status_asing_MELEMPAR_bukan_diam(self):
        """Kegagalan senyap adalah musuhnya: ada baris, tak ada hasil = salah."""
        with self.assertRaises(ValueError) as ctx:
            self._parse([ZPAY, _baris_zpay(ticket="D1", status="lunas"),
                         _baris_zpay(ticket="D2", status="lunas")])

        pesan = str(ctx.exception)
        self.assertIn("2", pesan)            # berapa baris yang tertahan
        self.assertIn("'lunas'", pesan)      # status yang ditemukan
        self.assertIn("settled", pesan)      # status yang dikenal

    def test_berkas_tanpa_baris_transaksi_sah_kosong(self):
        """Hanya header (atau penutup) — bukan kegagalan, jangan melempar."""
        self.assertEqual(self._parse([ZPAY]), [])

    def test_sebagian_status_asing_tidak_melempar(self):
        """Penjaga hanya berbunyi bila NOL hasil; campuran normal tetap lewat."""
        rows = self._parse([ZPAY, _baris_zpay(ticket="D1", status="settled"),
                            _baris_zpay(ticket="D2", status="lunas")])

        self.assertEqual([r["ticket_no"] for r in rows], ["D1"])

    def test_arah_wd_dihormati(self):
        r = self._parse([ZPAY, _baris_zpay()], flow="wd")[0]

        self.assertEqual(r["jenis"], "wd")
        self.assertEqual(str(r["money_delta"]), "-25000")

    def test_nilai_adalah_bruto_fee_plus_subtotal(self):
        """Menjaga asumsi: `Nilai` = `Fee` + `Sub Total`. Bila vendor mengubah
        artinya, tes ini yang berbunyi lebih dulu, bukan laporan keuangan."""
        r = self._parse([ZPAY, _baris_zpay(nilai="25000", fee="300", sub="24700")])[0]

        self.assertEqual(r["amount"] - r["fee"], 24700)

    def test_deteksi_csv_zpay(self):
        path = _csv([ZPAY, _baris_zpay()])
        try:
            hasil = detect_source(path, "06-08-2026 QRIS ZPAY DP M25.csv")
        finally:
            os.remove(path)

        self.assertEqual(hasil[0]["parser_key"], "zpay")
        self.assertGreaterEqual(hasil[0]["confidence"], 0.9)

    def test_zpay_tidak_tertukar_dengan_qhoki(self):
        """Keduanya CSV gateway QRIS — tanda tangannya harus saling asing."""
        path = _csv([ZPAY, _baris_zpay()])
        try:
            kunci = [h["parser_key"] for h in detect_source(path, "x.csv")]
        finally:
            os.remove(path)

        self.assertNotIn("qhoki", kunci)
