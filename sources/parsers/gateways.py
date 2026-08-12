"""Parser gateway pembayaran (sumber UANG, setara bank): NXPAY, QR FLYER, QHOKI, RPAY."""
import csv
from datetime import timedelta
from decimal import Decimal

from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_grid, read_xlsx_rows, row_hash


def _money(amount, flow):
    """Tanda money_delta berdasarkan flow file (dp = masuk +, wd = keluar -)."""
    return -amount if flow == "wd" else amount


class NXPayParser(BaseParser):
    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=2)  # baris 1 = judul report
        out = []
        for r in rows:
            ticket = str(r.get("Ticket Number", "") or "").strip()
            if not ticket or "total" in str(r.get("Username", "")).lower():
                continue  # skip footer / Grand Total
            amt = abs(parse_decimal(r.get("Amount")))
            occurred = parse_dt(r.get("Date"))  # format US: M/D/YYYY h:m:s AM/PM
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": _money(amt, flow),
                "fee": parse_decimal(r.get("Admin Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get("Username", "") or "").strip(),
                "reference": "",
                "counterparty": str(r.get("Account Title", "") or "").strip(),
                "description": f"NXPAY {r.get('Payment Type','')} {r.get('Status','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("nxpay", [ticket, row["username"], amt, occurred])
            out.append(row)
        return out


class QRFlyerParser(BaseParser):
    """QR FLYER — TIGA bentuk header, dipetakan lewat daftar alias.

    Vendornya mengganti penamaan kolom berulang kali sejak Agustus 2026, jadi
    kolom dikenali dari DAFTAR nama yang mungkin, bukan dua cabang mati:

        tiket panel  : TXN ID | transaction_id | Transaction Id
        referensi    : Client Reference | client_reference
        pemain       : Customer ID / User Account | username | Username
        nominal      : Transaction Value | total_amount | Amount
        waktu buat   : Transaction Date | trans_date_time | Created At
        waktu settle : Settlement Time | bot_success_time | Callback

    Ketiga bentuk memakai jam WIB — dibuktikan pada bentuk ketiga (HKW
    01-08-2026): `Created At` merentang penuh 00:00:36–23:59:45 dan panel
    menyetujui median 4 detik setelah `Callback`. Tak ada geseran, tidak
    seperti ZPay.

    **Penjaga header:** bila kolom tiket ATAU nominal tak ditemukan, parser
    MELEMPAR sambil menyebut header yang benar-benar ada. Ini pelajaran mahal
    dan bentuknya berbeda dari penjaga nol-hasil ZPay: bentuk ketiga tetap
    punya `Client Reference`, jadi baris TIDAK dilewati sebagai footer —
    parser menghasilkan 1.519 baris LENGKAP tapi kosong melompong (tiket ''),
    nominal Rp0, tanpa tanggal. Sampah yang lolos jauh lebih berbahaya
    daripada nol baris: ia mengaku data. Lima unggahan di empat toko sudah
    terlanjur memasukkan 6.118 baris seperti itu ke produksi (untung inert —
    nol terpakai batch, nol hasil pencocokan) sebelum ini ketahuan.

    `row_hash` sengaja memakai resep yang SAMA untuk semua bentuk (nilainya
    identik), supaya berkas yang sama diekspor ulang dalam bentuk lain tetap
    terdeteksi duplikat terhadap unggahan sebelumnya.
    """

    source_key = "gateway"

    #: bidang kanonik -> nama kolom yang mungkin dipakai vendor, urut prioritas
    _ALIAS = {
        "ticket": ("TXN ID", "transaction_id", "Transaction Id"),
        "ref": ("Client Reference", "client_reference"),
        "username": ("Customer ID / User Account", "username", "Username"),
        "amount": ("Transaction Value", "total_amount", "Amount"),
        "created": ("Transaction Date", "trans_date_time", "Created At"),
        "settled": ("Settlement Time", "bot_success_time", "Callback"),
        "status": ("Payment Status", "status"),
        "fee": ("Fee",),
    }
    #: tanpa kedua ini berkasnya bukan laporan Flyer yang bisa dipercaya
    _WAJIB = ("ticket", "amount")

    @classmethod
    def _petakan(cls, header):
        """{bidang kanonik: nama kolom nyata} untuk yang ketemu di header."""
        ada = [h for h in (header or []) if h]
        return {bidang: next((n for n in nama if n in ada), None)
                for bidang, nama in cls._ALIAS.items()}

    def parse(self, path, flow=""):
        header, rows = read_xlsx_rows(path, header_row=1)
        peta = self._petakan(header)
        hilang = [b for b in self._WAJIB if not peta[b]]
        if hilang:
            raise ValueError(
                "Laporan QR Flyer tak dikenali: kolom %s tidak ditemukan. "
                "Header berkas: %s. Kolom yang dikenal untuk %s. Kirimkan "
                "berkasnya ke pengembang agar bentuk barunya ditambahkan."
                % (" dan ".join(hilang),
                   ", ".join(repr(h) for h in (header or []) if h) or "(kosong)",
                   "; ".join("%s = %s" % (b, "/".join(self._ALIAS[b]))
                             for b in self._WAJIB))
            )
        kol = lambda bidang: peta[bidang] or "\x00"  # noqa: E731 - kolom absen = selalu None
        out = []
        for r in rows:
            amt = abs(parse_decimal(r.get(kol("amount"))))
            occurred = parse_dt(r.get(kol("created")))
            settle = parse_dt(r.get(kol("settled")))
            ticket = str(r.get(kol("ticket"), "") or "").strip()
            ref = str(r.get(kol("ref"), "") or "").strip()
            if not ticket and not ref:  # skip footer/total
                continue
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": (settle or occurred).date() if (settle or occurred) else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": _money(amt, flow),
                "fee": parse_decimal(r.get(kol("fee"))),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get(kol("username"), "") or "").strip(),
                "reference": ref,
                "counterparty": "",
                "description": f"QRFLYER {r.get(kol('status'), '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("qrflyer", [ticket, ref, amt])
            out.append(row)
        return out


class ZPayParser(BaseParser):
    """QRIS ZPay / ZETPAY (CSV) — gateway QRIS baru, panel Nexus (mis. M25).

    Kunci exact: kolom `Tiket Number` (D…) = Ticket Number panel → pass 0.
    `Order ID` berpola ``<BRAND>-<username>-<acak>``; username diambil dari
    segmen TENGAH — digabung kembali, bukan `split("-")[1]`, karena username
    boleh memuat tanda hubung.

    `Nilai` = bruto yang dibayar pemain (= `Fee` + `Sub Total`, dijaga tes);
    panel mencatat bruto juga, jadi itu yang dipakai sebagai `amount`.

    **`Status` punya TIGA nilai yang sama-sama berarti uang nyata: `paid`,
    `settled`, dan `done`** — satu daur hidup, bukan hal-hal berbeda (`paid`
    = sudah dibayar, dananya belum cair; `settled` = sudah cair, `Waktu
    Settled`-nya sudah lewat; `done` = penamaan baru vendor sejak Agustus
    2026, sekelas keduanya). Ketiganya terbukti dengan data nyata: 69 baris
    `settled` sampel 06-08-2026 cocok dengan panel 69/69 pada tiket, Order
    ID, DAN nominal; berkas STN 11-08-2026 berisi 565 baris `done` yang
    564 di antaranya cocok dengan panel hari itu pada tiket, nominal,
    username, DAN Order ID-nya muncul di Remarks panel — nol beda (sisa
    satu, D3298751, dibayar 23:59:59 WIB dan memang milik panel 12-Agustus).

    Lawannya di berkas yang sama adalah `unpaid` (42 baris): QRIS yang
    ditinggalkan pemain — nol tiket, nol `Paid At`, nol RRN, `Status
    Settled` = Unsettled. Itu BUKAN uang dan sengaja ditahan.

    Daftar putih ini sengaja TIDAK ditebak-lebihkan ("success", "complete",
    dst.) — yang menjaga dari nilai keempat adalah penjaga nol-hasil di
    bawah, bukan daftar yang dipanjangkan. Menyaring dengan daftar hitam
    justru berbahaya: status asing yang lolos masuk MENGARANG uang di
    aplikasi rekonsiliasi, sementara status asing yang tertahan setidaknya
    muncul sebagai baris panel tanpa uang di kerja harian.

    **Penjaga nol-hasil:** bila berkas memuat baris transaksi tapi tak satu
    pun lolos, parser MELEMPAR — bukan mengembalikan daftar kosong. Versi
    pertama menyaring `== "paid"` saja dan menelan bulat-bulat 69 baris
    berstatus `settled`: berkas dilaporkan "berhasil diunggah" dengan nol
    baris, kegagalan senyap yang sama persis dengan bug QR Flyer. Ini bukan
    dugaan berbasis kebiasaan seperti `web/penjaga.py` (yang sengaja hanya
    memperingatkan) melainkan kepastian — ada baris, tak ada hasil — jadi
    memblokir memang tepat. Berkas tanpa baris transaksi tetap sah kosong.
    Saat vendor mengganti nama status jadi `done`, penjaga inilah yang
    BERBUNYI dan memunculkan laporan penggunanya — berkas 11-08-2026 ditolak
    dengan pesan yang menyebut status yang ditemukan, bukan diterima diam-diam
    berisi nol baris. Rancangannya bekerja persis seperti maksudnya. Karena
    itu pula berkas yang SELURUH barisnya `unpaid` tetap melempar: ia memang
    tak membawa uang sama sekali, dan gagal-berisik lebih baik daripada
    unggahan "berhasil" yang kosong.

    **Penjaga itu punya DUA pesan, dan memilih yang salah berbahaya.** Bila
    semua status yang ditemukan ada di `STATUS_BUKAN_UANG` (kini hanya
    `unpaid`), berkasnya memang tak memuat satu pun pembayaran sukses —
    lazim pada tarikan setengah hari, jam sepi, atau merchant baru. Pesannya
    harus mengatakan itu apa adanya dan TIDAK menyuruh menambah daftar
    status: `unpaid` sudah dikenal dan sengaja ditahan. Pesan "vendor
    mengganti penamaan status, laporkan ke pengembang" pada kasus ini
    mengarahkan rantai yang berakhir fatal — operator melapor "vendor ganti
    status jadi unpaid", `unpaid` masuk `STATUS_UANG`, dan 42 baris QRIS yang
    tak pernah dibayar berubah jadi baris uang. Uang dikarang, persis yang
    dicegah rancangan daftar putih ini. Pesan lapor-pengembang tetap dipakai
    (dan hanya) saat ada status yang benar-benar asing — termasuk campuran
    `unpaid` + status asing, karena yang tak dikenal itulah beritanya.

    **Jam laporan ZETPAY adalah UTC, panel WIB — WAJIB digeser +7 jam.**
    Buktinya berlapis pada sampel 06-08-2026 dan tak punya penjelasan lain:
    panel yang mencakup penuh 06-Agu berisi 69 baris QRISZPAY dan NOL dari 48
    `Order ID` berkas ini; blok tiketnya terputus rapi dan bersambung (panel
    berhenti D770354, berkas mulai D770355) padahal tiket panel dipakai
    bersama semua kanal; dan setelah digeser +7 jam D770355 jatuh 1 menit 44
    detik setelah D770354 — sedangkan tanpa geseran ia mendahuluinya 7 jam.
    Tiket pun naik monoton mengikuti `Created At` (1 inversi sedetik dari 47
    pasang). Tanpa koreksi ini uangnya tercatat 7 jam lebih awal daripada
    kreditnya, sehingga jendela tanggal berarah engine (uang >= kredit)
    MEMBLOKIR pasangannya — bukan sekadar salah hari. `raw` sengaja menyimpan
    nilai asli vendor; yang digeser hanya `occurred_at`/`posted_date`.

    Belum ada sampel WD — `flow` tetap dihormati (arah `money_delta`), tapi
    jalur itu belum pernah diuji dengan berkas nyata.
    """

    source_key = "gateway"
    UTC_KE_WIB = timedelta(hours=7)
    STATUS_UANG = ("paid", "settled", "done")
    # Status yang DIKENAL tapi memang bukan uang: QRIS yang dibuat lalu
    # ditinggalkan pemain (42 baris berkas STN 11-08-2026 — nol tiket, nol
    # `Paid At`, nol RRN, `Status Settled` = Unsettled). Dipisahkan dari status
    # asing semata-mata supaya penjaga nol-hasil di bawah tidak salah
    # mendiagnosis; ia TIDAK ikut menentukan baris mana yang lolos.
    STATUS_BUKAN_UANG = ("unpaid",)

    @staticmethod
    def _username(order_id):
        bagian = str(order_id or "").split("-")
        return "-".join(bagian[1:-1]).strip() if len(bagian) >= 3 else ""

    def parse(self, path, flow=""):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
        out, kandidat, status_terlihat = [], 0, []
        for r in rows:
            order = str(r.get("Order ID", "") or "").strip()
            ticket = str(r.get("Tiket Number", "") or "").strip()
            if not order and not ticket:
                continue  # judul/penutup, bukan baris transaksi
            kandidat += 1
            status = str(r.get("Status", "") or "").strip().lower()
            if status not in status_terlihat:
                status_terlihat.append(status)
            if status not in self.STATUS_UANG:
                continue
            amt = abs(parse_decimal(r.get("Nilai")))
            occurred = parse_dt(r.get("Paid At")) or parse_dt(r.get("Created At"))
            if occurred:
                occurred += self.UTC_KE_WIB  # lihat docstring: laporan vendor UTC
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": _money(amt, flow),
                "fee": parse_decimal(r.get("Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": self._username(order),
                "reference": order,
                "counterparty": "",
                "description": f"ZPAY {r.get('Payment Method','')} {r.get('RRN','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("zpay", [order, ticket, amt])
            out.append(row)
        if kandidat and not out:
            terlihat = ", ".join(repr(s) for s in status_terlihat)
            if all(s in self.STATUS_BUKAN_UANG for s in status_terlihat):
                # Semua statusnya dikenal dan memang ditahan — bukan salah
                # vendor, bukan salah daftar. Jangan pernah mengarahkan ke
                # "tambahkan statusnya": lihat docstring, ujungnya uang dikarang.
                raise ValueError(
                    "Berkas ZPay memuat %d baris transaksi tetapi tak satu pun "
                    "berisi pembayaran sukses — semuanya berstatus %s, yaitu QRIS "
                    "yang dibuat lalu ditinggalkan pemain (tanpa nomor tiket, "
                    "tanpa waktu bayar). Tidak ada yang bisa dicatat. Periksa "
                    "apakah periode atau berkas yang diunduh sudah benar."
                    % (kandidat, terlihat)
                )
            raise ValueError(
                "Berkas ZPay memuat %d baris transaksi tetapi tak satu pun "
                "berstatus uang. Status yang ditemukan: %s. Status yang dikenal: "
                "%s. Kemungkinan vendor mengganti penamaan status — laporkan ke "
                "pengembang agar daftarnya ditambah."
                % (kandidat, terlihat, ", ".join(self.STATUS_UANG))
            )
        return out


class QHokiParser(BaseParser):
    """QRIS HOKI (gateway brand panel-Nexus: MUL/WLG/LBS). Whitelabel Transaction
    ID = Ticket Panel (D...), Transaction ID = UUID (juga muncul di Remarks panel).
    Sebagian brand mengekspornya sebagai CSV quoted (kolom identik xlsx)."""

    source_key = "gateway"

    def parse(self, path, flow=""):
        if str(path).lower().endswith(".csv"):
            with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
                rows = list(csv.DictReader(f))
        else:
            _, rows = read_xlsx_rows(path, header_row=1)
        out = []
        for r in rows:
            if str(r.get("Status", "") or "").strip().lower() != "success":
                continue
            wl = str(r.get("Whitelabel Transaction ID", "") or "").strip()
            txid = str(r.get("Transaction ID", "") or "").strip()
            if not wl and not txid:
                # Tanpa identitas apa pun row_hash cuma bergantung nominal ->
                # baris senominal saling tabrak & terbuang diam-diam. Skip.
                continue
            amt = abs(parse_decimal(r.get("Amount")))
            occurred = parse_dt(r.get("Transaction Date"))
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if flow == "wd" else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": _money(amt, flow),
                "fee": parse_decimal(r.get("Downline Fee Amount")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": wl,
                "username": str(r.get("Member ID", "") or "").strip(),
                "reference": txid,
                "counterparty": "",
                "description": f"QHOKI {r.get('Rrn','')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items()},
            }
            row["row_hash"] = row_hash("qhoki", [txid, wl, amt])
            out.append(row)
        return out


class RPayGatewayParser(BaseParser):
    """Gateway QRIS RPay (CSV, dipakai brand panel-Nexus, mis. MUL/M77).

    Membawa `Customer Username` == username panel -> anchor pass-1 username
    exact. `UUID` DISIMPAN di raw saja, TIDAK di `reference`: aturan blocked
    engine mengasingkan gateway ber-reference yang tak dikenal panel dari pass
    identitas, dan panel Nexus TERBUKTI tidak menanam UUID RPay di Remarks
    (verifikasi panel M77 09-Jul-2026: 0 dari 2.058 baris QRISRPAY).
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            raw_rows = list(csv.DictReader(f))
        is_wd = flow == "wd"
        out = []
        for r in raw_rows:
            uuid = str(r.get("UUID", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not uuid or status != "success":
                continue
            # abs: tanda ditentukan flow (konsisten parser gateway lain);
            # dayfirst: vendor Indonesia, 09/07 = 9 Juli (format bernama-bulan
            # "09 Jul 2026" tak terpengaruh).
            amt = abs(parse_decimal(r.get("Amount")))
            occurred = parse_dt(r.get("Date"), dayfirst=True)
            username = str(r.get("Customer Username", "") or "").strip()
            cname = str(r.get("Customer Name", "") or "").strip()
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd" if is_wd else "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt if is_wd else amt,
                "fee": parse_decimal(r.get("Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                "reference": "",
                "counterparty": "" if cname.lower() == username.lower() else cname,
                "description": f"RPay {r.get('RRN', '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items() if k},
            }
            row["row_hash"] = row_hash("rpay", [uuid, amt])
            out.append(row)
        return out


class RPayWDGatewayParser(BaseParser):
    """Gateway RafflesPay sisi WD/disbursement (CSV, brand panel-Nexus mis. BBS/BO7).

    Beda dari `RPayGatewayParser` (rail DP: anchor `Customer Username` == username
    panel). Laporan disbursement ini TANPA username — kunci pasti = `External ID`
    (nomor tiket `W...`) == `Ticket Number` panel WD -> pass 0 ticket-join engine
    (pola sama NXPay/QHoki). `UUID` RafflesPay DISIMPAN di raw saja, TIDAK di
    `reference`: Remarks panel Nexus terbukti tak memuatnya, dan aturan blocked
    engine mengasingkan gateway ber-reference asing dari pencocokan (pelajaran
    sama dgn RPay DP). `Disbursed Amount` = uang riil keluar (== Withdrawal Amount
    panel, terverifikasi 12-07-2026). Hanya baris `Transfer Status` = Success
    (uang benar-benar keluar); selalu WD (`flow` diabaikan).
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            rows = list(csv.DictReader(f))
        out = []
        for r in rows:
            ticket = str(r.get("External ID", "") or "").strip()
            # Transfer Status = Success => uang benar-benar keluar. Ini satu-satunya
            # penentu (deteksi pun mengunci token "transfer status", jadi konsisten:
            # tak ada baris tersaring diam-diam karena kolom lain hilang).
            transfer = str(r.get("Transfer Status", "") or "").strip().lower()
            if not ticket or transfer != "success":
                continue
            amt = abs(parse_decimal(r.get("Disbursed Amount")))
            occurred = parse_dt(r.get("Date"), dayfirst=True)
            # Selalu WD: laporan disbursement tak pernah jadi deposit. `flow`
            # diabaikan supaya salah-pilih DP di UI tak bisa membalik tanda.
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt,
                "fee": parse_decimal(r.get("Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": "",
                "reference": "",
                "counterparty": str(r.get("Account Name", "") or "").strip(),
                "description": f"RPAY WD {r.get('Bank Name', '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items() if k},
            }
            # UUID RafflesPay unik per percobaan disbursement; + ticket sebagai
            # cadangan. TANPA nominal supaya idempotensi tak goyah oleh format
            # angka ("1000000" vs "1000000.0" vs "1000000.00").
            row["row_hash"] = row_hash(
                "rpay_wd", [str(r.get("UUID", "") or "").strip(), ticket])
            out.append(row)
        return out


class RPayDPXlsxParser(BaseParser):
    """Gateway RafflesPay sisi DP, varian XLSX (brand panel-Nexus mis. BBS).

    Beda dari `rpay` (CSV ber-`Customer Username`/`UUID`): varian ini laporan
    "Deposit QRIS" panel ber-gateway RafflesPay yang membawa `Ticket Number`
    (D...) == panel DP -> pass 0 ticket-join engine. `RRN` DISIMPAN di raw
    saja, TIDAK di `reference`: ada duplikat nyata (9 dari 1.233, sampel BBS
    16-07-2026) dan aturan blocked engine mengasingkan reference asing.
    `Amount (IDR)` sudah rupiah penuh (`Amount (Chip)` = ribuan versi panel —
    JANGAN dipakai). Baris `Status=Success` diambil TERMASUK yang
    `Ticket Status=failed`: uang masuk tanpa kredit panel harus muncul sebagai
    "Tidak Ada di Panel", bukan hilang di parser. Selalu DP: `flow` diabaikan.
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path)
        out = []
        for r in rows:
            ticket = str(r.get("Ticket Number", "") or "").strip()
            status = str(r.get("Status", "") or "").strip().lower()
            if not ticket or status != "success":
                continue
            amt = abs(parse_decimal(r.get("Amount (IDR)")))
            occurred = parse_dt(r.get("Date"), dayfirst=True)
            rrn = str(r.get("RRN", "") or "").strip()
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "depo",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": amt,
                "fee": parse_decimal(r.get("Admin Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get("Player", "") or "").strip(),
                "reference": "",
                "counterparty": "",
                "description": f"RPAY QR {rrn}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items() if k},
            }
            row["row_hash"] = row_hash("rpay_xlsx", [ticket, rrn])
            out.append(row)
        return out


class RPayWDXlsxParser(BaseParser):
    """Gateway RafflesPay sisi WD, varian XLSX header dua-tingkat (brand BBS).

    Beda dari `rpay_wd` (CSV ber-`External ID`/`Transfer Status`): header grup
    di baris 1 (Beneficiary / Amount / Status) + sub-kolom di baris 2 (Bank,
    Name, Number / Amount, Disbursed Amount, Fee / Status, Approve, Reject,
    Transfer), data mulai baris 3 -> di-flatten manual (sub-kolom menang bila
    terisi). Kunci pasti = `Ticket` (W...) == `Ticket Number` panel WD -> pass
    0. Hanya baris `Transfer=success` (uang benar-benar keluar). `Disbursed
    Amount` = uang riil keluar. `Beneficiary Number` (nomor rekening/e-wallet
    tujuan) tersimpan di raw. Selalu WD: `flow` diabaikan.
    """

    source_key = "gateway"

    def parse(self, path, flow=""):
        grid = read_xlsx_grid(path)
        if len(grid) < 3:
            return []
        top, sub = grid[0], grid[1]
        width = max(len(top), len(sub))

        def _cell(row, i):
            v = row[i] if i < len(row) else None
            return str(v).strip() if v is not None else ""

        headers = [(_cell(sub, i) or _cell(top, i)) for i in range(width)]
        out = []
        for raw_row in grid[2:]:
            r = {h: c for h, c in zip(headers, raw_row) if h}
            ticket = str(r.get("Ticket", "") or "").strip()
            transfer = str(r.get("Transfer", "") or "").strip().lower()
            if not ticket or transfer != "success":
                continue
            amt = abs(parse_decimal(r.get("Disbursed Amount")))
            occurred = parse_dt(r.get("Date"), dayfirst=True)
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": "wd",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt,
                "fee": parse_decimal(r.get("Fee")),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get("Player", "") or "").strip(),
                "reference": "",
                "counterparty": str(r.get("Name", "") or "").strip(),
                "description": f"RPAY WD {r.get('Bank', '')}".strip(),
                "raw": {k: ("" if v is None else str(v)) for k, v in r.items() if k},  # Nomor tujuan (rekening/e-wallet) ada di raw["Number"] — kunci hasil flatten, BUKAN "Beneficiary Number".
            }
            # ID RafflesPay unik per baris; + ticket cadangan. TANPA nominal
            # supaya idempotensi tak goyah oleh variasi format angka.
            row["row_hash"] = row_hash(
                "rpay_wd_xlsx", [str(r.get("ID", "") or "").strip(), ticket])
            out.append(row)
        return out
