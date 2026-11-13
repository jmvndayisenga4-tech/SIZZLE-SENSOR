from django.conf import settings
from django.db import models


class Cooker(models.Model):
    """One cooker belonging to one user. ``state_data`` holds the simulator state."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cookers")
    name = models.CharField(max_length=60, default="My cooker")
    state_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return "%s (%s)" % (self.name, self.owner)
