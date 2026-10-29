import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = self.root / "target"
        self.target.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, target=None, env=None):
        return subprocess.run([str(INSTALLER), str(target or self.target)], text=True,
                              capture_output=True, env=env)

    def test_installs_without_overwriting_unrelated_content_and_conflicts_atomically(self):
        unrelated = self.target / ".concord/keep.txt"
        unrelated.parent.mkdir()
        unrelated.write_text("preserve")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / "concordw").stat().st_mode & 0o111)
        self.assertEqual(unrelated.read_text(), "preserve")
        before = (self.target / "concordw").read_bytes()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.target / "concordw").read_bytes(), before)

    def test_conflicting_properties_does_not_install_launcher(self):
        wrapper_dir = self.target / ".concord/wrapper"
        wrapper_dir.mkdir(parents=True)
        conflict = wrapper_dir / "concord-wrapper.properties"
        conflict.symlink_to(self.root / "missing")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.target / "concordw").exists())
        self.assertTrue(conflict.is_symlink())

    def test_second_publication_failure_rolls_back_only_created_files(self):
        shim_dir = self.root / "bin"
        shim_dir.mkdir()
        count = self.root / "ln-count"
        shim = shim_dir / "ln"
        shim.write_text("#!/bin/sh\nn=$(cat \"$LN_COUNT\" 2>/dev/null || printf 0)\nn=$((n + 1))\nprintf '%s' \"$n\" > \"$LN_COUNT\"\n[ \"$n\" -eq 2 ] && exit 1\nexec /bin/ln \"$@\"\n")
        shim.chmod(0o755)
        env = os.environ.copy()
        env.update({"PATH": str(shim_dir) + os.pathsep + env["PATH"], "LN_COUNT": str(count)})
        unrelated_dir = self.target / ".concord"
        unrelated_dir.mkdir()
        keep = unrelated_dir / "keep"
        keep.write_text("untouched")
        result = self.install(env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.target / "concordw").exists())
        self.assertFalse((self.target / ".concord/wrapper/concord-wrapper.properties").exists())
        self.assertEqual(keep.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
