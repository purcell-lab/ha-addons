"""Use the actual pinned HA API client, without importing HA Core at package init.

Synthetic CI credentials arrive on stdin, never argv. Only sanitized command
states and scoped metering are printed. Entity behaviour is tested separately.
"""
import asyncio
import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
import aiohttp

package = types.ModuleType("lab_client")
package.__path__ = ["/opt/client"]
sys.modules["lab_client"] = package
lab = importlib.import_module("lab_client.lab_control")
hasura = importlib.import_module("lab_client.hasura_client")
compat = importlib.import_module("lab_client.compatibility")
telemetry = importlib.import_module("lab_client.lab_telemetry")
pricing = importlib.import_module("lab_client.pricing")
BRISBANE = timezone(timedelta(hours=10))


def amber(channel, base, now):
    """A synthetic Amber forecast sensor: the current 5-minute interval, then 30-minute ones."""
    # Like Amber: starts at :01, ends on the minute.
    edge = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
    edges = [edge, edge + timedelta(minutes=5)]
    while len(edges) < 13:
        edges.append(edges[-1] + timedelta(minutes=30))
    spans = [(a + timedelta(seconds=1), b) for a, b in zip(edges, edges[1:])]
    forecasts = [{"per_kwh": round(base + 0.01 * i, 4), "start_time": a.isoformat(),
                  "end_time": b.isoformat(), "duration": int((b - a).total_seconds() // 60)}
                 for i, (a, b) in enumerate(spans)]
    return types.SimpleNamespace(state=str(forecasts[0]["per_kwh"]),
        attributes={"forecasts": forecasts, "channel_type": channel, "unit_of_measurement": "$/kWh"})


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
            price_schedule = None
            if x.get("priced"):
                await client.ping()
                price_schedule = pricing.build_price_schedule(
                    pricing.amber_intervals(amber("general", 0.225, datetime.now(timezone.utc))))
            return await client.submit_schedule(**common, transaction_id=x["transaction_id"],
                periods=x["periods"], duration=x["duration"],
                start_at=datetime.fromisoformat(x["start_at"]), price_schedule=price_schedule)
        if action == "cost":
            await client.ping()
            current, nxt = pricing.current_and_next(
                pricing.amber_intervals(amber("general", 0.225, datetime.now(timezone.utc))))
            body = pricing.build_cost_updated(x["transaction_id"], current, nxt, BRISBANE, total_cost=0.42)
            return {"body": body, "dispatch": await client.cost_updated(**common, body=body)}
        if action == "tariff":
            await client.ping()
            now = datetime.now(timezone.utc)
            tariff = pricing.build_tariff(pricing.amber_intervals(amber("general", 0.225, now)), BRISBANE,
                export_intervals=pricing.amber_intervals(amber("feedIn", 0.08, now)), count=12)
            result = await client.set_default_tariff(**common, evse_id=0, tariff=tariff)
            return {"entries": len(tariff["energy"]["prices"]), "dispatch": result}
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
