"""Parser gateway pembayaran (sumber UANG, setara bank): NXPAY, QR FLYER, QHOKI, RPAY, KINGSPAY."""
import csv
import os
import re
from datetime import timedelta
from decimal import Decimal

from .base import BaseParser, parse_decimal, parse_dt, read_xlsx_grid, read_xlsx_rows, row_hash


def _money(amount, flow):
    """Tanda money_delta berdasarkan flow file (dp = masuk +, wd = keluar -)."""
    return -amount if flow == "wd" else amount


def _nxpay_jenis(ticket, amount_signed, flow):
    """Arah baris NXPay — ticket panel-compatible mengalahkan nama berkas.

    Staff sering menukar nama file DP/WD (bukti BTS 20-08-2026: berkas
    ``… DP NXPAY.xlsx`` berisi ticket ``W…`` / Amount negatif, dan sebaliknya).
    Ticket ``D…`` = deposit, ``W…`` = withdraw — sama dengan konvensi panel
    Nexus. Tanpa prefix D/W: ``flow`` nama file, lalu tanda ``Amount`` vendor.
    """
    t = (ticket or "").strip().upper()
    if t.startswith("W"):
        return "wd"
    if t.startswith("D"):
        return "depo"
    if flow == "wd":
        return "wd"
    if flow == "dp":
        return "depo"
    if amount_signed is not None and amount_signed < 0:
        return "wd"
    if amount_signed is not None and amount_signed > 0:
        return "depo"
    return "depo"


