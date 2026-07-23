"""Middleware gerbang: paksa ganti password + kunci wilayah (geo-block)."""
import ipaddress

from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse


class ForcePasswordChangeMiddleware:
    """Selama flag menyala, semua halaman selain allowlist dialihkan ke
    halaman ganti password — tidak bisa di-bypass dengan mengetik URL langsung.

    Allowlist: halaman ganti password itu sendiri (hindari loop), logout
    (user harus bisa keluar), dan aset statis/media (agar CSS/font halaman termuat).
    Catatan: meski `STATIC_URL`/`MEDIA_URL` ditulis tanpa garis miring depan
    di settings.py, Django menormalisasinya jadi berawalan "/" saat runtime
    (sama seperti `request.path`) — jadi keduanya dibandingkan apa adanya,
    tanpa `lstrip("/")`.
    Harus dipasang SETELAH AuthenticationMiddleware (butuh request.user).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and getattr(user, "must_change_password", False):
            path = request.path
            allowed = (reverse("ganti_password"), reverse("logout"))
            asset_prefixes = tuple(p for p in (settings.STATIC_URL, settings.MEDIA_URL) if p)
            if path not in allowed and not path.startswith(asset_prefixes):
                return redirect("ganti_password")
        return self.get_response(request)


# --- Geo-block (kunci wilayah) ---------------------------------------------
# Fitur K4: hanya negara di GEO_BLOCK_COUNTRIES yang boleh masuk; sisanya 403.
# DEFAULT MATI (settings.GEO_BLOCK_ENABLED=False) → middleware no-op total.

_geoip_instance = None


def _lookup_country(ip):
    """Kembalikan kode negara 2-huruf (mis. 'KH','ID') untuk IP.

    Import GeoIP LAZY di dalam fungsi supaya app tetap boot bila lib belum
    terpasang; melempar (ImportError / exception apa pun) bila lookup mustahil,
    dan pemanggil (middleware) menangkapnya sebagai FAIL-OPEN. Instance
    GeoIP2Fast di-cache di modul (dibuat sekali).
    """
    global _geoip_instance
    from geoip2fast import GeoIP2Fast  # lazy; ImportError bila lib absen

    if _geoip_instance is None:
        _geoip_instance = GeoIP2Fast()
    result = _geoip_instance.lookup(ip)
    return (getattr(result, "country_code", "") or "").upper()


def _client_ip(request):
    """Ambil IP klien asli di belakang proxy Railway (Envoy).

    Prioritas: X-Envoy-External-Address (dihitung Envoy) → hop PALING KANAN
    X-Forwarded-For (ditambah infrastruktur, sulit dipalsukan; JANGAN kiri —
    klien bisa prepend IP palsu) → X-Real-IP → REMOTE_ADDR.
    """
    meta = request.META
    envoy = meta.get("HTTP_X_ENVOY_EXTERNAL_ADDRESS")
    if envoy and envoy.strip():
        return envoy.strip()
    xff = meta.get("HTTP_X_FORWARDED_FOR")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]  # rightmost = hop tepercaya
    real = meta.get("HTTP_X_REAL_IP")
    if real and real.strip():
        return real.strip()
    return (meta.get("REMOTE_ADDR") or "").strip()


def _ip_is_internal(ip):
    """IP privat/loopback/link-local → selalu lolos (health-check + dev)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local


