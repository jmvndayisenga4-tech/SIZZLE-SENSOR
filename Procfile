web: python manage.py migrate --noinput && gunicorn sizzle_project.wsgi --workers 1 --threads 8 --bind 0.0.0.0:$PORT
