"""Electricity cost at the REG (Rwanda Energy Group) residential tariff.

The tariff is a set of monthly blocks (default, RURA notice effective 1 Oct 2025, VAT exclusive):

    first 20 kWh        89 RWF/kWh
    next 30 kWh (to 50) 310 RWF/kWh
    above 50 kWh        369 RWF/kWh

Blocks restart each calendar month (Africa/Kigali) for every account, and are shared by all of
an account's cookers. A cook is priced for the kWh slice it adds on top of what the account had
already used that month, so a cook that crosses a block boundary is split across both rates.

Money is returned as plain floats rounded to 2 decimals (RWF); the database keeps Decimals.
"""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from .models import CookSession


def blocks():
    return list(settings.REG_TARIFF_BLOCKS)       # [(upper_kwh or None, rate), ...]


def _vat_factor():
    return 1.0 + float(settings.REG_VAT_PERCENT) / 100.0


def price(used_kwh, kwh):
    """Cost of ``kwh`` consumed after ``used_kwh`` were already used this month.

    Returns ``(cost, parts)``; ``parts`` is one dict per block touched. VAT (if any) is included.
    """
    pos, left = max(0.0, float(used_kwh)), max(0.0, float(kwh))
    total, parts = 0.0, []
    for i, (upto, rate) in enumerate(blocks()):
        if left <= 1e-12:
            break
        top = float("inf") if upto is None else float(upto)
        if pos >= top:
            continue
        take = min(left, top - pos)
        cost = take * rate * _vat_factor()
        parts.append({"block": i + 1, "kwh": round(take, 4), "rate": rate, "cost": round(cost, 2)})
        total += cost
        pos += take
        left -= take
    return round(total, 2), parts


def block_at(used_kwh):
    """The block the next kWh falls into: ``(index, rate, kwh_left_in_block or None)``."""
    used = max(0.0, float(used_kwh))
    bl = blocks()
    for i, (upto, rate) in enumerate(bl):
        if upto is None or used < upto - 1e-12:
            return i + 1, rate, (None if upto is None else round(upto - used, 3))
    return len(bl), bl[-1][1], None


def block_label(index):
    """'0-20 kWh', '20-50 kWh', 'above 50 kWh' for block ``index`` (1-based)."""
    bl, lo = blocks(), 0.0
    for i, (upto, _rate) in enumerate(bl):
        if i + 1 == index:
            if upto is None:
                return "above %g kWh" % lo
            return "%g-%g kWh" % (lo, upto)
        lo = upto if upto is not None else lo
    return ""


def _tz():
    try:
        return ZoneInfo(settings.BILLING_TIME_ZONE)
    except Exception:  # tzdata missing: fall back to UTC rather than crash billing
        return dt_timezone.utc


def month_window(when=None):
    """(start, next_start) of the billing month containing ``when`` (default: now), as aware datetimes."""
    tz = _tz()
    when = (when or timezone.now()).astimezone(tz)
    start = when.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, nxt


def month_used(owner_id, when=None):
    """kWh the account has already used (in finished cooks) in the billing month of ``when``."""
    start, nxt = month_window(when)
    total = CookSession.objects.filter(owner_id=owner_id, ended_at__gte=start, ended_at__lt=nxt) \
        .aggregate(t=Sum("kwh"))["t"]
    return float(total or 0.0)


def record_cook(cooker, d):
    """Price one finished cook ``d`` (see SmartCooker._end_cook) and store it as a CookSession."""
    ended = datetime.fromtimestamp(d.get("ended_at") or timezone.now().timestamp(), tz=dt_timezone.utc)
    started = d.get("started_at")
    cost, parts = price(month_used(cooker.owner_id, ended), d["kwh"])
    kwh = float(d["kwh"])
    return CookSession.objects.create(
        owner_id=cooker.owner_id, cooker=cooker, cooker_name=cooker.name, food=d.get("food", ""),
        mode=d.get("mode", ""), ended_at=ended, seconds=float(d.get("seconds") or 0), kwh=kwh,
        started_at=datetime.fromtimestamp(started, tz=dt_timezone.utc) if started else None,
        cost=Decimal(str(cost)), avg_rate=Decimal(str(round(cost / kwh, 2) if kwh else 0)),
        breakdown=parts, reason=d.get("reason", ""),
    )


def _session_dict(s):
    return {
        "food": s.food, "kwh": round(s.kwh, 4), "cost": float(s.cost), "reason": s.reason,
        "ended_at": s.ended_at.timestamp(), "cooker": s.cooker_name,
    }


def _info():
    return {
        "currency": settings.CURRENCY, "tariff_label": settings.REG_TARIFF_LABEL,
        "vat_percent": float(settings.REG_VAT_PERCENT),
        "blocks": [{"upto": u, "rate": r} for u, r in blocks()],
    }


def live_summary(cooker, sim):
    """Everything the dashboard shows about cost for one cooker (cheap: two small queries)."""
    used = month_used(cooker.owner_id)
    live = bool(sim.cook_open)
    if live:
        kwh = float(sim.energy)
        this_cost, parts = price(used, kwh)
    else:
        last = cooker.sessions.first() if sim.energy > 1e-6 else None
        kwh = last.kwh if last else 0.0
        this_cost = float(last.cost) if last else 0.0
        parts = last.breakdown if last else []
    total_kwh = used + (float(sim.energy) if live else 0.0)
    month_cost, _ = price(0.0, total_kwh)
    idx, rate, left = block_at(total_kwh)
    out = _info()
    out.update({
        "live": live, "this_cook": this_cost, "this_kwh": round(kwh, 4), "breakdown": parts,
        "avg_rate": round(this_cost / kwh, 2) if kwh > 1e-9 else rate * _vat_factor(),
        "rate": round(rate * _vat_factor(), 2), "block": idx, "block_label": block_label(idx),
        "block_left": left,
        "month_kwh": round(total_kwh, 4), "month_cost": month_cost,
        "month_name": month_window()[0].strftime("%B %Y"),
        "recent": [_session_dict(s) for s in cooker.sessions.all()[:5]],
    })
    return out


def owner_month(owner):
    """Month-to-date kWh and cost for one account (all its cookers)."""
    used = month_used(owner.pk)
    cost, _ = price(0.0, used)
    idx, rate, left = block_at(used)
    out = _info()
    out.update({"month_kwh": round(used, 3), "month_cost": cost, "rate": round(rate * _vat_factor(), 2),
                "block": idx, "block_label": block_label(idx), "block_left": left,
                "month_name": month_window()[0].strftime("%B %Y")})
    return out


def all_month():
    """Totals for the admin dashboard: every account's kWh and billed cost this month."""
    start, nxt = month_window()
    agg = CookSession.objects.filter(ended_at__gte=start, ended_at__lt=nxt).aggregate(k=Sum("kwh"), c=Sum("cost"))
    n = CookSession.objects.filter(ended_at__gte=start, ended_at__lt=nxt).count()
    return {"kwh": round(float(agg["k"] or 0), 3), "cost": round(float(agg["c"] or 0), 2), "cooks": n}
