from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from sources import services
from sources.models import SourceType, Toko
from transactions.models import Transaction

User = get_user_model()


class TokoModelTests(TestCase):
    def test_str_returns_name(self):
        t = Toko.objects.create(key="xyz", name="XYZ")
        self.assertEqual(str(t), "XYZ")

    def test_seed_creates_lbs_and_slo(self):
        self.assertTrue(Toko.objects.filter(key="lbs").exists())
        self.assertTrue(Toko.objects.filter(key="slo").exists())

    def test_seed_16_toko(self):
        keys = {
            "ahk", "mul", "stn", "lbs", "w25", "m25", "mxw", "hks",
            "bwn", "ltn", "wlg", "ssn", "ctr", "slo", "g25", "k25",
        }
        have = set(Toko.objects.values_list("key", flat=True))
        self.assertTrue(keys <= have, f"kurang: {keys - have}")
        self.assertEqual(Toko.objects.get(key="ahk").name, "AHK")
        self.assertEqual(Toko.objects.filter(key="lbs").count(), 1)  # tidak duplikat


_CANON = {
    "occurred_at": datetime(2026, 6, 27, 10, 0), "posted_date": None, "jenis": "depo",
    "amount": Decimal("50000"), "credit_delta": Decimal("-50000"), "money_delta": Decimal("50000"),
    "fee": Decimal("0"), "bonus": Decimal("0"), "balance_after": None,
    "ticket_no": "D1", "username": "budi", "reference": "", "counterparty": "",
    "description": "", "raw": {}, "row_hash": "hash-a2-1",
}


class _DummyBracket:
    source_key = "bracket"

    def parse(self, path, flow=""):
        return [dict(_CANON)]


class IngestTokoTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        SourceType.objects.get_or_create(key="bracket", defaults={"name": "Bracket"})

    def test_ingest_sets_toko_and_provider(self):
        with patch.dict(services.PARSERS, {"dummy": _DummyBracket}, clear=False):
            up, created, dup = services.ingest("dummy", "/nofile", toko=self.lbs, provider="Nexus")
        self.assertEqual(up.toko, self.lbs)
        self.assertEqual(up.provider, "Nexus")
        self.assertEqual(created, 1)
        self.assertEqual(Transaction.objects.get().toko, self.lbs)


class TokoPanelMigrationTests(TestCase):
    """Hasil migrasi data 0012: pengelompokan panel per key toko seed."""

    def test_slo_jadi_vigor(self):
        self.assertEqual(Toko.objects.get(key="slo").panel, Toko.PANEL_VIGOR)

    def test_w25_dan_g25_jadi_tm_gaming(self):
        self.assertEqual(Toko.objects.get(key="w25").panel, Toko.PANEL_TMG)
        self.assertEqual(Toko.objects.get(key="g25").panel, Toko.PANEL_TMG)

    def test_toko_lain_tetap_nexus(self):
        self.assertEqual(Toko.objects.get(key="lbs").panel, Toko.PANEL_NEXUS)
        self.assertEqual(Toko.objects.get(key="ahk").panel, Toko.PANEL_NEXUS)


class TokoPanelModelTests(TestCase):
    """Default field panel = nexus utk toko baru yang tak menyebut panel."""

    def test_default_panel_nexus(self):
        t = Toko.objects.create(key="qqq", name="QQQ")
        self.assertEqual(t.panel, Toko.PANEL_NEXUS)


