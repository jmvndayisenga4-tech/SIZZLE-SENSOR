# Sizzle Sense (Django)

Smart cooker simulator: Django backend + Bootstrap 5 dashboard. The simulation
runs on the server and every user has their own account and their own cookers.

## Accounts: every user cooks separately

Each person signs up / logs in with a Django account and owns their own cookers
(default limit 5 per account). A cooker is a database row; its simulator state is
stored in `Cooker.state_data`. Nobody can see or control another user's cooker
(all `/c/<id>/...` URLs return 404 for non-owners, and the JSON API returns 401
when logged out).

There is **no background thread any more**. Whenever a cooker is opened or polled,
the server replays the real time that has passed since it was last updated, in
0.5 s steps, so the physics are the same as before and a cooker keeps cooking
(and stops at the 0.50 kWh cap) while its owner is away. When the owner comes back
the cooker shows READY / the right temperature.

## Approving new accounts

By default a new sign-up is created **inactive**: the person sees a "Waiting for approval"
page and cannot sign in.

**Quickest way:** sign in as an admin (staff/superuser) and open **My cookers**. A
**Waiting for approval** panel lists every pending account with **Approve** and **Reject**
buttons (reject deletes the account and its cooker). Normal users never see this panel.

**Or in the Django admin:**

1. Log in at `/admin/` with a superuser (`python manage.py createsuperuser`).
2. Open **Users**: waiting accounts are listed first (Active = unticked; filter by *Is active*).
3. Tick them and choose **Approve selected accounts** (or open one user and tick *Active*).

Use **Disable selected accounts** to lock someone out; they are signed out immediately.
Their first cooker is already created, so it is ready as soon as they are approved.
Accounts you create yourself in `/admin/` or with `createsuperuser` are active straight away.

## Electricity cost (REG tariff)

Every finished cook is priced at the REG (Rwanda Energy Group) residential tariff, effective
1 October 2025 (RURA notice, VAT exclusive):

| Monthly use of the account | RWF per kWh |
|---|---|
| first 20 kWh | 89 |
| 21 - 50 kWh | 310 |
| above 50 kWh | 369 |

* Blocks restart every calendar month (Africa/Kigali) and are shared by all cookers of an account,
  like a household meter. A cook that crosses a boundary is split across both rates.
* The cooker page shows the cost so far while cooking, the rate and block you are in, the month
  total, a **Recent cooks** list, and the cost of the cook in the "ready" pop-up.
* *My cookers* shows the month's kWh and cost for the account; the admin dashboard shows the
  totals for all accounts.
* Cooks are stored in the `CookSession` table (run `python manage.py migrate` once after upgrading;
  on Vercel run it against your database from your computer with `DATABASE_URL` set).
* Settings (environment variables): `REG_TARIFF_BLOCKS` (default `20:89,50:310,*:369`),
  `REG_VAT_PERCENT` (default `0`), `REG_TARIFF_LABEL`, `BILLING_TIME_ZONE`.
* The prototype is solar powered, so this is the value of the energy at the grid price (what the
  same cook would cost on REG power), not a bill.

Run the cost checks with `python test_cost.py`.

## Amount of food (kg)

Type how much you are cooking in the **Amount of food** field (any amount from 0.05 to 100 kg,
10 g precision, press Enter or Set). Before you press start it shows the plan: kWh, cost at the
REG tariff, RWF per kg, minutes, and how much water to add.

* Energy comes from heating physics, not a fixed number: the food, its water and the pot are
  heated to the food's cooking temperature (specific heat x mass x temperature rise, divided by
  the cooker's efficiency) plus the heat lost while it simmers. See `energy_estimate_kwh` in
  `cooker/simulator.py`; the constants per food (`cp`, `water`, `ref_kg`) are at the top of that file.
* Cooking time grows a little with the batch (the usual batch keeps the standard time).
* There is no limit per food. The 0.50 kWh battery cap is still a hard safety stop: if a batch
  needs more (for example more than about 0.9 kg of beans), the plan line turns amber and says so,
  the cooker stops at the cap with "energy cap reached" (food only partly cooked) and bills only
  the energy used. The plan line suggests how many smaller batches would fit.
