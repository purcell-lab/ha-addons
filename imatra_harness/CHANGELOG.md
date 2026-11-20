# Changelog

## 0.1.2

- New option `ev_protocol` (default `ISO_15118_2`, as before). `DIN_SPEC_70121`
  makes the test EV DIN-only, so Imatra reads its state of charge.

## 0.1.1

- New option `charge_loop_cycles` (default 30, as before): the test EV's
  ChargingStatus loops per session, so a session can last through a
  multi-step control test.

## 0.1.0

- First draft. Imatra test station and Josev 0.31.2 test EV on a veth V2G link.
- Harness fetched at run time after `accept_licence`, pinned to
  imatra.test_harness e1e9dfc (contracts/IMATRA_REF d07ba26), SHA-256 checked.
- Built locally by the Supervisor; no `image:` and no published image.
