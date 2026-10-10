/* SPDX-License-Identifier: GPL-3.0-only
 * Native Status-page enhancement. No external assets, writes or OCPP commands.
 */
(() => {
  "use strict";
  const base = new URL("api/", window.location.href);
  let mounted = null;
  let busy = false;
  let cards = [];
  const node = (tag, text) => {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    return el;
  };
  function mount(root) {
    root.append(node("h3", "Last received TxProfile"));
    root.append(node("p", "Read-only diagnostic. Receipt does not prove acceptance or that this profile is active. Cleared when the simulator restarts."));
    cards = [1, 2].map(id => {
      const box = node("section");
      box.className = "txprofile-card";
      const header = node("div");
      header.className = "txprofile-heading";
      header.append(node("h4", `Connector ${id}`));
      const copy = node("button", "Copy JSON");
      copy.type = "button";
      copy.disabled = true;
      copy.setAttribute("aria-label", `Copy connector ${id} TxProfile JSON`);
      header.append(copy);
      const status = node("p", "Loading received profile…");
      status.setAttribute("role", "status");
      const pre = node("pre");
      pre.tabIndex = 0;
      pre.setAttribute("aria-label", `Connector ${id} received TxProfile JSON`);
      pre.hidden = true;
      box.append(header, status, pre);
      root.append(box);
      copy.onclick = async () => {
        try {
          await navigator.clipboard.writeText(pre.textContent);
          copy.textContent = "Copied";
        } catch (_) {
          pre.focus();
          const range = document.createRange();
          range.selectNodeContents(pre);
          window.getSelection().removeAllRanges();
          window.getSelection().addRange(range);
          copy.textContent = "JSON selected: copy manually";
        }
      };
      return {id, status, pre, copy};
    });
  }
  async function refresh() {
    const root = document.getElementById("txprofile-status");
    if (!root || document.hidden || busy) return;
    if (root !== mounted) {
      mounted = root;
      mount(root);
    }
    busy = true;
    try {
      await Promise.all(cards.map(async ({id, status, pre, copy}) => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 4000);
        try {
          const response = await fetch(new URL(`connector/${id}/txprofile`, base), {
            cache: "no-store", signal: controller.signal
          });
          if (!response.ok) throw new Error("unavailable");
          const data = await response.json();
          if (!root.isConnected) return;
          if (typeof data.received !== "boolean" ||
              !["empty", "captured", "too_large"].includes(data.captureStatus))
            throw new Error("invalid response");
          const json = data.captureStatus === "captured" && data.payload
            ? JSON.stringify(data.payload, null, 2) : "";
          if (pre.textContent !== json) {
            pre.textContent = json; // Never interpret CSMS-supplied values as HTML.
            copy.textContent = "Copy JSON";
          }
          pre.hidden = !json;
          copy.disabled = !json;
          status.textContent = !data.received
            ? "No TxProfile received since simulator restart."
            : data.captureStatus === "too_large"
              ? "TxProfile received, but exceeds the 4 KiB diagnostic display limit. OCPP processing is unchanged."
              : `Received ${data.receivedAt || "(time unavailable)"}. Acceptance not recorded; not an active-profile indicator.`;
        } catch (_) {
          if (!root.isConnected) return;
          status.textContent = "Unable to refresh received TxProfile. Retrying automatically.";
          pre.hidden = true;
          pre.textContent = "";
          copy.disabled = true;
        } finally {
          clearTimeout(timeout);
        }
      }));
    } finally {
      busy = false;
    }
  }
  refresh();
  setInterval(refresh, 2000);
})();
