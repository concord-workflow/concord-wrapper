import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "concordw"


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project with spaces"
        (self.project / ".concord/wrapper").mkdir(parents=True)
        shutil.copy2(WRAPPER, self.project / "concordw")
        (self.project / "concordw").chmod(0o755)
        self.payload = b"not-a-real-jar-but-a-known-artifact"
        self.digest = hashlib.sha256(self.payload).hexdigest()
        self.url = "https://example.invalid/cli.jar"
        self.properties = self.project / ".concord/wrapper/concord-wrapper.properties"
        self.cache = self.root / "cache with spaces"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.java_log = self.root / "java.log"
        self._executable("java", "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$JAVA_LOG\"\nexit 0\n")
        self._executable("curl", "#!/bin/sh\nwhile [ \"$1\" != --output ]; do shift; done\nshift; out=$1\n[ \"${CURL_FAIL:-0}\" = 1 ] && { printf partial > \"$out\"; exit 22; }\nprintf '%s' \"$PAYLOAD\" > \"$out\"\n")
        self.environment = os.environ.copy()
        self.environment.update({"PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
                                 "XDG_CACHE_HOME": str(self.cache), "JAVA_LOG": str(self.java_log),
                                 "PAYLOAD": self.payload.decode().strip(), "JAVA_HOME": ""})
        self.write_properties()

    def tearDown(self):
        self.tmp.cleanup()

    def _executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)
        return path

    def write_properties(self, text=None):
        if text is None:
            text = f"distributionUrl={self.url}\ndistributionSha256Sum={self.digest}\n"
        self.properties.write_text(text)

    def run_wrapper(self, *args, env=None):
        return subprocess.run([str(self.project / "concordw"), *args], cwd=self.root,
                              env=env or self.environment, text=True, capture_output=True)

    def entry(self):
        return self.cache / "concord-wrapper" / self.digest / "concord-cli.jar"

    def test_bad_properties_never_execute_or_download(self):
        for text in ("", f"distributionUrl={self.url}\n", f"distributionUrl={self.url}\ndistributionSha256Sum={self.digest}\ndistributionUrl={self.url}\n",
                     f"distributionUrl={self.url}\ndistributionSha256Sum={self.digest}\nunknown=x\n",
                     f"distributionUrl=$(touch {self.root}/marker)\ndistributionSha256Sum={self.digest}\n"):
            with self.subTest(text=text):
                self.write_properties(text)
                self.java_log.unlink(missing_ok=True)
                result = self.run_wrapper("--version")
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.java_log.exists())
                self.assertFalse((self.root / "marker").exists())
                self.assertFalse(self.entry().exists())

    def test_failed_and_bad_downloads_do_not_publish(self):
        failed_env = self.environment | {"CURL_FAIL": "1"}
        self.assertNotEqual(self.run_wrapper("x", env=failed_env).returncode, 0)
        self.assertFalse(self.entry().exists())
        bad_env = self.environment | {"PAYLOAD": "wrong"}
        self.assertNotEqual(self.run_wrapper("x", env=bad_env).returncode, 0)
        self.assertFalse(self.entry().exists())
        self.assertEqual(self.run_wrapper("x").returncode, 0)
        self.assertEqual(self.entry().read_bytes(), self.payload)

    def test_verified_cache_is_offline_and_tampering_fails(self):
        self.assertEqual(self.run_wrapper("--version").returncode, 0)
        (self.bin / "curl").unlink()
        self.assertEqual(self.run_wrapper("--version").returncode, 0)
        self.entry().write_bytes(b"tampered")
        result = self.run_wrapper("--version")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.entry()), result.stderr)
        self.assertEqual(self.java_log.read_text().count("-jar"), 2)

    def test_concurrent_cold_starts_publish_only_verified_artifact(self):
        release = self.root / "release"
        ready = self.root / "ready"
        ready.mkdir()
        self._executable(
            "curl",
            "#!/bin/sh\nwhile [ \"$1\" != --output ]; do shift; done\nshift; out=$1\n"
            "touch \"$READY_DIR/$$\"\n"
            "while [ ! -e \"$RELEASE_FILE\" ]; do sleep 0.01; done\n"
            "printf '%s' \"$PAYLOAD\" > \"$out\"\n",
        )
        env = self.environment | {"READY_DIR": str(ready), "RELEASE_FILE": str(release)}
        processes = [
            subprocess.Popen([str(self.project / "concordw"), "--version"], cwd=self.root,
                             env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            for _ in range(2)
        ]
        deadline = time.monotonic() + 10
        while len(list(ready.iterdir())) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(len(list(ready.iterdir())), 2, "both downloads must reach the barrier")
        release.touch()
        results = [process.communicate(timeout=10) + (process.returncode,) for process in processes]
        self.assertEqual([result[2] for result in results], [0, 0], results)
        self.assertEqual(self.entry().read_bytes(), self.payload)


if __name__ == "__main__":
    unittest.main()
