"""Checks for the amount (kg) feature.  Run:  python test_quantity.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["DJANGO_DB_PATH"] = os.path.join(tmp, "t.sqlite3")
os.environ["DJANGO_REQUIRE_APPROVAL"] = "0"
os.environ["DJANGO_SETTINGS_MODULE"] = "sizzle_project.settings"
import django; django.setup()
from django.core.management import call_command
call_command("migrate", verbosity=0)
from django.test import Client
from django.contrib.auth import get_user_model
from cooker import simulator as S
from cooker.models import Cooker, CookSession

n = 0
def check(cond, label):
    global n
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: sys.exit(1)
    n += 1
def near(a, b, tol=0.01): return abs(a - b) <= tol

# --- 1. the physics model -------------------------------------------------------------------
for k, f in S.FOODS.items():
    ref = S.energy_estimate_kwh(k, f["ref_kg"])
    check(0.1 < ref < S.ENERGY_CAP_KWH, f"{k}: the usual batch ({f['ref_kg']} kg) needs {ref:.2f} kWh, inside the cap")
    check(S.energy_estimate_kwh(k, f["max_kg"]) <= S.ENERGY_CAP_KWH, f"{k}: the largest batch ({f['max_kg']} kg) still fits the 0.50 kWh cap")
    check(S.energy_estimate_kwh(k, f["max_kg"] + S.KG_STEP) > S.ENERGY_CAP_KWH, f"{k}: one more step would exceed the cap")
    check(S.energy_estimate_kwh(k, 1.0) > S.energy_estimate_kwh(k, 0.5), f"{k}: more food needs more energy")
    check(S.cook_seconds_for(k, f["max_kg"]) > S.cook_seconds_for(k, f["min_kg"]), f"{k}: bigger batches take longer")
    check(S.cook_seconds_for(k, f["ref_kg"]) == f["time"] * 60, f"{k}: the usual batch keeps the standard cooking time")
check(S.clamp_kg("rice", 0.77) == 0.75 and S.clamp_kg("rice", 99) == S.FOODS["rice"]["max_kg"] and S.clamp_kg("rice", 0) == 0.1, "kg is rounded to 0.05 and clamped")

# --- 2. through the API --------------------------------------------------------------------
User = get_user_model()
c = Client()
c.post("/accounts/signup/", {"username": "kay", "password1": "Sizzle-Test-4821!", "password2": "Sizzle-Test-4821!"})
ck = Cooker.objects.get(owner__username="kay")
def cmd(command, value=None):
    return c.post(f"/c/{ck.pk}/api/command", data=json.dumps({"command": command, "value": value}), content_type="application/json")
def state(): return c.get(f"/c/{ck.pk}/api/state").json()
def fast_forward(sec):
    ck.refresh_from_db(); d = dict(ck.state_data); d["last_tick"] -= sec; ck.state_data = d; ck.save()

st = state()
check(st["quantity_kg"] == 0.5 and st["food"] == "beans", "new cooker starts with 0.5 kg of beans")
check(st["foods"]["beans"]["max_kg"] == S.FOODS["beans"]["max_kg"] and "water" in st["foods"]["beans"], "dashboard gets each food's min / max kg")
check(near(st["water_litres"], 1.25), "recommended water for 0.5 kg beans = 1.25 L")
base_budget, base_cost, base_min = st["energy_budget"], st["cost"]["plan_cost"], st["plan_minutes"]
check(near(st["cost"]["plan_kwh"], base_budget, 0.0001) and base_cost > 0, "the cost of the planned cook is shown before starting")

r = cmd("quantity", 0.9)
st = r.json()
check(r.status_code == 200 and st["quantity_kg"] == 0.9, "set 0.9 kg of beans")
check(st["energy_budget"] > base_budget and st["cost"]["plan_cost"] > base_cost and st["plan_minutes"] > base_min, "more beans: more kWh, more RWF, more minutes")
check(near(st["cost"]["plan_cost_per_kg"], st["cost"]["plan_cost"] / 0.9, 0.01), "cost per kg is reported")
check(near(st["remaining"], st["cooking_seconds"], 0.5) and near(st["water_litres"], 2.25), "timer and water follow the amount")

r = cmd("quantity", 5)
check(r.status_code == 400 and "kg" in r.json()["error"], "an amount that would break the 0.50 kWh cap is refused")
check(cmd("quantity", "abc").status_code == 400, "non-numeric amount is refused")
check(cmd("quantity", 0.01).status_code == 400, "too small an amount is refused")

cmd("food", "rice")
check(state()["quantity_kg"] == S.FOODS["rice"]["ref_kg"], "changing food goes back to that food's usual batch")
cmd("quantity", 1.2); cmd("speed", 20)
st = state(); budget = st["energy_budget"]
check(near(budget, S.energy_estimate_kwh("rice", 1.2), 0.001), "energy plan matches the physics model for 1.2 kg rice")

cmd("start")
check(cmd("quantity", 0.5).status_code == 409, "the amount cannot change while cooking")
fast_forward(400)
st = state()
check(st["state"] == "READY" and near(st["energy"], budget, 0.002), "a full cook uses the planned energy for that amount")
s1 = CookSession.objects.get()
check(near(s1.quantity_kg, 1.2) and near(float(s1.cost), budget * 89, 0.2), "the booked cook stores kg and costs planned kWh x 89")
check(st["cost"]["recent"][0]["kg"] == 1.2 and near(st["cost"]["recent"][0]["cost_per_kg"], float(s1.cost) / 1.2, 0.01), "recent cooks show kg and RWF per kg")

# a small batch costs less than a big one
cmd("quantity", 0.3); cmd("start"); fast_forward(400); state()
s2 = CookSession.objects.order_by("-ended_at").first()
check(s2.kwh < s1.kwh and float(s2.cost) < float(s1.cost), "0.3 kg costs less than 1.2 kg")

r = c.get(f"/c/{ck.pk}/")
check(b'id="qtySlider"' in r.content and b'id="planLine"' in r.content, "cooker page has the amount slider and plan line")

# --- 3. old saved cookers --------------------------------------------------------------------
ck.state_data = {"state": "IDLE", "current_food": "cassava", "energy": 0.0}; ck.save()
st = state()
check(st["quantity_kg"] == 1.0 and st["energy_budget"] > 0, "cookers saved before this upgrade get their usual batch and a plan")
print("\nALL %d AMOUNT CHECKS PASSED" % n)
