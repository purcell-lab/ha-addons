"use strict";
// Relative URLs so Home Assistant Ingress path prefixes work.
const $ = (id) => document.getElementById(id);
const fmt = (v, d = 0) => (typeof v === "number" && isFinite(v)) ? v.toLocaleString("en-AU", { maximumFractionDigits: d, minimumFractionDigits: d }) : "–";

function cell(row, text, cls) { const td = row.insertCell(); td.textContent = text; if (cls) td.className = cls; return td; }

function setLive(items) {
  const dl = $("live");
  dl.replaceChildren(...items.map(([label, value]) => {
    const div = document.createElement("div");
    const dt = document.createElement("dt"); dt.textContent = label;
    const dd = document.createElement("dd"); dd.textContent = value;
    div.append(dt, dd); return div;
  }));
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
    setLive([]); return;
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
  const lim = val(s.evse.limits) || {};
  const p = (pm.power_W || {}), e = (pm.energy_Wh_import || {}), i = (pm.current_A || {}), v = (pm.voltage_V || {});
  setLive([
    ["State", si.state || "–"],
    ["Power", fmt(p.total) + " W"],
    ["Session energy", fmt(si.charged_energy_wh) + " Wh"],
    ["Meter import", fmt(e.total) + " Wh"],
    ["Current L1", fmt(i.L1, 1) + " A"],
    ["Voltage L1", fmt(v.L1, 1) + " V"],
    ["EVSE current limit", fmt(lim.max_current, 2) + " A"],
    ["Phases available", fmt(lim.nr_of_phases_available)],
  ]);

  const body = $("composite").tBodies[0]; body.replaceChildren();
  const cs = s.composite_schedule;
  if (cs && Array.isArray(cs.charging_schedule_period)) {
    for (const per of cs.charging_schedule_period) {
      const row = body.insertRow();
      cell(row, fmt(per.start_period), "num");
      cell(row, fmt(per.limit) + " " + (cs.charging_rate_unit || ""), "num");
      cell(row, per.number_phases != null ? String(per.number_phases) : "–", "num");
    }
  } else { cell(body.insertRow(), "No schedule published yet").colSpan = 3; }
  showPrice(s.session_cost);
}

// Dynamic pricing: session cost (CostUpdated / California Pricing) and the
// price schedule of the last charging profile (information only).
const money = (v, cur) => (typeof v === "number" && isFinite(v)) ? v.toLocaleString("en-AU", { minimumFractionDigits: 2, maximumFractionDigits: 4 }) + (cur ? " " + cur : "") : "–";
const utc = (t) => t ? String(t).replace("T", " ").replace(/(\.\d+)?(Z|[+-]00:00)$/, "") : "–";
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
    ["Next from (UTC)", utc(p.next_at)],
    ["Status", p.status || "–"],
    ["Cost time (UTC)", utc(p.timestamp)],
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
    (s.time_anchor ? ", time anchor " + s.time_anchor : "")).join("; ") +
    ". Information only: EVerest stores the schedule but does not act on it.";
  for (const s of list) for (const it of s.intervals) {
    const row = body.insertRow();
    cell(row, it.start ? utc(it.start) : "+" + duration(it.offset_s));
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
    cell(row, utc(ev.received));
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
    $("txmeta").textContent = what + "Received " + tx.received + " (UTC), message " + tx.message_id + ". " + reply + ".";
    if (tx.payload) { lastJson = JSON.stringify(tx.payload, null, 2); $("txjson").textContent = lastJson; $("copy").disabled = false; }
    else { lastJson = ""; $("txjson").textContent = "Payload larger than 8 KiB (" + tx.payload_bytes + " bytes); see the App's OCPP message log."; $("copy").disabled = true; }
  } else { $("txmeta").textContent = "No charging profile received yet."; $("txjson").textContent = ""; $("copy").disabled = true; }
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
  showPriceSchedules(d.price_schedules);
  showPricing(d.pricing);
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

refreshStatus(); refreshProfiles();
setInterval(refreshStatus, 2000); setInterval(refreshProfiles, 4000);
