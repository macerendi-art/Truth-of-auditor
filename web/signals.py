"""Signal receiver: tandai sesi untuk tampilkan pop-up pengingat toko setelah login."""
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def tandai_pengingat_toko(sender, request, user, **kwargs):
    request.session["show_toko_reminder"] = True
