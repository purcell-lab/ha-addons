"use strict";
// Relative URLs so Home Assistant Ingress path prefixes work.
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) => (typeof v === "number" && isFinite(v)) ? v.toLocaleString("en-AU", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–";

function cell(row, text, cls) { const td = row.insertCell(); td.textContent = text; if (cls) td.className = cls; return td; }

const SVG = "http://www.w3.org/2000/svg";
function icon(name) {
  const svg = document.createElementNS(SVG, "svg"); svg.setAttribute("class", "icon"); svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG, "use"); use.setAttribute("href", "#i-" + name);
  svg.append(use); return svg;
}
// Sign class: positive is import/charging (green), negative export/discharge (blue).
const tone = (w, dead = 50) => (typeof w !== "number" || !isFinite(w)) ? "idle" : w > dead ? "pos" : w < -dead ? "neg" : "idle";
// Signed text so meaning never depends on colour alone.
const signed = (v, d = 0) => (typeof v === "number" && isFinite(v)) ? (v > 0 ? "+" : v < 0 ? "\u2212" : "") + fmt(Math.abs(v), d) : "\u2013";

// items: [label, value, iconName, toneClass]
function setLive(items) {
  $("live").replaceChildren(...items.map(([label, value, name, cls]) => {
    const div = document.createElement("div"); div.className = "chip " + (cls || "idle");
    const text = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    text.append(dt, dd); div.append(icon(name || "state"), text); return div;
  }));
}

// Power bar and two-minute trend (client-side history at the refresh rate).
const history = [];
const HISTORY_S = 120;
function drawPower(w, kw) {
  const max = (kw || 11) * 1000;
  const frac = typeof w === "number" && isFinite(w) ? Math.max(-1, Math.min(1, w / max)) : 0;
  const half = 100 * Math.abs(frac);
  $("barpos").setAttribute("width", frac > 0 ? half : 0);
  $("barneg").setAttribute("x", frac < 0 ? 100 - half : 100);
  $("barneg").setAttribute("width", frac < 0 ? half : 0);
  const now = Date.now() / 1000;
  history.push([now, typeof w === "number" && isFinite(w) ? w : null]);
  while (history.length && history[0][0] < now - HISTORY_S) history.shift();
  const pts = history.filter(([, v]) => v !== null).map(([t, v]) =>
    [240 * (1 - (now - t) / HISTORY_S), 30 - 28 * Math.max(-1, Math.min(1, v / max))]);
  const line = pts.map(([x, y]) => x.toFixed(1) + "," + y.toFixed(1)).join(" ");
  $("sparkline").setAttribute("points", line);
  const area = (keep) => pts.length ? [[pts[0][0], 30], ...pts.map(([x, y]) => [x, keep(y) ? y : 30]), [pts[pts.length - 1][0], 30]]
    .map(([x, y]) => x.toFixed(1) + "," + y.toFixed(1)).join(" ") : "";
  $("sparkpos").setAttribute("points", area((y) => y < 30));
  $("sparkneg").setAttribute("points", area((y) => y > 30));
}

let lastDirection = "";
function announce(direction) {
  if (direction !== lastDirection) { $("livestatus").textContent = "Direction: " + direction; lastDirection = direction; }
}

function signedCell(row, v, unit) {
  const td = cell(row, v != null ? signed(v) + unit : "\u2013", "num");
  const t = tone(v, 0); if (t !== "idle") td.classList.add("v-" + t);
  return td;
}

function val(entry) { return entry && entry.age_s < 15 ? entry.value : null; }

