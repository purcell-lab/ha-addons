# Upstream sources and licences

This App repackages binaries from the EVerest project. It does not modify
EVerest source code. All EVerest components are Apache-2.0 licensed.

## Pinned inputs

| Input | Pin |
|---|---|
| EVerest demo manager image | `ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756` (multi-arch index) |
| everest-demo repository | [EVerest/everest-demo](https://github.com/EVerest/everest-demo) at `686e370d6ed6460211b06e34a4cdf9438a22e81e` (`TAG=2025.10.0-single-phase`) |
| everest-core | 2025.10.0 (built inside the demo image) |
| libocpp | `a68f6735ebee194bd543386bbf4dbe2f678df268` |
| everest-framework | `23a1414f35f0b4bfcaf260340e3c7ca674214095` |
| libwebsockets | `8038d1d891d26d053c4b40454f31ae1b6d304b86` |
| Runtime base | `debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587` (same Debian 12 ABI as the demo build) |

The getting-started guide this App follows is
[EVerest: Get started with software](https://everest.github.io/latest/how-to-guides/getting-started/get-started-sw.html).

## Demo-image patches that affect this App

The demo image applies patches from `manager/demo-patches` in everest-demo.
The ones relevant to the modules shipped here:

- `composite_schedule_fixes.patch`: INFO logging of composite schedules in
  the OCPP201 and API modules. The App's log forwarder drops these repeats.
- `enable_ocpp_logging.patch`: SetChargingProfile accept/reject logged at INFO.
- `hw_cap_down_to_16A.patch`: default `CompositeScheduleDefaultLimitAmps` 16.
  The App overrides it with `max_current_a`.
- `switch_to_single_phase.patch`: ISO 15118 phase handling. Not active here
  because ISO 15118 is disabled (`ac_hlc_enabled: false`).

## What is copied

Only `/ext/dist` runtime content from the demo image: `bin/manager`, shared
libraries, the module directories listed in the Dockerfile `MODULES`
argument, `share/everest` and the default certificates. Binaries are
stripped. The upstream admin-panel `controller` (which listens on all
interfaces) is replaced by a stub. `etc/everest/default_logging.cfg` is
replaced by the App's own (no colour codes).

## Licences

The image carries `/usr/share/doc/everest/EVerest-LICENSE` and the
licence/notice files of every CPM-fetched dependency under
`/usr/share/doc/everest/third_party/`. Debian packages carry their own
copyright files under `/usr/share/doc/`.
