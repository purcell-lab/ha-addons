"""Unit tests for image_tree_compare.py (synthetic tar streams, no Docker)."""
import io, sys, tarfile, unittest
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
import image_tree_compare as itc

def tar(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, kind, data, mode, extra in entries:
            info = tarfile.TarInfo(name); info.mode = mode; info.mtime = extra.get("mtime", 0)
            if kind == "dir": info.type = tarfile.DIRTYPE; t.addfile(info)
            elif kind == "sym": info.type = tarfile.SYMTYPE; info.linkname = data; t.addfile(info)
            else: info.size = len(data); t.addfile(info, io.BytesIO(data))
    buf.seek(0); return itc.tree_from_tar(buf)

BASE = [("opt/everest", "dir", None, 0o755, {}), ("opt/everest/bin/manager", "file", b"ELF1", 0o755, {}),
        ("opt/everest/lib/libx.so", "sym", "libx.so.1", 0o777, {}), ("var/log/dpkg.log", "file", b"a", 0o644, {}),
        (".dockerenv", "file", b"", 0o755, {}), ("etc/hostname", "file", b"h1", 0o644, {})]

class T(unittest.TestCase):
    def test_identical_ignores_mtime_and_docker_files(self):
        a = tar(BASE)
        b = tar([(n, k, d, m, {"mtime": 99}) if n != "etc/hostname" else (n, k, b"h2", m, {}) for n, k, d, m, _ in BASE])
        self.assertNotIn(".dockerenv", a); self.assertEqual(itc.compare(a, b, ["opt/everest"]), ([], []))
    def test_content_mode_link_and_added_paths_fail_strict(self):
        a = tar(BASE)
        b = tar([("opt/everest", "dir", None, 0o700, {}), ("opt/everest/bin/manager", "file", b"ELF2", 0o755, {}),
                 ("opt/everest/lib/libx.so", "sym", "libx.so.2", 0o777, {}), ("opt/everest/new", "file", b"", 0o644, {}),
                 ("var/log/dpkg.log", "file", b"b", 0o644, {})])
        strict, other = itc.compare(a, b, ["opt/everest"])
        got = {(e["path"], e["change"], tuple(e.get("fields", []))) for e in strict}
        self.assertEqual(got, {("opt/everest", "changed", ("mode",)), ("opt/everest/bin/manager", "changed", ("sha256",)),
                               ("opt/everest/lib/libx.so", "changed", ("target",)), ("opt/everest/new", "added", ())})
        self.assertEqual([e["path"] for e in other], ["var/log/dpkg.log"])
    def test_expected_differences_are_kind_and_prefix_specific(self):
        a = tar(BASE + [("opt/everest/share/www/i.html", "file", b"x", 0o644, {})])
        b = tar([e for e in BASE if e[0] != "opt/everest/lib/libx.so"]
                + [("opt/everest/bin/manager", "file", b"ELF2", 0o755, {})])
        strict, _ = itc.compare(a, b, ["opt/everest"])
        rules = [("removed", "opt/everest/lib/libx.so"), ("removed", "opt/everest/share/www"),
                 ("changed", "opt/everest/doc")]
        unexpected, expected, unused = itc.apply_expected(strict, rules)
        self.assertEqual({e["path"] for e in expected}, {"opt/everest/lib/libx.so", "opt/everest/share/www/i.html"})
        self.assertEqual([e["path"] for e in unexpected], ["opt/everest/bin/manager"])
        self.assertEqual(unused, [("changed", "opt/everest/doc")])
    def test_expected_file_format(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("# c\nremoved /opt/everest/x  # why\n\nchanged usr/doc/a\n")
        try:
            self.assertEqual(itc.load_expected(f.name), [("removed", "opt/everest/x"), ("changed", "usr/doc/a")])
            with open(f.name, "w") as g: g.write("deleted opt/x\n")
            with self.assertRaises(ValueError): itc.load_expected(f.name)
        finally:
            os.unlink(f.name)
    def test_pyc_ignores_only_the_source_mtime_field(self):
        head = b"\xa7\r\r\n" + b"\0\0\0\0"
        a = tar([("x/m.pyc", "file", head + b"\1\0\0\0" + b"\x10\0\0\0" + b"code", 0o644, {})])
        b = tar([("x/m.pyc", "file", head + b"\2\0\0\0" + b"\x10\0\0\0" + b"code", 0o644, {})])
        c = tar([("x/m.pyc", "file", head + b"\2\0\0\0" + b"\x11\0\0\0" + b"code", 0o644, {})])
        d = tar([("x/m.pyc", "file", head + b"\1\0\0\0" + b"\x10\0\0\0" + b"CODE", 0o644, {})])
        self.assertEqual(itc.compare(a, b, ["x"]), ([], []))
        self.assertEqual(len(itc.compare(a, c, ["x"])[0]), 1)  # source size differs
        self.assertEqual(len(itc.compare(a, d, ["x"])[0]), 1)  # code differs
        hashed = b"\xa7\r\r\n\1\0\0\0" + b"\1\0\0\0" + b"\x10\0\0\0" + b"code"
        e = tar([("x/m.pyc", "file", hashed, 0o644, {})]); f = tar([("x/m.pyc", "file", hashed[:8] + b"\2" + hashed[9:], 0o644, {})])
        self.assertEqual(len(itc.compare(e, f, ["x"])[0]), 1)  # hash-based pyc compared in full
    def test_prefix_is_a_path_boundary(self):
        self.assertTrue(itc.under("opt/everest/x", ["opt/everest"])); self.assertFalse(itc.under("opt/everest2", ["opt/everest"]))
    def test_dot_slash_and_dotfiles(self):
        self.assertEqual(itc.normalise("./.hidden"), ".hidden"); self.assertEqual(itc.normalise("./opt/"), "opt")
unittest.main(verbosity=1)
