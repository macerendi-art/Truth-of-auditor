from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at", "source_type", "jenis", "amount",
        "username", "ticket_no", "reference", "is_duplicate",
    )
    list_filter = ("source_type", "jenis", "is_duplicate", "account")
    search_fields = ("username", "ticket_no", "reference", "counterparty", "description")
    date_hierarchy = "occurred_at"
    list_select_related = ("source_type", "account")
