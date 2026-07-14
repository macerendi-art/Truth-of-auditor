from django import template

register = template.Library()


@register.filter
def raw_get(d, key):
    """Ambil nilai dict raw dgn key ber-spasi (kolom Excel asli)."""
    return (d or {}).get(key, "")


# Peta kode alasan mesin → (label rapih Bahasa, nada warna badge).
# Nada memakai kelas design-system yang sudah ada: ok / warn / bad / src(info) / muted.
REASON_LABELS = {
    # cocok kuat
    "ticket+amount":    ("Ticket & nominal sama",    "ok"),
    "ticket":           ("Ticket sama",              "ok"),
    "amount+date+name": ("Nominal · tanggal · nama", "ok"),
    "alias_history":    ("Rekening langganan (riwayat)", "ok"),
    # perlu tinjau
    "amount_fee":       ("Selisih biaya transfer",   "warn"),
    "amount_mismatch":  ("Selisih nominal",          "warn"),
    "ticket_amount":    ("Ticket sama · selisih nominal", "warn"),
    "date_before":      ("Uang tiba H-1",            "warn"),
    "name_partial":     ("Nama mirip",               "warn"),
    "weak_name":        ("Nama belum yakin",         "warn"),  # data lama (pra-anchor)
    "pulsa_manual":     ("DP Pulsa — cek konversi manual", "warn"),
    # tertunda / info / keputusan manusia
    "late_settlement":  ("Settle terlambat",         "src"),
    "manual_override":  ("Ditandai manual",          "src"),
    # tidak cocok
    "no_bracket":       ("Tak ada di bracket",       "bad"),
    "no_panel":         ("Tak ada di panel",         "bad"),
    "no_money":         ("Belum ada uang masuk",     "bad"),
    "gateway_unpaid":   ("QR belum settle",          "bad"),
}


@register.filter
def reason_label(code):
    """Kode alasan mesin → frasa rapih untuk ditampilkan. Fallback: kode apa adanya."""
    if not code:
        return "—"
    return REASON_LABELS.get(code, (code, "muted"))[0]


@register.filter
def reason_tone(code):
    """Kode alasan mesin → kelas nada badge (ok/warn/bad/src/muted)."""
    if not code:
        return "muted"
    return REASON_LABELS.get(code, (code, "muted"))[1]


# Peta kode aksi AuditLog → (label rapih, nada badge). Kode lama tetap di sini
# supaya baris historis tetap terbaca.
AKSI_LABELS = {
    # alur rekonsiliasi
    "reconcile":           ("Jalankan rekonsiliasi", "ok"),
    "review":              ("Review hasil",          "src"),
    "review_massal":       ("Review massal",         "src"),
    "export_batch":        ("Export batch",          "src"),
    "hapus_batch":         ("Hapus batch",           "bad"),
    "hapus_upload":        ("Hapus upload",          "bad"),
    "hapus_upload_massal": ("Hapus upload massal",   "bad"),
    # kelola pengguna
    "buat_user":           ("Buat user",             "ok"),
    "ubah_user":           ("Ubah user",             "src"),
    "reset_password":      ("Reset password",        "warn"),
    "aktifkan_user":       ("Aktifkan user",         "ok"),
    "nonaktifkan_user":    ("Nonaktifkan user",      "warn"),
    "hapus_user":          ("Hapus user",            "bad"),
    "ganti_password":      ("Ganti password sendiri", "src"),
    # kelola toko
    "buat_toko":           ("Buat toko",             "ok"),
    "ubah_nama_toko":      ("Ubah nama toko",        "src"),
    "aktifkan_toko":       ("Aktifkan toko",         "ok"),
    "nonaktifkan_toko":    ("Nonaktifkan toko",      "warn"),
    "hapus_toko":          ("Hapus toko",            "bad"),
}


@register.filter
def aksi_label(code):
    """Kode aksi AuditLog → frasa rapih. Fallback: kode apa adanya."""
    return AKSI_LABELS.get(code, (code, "muted"))[0] if code else "—"


@register.filter
def aksi_tone(code):
    """Kode aksi AuditLog → kelas nada badge (ok/warn/bad/src/muted)."""
    return AKSI_LABELS.get(code, (code, "muted"))[1] if code else "muted"


@register.inclusion_tag("web/_pager.html", takes_context=True)
def pager(context, page, on_each_side=5, on_ends=1):
    """Pager bernomor jendela-geser (elided) yang mempertahankan semua query kecuali `page`."""
    request = context.get("request")
    try:
        nums = list(
            page.paginator.get_elided_page_range(
                page.number, on_each_side=on_each_side, on_ends=on_ends
            )
        )
    except Exception:
        nums = []
    if request is not None:
        params = request.GET.copy()
        params.pop("page", None)
        base_qs = params.urlencode()
    else:
        base_qs = ""
    return {
        "page": page,
        "nums": nums,
        "base_qs": base_qs,
        "ellipsis": page.paginator.ELLIPSIS,
    }
