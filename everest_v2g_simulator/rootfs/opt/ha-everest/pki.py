"""Per-install ISO 15118-20 test PKI for the simulated charger and EV.

ISO 15118-20 requires TLS 1.3 with mutual authentication, so both simulators
need certificates. Instead of shipping published demo keys, each install
generates its own chain with Josev's create_certs.sh, under a random key
password. The chain is test-only: it never leaves the App and never trusts or
is trusted by real vehicles or chargers. The 60-day leaf certificates are
renewed on start when they are close to expiry.
"""
from pathlib import Path
import re
import secrets
import shutil
import subprocess

JOSEV_PKI = Path("/opt/everest/libexec/everest/3rd_party/josev/iso15118/shared/pki")
LEAVES = ("client/cso/SECC_LEAF.pem", "client/vehicle/VEHICLE_LEAF.pem")
PASSWORD_FILE = "client/cso/SECC_LEAF_PASSWORD.txt"
RENEW_MARGIN_S = 7 * 86400
PASSWORD = re.compile(r"[0-9a-f]{24}")


def password(certs):
    value = (certs / PASSWORD_FILE).read_text().strip()
    if not PASSWORD.fullmatch(value):
        raise ValueError("invalid stored PKI key password")
    return value


def valid(certs, margin=RENEW_MARGIN_S):
    """True when both TLS leaves exist and stay valid for at least `margin`."""
    try:
        password(certs)
    except (OSError, ValueError):
        return False
    for leaf in LEAVES:
        path = certs / leaf
        if not path.is_file():
            return False
        check = subprocess.run(
            ["openssl", "x509", "-noout", "-checkend", str(int(margin)), "-in", str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if check.returncode != 0:
            return False
    return True


def generate(certs, script_dir=JOSEV_PKI):
    """Create a fresh chain next to `certs`, then swap it in."""
    work = certs.parent / "pki-work"
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(script_dir, work)
    key_password = secrets.token_hex(12)
    # The script prints the password; keep its output out of the App log.
    # keytool (Java keystores for other tools) is optional and not installed.
    subprocess.run(["bash", "create_certs.sh", "-v", "iso-20", "-p", key_password],
                   cwd=work, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    fresh = work / "iso15118_20" / "certs"
    if password(fresh) != key_password or not valid(fresh, margin=0):
        raise ValueError("generated test PKI is incomplete")
    old = certs.parent / "certs.old"
    shutil.rmtree(old, ignore_errors=True)
    if certs.exists():
        certs.rename(old)
    fresh.rename(certs)
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
    return key_password


def ensure(data, script_dir=JOSEV_PKI):
    """Return (key_password, certs_dir, regenerated)."""
    certs = data / "pki" / "certs"
    certs.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if valid(certs):
        return password(certs), certs, False
    return generate(certs, script_dir), certs, True


def link(prefix, certs):
    """EvseSecurity and Josev both read <prefix>/etc/everest/certs."""
    target = prefix / "etc" / "everest" / "certs"
    if target.is_symlink():
        if target.resolve() == certs.resolve():
            return
        target.unlink()
    elif target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(certs)
