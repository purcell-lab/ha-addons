# Changelog

## 0.1.5

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
  v0.9.0, libwebsockets v4.4.1 and everest-core commits. The libocpp,
  everest-framework and libwebsockets hashes given before were build-cache
  keys, not commits.

## 0.1.4 and earlier

See the git history of `everest_simulator/`. 0.1.4 added the
`tx_sample_interval_s` option (default 5 s) and the any-purpose profile
panel; 0.1.3 applied 3-phase watt limits in full.