class NXPayParser(BaseParser):
    source_key = "gateway"

    def parse(self, path, flow=""):
        _, rows = read_xlsx_rows(path, header_row=2)  # baris 1 = judul report
        out = []
        for r in rows:
            ticket = str(r.get("Ticket Number", "") or "").strip()
            if not ticket or "total" in str(r.get("Username", "")).lower():
                continue  # skip footer / Grand Total
            signed = parse_decimal(r.get("Amount"))
            amt = abs(signed)
            jenis = _nxpay_jenis(ticket, signed, flow)
            occurred = parse_dt(r.get("Date"))  # format US: M/D/YYYY h:m:s AM/PM
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date() if occurred else None,
                "jenis": jenis,
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt if jenis == "wd" else amt,
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
    """QR FLYER — EMPAT bentuk header, dipetakan lewat daftar alias ternormalkan.

    Vendornya mengganti penamaan kolom berulang kali sejak Agustus 2026, jadi
    kolom dikenali dari DAFTAR nama yang mungkin, bukan cabang mati per bentuk:

        tiket panel  : TXN ID | transaction_id | Transaction Id
        referensi    : Client Reference | client_reference | Client Reff
        pemain       : Customer ID / User Account | username | Username
        nominal      : Transaction Value | total_amount | Amount
        waktu buat   : Transaction Date | trans_date_time | Created At | date
        waktu settle : Settlement Time | bot_success_time | Callback
        biaya        : Fee | charges

    **Pencocokan kolom dinormalkan** (huruf kecil, spasi/garis bawah/tanda baca
    dibuang) lalu dibandingkan PERSIS. Normalisasi itu meredam satu kelas
    penggantian nama tanpa perlu rilis baru — `Date`/`date`/`DATE` dan
    `total_amount`/`Total Amount` jatuh ke entri yang sama. Persis, BUKAN
    substring, dan itu penting: `net_amount` menormal jadi 'netamount' sehingga
    tak pernah tertukar dengan `amount`. Kalau tertukar, tiap baris meleset
    sebesar fee dan pass 0 gagal tanpa satu pun pesan error.

    Keempat bentuk memakai jam WIB — dibuktikan pada bentuk ketiga (HKW
    01-08-2026: panel menyetujui median 4 detik setelah `Callback`) dan diuji
    ulang mandiri pada bentuk keempat (LTN 12-08-2026: 339 baris, median +3
    detik, p10/p90 +2/+6, NOL selisih negatif). Tak ada geseran, tidak seperti
    ZPay.

    **Penjaga header — tiga bidang, dan bidang ketiganya ditambahkan mahal.**
    Bila kolom tiket, nominal, ATAU seluruh kolom waktu tak ditemukan, parser
    MELEMPAR sambil menyebut header yang benar-benar ada. Dua kegagalan senyap
    mengajarkan bentuknya:

    * Bentuk ketiga (v1.17): `Client Reference` masih ada sehingga baris tidak
      dilewati sebagai footer — parser menghasilkan 1.519 baris LENGKAP tapi
      kosong melompong (tiket '', Rp0, tanpa tanggal). Penjaga tiket+nominal
      lahir dari sini; 6.118 baris seperti itu sudah terlanjur masuk produksi.
    * Bentuk keempat (v1.18.1): tiket DAN nominal justru terbaca benar semua,
      jadi penjaga itu lolos dengan tenang. Yang hilang cuma `date` — dan itu
      saja sudah cukup: `posted_date` NULL membuat baris tak terlihat oleh
      jendela tanggal mana pun, sehingga 339 baris panel LTN berhenti di
      "Belum ada uang masuk" padahal uangnya sudah ada di database. 1.705 baris
      di dua toko (LTN 339, BSW 1.366) hilang begitu sebelum ini ketahuan.

    Gerbang waktunya "salah satu", bukan `created`: `posted_date` diturunkan
    dari `(settled or created)`, jadi berkas yang hanya membawa waktu
    settlement tetap sah.

    `row_hash` sengaja memakai resep yang SAMA untuk semua bentuk (nilainya
    identik), supaya berkas yang sama diekspor ulang dalam bentuk lain tetap
    terdeteksi duplikat terhadap unggahan sebelumnya.
    """

    source_key = "gateway"

    #: bidang kanonik -> nama kolom yang mungkin dipakai vendor, urut prioritas.
    #: Dibandingkan setelah `_norm`, jadi varian huruf besar/kecil dan
    #: spasi-vs-garis-bawah TIDAK perlu entri sendiri.
    _ALIAS = {
        "ticket": ("TXN ID", "transaction_id", "Transaction Id"),
        "ref": ("Client Reference", "Client Reff"),
        "username": ("Customer ID / User Account", "username", "Username"),
        "amount": ("Transaction Value", "total_amount", "Amount"),
        # `date` paling belakang: nama paling umum, jadi paling gampang salah
        # rebut kalau berkasnya kebetulan punya kolom waktu yang lebih spesifik.
        "created": ("Transaction Date", "trans_date_time", "Created At", "date"),
        "settled": ("Settlement Time", "bot_success_time", "Callback"),
        "status": ("Payment Status", "status"),
        "fee": ("Fee", "charges"),
    }
    #: tanpa ketiganya berkasnya bukan laporan Flyer yang bisa dipercaya
    _WAJIB = ("ticket", "amount")
    #: minimal SALAH SATU harus ada — tanpa waktu, barisnya mustahil dicocokkan
    _WAJIB_WAKTU = ("created", "settled")

    @staticmethod
    def _norm(nama):
        """'Client Reff' / 'client_reff' / 'CLIENT REFF' -> 'clientreff'."""
        return re.sub(r"[^a-z0-9]", "", str(nama or "").lower())

    @classmethod
    def _petakan(cls, header):
        """{bidang kanonik: nama kolom nyata} untuk yang ketemu di header."""
        ada = {}
        for h in (header or []):
            if h:
                ada.setdefault(cls._norm(h), h)   # kemunculan pertama menang
        return {bidang: next((ada[k] for k in (cls._norm(n) for n in nama)
                              if k in ada), None)
                for bidang, nama in cls._ALIAS.items()}

    def parse(self, path, flow=""):
        header, rows = read_xlsx_rows(path, header_row=1)
        peta = self._petakan(header)
        hilang = [b for b in self._WAJIB if not peta[b]]
        if not any(peta[b] for b in self._WAJIB_WAKTU):
            hilang.append("waktu (%s)" % "/".join(self._WAJIB_WAKTU))
        if hilang:
            dikenal = list(self._WAJIB) + list(self._WAJIB_WAKTU)
            raise ValueError(
                "Laporan QR Flyer tak dikenali: kolom %s tidak ditemukan. "
                "Header berkas: %s. Kolom yang dikenal untuk %s. Kirimkan "
                "berkasnya ke pengembang agar bentuk barunya ditambahkan."
                % (" dan ".join(hilang),
                   ", ".join(repr(h) for h in (header or []) if h) or "(kosong)",
                   "; ".join("%s = %s" % (b, "/".join(self._ALIAS[b]))
                             for b in dikenal))
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


class QRISEliteParser(BaseParser):
    """QRIS ELITE CSV — gateway deposit panel Nexus.

    Baris pertama adalah judul dan baris kedua header. ``RECORD DATE`` sudah
    WIB walaupun suffix vendor rusak menjadi ``+07:00+007``; hanya 19 karakter
    tanggal-jam pertama yang dipakai. ``APPROVE`` sengaja tidak dipakai.
    """

    source_key = "gateway"
    STATUS_UANG = frozenset({"SUCCESS"})
    KOLOM_WAJIB = ("TICKET", "RECORD VALUE", "RECORD DATE")

    def parse(self, path, flow=""):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            next(reader, None)  # baris 1 = judul "MUTASI QRIS TRANSACTION"
            header = [str(h or "").strip() for h in (next(reader, None) or [])]
            peta_header = {h.casefold(): h for h in header if h}
            hilang = [h for h in self.KOLOM_WAJIB if h.casefold() not in peta_header]
            if hilang:
                raise ValueError(
                    "Laporan QRIS ELITE tak dikenali: kolom %s tidak ditemukan. "
                    "Header berkas: %s."
                    % (
                        " dan ".join(hilang),
                        ", ".join(repr(h) for h in header if h) or "(kosong)",
                    )
                )
            rows = [dict(zip(header, nilai)) for nilai in reader if any(nilai)]

        kolom = lambda nama: peta_header.get(nama.casefold(), "\x00")  # noqa: E731
        out = []
        jumlah_transaksi = 0
        status_ditemukan = set()
        for r in rows:
            ticket = str(r.get(kolom("TICKET"), "") or "").strip()
            identitas = str(r.get(kolom("ID"), "") or "").strip()
            if not ticket and not identitas:
                continue
            jumlah_transaksi += 1
            status = str(r.get(kolom("STATUS"), "") or "").strip().upper()
            status_ditemukan.add(status or "(kosong)")
            if status not in self.STATUS_UANG:
                continue

            waktu_raw = str(r.get(kolom("RECORD DATE"), "") or "").strip()
            occurred = parse_dt(waktu_raw[:19])
            if not occurred:
                raise ValueError(
                    "QRIS ELITE: RECORD DATE tidak dapat dibaca untuk tiket %s: %r."
                    % (ticket or identitas, waktu_raw)
                )
            amount = abs(parse_decimal(r.get(kolom("RECORD VALUE"))))
            fee = abs(parse_decimal(r.get(kolom("RECORD FEE"))))
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}

            # Kalibrasi 85/85 BBS: panel.Approved − RECORD DATE median +37 dtk
            # (rentang +11..+358, nol negatif), sedangkan terhadap APPROVE
            # median −25.199 dtk dan 85/85 negatif. RECORD DATE sudah WIB;
            # jangan dibalik menjadi APPROVE atau ditambah tujuh jam.
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date(),
                # Bentuk kolom adalah deposit dari vendor. Nama berkas/flow
                # diketik manusia dan tidak boleh membalik tanda uang.
                "jenis": "depo",
                "amount": amount,
                "credit_delta": Decimal("0"),
                "money_delta": amount,
                "fee": fee,
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": ticket,
                "username": str(r.get(kolom("MEMBER"), "") or "").strip(),
                "reference": "",
                "counterparty": "",
                "description": "QRIS ELITE %s" % str(
                    r.get(kolom("MERCHANT"), "") or ""
                ).strip(),
                "raw": raw,
            }
            nominal_kanonik = format(amount.normalize(), "f")
            row["row_hash"] = row_hash("qris_elite", [ticket, nominal_kanonik])
            out.append(row)

        if jumlah_transaksi and not out:
            ditemukan = ", ".join(repr(s) for s in sorted(status_ditemukan))
            dikenal = ", ".join(sorted(self.STATUS_UANG))
            raise ValueError(
                "Laporan QRIS ELITE memuat %d baris transaksi tetapi tidak satu "
                "pun berstatus uang. Status ditemukan: %s. Status yang dikenal: "
                "%s. Laporkan berkas ini bila vendor mengganti nama status."
                % (jumlah_transaksi, ditemukan or "(kosong)", dikenal)
            )
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


