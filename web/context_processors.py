from web.access import SEMUA_TOKO, is_admin, tokos_for


def toko(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {
            "all_tokos": [],
            "tokos_grouped": [],
            "active_toko": None,
            "is_admin_user": False,
            "show_toko_reminder": False,
            "semua_toko": False,
        }
    tokos = list(tokos_for(user))
    admin = is_admin(user)
    active_id = request.session.get("active_toko_id")
    # Mode "Semua Toko": sentinel string, khusus admin. `active_toko` TETAP toko
    # nyata (fallback pertama) — puluhan template lama memakainya tanpa guard,
    # dan halaman single-toko memang menampilkan toko itu.
    semua = admin and active_id == SEMUA_TOKO
    active = next((t for t in tokos if t.id == active_id), tokos[0] if tokos else None)
    # Picker toko berkelompok per panel client (Nexus/Vigor/TM Gaming) — dibangun
    # dari `tokos` yang SUDAH difetch di atas (list, bukan queryset baru), jadi
    # nol query tambahan. Hanya grup berisi yang dikirim ke template.
    from sources.models import Toko

    tokos_grouped = [
        (label, [t for t in tokos if t.panel == key])
        for key, label in Toko.PANEL_CHOICES
    ]
    tokos_grouped = [(label, grup) for label, grup in tokos_grouped if grup]
    # Jumlah antrean tinjau — badge kecil di menu Rekonsiliasi. Mode Semua Toko
    # menghitung lintas toko lewat `toko__in` (tetap SATU query agregat, bukan
    # satu query per toko).
    pending_review = 0
    if semua or active is not None:
        from reconciliation.models import MatchResult

        lingkup = {"run__batch__toko__in": tokos} if semua else {"run__batch__toko": active}
        pending_review = MatchResult.objects.filter(
            bucket=MatchResult.Bucket.TINJAU, **lingkup
        ).count()
    return {
        "all_tokos": tokos,
        "tokos_grouped": tokos_grouped,
        "active_toko": active,
        "is_admin_user": admin,
        "show_toko_reminder": request.session.pop("show_toko_reminder", False),
        "pending_review_count": pending_review,
        "semua_toko": semua,
    }


def motivation(request):
    """Satu kutipan motivasi acak untuk toast (dipakai app_base). Ringan: O(1)."""
    from web.quotes import random_quote

    return {"motivation_quote": random_quote()}