async function refreshStatus() {
  let s;
  try {
    const r = await fetch("api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    s = await r.json();
  } catch (e) {
    $("conn").textContent = "Status unavailable"; $("conn").className = "badge bad";
    setLive([]); drawPower(null); return;
  }
  const app = s.app || {};
  const conn = val(s.ocpp_connection);
  if (!app.csms_configured) { $("conn").textContent = "Disconnected (no CSMS URL)"; $("conn").className = "badge"; }
  else if (conn === "connected" && app.negotiated) { $("conn").textContent = "Connected: " + app.negotiated; $("conn").className = "badge ok"; }
  else { $("conn").textContent = "Not connected"; $("conn").className = "badge bad"; }
  $("ident").textContent = app.charge_point_id || "";
  $("offer").textContent = app.offered_subprotocols ? "Offers " + app.offered_subprotocols.join(", ") : "";

  const si = val(s.evse.session_info) || {};
  const pm = val(s.evse.powermeter) || {};
  const p = (pm.power_W || {}), e = (pm.energy_Wh_import || {}), x = (pm.energy_Wh_export || {});
  const i = (pm.current_A || {}), v = (pm.voltage_V || {});
  const w = typeof p.total === "number" ? p.total : null;
  const t = tone(w);
  const dir = w === null ? "\u2013" : t === "pos" ? "Charging" : t === "neg" ? "Discharging (V2G)" : "Idle";
  const dirIcon = t === "pos" ? "in" : t === "neg" ? "out" : "swap";
  const it = tone(typeof i.DC === "number" ? i.DC : null, 0.5);
  setLive([
    // EVerest reports "Charging" in both directions; the Direction chip carries the sign.
    ["State", si.state || "\u2013", "state", "idle"],
    ["Direction", dir, dirIcon, t],
    ["Power", signed(w) + " W", "bolt", t],
    ["Meter import", fmt(e.total, 1) + " Wh", "in", "pos"],
    ["Meter export", fmt(x.total, 1) + " Wh", "out", "neg"],
    ["DC voltage", fmt(v.DC, 1) + " V", "volt", "idle"],
    ["DC current", signed(i.DC, 1) + " A", "amp", it],
    ["Rated power", "\u00b1" + fmt(app.max_power_kw) + " kW", "gauge", "idle"],
  ]);
  drawPower(w, app.max_power_kw);
  announce(dir);

  const body = $("composite").tBodies[0]; body.replaceChildren();
  const cs = s.composite_schedule;
  if (cs && Array.isArray(cs.charging_schedule_period)) {
    for (const per of cs.charging_schedule_period) {
      const row = body.insertRow();
      cell(row, fmt(per.start_period), "num");
      const unit = " " + (cs.charging_rate_unit || "");
      signedCell(row, per.limit, unit);
      signedCell(row, per.discharge_limit, unit);
      signedCell(row, per.setpoint, unit);
    }
  } else { cell(body.insertRow(), "No schedule published yet").colSpan = 4; }
}

let lastJson = "";
async function refreshProfiles() {
  let d;
  try {
    const r = await fetch("api/profiles", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    d = await r.json();
  } catch (e) {
    $("txmeta").textContent = "Profile log unavailable; retrying."; $("txjson").textContent = ""; $("copy").disabled = true; return;
  }
  const tx = d.latest_tx_profile;
  if (tx) {
    const reply = tx.status ? "Station reply: " + tx.status : "Station reply: not yet recorded";
    $("txmeta").textContent = "Received " + tx.received + " (UTC), message " + tx.message_id + ". " + reply + ".";
    if (tx.payload) { lastJson = JSON.stringify(tx.payload, null, 2); $("txjson").textContent = lastJson; $("copy").disabled = false; }
    else { lastJson = ""; $("txjson").textContent = "Payload larger than 8 KiB (" + tx.payload_bytes + " bytes); see the App's OCPP message log."; $("copy").disabled = true; }
  } else { $("txmeta").textContent = "No TxProfile received yet."; $("txjson").textContent = ""; $("copy").disabled = true; }
  const body = $("recent").tBodies[0]; body.replaceChildren();
  for (const ev of d.recent || []) {
    const row = body.insertRow();
    const prof = (ev.payload && ev.payload.chargingProfile) || {};
    cell(row, String(ev.received).replace("T", " ").replace(/\.\d+Z$/, ""));
    cell(row, ev.status || "pending", "st-" + (ev.status || "pending"));
    cell(row, ev.action);
    cell(row, prof.chargingProfilePurpose || (ev.payload && ev.payload.chargingProfileCriteria ? "criteria" : "–"));
  }
  if (!(d.recent || []).length) cell(body.insertRow(), "None received").colSpan = 4;
}

for (const b of document.querySelectorAll("button[data-cmd]")) {
  b.addEventListener("click", async () => {
    b.disabled = true;
    try {
      const r = await fetch("api/ev/" + b.dataset.cmd, { method: "POST", headers: { "X-HA-EVerest": "1" } });
      $("cmdmsg").textContent = r.ok ? "Sent: " + b.textContent : "Command failed (" + r.status + ")";
    } catch (e) { $("cmdmsg").textContent = "Command failed"; }
    finally { b.disabled = false; refreshStatus(); }
  });
}

$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(lastJson); $("copy").textContent = "Copied"; }
  catch (e) { const sel = window.getSelection(); const range = document.createRange(); range.selectNodeContents($("txjson")); sel.removeAllRanges(); sel.addRange(range); $("copy").textContent = "Selected; press Ctrl+C"; }
  setTimeout(() => { $("copy").textContent = "Copy JSON"; }, 2500);
});

function showSelftest(t) {
  const badge = $("selftest");
  if (!t) { badge.textContent = "Not run yet"; badge.className = "badge muted"; return; }
  badge.textContent = (t.pass ? "Passed" : "Failed") + " (" + (t.source || "") + ", " + new Date(t.at * 1000).toLocaleTimeString("en-AU") + ")";
  badge.className = "badge " + (t.pass ? "ok" : "bad");
  const cap = (n) => { const c = (t.capture || {})[n]; if (!c) return "not captured"; if (!c.available) return "capture unavailable"; return c.count ? c.frames.map(f => f.direction + " " + f.sdp).join(", ") : "no SDP frames"; };
  const items = [["Unicast to charger", (t.unicast || {}).result || "–"], ["Multicast ff02::1", (t.multicast || {}).result || "–"],
                 ["Seen on v2g1 (EV)", cap("v2g1")], ["Seen on v2g0 (charger)", cap("v2g0")]];
  if (t.charger_sdp_blocked) items.push(["Charger", "Ignoring discovery: an earlier ISO 15118 session never closed. Restart the App."]);
  $("diagsum").replaceChildren(...items.map(([label, value]) => {
    const div = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    div.append(dt, dd); return div;
  }));
}

async function refreshDiagnostics() {
  try {
    const r = await fetch("api/diagnostics", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    showSelftest(d.selftest);
    $("diagjson").textContent = JSON.stringify(d.snapshot, null, 2);
  } catch (e) { $("diagjson").textContent = "Diagnostics unavailable; retrying."; }
}

$("runtest").addEventListener("click", async () => {
  $("runtest").disabled = true; $("selftest").textContent = "Running"; $("selftest").className = "badge muted";
  try {
    const r = await fetch("api/diag/selftest", { method: "POST", headers: { "X-HA-EVerest": "1" } });
    if (r.ok) showSelftest(await r.json()); else $("selftest").textContent = "Self-test request failed (" + r.status + ")";
  } catch (e) { $("selftest").textContent = "Self-test request failed"; }
  finally { $("runtest").disabled = false; refreshDiagnostics(); }
});

refreshStatus(); refreshProfiles(); refreshDiagnostics();
setInterval(refreshStatus, 1000); setInterval(refreshProfiles, 4000); setInterval(refreshDiagnostics, 15000);
