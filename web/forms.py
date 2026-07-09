"""Form kustom aplikasi web."""
from django.contrib.auth.forms import PasswordChangeForm


class GantiPasswordForm(PasswordChangeForm):
    """Ganti password wajib (login pertama / setelah reset admin).

    Mewarisi field password lama + baru + konfirmasi dan validator Django penuh
    (panjang minimum, password umum, semua-angka, kemiripan atribut user).
    Tambahan aturan: password baru WAJIB berbeda dari password lama (sementara),
    supaya user tidak sekadar mengetik ulang password shared.
    """

    def clean(self):
        cleaned = super().clean()
        old = cleaned.get("old_password")
        new = cleaned.get("new_password1")
        if old and new and old == new:
            self.add_error(
                "new_password1",
                "Password baru harus berbeda dari password lama.",
            )
        return cleaned
