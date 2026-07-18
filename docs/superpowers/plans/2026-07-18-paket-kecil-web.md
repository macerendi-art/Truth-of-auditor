# Paket Kecil Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tiga permintaan kecil klien: log hapus-massal menyebut nama file, pencarian nama file di Riwayat Upload (khusus admin), dan ganti nama toko di Kelola Toko.

**Architecture:** Perubahan tipis pada view/template yang sudah ada — tanpa model/migrasi baru. Detail di spec `docs/superpowers/specs/2026-07-18-paket-kecil-web-design.md`.

**Tech Stack:** Django 5.2 (`TestCase`), helper `web.access.is_admin`, `core.audit.catat`.

## Global Constraints

- Venv checkout utama: `/Users/macads/Truth-of-auditor/.venv/bin/python` (worktree tanpa .venv).
- UI/komentar bahasa Indonesia; tanpa emoji/glyph-teks; ikuti markup form yang sudah ada di template target.
- TANPA migrasi; `Toko.key` TIDAK pernah berubah.
- `collectstatic --noinput` sekali bila test render kena `Missing staticfiles manifest entry`.
- Commit di akhir task; JANGAN push/deploy (controller yang push+deploy).
- JANGAN `git add -A` — stage hanya file yang diubah.

---

### Task 1: Tiga fitur paket kecil (D1+D2+D3)

**Files:**
- Modify: `web/admin_views.py` (bulk_delete_uploads, kelola_toko)
- Modify: `web/views.py` (`_uploads_page`, view `upload`)
- Modify: `web/templates/web/upload.html` (form cari, header kartu Riwayat Upload)
- Modify: `web/templates/web/kelola/toko.html` (form rename per baris)
- Modify (bila peta label eksplisit ada): `web/templatetags/web_extras.py` (`aksi_label` utk `ubah_nama_toko`)
- Test: `web/tests_paket_kecil.py` (file baru)

**Interfaces:**
- Consumes: `web.access.is_admin`, `core.audit.catat`, `_uploads_for`, `_locking_batches`, konteks template `is_admin_user`.
- Produces: `_uploads_page(toko, request, q="")`; aksi POST `rename` di `kelola_toko`; log `hapus_upload_massal` ber-`detail["files"]`.

- [ ] **Step 1: Tulis failing tests**

Buat `web/tests_paket_kecil.py`:

