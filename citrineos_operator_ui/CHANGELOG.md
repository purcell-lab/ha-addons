# Changelog

## 0.2.0

- Built from CitrineOS **v2.1.0** (`4fd7599b91c2fb6e6065e7c9b94be69880cced27`,
  upstream Operator UI 1.4.0), matching CitrineOS Isolated Lab 0.8.0, which
  this version needs. The v2.0.1 UI read the `LatestStatusNotifications`
  table that v2.1.0 drops; this UI reads each connector's
  `LatestStatusNotification`, and has upstream's new Network Alerts page.
  `operator-ui.patch` carries the same changes, rebased.
- The v2.1.0 UI asks CitrineOS for the user's permissions
  (`/permissions/user`). The proxy answers that itself with "not enforcing",
  so the UI shows every page and button as before; the server's gateway
  still enforces the operator scope. CitrineOS's development login
  (`/dev/...`) answers 404 and is never forwarded.

## 0.1.0

- First release: CitrineOS v2.0.1 Operator UI behind Home Assistant Ingress,
  read-only data through the lab gateway's `operator_ro` role and optional
  bounded OCPP commands. Needs CitrineOS Isolated Lab 0.5.0.
