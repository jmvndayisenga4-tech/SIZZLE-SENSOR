from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("healthz", views.healthz, name="healthz"),
    path("api/state", views.api_state, name="api_state"),
    path("api/status", views.api_state, name="api_status"),   # compat alias
    path("api/links", views.api_links, name="api_links"),
    path("api/command", views.api_command, name="api_command"),
    path("api/reset", views.api_reset, name="api_reset"),
    path("qr.png", views.qr_png, name="qr_png"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("icon.svg", views.icon_svg, name="icon_svg"),
    path("sw.js", views.service_worker, name="service_worker"),
]
