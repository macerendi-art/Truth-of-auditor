from django.contrib import admin

from .models import LoginAttempt


@admin.register(LoginAttempt)
class LoginAttemptAdmin(admin.ModelAdmin):
    """Read-mostly: lihat siapa sedang terkunci tanpa perlu shell.

    Aksi "Buka kunci" = jalan pulih HTTP TAMBAHAN untuk admin yang masih bisa
    login — `manage.py buka_kunci_login` tetap jalan pulih UTAMA (non-HTTP,
    dipakai bila admin sendiri ikut terkunci).

    Baris ber-`username` berawalan `?` = percobaan pada username yang TIDAK
    dikenal, disimpan sebagai hash (P4) — ketikan aslinya sengaja tidak ada
    di mana pun (bisa saja itu kata sandi yang salah kolom)."""

    list_display = ("username", "ip", "fail_count", "locked_until", "updated_at")
    list_filter = ("locked_until",)
    search_fields = ("username", "ip")
    actions = ["buka_kunci_terpilih"]

    @admin.action(description="Buka kunci baris terpilih")
    def buka_kunci_terpilih(self, request, queryset):
        jumlah = queryset.update(fail_count=0, locked_until=None)
        self.message_user(request, f"{jumlah} baris dibuka kuncinya.")
