web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn truth_auditor.wsgi --bind 0.0.0.0:$PORT --workers 4 --threads 8 --worker-class gthread --timeout 120
