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


class CookSession(models.Model):
    """One finished cook: how much energy it used and what that costs at the REG tariff."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cook_sessions")
    cooker = models.ForeignKey(Cooker, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    cooker_name = models.CharField(max_length=60, blank=True)
    food = models.CharField(max_length=20, blank=True)
    mode = models.CharField(max_length=10, blank=True)
    quantity_kg = models.FloatField(default=0)                  # amount of food in the pot
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField()
    seconds = models.FloatField(default=0)                      # simulated cooking time
    kwh = models.FloatField(default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)   # RWF, incl. VAT if configured
    avg_rate = models.DecimalField(max_digits=8, decimal_places=2, default=0)  # RWF per kWh for this cook
    breakdown = models.JSONField(default=list, blank=True)      # [{"block", "kwh", "rate", "cost"}]
    reason = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-ended_at", "-pk"]
        indexes = [models.Index(fields=["owner", "ended_at"])]

    def __str__(self):
        return "%s %.3f kWh = %s RWF" % (self.cooker_name or "cook", self.kwh, self.cost)
