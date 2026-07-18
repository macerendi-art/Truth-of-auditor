"""Hutang/Piutang — daftar baris FR berkategori hutang/piutang, query-time.

Pola sama `web/breakdown.py`: baca `Transaction.raw` bracket tanpa migrasi,
berlaku retroaktif untuk data lama. Read-only murni.
"""
from datetime import date
from decimal import Decimal

from django.db.models.fields.json import KeyTextTransform

from transactions.models import Transaction
from web.breakdown import _slug_kategori

NOL = Decimal("0")


def hutang_piutang(toko, dari=None, sampai=None):
    """Baris bracket berkategori Hutang/Piutang + ringkasan total.

    Filter kategori didorong ke DB (iregex pada key JSON) supaya scan tetap
    ringan di volume produksi; slug final tetap lewat `_slug_kategori` agar
    normalisasi varian ejaan satu pintu.
    """
    qs = Transaction.objects.filter(toko=toko, source_type__key="bracket")
    if dari:
        qs = qs.filter(posted_date__gte=dari)
    if sampai:
        qs = qs.filter(posted_date__lte=sampai)
    qs = (
        qs.annotate(
            fr_bank=KeyTextTransform("Bank", "raw"),
            fr_kategori=KeyTextTransform("Kategori", "raw"),
            fr_jam=KeyTextTransform("Jam", "raw"),
            fr_member=KeyTextTransform("Member", "raw"),
            fr_username=KeyTextTransform("Username", "raw"),
            fr_expense=KeyTextTransform("Expense", "raw"),
        )
        .filter(fr_kategori__iregex=r"^\s*(hutang|piutang)\s*$")
        .values_list("id", "posted_date", "money_delta", "fr_bank",
                     "fr_kategori", "fr_jam", "fr_member", "fr_username",
                     "fr_expense")
    )
    rows, total_h, total_p = [], NOL, NOL
    for pk, tanggal, delta, bank, kategori, jam, member, username, expense in qs:
        slug = _slug_kategori(kategori)
        delta = delta or NOL
        rows.append({
            "id": pk, "tanggal": tanggal, "jam": str(jam or ""),
            "account": str(bank or "").strip() or "(Tanpa Akun)",
            "kategori": slug,
            "member": str(member or "").strip() or str(username or "").strip(),
            "keterangan": str(expense or "").strip(),
            "nominal": delta,
        })
        if slug == "hutang":
            total_h += delta
        else:
            total_p += delta
    rows.sort(key=lambda r: (r["tanggal"] or date.min, r["jam"], r["id"]), reverse=True)
    return {"rows": rows, "total_hutang": total_h, "total_piutang": total_p,
            "netto": total_h + total_p, "count": len(rows)}
