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
    # perlu tinjau
    "amount_fee":       ("Selisih biaya transfer",   "warn"),
    "amount_mismatch":  ("Selisih nominal",          "warn"),
    "ticket_amount":    ("Ticket sama · selisih nominal", "warn"),
    "date_before":      ("Uang tiba H-1",            "warn"),
    "weak_name":        ("Nama belum yakin",         "warn"),
    # tertunda / info / keputusan manusia
    "late_settlement":  ("Settle terlambat",         "src"),
    "manual_override":  ("Ditandai manual",          "src"),
    # tidak cocok
    "no_bracket":       ("Tak ada di bracket",       "bad"),
    "no_panel":         ("Tak ada di panel",         "bad"),
    "no_money":         ("Belum ada uang masuk",     "bad"),
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
