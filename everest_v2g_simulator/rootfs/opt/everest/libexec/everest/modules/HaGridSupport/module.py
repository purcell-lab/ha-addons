"""grid_support provider for the simulated DC V2G charger (purcell-lab/ha-addons).

Not part of EVerest. OCPPmulti enables its DER device-model component
(DCDERCtrlr for a DC EVSE) only when a grid_support provider publishes a
capability, and libocpp answers a SetDERControl NotSupported unless its
controlType is in that component's ModesSupported. Evse15118D20 provides
grid_support but publishes no capability, so this module declares one for the
simulated charger, writes every active directive set OCPPmulti pushes to a
JSON file for the App's Status page, and forwards the set unchanged to the
optional `relay` (Evse15118D20). Grid alarms from the relay are passed on.

Nothing here changes power. A forwarded set takes effect only where the relay
acts on it: Evse15118D20 maps curve directives onto AC DER sessions
(ISO 15118-20 AC_DER_IEC/SAE); this App's EV runs DC_BPT.
"""
import json
import os
from pathlib import Path
import queue
import threading
import time

ALARMS_KEPT = 10


def capability(config):
    """EVSECapability (types/grid_support.yaml) for a DC EVSE from the module config."""
    types = [t.strip() for t in str(config.get("supported_types", "")).split(",") if t.strip()]
    watts = float(config.get("rated_power_W", 25000))
    return {
        "evse_id": int(config.get("evse_id", 1)),
        "capability": {
            "supported_types": types,
            "nameplate": {
                "max_w_W": watts,
                "max_va_VA": watts,
                "v_nom_V": float(config.get("nominal_voltage_V", 380)),
                "max_charge_w_W": watts,
                "max_discharge_w_W": watts,
            },
            "dc": {"device_info": {"manufacturer": "purcell-lab", "model": "EVerest-SIL-DC-V2G",
                                   "sw_version": "ha-addons"}},
        },
    }


class DerState:
    """The module's view, written atomically to `path` after every change."""

    def __init__(self, path, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.lock = threading.Lock()
        self.state = {"capability": None, "capability_at": None, "active": None, "active_at": None,
                      "updates": 0, "relay": "not connected", "relay_at": None, "alarms": []}

    def update(self, **values):
        with self.lock:
            self.state.update(values)
            self.write()

    def set_capability(self, value):
        self.update(capability=value, capability_at=self.clock())

    def set_active(self, directive_set):
        with self.lock:
            self.state["active"] = directive_set
            self.state["active_at"] = self.clock()
            self.state["updates"] += 1
            self.write()

    def add_alarm(self, alarm):
        with self.lock:
            self.state["alarms"] = (self.state["alarms"] + [{"at": self.clock(), "alarm": alarm}])[-ALARMS_KEPT:]
            self.write()

    def write(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(json.dumps(self.state))
            os.chmod(temporary, 0o644)
            temporary.replace(self.path)
        except OSError:
            pass  # the Status page shows the file as missing; directives are unaffected


def main():
    from everest.framework import Module, RuntimeSession, log

    session = RuntimeSession()
    module = Module(session)
    log.update_process_name(module.info.id)
    setup = module.say_hello()
    config = setup.configs.module
    state = DerState(config.get("state_file", "/run/ha-everest/der.json"))
    relays = setup.connections.get("relay", [])
    state.update(relay="connected" if relays else "not connected")
    pending = queue.Queue()

    def forward():
        # Separate thread: a command call from inside a command handler would
        # wait on the thread that has to deliver its result.
        while True:
            directive_set = pending.get()
            for relay in relays:
                try:
                    result = module.call_command(relay, "set_active_directives", {"directives": directive_set})
                    accepted = isinstance(result, dict) and result.get("accepted") is True
                    state.update(relay="accepted" if accepted else f"rejected: {result}", relay_at=time.time())
                except Exception as error:  # report, keep forwarding later sets
                    state.update(relay=f"error: {type(error).__name__}: {error}", relay_at=time.time())
                    log.warning(f"HaGridSupport: forwarding to the relay failed: {error}")

    def set_active_directives(args):
        directive_set = args.get("directives") or {}
        state.set_active(directive_set)
        count = len(directive_set.get("directives") or [])
        log.info(f"HaGridSupport: {count} active DER directive(s) for EVSE {directive_set.get('evse_id')}: "
                 + ", ".join(f"{d.get('directive_type')} {d.get('id')}" for d in directive_set.get("directives") or [])
                 + " (recorded, not applied to power)")
        if relays:
            pending.put(directive_set)
        return {"accepted": True}

    def on_alarm(alarm):
        state.add_alarm(alarm)
        module.publish_variable("main", "alarm", alarm)

    module.implement_command("main", "set_active_directives", set_active_directives)
    for relay in relays:
        module.subscribe_variable(relay, "alarm", on_alarm)

    def ready():
        value = capability(config)
        module.publish_variable("main", "capability", value)
        state.set_capability(value)
        log.info(f"HaGridSupport: DC DER capability published for EVSE {value['evse_id']} "
                 f"({len(value['capability']['supported_types'])} control types)")

    threading.Thread(target=forward, daemon=True).start()
    module.init_done(ready)
    threading.Event().wait()


if __name__ == "__main__":
    main()