```python
"""Paket kecil web: log hapus massal ber-nama-file, cari riwayat upload (admin),
ganti nama toko."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from sources.models import SourceType, Toko, Upload


def _buat_user(username, role, toko=None):
    u = get_user_model().objects.create_user(
        username=username, password="rahasia123", role=role)
    if toko is not None:
        u.allowed_tokos.add(toko)
    return u


class _Dasar(TestCase):
    def setUp(self):
        self.toko = Toko.objects.get(key="lbs")
        self.bank = SourceType.objects.get_or_create(
            key="bank", defaults={"name": "Bank"})[0]

    def _login(self, role="admin"):
        user = _buat_user(f"u_{role}", role, self.toko)
        self.client.force_login(user)
        s = self.client.session
        s["active_toko_id"] = self.toko.id
        s.save()
        return user

    def _upload(self, nama):
        return Upload.objects.create(
            source_type=self.bank, toko=self.toko, original_name=nama)


class HapusMassalLogNamaFileTests(_Dasar):
    def test_log_memuat_nama_file_terhapus(self):
        self._login("admin")
        a = self._upload("01_07_BANK_A.csv")
        b = self._upload("01_07_BANK_B.csv")
        r = self.client.post(reverse("bulk_delete_uploads"),
                             {"upload_ids": [a.id, b.id]})
        self.assertEqual(r.status_code, 302)
        log = AuditLog.objects.filter(aksi="hapus_upload_massal").latest("id")
        self.assertIn("01_07_BANK_A.csv", log.detail["files"])
        self.assertIn("01_07_BANK_B.csv", log.detail["files"])


class CariRiwayatUploadTests(_Dasar):
    def setUp(self):
        super().setUp()
        self._upload("17-07-2026 MUL DP BCA ZUNAEDY.CSV")
        self._upload("17-07-2026 MUL DP QRIS FLYER.xlsx")

    def test_admin_bisa_cari_nama_file(self):
        self._login("admin")
        r = self.client.get(reverse("upload"), {"q": "FLYER"})
        self.assertContains(r, "QRIS FLYER.xlsx")
        self.assertNotContains(r, "BCA ZUNAEDY.CSV")

    def test_non_admin_parameter_diabaikan(self):
        self._login("auditor")
        r = self.client.get(reverse("upload"), {"q": "FLYER"})
        self.assertContains(r, "QRIS FLYER.xlsx")
        self.assertContains(r, "BCA ZUNAEDY.CSV")  # daftar penuh

    def test_form_cari_hanya_utk_admin(self):
        self._login("auditor")
        r = self.client.get(reverse("upload"))
        self.assertNotContains(r, 'name="q"')


class GantiNamaTokoTests(_Dasar):
    def test_rename_sukses_dan_terlog(self):
        self._login("admin")
        lama = self.toko.name
        r = self.client.post(reverse("kelola_toko"), {
            "action": "rename", "toko_id": self.toko.id,
            "nama_baru": "LBS Sports"})
        self.assertEqual(r.status_code, 302)
        self.toko.refresh_from_db()
        self.assertEqual(self.toko.name, "LBS Sports")
        self.assertEqual(self.toko.key, "lbs")  # key stabil
        log = AuditLog.objects.filter(aksi="ubah_nama_toko").latest("id")
        self.assertEqual(log.detail["nama_lama"], lama)
        self.assertEqual(log.detail["nama_baru"], "LBS Sports")

    def test_nama_kosong_ditolak(self):
        self._login("admin")
        lama = self.toko.name
        self.client.post(reverse("kelola_toko"), {
            "action": "rename", "toko_id": self.toko.id, "nama_baru": "   "})
        self.toko.refresh_from_db()
        self.assertEqual(self.toko.name, lama)

    def test_auditor_ditolak(self):
        self._login("auditor")
        r = self.client.post(reverse("kelola_toko"), {
            "action": "rename", "toko_id": self.toko.id, "nama_baru": "X"})
        self.assertIn(r.status_code, (302, 403))
        self.toko.refresh_from_db()
        self.assertNotEqual(self.toko.name, "X")
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_paket_kecil -v 2`
Expected: FAIL — `detail["files"]` KeyError; pencarian tak menyaring; aksi rename tak dikenal.

- [ ] **Step 3: Implementasi D1 (log nama file)**

Di `web/admin_views.py` `bulk_delete_uploads`: kumpulkan nama sebelum hapus —
di loop, setelah `up.delete()` tambah nama ke list `terhapus` (ambil
`up.original_name or f"Upload #{up.pk}"` SEBELUM delete), lalu ubah `catat`:

```python
        terhapus = []
        for up in ups:
            if _locking_batches(up):
                dilewati.append(up.original_name or f"Upload #{up.pk}")
                continue
            nama = up.original_name or f"Upload #{up.pk}"
            n_tx += up.transactions.count()
            if up.file:
                up.file.delete(save=False)
            up.delete()
            n_file += 1
            terhapus.append(nama)
        if n_file:
            catat(request.user, "hapus_upload_massal", f"{n_file} file",
                  toko=active, n_file=n_file, n_tx=n_tx,
                  files=", ".join(terhapus)[:1000])
```

(Sesuaikan dengan bentuk loop yang ada — jangan menduplikasi baris lain.)

- [ ] **Step 4: Implementasi D2 (cari riwayat, admin)**

`web/views.py`:

