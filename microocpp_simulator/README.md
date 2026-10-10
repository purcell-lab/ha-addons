# MicroOCPP Simulator Home Assistant App

Native OCPP 2.0.1 test station with two EVSEs (one connector each), persistent protocol state,
Ingress-only web UI and a disconnected first start. No production control
or payment integration is included.

Read [DOCS.md](DOCS.md) before connecting to a CSMS and [UPSTREAM.md](UPSTREAM.md)
for version and licensing details. This package is for isolated laboratory
testing, not a certified charger or revenue meter.

MicroOCPP's 2.0.1 implementation has limited feature coverage. This App
targets connection, authorisation, transaction events and metering, not
complete 2.0.1 smart charging or V2G.
