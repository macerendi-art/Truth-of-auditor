from django.contrib import admin

from .models import MatchResult, MatchRun, ReconBatch, ReviewAction, ToleranceProfile


@admin.register(ToleranceProfile)
class ToleranceProfileAdmin(admin.ModelAdmin):
    list_display = (
        "name", "date_window_days", "date_direction",
        "amount_abs_tol", "amount_pct_tol", "fuzzy_threshold",
    )


@admin.register(MatchRun)
class MatchRunAdmin(admin.ModelAdmin):
    list_display = ("id", "relation", "tolerance", "date_from", "date_to", "created_at")
    list_filter = ("relation",)


@admin.register(MatchResult)
class MatchResultAdmin(admin.ModelAdmin):
    list_display = ("id", "run", "bucket", "reason_code", "score")
    list_filter = ("bucket", "run__relation")
    search_fields = ("reason_code", "reason_detail")


@admin.register(ReviewAction)
class ReviewActionAdmin(admin.ModelAdmin):
    list_display = ("id", "result", "action", "reviewer", "created_at")


@admin.register(ReconBatch)
class ReconBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "toko", "tolerance", "date_from", "date_to", "created_at")
    list_filter = ("toko",)
