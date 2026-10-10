"""Fail if anything other than nginx's Ingress port listens beyond loopback."""
import sys

allowed_public = {8099}
bad = []
for name in ("/proc/net/tcp", "/proc/net/tcp6"):
    try:
        rows = open(name).read().splitlines()[1:]
    except OSError:
        continue
    for row in rows:
        local, state = row.split()[1], row.split()[3]
        if state != "0A":  # LISTEN
            continue
        address, port = local.rsplit(":", 1)
        port = int(port, 16)
        loopback = address in ("0100007F", "00000000000000000000000001000000")
        if not loopback and port not in allowed_public:
            bad.append((address, port))
print("listeners outside loopback:", bad or "none (only Ingress 8099)")
sys.exit(1 if bad else 0)
