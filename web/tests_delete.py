from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import TestCase
from django.urls import reverse

from sources.models import SourceType, Toko, Upload
from transactions.models import Transaction

User = get_user_model()


def _mk_upload(toko, with_file=False):
    st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
    up = Upload.objects.create(source_type=st, toko=toko, original_name="f.xlsx")
    if with_file:
        up.file.save("f.xlsx", ContentFile(b"data"), save=True)
    return up, st


class DeleteUploadTests(TestCase):
    def setUp(self):
        self.lbs = Toko.objects.get(key="lbs")
        User.objects.create_user("adm", password="pw123456", role="admin")

    def test_admin_hapus_upload_beserta_tx_dan_file(self):
        from datetime import datetime
        from decimal import Decimal
        up, st = _mk_upload(self.lbs, with_file=True)
        path = up.file.name
        Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="del-1",
        )
        self.client.login(username="adm", password="pw123456")
        r = self.client.post(reverse("delete_upload", args=[up.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Upload.objects.filter(pk=up.pk).exists())
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertFalse(default_storage.exists(path))

    def test_auditor_ditolak(self):
        up, _ = _mk_upload(self.lbs)
        aud = User.objects.create_user("aud1", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud1", password="pw123456")
        self.client.post(reverse("delete_upload", args=[up.pk]))
        self.assertTrue(Upload.objects.filter(pk=up.pk).exists())

    def test_get_tidak_menghapus(self):
        up, _ = _mk_upload(self.lbs)
        self.client.login(username="adm", password="pw123456")
        self.client.get(reverse("delete_upload", args=[up.pk]))
        self.assertTrue(Upload.objects.filter(pk=up.pk).exists())

    def test_tombol_hapus_massal_admin_dan_supervisor_bukan_auditor(self):
        """Tombol hapus massal upload: admin + supervisor YA, auditor TIDAK."""
        _mk_upload(self.lbs)
        aud = User.objects.create_user("aud2", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud2", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("upload"))
        self.assertNotContains(r, "Hapus terpilih")
        self.assertNotContains(r, 'id="chkAll"')
        for nama in ("adm", "sup_up_btn"):
            if nama != "adm":
                User.objects.create_user(nama, password="pw123456", role="supervisor")
            self.client.login(username=nama, password="pw123456")
            self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
            r = self.client.get(reverse("upload"))
            self.assertContains(r, "Hapus terpilih", msg_prefix=nama)
            self.assertContains(r, 'id="chkAll"', msg_prefix=nama)

    def test_supervisor_hapus_upload_satuan(self):
        up, _ = _mk_upload(self.lbs)
        User.objects.create_user("sup_up", password="pw123456", role="supervisor")
        self.client.login(username="sup_up", password="pw123456")
        self.client.post(reverse("delete_upload", args=[up.pk]))
        self.assertFalse(Upload.objects.filter(pk=up.pk).exists())

    def test_supervisor_hapus_upload_massal(self):
        up, _ = _mk_upload(self.lbs)
        User.objects.create_user("sup_upm", password="pw123456", role="supervisor")
        self.client.login(username="sup_upm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.client.post(reverse("bulk_delete_uploads"), {"upload_ids": [str(up.pk)]})
        self.assertFalse(Upload.objects.filter(pk=up.pk).exists())

    def test_guard_integritas_tetap_menolak_supervisor(self):
        """`_locking_batches` BUKAN guard peran — ia berlaku juga utk supervisor.

        Hak hapus supervisor disetarakan dengan admin (v1.24.0), tapi admin pun
        tak pernah kebal guard ini: upload yang buktinya dipakai hasil
        rekonsiliasi tetap tak boleh hilang.
        """
        from datetime import date
        from reconciliation.models import ReconBatch, ToleranceProfile
        up, st = _mk_upload(self.lbs)
        tol = ToleranceProfile.objects.get(name="Default")
        b = ReconBatch.objects.create(
            toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 20), summary={})
        Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis="depo",
            amount=1000, row_hash="lock1", consumed_by_batch=b)
        User.objects.create_user("sup_lock", password="pw123456", role="supervisor")
        self.client.login(username="sup_lock", password="pw123456")
        r = self.client.post(reverse("delete_upload", args=[up.pk]), follow=True)
        self.assertTrue(Upload.objects.filter(pk=up.pk).exists())
        self.assertContains(r, "tidak bisa dihapus")


class DeleteBatchTests(TestCase):
    def setUp(self):
        from reconciliation.engine import run_batch
        from reconciliation.models import ToleranceProfile
        self.lbs = Toko.objects.get(key="lbs")
        tol = ToleranceProfile.objects.get_or_create(name="Default", defaults={"date_window_days": 1})[0]
        self.batch = run_batch(self.lbs, tol)
        User.objects.create_user("adm", password="pw123456", role="admin")

    def test_admin_hapus_batch_transaksi_utuh(self):
        from datetime import datetime
        from decimal import Decimal
        from reconciliation.models import MatchRun, ReconBatch
        st = SourceType.objects.get_or_create(key="panel", defaults={"name": "Panel"})[0]
        up = Upload.objects.create(source_type=st, toko=self.lbs)
        Transaction.objects.create(
            upload=up, source_type=st, toko=self.lbs, jenis="depo",
            amount=Decimal("1"), money_delta=Decimal("1"),
            occurred_at=datetime(2026, 6, 27, 10, 0), row_hash="keep-1",
        )
        self.client.login(username="adm", password="pw123456")
        r = self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertEqual(MatchRun.objects.filter(batch_id=self.batch.pk).count(), 0)
        self.assertEqual(Transaction.objects.count(), 1)  # transaksi TIDAK ikut terhapus

    def _mk_result(self, batch):
        """Satu MatchResult di dalam batch (untuk ditempeli ReviewAction)."""
        from reconciliation.models import MatchResult, MatchRun, ToleranceProfile
        tol = ToleranceProfile.objects.get(name="Default")
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=tol, batch=batch)
        return MatchResult.objects.create(run=run, bucket=MatchResult.Bucket.COCOK)

    def test_supervisor_boleh_hapus_batch_terakhir(self):
        from datetime import date
        from core.models import AuditLog
        from reconciliation.models import ReconBatch
        self.batch.recon_date = date(2026, 8, 21)
        self.batch.save(update_fields=["recon_date"])
        User.objects.create_user("sup", password="pw123456", role="supervisor")
        self.client.login(username="sup", password="pw123456")
        r = self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        # M5: jejak audit menyimpan recon_date + jumlah review.
        log = AuditLog.objects.filter(aksi="hapus_batch").latest("id")
        self.assertEqual(log.detail.get("recon_date"), "2026-08-21")
        self.assertEqual(log.detail.get("n_review"), 0)

    def test_supervisor_boleh_hapus_batch_punya_review(self):
        """Guard v1.22.0 DICABUT (v1.24.0) — tapi jejak audit wajib mencatat
        berapa keputusan review manual ikut hilang, karena ReviewAction mati
        lewat cascade dan angka ini satu-satunya sisa buktinya."""
        from reconciliation.models import ReconBatch, ReviewAction
        res = self._mk_result(self.batch)
        ReviewAction.objects.create(result=res, action="override")
        User.objects.create_user("sup_rv", password="pw123456", role="supervisor")
        self.client.login(username="sup_rv", password="pw123456")
        self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        from core.models import AuditLog
        log = AuditLog.objects.filter(aksi="hapus_batch").latest("id")
        self.assertEqual(log.detail.get("n_review"), 1)

    def test_admin_tetap_boleh_hapus_batch_punya_review(self):
        from reconciliation.models import ReconBatch, ReviewAction
        res = self._mk_result(self.batch)
        ReviewAction.objects.create(result=res, action="override")
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        from core.models import AuditLog
        log = AuditLog.objects.filter(aksi="hapus_batch").latest("id")
        self.assertEqual(log.detail.get("n_review"), 1)

    def test_supervisor_boleh_hapus_batch_bukan_terakhir(self):
        from datetime import date
        from reconciliation.models import ReconBatch, ToleranceProfile
        tol = ToleranceProfile.objects.get(name="Default")
        self.batch.recon_date = date(2026, 8, 20)
        self.batch.save(update_fields=["recon_date"])
        ReconBatch.objects.create(
            toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 21), summary={})
        User.objects.create_user("sup_nl", password="pw123456", role="supervisor")
        self.client.login(username="sup_nl", password="pw123456")
        self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())

    def test_auditor_tetap_ditolak_hapus_batch(self):
        from reconciliation.models import ReconBatch
        aud = User.objects.create_user("aud_b", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud_b", password="pw123456")
        self.client.post(reverse("delete_batch", args=[self.batch.pk]))
        self.assertTrue(ReconBatch.objects.filter(pk=self.batch.pk).exists())

    def test_supervisor_tetap_ditolak_kelola(self):
        """Hak hapus supervisor TIDAK meluas ke /kelola/ (toko, user, IP)."""
        from web.models import AllowedIP
        target = User.objects.create_user("korban", password="pw123456", role="auditor")
        ip = AllowedIP.objects.create(label="kantor", cidr="10.9.8.0/24")
        User.objects.create_user("sup_k", password="pw123456", role="supervisor")
        self.client.login(username="sup_k", password="pw123456")
        self.client.post(reverse("delete_toko", args=[self.lbs.pk]))
        self.assertTrue(Toko.objects.filter(pk=self.lbs.pk).exists())
        self.client.post(reverse("delete_user", args=[target.pk]))
        self.assertTrue(User.objects.filter(pk=target.pk).exists())
        self.client.post(reverse("kelola_ip"), {"action": "delete", "ip_id": str(ip.pk)})
        self.assertTrue(AllowedIP.objects.filter(pk=ip.pk).exists())

    def test_tombol_hapus_batch_tampil_untuk_supervisor(self):
        User.objects.create_user("sup_ui", password="pw123456", role="supervisor")
        self.client.login(username="sup_ui", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'id="chkAllBatch"')
        self.assertContains(r, "Hapus terpilih")

    def test_riwayat_batch_punya_checkbox_massal_admin(self):
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.get(reverse("reconcile"))
        self.assertContains(r, 'id="chkAllBatch"')
        self.assertContains(r, 'name="batch_ids"')
        self.assertContains(r, "Hapus terpilih")
        self.assertContains(r, reverse("bulk_delete_batches"))

    def test_bulk_delete_batches_admin(self):
        from datetime import date
        from reconciliation.models import ReconBatch, ToleranceProfile
        tol = ToleranceProfile.objects.get(name="Default")
        b2 = ReconBatch.objects.create(toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 22), summary={})
        b3 = ReconBatch.objects.create(toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 23), summary={})
        self.client.login(username="adm", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        r = self.client.post(reverse("bulk_delete_batches"), {
            "batch_ids": [str(b2.pk), str(b3.pk)],
            "bulan": "2026-08",
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn("bulan=2026-08", r.url)
        self.assertFalse(ReconBatch.objects.filter(pk__in=[b2.pk, b3.pk]).exists())
        self.assertTrue(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        from core.models import AuditLog
        log = AuditLog.objects.filter(aksi="hapus_batch_massal").latest("id")
        self.assertEqual(log.detail.get("n_batch"), 2)

    def test_bulk_delete_batches_supervisor_ekor_terakhir(self):
        """Supervisor boleh hapus massal ekor batch terbaru (urut terbaru-dulu)."""
        from datetime import date
        from reconciliation.models import ReconBatch, ToleranceProfile
        tol = ToleranceProfile.objects.get(name="Default")
        b2 = ReconBatch.objects.create(toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 22), summary={})
        b3 = ReconBatch.objects.create(toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 23), summary={})
        User.objects.create_user("sup2", password="pw123456", role="supervisor")
        self.client.login(username="sup2", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.client.post(reverse("bulk_delete_batches"),
                         {"batch_ids": [str(b2.pk), str(b3.pk)]})
        self.assertFalse(ReconBatch.objects.filter(pk__in=[b2.pk, b3.pk]).exists())
        self.assertTrue(ReconBatch.objects.filter(pk=self.batch.pk).exists())

    def test_bulk_delete_batches_supervisor_boleh_batch_lama(self):
        """Guard "hanya batch terakhir" DICABUT (v1.24.0): batch lama ikut terhapus.

        Sebelumnya batch non-terakhir dilewati & dilaporkan; kini supervisor
        setara admin, jadi keduanya benar-benar hilang.
        """
        from datetime import date
        from reconciliation.models import ReconBatch, ToleranceProfile
        tol = ToleranceProfile.objects.get(name="Default")
        self.batch.recon_date = date(2026, 8, 20)
        self.batch.save(update_fields=["recon_date"])
        b2 = ReconBatch.objects.create(toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 22), summary={})
        b3 = ReconBatch.objects.create(toko=self.lbs, tolerance=tol, recon_date=date(2026, 8, 23), summary={})
        User.objects.create_user("sup3", password="pw123456", role="supervisor")
        self.client.login(username="sup3", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        # Pilih batch paling lama + paling baru: KEDUANYA terhapus sekarang.
        self.client.post(reverse("bulk_delete_batches"),
                         {"batch_ids": [str(self.batch.pk), str(b3.pk)]})
        self.assertFalse(ReconBatch.objects.filter(pk=b3.pk).exists())
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        # Yang TIDAK dipilih tetap utuh — penghapusan hanya menyentuh pilihan.
        self.assertTrue(ReconBatch.objects.filter(pk=b2.pk).exists())

    def test_bulk_delete_batches_supervisor_boleh_batch_ber_review(self):
        """Jalur massal ikut mencabut guard review — dan mencatat jumlahnya.

        `n_review` di jejak audit adalah satu-satunya sisa bukti bahwa
        keputusan review manual pernah ada di batch yang dihapus.
        """
        from reconciliation.models import MatchResult, MatchRun, ReconBatch, ReviewAction, ToleranceProfile
        tol = ToleranceProfile.objects.get(name="Default")
        run = MatchRun.objects.create(
            relation=MatchRun.Relation.PANEL_BANK, tolerance=tol, batch=self.batch)
        res = MatchResult.objects.create(run=run, bucket=MatchResult.Bucket.COCOK)
        ReviewAction.objects.create(result=res, action="override")
        User.objects.create_user("sup4", password="pw123456", role="supervisor")
        self.client.login(username="sup4", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})
        self.client.post(reverse("bulk_delete_batches"),
                         {"batch_ids": [str(self.batch.pk)]})
        self.assertFalse(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        from core.models import AuditLog
        log = AuditLog.objects.filter(aksi="hapus_batch_massal").latest("id")
        self.assertEqual(log.detail.get("n_review"), 1)

    def test_bulk_delete_batches_auditor_ditolak(self):
        from reconciliation.models import ReconBatch
        aud = User.objects.create_user("aud3", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud3", password="pw123456")
        self.client.post(reverse("bulk_delete_batches"), {"batch_ids": [str(self.batch.pk)]})
        self.assertTrue(ReconBatch.objects.filter(pk=self.batch.pk).exists())

    def test_bulk_delete_batches_tanpa_toko_aktif_gagal(self):
        """M1 fail-closed: toko aktif None → tidak ada satu batch pun dihapus."""
        from reconciliation.models import ReconBatch
        self.client.login(username="adm", password="pw123456")
        Toko.objects.update(is_active=False)  # tokos_for jadi kosong → active None
        r = self.client.post(reverse("bulk_delete_batches"),
                             {"batch_ids": [str(self.batch.pk)]}, follow=True)
        self.assertTrue(ReconBatch.objects.filter(pk=self.batch.pk).exists())
        self.assertContains(r, "Toko aktif tidak ditemukan")


class HutangManualHapusSupervisorTests(TestCase):
    """Supervisor mendapat cabang HAPUS override hutang/piutang; simpan tetap admin."""

    def setUp(self):
        from datetime import date
        from web.models import HutangManual
        self.lbs = Toko.objects.get(key="lbs")
        self.periode = date(2026, 8, 1)
        HutangManual.objects.create(
            toko=self.lbs, periode=self.periode, field=HutangManual.FIELD_HUTANG,
            nilai="1000", tanggal=date(2026, 8, 15))
        User.objects.create_user("sup_h", password="pw123456", role="supervisor")
        self.client.login(username="sup_h", password="pw123456")
        self.client.post(reverse("set_toko"), {"toko_id": self.lbs.id})

    def test_supervisor_boleh_hapus_override(self):
        from web.models import HutangManual
        r = self.client.post(reverse("hutang_manual_simpan"),
                             {"bulan": "2026-08", "hapus": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(HutangManual.objects.filter(
            toko=self.lbs, periode=self.periode).exists())
        from core.models import AuditLog
        self.assertTrue(AuditLog.objects.filter(aksi="hutang_manual_hapus").exists())

    def test_supervisor_ditolak_simpan_override(self):
        from web.models import HutangManual
        r = self.client.post(reverse("hutang_manual_simpan"), {
            "bulan": "2026-08", "tanggal": "2026-08-15",
            "nilai_hutang": "2000", "catatan": "coba",
        }, follow=True)
        self.assertContains(r, "khusus admin")
        obj = HutangManual.objects.get(toko=self.lbs, periode=self.periode,
                                       field=HutangManual.FIELD_HUTANG)
        self.assertEqual(str(obj.nilai), "1000.00")

    def test_auditor_tetap_ditolak_hapus_override(self):
        from web.models import HutangManual
        aud = User.objects.create_user("aud_h", password="pw123456", role="auditor")
        aud.allowed_tokos.add(self.lbs)
        self.client.login(username="aud_h", password="pw123456")
        self.client.post(reverse("hutang_manual_simpan"),
                         {"bulan": "2026-08", "hapus": "1"})
        self.assertTrue(HutangManual.objects.filter(
            toko=self.lbs, periode=self.periode).exists())
