# Force Ganti Password di Login Pertama

**Tanggal:** 2026-07-09
**Status:** Disetujui (siap masuk plan implementasi)

## Latar & tujuan

Admin membuat akun user baru dan membagikan *password awal* (mis. via chat). Selama
user belum menggantinya, password itu dipegang minimal dua orang (admin + user), dan
bila admin memakai pola password yang sama untuk banyak user, satu bocor = banyak bocor.

Tujuan: **setiap user pada akhirnya punya password pribadi yang tidak diketahui admin.**
Caranya paling sederhana dan tidak ambigu: sebuah flag boolean per user. Selama flag
`TRUE`, user dipaksa membuat password baru sebelum bisa mengakses apa pun. Begitu diganti,
flag jadi `FALSE` dan tidak pernah mengganggu lagi.

Ini menggantikan ide awal "deteksi password shared" yang kompleks (harus melacak apakah
sebuah password unik atau dipakai bersama). Flag boolean: `TRUE` = belum ganti, `FALSE` = sudah.

## Keputusan yang sudah diambil

1. **Pemicu flag = buat user baru DAN reset password** (bukan cuma buat baru). Kapan pun
   admin *tahu* password seseorang, orang itu harus membuat yang baru.
   - Penyempurnaan: reset password hanya memaksa ganti bila `target != admin yang login`.
     Admin me-reset password **dirinya sendiri** = memilih password sendiri, jadi tidak
     perlu dipaksa ganti lagi. Makna flag: "password ini di-set orang lain / bersifat sementara".
2. **Password baru wajib berbeda dari password sementara.** Tanpa aturan ini user bisa
   "mengganti" ke password shared yang sama persis, membuat fitur percuma.

## Arsitektur

Gerbang (gate) dipasang sebagai **middleware**, bukan dekorator per-view. Alasan: syarat inti
"user tidak bisa akses halaman lain sampai password diganti, termasuk kalau langsung ketik URL"
menuntut satu titik cegat tunggal yang tidak bisa dilewati. Codebase saat ini tidak punya
middleware auth global (tiap view membawa `@login_required` sendiri), jadi ini penambahan bersih.

Alternatif yang ditolak:
- **Dekorator per-view / redirect saat login saja** — rapuh: 15+ view, gampang terlewat satu,
  dan view baru di masa depan diam-diam membuka celah bypass.
- **Subclass `LoginView` (redirect hanya saat login)** — gagal edge case inti: setelah masuk,
  user bisa langsung menuju `/transactions/` dsb.

### Komponen

**1. Model — `accounts/models.py`**

Tambah field pada `accounts.User`:

```python
must_change_password = models.BooleanField(default=False)
```

+ migrasi. `default=False` penting: user prod yang sudah ada dan admin bootstrap
(`createsuperuser`) tidak terpengaruh — hanya akun yang **secara eksplisit** kita tandai
yang kena gerbang.

**2. Titik yang men-set flag TRUE — `web/admin_views.py`**

- `kelola_user` (buat user): selalu `TRUE`. Admin selalu membuat untuk orang lain.
  Diteruskan lewat `create_user(..., must_change_password=True)`.
- `kelola_user_edit` action `reset_password`: set `TRUE` **hanya bila `target != request.user`**.
  Reset password sendiri → tetap `FALSE`.

**3. Middleware — `web/middleware.py` `ForcePasswordChangeMiddleware`**

Dipasang di `MIDDLEWARE` **setelah** `AuthenticationMiddleware` (butuh `request.user` sudah ada).

Logika per request:
- User anonim → lewati (halaman login dll. tidak terpengaruh).
- User terautentikasi **dan** `must_change_password == True` **dan** path bukan bagian allowlist
  → `redirect('ganti_password')`.
- Selain itu → teruskan.

Allowlist (path yang tetap boleh diakses saat flag menyala):
- URL halaman ganti password itu sendiri (`ganti_password`) — kalau tidak, redirect loop.
- `logout` — user harus selalu bisa keluar.
- prefix `STATIC_URL` dan `MEDIA_URL` — agar CSS/aset halaman ganti password tetap termuat.

Biayanya satu cek boolean pada objek user yang sudah dimuat — dapat diabaikan.

Django admin (`/admin/`) **tidak** di-allowlist: konsisten dengan syarat "tidak boleh akses
halaman lain". Karena flag hanya `TRUE` untuk akun yang kita tandai (bukan superuser bootstrap),
ini tidak mengunci admin secara tidak sengaja.

**4. Halaman & view ganti password**

