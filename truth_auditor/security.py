"""Resolusi konfigurasi keamanan/observability yang harus fail-safe.

Dipisah dari settings.py supaya bisa diuji unit (mock `sentry_sdk.init`)
tanpa reload modul settings — settings.py dieksekusi sekali saat boot dan
sebagian besar isinya tak bisa "diimpor ulang" dengan aman di tengah proses
test yang sama.
"""


def configure_sentry(env, debug):
    """Inisialisasi Sentry HANYA bila env `SENTRY_DSN` ada.

    Tanpa `SENTRY_DSN` (deploy apa pun yang belum mengaktifkan pelacak error):
    fungsi ini langsung `return False` TANPA mengimpor `sentry_sdk` sama
    sekali — nol perubahan perilaku, dan paket boleh belum terpasang tanpa
    membuat boot gagal. Dipanggil dari `settings.py` setelah `DEBUG`
    diketahui.
    """
    dsn = env.get("SENTRY_DSN", "")
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    try:
        traces_sample_rate = float(env.get("SENTRY_TRACES_SAMPLE_RATE", "0"))
    except ValueError:
        traces_sample_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        integrations=[DjangoIntegration()],
        environment=env.get("SENTRY_ENVIRONMENT", "production" if not debug else "development"),
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,  # data finansial — jangan kirim user PII ke SaaS pihak ketiga
        # M7 (04-09-2026): `send_default_pii=False` TIDAK menahan badan
        # request — bawaan `max_request_body_size="medium"` tetap mengirim
        # body POST (form upload, review, koreksi FR) ke Sentry saat error.
        # "never" = badan request tak pernah ikut, apa pun ukurannya.
        max_request_body_size="never",
    )
    return True
