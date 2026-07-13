web: python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn truth_auditor.wsgi --bind 0.0.0.0:$PORT --workers 2 --threads 4 --worker-class gthread --timeout 120
