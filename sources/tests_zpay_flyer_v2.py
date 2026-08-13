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
# Bentuk KEEMPAT, berkas LTN 12-08-2026. Tiket + nominal tetap terbaca (nama
# kolomnya sudah dikenal), tapi `date`/`Client Reff`/`charges` TIDAK — dan
# karena tak ada kolom waktu yang cocok, 339 baris masuk TANPA tanggal sama
# sekali sehingga tak pernah terlihat oleh jendela tanggal mana pun.
FLYER_KEEMPAT = ["date", "Client Reff", "transaction_id", "rrn", "username",
                 "total_amount", "charges", "net_amount", "rate_merchant"]
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


# Baris nyata pertama berkas LTN 12-08-2026.
def _baris_keempat(ticket="D2506425", ref="D260812119700084141", user="Pablo007",
                   total="50000.00", charges="600.00", net="49400.00",
                   tanggal="2026-08-12 13:30:59.0"):
    return [tanggal, ref, ticket, "1r8yujw12322", user, total, charges, net, "1.2"]


class FlyerBentukKeempatTest(SimpleTestCase):
    """Bentuk KEEMPAT (LTN 12-08-2026) — kegagalan senyap ketiga vendor ini.

    Berbeda dari dua kegagalan sebelumnya, dan justru itu pelajarannya:
    kolom tiket (`transaction_id`) dan nominal (`total_amount`) SUDAH dikenal,
    jadi penjaga header bentuk ketiga lolos dan 339 baris masuk dengan tiket,
    nominal, dan username yang BENAR SEMUA. Yang hilang cuma `date` — dan itu
    sudah cukup untuk melenyapkan uangnya: `posted_date` NULL membuat baris tak
    terlihat oleh jendela tanggal mana pun, sehingga 339 baris panel LTN
    berhenti di "Belum ada uang masuk" padahal uangnya ada di database.
    """

    def _parse(self, rows, flow="dp"):
        path = _xlsx(rows)
        try:
            return QRFlyerParser().parse(path, flow=flow)
        finally:
            os.remove(path)

    def test_bentuk_KEEMPAT_terbaca_penuh(self):
        r = self._parse([FLYER_KEEMPAT, _baris_keempat()])[0]

        self.assertEqual(r["ticket_no"], "D2506425")
        self.assertEqual(r["reference"], "D260812119700084141")   # 'Client Reff'
        self.assertEqual(r["username"], "Pablo007")
        self.assertEqual(str(r["amount"]), "50000.00")            # BRUTO, bukan net
        self.assertEqual(str(r["fee"]), "600.00")                 # 'charges'
        self.assertEqual(str(r["occurred_at"]), "2026-08-12 13:30:59")
        self.assertEqual(str(r["posted_date"]), "2026-08-12")

    def test_nominal_diambil_dari_bruto_BUKAN_net_amount(self):
        """`net_amount` (bruto − charges) ada di kolom sebelahnya. Panel mencatat
        bruto; salah ambil = tiap baris meleset sebesar fee dan pass 0 gagal."""
        r = self._parse([FLYER_KEEMPAT, _baris_keempat()])[0]

        self.assertEqual(str(r["amount"]), "50000.00")
        self.assertNotEqual(str(r["amount"]), "49400.00")

    def test_bentuk_keempat_TANPA_geseran_jam(self):
        """Jam sudah WIB — dibuktikan pada 339 baris LTN 12-08-2026: panel
        menyetujui median +3 detik setelah `date`, p10/p90 +2/+6 detik, dan NOL
        baris bernilai negatif. Geseran +7 jam ala ZPay akan membalik semuanya
        jadi negatif dan memblokir pass 0 lewat jendela tanggal berarah."""
        r = self._parse([FLYER_KEEMPAT,
                         _baris_keempat(tanggal="2026-08-12 23:59:17.0")])[0]

        self.assertEqual(str(r["occurred_at"]), "2026-08-12 23:59:17")
        self.assertEqual(str(r["posted_date"]), "2026-08-12")

    def test_row_hash_SAMA_dengan_bentuk_lama(self):
        """Satu transaksi logis, empat bentuk berkas, satu hash."""
        lama = self._parse([FLYER_LAMA,
                            ["2026-08-12 13:30:59", "2026-08-12 13:31:02",
                             "D2506425", "D260812119700084141", "Pablo007",
                             "SUCCESS", "50000.00"]])[0]
        keempat = self._parse([FLYER_KEEMPAT, _baris_keempat()])[0]

        self.assertEqual(lama["row_hash"], keempat["row_hash"])

    def test_beda_huruf_besar_kecil_dan_pemisah_TAK_lagi_soal(self):
        """Inti pertahanan barunya: kolom dicocokkan setelah dinormalkan
        (huruf kecil, tanpa spasi/garis bawah/tanda baca). `Date`, `date`,
        `DATE`, dan `Total_Amount` karena itu tak perlu entri baru — dan bentuk
        yang SUDAH ada di produksi (BSW/M25 memakai `Date`) ikut sembuh."""
        r = self._parse([["DATE", "CLIENT_REFF", "Transaction_ID", "RRN",
                          "USERNAME", "Total Amount", "Charges", "net_amount",
                          "rate_merchant"],
                         _baris_keempat()])[0]

        self.assertEqual(r["ticket_no"], "D2506425")
        self.assertEqual(r["reference"], "D260812119700084141")
        self.assertEqual(r["username"], "Pablo007")
        self.assertEqual(str(r["amount"]), "50000.00")
        self.assertEqual(str(r["posted_date"]), "2026-08-12")

    def test_normalisasi_TIDAK_boleh_mencocokkan_sebagian(self):
        """`net_amount` menormal jadi 'netamount', BUKAN 'amount'. Kalau
        pencocokan diubah jadi substring, kolom net akan menelan kolom bruto
        dan tiap baris meleset sebesar fee — tanpa error di mana pun."""
        peta = QRFlyerParser._petakan(["net_amount", "total_amount"])

        self.assertEqual(peta["amount"], "total_amount")

    def test_header_tanpa_kolom_waktu_APA_PUN_melempar(self):
        """Justru gerbang yang absen saat bentuk keempat datang. Tanpa waktu,
        baris yang dihasilkan mustahil dicocokkan — dan diamnya jauh lebih
        mahal daripada unggahan yang ditolak."""
        with self.assertRaises(ValueError) as ctx:
            self._parse([["Client Reff", "transaction_id", "rrn", "username",
                          "total_amount", "charges"],
                         ["D260812", "D2506425", "r1", "Pablo007", "50000", "600"]])

        pesan = str(ctx.exception)
        self.assertIn("waktu", pesan.lower())
        self.assertIn("transaction_id", pesan)   # header nyata disebut
        self.assertIn("Created At", pesan)       # yang dikenal disebut

    def test_kolom_settlement_SAJA_tidak_melempar(self):
        """`posted_date` = (settled or created), jadi berkas yang hanya membawa
        waktu settlement tetap sah. Gerbangnya 'salah satu', bukan 'created'."""
        r = self._parse([["Callback", "Transaction Id", "Client Reference",
                          "Username", "Amount"],
                         ["2026-08-12 13:31:02", "D2506425",
                          "D260812119700084141", "Pablo007", 50000]])[0]

        self.assertEqual(str(r["posted_date"]), "2026-08-12")
        self.assertIsNone(r["occurred_at"])

    def test_deteksi_bentuk_keempat_berkeyakinan_tinggi(self):
        """Sebelum ini bentuk keempat cuma lolos lewat aturan nama file (0,85)
        — celah yang sama persis dengan bentuk ketiga dulu."""
        path = _xlsx([FLYER_KEEMPAT, _baris_keempat()])
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

    # --- Penamaan status KETIGA vendor: `done` (berkas STN 11-08-2026) ------

    def test_status_DONE_terbaca_penuh_dan_unpaid_dilewati(self):
        """Vendor mengganti penamaan statusnya lagi: 565 baris `done` (uang)
        berdampingan dengan 42 `unpaid` (QRIS ditinggalkan pemain).

        `done` sekelas `paid`/`settled`: 564 dari 565 baris itu berpasangan
        dengan panel 11-08-2026 pada tiket, nominal, username, DAN Order
        ID-nya muncul di kolom Remarks panel — nol beda. Yang satu lagi
        (D3298751, dibayar 23:59:59 WIB) memang milik panel 12-Agustus.
        Campuran begini TIDAK boleh melempar: ada hasil, penjaga diam.
        """
        rows = self._parse([ZPAY,
                            _baris_zpay(ticket="D3298751", status="done",
                                        order="STN-jourseva-wa1bb3itoieux"),
                            _baris_zpay(ticket="", paid="", status="unpaid",
                                        order="STN-dienboele-s1o8sesqs933a"),
                            _baris_zpay(ticket="D3298750", status="done",
                                        order="STN-Golexrezeki-6lxh4f13mnpbn")])

        self.assertEqual([r["ticket_no"] for r in rows], ["D3298751", "D3298750"])
        self.assertEqual(rows[0]["username"], "jourseva")

    def test_baris_done_tetap_kena_geseran_utc_ke_wib(self):
        """Penamaan statusnya berubah, zona waktunya tidak.

        Baris pertama berkas nyata STN: Paid At 16:59:59 = 23:59:59 WIB,
        masih hari 11-Agustus. Tanpa geseran ia jatuh 16:59 dan uangnya
        mendahului kreditnya tujuh jam — pasangannya diblokir jendela
        tanggal berarah engine.
        """
        r = self._parse([ZPAY, _baris_zpay(ticket="D3298751", status="done",
                                           created="2026-08-11 16:58:48",
                                           paid="2026-08-11 16:59:59")])[0]

        self.assertEqual(str(r["occurred_at"]), "2026-08-11 23:59:59")
        self.assertEqual(str(r["posted_date"]), "2026-08-11")
        # Jejak audit: salinan mentah tetap jam asli vendor (UTC).
        self.assertEqual(r["raw"]["Paid At"], "2026-08-11 16:59:59")
        self.assertEqual(r["raw"]["Status"], "done")

    def test_row_hash_done_SAMA_dengan_paid(self):
        """Satu transaksi logis, dua penamaan status → satu hash. Kalau tidak,
        hari yang sama yang diekspor ulang dengan penamaan baru masuk DUA
        KALI alih-alih terdeteksi duplikat."""
        a = self._parse([ZPAY, _baris_zpay(ticket="D3298750", status="paid")])[0]
        b = self._parse([ZPAY, _baris_zpay(ticket="D3298750", status="done")])[0]

        self.assertEqual(a["row_hash"], b["row_hash"])

    def test_berkas_SELURUHNYA_unpaid_tetap_MELEMPAR(self):
        """Keputusan sadar, bukan kelalaian.

        `unpaid` = QRIS yang ditinggalkan pemain (42 baris berkas nyata: nol
        tiket, nol Paid At, nol RRN) — bukan uang, memang ditahan. Tapi ia
        tetap membawa `Order ID`, jadi tetap terhitung baris transaksi:
        berkas yang isinya cuma itu tak membawa uang SAMA SEKALI, dan
        gagal-berisik lebih baik daripada unggahan "berhasil" berisi nol
        baris — kegagalan senyap yang persis bug QR Flyer. Pengguna melihat
        pesannya lalu mengunggah ekspor yang lengkap.
        """
        with self.assertRaises(ValueError) as ctx:
            self._parse([ZPAY,
                         _baris_zpay(ticket="", paid="", status="unpaid",
                                     order="STN-dienboele-s1o8sesqs933a"),
                         _baris_zpay(ticket="", paid="", status="unpaid",
                                     order="STN-rahmadani-9k2jd0slam3x")])

        pesan = str(ctx.exception)
        self.assertIn("2", pesan)            # berapa baris yang tertahan
        self.assertIn("'unpaid'", pesan)     # status yang ditemukan

    def test_pesan_berkas_unpaid_TIDAK_menuduh_vendor(self):
        """Diagnosis yang salah lebih berbahaya daripada tak ada pesan.

        `unpaid` SUDAH dikenal dan sengaja ditahan. Menyuruh pengguna
        "laporkan ke pengembang agar daftarnya ditambah" mengarahkan rantai
        yang berakhir fatal: operator melapor "vendor ganti status jadi
        unpaid" → `unpaid` masuk `STATUS_UANG` → 42 baris QRIS yang tak
        pernah dibayar berubah jadi baris uang. Uang dikarang — persis yang
        dicegah rancangan daftar putih ini. Pesannya harus mengatakan apa
        adanya: berkasnya memang tak memuat pembayaran sukses.
        """
        with self.assertRaises(ValueError) as ctx:
            self._parse([ZPAY,
                         _baris_zpay(ticket="", paid="", status="unpaid",
                                     order="STN-dienboele-s1o8sesqs933a"),
                         _baris_zpay(ticket="", paid="", status="UNPAID",
                                     order="STN-rahmadani-9k2jd0slam3x")])

        pesan = str(ctx.exception)
        self.assertIn("pembayaran sukses", pesan)   # diagnosis yang benar
        self.assertNotIn("laporkan", pesan.lower())  # jangan menuduh vendor
        self.assertNotIn("ditambah", pesan.lower())
        self.assertNotIn("done", pesan)              # daftar putih tak relevan

    def test_status_asing_SESUDAH_done_tetap_MELEMPAR(self):
        """Pelindung dari penamaan KEEMPAT tetap penjaga nol-hasil ini, bukan
        daftar putih yang dipanjangkan menebak-nebak."""
        with self.assertRaises(ValueError) as ctx:
            self._parse([ZPAY, _baris_zpay(ticket="D1", status="refunded")])

        pesan = str(ctx.exception)
        self.assertIn("'refunded'", pesan)   # status yang ditemukan disebut
        self.assertIn("done", pesan)         # daftar putih terbaru disebut
        self.assertIn("laporkan", pesan.lower())  # jalur yang benar utk kasus ini

    def test_campuran_unpaid_dan_status_ASING_dianggap_kasus_asing(self):
        """Satu status asing sudah cukup: yang tak dikenal itulah beritanya,
        dan `unpaid` di sebelahnya tak boleh menyembunyikannya di balik pesan
        "tak ada pembayaran sukses"."""
        with self.assertRaises(ValueError) as ctx:
            self._parse([ZPAY,
                         _baris_zpay(ticket="", paid="", status="unpaid",
                                     order="STN-dienboele-s1o8sesqs933a"),
                         _baris_zpay(ticket="D1", status="refunded")])

        pesan = str(ctx.exception)
        self.assertIn("'refunded'", pesan)
        self.assertIn("laporkan", pesan.lower())
