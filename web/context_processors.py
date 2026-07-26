from web.access import is_admin, tokos_for


def toko(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {
            "all_tokos": [],
            "tokos_grouped": [],
            "active_toko": None,
            "is_admin_user": False,
            "show_toko_reminder": False,
        }
    tokos = list(tokos_for(user))
    active_id = request.session.get("active_toko_id")
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
    # Jumlah antrean tinjau toko aktif — badge kecil di menu Rekonsiliasi.
    pending_review = 0
    if active is not None:
        from reconciliation.models import MatchResult

        pending_review = MatchResult.objects.filter(
            run__batch__toko=active, bucket=MatchResult.Bucket.TINJAU
        ).count()
    return {
        "all_tokos": tokos,
        "tokos_grouped": tokos_grouped,
        "active_toko": active,
        "is_admin_user": is_admin(user),
        "show_toko_reminder": request.session.pop("show_toko_reminder", False),
        "pending_review_count": pending_review,
    }


def motivation(request):
    """Satu kutipan motivasi acak untuk toast (dipakai app_base). Ringan: O(1)."""
    from web.quotes import random_quote

    return {"motivation_quote": random_quote()}
