# Spec: Panel Admin + RBAC Toko

**Tanggal:** 2026-07-02
**Status:** Disetujui untuk perencanaan implementasi
**Cakupan:** Spec A dari roadmap tiga tahap (A: panel admin+RBAC · B: upload lanjutan/password Mandiri+parser baru · C: arsip & report)

## 1. Tujuan

Admin dapat mengelola pengguna (auditor/supervisor/admin baru) dan toko (16+ kode) dari dalam aplikasi — tanpa Django `/admin/` — dan setiap pengguna hanya melihat data toko yang menjadi haknya.

## 2. Kondisi saat ini (baseline)

- `accounts.User.role` (admin/auditor) **ada tapi tidak dipakai** — semua view hanya `@login_required`.
- **Tidak ada relasi User↔Toko**; `set_toko`/`_active_toko` (web/views.py) mengizinkan user login mana pun memilih toko aktif mana pun.
- `Toko` (sources): `key` slug unik, `name`, `is_active`; seed hanya `lbs`, `slo`. Sudah jadi sumbu scoping Dashboard/Transaksi/Upload/Rekonsiliasi via `_active_toko()`.
- Satu-satunya user: `admin` (role=admin, superuser).

## 3. Model peran

| Peran | Akses toko | Panel Admin (`/kelola/…`) |
|---|---|---|
| `admin` | Semua toko aktif | ✅ |
| `supervisor` | Semua toko aktif | ❌ |
| `auditor` | Hanya `allowed_tokos` (wajib ≥1) | ❌ |

- Superuser diperlakukan seperti `admin`.
- `User.Role` ditambah `SUPERVISOR = "supervisor"`.

## 4. Perubahan data model

1. `accounts.User.allowed_tokos = ManyToManyField("sources.Toko", blank=True)` — hanya relevan untuk auditor.
2. `User.Role` + `SUPERVISOR`.
3. Data-migration seed toko (idempotent, `get_or_create` per key): AHK, MUL, STN, LBS, W25, M25, MXW, HKS, BWN, LTN, WLG, SSN, CTR, SLO, G25, K25 → `key` lowercase, `name` UPPERCASE. LBS/SLO yang ada tidak diduplikasi. Toko = **kode saja** (name = kode kapital).

## 5. Enforcement scoping (RBAC)

Titik kunci tunggal — helper `tokos_for(user)` di `web/access.py`:

- admin/superuser/supervisor → `Toko.objects.filter(is_active=True)`
- auditor → `user.allowed_tokos.filter(is_active=True)`

Dipakai di:

- `_active_toko(request)`: toko di session harus ∈ `tokos_for`; kalau tidak (akses dicabut/toko nonaktif), fallback ke toko pertama yang diizinkan; kalau kosong → `None`.
- `set_toko`: tolak toko di luar `tokos_for`.
- Context processor dropdown Toko: hanya `tokos_for(user)`.
- View inti yang menerima `active=None` merender empty-state "Tidak ada toko yang ditugaskan — hubungi admin" (pengaman; normalnya form mencegah auditor tanpa toko).

Karena semua halaman inti sudah lewat `_active_toko()`, satu titik ini mengunci Dashboard, Transaksi, Upload, Rekonsiliasi, batch/run detail.

## 6. Area Admin

Akses: decorator `@admin_required` (`login_required` + role admin/superuser). Non-admin → pesan error + redirect dashboard. Sidebar `app_base.html` dapat seksi **"Admin"** (Pengguna, Toko) yang hanya dirender untuk admin.

### 6.1 Kelola Pengguna — `/kelola/user/`

- **Daftar:** username, nama, role, toko ditugaskan (untuk auditor), status aktif, last login.
- **Tambah:** Username · Password (≥8 char) · Nama (`first_name`) · Role (admin/supervisor/auditor) · checkbox toko (muncul/berlaku hanya untuk auditor).
- **Edit:** nama, role, toko. **Reset password.** **Aktif/Nonaktif** (cabut akses; tanpa hapus permanen — user terkait Upload/ReviewAction).
- **Validasi:** role=auditor wajib ≥1 toko dicentang (tambah maupun edit). Password via `set_password`.
- **Self-protection:** admin tidak bisa menonaktifkan atau menurunkan role **dirinya sendiri**.

### 6.2 Kelola Toko — `/kelola/toko/`

- **Daftar:** kode, status aktif, jumlah transaksi & upload (info).
- **Tambah:** input kode saja → `key=lower`, `name=UPPER`; unik.
- **Aktif/Nonaktif.** Tanpa hapus (toko ber-FK ke Transaction/Upload/Account/ReconBatch).

## 7. Struktur kode

| Unit | Isi |
|---|---|
| `web/access.py` | `admin_required`, `tokos_for(user)` |
| `web/admin_views.py` | view kelola user + toko |
| `web/templates/web/kelola/users.html`, `toko.html` | UI, extend `app_base.html`, pakai design system yang ada |
| `web/urls.py` | route `/kelola/user/…`, `/kelola/toko/…` |
| `accounts/migrations/` | M2M `allowed_tokos` (+ pilihan role baru) |
| `sources/migrations/` | seed 16 toko |

Tanpa perubahan template login; tanpa perubahan model selain di atas.

## 8. Edge cases

- Auditor yang toko satu-satunya dinonaktifkan → empty-state (§5), admin menugaskan ulang.
- Session `active_toko_id` menunjuk toko yang tak lagi diizinkan → fallback otomatis, tanpa error.
- Username duplikat → error form standar.
- Admin menonaktifkan sesama admin: boleh; dirinya sendiri: ditolak.
- User `admin` eksisting (role=admin) otomatis melihat semua — tidak perlu backfill.

## 9. Testing

- **Akses:** auditor & supervisor ditolak dari `/kelola/…` (redirect+pesan); admin diizinkan; seksi sidebar Admin tak dirender untuk non-admin.
- **RBAC scoping:** auditor tak bisa `set_toko` ke toko yang tak ditugaskan; dropdown terfilter; supervisor melihat semua; auditor tanpa toko → empty-state.
- **Kelola user:** create (termasuk validasi auditor-≥1-toko & password <8 ditolak), edit role/toko, reset password, nonaktif→login gagal, self-protection.
- **Kelola toko:** create (normalisasi case, duplikat ditolak), nonaktif → hilang dari dropdown & `tokos_for`.
- **Seed:** migration menghasilkan tepat 16 toko, idempotent, LBS/SLO tak terduplikasi.

## 10. Di luar cakupan (spec berikutnya)

- Password file mutasi Mandiri saat upload; parser Unopay / Excel Credit Bonus / TM Gaming (**Spec B**, menunggu file sample).
- Arsip hasil rekonsiliasi & report Summary per toko (**Spec C**).
- Pembatasan fitur inti per peran di luar scoping toko (mis. supervisor read-only) — bisa ditambah nanti bila perlu.
