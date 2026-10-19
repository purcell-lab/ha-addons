"""Build-time patches to the simulated EV (PyEvJosev and Josev).

1. Josev's UDP client sends SDP on the configured interface (v2g1).
2. A fresh simulated-EV ISO 15118 stack on every plug-in.
3. The simulated EV discharges up to 25 kW (66 A) instead of 11 kW (25 A).
4. The simulated EV waits for authorisation as long as the charger does
   (3 minutes) instead of 60 s.

Upstream PyEvJosev (EVerest 2025.10.0) runs one Josev EVCC per plug-in with
asyncio.run(). When discovery fails, Josev logs SDPFailedError but its
session handler keeps waiting, so asyncio.run() never returns and every
later plug-in is ignored until the App restarts. Other errors end the loop
(only KeyboardInterrupt is caught), with the same effect.

This patch runs each EVCC on its own event loop. A new plug-in cancels a
stack that is still running, errors are logged and reported as a finished
session, and the plug-in event is cleared before each run so a plug-in
during a run is never lost.

The build fails if the upstream text differs, so a new EVerest version
cannot silently drop the patch.
"""
from pathlib import Path
import sys

TARGET = Path("/opt/everest/libexec/everest/modules/PyEvJosev/module.py")
MARKER = "ha-everest: EV ISO 15118 stack stopped"
LOOP_ANCHOR = """    def start_evcc_handler(self):
        while True:
            self._ready_event.wait()
            try:
                asyncio.run(evcc_handler_main_loop(self._setup.configs.module))
                self._mod.publish_variable('ev', 'v2g_session_finished', None)
            except KeyboardInterrupt:
                log.debug("SECC program terminated manually")
                break
            self._ready_event.clear()
"""
LOOP_REPLACEMENT = """    def start_evcc_handler(self):
        # ha-everest patch (patch_josev.py): one fresh EVCC per plug-in.
        self._ha_stack = None
        while True:
            self._ready_event.wait()
            self._ready_event.clear()
            loop = asyncio.new_event_loop()
            task = loop.create_task(evcc_handler_main_loop(self._setup.configs.module))
            self._ha_stack = (loop, task)
            try:
                loop.run_until_complete(task)
            except KeyboardInterrupt:
                log.debug("SECC program terminated manually")
                break
            except asyncio.CancelledError:
                log.error("ha-everest: EV ISO 15118 stack stopped (replaced by a new plug-in); "
                          "starting a fresh stack")
            except Exception as error:
                log.error(f"ha-everest: EV ISO 15118 stack stopped ({type(error).__name__}: {error}); "
                          "a fresh stack starts on the next plug-in")
            finally:
                self._ha_stack = None
                pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for leftover in pending:
                    leftover.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            self._mod.publish_variable('ev', 'v2g_session_finished', None)
"""
START_ANCHOR = """        self._es.EnergyTransferMode = args['EnergyTransferMode']

        self._ready_event.set()
"""
START_REPLACEMENT = """        self._es.EnergyTransferMode = args['EnergyTransferMode']

        # ha-everest patch: a stack still running from an earlier plug-in
        # (for example idle after a failed discovery) is cancelled first.
        stack = getattr(self, '_ha_stack', None)
        if stack is not None and not stack[1].done():
            stack[0].call_soon_threadsafe(stack[1].cancel)
        self._ready_event.set()
"""


UDP_TARGET = Path("/opt/everest/libexec/everest/3rd_party/josev/iso15118/evcc/transport/udp_client.py")
UDP_MARKER = "ha-everest: send SDP on the configured interface"
UDP_ANCHOR = """        interface_index = socket.if_nametoindex(iface)
        # sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, interface_index)
"""
# Upstream leaves the interface unset, so the kernel picks the default
# multicast route: the private link in CI (no other interface), but eth0 on
# Home Assistant OS, where the charger never sees the request.
UDP_REPLACEMENT = """        interface_index = socket.if_nametoindex(iface)
        # ha-everest: send SDP on the configured interface (patch_josev.py)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, interface_index)
"""


