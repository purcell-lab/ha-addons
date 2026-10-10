/* Focused browser QA against the built HTML, with synthetic HTTP responses only.
 * Usage: node txprofile_ui.cjs /path/to/bundle.html /optional/screenshots
 * Requires playwright@1.56.0 and its Chromium; no live HA or OCPP connection.
 */
const {chromium} = require("playwright");
const fs = require("node:fs");
const assert = require("node:assert/strict");

(async () => {
  const html = fs.readFileSync(process.argv[2], "utf8");
  const browser = await chromium.launch({headless: true, channel: "chromium"});
  try {
    const context = await browser.newContext({
      viewport: {width: 1280, height: 900},
      permissions: ["clipboard-read", "clipboard-write"]
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    let mode = "captured";
    const payload = {connectorId: 1, csChargingProfiles: {
      chargingProfileId: 160502, transactionId: 1601, stackLevel: 0,
      chargingProfilePurpose: "TxProfile", chargingProfileKind: "Absolute",
      chargingSchedule: {chargingRateUnit: "W", startSchedule: "2026-10-10T06:03:31Z",
        chargingSchedulePeriod: [11000, 7000, 11000, 3000, 0, 11000, 0]
          .map((limit, i) => ({startPeriod: i * 20, limit}))}
    }};
    await page.route("**/*", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/bundle.html"))
        return route.fulfill({contentType: "text/html", body: html});
      assert.equal(route.request().method(), "GET", "Status must not send commands");
      let data = {};
      if (path.endsWith("/txprofile")) {
        if (mode === "error") return route.fulfill({status: 503, body: "unavailable"});
        const received = path.includes("/1/") && mode !== "empty";
        data = {received, captureStatus: received ? mode : "empty",
          receivedAt: received ? "2026-10-10T06:03:20Z" : null,
          acceptance: "not_recorded",
          payload: received && mode === "captured" ? payload : null};
      } else if (path.endsWith("/connectors")) data = ["1", "2"];
      else if (path.endsWith("/evse"))
        data = {evPlugged: false, evReady: false, evseReady: false, chargePointStatus: "Available"};
      else if (path.endsWith("/meter")) data = {power: 0, energy: 0, current: 0, voltage: 0};
      else if (path.endsWith("/transaction")) data = {transactionId: 0};
      else if (path.endsWith("/smartcharging")) data = {maxPower: 11000, maxCurrent: 48};
      return route.fulfill({json: data});
    });
    // Ingress-like prefix validates relative URLs.
    await page.goto("https://simulator.test/api/hassio_ingress/test/bundle.html");
    const pre = page.locator("#txprofile-status pre").first();
    await pre.waitFor({state: "visible"});
    assert.equal(await pre.textContent(), JSON.stringify(payload, null, 2));
    const copy = page.getByRole("button", {name: "Copy connector 1 TxProfile JSON"});
    await copy.click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), JSON.stringify(payload, null, 2));
    assert.equal(await page.getByRole("button", {name: "Copy connector 2 TxProfile JSON"}).isDisabled(), true);
    const screenshot = async name => {
      if (process.argv[3]) {
        fs.mkdirSync(process.argv[3], {recursive: true});
        await page.screenshot({path: `${process.argv[3]}/${name}.png`, fullPage: true});
      }
    };
    await page.locator("#txprofile-status").scrollIntoViewIfNeeded();
    await screenshot("txprofile-desktop");
    await page.setViewportSize({width: 375, height: 812});
    await page.waitForFunction(() => {
      const main = document.querySelector("main").getBoundingClientRect();
      return Math.abs(main.x) < 1 && Math.abs(main.width - 375) < 1;
    });
    await page.locator("#txprofile-status").scrollIntoViewIfNeeded();
    await screenshot("txprofile-mobile");
    const bounds = await page.locator("#txprofile-status").boundingBox();
    assert(bounds.width >= 340 && bounds.x >= 0 && bounds.x + bounds.width <= 376, JSON.stringify(bounds));
    payload.csChargingProfiles.diagnosticLabel = "<img src=x onerror=alert(1)> %s %n";
    await page.waitForFunction(() => document.querySelector("#txprofile-status pre").textContent.includes("%n"));
    assert.equal(await page.locator("#txprofile-status img").count(), 0);
    mode = "error";
    await page.getByText("Unable to refresh received TxProfile. Retrying automatically.").first().waitFor();
    assert.equal(await pre.isHidden(), true);
    assert.equal(await copy.isDisabled(), true);
    await screenshot("txprofile-error");
    mode = "too_large";
    await page.getByText(/exceeds the 4 KiB/).waitFor();
    assert.equal(await pre.isHidden(), true);
    mode = "empty";
    await page.waitForFunction(() => [...document.querySelectorAll(".txprofile-card p")]
      .every(el => el.textContent.includes("No TxProfile received")));
    await screenshot("txprofile-empty");
    mode = "captured";
    await pre.waitFor({state: "visible"});
    // Clipboard-denied fallback is exercised through the visible button.
    await page.evaluate(() => {
      navigator.clipboard.writeText = async () => {throw new Error("denied");};
    });
    await copy.click();
    assert.equal(await copy.textContent(), "JSON selected: copy manually");
    assert.equal(await page.evaluate(() => window.getSelection().toString()), JSON.stringify(payload, null, 2));
    assert.deepEqual(errors, []);
    console.log("PASS UI: pretty JSON, copy/fallback, empty, retry/recovery, size warning, HTML safety, mobile, ingress prefix; no commands");
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
