# purcell-lab Home Assistant Add-ons

A Home Assistant add-on repository mirroring upstream projects with the
Supervisor-compatible layout (top-level `repository.yaml` + slug-named add-on
directories).

## Add to Home Assistant

In the HA UI:

1. Settings → Add-ons → Add-on Store → ⋮ menu → **Repositories**
2. Paste: `https://github.com/purcell-lab/ha-addons`
3. Add → close → the new section "purcell-lab Home Assistant Add-ons" appears in the store.

## Add-ons in this repository

### citrineos_server

Staged CitrineOS Compatibility Lab. This package is disconnected-only and does
not start a central system. Client/server compatibility is blocked; no activation,
charger connection or deployment is enabled.

See [compatibility findings and activation gates](citrineos_server/DOCS.md).

### citrineos_operator_ui

The CitrineOS v2.0.1 Operator UI (CSMS web app) for the isolated lab, in the
sidebar through Ingress. Read-only data through the lab gateway, plus an
optional, bounded set of OCPP commands. Needs CitrineOS Isolated Lab 0.5.0
with its operator scope enabled.

See [setup and limitations](citrineos_operator_ui/DOCS.md).

### microocpp_simulator

Native OCPP 2.0.1 test charger packaged as a Home Assistant App, with a
disconnected default, `SIM-` station identity and Ingress-only web UI.
Requires an isolated test CSMS and exclusion from real charging/payment
automations. No automatic deployment or connection is enabled.

See [setup and limitations](microocpp_simulator/DOCS.md).

### microocpp_simulator16

Separate OCPP 1.6J smart-charging test App, with watt-based TxProfile,
TxDefaultProfile and ChargePointMaxProfile control. Its `SIM-16-` identity
and separate storage preserve the existing OCPP 2.0.1 experiment.
Starts disconnected and is never installed or connected automatically.

See [setup and limitations](microocpp_simulator16/DOCS.md).

### everest_simulator

EVerest 2025.10.0 software-in-the-loop AC charger with a simulated EV. Offers
OCPP 2.1 first with automatic 2.0.1 fallback (or 2.0.1 only), single- or
three-phase, 6 to 32 A. Status page shows the negotiated version, live power
and energy, the effective composite limit and the last received TxProfile
with the station's actual reply. AC charging only: no ISO 15118 or V2G.
`SIM-EV-` identity, disconnected default, Ingress-only UI, never installed or
connected automatically.

See [setup and limitations](everest_simulator/DOCS.md).

### everest_v2g_simulator

EVerest 2025.10.0 software-in-the-loop **bidirectional DC** charger with a
simulated EV: ISO 15118-20 DC_BPT over mutual TLS 1.3, 3 to 11 kW each way.
Under OCPP 2.1 a CSMS can charge and discharge (V2G export) with
CentralSetpoint TxProfiles; under the 2.0.1 fallback it is charging only.
Needs NET_ADMIN only for a private in-container ISO 15118 link and an
inbound drop firewall (lower HA security rating). Per-install test PKI,
`SIM-EV-` identity, disconnected default, Ingress-only UI, never installed or
connected automatically. Known EVerest limitations are listed in the docs.

See [setup and limitations](everest_v2g_simulator/DOCS.md).

### nem_price_forecaster

NEM 7-day wholesale price forecaster sidecar. Configurable price model
(`darts_naive_blend` / `isotonic` / `darts` / `hybrid`), calibrator
(`isotonic` / `monotone_gbm`), and forecast horizon. Exposes the sidecar
HTTP API on port 8765 for the matching `nem_price_forecaster` HA custom
integration.

Upstream: [BrettLynch123/nem-price-forecaster](https://github.com/BrettLynch123/nem-price-forecaster)

After install:

- Configuration tab: set `region` (QLD1 / NSW1 / VIC1 / SA1 / TAS1) and
  optional `latitude` / `longitude`. Leave other knobs at defaults unless
  tuning the calibrator.
- In the matching HA integration, set the sidecar URL to
  `http://localhost:8765`.

## Sync from upstream

```bash
./scripts/sync-upstream.sh
```

Pulls the latest `addon/` tree from
[BrettLynch123/nem-price-forecaster](https://github.com/BrettLynch123/nem-price-forecaster)
into `nem_price_forecaster/` and reports any changes ready to commit.

## License

Add-on contents inherit the upstream project's license. This repository's
packaging (manifest, sync script, README) is MIT.
