from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentcollab-public-launcher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Public"
        self.root.mkdir()
        for name in ("install.sh", "installer-manifest.json", "agentcollab-bootstrap.py"):
            shutil.copy2(ROOT / name, self.root / name)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "install.sh", "installer-manifest.json", "agentcollab-bootstrap.py"],
                       cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture Public revision"], cwd=self.root, check=True)
        self.bindir = Path(self.temp.name) / "bin"
        self.bindir.mkdir()
        for name in ("git",):
            executable = shutil.which(name)
            if executable:
                (self.bindir / name).symlink_to(executable)
        self.capture = Path(self.temp.name) / "arguments.txt"
        python = self.bindir / "python3"
        python.write_text('''#!/bin/sh
printf '%s\\n' "$@" > "$CAPTURE"
''', encoding="utf-8")
        python.chmod(0o755)

    def invoke(self, *args):
        env = dict(os.environ, PATH=f"{self.bindir}:/usr/bin:/bin", CAPTURE=str(self.capture))
        return subprocess.run(["/bin/sh", str(self.root / "install.sh"), *args], cwd=self.root,
                              env=env, capture_output=True, text=True, check=False)

    def test_checked_out_launcher_runs_sibling_bootstrap_and_passes_cli_unchanged(self):
        result = self.invoke("plan", "--channel", "beta", "--web-port", "18123")
        self.assertEqual(0, result.returncode, result.stderr)
        argv = self.capture.read_text(encoding="utf-8").splitlines()
        self.assertEqual(str(self.root / "agentcollab-bootstrap.py"), argv[0])
        self.assertEqual(["--manifest", str(self.root / "installer-manifest.json"),
                          "plan", "--channel", "beta", "--web-port", "18123"], argv[1:])

    def test_launcher_blocks_dirty_or_mixed_public_revision(self):
        (self.root / "agentcollab-bootstrap.py").write_text("# mismatched bootstrap\n", encoding="utf-8")
        result = self.invoke("plan")
        self.assertEqual(2, result.returncode)
        self.assertIn("same committed Public revision", result.stderr)
        self.assertFalse(self.capture.exists())

    def test_public_launcher_has_no_product_version_or_remote_bootstrap_pin(self):
        content = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("v0.2.0", content)
        self.assertNotIn("/releases/download/", content)
        self.assertNotIn("curl", content)
        self.assertNotIn("gh auth", content)
        self.assertNotIn("development_setup.py", content)
        self.assertNotIn("guided_installer", content)
        self.assertFalse((ROOT / "agentcollab-installer.py").exists())


if __name__ == "__main__":
    unittest.main()
