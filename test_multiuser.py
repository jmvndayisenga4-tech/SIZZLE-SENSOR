import os, re, sys, json, time, threading, tempfile
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
from cooker.models import Cooker

PW = "Sizzle-Test-4821!"
ok_count = 0
def check(cond, label):
    global ok_count
    print(("PASS " if cond else "FAIL ") + label)
    if not cond: sys.exit(1)
    ok_count += 1

def token(html):
    return re.search(r'data-csrf="([^"]+)"', html).group(1)

def signup(name):
    c = Client(enforce_csrf_checks=True)
    c.get("/accounts/signup/")
    t = c.cookies["csrftoken"].value
    r = c.post("/accounts/signup/", {"username": name, "password1": PW, "password2": PW, "csrfmiddlewaretoken": t})
    return c, r

def api(c, pk, cmd=None, value=None, tok=None, path=None):
    if cmd is None:
        return c.get(f"/c/{pk}/api/state")
    return c.post(f"/c/{pk}/api/command", data=json.dumps({"command": cmd, "value": value}),
                  content_type="application/json", HTTP_X_CSRFTOKEN=tok or "")

# --- 1. anonymous access is blocked ------------------------------------------
anon = Client()
r = anon.get("/");                      check(r.status_code == 302 and "/accounts/login/" in r["Location"], "anonymous / redirects to login")
r = anon.get("/c/1/");                  check(r.status_code == 302, "anonymous dashboard redirects to login")
r = anon.get("/c/1/api/state");         check(r.status_code == 401 and r.json()["error"] == "login required", "anonymous API gets JSON 401")
r = anon.get("/accounts/login/");       check(r.status_code == 200 and b"Sign in" in r.content, "login page renders")

# --- 2. signup + first cooker --------------------------------------------------
alice, r = signup("alice")
check(r.status_code == 302, "signup succeeds and redirects")
a_ck = Cooker.objects.get(owner__username="alice")
check(a_ck.name == "Kitchen cooker", "signup creates a first cooker")
r = alice.get("/");                      check(r.status_code == 200 and b"Kitchen cooker" in r.content, "home lists the cooker")
r = alice.get(f"/c/{a_ck.pk}/")
check(r.status_code == 200, "dashboard renders")
html = r.content.decode(); tokA = token(html)
check(f'/c/{a_ck.pk}/api/state' in html and f'/c/{a_ck.pk}/api/command' in html, "dashboard points at its own cooker's API")
need = ["tempBar","energyBar","powerBar","progBar","pressureBtn","foodRow","modeRow","qrImg","lanUrl"]
check(all(f'id="{i}"' in html for i in need), "dashboard still has every element app.js needs")

# --- 3. API payload shape unchanged ---------------------------------------------
s = api(alice, a_ck.pk).json()
keys = ["state","mode","food","power","pressure","temperature","target_temp","energy","energy_pct","remaining","progress",
        "sim_speed","ready","ready_reason","history","links","foods","modes","food_icon","cooking_seconds"]
check(all(k in s for k in keys) and s["ok"] is True, "state JSON has every field app.js reads")
check(s["links"]["lan"].endswith(f"/c/{a_ck.pk}/"), "QR link opens this exact cooker")

# --- 4. CSRF enforced ---------------------------------------------------------------
r = api(alice, a_ck.pk, "start", tok="")
check(r.status_code == 403, "command without CSRF token is rejected (403)")
r = api(alice, a_ck.pk, "start", tok=tokA)
check(r.status_code == 200 and r.json()["state"] == "PREHEAT", "command with CSRF token works: start -> PREHEAT")
check(api(alice, a_ck.pk, "bogus", tok=tokA).status_code == 400, "unknown command -> 400 JSON error")
check(api(alice, a_ck.pk, "power", "abc", tok=tokA).json()["error"].startswith("power must"), "bad value -> readable error")

# --- 5. every command still works -------------------------------------------------------
api(alice, a_ck.pk, "stop", tok=tokA)
for cmd, val, field, expect in [("food","rice","food","rice"),("mode","MANUAL","mode","MANUAL"),("power",40,"power",40),
                                ("target",90,"target_temp",90),("speed",5,"sim_speed",5),("pressure",True,"pressure",True)]:
    r = api(alice, a_ck.pk, cmd, val, tok=tokA).json()
    check(r[field] == expect, f"command '{cmd}' applied ({field}={expect})")
check(api(alice, a_ck.pk).json()["power"] == 40, "settings persist between requests (stored in DB)")
r = alice.post(f"/c/{a_ck.pk}/api/reset", HTTP_X_CSRFTOKEN=tokA); check(r.status_code == 200 and r.json()["state"] == "IDLE", "reset works")

