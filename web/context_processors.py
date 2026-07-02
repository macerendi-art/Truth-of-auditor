from sources.models import Toko


def toko(request):
    tokos = list(Toko.objects.filter(is_active=True).order_by("name"))
    active_id = request.session.get("active_toko_id")
    active = next((t for t in tokos if t.id == active_id), tokos[0] if tokos else None)
    return {"all_tokos": tokos, "active_toko": active}
