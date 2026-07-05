from web.access import is_admin, tokos_for


def toko(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {
            "all_tokos": [],
            "active_toko": None,
            "is_admin_user": False,
            "show_toko_reminder": False,
        }
    tokos = list(tokos_for(user))
    active_id = request.session.get("active_toko_id")
    active = next((t for t in tokos if t.id == active_id), tokos[0] if tokos else None)
    # Jumlah antrean tinjau toko aktif — badge kecil di menu Rekonsiliasi.
    pending_review = 0
    if active is not None:
        from reconciliation.models import MatchResult

        pending_review = MatchResult.objects.filter(
            run__batch__toko=active, bucket=MatchResult.Bucket.TINJAU
        ).count()
    return {
        "all_tokos": tokos,
        "active_toko": active,
        "is_admin_user": is_admin(user),
        "show_toko_reminder": request.session.pop("show_toko_reminder", False),
        "pending_review_count": pending_review,
    }