# --- 6. second user cannot touch Alice's cooker -------------------------------------------
bob, _ = signup("bob")
b_ck = Cooker.objects.get(owner__username="bob")
tokB = token(bob.get(f"/c/{b_ck.pk}/").content.decode())
check(api(bob, a_ck.pk).status_code == 404, "Bob cannot read Alice's cooker (404)")
check(api(bob, a_ck.pk, "start", tok=tokB).status_code == 404, "Bob cannot command Alice's cooker (404)")
check(bob.get(f"/c/{a_ck.pk}/").status_code == 404, "Bob cannot open Alice's page (404)")
r = bob.post(f"/c/{a_ck.pk}/delete/", {"csrfmiddlewaretoken": bob.cookies["csrftoken"].value})
check(r.status_code == 404 and Cooker.objects.filter(pk=a_ck.pk).exists(), "Bob (valid CSRF) still cannot delete Alice's cooker")
api(alice, a_ck.pk, "mode", "AUTO", tok=tokA); api(alice, a_ck.pk, "start", tok=tokA)
api(bob, b_ck.pk, "food", "maize", tok=tokB)
sa, sb = api(alice, a_ck.pk).json(), api(bob, b_ck.pk).json()
check(sa["state"] == "PREHEAT" and sb["state"] == "IDLE" and sa["food"] == "rice" and sb["food"] == "maize",
      "two users cook completely separately")

# --- 7. cooking continues while the owner is away (lazy catch-up, no thread) ---------------
api(alice, a_ck.pk, "speed", 20, tok=tokA)
row = Cooker.objects.get(pk=a_ck.pk); d = row.state_data; d["last_tick"] -= 120; row.state_data = d; row.save()
s = api(alice, a_ck.pk).json()
check(s["temperature"] > 60 and s["state"] in ("BOIL","SIMMER","READY") and s["energy"] > 0,
      f"2 min away at 20x: now {s['state']}, {s['temperature']:.0f}C, {s['energy']:.3f} kWh")
row = Cooker.objects.get(pk=a_ck.pk); d = row.state_data; d["last_tick"] -= 3 * 3600; row.state_data = d; row.save()
s = api(alice, a_ck.pk).json()
check(s["state"] == "READY" and s["energy"] <= 0.5 + 1e-9 and s["ready"] is True, f"long absence ends READY, energy {s['energy']} <= 0.50 cap")
check(api(bob, b_ck.pk).json()["state"] == "IDLE", "Bob's cooker was not affected")

# --- 8. multiple cookers per user, limit, rename, delete ------------------------------------
tH = alice.get("/").cookies["csrftoken"].value
def post(c, url, **data):
    data["csrfmiddlewaretoken"] = c.cookies["csrftoken"].value
    return c.post(url, data)
for i in range(4): post(alice, "/c/new/", name=f"Extra {i}")
check(Cooker.objects.filter(owner__username="alice").count() == 5, "Alice can have 5 cookers")
r = post(alice, "/c/new/", name="Too many"); check(Cooker.objects.filter(owner__username="alice").count() == 5, "6th cooker refused (limit)")
ex = Cooker.objects.filter(owner__username="alice").last()
post(alice, f"/c/{ex.pk}/rename/", name="Renamed!"); ex.refresh_from_db(); check(ex.name == "Renamed!", "rename works")
post(alice, f"/c/{ex.pk}/delete/"); check(not Cooker.objects.filter(pk=ex.pk).exists(), "owner can delete a cooker")
check(alice.get("/").status_code == 200, "home page lists all cookers after changes")

# --- 9. logout ---------------------------------------------------------------------------------
r = post(alice, "/accounts/logout/"); check(r.status_code == 302, "logout works")
check(alice.get("/c/1/api/state").status_code == 401, "after logout the API is locked again")

# --- 10. many simultaneous requests on ONE cooker (phone + laptop + spam) -------------------------
carol, _ = signup("carol")
c_ck = Cooker.objects.get(owner__username="carol")
tokC = token(carol.get(f"/c/{c_ck.pk}/").content.decode())
api(carol, c_ck.pk, "speed", 20, tok=tokC); api(carol, c_ck.pk, "start", tok=tokC)
sessionid = carol.cookies["sessionid"].value; csrfc = carol.cookies["csrftoken"].value
errors, energies = [], []
def worker(n):
    c = Client(enforce_csrf_checks=True); c.cookies["sessionid"] = sessionid; c.cookies["csrftoken"] = csrfc
    for i in range(25):
        try:
            r = api(c, c_ck.pk) if i % 3 else api(c, c_ck.pk, "power", 50 + (i % 5) * 10, tok=tokC)
            if r.status_code != 200: errors.append(r.status_code)
            else: energies.append(r.json()["energy"])
        except Exception as e:
            errors.append(repr(e))
ts = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
t0 = time.time(); [t.start() for t in ts]; [t.join() for t in ts]
check(not errors, f"200 concurrent requests, no errors ({time.time()-t0:.1f}s)")
check(max(energies) <= 0.5 + 1e-9, "energy never exceeds the 0.50 kWh cap under load")

