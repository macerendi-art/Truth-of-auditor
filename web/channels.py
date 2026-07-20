"""Kartu dashboard "Metode Pembayaran" — agregasi murni, tanpa render.

Permintaan klien: breakdown berapa trx & nilai deposit per Bank/QRIS/E-wallet
dan withdraw per Bank/Nexuspay/QRIS — "buat QR pakai acuan Bank Title bank
kita, diambil dari panel".

Sumber data = queryset `_pr` panel_sum di view dashboard (baris panel yang
dikonsumsi batch terakhir, tanpa duplikat), dipakai apa adanya supaya total
kartu PASTI klop dengan strip Ringkasan Panel.

Klasifikasi memakai kolom ``Transaction.bank_title`` — segmen pertama raw
"Bank Title" (format ``KODE|NAMA|NOREK``), sudah di-upper saat ingest dan
terverifikasi identik 100% dengan nilai raw di data produksi — jadi cukup
satu query agregat kecil (belasan baris), tanpa membaca JSON per baris.
Urutan cek substring (case-insensitive):

- DP : "QR" → QRIS · substring e-wallet → E-wallet · ada isi → Bank ·
       kosong → Lainnya. Contoh klien: "NXPAY DEPOSIT QR" = QRIS.
- WD : "NEXUSPAY"/"NXPAY" → Nexuspay (WAJIB paling awal — kodenya bisa
       memuat "QR"/"BANK"; contoh klien: akun "QRIS NEXUSPAY" = Nexuspay) ·
       "QR" → QRIS · ada isi → Bank · kosong → Lainnya.
"""
from django.db.models import Count, Sum

# Substring e-wallet di Bank Title. Belum semuanya pernah muncul di data —
# tetap dipasang untuk brand lain / masa depan.
_EWALLET = ("DANA", "OVO", "GOPAY", "SHOPEEPAY", "LINKAJA", "SAKUKU")

# Urutan kanonik baris per grup — dipertahankan saat nilai seri (mis. semua 0).
_URUTAN = {
    "dp": ("QRIS", "E-wallet", "Bank", "Lainnya"),
    "wd": ("Nexuspay", "QRIS", "Bank", "Lainnya"),
}


def kelas_metode(jenis, bank_title):
    """Metode pembayaran untuk satu kode Bank Title panel (jenis depo/wd)."""
    kode = (bank_title or "").strip().upper()
    if not kode:
        return "Lainnya"
    if jenis == "wd":
        if "NXPAY" in kode or "NEXUSPAY" in kode:
            return "Nexuspay"
        return "QRIS" if "QR" in kode else "Bank"
    # depo — QR menang duluan (klien menandai huruf QR-nya).
    if "QR" in kode:
        return "QRIS"
    # "DANAMON" (bank) memuat substring "DANA" — jangan nyasar ke E-wallet.
    if "DANAMON" not in kode and any(w in kode for w in _EWALLET):
        return "E-wallet"
    return "Bank"


def breakdown_metode(panel_qs):
    """Breakdown metode per grup dp/wd dari queryset panel dashboard.

    ``panel_qs`` = queryset yang SAMA dengan panel_sum di view dashboard
    (sudah ter-filter batch/sumber panel/duplikat). Hasil: ``{"dp": [...],
    "wd": [...]}``; baris = ``{label, n, v, pct}`` urut nilai terbesar;
    ``pct`` = pangsa nilai dalam grup; "Lainnya" hanya ikut bila n > 0.
    """
    per = {"depo": {}, "wd": {}}
    agg = (
        panel_qs.filter(jenis__in=["depo", "wd"])
        .values("jenis", "bank_title")
        .annotate(n=Count("id"), v=Sum("amount"))
    )
    for r in agg:  # hasil agregat cuma belasan baris — klasifikasi di Python
        slot = per[r["jenis"]].setdefault(
            kelas_metode(r["jenis"], r["bank_title"]), {"n": 0, "v": 0.0})
        slot["n"] += r["n"]
        slot["v"] += float(r["v"] or 0)

    hasil = {}
    for grup, jenis in (("dp", "depo"), ("wd", "wd")):
        isi = per[jenis]
        total_v = sum(s["v"] for s in isi.values())
        rows = []
        for label in _URUTAN[grup]:
            s = isi.get(label, {"n": 0, "v": 0.0})
            if label == "Lainnya" and s["n"] == 0:
                continue  # "Lainnya" hanya muncul bila benar-benar ada isinya
            rows.append({
                "label": label, "n": s["n"], "v": s["v"],
                "pct": round(100 * s["v"] / total_v, 1) if total_v else 0.0,
            })
        rows.sort(key=lambda b: b["v"], reverse=True)  # stabil: seri tetap kanonik
        hasil[grup] = rows
    return hasil