class KingsPayParser(BaseParser):
    """QRIS KINGSPAY CSV — gateway deposit panel Nexus (mis. STN).

    Format vendor (header snakeCase): `platformTrxId`, `merchantTrxId`,
    `username`, `amount` (rupiah penuh), `status=success`. Panel menandai kanal
    di Bank Title `KINGSPAY|…` dan menanam `platformTrxId` di Remarks
    (`kingspay auto approve <id>`) — **tidak** di kolom Ticket/Reference panel.

    Anchor = `username` (pass identitas), pola RPay. `platformTrxId` DISIMPAN di
    raw saja, TIDAK di `reference`: engine mengasingkan gateway ber-reference
    yang tak dikenal field `Transaction.reference` panel. Kalibrasi STN
    20-08-2026: 560/560 success ↔ panel KINGSPAY via username+nominal; 560/561
    remarks memuat platformTrxId.

    `description` wajib diawali `KINGSPAY` (token channel guard, 12 char pertama).
    """

    source_key = "gateway"
    STATUS_UANG = frozenset({"success"})
    KOLOM_WAJIB = (
        "platformTrxId", "merchantTrxId", "amount", "status", "username",
    )

    def parse(self, path, flow=""):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise ValueError(
                    "Laporan KINGSPAY tak dikenali: header CSV kosong."
                )
            header = [str(h or "").strip() for h in reader.fieldnames]
            peta = {h.casefold(): h for h in header if h}
            hilang = [k for k in self.KOLOM_WAJIB if k.casefold() not in peta]
            if hilang:
                raise ValueError(
                    "Laporan KINGSPAY tak dikenali: kolom %s tidak ditemukan. "
                    "Header berkas: %s."
                    % (
                        " dan ".join(hilang),
                        ", ".join(repr(h) for h in header if h) or "(kosong)",
                    )
                )
            raw_rows = list(reader)

        def kol(r, nama):
            return r.get(peta[nama.casefold()], "")

        out = []
        jumlah_transaksi = 0
        status_ditemukan = set()
        for r in raw_rows:
            plat = str(kol(r, "platformTrxId") or "").strip()
            merch = str(kol(r, "merchantTrxId") or "").strip()
            if not plat and not merch:
                continue
            jumlah_transaksi += 1
            status = str(kol(r, "status") or "").strip().lower()
            status_ditemukan.add(status or "(kosong)")
            if status not in self.STATUS_UANG:
                continue

            # success_at = waktu bayar; created_at = buat QR (bisa beda menit).
            occurred = parse_dt(kol(r, "success_at")) or parse_dt(kol(r, "created_at"))
            if not occurred:
                raise ValueError(
                    "KINGSPAY: success_at/created_at tidak dapat dibaca untuk "
                    "platformTrxId %s: success_at=%r created_at=%r."
                    % (plat or merch, kol(r, "success_at"), kol(r, "created_at"))
                )
            amount = abs(parse_decimal(kol(r, "amount")))
            fee = abs(parse_decimal(kol(r, "biayaPlatform")))
            username = str(kol(r, "username") or "").strip()
            store = str(kol(r, "storeName") or "").strip()
            rrn = str(kol(r, "rrn") or "").strip()
            raw = {k: ("" if v is None else str(v)) for k, v in r.items() if k}

            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date(),
                # Bentuk deposit vendor; nama file/flow tak boleh membalik tanda.
                "jenis": "depo",
                "amount": amount,
                "credit_delta": Decimal("0"),
                "money_delta": amount,
                "fee": fee,
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": username,
                # platformTrxId hanya di raw — lihat docstring.
                "reference": "",
                "counterparty": store,
                "description": ("KINGSPAY %s" % rrn).strip(),
                "raw": raw,
            }
            nominal_kanonik = format(amount.normalize(), "f")
            row["row_hash"] = row_hash(
                "kingspay", [plat or merch, nominal_kanonik])
            out.append(row)

        if jumlah_transaksi and not out:
            ditemukan = ", ".join(repr(s) for s in sorted(status_ditemukan))
            dikenal = ", ".join(sorted(self.STATUS_UANG))
            raise ValueError(
                "Laporan KINGSPAY memuat %d baris transaksi tetapi tidak satu "
                "pun berstatus uang. Status ditemukan: %s. Status yang dikenal: "
                "%s. Laporkan berkas ini bila vendor mengganti nama status."
                % (jumlah_transaksi, ditemukan or "(kosong)", dikenal)
            )
        return out