```python
def _uploads_page(toko, request, q=""):
    """Halaman riwayat upload (20/halaman, pager seragam) — dulu terpotong 20
    terakhir sehingga file tanggal lama tak bisa dihapus dari UI.
    `q` (khusus admin, diisi view) menyaring nama file."""
    qs = _uploads_for(toko)
    if q:
        qs = qs.filter(original_name__icontains=q)
    return Paginator(qs, 20).get_page(request.GET.get("page"))
```

Di view `upload` (kedua titik yang memanggil `_uploads_page`): hitung sekali di
awal `q = request.GET.get("q", "").strip() if is_admin(request.user) else ""`
(impor `is_admin` dari `web.access` bila belum) lalu teruskan
`_uploads_page(active, request, q=q)` dan tambahkan `"q": q` ke context render
terakhir.

Template `web/templates/web/upload.html`: di header kartu Riwayat Upload
(cari teks "Riwayat Upload"), tambahkan di sisi kanan header (ikuti markup
header kartu yang ada):

```html
{% if is_admin_user %}
<form method="get" class="row" style="gap:6px;align-items:center">
  <input name="q" value="{{ q|default:'' }}" placeholder="Cari nama file…"
         style="max-width:220px" aria-label="Cari nama file">
  <button class="btn sm" type="submit">Cari</button>
  {% if q %}<a class="btn sm ghost" href="{% url 'upload' %}">Reset</a>{% endif %}
</form>
{% endif %}
```

- [ ] **Step 5: Implementasi D3 (rename toko)**

`web/admin_views.py` `kelola_toko` — blok baru setelah blok `toggle`:

```python
    if request.method == "POST" and request.POST.get("action") == "rename":
        tid = request.POST.get("toko_id", "")
        nama_baru = (request.POST.get("nama_baru") or "").strip()[:100]
        if not tid.isdecimal():
            messages.error(request, "ID toko tidak valid.")
            return redirect("kelola_toko")
        if not nama_baru:
            messages.error(request, "Nama baru wajib diisi.")
            return redirect("kelola_toko")
        t = get_object_or_404(Toko, pk=tid)
        nama_lama = t.name
        if nama_baru != nama_lama:
            t.name = nama_baru
            t.save(update_fields=["name"])
            catat(request.user, "ubah_nama_toko", f"{nama_lama} → {nama_baru}",
                  toko=t, nama_lama=nama_lama, nama_baru=nama_baru)
            messages.success(request, f"Nama toko {nama_lama} diganti menjadi {nama_baru}.")
        return redirect("kelola_toko")
```

Template `web/templates/web/kelola/toko.html`: di sel aksi tiap baris (sebelah
form toggle), form inline:

```html
          <form method="post" style="display:inline-flex;gap:4px;align-items:center">
            {% csrf_token %}
            <input type="hidden" name="action" value="rename">
            <input type="hidden" name="toko_id" value="{{ t.id }}">
            <input name="nama_baru" value="{{ t.name }}" maxlength="100"
                   style="max-width:140px" aria-label="Nama baru {{ t.name }}">
            <button class="btn sm" type="submit">Ganti Nama</button>
          </form>
```

Cek `web/templatetags/web_extras.py`: bila ada peta label aksi log
(mis. `AKSI_LABELS`/`aksi_label`), tambah entri `"ubah_nama_toko": "Ubah Nama Toko"`
mengikuti gaya entri lain; bila label dibangkitkan otomatis dari slug, lewati.

- [ ] **Step 6: Jalankan test, pastikan lulus**

Run: `/Users/macads/Truth-of-auditor/.venv/bin/python manage.py test web.tests_paket_kecil web.tests_audit_log -v 1`
Expected: PASS (8 test baru + modul log lama utuh).

- [ ] **Step 7: Commit**

```bash
git add web/admin_views.py web/views.py web/templates/web/upload.html \
        web/templates/web/kelola/toko.html web/tests_paket_kecil.py
git add web/templatetags/web_extras.py 2>/dev/null || true
git commit -m "feat(web): cari nama file riwayat upload (admin), log hapus massal ber-nama-file, ganti nama toko"
```
