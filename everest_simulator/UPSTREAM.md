# Upstream sources and licences

This App repackages binaries from the EVerest project. It does not modify
EVerest source code. All EVerest components are Apache-2.0 licensed.

## Pinned inputs

| Input | Pin |
|---|---|
| EVerest demo manager image | `ghcr.io/everest/everest-demo/manager:2025.10.0-single-phase@sha256:9165d0937323ae61ee2e496f68f3c4a465ed9099740e489df1f0161265492756` (multi-arch index) |
| everest-demo repository | [EVerest/everest-demo](https://github.com/EVerest/everest-demo) at `686e370d6ed6460211b06e34a4cdf9438a22e81e` (`TAG=2025.10.0-single-phase`) |
| everest-core | 2025.10.0, commit `c86cd9c0ada60b5797f574fd484eae4d8330017d` (built inside the demo image) |
| libocpp | v0.30.3, commit `1c6fb7c5fd92b4651648bcf3a6c8f32b58b935dc` (everest-core `dependencies.yaml`) |
| everest-framework | v0.24.0, commit `059e95ca6cdd23f318259a87480c0b1f48d0cf72` |
| libiso15118 | v0.9.0, commit `a792d07039475375faf56813ce46f52728032d80` (in the build; this App ships no ISO 15118 module) |
| libwebsockets | v4.4.1, commit `adc128ca082a3c6fb9d4abbadefc09e3bc736724` (libocpp and everest-framework `dependencies.yaml`) |
| Runtime base | `debian:bookworm-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587` (same Debian 12 ABI as the demo build) |

Up to 0.1.4 this table gave `a68f6735…` as the libocpp commit, `23a1414…` as
the everest-framework commit and `8038d1d8…` for libwebsockets. Those are the
demo build's CPM cache directory keys (`/ext/cache/cpm/libocpp/a68f6735…`, as in
everest-demo's `enable_ocpp_logging.patch`), not git commits. The versions
above are the tags pinned by everest-core 2025.10.0.

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
