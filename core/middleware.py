"""Middleware keamanan lintas-app."""

# Semua aset di-vendor (tanpa CDN/origin eksternal) — dibuktikan ULANG saat
# Gelombang 1 (04-09-2026), bukan diasumsikan dari commit lama: grep atas
# web/templates/ dan web/static/ tidak menemukan satu pun <script src="http">,
# <link href="http">, @import, atau url(https:) di CSS/template — termasuk
# yang ditambah sejak Juli (web/static/web/js/range-select.js, toko-picker.js,
# web/static/web/vendor/gsap-3.12.5.min.js, three-*.module.min.js, htmx-*.js).
# Dua <a href="https://..."> di app_base.html (kredit UI/UX) adalah tautan
# navigasi biasa, bukan resource fetch — CSP (default-src dst.) tidak
# menggerbang navigasi <a>, jadi tidak relevan bagi kebijakan ini.
# default-src 'self' + connect-src 'self' aman: nol fetch/XHR/WebSocket ke
# origin eksternal ditemukan di template/JS statis.
#
# 'unsafe-inline' untuk script-src DAN style-src — sadar, bukan malas:
# grep yang sama menemukan <script> inline TANPA src di 16 template
# (base.html, app_base.html, dashboard.html, upload.html, reconcile.html,
# review_queue.html, kelola/users.html, dst.), atribut onchange=/onclick=
# inline di 18 template (termasuk onchange="this.form.submit()" milik
# picker Toko di app_base.html — CLAUDE.md menyebutnya eksplisit), dan
# atribut style="..."/blok <style> inline di puluhan template lain. Nonce
# per-request akan menyentuh template di hampir setiap app — di luar
# wewenang tulis gelombang ini (settings.py/middleware/tests saja), dan CSP
# yang menghalangi `this.form.submit()` di halaman transaksi finansial yang
# hidup jauh lebih mahal daripada CSP yang sedikit longgar. object-src
# 'none' + base-uri 'self' + form-action 'self' + frame-ancestors 'none'
# tetap menutup celah paling berbahaya (suntik <object>/<base>, submit ke
# origin asing, clickjacking) — 'unsafe-inline' hanya melonggarkan proteksi
# XSS-via-inline yang sudah dijaga lapisan lain (autoescape Django + CSRF),
# BUKAN membuka origin eksternal baru.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


class ContentSecurityPolicyMiddleware:
    """Header CSP di setiap respons.

    `setdefault` — tidak menimpa kalau sebuah view sudah menyetel headernya
    sendiri (tak ada yang begitu hari ini, tapi aman untuk masa depan).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", _CSP)
        return response
