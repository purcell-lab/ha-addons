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

// Protocol tags: kind "ocpp" (OCPP 2.1 names) or "iso" (ISO 15118-20 names).
function tag(text, kind) {
  const code = document.createElement("code"); code.className = "tag " + (kind || "ocpp"); code.textContent = text;
  return code;
}

// items: [label, value, iconName, toneClass, ocppTags]
function setLive(items) {
  $("live").replaceChildren(...items.map(([label, value, name, cls, tags]) => {
    const div = document.createElement("div"); div.className = "chip " + (cls || "idle");
    const text = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    text.append(dt, dd);
    if (tags && tags.length) { const t = document.createElement("div"); t.className = "chip-tags"; t.append(...tags.map((x) => tag(x))); text.append(t); }
    div.append(icon(name || "state"), text); return div;
  }));
}

// Security Profile chip: 0 and 1 red (no TLS), 2 amber (TLS, password), 3+ green (mutual TLS).
const SECURITY = {
  0: ["sp-bad", "no authentication"], 1: ["sp-bad", "Basic Auth, unencrypted"],
  2: ["sp-warn", "TLS + Basic Auth"], 3: ["sp-ok", "TLS + client certificate"],
};
function showSecurity(app) {
  const el = $("security"), p = app.security_profile;
  if (p === null || p === undefined) { el.hidden = true; return; }
  const [cls, what] = SECURITY[p] || (p >= 3 ? SECURITY[3] : ["sp-bad", "unknown"]);
  el.className = "pill " + cls; el.hidden = false; el.replaceChildren(icon("shield"));
  el.append("Security Profile " + p + ": " + what + (app.csms_scheme ? " (" + app.csms_scheme + "://" +
    (app.csms_trust ? ", trust " + app.csms_trust : "") + ")" : ""));
  el.title = "OCPP SecurityCtrlr.SecurityProfile " + p;
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

// EV watchdog (issue #33): the EV gave up its ISO 15118 session while plugged in.
function showWatchdog(wd) {
  const el = $("evwatch"), last = (wd && wd.last_recovery) || null;
  const when = last ? new Date(last.at * 1000).toLocaleTimeString("en-AU") : "";
  let text = "";
  if (wd && wd.ev_session === "recovering") text = "The simulated EV gave up waiting. Unplugging and plugging it in again automatically.";
  else if (wd && wd.ev_session === "gave_up") text = "The simulated EV gave up its ISO 15118 session while plugged in" + (last && last.result !== "re-plugged" ? " (" + last.result + ", " + when + ")" : "") + ". If this stays, unplug and plug in.";
  else if (last) text = "Last EV watchdog action at " + when + ": " + last.result + ".";
  el.textContent = text; el.hidden = !text;
  el.className = wd && wd.ev_session !== "ok" ? "alert" : "note";
}

async function refreshStatus() {
  let s;
  try {
    const r = await fetch("api/status", { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    s = await r.json();
  } catch (e) {
    $("conn").textContent = "Status unavailable"; $("conn").className = "pill bad";
    setLive([]); drawPower(null); return;
  }
  const app = s.app || {};
  const conn = val(s.ocpp_connection);
  if (!app.csms_configured) { $("conn").textContent = "Disconnected (no CSMS URL)"; $("conn").className = "pill"; }
  else if (conn === "connected" && app.negotiated) { $("conn").textContent = "Connected: " + app.negotiated; $("conn").className = "pill ok"; }
  else { $("conn").textContent = "Not connected"; $("conn").className = "pill bad"; }
  $("ident").textContent = app.charge_point_id || "";
  $("offer").textContent = app.offered_subprotocols ? "Offers " + app.offered_subprotocols.join(", ") : "";
  showSecurity(app);
  const np = $("needspill"); np.hidden = !app.csms_configured;
  np.textContent = "NotifyEVChargingNeeds " + (app.ev_charging_needs ? "on" : "off");
  np.className = "pill " + (app.ev_charging_needs ? "ok" : "muted");

  const si = val(s.evse.session_info) || {};
  const pm = val(s.evse.powermeter) || {};
  const p = (pm.power_W || {}), e = (pm.energy_Wh_import || {}), x = (pm.energy_Wh_export || {});
  const i = (pm.current_A || {}), v = (pm.voltage_V || {});
  const w = typeof p.total === "number" ? p.total : null;
  const t = tone(w);
  const dir = w === null ? "\u2013" : t === "pos" ? "Charging" : t === "neg" ? "Discharging (V2G)" : "Idle";
  const dirIcon = t === "pos" ? "in" : t === "neg" ? "out" : "swap";
  const it = tone(typeof i.DC === "number" ? i.DC : null, 0.5);
  const ev = s.ev || {};
  setLive([
    // EVerest reports "Charging" in both directions; the Direction chip carries the sign.
    ["State", si.state || "\u2013", "state", "idle"],
    ["Direction", dir, dirIcon, t],
    ["Power", signed(w) + " W", "bolt", t, [w < 0 ? "Power.Active.Export" : "Power.Active.Import"]],
    ["Meter import", fmt(e.total, 1) + " Wh", "in", "pos", ["Energy.Active.Import.Register"]],
    ["Meter export", fmt(x.total, 1) + " Wh", "out", "neg", ["Energy.Active.Export.Register"]],
    ["DC voltage", fmt(v.DC, 1) + " V", "volt", "idle", ["Voltage"]],
    ["DC current", signed(i.DC, 1) + " A", "amp", it, [typeof i.DC === "number" && i.DC < 0 ? "Current.Export" : "Current.Import"]],
    ["EV SoC", typeof ev.soc === "number" ? fmt(ev.soc, 1) + " %" : "\u2013", "battery", "idle", ["SoC"]],
    ["Rated power", "\u00b1" + fmt(app.max_power_kw) + " kW", "gauge", "idle"],
    ...priceChips(s.session_cost),
  ]);
  drawPower(w, app.max_power_kw);
  announce(dir);
  showWatchdog(s.ev_watchdog);

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
  showPrice(s.session_cost);
  showDer(s.der);
  showEv(ev, si, app);
}

// OCPP 2.1 DER control: the active set the CSMS's controls produce, as
// recorded by the App's grid_support module. Recorded only, never applied.
function showDer(der) {
  const body = $("deractive").tBodies[0]; body.replaceChildren();
  if (!der) {
    $("dermeta").textContent = "No DER capability declared yet (EVerest starting, or OCPP 2.0.1).";
    cell(body.insertRow(), "None").colSpan = 5; return;
  }
  const n = (der.control_types || []).length;
  $("dermeta").textContent = "Declared: DC, " + n + " control types. Active set updated " +
    (der.active_at ? new Date(der.active_at * 1000).toLocaleTimeString("en-AU", { hour12: false }) : "never") +
    "; forwarded to the ISO 15118-20 charger: " + (der.relay || "–") + ". Not applied to power.";
  for (const d of der.active || []) {
    const row = body.insertRow();
    cell(row, d.type || "–"); cell(row, d.id || "–"); cell(row, d.priority === undefined ? "–" : String(d.priority), "num");
    cell(row, d.is_default ? "default" : (d.start_time ? local(d.start_time) : "now") + (d.duration_s ? " for " + duration(d.duration_s) : ""));
    cell(row, d.detail || "–");
  }
  if (!(der.active || []).length) cell(body.insertRow(), "No active DER controls").colSpan = 5;
}

function showDerMessages(events) {
  const body = $("dermsgs").tBodies[0]; body.replaceChildren();
  for (const ev of events || []) {
    const row = body.insertRow();
    const p = ev.payload || {};
    cell(row, local(ev.received));
    cell(row, ev.status || "pending", "st-" + (ev.status || "pending"));
    cell(row, ev.action);
    cell(row, [p.controlType, p.controlId, p.isDefault ? "default" : null].filter(Boolean).join(", ") || "–");
  }
  if (!(events || []).length) cell(body.insertRow(), "None received").colSpan = 4;
}

// Dynamic pricing: session cost (CostUpdated / California Pricing) and the
// price schedule of the last charging profile (information only).
const money = (v, cur) => (typeof v === "number" && isFinite(v)) ? v.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + (cur ? " " + cur : "") : "–";
// Times in the browser's time zone (AEDT at the Canberra Plugfest), with the zone shown.
const local = (t, opts) => {
  const d = t ? new Date(t) : null;
  if (!d || isNaN(d)) return t ? String(t) : "–";
  return d.toLocaleString("en-AU", { hour12: false, timeZoneName: "short", ...(opts || { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" }) });
};
const clock = (t) => local(t, { hour: "2-digit", minute: "2-digit" });

// Live-reading chips for the latest session cost: price now, and the next price with its start.
function priceChips(entry) {
  const p = entry && entry.value;
  const cur = (p && p.currency) || "";
  const now = p && p.kwh_price != null ? money(p.kwh_price, cur) + "/kWh" : "\u2013";
  const next = p && p.next_kwh_price != null ? money(p.next_kwh_price) + (p.next_at ? " from " + clock(p.next_at) : "") : "\u2013";
  return [["Price now", now, "price", "idle", ["CostUpdated customData"]],
          ["Next price", next, "price", "idle", ["CostUpdated customData"]],
          ["Total cost", p && p.total_cost != null ? money(p.total_cost, cur) : "\u2013", "price", "idle", ["totalCost"]]];
}
const duration = (s) => typeof s !== "number" ? "–" : s % 3600 === 0 ? fmt(s / 3600) + " h" : s % 60 === 0 ? fmt(s / 60) + " min" : fmt(s) + " s";

function setGrid(el, items) {
  el.replaceChildren(...items.map(([label, value]) => {
    const div = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    div.append(dt, dd); return div;
  }));
}

function showPrice(entry) {
  const p = entry && entry.value;
  if (!p) { setGrid($("price"), []); $("pricetext").hidden = true; return; }
  const cur = p.currency || "";
  const items = [
    ["Total cost", money(p.total_cost, cur)],
    ["Price now", p.kwh_price != null ? money(p.kwh_price, cur) + "/kWh" : "–"],
    ["Next price", p.next_kwh_price != null ? money(p.next_kwh_price, cur) + "/kWh" : "–"],
    ["Next from", local(p.next_at)],
    ["Status", p.status || "–"],
    ["Cost time", local(p.timestamp)],
  ];
  if (p.hour_price != null) items.splice(2, 0, ["Time price", money(p.hour_price, cur) + "/h"]);
  setGrid($("price"), items);
  $("pricemeta").textContent = "Latest session cost from EVerest" + (p.session_id ? " for transaction " + p.session_id : "") +
    ", received " + fmt(entry.age_s) + " s ago. Shown only; the price does not change charging.";
  $("pricetext").textContent = p.text ? "Price text: " + p.text : "";
  $("pricetext").hidden = !p.text;
}

function schedulePrice(sched, it) {
  if (sched.kind === "absolutePriceSchedule") return it.energy_fee != null ? money(it.energy_fee, sched.currency) + "/kWh" + (it.rules > 1 ? " (" + it.rules + " power ranges)" : "") : "–";
  const level = it.price_level != null ? "Level " + it.price_level + (sched.number_of_price_levels ? " of " + sched.number_of_price_levels : "") : "–";
  return it.cost != null ? level + ", cost " + it.cost : level;
}

function showPriceSchedules(list) {
  const body = $("pricesched").tBodies[0]; body.replaceChildren();
  if (!list || !list.length) {
    $("schedmeta").textContent = "No price schedule in the last charging profile.";
    cell(body.insertRow(), "None").colSpan = 3; return;
  }
  $("schedmeta").textContent = list.map((s) => s.kind + (s.id != null ? " #" + s.id : "") +
    (s.description ? " “" + s.description + "”" : "") + ": " + s.count + " interval" + (s.count === 1 ? "" : "s") +
    (s.count > s.intervals.length ? ", first " + s.intervals.length + " shown" : "") +
    (s.time_anchor ? ", time anchor " + local(s.time_anchor) : "")).join("; ") +
    ". Information only: EVerest stores the schedule but does not act on it.";
  for (const s of list) for (const it of s.intervals) {
    const row = body.insertRow();
    cell(row, it.start ? local(it.start) : "+" + duration(it.offset_s));
    cell(row, duration(it.duration_s), "num");
    cell(row, schedulePrice(s, it), "num");
  }
}

function pricingDetail(ev) {
  if (ev.status === "CallError") return (ev.status_info && ev.status_info.reasonCode) || "CALLERROR";
  const p = ev.payload || {};
  if (ev.action === "CostUpdated") return "Total " + p.totalCost + ", transaction " + p.transactionId + (p.customData ? ", with customData" : "");
  if (ev.action === "SetDefaultTariff" && p.tariff) return "Tariff " + (p.tariff.tariffId || "") + ", EVSE " + p.evseId;
  return ev.status_info && ev.status_info.reasonCode ? ev.status_info.reasonCode : "–";
}

function showPricing(events) {
  const body = $("pricing").tBodies[0]; body.replaceChildren();
  for (const ev of events || []) {
    const row = body.insertRow();
    cell(row, local(ev.received));
    cell(row, ev.status || "pending", "st-" + (ev.status || "pending"));
    cell(row, ev.action);
    cell(row, pricingDetail(ev));
  }
  if (!(events || []).length) cell(body.insertRow(), "None received").colSpan = 4;
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
  const tx = d.latest_profile || d.latest_tx_profile;
  if (tx) {
    const reply = tx.status ? "Station reply: " + tx.status : "Station reply: not yet recorded";
    const cp = (tx.payload && tx.payload.chargingProfile) || {};
    const what = cp.chargingProfilePurpose ? cp.chargingProfilePurpose + " #" + cp.id + ", stack level " + cp.stackLevel + ". " : "";
    const left = (tx.omitted || []).length ? " Shown without its " + tx.omitted.join(" and ") + " (" + fmt(tx.payload_bytes / 1024, 1) + " KiB in full); the price schedule is summarised in the Price panel." : "";
    $("txmeta").textContent = what + "Received " + local(tx.received) + ", message " + tx.message_id + ". " + reply + "." + left;
    $("txpurpose").textContent = cp.chargingProfilePurpose || "TxProfile";
    showProfileSummary(cp);
    if (tx.payload) { lastJson = JSON.stringify(tx.payload, null, 2); $("txjson").textContent = lastJson; $("copy").disabled = false; }
    else { lastJson = ""; $("txjson").textContent = "Payload larger than 8 KiB (" + tx.payload_bytes + " bytes); see the App's OCPP message log."; $("copy").disabled = true; }
  } else { $("txmeta").textContent = "No charging profile received yet."; $("txjson").textContent = ""; $("copy").disabled = true; }
  const body = $("recent").tBodies[0]; body.replaceChildren();
  for (const ev of d.recent || []) {
    const row = body.insertRow();
    const prof = (ev.payload && ev.payload.chargingProfile) || {};
    cell(row, local(ev.received));
    cell(row, ev.status || "pending", "st-" + (ev.status || "pending"));
    cell(row, ev.action);
    cell(row, prof.chargingProfilePurpose || (ev.payload && ev.payload.chargingProfileCriteria ? "criteria" : "–"));
  }
  if (!(d.recent || []).length) cell(body.insertRow(), "None received").colSpan = 4;
  showPriceSchedules(d.price_schedules);
  showPricing(d.pricing);
  showDerMessages(d.der);
  showNeedsMessages(d.charging_needs);
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
  if (!t) { badge.textContent = "Not run yet"; badge.className = "pill muted"; return; }
  badge.textContent = (t.pass ? "Passed" : "Failed") + " (" + (t.source || "") + ", " + new Date(t.at * 1000).toLocaleTimeString("en-AU") + ")";
  badge.className = "pill " + (t.pass ? "ok" : "bad");
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
  $("runtest").disabled = true; $("selftest").textContent = "Running"; $("selftest").className = "pill muted";
  try {
    const r = await fetch("api/diag/selftest", { method: "POST", headers: { "X-HA-EVerest": "1" } });
    if (r.ok) showSelftest(await r.json()); else $("selftest").textContent = "Self-test request failed (" + r.status + ")";
  } catch (e) { $("selftest").textContent = "Self-test request failed"; }
  finally { $("runtest").disabled = false; refreshDiagnostics(); }
});


// ---- Simulated EV: SoC, charging needs and the ISO 15118-20 session ----
const pct = (v) => (typeof v === "number" && isFinite(v)) ? fmt(v) + " %" : "–";
const wh = (v) => (typeof v === "number" && isFinite(v)) ? signed(v) + " Wh" : "–";
const span = (s) => typeof s !== "number" ? "–" : s >= 3600 ? fmt(Math.floor(s / 3600)) + " h " + fmt(Math.floor(s % 3600 / 60)) + " min" : fmt(Math.round(s / 60)) + " min";

function kv(el, items) {
  el.replaceChildren(...items.map(([label, value, tags]) => {
    const div = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = label;
    for (const [text, kind] of tags || []) dt.append(" ", tag(text, kind));
    const dd = document.createElement("dd"); dd.textContent = value;
    div.append(dt, dd); return div;
  }));
}

function showEv(ev, si, app) {
  const iso = ev.iso20 || {}, needs = ev.needs || {}, info = (ev.ev_info && ev.ev_info.value) || {};
  const soc = typeof ev.soc === "number" ? ev.soc : null;
  $("socvalue").textContent = soc === null ? "–" : fmt(soc, 1);
  $("socfill").style.width = (soc || 0) + "%";
  $("socmeter").setAttribute("aria-valuenow", soc === null ? 0 : Math.round(soc));
  const floor = iso.min_soc, target = iso.target_soc;
  $("socmin").style.left = (floor || 0) + "%"; $("socmin").hidden = typeof floor !== "number";
  $("soctarget").style.left = (target || 0) + "%"; $("soctarget").hidden = typeof target !== "number";
  $("soclegend").textContent = "minimum " + pct(floor) + ", target " + pct(target);
  $("socnote").textContent = ev.in_session
    ? "Battery model: " + fmt((ev.capacity_wh || 0) / 1000) + " kWh, from the charger's import and export meter since plug-in."
    : "Unplugged: the EV plugs in at " + pct(needs.start_soc) + ".";

  if (!needsDirty) fillNeeds(needs);
  const proto = (ev.selected_protocol && ev.selected_protocol.value) || "";
  kv($("isostatus"), [
    ["Protocol", proto || "none yet"],
    ["Energy service", "DC_BPT (bidirectional DC)", [["SelectedEnergyService", "iso"]]],
    ["Control mode", "Dynamic: the charger sets the target", [["ControlMode", "iso"]]],
    ["Transport", "TLS 1.3, mutual (EV certificate)"],
    ["EVCCID", info.evcc_id || "–", [["EVCCID", "iso"]]],
    ["EVSE state", si.state || "–"],
    ["SoC at the charger", pct(info.soc), [["PresentSOC", "iso"]]],
    ["EV maximum voltage", typeof info.maximum_voltage_limit === "number" ? fmt(info.maximum_voltage_limit) + " V" : "–", [["EVMaximumVoltage", "iso"]]],
  ]);

  const departure = typeof iso.departure_time === "number" ? span(iso.departure_time) +
    " (" + local((iso.at + iso.departure_time) * 1000, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) + ")" : "–";
  const rows = [
    ["DepartureTime", "departureTime", departure],
    ["TargetSOC", "v2xChargingParameters.targetSoC", pct(iso.target_soc)],
    ["MinimumSOC", "(in evMinEnergyRequest)", pct(iso.min_soc)],
    ["PresentSOC", "dcChargingParameters.stateOfCharge", pct(iso.present_soc)],
    ["EVTargetEnergyRequest", "evTargetEnergyRequest", wh(iso.target_wh)],
    ["EVMaximumEnergyRequest", "evMaxEnergyRequest", wh(iso.max_wh)],
    ["EVMinimumEnergyRequest", "evMinEnergyRequest", wh(iso.min_wh)],
    ["EVMinimumV2XEnergyRequest", "evMinV2XEnergyRequest", iso.v2x_min_wh == null ? "none (no discharge window)" : wh(iso.v2x_min_wh)],
    ["EVMaximumV2XEnergyRequest", "evMaxV2XEnergyRequest", iso.v2x_max_wh == null ? "none" : wh(iso.v2x_max_wh)],
    ["EVMaximumDischargePower", "maxDischargePower", typeof iso.max_discharge_w === "number" ? fmt(iso.max_discharge_w) + " W" : "–"],
    ["EVMaximumDischargeCurrent", "maxDischargeCurrent", typeof iso.max_discharge_a === "number" ? fmt(iso.max_discharge_a) + " A" : "–"],
    ["RemainingTimeToTargetSOC", "–", span(iso.remaining_time_to_target_soc)],
    ["BatteryEnergyCapacity", "dcChargingParameters.evEnergyCapacity", typeof iso.battery_capacity_wh === "number" ? fmt(iso.battery_capacity_wh) + " Wh" : "–"],
  ];
  const body = $("evsends").tBodies[0]; body.replaceChildren();
  for (const [isoName, ocppName, value] of rows) {
    const row = body.insertRow();
    row.insertCell().append(tag(isoName, "iso"));
    const oc = row.insertCell(); if (ocppName.startsWith("(") || ocppName === "–") oc.textContent = ocppName; else oc.append(tag(ocppName));
    cell(row, value, "num");
  }
  $("needsmeta").textContent = app.ev_charging_needs
    ? "The station forwards these needs to the CSMS in NotifyEVChargingNeeds (App option ev_charging_needs). On OCPP 2.1 a Rejected reply ends the transaction (ReqEnergyTransferRejected)."
    : "Not forwarded: the App option ev_charging_needs is off, so the needs reach the charger over ISO 15118-20 only.";
}

function showNeedsMessages(events) {
  const body = $("needsmsgs").tBodies[0]; body.replaceChildren();
  for (const ev of events || []) {
    const row = body.insertRow(), n = (ev.payload && ev.payload.chargingNeeds) || {};
    cell(row, local(ev.received));
    cell(row, ev.status || "pending", "st-" + (ev.status || "pending"));
    cell(row, n.requestedEnergyTransfer || "–");
    const v = n.v2xChargingParameters || {};
    cell(row, [n.controlMode, v.targetSoC != null ? "targetSoC " + v.targetSoC + " %" : null,
      n.departureTime ? "departure " + local(n.departureTime) : null].filter(Boolean).join(", ") || "–");
  }
  if (!(events || []).length) cell(body.insertRow(), "None sent").colSpan = 4;
}

function showProfileSummary(cp) {
  const sched = (Array.isArray(cp.chargingSchedule) ? cp.chargingSchedule[0] : cp.chargingSchedule) || {};
  const periods = sched.chargingSchedulePeriod || [];
  const modes = [...new Set(periods.map((p) => p.operationMode).filter(Boolean))];
  kv($("txsummary"), [
    ["Purpose", cp.chargingProfilePurpose || "–", [["chargingProfilePurpose"]]],
    ["Profile", cp.id != null ? "#" + cp.id + ", stack level " + cp.stackLevel : "–", [["id"], ["stackLevel"]]],
    ["Kind", cp.chargingProfileKind || "–", [["chargingProfileKind"]]],
    ["Unit", sched.chargingRateUnit || "–", [["chargingRateUnit"]]],
    ["Periods", periods.length ? String(periods.length) : "–", [["chargingSchedulePeriod"]]],
    ["Operation mode", modes.join(", ") || "–", [["operationMode"]]],
  ]);
}

// Charging needs form. Kept as typed until applied or reset by a refresh.
let needsDirty = false;
const form = $("needsform");
function toLocalInput(epoch) {
  if (!epoch) return "";
  const d = new Date(epoch * 1000), p = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + "T" + p(d.getHours()) + ":" + p(d.getMinutes());
}
function modeFields() {
  const mode = form.elements.mode.value;
  for (const el of form.querySelectorAll("[data-mode]")) el.hidden = el.dataset.mode !== mode;
  form.elements.ready_by.required = mode === "charge_by";
  $("needshelp").textContent = mode === "charge_by"
    ? "Charge by: the EV asks to reach the target by the ready-by time. Its minimum SoC is the target, so it offers no discharge (EVMaximumDischargePower 0 W)."
    : "Allow discharge: the EV may be discharged down to the minimum SoC and stops offering discharge there. Ready by is optional (24 hours if empty).";
}
function fillNeeds(n) {
  if (!n || !n.mode) return;
  form.elements.mode.value = n.mode;
  form.elements.target_soc.value = n.target_soc;
  form.elements.min_soc.value = n.min_soc;
  form.elements.start_soc.value = n.start_soc;
  form.elements.ready_by.value = toLocalInput(n.ready_by);
  modeFields();
}
form.addEventListener("input", () => { needsDirty = true; });
form.addEventListener("change", modeFields);
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const f = form.elements, body = { mode: f.mode.value, target_soc: Number(f.target_soc.value), start_soc: Number(f.start_soc.value) };
  if (f.mode.value === "allow_discharge") body.min_soc = Number(f.min_soc.value);
  if (f.ready_by.value) body.ready_by = Math.floor(new Date(f.ready_by.value).getTime() / 1000);
  $("needsapply").disabled = true;
  try {
    const r = await fetch("api/ev/needs", { method: "POST", headers: { "X-HA-EVerest": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const reply = await r.json().catch(() => ({}));
    $("needsmsg").textContent = r.ok ? "Applied. The EV sends these needs from its next ISO 15118-20 message." : "Not applied: " + (reply.error || r.status);
    if (r.ok) needsDirty = false;
  } catch (e) { $("needsmsg").textContent = "Not applied: request failed"; }
  finally { $("needsapply").disabled = false; refreshStatus(); }
});

refreshStatus(); refreshProfiles(); refreshDiagnostics();
setInterval(refreshStatus, 1000); setInterval(refreshProfiles, 4000); setInterval(refreshDiagnostics, 15000);
