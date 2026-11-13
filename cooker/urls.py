from django.conf import settings
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .forms import ApprovalAuthenticationForm

urlpatterns = [
    # accounts
    path("accounts/login/", auth_views.LoginView.as_view(
        template_name="cooker/login.html", authentication_form=ApprovalAuthenticationForm,
        redirect_authenticated_user=True,
        extra_context={"allow_signup": settings.ALLOW_SIGNUP}), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/pending/", views.signup_pending, name="signup_pending"),

    # my cookers
    path("", views.home, name="home"),
    path("users/<int:pk>/approve/", views.user_approve, name="user_approve"),
    path("users/<int:pk>/reject/", views.user_reject, name="user_reject"),
    path("c/new/", views.cooker_create, name="cooker_create"),
    path("c/<int:pk>/", views.cooker_page, name="cooker_page"),
    path("c/<int:pk>/rename/", views.cooker_rename, name="cooker_rename"),
    path("c/<int:pk>/delete/", views.cooker_delete, name="cooker_delete"),

    # per-cooker API (same JSON as before, now scoped to one cooker)
    path("c/<int:pk>/api/state", views.api_state, name="api_state"),
    path("c/<int:pk>/api/command", views.api_command, name="api_command"),
    path("c/<int:pk>/api/reset", views.api_reset, name="api_reset"),

    # shared helpers / PWA
    path("healthz", views.healthz, name="healthz"),
    path("qr.png", views.qr_png, name="qr_png"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("icon.svg", views.icon_svg, name="icon_svg"),
    path("sw.js", views.service_worker, name="service_worker"),
]
