#!/usr/bin/env python3
"""Compare the file trees of two container images.

Usage:
  image_tree_compare.py REFERENCE CANDIDATE [--strict PREFIX ...] [--report FILE]

Both images are exported with `docker create` and `docker export`. Every
path is recorded with its type, permission bits, owner, and either the
SHA-256 of its content (files) or its target (links). Timestamps are not
compared. For timestamp-based Python bytecode (.pyc, PEP 552 flags 0) the
4-byte source mtime field is the build checkout time, so it is excluded
from the hash; magic, flags, source size and code are still compared.
Python's marshal output is not byte-reproducible across builds (reference
flags depend on object identity), so a .pyc pair that still differs is
loaded with the candidate image's own python3 and accepted only if the
code objects compare equal (bytecode, constants, names, line tables).

Paths under a --strict prefix must be identical: any added, removed or
changed path there fails the check (exit 1). Differences elsewhere are
listed for information only, because the Debian packages are resolved by
apt at build time and can move between builds.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tarfile

def normalise(name):
    while name.startswith("./"):
        name = name[2:]
    return name.strip("/")


TYPES = {tarfile.REGTYPE: "file", tarfile.AREGTYPE: "file", tarfile.DIRTYPE: "dir",
         tarfile.SYMTYPE: "symlink", tarfile.LNKTYPE: "hardlink",
         tarfile.CHRTYPE: "char", tarfile.BLKTYPE: "block", tarfile.FIFOTYPE: "fifo"}

# Created by `docker create` itself, not by the image build.
DOCKER_CREATED = {".dockerenv", "etc/hostname", "etc/hosts", "etc/resolv.conf", "proc", "sys", "dev"}


def tree_from_tar(stream, pyc=None):
    """Map normalised path -> record, from an uncompressed tar stream.

    If `pyc` is a dict, raw .pyc bytes are stored in it by path."""
    tree = {}
    with tarfile.open(fileobj=stream, mode="r|") as tar:
        for member in tar:
            path = normalise(member.name)
            if not path or path in DOCKER_CREATED or path.split("/")[0] in ("proc", "sys", "dev"):
                continue
            record = {"type": TYPES.get(member.type, f"other:{member.type!r}"),
                      "mode": oct(member.mode & 0o7777), "uid": member.uid, "gid": member.gid}
            if member.isfile():
                digest = hashlib.sha256()
                handle = tar.extractfile(member)
                if path.endswith(".pyc"):
                    data = handle.read()
                    if pyc is not None:
                        pyc[path] = data
                    if len(data) >= 16 and data[4:8] == b"\0\0\0\0":
                        data = data[:8] + data[12:]
                        record["pyc_mtime_ignored"] = True
                    digest.update(data)
                else:
                    for chunk in iter(lambda: handle.read(1 << 20), b""):
                        digest.update(chunk)
                record["sha256"] = digest.hexdigest()
                record["size"] = member.size
            elif member.issym() or member.islnk():
                record["target"] = normalise(member.linkname) if member.islnk() else member.linkname
            tree[path] = record
    return tree


def image_tree(image, pyc=None):
    container = subprocess.run(["docker", "create", image, "/bin/true"], check=True,
                               capture_output=True, text=True).stdout.strip()
    try:
        export = subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE)
        tree = tree_from_tar(export.stdout, pyc)
        if export.wait() != 0:
            raise RuntimeError(f"docker export failed for {image}")
        return tree
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


EQUIVALENT_PYC = r"""
import base64, json, marshal, sys
out = {}
for path, (a, b) in json.load(sys.stdin).items():
    try:
        out[path] = marshal.loads(base64.b64decode(a)[16:]) == marshal.loads(base64.b64decode(b)[16:])
    except Exception as exc:
        out[path] = False
print(json.dumps(out))
"""


def equivalent_pyc(image, pairs):
    """Return {path: bool} using the image's python3 to compare code objects."""
    if not pairs:
        return {}
    payload = json.dumps({p: [base64.b64encode(a).decode(), base64.b64encode(b).decode()]
                          for p, (a, b) in pairs.items()})
    result = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none",
                             "--entrypoint", "python3", image, "-c", EQUIVALENT_PYC],
                            input=payload, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def under(path, prefixes):
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def compare(reference, candidate, strict):
    """Return (strict_differences, other_differences), each a sorted list."""
    strict_diffs, other = [], []
    for path in sorted(set(reference) | set(candidate)):
        old, new = reference.get(path), candidate.get(path)
        if old == new:
            continue
        if old is None:
            entry = {"path": path, "change": "added", "candidate": new}
        elif new is None:
            entry = {"path": path, "change": "removed", "reference": old}
        else:
            fields = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
            entry = {"path": path, "change": "changed", "fields": fields,
                     "reference": old, "candidate": new}
        (strict_diffs if under(path, strict) else other).append(entry)
    return strict_diffs, other


def summarise(entries, limit=200):
    lines = []
    for entry in entries[:limit]:
        detail = ",".join(entry.get("fields", [])) if entry["change"] == "changed" else ""
        lines.append(f"  {entry['change']:8} {entry['path']} {detail}".rstrip())
    if len(entries) > limit:
        lines.append(f"  ... and {len(entries) - limit} more")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference")
    parser.add_argument("candidate")
    parser.add_argument("--strict", action="append", default=[],
                        help="path prefix (no leading slash) that must be identical")
    parser.add_argument("--report", help="write the full comparison as JSON")
    args = parser.parse_args(argv)
    strict = [p.strip("/") for p in args.strict]

    ref_pyc, cand_pyc = {}, {}
    reference = image_tree(args.reference, ref_pyc)
    candidate = image_tree(args.candidate, cand_pyc)
    strict_diffs, other = compare(reference, candidate, strict)
    pairs = {e["path"]: (ref_pyc[e["path"]], cand_pyc[e["path"]]) for e in strict_diffs
             if e["change"] == "changed" and e["fields"] == ["sha256"] and e["path"].endswith(".pyc")}
    same = equivalent_pyc(args.candidate, pairs)
    pyc_equal = [e for e in strict_diffs if same.get(e["path"])]
    strict_diffs = [e for e in strict_diffs if not same.get(e["path"])]
    checked = [p for p in candidate if under(p, strict)]
    files = [p for p in checked if candidate[p]["type"] == "file"]
    print(f"reference {args.reference}: {len(reference)} paths")
    print(f"candidate {args.candidate}: {len(candidate)} paths")
    print(f"strict prefixes {', '.join('/' + p for p in strict)}: {len(checked)} paths "
          f"({len(files)} files) compared, {len(strict_diffs)} differences")
    if pyc_equal:
        print(f"  {len(pyc_equal)} .pyc differ only in marshal encoding; code objects are equal")
    print("\n".join(summarise(strict_diffs)))
    print(f"outside the strict prefixes: {len(other)} differences (information only)")
    print("\n".join(summarise(other)))
    if args.report:
        with open(args.report, "w") as handle:
            json.dump({"reference": args.reference, "candidate": args.candidate, "strict": strict,
                       "strict_paths": len(checked), "strict_files": len(files),
                       "strict_differences": strict_diffs,
                       "pyc_code_equal": [e["path"] for e in pyc_equal], "other_differences": other},
                      handle, indent=1)
    if not checked:
        print("::error::no paths under the strict prefixes; check the prefixes")
        return 1
    if strict_diffs:
        print(f"::error::{len(strict_diffs)} differences under the strict prefixes")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
