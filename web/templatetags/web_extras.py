from django import template

register = template.Library()


@register.filter
def raw_get(d, key):
    """Ambil nilai dict raw dgn key ber-spasi (kolom Excel asli)."""
    return (d or {}).get(key, "")


_REASON_LABELS = {
    "gateway_ticket": "Cocok · TX ID",
    "gateway_reference": "Cocok · Ref QR",
    "ticket+amount": "Cocok · Tiket",
    "amount+date+name": "Cocok · nama+nominal",
    "gateway_amount_mismatch": "TX ID cocok, nominal beda",
    "gateway_key_ambiguous": "Kunci QR ganda",
    "gateway_unpaid": "QR belum settle — uang belum masuk",
    "gateway_no_panel": "Uang QR tanpa deposit Panel",
    "pulsa_manual": "DP Pulsa — cek konversi manual",
    "weak_name": "Nama mirip sebagian — cek manual",
    "alias_history": "Cocok · rekening dikenal (riwayat)",
    "ambiguous_multi": "Kandidat ganda (identitas beda)",
    "amount_mismatch": "Nominal beda",
    "no_money": "Tak ada padanan uang",
    "no_bracket": "Tiket tak ada di Bracket",
    "no_panel": "Tiket tak ada di Panel",
}


@register.filter
def reason_label(code):
    """Label ramah untuk reason_code (fallback: kode apa adanya)."""
    return _REASON_LABELS.get(code, code)


@register.filter
def sparkline_points(values, width=120):
    """List angka → string points polyline SVG (viewBox 0 0 {width} 32)."""
    values = list(values or [])
    if not values:
        return ""
    h, pad = 32, 2
    vmax = max(values) or 1
    step = width / max(len(values) - 1, 1)
    return " ".join(
        f"{i * step:.1f},{h - pad - (v / vmax) * (h - 2 * pad):.1f}"
        for i, v in enumerate(values)
    )
