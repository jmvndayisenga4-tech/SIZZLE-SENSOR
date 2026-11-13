from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

from .models import Cooker

User = get_user_model()


@admin.register(Cooker)
class CookerAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "created_at", "updated_at")
    list_filter = ("owner",)
    search_fields = ("name", "owner__username")
    readonly_fields = ("created_at", "updated_at")


admin.site.unregister(User)


@admin.register(User)
class ApprovalUserAdmin(UserAdmin):
    """Users list with the waiting accounts first, plus one-click approve / disable."""

    list_display = ("username", "email", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "is_staff", "is_superuser")
    ordering = ("is_active", "-date_joined")      # inactive (waiting) accounts on top
    actions = ["approve_accounts", "disable_accounts"]

    @admin.action(description="Approve selected accounts (they can sign in)")
    def approve_accounts(self, request, queryset):
        n = queryset.update(is_active=True)
        self.message_user(request, "%d account(s) approved." % n)

    @admin.action(description="Disable selected accounts (they cannot sign in)")
    def disable_accounts(self, request, queryset):
        n = queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, "%d account(s) disabled." % n)
