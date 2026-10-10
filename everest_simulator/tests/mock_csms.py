"""Minimal test-only OCPP 2.x CSMS (never for production use).

Selects the configured subprotocol, answers station-initiated calls, records
every frame and lets an acceptance script send CSMS-initiated calls.
"""
import asyncio
import base64
import datetime as dt
import itertools
import json

import websockets


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class MockCsms:
    def __init__(self, accept=("ocpp2.1", "ocpp2.0.1"), host="127.0.0.1", port=0):
        self.accept = list(accept)
        self.host, self.port = host, port
        self.frames = []           # (direction, decoded frame, monotonic time)
        self.subprotocol = None
        self.path = None
        self.authorization = None
        self.connected = asyncio.Event()
        self._ws = None
        self._pending = {}
        self._ids = itertools.count(1)
        self.boot = asyncio.Event()
        self.server = None

    async def start(self):
        self.server = await websockets.serve(
            self._handler, self.host, self.port,
            subprotocols=self.accept, select_subprotocol=self._select,
            ping_interval=None)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    def _select(self, first, second):
        # websockets >= 13: (connection, client_offer); legacy: (client_offer, server_list).
        offered = first if isinstance(first, (list, tuple)) else second
        # Honour this CSMS's preference order, as a real CSMS would.
        for proto in self.accept:
            if proto in offered:
                return proto
        return None

    async def _handler(self, ws, *path):
        request = getattr(ws, "request", None)
        self.path = request.path if request is not None else (path[0] if path else ws.path)
        headers = request.headers if request is not None else ws.request_headers
        auth = headers.get("Authorization")
        if auth and auth.startswith("Basic "):
            self.authorization = base64.b64decode(auth[6:]).decode().split(":", 1)[0]
        self.subprotocol = ws.subprotocol
        print("connected", self.path, "subprotocol", self.subprotocol, "user", self.authorization, flush=True)
        self._ws = ws
        self.connected.set()
        async for raw in ws:
            msg = json.loads(raw)
            self.frames.append(("in", msg, asyncio.get_running_loop().time()))
            if msg[0] == 2:
                await self._reply(ws, msg)
            elif msg[0] in (3, 4) and msg[1] in self._pending:
                self._pending.pop(msg[1]).set_result(msg)

    async def _reply(self, ws, msg):
        _, uid, action, payload = msg
        accepted = {"idTokenInfo": {"status": "Accepted"}}
        body = {
            "BootNotification": {"currentTime": now(), "interval": 60, "status": "Accepted"},
            "Heartbeat": {"currentTime": now()},
            "Authorize": accepted,
        }.get(action, {})
        if action == "TransactionEvent" and "idToken" in payload:
            body = accepted
        frame = [3, uid, body]
        self.frames.append(("out", frame, asyncio.get_running_loop().time()))
        await ws.send(json.dumps(frame))
        if action == "BootNotification":
            self.boot.set()

    async def call(self, action, payload, timeout=20):
        uid = f"csms-{next(self._ids)}"
        future = asyncio.get_running_loop().create_future()
        self._pending[uid] = future
        frame = [2, uid, action, payload]
        self.frames.append(("out", frame, asyncio.get_running_loop().time()))
        await self._ws.send(json.dumps(frame))
        return await asyncio.wait_for(future, timeout)

    def calls(self, action):
        return [f[1][3] for f in self.frames if f[0] == "in" and f[1][0] == 2 and f[1][2] == action]


if __name__ == "__main__":
    import sys

    async def main():
        csms = await MockCsms(port=int(sys.argv[1]) if len(sys.argv) > 1 else 9220).start()
        print("mock CSMS on", csms.port, flush=True)
        await asyncio.Future()

    asyncio.run(main())