* The amount can only be changed while the cooker is idle or ready. Changing food goes back to
  that food's usual batch.
* Every booked cook stores its kg, so **Recent cooks** shows kg and RWF per kg.
* Run `python manage.py migrate` after upgrading (adds the `quantity_kg` column).
* The numbers are a model, not measurements: calibrate `cp`, `water`, the efficiencies and
  simmer losses against readings from the real prototype's energy meter.

Run the checks with `python test_quantity.py`.

## Run locally (Windows PowerShell)

```powershell
cd "SIZZLE SENSOR"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser      # optional: an admin account for /admin/
python manage.py runserver 0.0.0.0:8000
```

Open http://localhost:8000, click **Create an account**, and you land on *My cookers*.
The QR code on a cooker's page opens **that cooker**; the phone just logs in with the
same account (same Wi-Fi; allow Python through Windows Firewall if asked).

Run the automated checks (isolation, CSRF, catch-up, concurrency, every command):

```powershell
python test_multiuser.py
```

## Deploy (Render / Railway / any VPS)

| Variable | Value |
|---|---|
| `DJANGO_DEBUG` | `0` |
| `DJANGO_SECRET_KEY` | a long random string |
| `DJANGO_ALLOWED_HOSTS` | your domain, e.g. `sizzle.onrender.com` |
| `DJANGO_CSRF_TRUSTED` | `https://sizzle.onrender.com` |
| `DATABASE_URL` | *(recommended in production)* `postgres://user:pass@host:5432/db` |
| `DJANGO_REQUIRE_APPROVAL` | `1` (default): new sign-ups stay inactive until an admin approves them; `0` = instant access |
| `DJANGO_ALLOW_SIGNUP` | `0` to stop public registration (admin creates accounts) |
| `MAX_COOKERS_PER_USER` | default `5` |

Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput`

Start command (also in `Procfile`; it runs `migrate` first):

```
python manage.py migrate --noinput && gunicorn sizzle_project.wsgi --workers 1 --threads 8 --bind 0.0.0.0:$PORT
```

**Database:** the default is a SQLite file (`db.sqlite3`). That is fine on your own
PC or VPS, but on hosts with a temporary disk (Render free tier, Railway without a
volume) it is wiped on every deploy, deleting all accounts. Use PostgreSQL there
(`pip install "psycopg[binary]"` and set `DATABASE_URL`). With PostgreSQL you may raise
`--workers`; with SQLite keep `--workers 1`.

**Vercel + Neon (PostgreSQL):** works, but Vercel never runs `migrate` for you.
1. In Neon copy the connection string (Dashboard -> Connect). If you do not know the
   password, click *Reset password* first, then copy the new string.
2. Set `DATABASE_URL` in Vercel (Settings -> Environment Variables) to that string,
   with no extra quotes or spaces, for the Production environment, then **redeploy**.
3. Create the tables once, from your own PC, pointing at the same database:
   ```powershell
   $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/neondb?sslmode=require"
   python manage.py migrate
   python manage.py createsuperuser
   ```
4. Error `password authentication failed` = the password in `DATABASE_URL` is wrong or
   outdated. SQLite files cannot be used on Vercel (read-only disk).

## Layout

```
manage.py
test_multiuser.py       automated checks
requirements.txt
Procfile
sizzle_project/         settings, urls, wsgi/asgi
cooker/
  simulator.py          SmartCooker physics + to_dict/from_dict/advance (no Django imports)
  models.py             Cooker (owner, name, state_data)
  services.py           open_cooker(): per-cooker lock + transaction + catch-up + save
  views.py              accounts, My cookers, dashboard, per-cooker API, QR, PWA files
  urls.py  admin.py  migrations/
  templates/cooker/     dashboard.html, cooker_list.html, login.html, signup.html, base_auth.html
  static/cooker/        css/app.css, js/app.js
```

## API

- `GET  /c/<id>/api/state` - full snapshot (state, readings, history, links)
- `POST /c/<id>/api/command` - `{"command": "start|stop|reset|mode|food|power|pressure|target|speed", "value": ...}`
- `POST /c/<id>/api/reset`, `GET /healthz`, `GET /qr.png?url=...`
