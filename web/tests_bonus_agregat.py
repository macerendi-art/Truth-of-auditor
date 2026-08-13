"""Modus agregat Rekonsiliasi Bonus: lump bracket per kategori/hari.

Yang ditegakkan di sini, berurutan menurut kepentingannya:

1. **Nexus tidak bergeser satu baris pun.** `NexusTidakBerubahTests` berjalan
   tanpa satu pun baris panel berpenanda dan menuntut himpunan kunci dict yang
   dikembalikan SAMA PERSIS dengan bentuk lama — tanpa `agregat`, tanpa
   `agregat_*`. Kategorinya sengaja dipilih supaya AKAN cocok di bawah aturan
   pemetaan, sehingga yang terbukti bekerja adalah gerbang penanda, bukan
   kebetulan pemetaan.
2. Pemetaan kategori lintas-namespace (prefiks batas-kata, bukan subset token).
3. `TGL dd.mm.yyyy` hanya menyentuh jalur agregat.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from sources.parsers.bonus import MARKER_AGREGAT
from web.bonus import rekonsiliasi_bonus
from web.tests_bonus import TGL, _BonusData

# Bentuk nyata produksi W25 (04-08-2026).
D3, D4 = date(2026, 8, 3), date(2026, 8, 4)

KAT_ROLL_PANEL = "BONUS ROLLINGAN SLOT HARIAN 0.5%"
KAT_ROLL_BRACKET = "BONUS ROLLINGAN"

# Kunci LAMA `ringkas["kategori"][k]` — kontrak yang dijaga gerbang penanda.
KUNCI_KAT_LAMA = {"bracket_only", "bracket_only_total", "cocok", "cocok_total",
                  "panel_only", "panel_only_total"}


class _AgregatData(_BonusData):
    """`_BonusData` + kemampuan menulis penanda `raw["Sumber"]`.

    Diperluas, bukan disalin: helper `buat/panel_row/bracket_row` sudah ada dan
    tes lama memakainya apa adanya.
    """

    def buat(self, *a, sumber=None, **kw):
        t = super().buat(*a, **kw)
        if sumber:
            t.raw = dict(t.raw or {}, Sumber=sumber)
            t.save(update_fields=["raw"])
        return t

    def panel_cor(self, username, amount, **kw):
        """Baris panel BERPENANDA — hanya parser `cor_panel_bonus` yang bisa
        membuatnya di produksi."""
        kw.setdefault("sumber", MARKER_AGREGAT)
        return self.panel_row(username, amount, **kw)

    def lump(self, amount, kategori, tanggal=D4, desc=None):
        """Baris bracket gelondongan: username kosong, deskripsi multi-baris."""
        return self.bracket_row(
            "", amount, kategori=kategori, tanggal=tanggal,
            desc=desc if desc is not None else f"{kategori}\nPlayer:")

    def recon(self, dari=D3, sampai=D4, **kw):
        return rekonsiliasi_bonus(self.toko, dari=dari, sampai=sampai, **kw)


class NexusTidakBerubahTests(_BonusData):
    """Tanpa baris berpenanda, hasilnya wajib bentuk LAMA persis."""

    def test_bracket_username_kosong_tetap_bracket_only(self):
        # Kategori dipilih supaya AKAN cocok di bawah aturan pemetaan agregat;
        # yang menahannya adalah gerbang penanda (panel TANPA `Sumber`).
        self.panel_row("budi", "50000", kategori=KAT_ROLL_PANEL)
        self.bracket_row("", "50000", kategori=KAT_ROLL_BRACKET)
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)

        self.assertEqual(len(data["cocok"]), 0)
        self.assertEqual(len(data["panel_only"]), 1)
        self.assertEqual(len(data["bracket_only"]), 1)
        self.assertNotIn("agregat", data)
        self.assertNotIn("agregat", data["ringkas"])
        self.assertEqual(sorted(data.keys()),
                         ["bracket_only", "cocok", "kategori_opsi",
                          "panel_only", "ringkas"])
        self.assertEqual(sorted(data["ringkas"].keys()),
                         ["bracket_only", "cocok", "kategori", "panel_only"])
        for k, d in data["ringkas"]["kategori"].items():
            self.assertEqual(set(d), KUNCI_KAT_LAMA, k)

    def test_baris_bertanggal_tgl_tanpa_penanda_tetap_apa_adanya(self):
        # Deskripsi bracket Nexus adalah teks bebas dan bisa memuat "TGL".
        self.panel_row("rina", "30000", tanggal=TGL)
        self.bracket_row("rina", "30000", tanggal=TGL,
                         desc="KOREKSI TGL 03.08.2026\nPlayer: rina")
        data = rekonsiliasi_bonus(self.toko, dari=TGL, sampai=TGL)
        self.assertEqual(len(data["cocok"]), 1)
        self.assertNotIn("agregat", data)


class GerbangSelTests(_AgregatData):
    def test_lump_cocok_dengan_total_panel(self):
        self.panel_cor("a", "500000.00", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.panel_cor("b", "538747.20", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.lump("1038747.00", KAT_ROLL_BRACKET)
        data = self.recon()

        self.assertEqual(len(data["agregat"]), 1)
        e = data["agregat"][0]
        self.assertEqual(e["tanggal"], D4)
        self.assertIsNone(e["tanggal_bracket"])
        self.assertEqual(e["kategori"], KAT_ROLL_BRACKET)
        self.assertEqual(e["kategori_detail"], KAT_ROLL_PANEL)
        self.assertEqual(e["kategori_panel"], [KAT_ROLL_PANEL])
        self.assertEqual(e["n_panel"], 2)
        self.assertEqual(e["panel_total"], Decimal("1038747.20"))
        self.assertEqual(e["n_bracket"], 1)
        self.assertEqual(e["bracket_total"], Decimal("1038747.00"))
        self.assertEqual(e["selisih"], Decimal("0.20"))
        self.assertEqual(e["status"], "cocok")
        self.assertIn("Player:", e["deskripsi"])
        # Baris yang terserap keluar dari kedua ember lama.
        self.assertEqual(len(data["panel_only"]), 0)
        self.assertEqual(len(data["bracket_only"]), 0)
        self.assertEqual(len(data["cocok"]), 0)

    def test_batas_toleransi(self):
        # Satu hari per kasus — sel adalah (kategori, tanggal), jadi tiga hari
        # berturut memberi tiga sel terpisah dalam satu pemanggilan.
        kasus = (("0.99", "cocok"), ("1.00", "selisih"), ("1.01", "selisih"))
        for i, (beda, _status) in enumerate(kasus):
            hari = date(2026, 8, 10 + i)
            self.panel_cor("a", "100000", kategori=KAT_ROLL_PANEL, tanggal=hari)
            self.lump(str(Decimal("100000") - Decimal(beda)),
                      KAT_ROLL_BRACKET, tanggal=hari)
        entri = self.recon(dari=date(2026, 8, 10), sampai=date(2026, 8, 12))
        entri = entri["agregat"]
        self.assertEqual(len(entri), 3)
        for e, (beda, status) in zip(entri, kasus):
            self.assertEqual(e["selisih"], Decimal(beda))
            self.assertEqual(e["status"], status)

    def test_selisih_nyata_terlihat(self):
        # Angka nyata: DAILY LOGIN panel 92.550 vs bracket 92.925.
        self.panel_cor("a", "92550", kategori="Daily Login", tanggal=D4)
        self.lump("92925", "DAILY LOGIN")
        e = self.recon()["agregat"][0]
        self.assertEqual(e["selisih"], Decimal("-375"))
        self.assertEqual(e["status"], "selisih")

    def test_sel_campuran_jatuh_seluruhnya_ke_jalur_lama(self):
        self.panel_cor("a", "100000", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.lump("100000", KAT_ROLL_BRACKET)
        self.bracket_row("koreksi1", "5000", kategori=KAT_ROLL_BRACKET,
                         tanggal=D4)
        data = self.recon()
        self.assertEqual(data["agregat"], [])
        self.assertEqual(len(data["bracket_only"]), 2)
        self.assertEqual(len(data["panel_only"]), 1)

    def test_lump_tanpa_pasangan_jadi_bracket_only(self):
        self.panel_cor("a", "92550", kategori="Daily Login", tanggal=D4)
        self.lump("215000", "SINGLE DEPOSIT")
        data = self.recon()
        self.assertEqual(data["agregat"], [])
        self.assertEqual(len(data["bracket_only"]), 1)
        self.assertEqual(len(data["panel_only"]), 1)

    def test_baris_panel_hanya_diklaim_sekali(self):
        # Dua sel memprefiks panel yang sama; urutan klaim deterministik
        # `(tanggal, kategori ternormalisasi)` -> "BONUS" menang atas
        # "BONUS ROLLINGAN".
        self.panel_cor("a", "100000", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.lump("100000", "BONUS")
        self.lump("100000", KAT_ROLL_BRACKET)
        data = self.recon()
        self.assertEqual(len(data["agregat"]), 1)
        self.assertEqual(data["agregat"][0]["kategori"], "BONUS")
        self.assertEqual(len(data["bracket_only"]), 1)
        self.assertEqual(data["bracket_only"][0]["kategori"], KAT_ROLL_BRACKET)

    def test_panel_tanpa_penanda_tak_pernah_teragregasi(self):
        # Mode menyala oleh baris berpenanda LAIN, tapi baris tak berpenanda
        # tetap tak layak diserap.
        self.panel_cor("x", "10000", kategori="Manual Freebet", tanggal=D4)
        self.panel_row("a", "100000", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.lump("100000", KAT_ROLL_BRACKET)
        data = self.recon()
        self.assertEqual(data["agregat"], [])
        self.assertEqual(len(data["bracket_only"]), 1)
        self.assertEqual(len(data["panel_only"]), 2)


class PemetaanKategoriTests(_AgregatData):
    KASUS = [
        (KAT_ROLL_BRACKET, KAT_ROLL_PANEL, True),      # prefiks batas-kata
        ("DAILY LOGIN", "Daily Login", True),          # sama, beda kapital
        ("SINGLE DEPOSIT", "Single Deposit", True),
        ("BONUS HARIAN", KAT_ROLL_PANEL, False),       # subset token -> DITOLAK
    ]

    def test_keempat_kasus_nyata(self):
        # Satu hari per kasus supaya keempatnya hidup berdampingan tanpa saling
        # mengklaim baris panel.
        for i, (kat_bracket, kat_panel, _harus) in enumerate(self.KASUS):
            hari = date(2026, 8, 10 + i)
            self.panel_cor("a", "100000", kategori=kat_panel, tanggal=hari)
            self.lump("100000", kat_bracket, tanggal=hari)
        data = self.recon(dari=date(2026, 8, 10), sampai=date(2026, 8, 13))
        teragregasi = {e["kategori"] for e in data["agregat"]}
        sisa = {r["kategori"] for r in data["bracket_only"]}
        for kat_bracket, kat_panel, harus in self.KASUS:
            with self.subTest(bracket=kat_bracket, panel=kat_panel):
                self.assertEqual(kat_bracket in teragregasi, harus)
                self.assertEqual(kat_bracket in sisa, not harus)

    def test_alias_eksplisit_menambal_pemetaan_putus(self):
        self.panel_cor("a", "55000", kategori="Manual Freebet", tanggal=D4)
        self.lump("55000", "FREEBET")
        self.assertEqual(self.recon()["agregat"], [])
        with patch.dict("web.bonus.ALIAS_AGREGAT",
                        {"FREEBET": "MANUAL FREEBET"}, clear=False):
            data = self.recon()
        self.assertEqual(len(data["agregat"]), 1)
        self.assertEqual(data["agregat"][0]["kategori_detail"], "Manual Freebet")

    def test_dua_kategori_panel_digabung(self):
        self.panel_cor("a", "100000", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.panel_cor("b", "50000", kategori="BONUS ROLLINGAN SPORT 0.3%",
                       tanggal=D4)
        self.lump("150000", KAT_ROLL_BRACKET)
        e = self.recon()["agregat"][0]
        self.assertEqual(e["kategori_panel"],
                         [KAT_ROLL_PANEL, "BONUS ROLLINGAN SPORT 0.3%"])
        self.assertEqual(e["kategori_detail"], KAT_ROLL_PANEL)  # alfabetis
        self.assertEqual(e["panel_total"], Decimal("150000"))
        self.assertEqual(e["status"], "cocok")


class TanggalEfektifTests(_AgregatData):
    def test_tgl_menggeser_tanggal_dan_menyimpan_tanggal_pembukuan(self):
        self.panel_cor("a", "92925", kategori="Daily Login", tanggal=D3)
        self.lump("92925", "DAILY LOGIN", tanggal=D4,
                  desc="LOGIN & SPIN (DAILY SPIN BONUS) TGL 03.08.2026\nPlayer:")
        e = self.recon()["agregat"][0]
        self.assertEqual(e["tanggal"], D3)
        self.assertEqual(e["tanggal_bracket"], D4)
        self.assertEqual(e["status"], "cocok")

    def test_tanpa_tgl_pakai_tanggal_pembukuan(self):
        self.panel_cor("a", "100000", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.lump("100000", KAT_ROLL_BRACKET, tanggal=D4,
                  desc="BONUS ROLLINGAN SLOT HARIAN 0.5%\nPlayer:")
        e = self.recon()["agregat"][0]
        self.assertEqual(e["tanggal"], D4)
        self.assertIsNone(e["tanggal_bracket"])

    def test_tgl_mustahil_diabaikan_bukan_exception(self):
        self.panel_cor("a", "100000", kategori="Single Deposit", tanggal=D4)
        self.lump("100000", "SINGLE DEPOSIT", tanggal=D4,
                  desc="DEPOSIT & SPIN (SINGLE DEPOSIT ) TGL 32.13.2026\nPlayer:")
        e = self.recon()["agregat"][0]
        self.assertEqual(e["tanggal"], D4)   # jatuh ke tanggal pembukuan

    def test_tahun_dua_digit(self):
        self.panel_cor("a", "100000", kategori="Single Deposit", tanggal=D3)
        self.lump("100000", "SINGLE DEPOSIT", tanggal=D4,
                  desc="DEPOSIT & SPIN (SINGLE DEPOSIT ) TGL 03.08.26\nPlayer:")
        self.assertEqual(self.recon()["agregat"][0]["tanggal"], D3)

    def test_tgl_tidak_menyentuh_jalur_per_pemain(self):
        # Baris bracket BER-username: `TGL` tak boleh menggeser pasangannya.
        self.panel_cor("x", "10000", kategori="Manual Freebet", tanggal=D4)
        self.panel_cor("lonk24", "10000", kategori="Manual Freebet", tanggal=D4)
        self.bracket_row("lonk24", "10000", kategori="BONUS HARIAN", tanggal=D4,
                         desc="K-BE21 TGL 03.08.2026\nPlayer: lonk24")
        data = self.recon()
        self.assertEqual(len(data["cocok"]), 1)
        self.assertEqual(data["cocok"][0]["bracket"]["username"], "lonk24")
        self.assertEqual(data["agregat"], [])

    def test_rentang_memotong_tgl(self):
        # Lump 04-08 menunjuk 03-08, tapi panel 03-08 tak diminta pengguna:
        # ARTEFAK TEPI yang disengaja — query TIDAK dilebarkan.
        self.panel_cor("x", "10000", kategori="Manual Freebet", tanggal=D4)
        self.panel_cor("a", "92925", kategori="Daily Login", tanggal=D3)
        self.lump("92925", "DAILY LOGIN", tanggal=D4,
                  desc="LOGIN & SPIN (DAILY SPIN BONUS) TGL 03.08.2026\nPlayer:")
        data = self.recon(dari=D4, sampai=D4)
        self.assertEqual(data["agregat"], [])
        self.assertEqual(len(data["bracket_only"]), 1)


class BentukNyataW25Tests(_AgregatData):
    """04-08-2026: 6 baris per pemain + 3 lump, nol bunyi palsu."""

    def _susun(self):
        # Panel 04-08 (berpenanda) — per pemain.
        for user, amt, kat in (("fuzzy666", "10000", "Manual Freebet"),
                               ("human10", "10000", "Manual Freebet"),
                               ("sam25", "15000", "Manual Freebet"),
                               ("memek49", "15000", "Bonus New Member Slot 30%"),
                               ("bantalguling", "10000", "Manual Freebet"),
                               ("lonk24", "10000", "Manual Freebet")):
            self.panel_cor(user, amt, kategori=kat, tanggal=D4)
        # Panel 04-08 — rollingan (74 baris nyata, dipadatkan jadi 2).
        self.panel_cor("p1", "500000.00", kategori=KAT_ROLL_PANEL, tanggal=D4)
        self.panel_cor("p2", "538747.20", kategori=KAT_ROLL_PANEL, tanggal=D4)
        # Panel 03-08 — sumber kedua lump ber-`TGL`.
        self.panel_cor("q1", "92925", kategori="Daily Login", tanggal=D3)
        self.panel_cor("q2", "215000", kategori="Single Deposit", tanggal=D3)
        # Bracket 04-08 — 6 per pemain + 3 lump.
        for user, amt, kode in (("fuzzy666", "10000", "K-BLS"),
                                ("human10", "10000", "K-BE21"),
                                ("sam25", "15000", "K-BE22"),
                                ("memek49", "15000", "K-BN4"),
                                ("bantalguling", "10000", "K-BE21"),
                                ("lonk24", "10000", "K-BE21")):
            self.bracket_row(user, amt, kategori="BONUS HARIAN", tanggal=D4,
                             desc=f"{kode}\nPlayer: {user}")
        self.lump("1038747.00", KAT_ROLL_BRACKET)
        self.lump("215000", "SINGLE DEPOSIT", desc=(
            "DEPOSIT & SPIN (SINGLE DEPOSIT ) TGL 03.08.2026\nPlayer:"))
        self.lump("92925", "DAILY LOGIN", desc=(
            "LOGIN & SPIN (DAILY SPIN BONUS) TGL 03.08.2026\nPlayer:"))

    def test_per_pemain_tetap_1_ke_1_dan_lump_teragregasi(self):
        self._susun()
        data = self.recon()
        self.assertEqual(len(data["cocok"]), 6)
        self.assertEqual(sum(c["panel"]["nominal"] for c in data["cocok"]),
                         Decimal("70000"))
        self.assertEqual(len(data["panel_only"]), 0)
        self.assertEqual(len(data["bracket_only"]), 0)
        self.assertEqual(len(data["agregat"]), 3)
        self.assertEqual([e["kategori"] for e in data["agregat"]],
                         ["DAILY LOGIN", "SINGLE DEPOSIT", KAT_ROLL_BRACKET])
        self.assertEqual([e["status"] for e in data["agregat"]],
                         ["cocok", "cocok", "cocok"])

    def test_ringkasan_agregat(self):
        self._susun()
        r = self.recon()["ringkas"]
        self.assertEqual(r["agregat"]["n"], 3)
        self.assertEqual(r["agregat"]["panel_total"], Decimal("1346672.20"))
        self.assertEqual(r["agregat"]["bracket_total"], Decimal("1346672.00"))
        self.assertEqual(r["agregat"]["selisih"], Decimal("0.20"))
        self.assertEqual(r["agregat"]["selisih_n"], 0)
        kat = r["kategori"][KAT_ROLL_PANEL]
        self.assertEqual(kat["agregat"], 1)
        self.assertEqual(kat["agregat_panel_total"], Decimal("1038747.20"))
        self.assertEqual(kat["agregat_bracket_total"], Decimal("1038747.00"))
        self.assertEqual(kat["agregat_selisih"], Decimal("0.20"))
        # Kategori tanpa lump tetap berkunci LAMA saja.
        self.assertEqual(set(r["kategori"]["Manual Freebet"]), KUNCI_KAT_LAMA)

    def test_selisih_n_menghitung_lump_bermasalah(self):
        self.panel_cor("a", "92550", kategori="Daily Login", tanggal=D4)
        self.panel_cor("b", "157500", kategori="Single Deposit", tanggal=D4)
        self.lump("92925", "DAILY LOGIN")
        self.lump("215000", "SINGLE DEPOSIT")
        r = self.recon()["ringkas"]
        self.assertEqual(r["agregat"]["n"], 2)
        self.assertEqual(r["agregat"]["selisih_n"], 2)
        self.assertEqual(r["agregat"]["selisih"], Decimal("-57875"))

    def test_filter_kategori_menyaring_entri_agregat(self):
        self._susun()
        opsi = self.recon()["kategori_opsi"]
        for k in ("Daily Login", "Single Deposit", KAT_ROLL_PANEL):
            self.assertIn(k, opsi)
        data = self.recon(kategori=KAT_ROLL_PANEL)
        self.assertEqual(len(data["agregat"]), 1)
        self.assertEqual(data["agregat"][0]["kategori_detail"], KAT_ROLL_PANEL)
        self.assertEqual(data["ringkas"]["agregat"]["n"], 1)
        self.assertEqual(len(data["cocok"]), 0)


class ToleransiMenskalaTests(_AgregatData):
    """Ambang selisih adalah batas ARITMETIS artefak pembulatan kolom.

    `Transaction.amount` = DecimalField(decimal_places=2), sedangkan ekspor
    panel memuat baris berdesimal tiga. Tiap baris bergeser <= 0,005 saat
    disimpan, jadi sel berisi n baris bergeser <= n x 0,005. Ambang tetap Rp1
    akan pecah di ~200 baris berdesimal-tiga; ambang yang menskala tidak.
    """

    def test_lantai_satu_rupiah_untuk_sel_kecil(self):
        from web.bonus import toleransi_agregat

        # 10 baris -> batas aritmetis 0,05, tapi lantai Rp1 yang berlaku.
        self.assertEqual(toleransi_agregat(10), Decimal("1"))
        self.assertEqual(toleransi_agregat(0), Decimal("1"))

    def test_menskala_di_atas_dua_ratus_baris(self):
        from web.bonus import toleransi_agregat

        # 200 x 0,005 = 1,00 -> titik silang; di atasnya batas aritmetis menang.
        self.assertEqual(toleransi_agregat(200), Decimal("1.000"))
        self.assertEqual(toleransi_agregat(2000), Decimal("10.000"))

    def test_selisih_nyata_tetap_terlihat_meski_sel_besar(self):
        """Ambang menskala tak boleh jadi pintu belakang: 2.000 baris memberi
        ambang Rp10, dan selisih Rp375 tetap harus berbunyi."""
        from web.bonus import toleransi_agregat

        self.assertLess(toleransi_agregat(2000), Decimal("375"))
