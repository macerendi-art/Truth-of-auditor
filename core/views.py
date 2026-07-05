from django.db import connections
from django.http import JsonResponse


def healthz(request):
    """Healthcheck deploy: proses hidup + DB terjangkau. Tanpa auth — dipakai
    Railway untuk memutuskan rollout; gagal = deploy baru tidak menerima traffic."""
    try:
        with connections["default"].cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        return JsonResponse({"status": "db-error"}, status=503)
    return JsonResponse({"status": "ok"})
