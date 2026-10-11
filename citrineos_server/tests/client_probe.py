"""Use the actual pinned HA API client, without importing HA Core at package init.

Synthetic CI credentials arrive on stdin, never argv. Only sanitized command
states and scoped metering are printed. Entity behaviour is tested separately.
"""
import asyncio
import importlib
import json
import sys
import types
from datetime import datetime
import aiohttp

package = types.ModuleType("lab_client")
package.__path__ = ["/opt/client"]
sys.modules["lab_client"] = package
lab = importlib.import_module("lab_client.lab_control")
hasura = importlib.import_module("lab_client.hasura_client")
compat = importlib.import_module("lab_client.compatibility")
telemetry = importlib.import_module("lab_client.lab_telemetry")


async def run(x):
    async with aiohttp.ClientSession() as session:
        client = lab.ScopedLabClient(session, "http://lab-server:8080", 1,
            x["reader"], True, 10, command_token=x["commander"], read_only=False)
        common = {"protocol": lab.PROTOCOL, "station_id": lab.STATION}
        action = x["action"]
        if action == "ping":
            await client.ping()
            return {"policy": "verified"}
        if action == "start":
            return await client.request_start_transaction(**common)
        if action == "stop":
            return await client.request_stop_transaction(**common, transaction_id=x["transaction_id"])
        if action == "profile":
            return await client.submit_schedule(**common, transaction_id=x["transaction_id"],
                periods=x["periods"], duration=x["duration"],
                start_at=datetime.fromisoformat(x["start_at"]))
        if action == "clear":
            return await client.clear_charging_profile(**common, profile_id=lab.PROFILE_ID)
        if action == "meter":
            h = hasura.HasuraClient(session, url="http://lab-server:8080/v1/graphql",
                token=x["reader"], bearer_auth=True, request_timeout=10, verify_ssl=True)
            result = await h.query(compat.V2_DISCOVERY_QUERY, variables={"tenantId": 1})
            rows = compat.normalize_v2_discovery(result, 1)
            station = next(s for s in rows["stations"] if s["id"] == lab.STATION)
            return await telemetry.fetch_meter(h, station, 1)
        raise ValueError("Unknown probe action")


try:
    print(json.dumps(asyncio.run(run(json.load(sys.stdin)))))
except Exception as error:
    # Our client emits bounded, credential-free errors; never print input.
    print(json.dumps({"error_type": type(error).__name__, "error": str(error)}))
    sys.exit(1)
