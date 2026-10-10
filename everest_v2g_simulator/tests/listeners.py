"""Fail on any listener reachable beyond loopback except the expected ones.

TCP: nginx Ingress 8099 (any address, Supervisor-only by nginx ACL and
nftables) and the ISO 15118-20 TLS server on port 50000, which must be bound
to an IPv6 link-local address (the private v2g0 link). UDP: the SDP server
binds :: port 15118 upstream; the nftables input policy drops it on every
interface except the private link (checked separately by the firewall probe).
"""
import sys

TCP_ANY = {8099}
TCP_LINK_LOCAL = {50000}
UDP_ANY = {15118}
LOOPBACK = {"0100007F", "00000000000000000000000001000000"}


def link_local(address):
    # /proc/net/*6 prints each 32-bit word in host (little-endian) order.
    return len(address) == 32 and address[6:8] + address[4:6] == "FE80"


bad = []
for name, udp in (("/proc/net/tcp", False), ("/proc/net/tcp6", False),
                  ("/proc/net/udp", True), ("/proc/net/udp6", True)):
    try:
        rows = open(name).read().splitlines()[1:]
    except OSError:
        continue
    for row in rows:
        fields = row.split()
        local, state = fields[1], fields[3]
        if not udp and state != "0A":  # TCP LISTEN only
            continue
        address, port = local.rsplit(":", 1)
        port = int(port, 16)
        if address in LOOPBACK:
            continue
        if udp:
            if port in UDP_ANY or state == "01":  # 01: connected client socket
                continue
        elif port in TCP_ANY or (port in TCP_LINK_LOCAL and link_local(address)):
            continue
        bad.append((name.rsplit("/", 1)[1], address, port))
print("unexpected listeners:", bad or "none (Ingress 8099, link-local TLS 50000, SDP 15118/udp)")
sys.exit(1 if bad else 0)
