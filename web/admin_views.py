"""Panel admin: kelola pengguna & toko, hapus data. Semua view digate admin_required."""
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from sources.models import Toko
from web.access import admin_required


@admin_required
def kelola_toko(request):
    if request.method == "POST" and request.POST.get("action") == "create":
        kode = request.POST.get("kode", "").strip()
        if not kode or not kode.isalnum():
            messages.error(request, "Kode toko wajib huruf/angka tanpa spasi.")
        elif Toko.objects.filter(key=kode.lower()).exists():
            messages.error(request, f"Toko {kode.upper()} sudah ada.")
        else:
            Toko.objects.create(key=kode.lower(), name=kode.upper())
            messages.success(request, f"Toko {kode.upper()} ditambahkan.")
        return redirect("kelola_toko")
    if request.method == "POST" and request.POST.get("action") == "toggle":
        t = get_object_or_404(Toko, pk=request.POST.get("toko_id"))
        t.is_active = not t.is_active
        t.save(update_fields=["is_active"])
        messages.success(request, f"Toko {t.name} {'diaktifkan' if t.is_active else 'dinonaktifkan'}.")
        return redirect("kelola_toko")
    tokos = Toko.objects.annotate(
        n_tx=Count("transaction", distinct=True),
        n_up=Count("upload", distinct=True),
    ).order_by("name")
    return render(request, "web/kelola/toko.html", {"tokos": tokos})
