# Changelog

## 0.1.1

- imatra-ocpp at commit `711a011`: event-feed polling is no longer logged
  every second; failures still are.

## 0.1.0

- First release: imatra-ocpp at commit `2220214`. Each Imatra device is an
  OCPP 2.1 / 2.0.1 charging station; SetChargingProfile is Accepted only once
  the device confirmed the limit. No ports; finds the Imatra App in the same
  repository by itself. Published as a prebuilt image, gated by the Imatra
  lab end to end with a mock CSMS.
