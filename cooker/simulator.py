"""Smart-cooker simulator (pure Python, no Django imports).

Each user cooker is one ``SmartCooker`` whose state is stored in the database
(see ``cooker.models.Cooker``). There is no background thread: whenever a cooker
is loaded, ``advance()`` replays the real time that has passed since its last
update in small steps, so the physics are identical to the old always-running
simulation and the cooker keeps "cooking" while its owner is away.
"""
import threading
import time
from collections import deque

ENERGY_CAP_KWH = 0.50          # hard cap - never exceeded
TICK_SECONDS = 0.5             # simulator tick
AMBIENT_TEMP = 24.0            # room temperature (deg C)
HISTORY_LEN = 180              # ~90 s of samples at 0.5 s/tick
MAX_CATCHUP_SECONDS = 4 * 3600  # never replay more than this after a long absence

FOODS = {
    "beans":   {"label": "Beans",   "icon": "\U0001FAD8", "time": 45, "temp": 115, "pressure": True},
    "maize":   {"label": "Maize",   "icon": "\U0001F33D", "time": 30, "temp": 110, "pressure": True},
    "cassava": {"label": "Cassava", "icon": "\U0001F360", "time": 35, "temp": 112, "pressure": True},
    "rice":    {"label": "Rice",    "icon": "\U0001F35A", "time": 20, "temp": 100, "pressure": False},
    "potato":  {"label": "Potato",  "icon": "\U0001F954", "time": 25, "temp": 105, "pressure": False},
}

MODES = ("AUTO", "MANUAL", "SEMI")
COOKING_STATES = ("PREHEAT", "BOIL", "SIMMER")


