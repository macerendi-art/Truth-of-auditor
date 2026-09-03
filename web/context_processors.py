from web.access import (
    MULTI_TOKO_LABELS,
    MULTI_TOKO_SENTINELS,
    MODE_PARTNER,
    MODE_PUSAT,
    SEMUA_TOKO,
    boleh_hapus_data,
    is_admin,
    multi_mode,
    tokos_for,
)


def toko(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {
            "all_tokos": [],
            "tokos_grouped": [],
            "active_toko": None,
            "is_admin_user": False,
            "boleh_hapus_data": False,
            "show_toko_reminder": False,
            "semua_toko": False,
            "multi_mode": None,
            "multi_mode_label": "",
            "mode_pusat": False,
            "mode_partner": False,
        }
    tokos = list(tokos_for(user))
    admin = is_admin(user)
    mode = multi_mode(request)
    semua = mode is not None
    from sources.models import Toko

    # Lingkup multi dari list yang sudah di-fetch (0 query ekstra).
    if mode == MODE_PUSAT:
        scope = [t for t in tokos if t.kepemilikan == Toko.KEPEMILIKAN_PUSAT]
    elif mode == MODE_PARTNER:
        scope = [t for t in tokos if t.kepemilikan == Toko.KEPEMILIKAN_PARTNER]
    else:
        scope = tokos
    # active_toko: di mode multi = fallback pertama di lingkup; else id sesi.
    active_id = request.session.get("active_toko_id")
    if mode is not None:
        active = scope[0] if scope else (tokos[0] if tokos else None)
    elif active_id in MULTI_TOKO_SENTINELS:
        # Sesi warisan non-admin: jangan samakan id string dengan pk.
        active = tokos[0] if tokos else None
    else:
        active = next((t for t in tokos if t.id == active_id), tokos[0] if tokos else None)

    # Picker toko: kepemilikan × panel. Label digabung (HTML optgroup tak nest).

    _KEP_LABEL = {
        Toko.KEPEMILIKAN_PUSAT: "Toko Pusat",
        Toko.KEPEMILIKAN_PARTNER: "Toko Partner",
    }
    tokos_grouped = []
    for kep_key, _ in Toko.KEPEMILIKAN_CHOICES:
        kep_lbl = _KEP_LABEL[kep_key]
        for panel_key, panel_lbl in Toko.PANEL_CHOICES:
            grup = [
                t for t in tokos
                if t.kepemilikan == kep_key and t.panel == panel_key
            ]
            if grup:
                tokos_grouped.append((f"{kep_lbl} · {panel_lbl}", grup))

    # Badge tinjau: multi → lingkup mode; tunggal → toko aktif.
    pending_review = 0
    if semua or active is not None:
        from reconciliation.models import MatchResult

        if semua:
            lingkup = {"run__batch__toko__in": scope}
        else:
            lingkup = {"run__batch__toko": active}
        pending_review = MatchResult.objects.filter(
            bucket=MatchResult.Bucket.TINJAU, **lingkup
        ).count()
    return {
        "all_tokos": tokos,
        "tokos_grouped": tokos_grouped,
        "active_toko": active,
        "is_admin_user": admin,
        "boleh_hapus_data": boleh_hapus_data(user),
        "show_toko_reminder": request.session.pop("show_toko_reminder", False),
        "pending_review_count": pending_review,
        "semua_toko": semua,
        "multi_mode": mode,
        "multi_mode_label": MULTI_TOKO_LABELS.get(mode or "", ""),
        "mode_pusat": mode == MODE_PUSAT,
        "mode_partner": mode == MODE_PARTNER,
        # Konstanta sentinel utk template option value (hindari hardcode).
        "MODE_SEMUA": SEMUA_TOKO,
        "MODE_PUSAT": MODE_PUSAT,
        "MODE_PARTNER": MODE_PARTNER,
    }


def motivation(request):
    """Satu kutipan motivasi acak untuk toast (dipakai app_base). Ringan: O(1)."""
    from web.quotes import random_quote

    return {"motivation_quote": random_quote()}
