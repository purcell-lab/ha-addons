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

refreshStatus(); refreshProfiles();
setInterval(refreshStatus, 2000); setInterval(refreshProfiles, 4000);
