"""Halaman /rekap-bulanan/ (Task 9) — render 100% dinamis dari `web.rekap.FIELDS`,
popup edit manual HTMX (klon fr_koreksi), Penyebab Selisih, audit trail, RBAC,
peringatan kunci carry, tooltip BONUS LAINNYA.

Modul inti (`web/rekap.py`, model `RekapManual`/`RekapPenyebab`) sudah diuji di
`web/tests_rekap.py` — di sini fokus HANYA lapisan halaman/HTMX.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction
from web.models import RekapManual, RekapPenyebab
from web.rekap import FIELDS

TAHUN, BULAN = 2026, 7
SEL_BULAN = f"{TAHUN:04d}-{BULAN:02d}"
PERIODE = date(TAHUN, BULAN, 1)


class _RekapPageData(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.user = get_user_model().objects.create_user(
            username="auditor1", password="rahasia123", role="auditor")
        self.user.allowed_tokos.add(self.toko)
        self.client.force_login(self.user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        self.st_panel = SourceType.objects.get_or_create(
            key="panel", defaults={"name": "Panel"})[0]
        self.st_pbonus = SourceType.objects.get(key="panel_bonus")
        self.uploads = {}
        self._n = 0

    def _upload(self, st):
        if st.key not in self.uploads:
            self.uploads[st.key] = Upload.objects.create(
                source_type=st, toko=self.toko, original_name=f"{st.key}.xlsx")
        return self.uploads[st.key]

    def _tx(self, st, tanggal, **kw):
        self._n += 1
        return Transaction.objects.create(
            upload=self._upload(st), source_type=st, toko=self.toko,
            posted_date=tanggal,
            occurred_at=datetime(tanggal.year, tanggal.month, tanggal.day, 10, 0),
            row_hash=f"rkpg{self._n}", **kw)

    def panel(self, jenis, amount, tanggal, is_duplicate=False):
        return self._tx(self.st_panel, tanggal, jenis=jenis, amount=Decimal(amount),
                        credit_delta=Decimal(amount), is_duplicate=is_duplicate)

    def bonus_panel(self, username, amount, kategori, tanggal=PERIODE):
        return self._tx(self.st_pbonus, tanggal, jenis="bonus", amount=Decimal(amount),
                        username=username, description=f"{kategori} {username}",
                        raw={"Kategori": kategori})

    def manual(self, field, nilai, tahun=TAHUN, bulan=BULAN, **kw):
        return RekapManual.objects.create(
            toko=self.toko, periode=date(tahun, bulan, 1), field=field,
            nilai=Decimal(nilai), **kw)

    def penyebab(self, label, nilai, urutan=0, tahun=TAHUN, bulan=BULAN):
        return RekapPenyebab.objects.create(
            toko=self.toko, periode=date(tahun, bulan, 1), label=label,
            nilai=Decimal(nilai), urutan=urutan)

    def _get(self, **params):
        params.setdefault("bulan", SEL_BULAN)
        return self.client.get(reverse("rekap_bulanan"), params)

    def _edit_get(self, field, **over):
        params = {"bulan": SEL_BULAN, "field": field}
        params.update(over)
        return self.client.get(reverse("rekap_edit_form"), params)

    def _edit_post(self, **over):
        base = {"bulan": SEL_BULAN, "field": "wl", "nilai": "1000", "catatan": ""}
        base.update(over)
        return self.client.post(reverse("rekap_edit_simpan"), base)

    def _penyebab_post(self, **over):
        base = {"bulan": SEL_BULAN, "label": "Auto Pulsa", "nilai": "1000"}
        base.update(over)
        return self.client.post(reverse("rekap_penyebab_simpan"), base)


class RenderDinamisTests(_RekapPageData):
    """Jaminan inti reviewer: TIDAK BOLEH ada baris registry yang di-hardcode."""

    def test_render_200_dan_setiap_label_fields_muncul(self):
        r = self._get()
        self.assertEqual(r.status_code, 200)
        isi = r.content.decode()
        for f in FIELDS:
            self.assertIn(f.label, isi, f"label '{f.label}' ({f.slug}) hilang dari render")

    def test_empat_kartu_seksi_tampil(self):
        r = self._get()
        isi = r.content.decode()
        self.assertIn("NET PROFIT", isi)
        self.assertIn("SISA DANA MEMBER", isi)
        self.assertIn("TOTAL DANA LEBIH WEB", isi)
        self.assertIn("SELISIH", isi)
        self.assertIn("Penyebab Selisih", isi)

    def test_baris_computed_tak_punya_tombol_edit(self):
        r = self._get()
        self.assertNotIn(
            f"field=net_profit", r.content.decode())

    def test_baris_manual_auto_carry_punya_tombol_edit(self):
        isi = self._get().content.decode()
        self.assertIn("field=wl", isi)      # manual
        self.assertIn("field=dp", isi)      # auto
        self.assertIn("field=wallet_balance_lalu", isi)  # carry

    def test_catatan_koreksi_fr_tidak_diterapkan(self):
        isi = self._get().content.decode()
        self.assertIn("Koreksi sel FR", isi)
        self.assertIn("tidak diterapkan di rekap", isi)


class MonthParamTests(_RekapPageData):
    def test_default_bulan_ini_tanpa_parameter(self):
        today = date.today()
        r = self.client.get(reverse("rekap_bulanan"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["sel_bulan"], f"{today.year:04d}-{today.month:02d}")

    def test_bulan_param_dipakai(self):
        self.manual("wl", "777000")
        r = self._get(bulan=SEL_BULAN)
        self.assertEqual(r.context["sel_bulan"], SEL_BULAN)
        self.assertIn("777.000", r.content.decode())

    def test_bulan_param_rusak_jatuh_ke_default(self):
        r = self._get(bulan="bukan-bulan")
        self.assertEqual(r.status_code, 200)


class EditFormTests(_RekapPageData):
    def test_get_form_slug_manual_200(self):
        r = self._edit_get("wl")
        self.assertEqual(r.status_code, 200)
        self.assertIn("WL", r.content.decode())

    def test_get_form_slug_auto_200(self):
        r = self._edit_get("dp")
        self.assertEqual(r.status_code, 200)

    def test_get_form_slug_carry_menyebut_kunci(self):
        r = self._edit_get("wallet_balance_lalu")
        self.assertEqual(r.status_code, 200)
        self.assertIn("mengunci", r.content.decode().lower())

    def test_get_form_slug_computed_400(self):
        r = self._edit_get("net_profit")
        self.assertEqual(r.status_code, 400)

    def test_get_form_slug_asing_400(self):
        r = self._edit_get("slug_tidak_ada")
        self.assertEqual(r.status_code, 400)

    def test_get_form_parameter_kurang_400(self):
        r = self.client.get(reverse("rekap_edit_form"), {"bulan": SEL_BULAN})
        self.assertEqual(r.status_code, 400)


class EditSimpanTests(_RekapPageData):
    def test_simpan_manual_persist_audit_dot_dan_total(self):
        r = self._edit_post(field="wl", nilai="1.500.000", catatan="uji simpan")
        self.assertEqual(r.status_code, 200)
        m = RekapManual.objects.get(toko=self.toko, periode=PERIODE, field="wl")
        self.assertEqual(m.nilai, Decimal("1500000"))
        self.assertEqual(m.catatan, "uji simpan")
        self.assertEqual(m.dibuat_oleh, self.user)
        log = AuditLog.objects.filter(aksi="rekap_manual").latest("id")
        self.assertEqual(log.detail["field"], "wl")
        self.assertEqual(log.detail["nilai_baru"], "1500000.00")
        isi = r.content.decode()
        self.assertIn('id="rekap-sections"', isi)
        # WL (baris manual) DAN NET PROFIT (baris rumus, plus rujukan berantai
        # wl_ref/sisa_dana_member/total_wallet_live/net_profit_ref) sama-sama
        # menampilkan 1.500.000 karena WL satu-satunya anggota berisi — bukti
        # total dihitung ULANG, bukan cache lama.
        self.assertGreaterEqual(isi.count("1.500.000"), 2)
        self.assertIn("rk-dot", isi)
        self.assertIn("auditor1", isi)

    def test_simpan_menang_atas_auto(self):
        self.panel("depo", "1000", PERIODE)
        r = self._edit_post(field="dp", nilai="-500")
        self.assertEqual(r.status_code, 200)
        m = RekapManual.objects.get(toko=self.toko, periode=PERIODE, field="dp")
        self.assertEqual(m.nilai, Decimal("-500"))
        isi = r.content.decode()
        # Titik dot manual menampilkan nilai auto ASLI (−1.000, dari deposit 1.000)
        # di title — bukti auto tetap terekam meski manual sudah menang.
        self.assertIn("-1.000", isi)

    def test_simpan_carry_menghilangkan_belum_dikunci(self):
        self.manual("bank_dp", "999", bulan=6)
        self.manual("wl", "100", bulan=6)
        sebelum = self._get().content.decode()
        self.assertIn("belum dikunci", sebelum)

        self._edit_post(field="wallet_balance_lalu", nilai="100")
        self._edit_post(field="akuran_lalu", nilai="0")
        r = self._edit_post(field="dana_lebih_lalu", nilai="999")
        sesudah = r.content.decode()
        self.assertNotIn("belum dikunci", sesudah)

    def test_hapus_manual_kembali_ke_auto(self):
        self.panel("depo", "2000", PERIODE)
        self._edit_post(field="dp", nilai="-1")
        self.assertTrue(RekapManual.objects.filter(toko=self.toko, periode=PERIODE, field="dp").exists())
        r = self._edit_post(field="dp", hapus="1")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(RekapManual.objects.filter(toko=self.toko, periode=PERIODE, field="dp").exists())
        self.assertTrue(AuditLog.objects.filter(aksi="rekap_manual_hapus").exists())
        self.assertIn("2.000", r.content.decode())

    def test_field_computed_ditolak_400(self):
        r = self._edit_post(field="net_profit", nilai="999")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(RekapManual.objects.filter(field="net_profit").exists())

    def test_field_asing_ditolak_400(self):
        r = self._edit_post(field="tidak_ada_di_registry", nilai="999")
        self.assertEqual(r.status_code, 400)

    def test_format_koma_desimal_diterima(self):
        r = self._edit_post(field="wl", nilai="1.500,50")
        self.assertEqual(r.status_code, 200)
        m = RekapManual.objects.get(toko=self.toko, periode=PERIODE, field="wl")
        self.assertEqual(m.nilai, Decimal("1500.50"))

    def test_nilai_nan_dan_infinity_ditolak(self):
        for buruk in ("NaN", "Infinity", "-Infinity", "99999999999999999999",
                      "9999999999999999,999", "1e30", "1E+28", "abc"):
            r = self._edit_post(field="wl", nilai=buruk)
            self.assertEqual(r.status_code, 400, buruk)
        self.assertFalse(RekapManual.objects.filter(toko=self.toko, periode=PERIODE, field="wl").exists())

    def test_wajib_login(self):
        self.client.logout()
        r = self._edit_post()
        self.assertEqual(r.status_code, 302)

    def test_rbac_auditor_bisa_edit(self):
        # `self.user` sudah role="auditor" — pin: peran non-admin tetap bisa edit
        self.assertEqual(self.user.role, "auditor")
        r = self._edit_post(field="wl", nilai="55")
        self.assertEqual(r.status_code, 200)


class PenyebabTests(_RekapPageData):
    def test_tambah_persist_audit_dan_redirect(self):
        r = self._penyebab_post(label="Auto Pulsa", nilai="150000")
        self.assertEqual(r.status_code, 302)
        self.assertIn(SEL_BULAN, r.url)
        p = RekapPenyebab.objects.get(toko=self.toko, periode=PERIODE, label="Auto Pulsa")
        self.assertEqual(p.nilai, Decimal("150000"))
        log = AuditLog.objects.filter(aksi="rekap_penyebab").latest("id")
        self.assertEqual(log.detail["label"], "Auto Pulsa")

    def test_urutan_auto_increment(self):
        self._penyebab_post(label="Pertama", nilai="1")
        self._penyebab_post(label="Kedua", nilai="2")
        urutan = list(RekapPenyebab.objects.filter(
            toko=self.toko, periode=PERIODE).order_by("id").values_list("urutan", flat=True))
        self.assertEqual(urutan, sorted(urutan))
        self.assertLess(urutan[0], urutan[1])

    def test_label_kosong_ditolak(self):
        r = self._penyebab_post(label="   ", nilai="10")
        self.assertEqual(r.status_code, 400)
        self.assertFalse(RekapPenyebab.objects.filter(toko=self.toko, periode=PERIODE).exists())

    def test_nilai_invalid_ditolak(self):
        r = self._penyebab_post(label="X", nilai="abc")
        self.assertEqual(r.status_code, 400)

    def test_hapus_persist_dan_audit(self):
        p = self.penyebab("Mistake credit", "500")
        r = self.client.post(reverse("rekap_penyebab_simpan"), {
            "bulan": SEL_BULAN, "hapus": "1", "id": p.id})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(RekapPenyebab.objects.filter(pk=p.id).exists())
        self.assertTrue(AuditLog.objects.filter(aksi="rekap_penyebab_hapus").exists())

    def test_hapus_toko_lain_404(self):
        lain = Toko.objects.exclude(pk=self.toko.pk).first()
        p_lain = RekapPenyebab.objects.create(
            toko=lain, periode=PERIODE, label="Punya toko lain", nilai=Decimal("1"))
        r = self.client.post(reverse("rekap_penyebab_simpan"), {
            "bulan": SEL_BULAN, "hapus": "1", "id": p_lain.id})
        self.assertEqual(r.status_code, 404)
        self.assertTrue(RekapPenyebab.objects.filter(pk=p_lain.id).exists())

    def test_datalist_saran_tampil(self):
        isi = self._get().content.decode()
        for saran in ("Auto Pulsa", "Delete transaksi deposit", "Mistake credit",
                      "Salah tujuan bank"):
            self.assertIn(saran, isi)


class CarryLockUiTests(_RekapPageData):
    def _mei_berisi(self):
        self.manual("bank_dp", "999", bulan=6)
        self.manual("wl", "100", bulan=6)

    def test_banner_tampil_saat_carry_belum_dikunci(self):
        self._mei_berisi()
        isi = self._get().content.decode()
        self.assertIn("belum dikunci", isi)
        self.assertIn("kunci", isi.lower())

    def test_banner_hilang_setelah_dikunci(self):
        self._mei_berisi()
        self.manual("wallet_balance_lalu", "100")
        self.manual("akuran_lalu", "0")
        self.manual("dana_lebih_lalu", "999")
        isi = self._get().content.decode()
        self.assertNotIn("belum dikunci", isi)

    def test_tanpa_data_bulan_lalu_tak_ada_banner(self):
        isi = self._get().content.decode()
        self.assertNotIn("belum dikunci", isi)


class BonusLainTooltipTests(_RekapPageData):
    def test_tooltip_muncul_saat_detail_terisi(self):
        self.bonus_panel("budi", "10000", kategori="Redemption Coupon")
        isi = self._get().content.decode()
        self.assertIn("Redemption Coupon", isi)

    def test_tanpa_bonus_lain_tak_ada_bocoran_nama_kategori(self):
        isi = self._get().content.decode()
        self.assertNotIn("Redemption Coupon", isi)


class SidebarTests(_RekapPageData):
    def test_menu_rekap_bulanan_tampil_setelah_ringkasan_bulanan(self):
        r = self._get()
        isi = r.content.decode()
        pos_bulanan = isi.index("Ringkasan Bulanan</a>")
        pos_rekap = isi.index("Rekap Bulanan</a>")
        pos_rekening = isi.index("Rincian Rekening</a>")
        self.assertLess(pos_bulanan, pos_rekap)
        self.assertLess(pos_rekap, pos_rekening)

    def test_link_aktif_saat_di_halaman_rekap(self):
        isi = self._get().content.decode()
        self.assertIn('href="/rekap-bulanan/"', isi)