class QRFlyerTampungParser(BaseParser):
    """QR Flyer — mutasi TAMPUNG / payout ke rekening bank (Sesama CM).

    Bukan mutasi DP member (`qrflyer`). Header payout (CSV atau XLSX):
    Request Timestamp, Client Ref, Bank, Beneficiary Account/Name,
    Payout Status, Payout Amount, Transaction Fee, Settlement Timestamp.

    XLSX vendor kadang baris-1 judul ``Withdraw - Qrisflyer`` lalu header di
    baris berikutnya (MXW 23-08-2026) — header dicari dinamis di 8 baris pertama.

    Selalu WD (uang keluar dari saldo QR tampung). Hanya Status=Success.
    Nominal format ID (`IDR 30.000.000`) atau angka. `reference` kosong.
    counterparty = Beneficiary Name; norek di description+raw untuk join Sesama CM.
    """

    source_key = "gateway"
    STATUS_UANG = frozenset({"success"})
    KOLOM_WAJIB = (
        "beneficiary account", "beneficiary name", "payout status",
        "payout amount", "settlement timestamp",
    )
    # Alias casefold → kanonik (vendor kadang beda spasi/underscore)
    _ALIAS = {
        "beneficiary account": ("beneficiary account", "beneficiary_account", "account number"),
        "beneficiary name": ("beneficiary name", "beneficiary_name", "account name"),
        "payout status": ("payout status", "payout_status", "status"),
        "payout amount": ("payout amount", "payout_amount", "amount"),
        "settlement timestamp": (
            "settlement timestamp", "settlement_timestamp", "settlement time", "settled at",
        ),
        "request timestamp": (
            "request timestamp", "request_timestamp", "created at", "transaction date",
        ),
        "client ref": ("client ref", "client_ref", "client reference", "client reff"),
        "transaction fee": ("transaction fee", "transaction_fee", "fee"),
        "bank": ("bank", "bank name", "bank identifier"),
    }

    @classmethod
    def _norm_h(cls, h):
        return re.sub(r"\s+", " ", str(h or "").strip().casefold())

    @classmethod
    def _petakan_header(cls, headers):
        """header list → {kanonik: nama asli di berkas}."""
        ada = {}
        for h in headers or []:
            if not h:
                continue
            ada.setdefault(cls._norm_h(h), str(h).strip())
        peta = {}
        for kanon, aliases in cls._ALIAS.items():
            for a in aliases:
                if a in ada:
                    peta[kanon] = ada[a]
                    break
        return peta

    def _baca_baris(self, path):
        """→ list[dict] keyed by original header names. Cari baris header dulu."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
                # sniffer: baris pertama bisa judul
                lines = f.readlines()
            if not lines:
                return []
            # Cari baris header di 8 baris pertama
            header_idx = 0
            for i, line in enumerate(lines[:8]):
                low = line.casefold()
                if "beneficiary" in low and ("payout" in low or "amount" in low):
                    header_idx = i
                    break
                if "payout amount" in low or "payout_amount" in low:
                    header_idx = i
                    break
            import io
            body = "".join(lines[header_idx:])
            reader = csv.DictReader(io.StringIO(body))
            return [r for r in reader if any((v or "").strip() for v in r.values())]

        # XLSX / XLS
        grid = read_xlsx_grid(path)
        if not grid:
            return []
        header_idx = None
        for i, row in enumerate(grid[:8]):
            cells = [str(c or "").strip() for c in row]
            low = " ".join(c.casefold() for c in cells if c)
            if "beneficiary" in low and ("payout" in low or "amount" in low):
                header_idx = i
                break
            if "payout amount" in low or "payout_amount" in low:
                header_idx = i
                break
        if header_idx is None:
            # fallback: baris pertama yang punya ≥3 sel non-kosong
            for i, row in enumerate(grid[:8]):
                n = sum(1 for c in row if c not in (None, ""))
                if n >= 3:
                    header_idx = i
                    break
        if header_idx is None:
            raise ValueError(
                "Laporan QR Flyer Tampung tak dikenali: baris header payout "
                "tidak ditemukan (cari Beneficiary/Payout Amount). "
                "Baris awal: %s."
                % (
                    "; ".join(
                        repr(" | ".join(str(c or "").strip() for c in row if c not in (None, "")))
                        for row in grid[:3]
                    )
                    or "(kosong)",
                )
            )
        headers = [
            str(c).strip() if c is not None else "" for c in grid[header_idx]
        ]
        out = []
        for row in grid[header_idx + 1 :]:
            if row is None or all(c is None or c == "" for c in row):
                continue
            d = {h: c for h, c in zip(headers, row) if h}
            if any(str(v or "").strip() for v in d.values()):
                out.append(d)
        return out

    def parse(self, path, flow=""):
        rows = self._baca_baris(path)
        if not rows:
            return []
        # header dari kunci baris pertama
        headers = list(rows[0].keys())
        peta = self._petakan_header(headers)
        hilang = [k for k in self.KOLOM_WAJIB if k not in peta]
        if hilang:
            raise ValueError(
                "Laporan QR Flyer Tampung tak dikenali: kolom %s tidak "
                "ditemukan. Header berkas: %s."
                % (
                    " dan ".join(hilang),
                    ", ".join(repr(h) for h in headers if h) or "(kosong)",
                )
            )

        kol = lambda nama: peta.get(nama, "\x00")  # noqa: E731
        out = []
        n_tx = 0
        status_ditemukan = set()
        for r in rows:
            ref = str(r.get(kol("client ref"), "") or "").strip()
            norek = str(r.get(kol("beneficiary account"), "") or "").strip()
            nama = str(r.get(kol("beneficiary name"), "") or "").strip()
            if not ref and not norek and not nama:
                continue
            n_tx += 1
            status = str(r.get(kol("payout status"), "") or "").strip().lower()
            status_ditemukan.add(status or "(kosong)")
            if status not in self.STATUS_UANG:
                continue

            raw_amt = r.get(kol("payout amount"))
            # XLSX typed number vs CSV "IDR 30.000.000"
            if isinstance(raw_amt, (int, float, Decimal)):
                amt = abs(parse_decimal(raw_amt))
            else:
                amt = abs(parse_decimal(raw_amt, number_format="id"))
            raw_fee = r.get(kol("transaction fee"))
            if isinstance(raw_fee, (int, float, Decimal)):
                fee = abs(parse_decimal(raw_fee))
            else:
                fee = abs(parse_decimal(raw_fee, number_format="id"))
            settle = parse_dt(r.get(kol("settlement timestamp")))
            created = parse_dt(r.get(kol("request timestamp")))
            occurred = settle or created
            if not occurred:
                raise ValueError(
                    "QR Flyer Tampung: waktu settlement/request tidak terbaca "
                    "untuk Client Ref %r." % (ref or norek,)
                )
            bank = str(r.get(kol("bank"), "") or "").strip()
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date(),
                "jenis": "wd",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt,
                "fee": fee,
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": "",
                "reference": "",  # Client Ref ≠ ticket panel
                "counterparty": nama,
                "description": (
                    "QRFLYER TAMPUNG %s %s %s" % (bank, norek, nama)
                ).strip(),
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "qrflyer_tampung",
                [ref, norek, format(amt.normalize(), "f")],
            )
            out.append(row)

        if n_tx and not out:
            raise ValueError(
                "Laporan QR Flyer Tampung memuat %d baris tetapi tidak satu pun "
                "berstatus Success. Status ditemukan: %s."
                % (n_tx, ", ".join(sorted(status_ditemukan)) or "(kosong)")
            )
        return out


class QRISEliteTampungParser(BaseParser):
    """QRIS Elite — mutasi TAMPUNG / disbursement ke rekening bank (Sesama CM).

    Bukan mutasi DP member (`qris_elite`). Baris 1 judul DISBURSEMENT HISTORY,
    baris 2 header: ID, DATE_DISBURSEMENT, BANK_CODE, BANK_NO, ACCOUNT_NAME,
    AMOUNT, REF_ID, VENDOR_ID, VENDOR_STATUS.

    Selalu WD. Hanya VENDOR_STATUS=success. Nominal rupiah penuh. BANK_NO
    sering ter-mask (`1191010221*****`) — simpan apa adanya; join Sesama CM
    lewat nama ACCOUNT_NAME + prefiks norek bila cukup digit.
    """

    source_key = "gateway"
    STATUS_UANG = frozenset({"success"})
    KOLOM_WAJIB = (
        "date_disbursement", "account_name", "amount", "vendor_status",
    )

    def parse(self, path, flow=""):
        with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.reader(f)
            judul = next(reader, None) or []
            header = [str(h or "").strip() for h in (next(reader, None) or [])]
            peta = {h.casefold(): h for h in header if h}
            hilang = [k for k in self.KOLOM_WAJIB if k not in peta]
            if hilang:
                raise ValueError(
                    "Laporan QRIS Elite Tampung tak dikenali: kolom %s tidak "
                    "ditemukan. Header berkas: %s. Judul: %s."
                    % (
                        " dan ".join(hilang),
                        ", ".join(repr(h) for h in header if h) or "(kosong)",
                        ", ".join(repr(h) for h in judul if h) or "(kosong)",
                    )
                )
            rows = [
                dict(zip(header, nilai))
                for nilai in reader
                if any(str(c or "").strip() for c in nilai)
            ]

        kol = lambda nama: peta.get(nama.casefold(), "\x00")  # noqa: E731
        out = []
        n_tx = 0
        status_ditemukan = set()
        for r in rows:
            pid = str(r.get(kol("id"), "") or "").strip()
            ref = str(r.get(kol("ref_id"), "") or "").strip()
            nama = str(r.get(kol("account_name"), "") or "").strip()
            norek = str(r.get(kol("bank_no"), "") or "").strip()
            if not pid and not ref and not nama:
                continue
            n_tx += 1
            status = str(r.get(kol("vendor_status"), "") or "").strip().lower()
            status_ditemukan.add(status or "(kosong)")
            if status not in self.STATUS_UANG:
                continue

            amt = abs(parse_decimal(r.get(kol("amount"))))
            occurred = parse_dt(r.get(kol("date_disbursement")))
            if not occurred:
                raise ValueError(
                    "QRIS Elite Tampung: DATE_DISBURSEMENT tidak terbaca untuk "
                    "ID %r: %r."
                    % (pid or ref, r.get(kol("date_disbursement")))
                )
            raw = {k: ("" if v is None else str(v)) for k, v in r.items()}
            # digit norek (buang mask *) untuk blob join Sesama CM
            norek_digit = re.sub(r"\D", "", norek.replace("*", ""))
            row = {
                "source_type": "gateway",
                "occurred_at": occurred,
                "posted_date": occurred.date(),
                "jenis": "wd",
                "amount": amt,
                "credit_delta": Decimal("0"),
                "money_delta": -amt,
                "fee": Decimal("0"),
                "bonus": Decimal("0"),
                "balance_after": None,
                "ticket_no": "",
                "username": "",
                "reference": "",
                "counterparty": nama,
                "description": (
                    "QRISELITE TAMPUNG %s %s %s"
                    % (norek_digit or norek, nama, ref)
                ).strip(),
                "raw": raw,
            }
            row["row_hash"] = row_hash(
                "qris_elite_tampung",
                [pid or ref, norek_digit or norek, format(amt.normalize(), "f")],
            )
            out.append(row)

        if n_tx and not out:
            raise ValueError(
                "Laporan QRIS Elite Tampung memuat %d baris tetapi tidak satu "
                "pun berstatus success. Status ditemukan: %s."
                % (n_tx, ", ".join(sorted(status_ditemukan)) or "(kosong)")
            )
        return out
