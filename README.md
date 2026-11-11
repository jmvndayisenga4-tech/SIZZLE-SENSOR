# Sizzle Sense (Django)

Smart cooker simulator: Django backend + Bootstrap 5 dashboard. The simulation
runs on the server, so every phone/laptop opening the site controls the same cooker.

## Run locally (Windows PowerShell)

```powershell
cd sizzle_django
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000. For a phone on the same Wi-Fi, scan the QR code on
the page (it shows your LAN address). If Windows Firewall asks, allow Python.

## Deploy (Render / Railway / any VPS)

Set environment variables:

| Variable | Value |
|---|---|
| `DJANGO_DEBUG` | `0` |
| `DJANGO_SECRET_KEY` | a long random string |
| `DJANGO_ALLOWED_HOSTS` | your domain, e.g. `sizzle.onrender.com` |
| `DJANGO_CSRF_TRUSTED` | `https://sizzle.onrender.com` |

Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput`

Start command (also in `Procfile`):

```
gunicorn sizzle_project.wsgi --workers 1 --threads 8 --bind 0.0.0.0:$PORT
```

**Keep `--workers 1`.** The cooker state lives in process memory; several worker
processes would each have their own separate cooker.

> Vercel is not suitable for this version (serverless functions cannot keep a
> background simulation running). Use the single-file `index.html` for Vercel.

## Layout

```
manage.py
requirements.txt
Procfile
sizzle_project/   settings, urls, wsgi/asgi
cooker/
  simulator.py    SmartCooker + background thread (no Django imports)
  views.py        dashboard, /api/state, /api/command, /qr.png, PWA files
  urls.py
  templates/cooker/dashboard.html
  static/cooker/css/app.css
  static/cooker/js/app.js
```

## API

- `GET  /api/state` - full snapshot (state, readings, history, links)
- `POST /api/command` - `{"command": "start|stop|reset|mode|food|power|pressure|target|speed", "value": ...}`
- `POST /api/reset`, `GET /healthz`, `GET /qr.png?url=...`