def _ip_in_allowlist(ip, allowlist):
    """Break-glass: IP klien cocok salah satu entri IP/CIDR di allowlist."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


def _via_cloudflare(peer_ip):
    """True bila PEER (yang membuka koneksi ke origin) adalah edge Cloudflare.

    Ini gerbang anti-spoof: header `CF-*` baru boleh dipercaya kalau koneksinya
    memang datang dari rentang IP resmi Cloudflare. Penyerang yang menembak
    origin Railway langsung TIDAK bisa memalsukan ini — header boleh dikarang,
    alamat peer tidak.
    """
    return _ip_in_allowlist(peer_ip, getattr(settings, "GEO_BLOCK_CF_CIDRS", []))


def _real_client_ip(request, via_cf):
    """IP pengguna sebenarnya. Di belakang Cloudflare, peer = edge CF, jadi IP
    asli ada di `CF-Connecting-IP` — allowlist tim HARUS diuji terhadap ini,
    bukan terhadap IP edge."""
    if via_cf:
        cf_ip = (request.META.get("HTTP_CF_CONNECTING_IP") or "").strip()
        if cf_ip:
            return cf_ip
    return _client_ip(request)


class GeoBlockMiddleware:
    """Kunci wilayah: saat menyala, hanya IP dari negara di
    GEO_BLOCK_COUNTRIES yang boleh mengakses app; sisanya dapat 403 halaman
    "Trust No One".

    Aman by design — DEFAULT MATI: bila GEO_BLOCK_ENABLED False (default),
    __call__ langsung meneruskan request (no-op). Deploy tidak mengubah akses
    apa pun sampai controller menyalakan env. FAIL-OPEN hanya bila lookup
    GeoIP mustahil (lib/DB tak termuat) — jangan pernah brick app live.

    Dipasang SETELAH AuthenticationMiddleware supaya request.user tersedia
    untuk GEO_BLOCK_BYPASS_STAFF (break-glass staff saat lockout).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._blokir(request):
            html = render_to_string("web/geo_block.html", request=request)
            return HttpResponseForbidden(html)
        return self.get_response(request)

    def _blokir(self, request):
        # (0) DEFAULT MATI → no-op total.
        if not getattr(settings, "GEO_BLOCK_ENABLED", False):
            return False

        # (1) aset statis/media exempt (halaman blokir pun tak boleh 500 karena aset).
        asset_prefixes = tuple(p for p in (settings.STATIC_URL, settings.MEDIA_URL) if p)
        if asset_prefixes and request.path.startswith(asset_prefixes):
            return False

        # (2) peer = yang membuka koneksi ke origin; tanpa IP jangan brick → lolos.
        peer = _client_ip(request)
        if not peer:
            return False

        # (3) IP privat/loopback/link-local → lolos (health-check internal + dev).
        if _ip_is_internal(peer):
            return False

        # (4) apakah request datang lewat Cloudflare? (menentukan boleh/tidaknya
        #     header CF dipercaya, dan mana IP pengguna yang sebenarnya)
        via_cf = _via_cloudflare(peer)
        ip = _real_client_ip(request, via_cf)

        # (5) allowlist break-glass — diuji pada IP pengguna asli.
        if _ip_in_allowlist(ip, getattr(settings, "GEO_BLOCK_ALLOWLIST", [])):
            return False

        # (6) bypass staff terautentikasi.
        if getattr(settings, "GEO_BLOCK_BYPASS_STAFF", True):
            user = getattr(request, "user", None)
            if user is not None and user.is_authenticated and user.is_staff:
                return False

        # (7) ORIGIN-LOCK: bila diwajibkan, request yang tidak lewat Cloudflare
        #     ditolak. Inilah penutup celah "akses origin Railway langsung"
        #     yang kalau tidak ditutup membuat geo-block di edge sia-sia.
        if getattr(settings, "GEO_BLOCK_REQUIRE_CF", False) and not via_cf:
            return True

        # (8) negara: utamakan header Cloudflare (akurat, data IPinfo) HANYA bila
        #     terbukti lewat CF; selain itu jatuh ke geoip2fast. Lookup mustahil
        #     → FAIL-OPEN (jangan pernah brick app live).
        country = ""
        if via_cf and getattr(settings, "GEO_BLOCK_TRUST_CF", True):
            country = (request.META.get("HTTP_CF_IPCOUNTRY") or "").strip().upper()
            # 'XX'/'T1' = tak diketahui/Tor menurut Cloudflare → jangan dipakai.
            if country in ("XX", "T1", ""):
                country = ""
        if not country:
            try:
                country = _lookup_country(ip)
            except Exception:
                return False

        # (9) negara dalam daftar yang diizinkan → lolos; else BLOK.
        allowed = getattr(settings, "GEO_BLOCK_COUNTRIES", {"ID"})
        return country not in allowed
