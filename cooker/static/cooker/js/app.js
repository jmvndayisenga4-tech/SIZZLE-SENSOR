(function () {
  "use strict";

  var body = document.body;
  var STATE_URL = body.dataset.stateUrl;
  var COMMAND_URL = body.dataset.commandUrl;
  var QR_URL = body.dataset.qrUrl;
  var SW_URL = body.dataset.swUrl;

  var SIMPLE = new URLSearchParams(location.search).has("simple");
  var POLL_MS = SIMPLE ? 1500 : 500;
  var inflight = false;
  var lastState = null;
  var readyShown = false;
  var charts = {};

  var $ = function (id) { return document.getElementById(id); };

  var FOODS = {
    beans:   { label: "Beans",   icon: "🫘" },
    maize:   { label: "Maize",   icon: "🌽" },
    cassava: { label: "Cassava", icon: "🍠" },
    rice:    { label: "Rice",    icon: "🍚" },
    potato:  { label: "Potato",  icon: "🥔" }
  };
  var MODES = ["AUTO", "MANUAL", "SEMI"];

  var readyModal = new bootstrap.Modal($("readyModal"));
  var toastEl = $("toast");
  var toastObj = new bootstrap.Toast(toastEl, { delay: 2000 });

  function toast(msg, isErr) {
    $("toastBody").textContent = msg;
    toastEl.classList.toggle("err", !!isErr);
    toastObj.show();
  }

  function fmtTime(s) {
    s = Math.max(0, Math.round(s));
    var m = Math.floor(s / 60), r = s % 60;
    return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r;
  }

  /* ---------- build chips ---------- */
  function buildChips() {
    var fr = $("foodRow");
    Object.keys(FOODS).forEach(function (k) {
      var b = document.createElement("button");
      b.className = "chip"; b.dataset.food = k;
      b.innerHTML = '<span class="ic">' + FOODS[k].icon + "</span>" + FOODS[k].label;
      b.addEventListener("click", function () { send("food", k); });
      fr.appendChild(b);
    });
    var mr = $("modeRow");
    MODES.forEach(function (m) {
      var b = document.createElement("button");
      b.className = "chip"; b.dataset.mode = m; b.textContent = m;
      b.addEventListener("click", function () { send("mode", m); });
      mr.appendChild(b);
    });
  }

  function setBusy(b) {
    ["startBtn", "stopBtn", "resetBtn", "pressureBtn"].forEach(function (id) { $(id).disabled = b; });
    document.querySelectorAll(".chip").forEach(function (c) { c.disabled = b; });
  }

  /* ---------- commands ---------- */
  function send(cmd, value) {
    if (inflight) return;
    inflight = true; setBusy(true);
    fetch(COMMAND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: cmd, value: value })
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (res) {
      if (!res.ok || res.j.ok === false) throw new Error(res.j.error || "request failed");
      toast("✓ " + (res.j.message || cmd));
      if (res.j.state) render(res.j);
    }).catch(function (e) {
      toast("⚠ " + e.message, true);
      poll();
    }).then(function () {
      inflight = false; setBusy(false);
    });
  }

  /* ---------- charts ---------- */
  function makeChart(id, color, min, max) {
    charts[id] = new Chart($(id).getContext("2d"), {
      type: "line",
      data: {
        labels: [],
        datasets: [{
          data: [], borderColor: color, borderWidth: 2, pointRadius: 0, tension: 0.3, fill: true,
          backgroundColor: function (c) {
            var ch = c.chart, a = ch.chartArea;
            if (!a) return color + "33";
            var g = ch.ctx.createLinearGradient(0, a.top, 0, a.bottom);
            g.addColorStop(0, color + "66"); g.addColorStop(1, color + "00");
            return g;
          }
        }]
      },
      options: {
        animation: false, responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { display: false },
          y: { min: min, max: max, ticks: { color: "#8b8ba7", maxTicksLimit: 3, font: { size: 9 } },
               grid: { color: "rgba(255,255,255,.06)" }, border: { display: false } }
        }
      }
    });
  }

  function drawCharts(h) {
    var labels = h.map(function (_, i) { return i; });
    var series = {
      tempChart: h.map(function (p) { return p.temp; }),
      energyChart: h.map(function (p) { return p.energy; }),
      powerChart: h.map(function (p) { return p.power; })
    };
    Object.keys(series).forEach(function (id) {
      var c = charts[id];
      if (!c) return;
      c.data.labels = labels;
      c.data.datasets[0].data = series[id];
      c.update("none");
    });
    if (h.length) {
      var l = h[h.length - 1];
      $("cTemp").textContent = l.temp.toFixed(1) + "°";
      $("cEnergy").textContent = l.energy.toFixed(3);
      $("cPower").textContent = Math.round(l.power) + "%";
    }
  }

  /* ---------- render ---------- */
  function render(st) {
    lastState = st;

    $("temp").textContent = st.temperature.toFixed(1);
    $("energy").textContent = st.energy.toFixed(3);
    $("power").textContent = Math.round(st.power);
    $("timer").textContent = fmtTime(st.remaining);

    $("tempBar").style.width = Math.min(100, st.temperature / 130 * 100) + "%";
    $("energyBar").style.width = st.energy_pct + "%";
    $("powerBar").style.width = st.power + "%";
    $("progBar").style.width = (st.progress * 100) + "%";

    var sb = $("stateBadge");
    sb.textContent = st.state;
    sb.className = "badge rounded-pill state-badge st-" + st.state;
    $("modeBadge").textContent = st.mode;

    document.querySelectorAll("[data-food]").forEach(function (c) { c.classList.toggle("on", c.dataset.food === st.food); });
    document.querySelectorAll("[data-mode]").forEach(function (c) { c.classList.toggle("on", c.dataset.mode === st.mode); });

    $("pressureTxt").textContent = st.pressure ? "on" : "off";
    $("pressureBtn").classList.toggle("on", !!st.pressure);

    // sliders follow the server unless the user is dragging one
    if (document.activeElement !== $("powerSlider")) {
      $("powerSlider").value = Math.round(st.power);
      $("powerVal").textContent = Math.round(st.power) + "%";
    }
    if (document.activeElement !== $("tempSlider")) {
      $("tempSlider").value = Math.round(st.target_temp);
      $("tempVal").textContent = Math.round(st.target_temp) + "°";
    }
    if (document.activeElement !== $("speedSlider")) {
      $("speedSlider").value = Math.round(st.sim_speed);
      $("speedVal").textContent = Math.round(st.sim_speed) + "x";
    }

    if (st.links && st.links.lan) {
      $("lanUrl").textContent = st.links.lan;
      var q = $("qrImg");
      if (!q.dataset.set) {
        q.src = QR_URL + "?url=" + encodeURIComponent(st.links.lan);
        q.dataset.set = "1";
      }
    }

    if (!SIMPLE) drawCharts(st.history || []);

    if (st.ready && !readyShown) {
      readyShown = true;
      var r = st.ready_reason;
      $("readyReason").textContent = r ? r.charAt(0).toUpperCase() + r.slice(1) + "." : "Cook complete.";
      readyModal.show();
      if (navigator.vibrate) navigator.vibrate([200, 100, 200]);
    }
    if (!st.ready) readyShown = false;
  }

  /* ---------- polling ---------- */
  function setOnline(on) {
    $("netDot").className = "bi bi-circle-fill me-1 " + (on ? "text-success" : "text-danger");
    $("netTxt").textContent = on ? "live" : "offline";
  }

  function poll() {
    if (document.hidden) return;   // save phone battery
    fetch(STATE_URL, { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) { render(j); setOnline(true); })
      .catch(function () { setOnline(false); });
  }

  /* ---------- init ---------- */
  function init() {
    buildChips();

    $("startBtn").addEventListener("click", function () { send("start"); });
    $("stopBtn").addEventListener("click", function () { send("stop"); });
    $("resetBtn").addEventListener("click", function () { send("reset"); });
    $("pressureBtn").addEventListener("click", function () {
      send("pressure", !(lastState && lastState.pressure));
    });

    [["powerSlider", "powerVal", "%", "power"],
     ["tempSlider", "tempVal", "°", "target"],
     ["speedSlider", "speedVal", "x", "speed"]].forEach(function (a) {
      var s = $(a[0]);
      s.addEventListener("input", function () { $(a[1]).textContent = s.value + a[2]; });
      s.addEventListener("change", function () { send(a[3], Number(s.value)); s.blur(); });
    });

    if (SIMPLE) {
      $("charts").classList.add("d-none");
      $("simpleNote").classList.remove("d-none");
    } else {
      makeChart("tempChart", "#e94560", 20, 130);
      makeChart("energyChart", "#f1c40f", 0, 0.5);
      makeChart("powerChart", "#2ecc71", 0, 100);
    }

    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });

    poll();
    setInterval(poll, POLL_MS);

    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register(SW_URL).catch(function () {});
    }
  }

  init();
})();