SIM_TARGET = Path("/opt/everest/libexec/everest/3rd_party/josev/iso15118/evcc/controller/simulator.py")
SIM_MARKER = "ha-everest: 25 kW EV discharge"
# Josev 2025.9.0 hard-codes the EV's ISO 15118-20 BPT discharge limits (charge
# parameter discovery and the dynamic DC loop): 25 A, which at the DC supply's
# voltage capped discharge at 5 kW, and 11 kW. 66 A at 380 V is 25 kW.
SIM_CURRENT = ("ev_max_discharge_current=RationalNumber(exponent=0, value=25),",
               "ev_max_discharge_current=RationalNumber(exponent=0, value=66),  "
               "# ha-everest: 25 kW EV discharge (patch_josev.py)")
SIM_POWER = ("ev_max_discharge_power=RationalNumber(exponent=3, value=11),",
             "ev_max_discharge_power=RationalNumber(exponent=3, value=25),")


AUTH_TARGET = Path("/opt/everest/libexec/everest/3rd_party/josev/iso15118/evcc/states/iso15118_20_states.py")
AUTH_MARKER = "ha-everest: EV waits for authorisation as long as the charger"
# Josev 2025.9.0 gives up 60 s after the first Ongoing AuthorizationRes and,
# with PyEvJosev's single SDP retry cycle, never starts another session in
# that plug-in, so a RequestStartTransaction about 60 s after plug-in left
# the transaction at 0 W (issue #33). The charger (libiso15118 v0.9.0)
# answers Ongoing for 3 minutes (TIMEOUT_EIM_ONGOING) before it fails the
# session; the EV now waits slightly longer, so the charger decides.
AUTH_WAIT_S = 190
AUTH_IMPORT = "from iso15118.shared.messages.timeouts import Timeouts as TimeoutsShared\n"
AUTH_TIMEOUT = "TimeoutsShared.V2G_EVCC_ONGOING_TIMEOUT"


def patch_auth(text):
    if AUTH_MARKER in text:
        return text
    # Upstream uses the shared ongoing timeout only in the Authorization state.
    if text.count(AUTH_IMPORT) != 1 or text.count(AUTH_TIMEOUT) != 2:
        raise ValueError("Josev iso15118_20_states.py does not match the expected upstream text")
    constant = (f"# {AUTH_MARKER} (patch_josev.py)\n"
                f"HA_EVEREST_AUTH_WAIT_S = {AUTH_WAIT_S}\n")
    return text.replace(AUTH_TIMEOUT, "HA_EVEREST_AUTH_WAIT_S").replace(AUTH_IMPORT, AUTH_IMPORT + constant)


def patch_sim(text):
    if SIM_MARKER in text:
        return text
    if text.count(SIM_CURRENT[0]) != 2 or text.count(SIM_POWER[0]) != 3:
        raise ValueError("Josev simulator.py does not match the expected upstream text")
    return text.replace(*SIM_CURRENT).replace(*SIM_POWER)


def patch_udp(text):
    if UDP_MARKER in text:
        return text
    if text.count(UDP_ANCHOR) != 1:
        raise ValueError("Josev udp_client.py does not match the expected upstream text")
    return text.replace(UDP_ANCHOR, UDP_REPLACEMENT)


def patch(text):
    if MARKER in text:
        return text
    for anchor in (LOOP_ANCHOR, START_ANCHOR):
        if text.count(anchor) != 1:
            raise ValueError("PyEvJosev module.py does not match the expected upstream text")
    return text.replace(LOOP_ANCHOR, LOOP_REPLACEMENT).replace(START_ANCHOR, START_REPLACEMENT)


def apply(path, function):
    path = Path(path)
    patched = function(path.read_text())
    compile(patched, str(path), "exec")
    path.write_text(patched)
    print(f"patched {path}")


def main(path=TARGET, udp_path=UDP_TARGET, sim_path=SIM_TARGET, auth_path=AUTH_TARGET):
    apply(path, patch)
    if udp_path:
        apply(udp_path, patch_udp)
    if sim_path:
        apply(sim_path, patch_sim)
    if auth_path:
        apply(auth_path, patch_auth)


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except (OSError, ValueError, SyntaxError) as error:
        print(f"patch_josev: {error}", file=sys.stderr)
        sys.exit(1)
