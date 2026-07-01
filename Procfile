web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn truth_auditor.wsgi --bind 0.0.0.0:$PORT --timeout 120
