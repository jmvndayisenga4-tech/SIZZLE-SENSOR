"""Checks for the REG cost / kWh feature.  Run:  python test_cost.py"""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["DJANGO_DB_PATH"] = os.path.join(tmp, "t.sqlite3")
os.environ["DJANGO_REQUIRE_APPROVAL"] = "0"
os.environ["DJANGO_SETTINGS_MODULE"] = "sizzle_project.settings"
import django; django.setup()
from django.core.management import call_command
call_command("migrate", verbosity=0)
from django.test import Client, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from cooker import tariff
from cooker.models import Cooker, CookSession

n = 0
def check(cond, label):
    global n
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: sys.exit(1)
    n += 1
def near(a, b, tol=0.02): return abs(a - b) <= tol

# --- 1. tariff maths (REG residential: 20 kWh @89, to 50 kWh @310, above @369) ------------------
check(tariff.price(0, 0.5)[0] == 44.5, "0.5 kWh in block 1 = 44.50 RWF")
check(near(tariff.price(19.8, 0.5)[0], 0.2 * 89 + 0.3 * 310), "a cook crossing 20 kWh is split across two rates")
check(len(tariff.price(19.8, 0.5)[1]) == 2, "split cook reports two breakdown lines")
check(near(tariff.price(49.9, 0.3)[0], 0.1 * 310 + 0.2 * 369), "crossing 50 kWh uses 310 then 369")
check(tariff.price(60, 1)[0] == 369, "above 50 kWh = 369 RWF/kWh")
check(tariff.price(0, 0)[0] == 0, "zero energy costs nothing")
check(tariff.price(0, 100)[0] == 20 * 89 + 30 * 310 + 50 * 369, "100 kWh walks all three blocks")
check(tariff.block_at(0) == (1, 89.0, 20.0), "block_at(0)")
check(tariff.block_at(20) == (2, 310.0, 30.0), "block_at(20) moves to block 2")
check(tariff.block_at(75) == (3, 369.0, None), "block_at(75) is the open top block")
check(tariff.block_label(1) == "0-20 kWh" and tariff.block_label(3) == "above 50 kWh", "block labels")
with override_settings(REG_VAT_PERCENT=18):
    check(near(tariff.price(0, 1)[0], 89 * 1.18, 0.01), "optional VAT is added on top")

# --- 2. a full cook through the real API ----------------------------------------------------------
User = get_user_model()
def login(name):
    c = Client()
    c.post("/accounts/signup/", {"username": name, "password1": "Sizzle-Test-4821!", "password2": "Sizzle-Test-4821!"})
    u = User.objects.get(username=name)
    return c, u, Cooker.objects.get(owner=u)

def cmd(c, pk, command, value=None):
    return c.post(f"/c/{pk}/api/command", data=json.dumps({"command": command, "value": value}), content_type="application/json")

def state(c, pk): return c.get(f"/c/{pk}/api/state").json()

def fast_forward(ck, seconds):
    ck.refresh_from_db(); d = dict(ck.state_data); d["last_tick"] -= seconds; ck.state_data = d; ck.save()

alice, ua, ca = login("alice")
bob, ub, cb = login("bob")
st = state(alice, ca.pk)
check(st["cost"]["this_cook"] == 0 and st["cost"]["month_cost"] == 0, "fresh account starts at 0 RWF")
check(st["cost"]["rate"] == 89 and st["cost"]["block"] == 1, "fresh account is in block 1 at 89 RWF/kWh")

cmd(alice, ca.pk, "food", "rice"); cmd(alice, ca.pk, "speed", 20); cmd(alice, ca.pk, "start")
fast_forward(ca, 20)                       # 20 real s x 20 = 400 simulated s of a 1200 s cook
st = state(alice, ca.pk)
budget = st["energy_budget"]
check(st["cost"]["live"] and 0 < st["energy"] < budget, "mid-cook: cost is live")
check(near(st["cost"]["this_cook"], st["energy"] * 89, 0.05), "live cost = kWh used so far x 89")
check(CookSession.objects.filter(owner=ua).count() == 0, "nothing is booked until the cook ends")

