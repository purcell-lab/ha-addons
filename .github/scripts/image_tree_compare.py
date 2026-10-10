#!/usr/bin/env python3
"""Compare the file trees of two container images.

Usage:
  image_tree_compare.py REFERENCE CANDIDATE [--strict PREFIX ...] [--report FILE]

Both images are exported with `docker create` and `docker export`. Every
path is recorded with its type, permission bits, owner, and either the
SHA-256 of its content (files) or its target (links). Timestamps are not
compared.

Paths under a --strict prefix must be identical: any added, removed or
changed path there fails the check (exit 1). Differences elsewhere are
listed for information only, because the Debian packages are resolved by
apt at build time and can move between builds.
"""
import argparse
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


def tree_from_tar(stream):
    """Map normalised path -> record, from an uncompressed tar stream."""
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
                for chunk in iter(lambda: handle.read(1 << 20), b""):
                    digest.update(chunk)
                record["sha256"] = digest.hexdigest()
                record["size"] = member.size
            elif member.issym() or member.islnk():
                record["target"] = normalise(member.linkname) if member.islnk() else member.linkname
            tree[path] = record
    return tree


def image_tree(image):
    container = subprocess.run(["docker", "create", image, "/bin/true"], check=True,
                               capture_output=True, text=True).stdout.strip()
    try:
        export = subprocess.Popen(["docker", "export", container], stdout=subprocess.PIPE)
        tree = tree_from_tar(export.stdout)
        if export.wait() != 0:
            raise RuntimeError(f"docker export failed for {image}")
        return tree
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


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


def summarise(entries, limit=40):
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

    reference, candidate = image_tree(args.reference), image_tree(args.candidate)
    strict_diffs, other = compare(reference, candidate, strict)
    checked = [p for p in candidate if under(p, strict)]
    files = [p for p in checked if candidate[p]["type"] == "file"]
    print(f"reference {args.reference}: {len(reference)} paths")
    print(f"candidate {args.candidate}: {len(candidate)} paths")
    print(f"strict prefixes {', '.join('/' + p for p in strict)}: {len(checked)} paths "
          f"({len(files)} files) compared, {len(strict_diffs)} differences")
    print("\n".join(summarise(strict_diffs)))
    print(f"outside the strict prefixes: {len(other)} differences (information only)")
    print("\n".join(summarise(other)))
    if args.report:
        with open(args.report, "w") as handle:
            json.dump({"reference": args.reference, "candidate": args.candidate, "strict": strict,
                       "strict_paths": len(checked), "strict_files": len(files),
                       "strict_differences": strict_diffs, "other_differences": other},
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
