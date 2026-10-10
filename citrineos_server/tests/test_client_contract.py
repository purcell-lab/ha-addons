"""Exercise the unmodified pinned HA client with the server route inventory.

Transport is a stub. No HA instance, credentials, station or server connection.
CI supplies CLIENT_SOURCE and ROUTE_REPORT; local safety tests need neither.
"""
import importlib.util
import json
import os
from pathlib import Path
import unittest


@unittest.skipUnless(os.environ.get("CLIENT_SOURCE") and os.environ.get("ROUTE_REPORT"),
                     "requires pinned client and compiled-server route report")
class ClientContract(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "pinned_citrine_api", os.environ["CLIENT_SOURCE"])
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)
        report = json.loads(Path(os.environ["ROUTE_REPORT"]).read_text())
        assert report["test_scope"] == "compiled_api_route_registration_with_inert_handlers"
        cls.routes = {(r["method"], r["url"]) for r in report["routes"]}

    def client(self, force_auth_error=False):
        outer = self
        class Probe(self.module.CitrineClient):
            async def _request(self, method, path, **kwargs):
                outer.requested.append((method, path))
                if force_auth_error:
                    raise outer.module.CitrineAuthError("Authentication failed")
                if (method, path) not in outer.routes:
                    raise outer.module.CitrineApiError(
                        f"Citrine API {method} {path} failed (404)")
                return []
        self.requested = []
        return Probe(None, "http://invalid.test", 1, None, True, 2)

    async def test_required_ping_is_incompatible(self):
        with self.assertRaisesRegex(self.module.CitrineApiError, r"failed \(404\)"):
            await self.client().ping()
        self.assertEqual(self.requested, [("GET", "/data/ocpprouter/systemConfig")])

    async def test_discovery_swallows_missing_routes_as_empty(self):
        result = await self.client().discover_chargers_rest()
        self.assertEqual(result, {"stations": [], "connectors": [], "transactions": []})
        self.assertEqual(len(self.requested), 16)
        self.assertTrue(all(route not in self.routes for route in self.requested))

    async def test_discovery_also_swallows_auth_error(self):
        self.assertEqual(await self.client(True).get_charging_stations(), [])

    async def test_protocol_paths_exist_but_do_not_prove_delivery(self):
        client = self.client()
        for protocol in ("ocpp2.0.1", "ocpp2.1"):
            first = client._ocpp2_paths(protocol, "smartcharging/setChargingProfile")[0]
            self.assertIn(("POST", first), self.routes)
        self.assertIn(("POST", "/ocpp/1.6/smartcharging/setChargingProfile"), self.routes)
        self.assertEqual(self.requested, [])


if __name__ == "__main__":
    unittest.main()
