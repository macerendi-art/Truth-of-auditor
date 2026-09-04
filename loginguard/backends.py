"""Auth backend: penguncian percobaan login (C4) per (username, IP).

KENAPA BACKEND, BUKAN MENGUBAH `web/views.py`/`AuditorLoginView`: berkas itu
(dan `web/signals.py`) sedang disunting agen lain (C6, audit gagal-login) di
gelombang paralel yang sama — dilarang disentuh. `django.contrib.auth.authenticate()`
memanggil SEMUA backend di `settings.AUTHENTICATION_BACKENDS` — satu-satunya
titik yang dilalui form login standar (`AuthenticationForm`/
`AdminAuthenticationForm`, jadi ini juga menggerbangi `/admin/login/`) TANPA
menyentuh satu baris pun di view/urls.

DUA BACKEND, BUKAN SATU (`settings.AUTHENTICATION_BACKENDS`): sesi yang sudah
login di produksi menyimpan `backend_path` lama
(`django.contrib.auth.backends.ModelBackend`) di session
(`django.contrib.auth.get_user()` menolak sesi bila `backend_path` itu tidak
lagi ada di `AUTHENTICATION_BACKENDS` — lihat `contrib/auth/__init__.py`).
Mengganti total dengan satu backend baru akan me-logout SEMUA sesi aktif saat
deploy. Menaruh `LockoutBackend` DI DEPAN `ModelBackend` bawaan menghindari
itu: sesi lama tetap valid (backend lamanya masih terdaftar), sedangkan login
BARU selalu lewat `LockoutBackend` dulu.

`PermissionDenied` yang dilempar di sini DITANGKAP oleh
`django.contrib.auth.authenticate()` sendiri: loop backend BERHENTI (baris
kedua/`ModelBackend` tidak ikut dicoba — kunci berlaku apa pun sandinya),
lalu `authenticate()` mengembalikan None — IDENTIK dengan kegagalan sandi
biasa. Ini disengaja (persyaratan butir 4): `AuthenticationForm` menampilkan
pesan generik yang SAMA PERSIS untuk sandi salah, username tak dikenal, ATAU
akun terkunci (lihat `web/templates/registration/login.html`: satu baris
"Username atau password salah. Coba lagi." untuk SEMUA `form.errors`, tidak
pernah membedakan sumbernya) — penyerang tidak bisa membedakan ketiganya.
`user_login_failed` (signal yang dipakai C6 untuk audit `login_gagal`) tetap
terkirim oleh `authenticate()` SENDIRI baik lewat jalur `break` (PermissionDenied)
maupun exhaustion loop biasa (kode sumbernya mengirim sinyal itu TANPA
syarat setelah loop, apa pun sebab loop berhenti) — jadi TIDAK ada duplikasi
pencatatan audit di sini; modul ini murni MEMBLOKIR, bukan mencatat.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied

# Reuse WAJIB, jangan duplikasi: satu-satunya definisi "IP klien" (XFF paling
# kiri → Cloudflare `CF-Connecting-IP` bila terbukti lewat CF) sudah ada di
# `web/middleware.py` dan dipakai GeoBlock/IPAllowlist/audit IP. Berkas itu
# sedang disunting agen lain: IMPOR fungsinya, JANGAN mengubah berkasnya.
from web.middleware import resolve_client_ip

from .throttle import is_locked, register_failure, register_success


class LockoutBackend(ModelBackend):
    """Bungkus `ModelBackend` bawaan: tolak (tanpa mengecek sandi) bila
    (username, ip) sedang terkunci; jika tidak, delegasikan pengecekan
    sandi normal dan catat hasilnya (sukses → reset, gagal → tambah
    hitungan) di `loginguard.throttle`."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if username is None or password is None:
            return None

        ip = resolve_client_ip(request) if request is not None else ""

        if is_locked(username, ip):
            # Berhenti SEBELUM mengecek sandi sama sekali — lihat docstring
            # modul: authenticate() menangkap ini dan balik None, sama
            # seperti kegagalan sandi biasa (tidak membocorkan status kunci
            # maupun apakah username-nya ada).
            raise PermissionDenied

        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is not None:
            register_success(username, ip)
            return user

        register_failure(username, ip)
        return None
