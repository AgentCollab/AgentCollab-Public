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
LAUNCHER = ROOT / "install.sh"
VERSION = "0.1.0"
SOURCE_SHA = "3980ee450f373f36cc516ae0b9c49790083973c0"
MANIFEST_URL = f"https://raw.githubusercontent.com/lkhkhk/AgentCollab-Public/v{VERSION}/installer-manifest.json"
ARTIFACT_URL = f"https://github.com/lkhkhk/AgentCollab-Public/releases/download/v{VERSION}/agentcollab-installer.py"


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentcollab-public-launcher-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tmpdir = self.root / "tmp"
        self.tmpdir.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ("python3", "cp", "sha256sum", "rm", "mktemp"):
            source = shutil.which(tool)
            if source:
                (self.bin / tool).symlink_to(source)
        self.marker = self.root / "installer-ran"
        self.fixture_artifact = self.root / "fixture-installer.py"
        self.fixture_artifact.write_text(
            "from pathlib import Path\nimport os\np=Path(os.environ['RUN_MARKER'])\np.write_text(p.read_text()+'x' if p.exists() else 'x')\n",
            encoding="utf-8")
        self.manifest_path = self.root / "fixture-manifest.json"
        self.artifact_sha = hashlib.sha256(self.fixture_artifact.read_bytes()).hexdigest()
        self.write_manifest()
        self.fake_curl = self.bin / "curl"
        self.fake_curl.write_text('''#!/bin/sh
set -eu
out=
url=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) out=$2; shift 2 ;;
        *) url=$1; shift ;;
    esac
done
if [ "${FAIL_DOWNLOAD_URL:-}" = "$url" ]; then exit 22; fi
if [ "${PARTIAL_DOWNLOAD_URL:-}" = "$url" ]; then printf partial > "$out"; exit 22; fi
case "$url" in
    *installer-manifest.json) cp "$FIXTURE_MANIFEST" "$out" ;;
    *agentcollab-installer.py) cp "$FIXTURE_ARTIFACT" "$out" ;;
    *) exit 22 ;;
esac
''', encoding="utf-8")
        self.fake_curl.chmod(0o755)

    def write_manifest(self, **overrides):
        manifest = {
            "schema_version": 1, "channel": "stable", "version": VERSION,
            "public_repository": "lkhkhk/AgentCollab-Public",
            "private_source": {"repository": "lkhkhk/AgentCollab", "commit": SOURCE_SHA,
                               "path": "deploy/guided_installer.py"},
            "artifact": {"name": "agentcollab-installer.py", "url": ARTIFACT_URL,
                         "sha256": self.artifact_sha if hasattr(self, "artifact_sha") else "0" * 64},
        }
        for key, value in overrides.items():
            if key.startswith("source_"):
                manifest["private_source"][key[7:]] = value
            elif key.startswith("artifact_"):
                manifest["artifact"][key[9:]] = value
            else:
                manifest[key] = value
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def invoke(self, *, fail_url="", partial_url=""):
        env = dict(os.environ)
        env.update({"PATH": f"{self.bin}:/usr/bin:/bin", "TMPDIR": str(self.tmpdir),
                    "FIXTURE_MANIFEST": str(self.manifest_path),
                    "FIXTURE_ARTIFACT": str(self.fixture_artifact),
                    "RUN_MARKER": str(self.marker), "FAIL_DOWNLOAD_URL": fail_url,
                    "PARTIAL_DOWNLOAD_URL": partial_url})
        result = subprocess.run(["/bin/sh", str(LAUNCHER)], cwd=self.root, env=env,
                                capture_output=True, text=True, check=False)
        self.assertEqual([], list(self.tmpdir.iterdir()), "launcher left temporary downloads behind")
        return result

    def test_valid_manifest_and_artifact_execute_verified_installer_and_rerun_safely(self):
        for _ in range(2):
            result = self.invoke()
            self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("xx", self.marker.read_text())

    def test_checksum_mismatch_fails_closed(self):
        self.fixture_artifact.write_text("raise SystemExit('wrong bytes')\n", encoding="utf-8")
        result = self.invoke()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())

    def test_missing_manifest_fails_closed(self):
        result = self.invoke(fail_url=MANIFEST_URL)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("manifest", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_corrupt_manifest_fails_closed(self):
        self.manifest_path.write_text("not-json", encoding="utf-8")
        result = self.invoke()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())

    def test_version_mismatch_fails_closed(self):
        self.write_manifest(version="9.9.9")
        result = self.invoke()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())

    def test_private_source_sha_mismatch_fails_closed(self):
        self.write_manifest(source_commit="f" * 40)
        result = self.invoke()
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())

    def test_artifact_download_failure_is_actionable_and_fails_closed(self):
        result = self.invoke(fail_url=ARTIFACT_URL)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("artifact", result.stderr)
        self.assertFalse(self.marker.exists())

    def test_partial_artifact_is_never_executed(self):
        result = self.invoke(partial_url=ARTIFACT_URL)
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(self.marker.exists())

    def test_manifest_identity_url_and_digest_metadata_fail_closed(self):
        for change in ({"artifact_name": "other.py"}, {"artifact_url": "http://example.invalid/file"},
                       {"artifact_sha256": "not-a-digest"}, {"source_path": "other.py"},
                       {"public_repository": "other/entry"}):
            with self.subTest(change=change):
                self.write_manifest(**change)
                result = self.invoke()
                self.assertNotEqual(0, result.returncode)
                self.assertFalse(self.marker.exists())

    def test_launcher_contains_no_private_install_engine_or_credentials(self):
        text = LAUNCHER.read_text(encoding="utf-8")
        for prohibited in ("development_setup.py", "actions/runners", "runtime-config.py",
                           "AGENTCOLLAB_ORCHESTRATION_TOKEN", "gh auth", "AGENTCOLLAB_DATA_ROOT"):
            self.assertNotIn(prohibited, text)


if __name__ == "__main__":
    unittest.main()
