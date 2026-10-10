"""Private ISO 15118 link and inbound firewall for the V2G App.

ISO 15118 discovery (SDP) is IPv6 link-local multicast, which loopback does not
carry. The App creates a veth pair inside its own network namespace: the
simulated charger uses one end and the simulated EV the other. Nothing is
bridged to the host or the LAN. This is the only use of NET_ADMIN.

The EVerest SDP server binds every interface, so an nftables policy drops all
inbound traffic on the Home Assistant network interface except Ingress from
the Supervisor and replies to this App's own outbound connections (OCPP).
Setup fails closed: if either step fails, no EVerest process starts.
"""
from pathlib import Path
import subprocess
import time

SECC_LINK = "v2g0"
EVCC_LINK = "v2g1"
SUPERVISOR = "172.30.32.2"
INGRESS_PORT = 8099
TABLE = "ha_everest_v2g"
IF_INET6 = Path("/proc/net/if_inet6")
TENTATIVE = 0x40


def ruleset():
    # add+delete first: one atomic transaction that replaces any earlier copy.
    return f"""add table inet {TABLE}
delete table inet {TABLE}
table inet {TABLE} {{
  chain input {{
    type filter hook input priority filter; policy drop;
    iif "lo" counter accept comment "loopback"
    iifname {{ "{SECC_LINK}", "{EVCC_LINK}" }} counter accept comment "private V2G link"
    ct state invalid counter drop comment "invalid"
    ct state established,related counter accept comment "replies to outbound"
    ip saddr {SUPERVISOR} tcp dport {INGRESS_PORT} counter accept comment "Supervisor Ingress"
    icmpv6 type {{ nd-neighbor-solicit, nd-neighbor-advert, nd-router-advert }} counter accept comment "neighbour discovery"
    counter comment "dropped by policy"
  }}
  chain output {{
    type filter hook output priority filter; policy accept;
    oifname != {{ "lo", "{SECC_LINK}", "{EVCC_LINK}" }} udp dport 15118 counter drop comment "SDP kept on the private link"
  }}
}}
"""


def link_local(name, text=None):
    """Usable (non-tentative) fe80::/10 address on interface `name`, or None."""
    if text is None:
        try:
            text = IF_INET6.read_text()
        except OSError:
            return None
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 6 or fields[5] != name:
            continue
        address, scope, flags = fields[0], int(fields[3], 16), int(fields[4], 16)
        if scope == 0x20 and address.startswith("fe8") and not flags & TENTATIVE:
            return ":".join(address[i:i + 4] for i in range(0, 32, 4))
    return None


def setup(run=subprocess.run, timeout=15, sleep=time.sleep):
    """Apply the firewall, create the veth pair and wait for link-local addresses."""
    applied = run(["nft", "-f", "-"], input=ruleset(), text=True,
                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if applied.returncode != 0:
        raise RuntimeError("could not apply the inbound firewall (nftables): "
                           + (applied.stdout or "").strip()[:200])
    exists = run(["ip", "link", "show", SECC_LINK], stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL).returncode == 0
    commands = [] if exists else [["ip", "link", "add", SECC_LINK, "type", "veth", "peer", "name", EVCC_LINK]]
    commands += [["ip", "link", "set", SECC_LINK, "up"], ["ip", "link", "set", EVCC_LINK, "up"]]
    for command in commands:
        result = run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed: " + (result.stdout or "").strip()[:200])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if link_local(SECC_LINK) and link_local(EVCC_LINK):
            return
        sleep(0.2)
    raise RuntimeError("no IPv6 link-local address on the private ISO 15118 link; "
                       "IPv6 may be disabled in this container")
