from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v0.2.0-beta.2"
PUBLIC = "AgentCollab/AgentCollab-Public"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentcollab-public-launcher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.bindir = self.root / "bin"
        self.bindir.mkdir()
        for name in ("python3", "cp", "sha256sum", "rm", "mktemp"):
            executable = shutil.which(name)
            if executable:
                (self.bindir / name).symlink_to(executable)
        self.marker = self.root / "marker"
        self.bootstrap = self.root / "bootstrap.py"
        self.bootstrap.write_text("import os; open(os.environ['MARKER'],'w').write('ran')\n", encoding="utf-8")
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "schema_version": 1, "channel": "beta", "version": VERSION,
            "public_repository": PUBLIC,
            "bootstrap": {"name": "agentcollab-bootstrap.py",
                          "sha256": hashlib.sha256(self.bootstrap.read_bytes()).hexdigest()},
        }), encoding="utf-8")
        self.curl = self.bindir / "curl"
        self.curl.write_text('''#!/bin/sh
set -eu
out=
url=
while [ "$#" -gt 0 ]; do
  case "$1" in --output) out=$2; shift 2 ;; *) url=$1; shift ;; esac
done
case "$url" in
  *installer-manifest.json) cp "$FIXTURE_MANIFEST" "$out" ;;
  *agentcollab-bootstrap.py) cp "$FIXTURE_BOOTSTRAP" "$out" ;;
  *) exit 22 ;;
esac
''', encoding="utf-8")
        self.curl.chmod(0o755)

    def invoke(self):
        env = dict(os.environ, PATH=f"{self.bindir}:/usr/bin:/bin", TMPDIR=str(self.tmpdir),
                   FIXTURE_MANIFEST=str(self.manifest), FIXTURE_BOOTSTRAP=str(self.bootstrap),
                   MARKER=str(self.marker))
        result = subprocess.run(["/bin/sh", str(ROOT / "install.sh"), "plan"], cwd=self.root,
                                env=env, capture_output=True, text=True, check=False)
        self.assertEqual([], list(self.tmpdir.iterdir()), "launcher left temp files behind")
        return result

    def test_verified_candidate_bootstrap_runs_and_cleans_temporary_files(self):
        result = self.invoke()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ran", self.marker.read_text())

    def test_bootstrap_digest_mismatch_fails_closed(self):
        self.bootstrap.write_text("raise SystemExit('tampered')\n", encoding="utf-8")
        result = self.invoke()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())

    def test_wrong_candidate_identity_fails_closed(self):
        value = json.loads(self.manifest.read_text())
        value["channel"] = "stable"
        self.manifest.write_text(json.dumps(value), encoding="utf-8")
        result = self.invoke()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())

    def test_public_launcher_has_no_install_engine_or_secret_input(self):
        content = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertNotIn("gh auth", content)
        self.assertNotIn("development_setup.py", content)
        self.assertNotIn("guided_installer", content)
        self.assertFalse((ROOT / "agentcollab-installer.py").exists())

    def test_checked_in_candidate_manifest_binds_org_addresses_and_bootstrap_digest(self):
        manifest = json.loads((ROOT / "installer-manifest.json").read_text(encoding="utf-8"))
        bootstrap = (ROOT / "agentcollab-bootstrap.py").read_bytes()
        self.assertEqual(VERSION, manifest["version"])
        self.assertEqual(PUBLIC, manifest["public_repository"])
        self.assertEqual("AgentCollab/AgentCollab-Distribution", manifest["distribution"]["repository"])
        self.assertEqual(hashlib.sha256(bootstrap).hexdigest(), manifest["bootstrap"]["sha256"])


if __name__ == "__main__":
    unittest.main()
