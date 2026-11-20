# Changelog

## 0.1.5

- imatra-ocpp at commit `75301d3`: the EV's state of charge, which Imatra reads
  over DIN 70121, is sent to the CSMS as a SoC sampled value (Percent,
  location EV) in a TransactionEvent Updated.

## 0.1.4

- imatra-ocpp at commit `9f4ce68`: a SetChargingProfile equal to the limit the
  device already confirmed is accepted at once and renewed. Before, it timed
  out as NotConfirmed and the rollback cancelled the limit.

## 0.1.3

- imatra-ocpp at commit `2d14e99`: the Imatra limit is cancelled when a
  session ends. Before, the last TxProfile limit stayed on the device for its
  full duration (default 3600 s) and the next session started limited.

## 0.1.2

- imatra-ocpp at commit `4868f8f`: OCPP timestamps are sent in UTC with
  milliseconds (`...T08:06:35.753Z`). CitrineOS rejected Imatra local-offset
  times with FormatViolation on TransactionEvent.

## 0.1.1

- imatra-ocpp at commit `711a011`: event-feed polling is no longer logged
  every second; failures still are.

## 0.1.0

- First release: imatra-ocpp at commit `2220214`. Each Imatra device is an
  OCPP 2.1 / 2.0.1 charging station; SetChargingProfile is Accepted only once
  the device confirmed the limit. No ports; finds the Imatra App in the same
  repository by itself. Published as a prebuilt image, gated by the Imatra
  lab end to end with a mock CSMS.
