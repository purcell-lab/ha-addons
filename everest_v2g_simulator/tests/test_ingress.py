"""Exercise the actual nginx ACL, not only string checks on its configuration."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request


class Backend(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(b"test backend")

    do_POST = do_GET

    def log_message(self, *args):
        pass


@unittest.skipUnless(shutil.which("nginx"), "nginx unavailable")
class IngressTest(unittest.TestCase):
    def test_peer_acl_and_mutation_allowlist(self):
        source = Path(__file__).resolve().parents[1] / "rootfs/opt/ha-everest/nginx.conf"
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
            thread = threading.Thread(target=backend.serve_forever, daemon=True)
            thread.start()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            conf = source.read_text().replace("listen 8099;", f"listen 127.0.0.1:{port};")
            conf = conf.replace("127.0.0.1:8000", f"127.0.0.1:{backend.server_port}")
            conf = conf.replace("/run/nginx.pid", str(tmp / "nginx.pid"))
            conf = conf.replace("/tmp/nginx-", str(tmp / "nginx-"))
            conf = conf.replace("/dev/stderr", str(tmp / "nginx.log"))

            def request(path="/", method="GET", headers=None):
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                             method=method, headers=headers or {})
                try:
                    with urllib.request.urlopen(req, timeout=2) as response:
                        return response.status, response.headers
                except urllib.error.HTTPError as error:
                    result = error.code, error.headers
                    error.close()
                    return result

            try:
                for allow_local in (False, True):
                    path = tmp / "nginx.conf"
                    # Local-peer substitution belongs ONLY to this test.
                    path.write_text(conf.replace("allow 172.30.32.2;", "allow 127.0.0.1;")
                                    if allow_local else conf)
                    process = subprocess.Popen(["nginx", "-c", str(path), "-g", "daemon off;"])
                    try:
                        for _ in range(30):
                            try:
                                request()
                                break
                            except OSError:
                                time.sleep(0.1)
                        if not allow_local:
                            self.assertEqual(request()[0], 403)
                            self.assertEqual(request(headers={"X-Forwarded-For": "172.30.32.2"})[0], 403)
                        else:
                            code, headers = request()
                            self.assertEqual(code, 200)
                            self.assertNotIn("Access-Control-Allow-Origin", headers)
                            # Read-only everywhere except the three EV-simulator commands.
                            for endpoint in ("/api/status", "/api/profiles", "/api/ev/plugin"):
                                self.assertEqual(request(endpoint)[0], 403 if endpoint.startswith("/api/ev/") else 200)
                            for endpoint in ("/", "/api/status", "/api/profiles", "/api/ocpp",
                                             "/api/ev/charge", "/api/ev/pause", "/api/ev/resume", "/api/ev/plugin/x", "/api/ev/../status"):
                                self.assertEqual(request(endpoint, "POST")[0], 403, endpoint)
                            for endpoint in ("/api/ev/plugin", "/api/ev/stop", "/api/ev/unplug"):
                                self.assertEqual(request(endpoint, "POST")[0], 200, endpoint)
                                self.assertEqual(request(endpoint, "PUT")[0], 403, endpoint)
                    finally:
                        process.terminate()
                        process.wait(timeout=5)
            finally:
                backend.shutdown()
                backend.server_close()


if __name__ == "__main__":
    unittest.main()