class TokoPanelKelolaViewTests(TestCase):
    """Panel wajib diisi saat buat toko + aksi ubah panel per baris — via kelola_toko."""

    def setUp(self):
        User.objects.create_user("adm_panel", password="pw123456", role="admin")
        self.client.login(username="adm_panel", password="pw123456")

    def test_create_dengan_panel_valid_tersimpan_dan_terlog(self):
        self.client.post(reverse("kelola_toko"), {
            "action": "create", "kode": "zzp", "panel": Toko.PANEL_VIGOR,
            "kepemilikan": Toko.KEPEMILIKAN_PARTNER,
        })
        t = Toko.objects.get(key="zzp")
        self.assertEqual(t.panel, Toko.PANEL_VIGOR)
        self.assertEqual(t.kepemilikan, Toko.KEPEMILIKAN_PARTNER)
        log = AuditLog.objects.filter(aksi="buat_toko", objek="ZZP").latest("id")
        self.assertEqual(log.toko_id, t.id)

    def test_create_tanpa_panel_ditolak_tak_buat_toko(self):
        n = Toko.objects.count()
        r = self.client.post(reverse("kelola_toko"), {
            "action": "create", "kode": "zzb",
            "kepemilikan": Toko.KEPEMILIKAN_PUSAT,
        }, follow=True)
        self.assertEqual(Toko.objects.count(), n)
        self.assertFalse(Toko.objects.filter(key="zzb").exists())
        self.assertContains(r, "Pilih panel toko")

    def test_create_panel_bogus_ditolak_tak_buat_toko(self):
        n = Toko.objects.count()
        self.client.post(reverse("kelola_toko"), {
            "action": "create", "kode": "zzc", "panel": "galaksi",
            "kepemilikan": Toko.KEPEMILIKAN_PUSAT,
        })
        self.assertEqual(Toko.objects.count(), n)
        self.assertFalse(Toko.objects.filter(key="zzc").exists())

    def test_create_tanpa_kepemilikan_ditolak(self):
        n = Toko.objects.count()
        r = self.client.post(reverse("kelola_toko"), {
            "action": "create", "kode": "zzk", "panel": Toko.PANEL_NEXUS,
        }, follow=True)
        self.assertEqual(Toko.objects.count(), n)
        self.assertContains(r, "Pilih kepemilikan toko")

    def test_action_panel_mengubah_dan_terlog(self):
        t = Toko.objects.get(key="lbs")
        self.assertEqual(t.panel, Toko.PANEL_NEXUS)
        self.client.post(reverse("kelola_toko"), {
            "action": "panel", "toko_id": t.id, "panel": Toko.PANEL_VIGOR,
        })
        t.refresh_from_db()
        self.assertEqual(t.panel, Toko.PANEL_VIGOR)
        log = AuditLog.objects.filter(aksi="ubah_panel_toko").latest("id")
        self.assertIn("LBS", log.objek)
        self.assertEqual(log.toko_id, t.id)

    def test_action_kepemilikan_mengubah_dan_terlog(self):
        t = Toko.objects.get(key="lbs")
        self.assertEqual(t.kepemilikan, Toko.KEPEMILIKAN_PUSAT)
        self.client.post(reverse("kelola_toko"), {
            "action": "kepemilikan", "toko_id": t.id,
            "kepemilikan": Toko.KEPEMILIKAN_PARTNER,
        })
        t.refresh_from_db()
        self.assertEqual(t.kepemilikan, Toko.KEPEMILIKAN_PARTNER)
        log = AuditLog.objects.filter(aksi="ubah_kepemilikan_toko").latest("id")
        self.assertIn("LBS", log.objek)
        self.assertIn("Partner", log.objek)
        self.assertEqual(log.toko_id, t.id)

    def test_action_kepemilikan_tanpa_perubahan_tak_audit(self):
        t = Toko.objects.get(key="lbs")
        n_sebelum = AuditLog.objects.filter(aksi="ubah_kepemilikan_toko").count()
        self.client.post(reverse("kelola_toko"), {
            "action": "kepemilikan", "toko_id": t.id,
            "kepemilikan": Toko.KEPEMILIKAN_PUSAT,
        })
        self.assertEqual(
            AuditLog.objects.filter(aksi="ubah_kepemilikan_toko").count(), n_sebelum)

    def test_action_panel_tanpa_perubahan_tak_menulis_audit(self):
        t = Toko.objects.get(key="lbs")  # sudah nexus (default)
        n_sebelum = AuditLog.objects.filter(aksi="ubah_panel_toko").count()
        self.client.post(reverse("kelola_toko"), {
            "action": "panel", "toko_id": t.id, "panel": Toko.PANEL_NEXUS,
        })
        t.refresh_from_db()
        self.assertEqual(t.panel, Toko.PANEL_NEXUS)
        self.assertEqual(
            AuditLog.objects.filter(aksi="ubah_panel_toko").count(), n_sebelum)

    def test_toko_id_kepanjangan_ditolak_sebelum_query(self):
        """`isdecimal()` saja meloloskan "9"*11 ke query pk — di Postgres itu
        NumericValueOutOfRange/DataError (500), bukan 404 rapi. Batas panjang
        sama dengan `set_toko` (≤10 digit) menolaknya SEBELUM menyentuh DB:
        0 query ke tabel Toko. Berlaku utk aksi ber-toko_id di sini.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        for action, extra in (
            ("panel", {"panel": Toko.PANEL_VIGOR}),
            ("kepemilikan", {"kepemilikan": Toko.KEPEMILIKAN_PARTNER}),
            ("toggle", {}),
            ("rename", {"nama_baru": "Ngawur"}),
        ):
            with self.subTest(action=action):
                with CaptureQueriesContext(connection) as ctx:
                    r = self.client.post(reverse("kelola_toko"), {
                        "action": action, "toko_id": "9" * 11, **extra})
                self.assertEqual(r.status_code, 302)  # redirect + pesan galat
                self.assertFalse(
                    any('"sources_toko"' in q["sql"] for q in ctx),
                    f"id kepanjangan masih mencapai query Toko: "
                    f"{[q['sql'] for q in ctx]}")


class TokoKepemilikanModelTests(TestCase):
    def test_default_kepemilikan_pusat(self):
        t = Toko.objects.create(key="zzd", name="ZZD")
        self.assertEqual(t.kepemilikan, Toko.KEPEMILIKAN_PUSAT)
