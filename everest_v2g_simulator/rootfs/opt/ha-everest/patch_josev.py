"""Build-time patch: restart the simulated EV's ISO 15118 stack on every plug-in.

Upstream PyEvJosev (EVerest 2025.10.0) runs one Josev EVCC per plug-in in a
loop, but the loop only catches KeyboardInterrupt. Any other error, such as
SDPFailedError after an unanswered discovery request, ends the loop, and
every later plug-in is ignored until the whole App restarts. This patch logs
the error, reports the session as finished and waits for the next plug-in,
which starts a fresh EVCC (new asyncio loop, sockets and state).

The build fails if the upstream text differs, so a new EVerest version
cannot silently drop the patch.
"""
from pathlib import Path
import sys

TARGET = Path("/opt/everest/libexec/everest/modules/PyEvJosev/module.py")
MARKER = "ha-everest: EV ISO 15118 stack stopped"
ANCHOR = """            except KeyboardInterrupt:
                log.debug("SECC program terminated manually")
                break
            self._ready_event.clear()
"""
REPLACEMENT = """            except KeyboardInterrupt:
                log.debug("SECC program terminated manually")
                break
            except Exception as error:  # ha-everest patch (patch_josev.py)
                log.error(f"ha-everest: EV ISO 15118 stack stopped ({type(error).__name__}: {error}); "
                          "a fresh stack starts on the next plug-in")
                self._mod.publish_variable('ev', 'v2g_session_finished', None)
            self._ready_event.clear()
"""


def patch(text):
    if MARKER in text:
        return text
    if text.count(ANCHOR) != 1:
        raise ValueError("PyEvJosev module.py does not match the expected upstream text")
    return text.replace(ANCHOR, REPLACEMENT)


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
