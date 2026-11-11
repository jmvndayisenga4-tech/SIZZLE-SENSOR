import io
import json
import socket
import time

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .simulator import get_cooker

try:
    import qrcode

    HAS_QR = True
except Exception:  # optional dependency
    qrcode = None
    HAS_QR = False


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


def _links(request):
    """URLs for the QR code / 'open on phone' box.

    On localhost we advertise the LAN IP so a phone on the same Wi-Fi can reach
    it; on a real domain (Render, VPS, Tailscale...) we use that domain as-is.
    """
    host = request.get_host()
    hostname, _, port = host.partition(":")
    scheme = "https" if request.is_secure() else "http"
    public_host = host
    if hostname in ("localhost", "127.0.0.1", "[::1]"):
        public_host = get_lan_ip() + (":" + port if port else "")
    return {
        "local": "%s://%s" % (scheme, host),
        "lan": "%s://%s" % (scheme, public_host),
        "qr": "/qr.png",
        "health": "/healthz",
    }


def _payload(request, **extra):
    data = get_cooker().snapshot()
    data["links"] = _links(request)
    data["ok"] = True
    data.update(extra)
    return data


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@require_GET
def index(request):
    return render(request, "cooker/dashboard.html")


@require_GET
@never_cache
def healthz(request):
    return JsonResponse({"ok": True, "state": get_cooker().state, "uptime": round(time.time(), 1)})


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@require_GET
@never_cache
def api_state(request):
    return JsonResponse(_payload(request))


@require_GET
@never_cache
def api_links(request):
    return JsonResponse({"ok": True, "links": _links(request)})


@csrf_exempt
@require_POST
@never_cache
def api_command(request):
    """Body: {"command": "start|stop|reset|mode|food|power|pressure|target|speed", "value": ...}"""
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        data = None
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "body must be a JSON object"}, status=400)

    command = data.get("command")
    if not isinstance(command, str) or not command.strip():
        return JsonResponse({"ok": False, "error": "missing 'command'"}, status=400)

    try:
        ok, msg = get_cooker().run_command(command.strip().lower(), data.get("value"))
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:  # never crash on a bad command
        return JsonResponse({"ok": False, "error": "internal error: %s" % exc}, status=500)

    return JsonResponse(_payload(request, ok=bool(ok), message=msg), status=200 if ok else 409)


@csrf_exempt
@require_POST
@never_cache
def api_reset(request):
    get_cooker().reset_to_idle()
    return JsonResponse(_payload(request, message="reset"))


# --------------------------------------------------------------------------
# QR + PWA bits
# --------------------------------------------------------------------------
@require_GET
def qr_png(request):
    url = request.GET.get("url") or _links(request)["lan"]
    if not HAS_QR:
        return JsonResponse(
            {"ok": False, "error": "qrcode not installed", "hint": "pip install qrcode[pil]", "url": url},
            status=503,
        )
    try:
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
    except Exception as exc:
        return JsonResponse({"ok": False, "error": "qr failed: %s" % exc}, status=500)
    return HttpResponse(buf.getvalue(), content_type="image/png")


@require_GET
def manifest(request):
    data = {
        "name": "Sizzle Sense",
        "short_name": "Sizzle",
        "description": "Smart cooker simulator dashboard",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0f0f1a",
        "theme_color": "#e94560",
        "orientation": "portrait-primary",
        "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"}],
    }
    return HttpResponse(json.dumps(data), content_type="application/manifest+json")


@require_GET
def icon_svg(request):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">'
        '<rect width="192" height="192" rx="40" fill="#0f0f1a"/>'
        '<circle cx="96" cy="96" r="58" fill="none" stroke="#e94560" stroke-width="10"/>'
        '<path d="M96 52c14 18 22 28 22 40a22 22 0 1 1-44 0c0-12 8-22 22-40z" fill="#e94560"/>'
        "</svg>"
    )
    return HttpResponse(svg, content_type="image/svg+xml")


@require_GET
def service_worker(request):
    js = (
        "self.addEventListener('install',e=>{self.skipWaiting();});\n"
        "self.addEventListener('activate',e=>{e.waitUntil(self.clients.claim());});\n"
        "self.addEventListener('fetch',e=>{\n"
        "  const u=new URL(e.request.url);\n"
        "  if(u.pathname.startsWith('/api/')){return;}\n"
        "  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));\n"
        "});\n"
    )
    resp = HttpResponse(js, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    return resp
