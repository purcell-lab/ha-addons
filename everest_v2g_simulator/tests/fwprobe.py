"""Probe the V2G App from another host (or from inside it, as a control).

usage: fwprobe.py expect-silence|expect-reachable ADDRESS [ADDRESS ...]
       fwprobe.py private-link

expect-silence    from another host: no SDP reply (UDP 15118) and TCP 8099
                  (nginx listens on every address) and 50000 time out, which
                  means dropped by nftables, not refused
expect-reachable  negative control after the nftables table is deleted:
                  TCP 8099 must connect, proving the drop came from nftables
private-link      inside the App: the SDP server answers on the private
                  v2g0 link (positive control that discovery is live)
Upstream's SDP server binds :: but only answers on its configured interface,
so the firewall is defence in depth for UDP and the boundary for TCP.
"""
import json
import socket
import sys

# V2GTP v1, payload type 0x9000 (SDP request), length 2: no TLS (0x10), TCP (0x00).
SDP_REQUEST = bytes.fromhex("01fe9000000000021000")
SDP_RESPONSE_TYPE = bytes.fromhex("01fe9001")


def family(address):
    return socket.AF_INET6 if ":" in address else socket.AF_INET


def sdp(address, timeout=3.0, scope=None):
    with socket.socket(family(address), socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        target = (address, 15118, 0, socket.if_nametoindex(scope)) if scope else (address, 15118)
        sock.sendto(SDP_REQUEST, target)
        try:
            data, _ = sock.recvfrom(256)
        except (socket.timeout, ConnectionRefusedError):
            return "silent"
    return "reply" if data.startswith(SDP_RESPONSE_TYPE) else "other:" + data[:8].hex()


def tcp(address, port, timeout=3.0):
    with socket.socket(family(address), socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((address, port))
        except socket.timeout:
            return "dropped"
        except ConnectionRefusedError:
            return "refused"
        except OSError as error:
            return f"error:{error.errno}"
    return "connected"


def secc_address():
    sys.path.insert(0, "/opt/ha-everest")
    import netguard
    return netguard.link_local(netguard.SECC_LINK), netguard.EVCC_LINK


def main(argv):
    expectation, addresses = argv[0], argv[1:]
    results, ok = {}, True
    if expectation == "private-link":
        address, via = secc_address()
        results[f"{address}%{via}"] = {"sdp_15118_udp": sdp(address, scope=via)}
        ok = results[f"{address}%{via}"]["sdp_15118_udp"] == "reply"
    else:
        assert expectation in ("expect-silence", "expect-reachable") and addresses, __doc__
    for address in addresses:
        if expectation == "expect-silence":
            result = {"sdp_15118_udp": sdp(address), "tcp_8099": tcp(address, 8099),
                      "tcp_50000": tcp(address, 50000)}
            ok &= result["sdp_15118_udp"] == "silent"
            ok &= result["tcp_8099"] == "dropped" and result["tcp_50000"] == "dropped"
        else:
            result = {"tcp_8099": tcp(address, 8099)}
            ok &= result["tcp_8099"] == "connected"
        results[address] = result
    print(json.dumps({"expectation": expectation, "pass": ok, "results": results}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