- URL: `path("ganti-password/", views.ganti_password, name="ganti_password")` di `web/urls.py`.
- View `ganti_password(request)` di `web/views.py`, dihias `@login_required`. Efek samping
  gratis: bila sesi kedaluwarsa saat di halaman ini, submit → `login_required` melempar ke
  `/login/?next=…` (menutup edge case "sesi expired → balik ke login").
- Form `GantiPasswordForm(PasswordChangeForm)`:
  - Mewarisi field **password lama + baru + konfirmasi** dan pengecekan password lama benar.
  - Otomatis menjalankan `AUTH_PASSWORD_VALIDATORS` (min-length, umum, semua-angka, kemiripan
    atribut) — aturan yang sama dengan helper `_password_error` yang sudah ada.
  - Tambahan override `clean()` (di situ `old_password` dan `new_password1` yang sudah
    tervalidasi tersedia bersamaan): tolak bila password baru **sama persis** dengan
    password lama (aturan "wajib beda"). Pesan error Bahasa Indonesia.
- Alur sukses: `form.save()` (menyimpan password baru) → set `must_change_password = False`
  → `update_session_auth_hash(request, user)` (tetap login, tidak terlempar) →
  `messages.success(...)` → `redirect('dashboard')`.

**5. Template — `web/templates/registration/ganti_password.html`**

Halaman **berdiri sendiri**, bergaya seperti halaman login (kartu terpusat, branding), **bukan**
app shell dengan navigasi. Ini memperkuat "kerjakan ini dulu, tidak boleh berkeliaran" — user
bahkan tidak melihat menu untuk pergi. Menampilkan tiga field + error per-field/non-field,
tombol submit, dan link/tombol logout kecil sebagai jalan keluar.

## Alur data (ringkas)

```
Admin buat user / reset (orang lain)  ->  must_change_password = TRUE
                                              │
User login (pakai password sementara)         │
        │                                      │
        ▼                                      │
[middleware] flag == TRUE?  ── ya ──► redirect ke /ganti-password/
        │ tidak                                │
        ▼                                       ▼
   Dashboard normal              Form: lama + baru + konfirmasi
                                  (validasi Django + wajib-beda)
                                              │ sukses
                                              ▼
                                 set password, flag = FALSE,
                                 jaga sesi ► Dashboard
```

## Edge case & cara ditangani

| Edge case | Penanganan |
|---|---|
| Bypass dengan ketik URL langsung | Middleware mencegat **semua** request non-allowlist |
| Validasi password baru (panjang, umum, dll.) | `PasswordChangeForm` menjalankan `AUTH_PASSWORD_VALIDATORS` |
| Konfirmasi tidak cocok | Bawaan `PasswordChangeForm` (`new_password2`) |
| Password baru sama dengan sementara | `clean` kustom pada form menolak |
| Sesi kedaluwarsa saat di halaman ganti | View `@login_required` → lempar ke `/login/?next=…` |
| User perlu keluar tanpa ganti | `logout` masuk allowlist middleware |
| Admin bikin user → otomatis wajib ganti | `create_user(..., must_change_password=True)` |
| Admin reset password **dirinya sendiri** | Flag tidak di-set (`target != request.user`) |
| User & admin lama di prod | `default=False` → tak terpengaruh |

## Rencana pengujian (~10 test)

Model / titik pemicu:
- Field default `False` pada user baru via `create_superuser`/bootstrap.
- `kelola_user` membuat user → `must_change_password is True`.
- `reset_password` atas user lain → `True`.
- `reset_password` atas diri sendiri → tetap `False`.

Middleware:
- User ber-flag `True` GET `/transactions/` → redirect ke `ganti_password`.
- User ber-flag `True` GET `/ganti-password/` → 200 (boleh).
- User ber-flag `True` GET `/logout/` → boleh (tidak di-redirect ke ganti password).
- User ber-flag `False` → akses normal.

Form / view:
- Password lama salah → error, flag tetap `True`.
- Konfirmasi ≠ baru → error.
- Baru == lama (sementara) → error "wajib beda".
- Password lemah (mis. terlalu pendek / semua angka) → error validator.
- Sukses: flag jadi `False`, user tetap login (sesi terjaga), redirect ke `dashboard`.

## Di luar cakupan (YAGNI)

- UI admin untuk melihat/menyetel flag secara manual.
- Kedaluwarsa/rotasi password berkala.
- Notifikasi email.

Fokus tunggal: paksa ganti password pada login pertama (atau setelah reset oleh admin).
