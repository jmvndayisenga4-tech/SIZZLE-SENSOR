"""Staff-only admin dashboard (replaces having to open Django's /admin/ for daily work).

Everything here requires ``is_staff``. Rules that protect the system:
  * nobody can disable, delete or demote themselves,
  * only superusers can change staff / superuser accounts, or grant / remove staff rights.
"""
import functools

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from . import tariff
from .models import Cooker
from .services import new_state

User = get_user_model()
PAGE_SIZE = 20


def staff_required(view):
    @functools.wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper


def _back(request, tab="users"):
    """Return to the page the action came from (same tab, search and page)."""
    nxt = request.POST.get("next", "")
    if nxt.startswith("/manage/") and "//" not in nxt:
        return redirect(nxt)
    return redirect("%s?tab=%s" % (reverse("admin_dashboard"), tab))


def _can_manage(actor, target):
    """Staff manage normal users; only superusers manage staff / superusers. Never yourself."""
    if actor.pk == target.pk:
        return False
    if target.is_staff or target.is_superuser:
        return actor.is_superuser
    return True


def _target(request, pk):
    target = get_object_or_404(User, pk=pk)
    if not _can_manage(request.user, target):
        messages.error(request, "You cannot change %s." % target.get_username())
        return None
    return target


# --------------------------------------------------------------------------
@staff_required
@require_GET
def dashboard(request):
    tab = request.GET.get("tab", "users")
    if tab not in ("users", "cookers"):
        tab = "users"
    q = (request.GET.get("q") or "").strip()[:60]
    status = request.GET.get("status", "")

    stats = {
        "users": User.objects.count(),
        "active": User.objects.filter(is_active=True).count(),
        "pending": User.objects.filter(is_active=False, is_staff=False, is_superuser=False).count(),
        "staff": User.objects.filter(is_staff=True).count(),
        "cookers": Cooker.objects.count(),
    }

    stats["energy"] = tariff.all_month()
    ctx = {"tab": tab, "q": q, "status": status, "stats": stats,
           "limit": settings.MAX_COOKERS_PER_USER, "me": request.user}

    if tab == "users":
        qs = User.objects.annotate(n_cookers=Count("cookers"))
        if q:
            qs = qs.filter(Q(username__icontains=q) | Q(email__icontains=q))
        if status == "pending":
            qs = qs.filter(is_active=False, is_staff=False, is_superuser=False)
        elif status == "active":
            qs = qs.filter(is_active=True)
        elif status == "disabled":
            qs = qs.filter(is_active=False)
        elif status == "staff":
            qs = qs.filter(is_staff=True)
        qs = qs.order_by("is_active", "-date_joined")   # waiting accounts first
        page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
        for u in page:
            u.manageable = _can_manage(request.user, u)
            u.waiting = not u.is_active and not u.is_staff and not u.is_superuser
    else:
        qs = Cooker.objects.select_related("owner")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(owner__username__icontains=q))
        page = Paginator(qs.order_by("-updated_at"), PAGE_SIZE).get_page(request.GET.get("page"))

    ctx["page"] = page
    ctx["next"] = request.get_full_path()
    return render(request, "cooker/admin_dashboard.html", ctx)


# --------------------------------------------------------------------------
# user actions
# --------------------------------------------------------------------------
@staff_required
@require_POST
def user_approve(request, pk):
    u = _target(request, pk)
    if u:
        u.is_active = True
        u.save(update_fields=["is_active"])
        messages.success(request, "%s can now sign in." % u.get_username())
    return _back(request)


@staff_required
@require_POST
def user_disable(request, pk):
    u = _target(request, pk)
    if u:
        u.is_active = False
        u.save(update_fields=["is_active"])
        messages.success(request, "%s was disabled." % u.get_username())
    return _back(request)


@staff_required
@require_POST
def user_delete(request, pk):
    u = _target(request, pk)
    if u:
        name = u.get_username()
        u.delete()          # also removes that user's cookers
        messages.success(request, "%s and their cookers were deleted." % name)
    return _back(request)


@staff_required
@require_POST
def user_toggle_staff(request, pk):
    if not request.user.is_superuser:
        raise Http404
    u = _target(request, pk)
    if u:
        if u.is_superuser:
            messages.error(request, "Superuser rights are managed in Django admin.")
        else:
            u.is_staff = not u.is_staff
            u.save(update_fields=["is_staff"])
            messages.success(request, "%s is %s." % (u.get_username(), "now an admin" if u.is_staff else "no longer an admin"))
    return _back(request)


@staff_required
@require_POST
def user_set_password(request, pk):
    u = _target(request, pk)
    if u:
        pw = request.POST.get("password", "")
        try:
            validate_password(pw, u)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            u.set_password(pw)
            u.save(update_fields=["password"])
            messages.success(request, "Password updated for %s." % u.get_username())
    return _back(request)


# --------------------------------------------------------------------------
# cooker actions
# --------------------------------------------------------------------------
@staff_required
@require_POST
def cooker_reset(request, pk):
    c = get_object_or_404(Cooker, pk=pk)
    c.state_data = new_state()
    c.save(update_fields=["state_data", "updated_at"])
    messages.success(request, "%s was reset." % c.name)
    return _back(request, "cookers")


@staff_required
@require_POST
def cooker_delete(request, pk):
    c = get_object_or_404(Cooker, pk=pk)
    name = c.name
    c.delete()
    messages.success(request, "%s was deleted." % name)
    return _back(request, "cookers")