# --- 11. admin approval -------------------------------------------------------------------------
from django.test import override_settings
with override_settings(REQUIRE_APPROVAL=True):
    dave = Client(enforce_csrf_checks=True); dave.get("/accounts/signup/")
    r = dave.post("/accounts/signup/", {"username": "dave", "password1": PW, "password2": PW,
                                        "csrfmiddlewaretoken": dave.cookies["csrftoken"].value})
    U = get_user_model(); du = U.objects.get(username="dave")
    check(r.status_code == 302 and r["Location"] == "/accounts/pending/" and not du.is_active, "new sign-up is created inactive and sent to 'waiting' page")
    check(b"Waiting for approval" in dave.get("/accounts/pending/").content, "waiting-for-approval page renders")
    check(dave.get("/").status_code == 302, "unapproved user is not logged in after sign-up")
    r = dave.post("/accounts/login/", {"username": "dave", "password": PW, "csrfmiddlewaretoken": dave.cookies["csrftoken"].value})
    check(r.status_code == 200 and b"waiting for admin approval" in r.content and "sessionid" not in dave.cookies, "pending user cannot sign in and is told why")
    r = dave.post("/accounts/login/", {"username": "dave", "password": "wrong-password", "csrfmiddlewaretoken": dave.cookies["csrftoken"].value})
    check(b"waiting for admin approval" not in r.content, "wrong password does not reveal that the account is pending")
    # admin approves with the bulk action
    U.objects.create_superuser("boss", password=PW)
    adm = Client(); adm.login(username="boss", password=PW)
    r = adm.get("/admin/auth/user/"); check(r.status_code == 200 and b"Approve selected accounts" in r.content, "admin Users list offers the approve action")
    r = adm.post("/admin/auth/user/", {"action": "approve_accounts", "_selected_action": [du.pk]})
    du.refresh_from_db(); check(r.status_code == 302 and du.is_active, "admin approves the account in one click")
    dave.get("/accounts/login/")
    r = dave.post("/accounts/login/", {"username": "dave", "password": PW, "csrfmiddlewaretoken": dave.cookies["csrftoken"].value})
    check(r.status_code == 302 and dave.get("/").status_code == 200 and b"Kitchen cooker" in dave.get("/").content, "approved user signs in and finds a ready cooker")
    r = adm.post("/admin/auth/user/", {"action": "disable_accounts", "_selected_action": [du.pk]})
    check(dave.get("/").status_code == 302, "disabling an account logs that user out immediately")


# --- 12. approve from the My cookers page (staff only) -----------------------------------------------
with override_settings(REQUIRE_APPROVAL=True):
    eve = Client(enforce_csrf_checks=True); eve.get("/accounts/signup/")
    eve.post("/accounts/signup/", {"username": "eve", "password1": PW, "password2": PW, "csrfmiddlewaretoken": eve.cookies["csrftoken"].value})
    ev = U.objects.get(username="eve")
    staff = Client(enforce_csrf_checks=True); staff.get("/accounts/login/")
    staff.post("/accounts/login/", {"username": "boss", "password": PW, "csrfmiddlewaretoken": staff.cookies["csrftoken"].value})
    html = staff.get("/").content.decode()
    check("Waiting for approval" in html and ">eve<" in html and f"/users/{ev.pk}/approve/" in html, "admin sees the waiting account on My cookers")
    carol_html = carol.get("/").content.decode()
    check("Waiting for approval" not in carol_html, "normal users do not see the approval panel")
    r = carol.post(f"/users/{ev.pk}/approve/", {"csrfmiddlewaretoken": carol.cookies["csrftoken"].value})
    ev.refresh_from_db(); check(r.status_code == 404 and not ev.is_active, "a normal user cannot approve accounts")
    r = staff.post(f"/users/{ev.pk}/approve/", {"csrfmiddlewaretoken": staff.cookies["csrftoken"].value})
    ev.refresh_from_db(); check(r.status_code == 302 and ev.is_active, "admin approves with one click from My cookers")
    check(b"was approved" in staff.get("/").content, "admin sees a confirmation message")
    fay = Client(enforce_csrf_checks=True); fay.get("/accounts/signup/")
    fay.post("/accounts/signup/", {"username": "fay", "password1": PW, "password2": PW, "csrfmiddlewaretoken": fay.cookies["csrftoken"].value})
    fu = U.objects.get(username="fay")
    r = staff.post(f"/users/{fu.pk}/reject/", {"csrfmiddlewaretoken": staff.cookies["csrftoken"].value})
    check(r.status_code == 302 and not U.objects.filter(username="fay").exists() and not Cooker.objects.filter(owner_id=fu.pk).exists(), "admin can reject (account and its cooker removed)")
    boss = U.objects.get(username="boss")
    r = staff.post(f"/users/{boss.pk}/reject/", {"csrfmiddlewaretoken": staff.cookies["csrftoken"].value})
    check(r.status_code == 404 and U.objects.filter(username="boss").exists(), "admins cannot be rejected through this panel")

print(f"\nALL {ok_count} CHECKS PASSED")
