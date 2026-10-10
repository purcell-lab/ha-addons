"""Local browser QA fixture. Mock CSMS only; stops after 180 seconds.

Usage: python tests/ui_fixture.py /path/to/prepared/native/tree
Open http://127.0.0.1:8000/ and operate connector 1 through the real UI.
The JSON summary printed on exit contains received OCPP meter samples.
No Home Assistant access, external networking, or real charger controls.
"""
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile

from websockets.asyncio.server import serve


async def main(root):
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", 8000))
    received = []
    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, done.set)

    async def csms(ws):
        assert ws.subprotocol == "ocpp2.0.1"
        assert ws.request.path == "/SIM-MICROOCPP-01"
        async for raw in ws:
            message = json.loads(raw)
            if message[0] != 2:
                continue
            _, uid, action, payload = message
            received.append({"action": action, "payload": payload})
            reply = {}
            if action == "BootNotification":
                reply = {"status": "Accepted", "interval": 30,
                         "currentTime": datetime.now(timezone.utc).isoformat()}
            elif action == "Heartbeat":
                reply = {"currentTime": datetime.now(timezone.utc).isoformat()}
            elif action in ("Authorize", "TransactionEvent"):
                reply = {"idTokenInfo": {"status": "Accepted"}}
            await ws.send(json.dumps([3, uid, reply]))

    spec = importlib.util.spec_from_file_location(
        "app", Path(__file__).resolve().parents[1] / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)
    async with serve(csms, "127.0.0.1", 0, subprotocols=["ocpp2.0.1"]) as server:
        port = server.sockets[0].getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="microocpp-browser-") as tmp:
            data = Path(tmp)
            app.configure(data, {"backend_url": f"ws://127.0.0.1:{port}",
                                 "acknowledge_test_isolation": True})
            (data / "public").symlink_to(root / "public")
            binary = root / "build/mo_simulator"
            if not binary.exists():
                binary = root / "mo_simulator"
            with (data / "native.log").open("w") as log:
                process = subprocess.Popen([str(binary)], cwd=data, stdout=log, stderr=log)
                try:
                    print("Ready: loopback-only browser fixture; 180-second maximum.", flush=True)
                    try:
                        await asyncio.wait_for(done.wait(), timeout=180)
                    except asyncio.TimeoutError:
                        pass
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
            events = [r["payload"] for r in received if r["action"] == "TransactionEvent"]
            print(json.dumps({"events": events, "native_exit": process.returncode}), flush=True)


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
