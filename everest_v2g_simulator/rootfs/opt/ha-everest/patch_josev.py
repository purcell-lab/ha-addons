"""Build-time patch: a fresh simulated-EV ISO 15118 stack on every plug-in.

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


def patch(text):
    if MARKER in text:
        return text
    for anchor in (LOOP_ANCHOR, START_ANCHOR):
        if text.count(anchor) != 1:
            raise ValueError("PyEvJosev module.py does not match the expected upstream text")
    return text.replace(LOOP_ANCHOR, LOOP_REPLACEMENT).replace(START_ANCHOR, START_REPLACEMENT)


def main(path=TARGET):
    path = Path(path)
    patched = patch(path.read_text())
    compile(patched, str(path), "exec")
    path.write_text(patched)
    print(f"patched {path}")


if __name__ == "__main__":
    try:
        main(*sys.argv[1:])
    except (OSError, ValueError, SyntaxError) as error:
        print(f"patch_josev: {error}", file=sys.stderr)
        sys.exit(1)
