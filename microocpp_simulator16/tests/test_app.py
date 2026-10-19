import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import (configure, connection_diagnostics, lab_dns_url,
                 mongoose_a_query, parse_dns_answers, validate)


class OptionsTest(unittest.TestCase):
    def test_disconnected_default(self):
        self.assertEqual(validate({}), ("", "SIM-16-MICROOCPP-01"))
        with self.assertRaises(ValueError):
            validate([])

    def test_test_identity_required(self):
        for identity in ("physical-charger", "SIM-MICROOCPP-01", "SIM-16-a/b",
                         "SIM-16-", "SIM-16-" + "x" * 38):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                validate({"charge_point_id": identity})

    def test_acknowledgement_required(self):
        for value in (False, "true", 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate({"backend_url": "ws://test:9000", "acknowledge_test_isolation": value})

    def test_rejects_unsafe_or_unsupported_urls(self):
        for url in ("https://test:9000", "wss://test:9000", "ws://test",
                    "ws://user:pass@test:9000", "ws://test:9000?q=1",
                    "ws://test:9000/#x", "ws://test:bad", "ws://test:9000/\n",
                    "ws://test:9000/%2f", "ws://test:9000/SIM-16-MICROOCPP-01"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate({"backend_url": url, "acknowledge_test_isolation": True})

    def test_accepts_explicit_test_endpoint(self):
        self.assertEqual(validate({"backend_url": "ws://test:9000/ocpp/",
                                   "acknowledge_test_isolation": True})[0],
                         "ws://test:9000/ocpp")

    def test_16_connection_seeded_without_201_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            self.assertTrue(configure(data, {"backend_url": "ws://test:9000",
                                             "acknowledge_test_isolation": True}))
            document = json.loads((data / "mo_store/ws-conn.jsn").read_text())
            values = {v["key"]: v["value"] for v in document["configurations"]}
            self.assertEqual(values["Cst_BackendUrl"], "ws://test:9000")
            self.assertEqual(values["Cst_ChargeBoxId"], "SIM-16-MICROOCPP-01")
            self.assertFalse((data / "mo_store/ws-conn-v201.jsn").exists())

    def test_preserves_records_but_resets_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            configure(data, {})
            marker = data / "mo_store/transaction-marker.json"
            marker.write_text('{"preserve":true}')
            configure(data, {})
            self.assertEqual(marker.read_text(), '{"preserve":true}')
            doc = json.loads((data / "mo_store/simulator.jsn").read_text())
            values = {v["key"]: v["value"] for v in doc["configurations"]}
            self.assertEqual(values["OcppVersion"], "1.6")
            self.assertFalse(values["evReady_cId_1"])

    def test_no_silent_rebinding_after_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            options = {"backend_url": "ws://test:9000", "acknowledge_test_isolation": True}
            configure(data, options)
            configure(data, {})
            doc = json.loads((data / "mo_store/ws-conn.jsn").read_text())
            self.assertEqual(next(v["value"] for v in doc["configurations"]
                                  if v["key"] == "Cst_BackendUrl"), "")
            configure(data, options)
            for changes in ({"backend_url": "ws://other:9000"},
                            {"charge_point_id": "SIM-16-OTHER"}):
                with self.assertRaises(ValueError):
                    configure(data, dict(options, **changes))

    def test_invalid_options_do_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            with self.assertRaises(ValueError):
                configure(data, {"backend_url": "ws://test:9000"})
            self.assertFalse(data.exists())

    def test_invalid_stored_data_is_not_erased(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            configure(data, {})
            path = data / "mo_store/simulator.jsn"
            path.write_text("broken")
            with self.assertRaises(ValueError):
                configure(data, {})
            self.assertEqual(path.read_text(), "broken")

    def test_unbound_201_transactions_cannot_be_redirected(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            configure(data, {})
            transaction = data / "mo_store/tx201-1-1-0.json"
            transaction.write_text('{"existing":"test transaction"}')
            with self.assertRaises(ValueError):
                configure(data, {"backend_url": "ws://test:9000",
                                 "acknowledge_test_isolation": True})
            self.assertFalse((data / "test-identity.json").exists())
            self.assertTrue(transaction.exists())

    def test_archive_and_rebind_moves_state_aside(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            options = {"backend_url": "ws://test:9000", "acknowledge_test_isolation": True}
            configure(data, options)
            transaction = data / "mo_store/tx-1-1.json"
            transaction.write_text('{"existing":"test transaction"}')
            moved = dict(options, backend_url="ws://other:9000")
            with self.assertRaises(ValueError):
                configure(data, moved)
            configure(data, dict(moved, archive_and_rebind=True))
            archive = next(data.glob("archive-*"))
            self.assertEqual(archive.stat().st_mode & 0o777, 0o700)
            self.assertEqual((archive / "mo_store" / transaction.name).read_text(),
                             '{"existing":"test transaction"}')
            self.assertEqual(json.loads((archive / "test-identity.json").read_text())["backend_url"],
                             "ws://test:9000")
            self.assertEqual(json.loads((data / "test-identity.json").read_text())["backend_url"],
                             "ws://other:9000")
            self.assertFalse((data / "mo_store" / transaction.name).exists())

    def test_archive_and_rebind_must_be_boolean(self):
        for value in ("true", 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate({"archive_and_rebind": value})

    def test_lab_dns_url_uses_first_ipv4_resolver(self):
        self.assertEqual(lab_dns_url("# x\nnameserver fd00::1\nnameserver 172.30.32.3\n"
                                     "nameserver 1.1.1.1\n"), "udp://172.30.32.3:53")
        self.assertIsNone(lab_dns_url("nameserver ::1\nnameserver bogus\n"))


class ConnectionDiagnosticsTest(unittest.TestCase):
    """#31: log what Mongoose resolves and whether that address accepts TCP."""

    def test_query_is_byte_for_byte_mongoose_mg_dns_send(self):
        # Captured from the pinned mo_simulator resolving ws://fake-csms:8082.
        self.assertEqual(mongoose_a_query("fake-csms").hex(),
                         "0001010000010000000000000966616b652d63736d730000010001")

    def test_parse_answers_in_order_with_cname_and_aaaa(self):
        query = mongoose_a_query("csms")
        reply = bytearray(query)
        reply[2:4] = b"\x81\x80"
        reply[6:8] = (3).to_bytes(2, "big")
        reply += b"\xc0\x0c\x00\x05\x00\x01\x00\x00\x00\x0a\x00\x02\xc0\x0c"
        reply += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x0a\x00\x04" + bytes([172, 30, 33, 8])
        reply += b"\xc0\x0c\x00\x1c\x00\x01\x00\x00\x00\x0a\x00\x10" + bytes(15) + b"\x01"
        self.assertEqual(parse_dns_answers(bytes(reply)),
                         (0, [("type5", ""), ("A", "172.30.33.8"), ("AAAA", "::1")]))
        with self.assertRaises(ValueError):
            parse_dns_answers(bytes(reply[:-3]))

    def _fake_dns(self, answer):
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        self.addCleanup(server.close)

        def serve():
            query, peer = server.recvfrom(512)
            reply = bytearray(query)
            reply[2:4] = b"\x81\x80"
            reply[6:8] = b"\x00\x01"
            reply += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x0a\x00\x04" + socket.inet_aton(answer)
            server.sendto(bytes(reply), peer)

        threading.Thread(target=serve, daemon=True).start()
        return f"udp://127.0.0.1:{server.getsockname()[1]}"

    def test_reports_mongoose_answer_and_tcp_probe(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        self.addCleanup(listener.close)
        port = listener.getsockname()[1]
        dns = self._fake_dns("127.0.0.1")
        lines = connection_diagnostics(f"ws://csms.invalid:{port}",
                                       "nameserver 127.0.0.11\n", dns)
        self.assertTrue(all(line.startswith("Connection diagnostics: ") for line in lines))
        self.assertIn("resolv.conf nameservers: 127.0.0.11; Mongoose DNS: " + dns, lines[0])
        self.assertIn("libc getaddrinfo csms.invalid: failed", lines[1])
        self.assertIn("answers A 127.0.0.1; Mongoose connects to 127.0.0.1", lines[2])
        self.assertTrue(lines[3].endswith(f"TCP probe 127.0.0.1 port {port}: open"))

    def test_reports_refused_port_for_literal_address(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        lines = connection_diagnostics(f"ws://127.0.0.1:{port}", "", None)
        self.assertIn("nameservers: none", lines[0])
        self.assertIn("is an address; no DNS lookup", lines[1])
        self.assertTrue(lines[2].endswith("ECONNREFUSED"))


if __name__ == "__main__":
    unittest.main()
