import functools
import io
import json
import socket
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Cooker
from .services import new_state, open_cooker

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


def _links(request, cooker):
    """URLs for the QR code / 'open on phone' box (they open THIS cooker; the phone must log in)."""
    host = request.get_host()
    hostname, _, port = host.partition(":")
    scheme = "https" if request.is_secure() else "http"
    public_host = host
    if hostname in ("localhost", "127.0.0.1", "[::1]"):
        public_host = get_lan_ip() + (":" + port if port else "")
    path = reverse("cooker_page", args=[cooker.pk])
    return {
        "local": "%s://%s%s" % (scheme, host, path),
        "lan": "%s://%s%s" % (scheme, public_host, path),
        "qr": "/qr.png",
        "health": "/healthz",
    }


def _payload(request, handle, **extra):
    data = handle.sim.snapshot()
    data["links"] = _links(request, handle.obj)
    data["cooker"] = {"id": handle.obj.pk, "name": handle.obj.name}
    data["ok"] = True
    data.update(extra)
    return data


def api_login_required(view):
    """Like login_required, but answers JSON 401 instead of redirecting to an HTML page."""

    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"ok": False, "error": "login required"}, status=401)
        return view(request, *args, **kwargs)

    return wrapper


def _not_found():
    return JsonResponse({"ok": False, "error": "cooker not found"}, status=404)


# --------------------------------------------------------------------------
# accounts
# --------------------------------------------------------------------------
def signup(request):
    if not settings.ALLOW_SIGNUP:
        raise Http404("Sign-up is closed")
    if request.user.is_authenticated:
        return redirect("home")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.is_active = not settings.REQUIRE_APPROVAL      # waits for an admin when approval is required
        user.save()
        Cooker.objects.create(owner=user, name="Kitchen cooker", state_data=new_state())
        if settings.REQUIRE_APPROVAL:
            return redirect("signup_pending")
        login(request, user)
        return redirect("home")
    return render(request, "cooker/signup.html", {"form": form})


def signup_pending(request):
    return render(request, "cooker/pending.html")


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------
@login_required
@require_GET
def home(request):
    rows = []
    for c in Cooker.objects.filter(owner=request.user):
        with open_cooker(request.user, c.pk) as h:      # also advances + saves each cooker
            snap = h.sim.snapshot()
        rows.append({
            "cooker": c, "state": snap["state"], "temp": snap["temperature"],
            "icon": snap["food_icon"], "food": snap["food_label"], "pct": snap["energy_pct"],
            "ready": snap["ready"],
        })
    limit = settings.MAX_COOKERS_PER_USER
    pending = _pending_users() if request.user.is_staff else []
    return render(request, "cooker/cooker_list.html", {
        "rows": rows, "limit": limit, "can_add": len(rows) < limit, "pending": pending,
    })


def _pending_users():
    """Sign-ups waiting for an admin (never staff / superusers)."""
    User = get_user_model()
    return list(User.objects.filter(is_active=False, is_staff=False, is_superuser=False).order_by("-date_joined"))


@login_required
@require_POST
def user_approve(request, pk):
    if not request.user.is_staff:
        raise Http404
    u = get_object_or_404(get_user_model(), pk=pk, is_active=False, is_staff=False, is_superuser=False)
    u.is_active = True
    u.save(update_fields=["is_active"])
    messages.success(request, "%s was approved and can now sign in." % u.get_username())
    return redirect("home")


@login_required
@require_POST
def user_reject(request, pk):
    if not request.user.is_staff:
        raise Http404
    u = get_object_or_404(get_user_model(), pk=pk, is_active=False, is_staff=False, is_superuser=False)
    name = u.get_username()
    u.delete()          # also removes that user's cookers
    messages.success(request, "%s was rejected and removed." % name)
    return redirect("home")


@login_required
@require_GET
@ensure_csrf_cookie
def cooker_page(request, pk):
    cooker = get_object_or_404(Cooker, pk=pk, owner=request.user)
    return render(request, "cooker/dashboard.html", {"cooker": cooker})


@login_required
@require_POST
def cooker_create(request):
    if Cooker.objects.filter(owner=request.user).count() >= settings.MAX_COOKERS_PER_USER:
        messages.error(request, "You can have up to %d cookers." % settings.MAX_COOKERS_PER_USER)
        return redirect("home")
    name = (request.POST.get("name") or "").strip()[:60] or "My cooker"
    c = Cooker.objects.create(owner=request.user, name=name, state_data=new_state())
    return redirect("cooker_page", pk=c.pk)


@login_required
@require_POST
def cooker_rename(request, pk):
    c = get_object_or_404(Cooker, pk=pk, owner=request.user)
    name = (request.POST.get("name") or "").strip()[:60]
    if name:
        c.name = name
        c.save(update_fields=["name", "updated_at"])
    return redirect("home")


@login_required
@require_POST
def cooker_delete(request, pk):
    get_object_or_404(Cooker, pk=pk, owner=request.user).delete()
    return redirect("home")


@require_GET
@never_cache
def healthz(request):
    return JsonResponse({"ok": True, "uptime": round(time.time(), 1)})


# --------------------------------------------------------------------------
# API (one cooker per URL; only its owner may use it)
# --------------------------------------------------------------------------
@require_GET
@never_cache
@api_login_required
def api_state(request, pk):
    try:
        with open_cooker(request.user, pk) as h:
            return JsonResponse(_payload(request, h))
    except Cooker.DoesNotExist:
        return _not_found()


@require_POST
@never_cache
@api_login_required
def api_command(request, pk):
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
        with open_cooker(request.user, pk) as h:
            error = None
            try:
                ok, msg = h.sim.run_command(command.strip().lower(), data.get("value"))
                h.dirty = True
            except ValueError as exc:
                error, status = str(exc), 400
            except Exception as exc:  # never crash on a bad command
                error, status = "internal error: %s" % exc, 500
            if error is not None:
                return JsonResponse({"ok": False, "error": error}, status=status)
            return JsonResponse(_payload(request, h, ok=bool(ok), message=msg), status=200 if ok else 409)
    except Cooker.DoesNotExist:
        return _not_found()


@require_POST
@never_cache
@api_login_required
def api_reset(request, pk):
    try:
        with open_cooker(request.user, pk) as h:
            h.sim.reset_to_idle()
            h.dirty = True
            return JsonResponse(_payload(request, h, message="reset"))
    except Cooker.DoesNotExist:
        return _not_found()


# --------------------------------------------------------------------------
# QR + PWA bits
# --------------------------------------------------------------------------
@require_GET
def qr_png(request):
    url = (request.GET.get("url") or request.build_absolute_uri("/"))[:500]
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
        "  if(u.pathname.indexOf('/api/')!==-1){return;}\n"
        "  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));\n"
        "});\n"
    )
    resp = HttpResponse(js, content_type="application/javascript")
    resp["Service-Worker-Allowed"] = "/"
    return resp
