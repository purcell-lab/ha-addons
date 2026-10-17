"""Build-time patch: raise the simulated board's AC limits (YetiSimulator).

EVerest 2025.10.0's YetiSimulator reports fixed hardware capabilities of
32 A import and 16 A export per phase. EvseManager feeds them into energy
management for DC charging too, so on three phases at 230 V they cap the
charger at 22.08 kW charging and 11.04 kW discharging. Configuration can only
lower these values (EvseManager takes the minimum of the board and its own
max_current_import_A / max_current_export_A), so they are raised here to
128 A per phase, and the App's own per-phase setting (configure.ratings, up
to 109 A for 25 kW) is what actually applies.

The prebuilt binary is patched in place. Each architecture has an exact
SHA-256 and exact original bytes at each offset; the build fails on any
other binary, so a new EVerest version cannot be patched blindly.

- amd64: the function loads 32.0 and 16.0 from a .rodata block that no
  other code references (32.0, 6.0, 16.0 at 0x2fb174..0x2fb17f).
- arm64: the values are instruction immediates. 128.0 fits the same 4-byte
  MOVI encoding as 32.0 (movi v0.2s, #0x43, lsl #24), which also replaces the
  FMOV for 16.0 (an FMOV immediate cannot exceed 31.0).
"""
from pathlib import Path
import hashlib
import struct
import sys

TARGET = Path("/opt/everest/libexec/everest/modules/YetiSimulator/YetiSimulator")
BOARD_AMPS = 128.0
MOVI_32 = bytes.fromhex("4064020f")   # movi v0.2s, #0x42, lsl #24  (32.0)
MOVI_128 = bytes.fromhex("6064020f")  # movi v0.2s, #0x43, lsl #24  (128.0)
FMOV_16 = bytes.fromhex("0010261e")   # fmov s0, #16.0
F32 = struct.pack("<f", 32.0)
F16 = struct.pack("<f", 16.0)
F128 = struct.pack("<f", BOARD_AMPS)

# sha256 of the upstream binary -> (architecture, [(offset, original, patched)])
PATCHES = {
    "41ca9f86eb7c2c10ca6e200076b33308c5b6053f1e8a6478a2f61108a8a4d0ac": ("amd64", [
        (0x2FB174, F32, F128),       # max_current_A_import
        (0x2FB17C, F16, F128),       # max_current_A_export
    ]),
    "c2e43990ccb3dd415fb04e63a2bba427b427fe22f70c9443434e2feec6d00589": ("arm64", [
        (0x2F07F0, MOVI_32, MOVI_128),  # max_current_A_import
        (0x2F0810, FMOV_16, MOVI_128),  # max_current_A_export
    ]),
}


def patch(data):
    """Return (patched bytes, architecture); an already patched binary is unchanged."""
    entry = PATCHES.get(hashlib.sha256(data).hexdigest())
    if entry is None:
        for arch, edits in PATCHES.values():
            if all(data[o:o + len(new)] == new for o, _, new in edits):
                return data, arch
        raise ValueError("YetiSimulator does not match a known EVerest 2025.10.0 build")
    arch, edits = entry
    out = bytearray(data)
    for offset, old, new in edits:
        if out[offset:offset + len(old)] != old:
            raise ValueError(f"unexpected bytes at {offset:#x} ({arch})")
        out[offset:offset + len(new)] = new
    return bytes(out), arch


def main(path=TARGET, check=False):
    path = Path(path)
    data = path.read_bytes()
    patched, arch = patch(data)
    if check:
        if patched != data:
            raise ValueError(f"{path} is not patched ({arch})")
        print(f"{path} is patched ({arch})")
        return
    path.write_bytes(patched)
    print(f"patched {path} ({arch}): board limit {BOARD_AMPS:g} A per phase, both directions")


if __name__ == "__main__":
    try:
        args = [a for a in sys.argv[1:] if a != "--check"]
        main(*args, check="--check" in sys.argv[1:])
    except (OSError, ValueError) as error:
        print(f"patch_yeti: {error}", file=sys.stderr)
        sys.exit(1)
