# Menu Admin Log Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Halaman `/kelola/log/` khusus admin untuk melihat AuditLog dengan search & filter, plus pencatatan diperluas ke aksi kelola user/toko & ganti password, plus snapshot `username` supaya jejak pelaku hidup selamanya.

**Architecture:** Mengikuti pola `kelola/*` yang ada: view `@admin_required` di `web/admin_views.py`, template `web/kelola/log.html` (design system app_base), label aksi di `web/templatetags/web_extras.py` (pola REASON_LABELS), paginasi `Paginator(...,40)` + `{% pager page %}` (preserve querystring). Pencatatan memakai helper `core.audit.catat` yang sudah ada.

**Tech Stack:** Django 5.2; tes `django.test.TestCase` pola `web/tests_audit.py`.

## Global Constraints

- Bahasa UI/komentar Indonesia; identifier Inggris.
- Halaman HANYA admin (`admin_required`); log MENCATAT aksi semua role (keputusan user).
- Login/logout TIDAK dicatat (user tidak memilihnya).
- **Migrasi baru: core 0002** (AddField `AuditLog.username` + backfill dari FK) — deploy berikutnya menjalankan migrate.
- Filter form = GET (URL bisa dishare); pager sudah preserve querystring.
- Tes render base.html butuh staticfiles manifest (sudah ada di worktree ini).

---

### Task A: Snapshot `username` di AuditLog

**Files:** Modify `core/models.py`, `core/audit.py`; Create `core/migrations/0002_auditlog_username.py`; Test `web/tests_audit_log.py` (baru).

- Field: `username = models.CharField(max_length=150, blank=True, default="")` — identitas pelaku bertahan walau FK user SET_NULL.
- `catat()` mengisi `username=getattr(user, "username", "") or ""`.
- Migration: AddField + RunPython backfill loop (baris prod cuma puluhan).
- Tes: catat menyimpan snapshot; snapshot hidup setelah user dihapus.

### Task B: Pencatatan aksi kelola user/toko + ganti password

**Files:** Modify `web/admin_views.py`, `web/views.py` (ganti_password); Test `web/tests_audit_log.py`.

Aksi baru via `catat()`: `buat_user`, `ubah_user`, `reset_password`, `aktifkan_user`/`nonaktifkan_user`, `hapus_user`, `buat_toko`, `aktifkan_toko`/`nonaktifkan_toko`, `hapus_toko` (detail n_tx/n_up/n_batch), `ganti_password` (self, di web/views.py). Objek = username/nama toko. Tes: tiap aksi menulis 1 baris AuditLog dengan aksi & objek benar.

### Task C: Halaman `/kelola/log/` + menu sidebar + label

**Files:** Modify `web/admin_views.py` (view `kelola_log`), `web/urls.py`, `web/templates/web/app_base.html` (menu Admin), `web/templatetags/web_extras.py` (AKSI_LABELS + filter `aksi_label`/`aksi_tone`); Create `web/templates/web/kelola/log.html`; Test `web/tests_audit_log.py`.

- Filter: `q` (objek/username/aksi icontains), `aksi` (dropdown distinct DB), `user` (dropdown), `toko` (dropdown), `from`/`to` (`created_at__date`), tombol Filter + Reset. Paginator 40 + `{% pager page %}`.
- Tabel: Waktu · User (snapshot + role bila FK hidup) · Aksi (badge tone: hapus_*=bad, reset/nonaktif=warn, lainnya ok/muted) · Objek · Toko · Detail (chip k=v dari JSON).
- Sidebar Admin: link "Log Audit" (ikon scroll), active `'/kelola/log' in p`, hanya `is_admin_user`.
- Tes: admin 200 & isi tampil; supervisor/auditor redirect dashboard; filter aksi/q/tanggal/user bekerja; link sidebar hanya utk admin.

### Task D: Suite penuh + docs + push

Full suite hijau → commit → fetch+rebase → push origin/main. CLAUDE.md tidak perlu diubah (fitur web biasa). Update section Hasil di bawah.

---

## Hasil

Dieksekusi inline 2026-07-10 (4 task TDD):

- Task A: field `AuditLog.username` + migrasi core 0002 (AddField + backfill RunPython) + `catat()` mengisi otomatis — 2 tes.
- Task B: 10 aksi baru tercatat (buat/ubah/reset_password/aktifkan/nonaktifkan/hapus_user, buat/aktifkan/nonaktifkan/hapus_toko, ganti_password) — 9 tes.
- Task C: halaman `/kelola/log/` + menu sidebar + AKSI_LABELS (badge nada) + filter aksi/user/toko/tanggal + search q — 7 tes; verifikasi visual preview (badge berwarna, "user dihapus" utk FK mati, filter q bekerja).
- Suite penuh: **628 tes hijau** (610 → 628, +18).
- Gotcha yang ketangkap tes sendiri: placeholder input search sempat memuat contoh nyata ("Batch #3, budi") sehingga assertContains palsu — placeholder harus netral.
