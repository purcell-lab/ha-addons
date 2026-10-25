# Changelog

## 0.2.0

- **EVerest 2026.10.0-rc1, compiled from source.** There is no prebuilt
  everest-demo image for 2026.x, so the runtime
  (`ghcr.io/purcell-lab/everest-runtime:2026.10.0-rc1-1`,
  `everest_runtime_source/`) compiles everest-core at the tag (commit
  `f45ba0d`) in EVerest's own CI build image, with only the modules the App
  runs, and is extracted and stripped by the unchanged
  `everest_runtime/Dockerfile`. This is a release candidate. The AC App
  keeps the 2025.10.0 runtime.
- **OCPPmulti replaces OCPP201** (OCPP 2.0.1 and 2.1, `Mode: Only2`).
  The CSMS URL, Security Profile 1 with Basic Auth, the device-model
  overrides (rating, sampling, pricing), CentralSetpoint profiles, the
  25 kW / 380 V settings and the API module carry over. The databases keep
  their paths (`/data/everest/ocpp201/`).
- **OCPP 2.1 DER control** (DOCS.md, DER control). SetDERControl,
  GetDERControl (with ReportDERControl), ClearDERControl and
  NotifyDERStartStop for all 22 control types; `DCDERCtrlr` on EVSE 1 in
  the device model. The App's new `HaGridSupport` EVerest module declares
  the DC capability (EVerest enables DER only for a declared capability,
  and no upstream module declares one), records the active set for the new
  **DER control** panel and `der` in `/api/status` and `/api/profiles`,
  and forwards it to the ISO 15118-20 charger module. Nothing is applied to
  power.
- **Upgrade:** libocpp migrates the core database from schema 6 to 7 on
  the first start; the App keeps a copy of the old file
  (`cp-schema6.db.bak`). A rollback to 0.1.13 needs `archive_and_rebind`
  once (DOCS.md, Upgrading from 0.1.x).
- **Authorisation window is 55 s.** EVerest 2026.10's ISO 15118-20 charger
  stops an EIM authorisation wait after 55 s
  (V2G_SECC_Ongoing_Performance_Time), not 3 minutes. Start transactions
  sooner; the EV watchdog still re-plugs after a missed window.
- Patches: the YetiSimulator binary patch is gone (its
  `caps_max_current_A` option now sets the board limit to the per-phase
  rating); Josev's SDP interface fix is upstream; the PyEvJosev restart,
  25 kW discharge and authorisation-wait patches are rebased onto 2026.10.
  The admin-panel controller stub is gone (the manager no longer starts
  one).
- `environs` 14.5.0 (Josev now asks for 14.5 or later, as the everest-ci
  build image installs).
- Image checks: every EVerest ELF file must resolve its libraries, the
  OCPPmulti and HaGridSupport modules and libocpp's DER migration must be
  present, and the PR acceptance run adds the DER scenario. The start
  window of the late-start session check is now 40 s (was 75 s).

## 0.1.13

- The device model reports the rating per station. EVerest 2025.10.0
  builds EVSE 1 `Power` itself, with only an `Actual` attribute and a
  `maxLimit` from the simulated board (88,320 W after the board patch), so a
  CSMS could not learn `max_power_kw`, and the App cannot change that
  component. `ChargingStation` now has `Power` with `MaxSet` = rating and
  `MinSet` = minus the rating (discharge) in W, also as `maxLimit` and
  `minLimit`. CitrineOS (0.7.2 asks for the report when the station comes
  online) stores `MaxSet` and `MinSet` per station. See "Power rating in the
  device model".
- Documented why the station sends no NotifyEVChargingNeeds: OCPP201's
  `extensions_15118` is not connected to the ISO 15118-20 module, on
  purpose. CitrineOS v2.0.1 rejects ISO 15118-20 `DC_BPT` needs, and libocpp
  then stops the OCPP 2.1 transaction. A test keeps it unconnected
  (UPSTREAM.md items 13 and 14).

## 0.1.12

- Status page times are local: the browser's time zone, with the zone shown
  (AEDT at the Canberra Plugfest). Before, they were UTC. The API still
  uses UTC.
- **Live readings** has two price chips: price now (per kWh) and the next
  price with its start time, from the latest session cost.
- A charging profile over 8 KiB is shown without its price information
  (`absolutePriceSchedule`, `priceLevelSchedule`, `salesTariff`), so the
  power setpoint schedule stays readable. Before, the whole payload was
  withheld, and with it the Price panel's schedule summary: a profile with a
  48 h OpenADR price schedule from the CitrineOS-HA bridge is about 13 KiB.
  The summary is now taken from the full payload. `/api/profiles` events
  add `price_schedules` and `omitted`.

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
