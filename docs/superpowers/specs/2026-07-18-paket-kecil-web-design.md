# Paket D — Paket Kecil Web — Desain

**Tanggal:** 2026-07-18 · **Status:** eksekusi otonom atas mandat user ("lanjutkan sampai selesai dan terdeploy"); lingkup disetujui pada pemetaan feedback 16–17 Jul · **Paket:** D

## Permintaan klien (chat @VoxelAster + daftar awal)

1. "bantu tambah fitur searching by nama file dibagian import data di akun admin aja gpp"
2. "di log auditnya jg keknya bole ditambah misal ada penghapusan, dia tambahin
   rincian file sama nama file apa yg dihapus"
3. "End user ingin mengedit nama toko"

## Kondisi kode saat ini

- `web/views.py` `upload` + `_uploads_page(toko, request)`: riwayat 20/hal, TANPA filter nama.
- `web/admin_views.py` `delete_upload` SUDAH mencatat nama file; `bulk_delete_uploads`
  hanya mencatat `"{n} file"` + hitungan — nama file hilang dari jejak.
- `web/admin_views.py` `kelola_toko`: aksi `create` + `toggle`; TIDAK ada ganti nama.
- Helper akses: `web.access.is_admin(user)`; template pakai konteks `is_admin_user`.
- Template log (`kelola/log.html`) merender `detail.items` sebagai `k=v` — nilai
  string panjang tampil apa adanya.

## Desain

### D1 — Rincian nama file di log hapus massal

`bulk_delete_uploads`: kumpulkan `original_name` tiap upload yang benar-benar
terhapus; sertakan di `catat`:

- `objek` tetap `"{n} file"`;
- `detail` tambah `files="a.csv, b.xlsx, …"` (join koma, potong 1000 karakter
  supaya JSON log tak membengkak; file terkunci yang dilewati TIDAK ikut daftar).

### D2 — Cari nama file di Riwayat Upload (khusus admin)

- `_uploads_page(toko, request, q="")` → bila `q` non-kosong filter
  `original_name__icontains=q` sebelum paginasi.
- View `upload`: `q` dibaca dari GET **hanya bila `is_admin(request.user)`**
  (auditor/supervisor: parameter diabaikan — sesuai permintaan "akun admin aja").
- Template `upload.html`: form GET kecil (input `q` + tombol Cari + link reset)
  di header kartu Riwayat Upload, dibungkus `{% if is_admin_user %}`.
  Pager sudah mempertahankan seluruh query kecuali `page` — `q` ikut otomatis.

### D3 — Ganti nama toko

- `kelola_toko` aksi baru `rename`: `toko_id` (decimal) + `nama_baru`
  (strip, wajib non-kosong, ≤100 = max_length field).
- Simpan `t.name`, `catat(request.user, "ubah_nama_toko", f"{lama} → {baru}",
  toko=t, nama_lama=lama, nama_baru=baru)`, message sukses.
- `key` toko TIDAK berubah (slug stabil dipakai harness/seed).
- Template `kelola/toko.html`: form inline per baris (input prefilled `t.name`,
  maxlength 100 + tombol "Ganti Nama"), pola sama form toggle yang ada.
- Halaman kelola toko sudah admin-only (`admin_required`) — tak ada perubahan akses.

## Uji

1. D1: hapus massal 2 upload → AuditLog `hapus_upload_massal` memuat kedua nama
   di `detail["files"]`; file terkunci dilewati tak masuk daftar.
2. D2: admin `?q=` menyaring riwayat; non-admin dengan `?q=` melihat daftar penuh
   (parameter diabaikan); form hanya dirender utk admin.
3. D3: rename sukses ubah nama + AuditLog + message; nama kosong ditolak;
   `key` tak berubah.

## Non-lingkup

Label aksi `ubah_nama_toko` perlu masuk peta label log (`aksi_label`) bila peta
eksplisit ada — cek `web_extras` saat implementasi; selain itu tidak ada.