fast_forward(ca, 200)                      # enough to finish
st = state(alice, ca.pk)
check(st["state"] == "READY" and not st["cost"]["live"], "cook finished")
check(near(st["energy"], budget, 0.002), "a full cook uses the energy planned for its amount")
check(near(st["cost"]["this_cook"], budget * 89, 0.2), "finished cook costs planned kWh x 89 RWF")
check(CookSession.objects.filter(owner=ua).count() == 1, "exactly one cook booked")
check(len(st["cost"]["recent"]) == 1 and st["cost"]["recent"][0]["food"] == "rice", "recent list shows the cook")
check(near(st["cost"]["month_kwh"], budget, 0.002), "month total counts the cook once")
state(alice, ca.pk); state(alice, ca.pk)
check(CookSession.objects.filter(owner=ua).count() == 1, "polling again never double-books")

# --- 3. stopping early bills only what was used --------------------------------------------------
cmd(alice, ca.pk, "start"); fast_forward(ca, 15)
state(alice, ca.pk)
cmd(alice, ca.pk, "stop")
st = state(alice, ca.pk)
sessions = list(CookSession.objects.filter(owner=ua).order_by("ended_at"))
check(len(sessions) == 2 and sessions[1].reason == "stopped", "stopped cook is booked with reason 'stopped'")
check(0 < sessions[1].kwh < budget and near(float(sessions[1].cost), sessions[1].kwh * 89, 0.02), "stopped cook billed for energy used only")
check(near(st["cost"]["month_kwh"], sessions[0].kwh + sessions[1].kwh, 0.001), "month total adds both cooks")

# --- 4. blocks are per account and move up with usage -------------------------------------------
check(tariff.month_used(ub.pk) == 0, "another account's usage is separate")
CookSession.objects.create(owner=ub, cooker=cb, ended_at=timezone.now(), kwh=19.8, cost=0)
st = state(bob, cb.pk)
check(st["cost"]["block"] == 1 and near(st["cost"]["block_left"], 0.2, 0.001), "bob has 0.2 kWh left in block 1")
cmd(bob, cb.pk, "food", "rice"); cmd(bob, cb.pk, "speed", 20); cmd(bob, cb.pk, "start"); fast_forward(cb, 220)
st = state(bob, cb.pk)
last = CookSession.objects.filter(owner=ub).order_by("-ended_at").first()
check(near(float(last.cost), 0.2 * 89 + (last.kwh - 0.2) * 310, 0.1), "bob's cook crosses into block 2 and is priced across both")
check([p["block"] for p in last.breakdown] == [1, 2], "breakdown stored per block")
check(st["cost"]["block"] == 2 and st["cost"]["rate"] == 310, "bob is now on 310 RWF/kWh")

# --- 5. pages ------------------------------------------------------------------------------------
r = alice.get("/")
check(r.status_code == 200 and b"Electricity cost" in r.content and b"cost this month" in r.content, "home page shows monthly cost")
r = alice.get(f"/c/{ca.pk}/")
check(r.status_code == 200 and b"Cost at REG tariff" in r.content and b"readyCost" in r.content, "cooker page has the cost card")
ua.is_staff = True; ua.save()
r = alice.get("/manage/")
tot = tariff.all_month()
check(r.status_code == 200 and b"RWF at REG tariff" in r.content, "admin dashboard shows RWF total")
check(tot["cooks"] == 4 and tot["kwh"] > 20, "admin totals cover every account")

# --- 6. old saved state without the new fields still loads --------------------------------------
old = {"state": "IDLE", "current_food": "beans", "energy": 0.1}
ca.state_data = old; ca.save()
check(state(alice, ca.pk)["state"] == "IDLE", "cookers saved before this upgrade still load")

print("\nALL %d COST CHECKS PASSED" % n)
