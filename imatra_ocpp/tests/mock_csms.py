"""A minimal CSMS for CI (the ocpp library's central-system side).

Offers the versions in CSMS_VERSIONS. On the first TransactionEvent Started
it sends SetChargingProfile 10 A (TxProfile), then 3 A, then
ClearChargingProfile, and prints each answer as a JSON line.
"""
import asyncio
import importlib
import json
import os
from datetime import datetime, timezone

import websockets
from ocpp.routing import on

VERSIONS = os.environ.get("CSMS_VERSIONS", "ocpp2.1,ocpp2.0.1").split(",")
done = False


def out(**kw):
    print(json.dumps(kw), flush=True)


def now():
    return datetime.now(timezone.utc).isoformat()


def profile(amps, tx):
    return {"id": 1, "stack_level": 0, "charging_profile_purpose": "TxProfile", "charging_profile_kind": "Relative",
            "transaction_id": tx, "charging_schedule": [{"id": 1, "charging_rate_unit": "A",
            "charging_schedule_period": [{"start_period": 0, "limit": amps}]}]}


async def handler(ws):
    version = ws.subprotocol
    mod = importlib.import_module("ocpp.v21" if version == "ocpp2.1" else "ocpp.v201")
    A, R, C = mod.enums.Action, mod.call_result, mod.call

    class CSMS(mod.ChargePoint):
        @on(A.boot_notification)
        async def boot(self, charging_station, reason, **_):
            out(event="boot", version=version, station=self.id, model=charging_station.get("model"))
            return R.BootNotification(current_time=now(), interval=60, status="Accepted")

        @on(A.heartbeat)
        async def hb(self, **_):
            return R.Heartbeat(current_time=now())

        @on(A.status_notification)
        async def status(self, connector_status, **_):
            out(event="status", status=connector_status)
            return R.StatusNotification()

        @on(A.notify_report)
        async def report(self, **_):
            return R.NotifyReport()

        @on(A.transaction_event)
        async def tx(self, event_type, transaction_info, trigger_reason, **kw):
            out(event="tx", type=event_type, trigger=trigger_reason, tx=transaction_info.get("transaction_id"),
                state=transaction_info.get("charging_state"), stopped=transaction_info.get("stopped_reason"))
            global done
            if event_type == "Started" and not done:
                done = True
                asyncio.create_task(self.control(transaction_info["transaction_id"]))
            return R.TransactionEvent()

        async def control(self, tx):
            for amps in (10, 3):
                r = await self.call(C.SetChargingProfile(evse_id=1, charging_profile=profile(amps, tx)))
                out(event="set_profile", amps=amps, status=r.status, reason=(r.status_info or {}).get("reason_code"),
                    info=(r.status_info or {}).get("additional_info"))
            r = await self.call(C.ClearChargingProfile(charging_profile_id=1))
            out(event="clear", status=r.status)

    await CSMS(ws.request.path.rstrip("/").split("/")[-1], ws).start()


async def main():
    async with websockets.serve(handler, "0.0.0.0", 9000, subprotocols=VERSIONS):
        out(event="listening", versions=VERSIONS)
        await asyncio.Future()


asyncio.run(main())
