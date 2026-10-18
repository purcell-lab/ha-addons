# Changelog

## 0.1.11

- Dynamic pricing (DOCS.md, Dynamic pricing). The device model enables
  TariffCostCtrlr Tariff and Cost (`Available` and `Enabled`), Currency
  `AUD`, `NumberOfDecimalsForCostValues` 4 and California Pricing
  (`CustomImplementationEnabled[org.openchargealliance.costmsg]`). CostUpdated
  and a TransactionEventResponse `totalCost` now reach EVerest's session
  cost; before, libocpp acknowledged CostUpdated and dropped it.
- The Status page has a **Price** panel: total cost, current and next
  price per kWh with the next period's start, price text and timestamp from
  the latest session cost; the first intervals of any `absolutePriceSchedule`,
  `priceLevelSchedule` or `salesTariff` in the last received charging profile
  (stored by libocpp, not acted on); and the last ten CostUpdated,
  SetDefaultTariff, GetTariffs, ClearTariffs and ChangeTransactionTariff
  requests with the station's reply. libocpp v0.30.3 answers the four OCPP
  2.1 tariff messages `NotImplemented`. `/api/status` adds `session_cost`;
  `/api/profiles` adds `price_schedules` and `pricing`.
- The acceptance run sends CostUpdated with California Pricing during the
  transaction and checks the Status page; on OCPP 2.1 it also checks that a
  profile with an `absolutePriceSchedule` is accepted and shown, and that
  SetDefaultTariff is answered `NotImplemented`.
- UPSTREAM.md: libocpp v0.30.3, everest-framework v0.24.0, libiso15118
  v0.9.0 and everest-core commits. The libocpp and everest-framework hashes
  given before were build-cache keys, not commits.

## 0.1.10

- The acceptance run adds direct reversals between charge and discharge
  (+20 kW to -5 kW to +3 kW), checks 380 V on every discharge step, and
  checks that current times voltage gives the power. Charging still runs at
  the simulated EV's 900 V maximum (#70): with charging at or near 380 V,
  EvseManager left some power steps at the previous target (UPSTREAM.md,
  upstream behaviour 12).
- A start more than 60 s after plug-in now charges (#33). The simulated EV
  gave up 60 s after asking for authorisation, started no new session in
  that plug-in, and the transaction then ran at 0 W while a new plug-in was
  refused. The EV now waits 190 s (build-time patch, UPSTREAM.md), and
  the charger's own 3-minute limit applies. If the EV still gives up while
  plugged in, a new EV watchdog unplugs and plugs it in again, never while
  power flows and at most 3 times without a working session. The Status
  page shows a notice; the HA status object adds `ev_session` and
  `ev_last_recovery`. The acceptance run starts the second session 75 s
  after plug-in, and the release gate adds a watchdog run.
- The App log no longer shows `Can not apply external limits! No evse
  energy sink configured for evse_id: 0` every 10 s (part of #28). EVSE 0
  stays without a sink on purpose (its composite capped targets at a third
  of the rating) and neither upstream module can skip it, so the App drops
  only that line. The same warning for EVSE 1 would still show.

## 0.1.9

- 25 kW in both directions (`max_power_kw` 3 to 25, default 25), at 380 V.
  Three limits capped the simulator below that:
  - The simulated EV's discharge limit was hard-coded at 25 A and 11 kW in
    Josev, and the DC supply's 200 V default minimum set the voltage while
    discharging, so discharge stopped at 5 kW (25 A x 200 V). The EV now
    allows 66 A and 25 kW, and the supply minimum and EV target are 380 V.
  - The simulated board (YetiSimulator) reports 16 A export and 32 A import
    per phase, capping discharge at 11.04 kW and charging at 22.08 kW. A
    build-time patch raises both to 128 A in the prebuilt binary, checked by
    SHA-256 and exact bytes for each architecture (UPSTREAM.md).
- The acceptance run now steps +6,000, 0, -20,000, 0 and +20,000 W.

## 0.1.8

- 0 W setpoints are honoured. The simulated DC supply now has a 0 A minimum
  current (upstream default 1 A at 200 V), so EvseManager no longer sees a
  200 W minimum above a 0 W target and keeps the previous current. Before,
  a 0 W setpoint left the EV at its previous power, and after a discharge
  that power reappeared as charging. The acceptance run now steps
  +6,000, 0, -5,000, 0 and +3,000 W.
- Still upstream: a charging-only period (no `setpoint` or
  `dischargeLimit`) does not bound discharge, because EVerest 2025.10.0
  OCPP201 sends no export limit. Use CentralSetpoint periods (DOCS.md).

## 0.1.7

- `tx_sample_interval_s` option (default 5 s) and a profile panel that
  shows the newest SetChargingProfile of any purpose.

## 0.1.6 (unreleased)

- Offer and publish aarch64 images again alongside amd64, for example for a
  Home Assistant Green test host.
- Replace the full OpenJDK 17 JRE package (about 184 MB) with a jlink
  runtime of only the modules Josev's EXI codec uses (about 50 MB), with a
  fixed small heap (-Xmx128m, serial GC). The codec JVM's resident memory
  drops from about 158 MB to about 92 MB; EXI encoding is byte-identical.

## 0.1.5 (released 2026-10-11)

- Send OCPP transaction meter samples every second instead of every ten
  seconds, so the CSMS record can time step response and direction changes.
- Status page redesign: icons, a bidirectional power bar and a two-minute
  power trend; live reading chips coloured green for import/charging and blue
  for export/discharge, always with a +/- sign, arrow icon and text label;
  signed, coloured composite schedule values; discovery self-test moved to
  the bottom. Readings refresh every second.
- Accessibility: visible keyboard focus, AA contrast in light and dark themes,
  reduced-motion support and a polite screen-reader announcement only when
  the power direction changes. No new network access; icons are inline SVG
  under the existing Content-Security-Policy.

## 0.1.4 (released 2026-10-11)

- Add an optional provisioned Basic Authentication password for an isolated CSMS.
- Preserve the original generated password for rollback; never include the
  supplied password in returned settings or status.
- Keep the existing explicit archive-and-rebind requirement. No migration runs
  merely by upgrading the App.
- Prebuilt images require separately approved publication before installation.
- Request import/export energy and signed power in OCPP transaction frames.

## 0.1.3 (released 2026-10-11)

- Rebuilt from the shared EVerest runtime image
  `ghcr.io/purcell-lab/everest-runtime:2025.10.0-1`. No functional change:
  the identical-file release gate found 0 differences against 0.1.2 under
  the EVerest, licence, App code and Python paths.
- From the next release, only amd64 images are built and offered.