class SmartCooker:
    """Thread-safe smart-cooker simulator."""

    def __init__(self):
        self.lock = threading.RLock()

        self.state = "IDLE"            # IDLE | PREHEAT | BOIL | SIMMER | READY
        self.mode = "AUTO"
        self.current_food = "beans"

        self.power = 0
        self.pressure = FOODS[self.current_food]["pressure"]
        self.target_temp = float(FOODS[self.current_food]["temp"])
        self.sim_speed = 1.0

        self.temperature = AMBIENT_TEMP
        self.energy = 0.0
        self.elapsed = 0.0
        self.cooking_seconds = FOODS[self.current_food]["time"] * 60
        self.remaining = float(self.cooking_seconds)

        self.should_shutdown = False
        self.started_at = None
        self.ready_at = None
        self.ready_reason = None
        self.history = deque(maxlen=HISTORY_LEN)
        self._last_tick = time.time()

        self._record()

    # -- helpers -----------------------------------------------------------
    def _record(self):
        self.history.append(
            {
                "t": round(time.time(), 3),
                "temp": round(self.temperature, 2),
                "energy": round(self.energy, 4),
                "power": round(self.power, 1),
            }
        )

    def _finish(self, reason):
        if self.state == "READY":
            return
        self.state = "READY"
        self.power = 0
        self.ready_at = time.time()
        self.ready_reason = reason

    def _reset_locked(self):
        self.state = "IDLE"
        self.power = 0
        self.energy = 0.0
        self.elapsed = 0.0
        self.cooking_seconds = FOODS[self.current_food]["time"] * 60
        self.remaining = float(self.cooking_seconds)
        self.should_shutdown = False
        self.started_at = None
        self.ready_at = None
        self.ready_reason = None
        self.history.clear()
        self._record()

    # -- physics -----------------------------------------------------------
    def update(self, dt=None):
        with self.lock:
            now = time.time()
            if dt is None:
                dt = now - self._last_tick
            dt = max(0.0, min(float(dt), 2.0))
            self._last_tick = now

            if self.state in COOKING_STATES:
                food = FOODS[self.current_food]
                sim_dt = dt * self.sim_speed

                cooking_seconds = food["time"] * 60
                base_rate = 70.0 / cooking_seconds
                pressure_boost = 1.35 if self.pressure else 1.0
                heating_rate = (self.power / 100.0) * base_rate * pressure_boost * self.sim_speed

                if self.temperature < self.target_temp:
                    self.temperature = min(self.target_temp, self.temperature + heating_rate * dt)
                else:
                    self.temperature = max(self.target_temp - 1.5, self.temperature - 0.05 * sim_dt)

                # Calibrated so a full cook at 100 % power uses exactly the cap.
                increment = (self.power / 100.0) * (ENERGY_CAP_KWH / cooking_seconds) * sim_dt
                self.energy = min(self.energy + increment, ENERGY_CAP_KWH)

                self.elapsed += sim_dt
                self.remaining = max(0.0, cooking_seconds - self.elapsed)

                if self.state == "PREHEAT" and self.temperature >= 60.0:
                    self.state = "BOIL"
                elif self.state == "BOIL" and self.temperature >= self.target_temp - 0.5:
                    self.state = "SIMMER"

                if self.remaining <= 0.0:
                    self.energy = min(self.energy, ENERGY_CAP_KWH)
                    self._finish("cook complete")
                elif self.energy >= ENERGY_CAP_KWH - 1e-9:
                    self.energy = ENERGY_CAP_KWH
                    self._finish("energy cap reached")
                elif self.should_shutdown:
                    self._finish("shutdown requested")

            elif self.state == "IDLE":
                if self.temperature > AMBIENT_TEMP:
                    self.temperature = max(AMBIENT_TEMP, self.temperature - 0.35 * dt)
                self.power = 0

            elif self.state == "READY":
                if self.temperature > AMBIENT_TEMP:
                    self.temperature = max(AMBIENT_TEMP, self.temperature - 0.25 * dt)
                self.power = 0

            self._record()

    # -- persistence + catch-up -------------------------------------------
    _FIELDS = (
        "state", "mode", "current_food", "power", "pressure", "target_temp", "sim_speed",
        "temperature", "energy", "elapsed", "cooking_seconds", "remaining",
        "should_shutdown", "started_at", "ready_at", "ready_reason",
    )

    def to_dict(self):
        with self.lock:
            data = {k: getattr(self, k) for k in self._FIELDS}
            data["last_tick"] = self._last_tick
            data["history"] = list(self.history)
            return data

    @classmethod
    def from_dict(cls, data):
        """Rebuild a cooker from ``to_dict`` output. Missing/invalid keys fall back to defaults."""
        c = cls()
        if not isinstance(data, dict) or not data:
            return c
        for k in cls._FIELDS:
            if k in data:
                setattr(c, k, data[k])
        if c.current_food not in FOODS:
            c.current_food = "beans"
        if c.mode not in MODES:
            c.mode = "AUTO"
        if c.state not in ("IDLE", "READY") + COOKING_STATES:
            c.state = "IDLE"
        c._last_tick = float(data.get("last_tick") or time.time())
        c.history = deque(data.get("history") or [], maxlen=HISTORY_LEN)
        if not c.history:
            c._record()
        return c

    def advance(self, now=None):
        """Replay the real time since the last update. Returns True if the state changed."""
        with self.lock:
            now = time.time() if now is None else now
            gap = now - self._last_tick
            if gap < 0.25:
                return False
            gap = min(gap, MAX_CATCHUP_SECONDS)
            if self.state in ("IDLE", "READY") and self.temperature <= AMBIENT_TEMP + 1e-9:
                self._last_tick = now      # nothing to simulate
                return False
            steps = 0
            while gap > 1e-9 and steps < 30000:
                step = TICK_SECONDS if self.state in COOKING_STATES else 2.0
                dt = min(step, gap)
                self.update(dt)
                gap -= dt
                steps += 1
                if self.state in ("IDLE", "READY") and self.temperature <= AMBIENT_TEMP + 1e-9:
                    break
            self._last_tick = now
            return True

    # -- commands ----------------------------------------------------------
    def start(self):
        with self.lock:
            if self.state in COOKING_STATES:
                return False, "already cooking"

            self.should_shutdown = False
            self.energy = 0.0
            self.elapsed = 0.0
            self.cooking_seconds = FOODS[self.current_food]["time"] * 60
            self.remaining = float(self.cooking_seconds)
            self.ready_at = None
            self.ready_reason = None
            self.started_at = time.time()

            if self.mode == "AUTO":
                self.power = 100
                self.pressure = FOODS[self.current_food]["pressure"]
                self.target_temp = float(FOODS[self.current_food]["temp"])
            elif self.power <= 0:
                self.power = 60

            self.state = "PREHEAT"
            return True, "started"

    def stop(self):
        with self.lock:
            self.state = "IDLE"
            self.power = 0
            self.should_shutdown = False
            self.started_at = None
            return True, "stopped"

    def reset_to_idle(self):
        with self.lock:
            self._reset_locked()
            return True, "reset"

    def set_mode(self, mode):
        mode = str(mode).upper().strip()
        if mode not in MODES:
            raise ValueError("mode must be one of %s" % ", ".join(MODES))

        with self.lock:
            self.mode = mode
            self.should_shutdown = False

            if mode == "AUTO":
                food = FOODS[self.current_food]
                self.target_temp = float(food["temp"])
                self.pressure = food["pressure"]
                if self.state in ("IDLE", "READY"):
                    self.power = 0
                    self.energy = 0.0
                    self.elapsed = 0.0
                    self.cooking_seconds = food["time"] * 60
                    self.remaining = float(self.cooking_seconds)
                    self.ready_at = None
                    self.ready_reason = None
                    self.state = "IDLE"
                else:
                    self.power = 100
            return True, "mode=" + mode

    def change_food(self, food):
        key = str(food).lower().strip()
        if key not in FOODS:
            raise ValueError("food must be one of %s" % ", ".join(FOODS))

        with self.lock:
            self.current_food = key
            self.cooking_seconds = FOODS[key]["time"] * 60
            self.target_temp = float(FOODS[key]["temp"])
            self.pressure = FOODS[key]["pressure"]
            self._reset_locked()
            return True, "food=" + key

    def set_power(self, power):
        try:
            power = float(power)
        except (TypeError, ValueError):
            raise ValueError("power must be a number 0-100")
        power = max(0.0, min(100.0, power))
        with self.lock:
            self.power = power
            return True, "power=%d" % int(power)

    def set_pressure(self, on):
        with self.lock:
            self.pressure = bool(on)
            return True, "pressure=%s" % self.pressure

    def set_target_temp(self, temp):
        try:
            temp = float(temp)
        except (TypeError, ValueError):
            raise ValueError("target must be a number")
        temp = max(40.0, min(130.0, temp))
        with self.lock:
            self.target_temp = temp
            return True, "target=%d" % int(temp)

    def set_sim_speed(self, speed):
        try:
            speed = float(speed)
        except (TypeError, ValueError):
            raise ValueError("speed must be a number")
        speed = max(0.25, min(20.0, speed))
        with self.lock:
            self.sim_speed = speed
            return True, "speed=%s" % speed

    def run_command(self, command, value=None):
        """Dispatch a UI command. Raises ValueError on bad input / unknown command."""
        table = {
            "start": lambda: self.start(),
            "stop": lambda: self.stop(),
            "reset": lambda: self.reset_to_idle(),
            "mode": lambda: self.set_mode(value),
            "food": lambda: self.change_food(value),
            "power": lambda: self.set_power(value),
            "pressure": lambda: self.set_pressure(value),
            "target": lambda: self.set_target_temp(value),
            "speed": lambda: self.set_sim_speed(value),
        }
        if command not in table:
            raise ValueError("unknown command: %s" % command)
        return table[command]()

    # -- snapshot ----------------------------------------------------------
    def snapshot(self):
        with self.lock:
            food = FOODS[self.current_food]
            total = float(self.cooking_seconds) or 1.0
            progress = max(0.0, min(1.0, 1.0 - (self.remaining / total)))
            return {
                "state": self.state,
                "mode": self.mode,
                "food": self.current_food,
                "food_label": food["label"],
                "food_icon": food["icon"],
                "foods": {
                    k: {"label": v["label"], "icon": v["icon"], "time": v["time"],
                        "temp": v["temp"], "pressure": v["pressure"]}
                    for k, v in FOODS.items()
                },
                "modes": list(MODES),
                "power": round(self.power, 1),
                "pressure": self.pressure,
                "temperature": round(self.temperature, 2),
                "target_temp": round(self.target_temp, 1),
                "energy": round(self.energy, 4),
                "energy_cap": ENERGY_CAP_KWH,
                "energy_pct": round(min(100.0, self.energy / ENERGY_CAP_KWH * 100.0), 1),
                "elapsed": round(self.elapsed, 1),
                "remaining": round(self.remaining, 1),
                "cooking_seconds": self.cooking_seconds,
                "progress": round(progress, 4),
                "sim_speed": self.sim_speed,
                "ready": self.state == "READY",
                "ready_reason": self.ready_reason,
                "ready_at": self.ready_at,
                "history": list(self.history),
                "server_time": round(time.time(), 3),
            }
