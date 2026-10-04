from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agentcollab_bootstrap", ROOT / "agentcollab-bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def package(kind: str, setup: bytes = b"", contract: str = "1.0.0") -> bytes:
    managed = {"deploy/setup.py": setup} if kind == "runtime" else {"execution/task.json": b"{}"}
    manifest = {
        "product": "AgentCollab", "release_version": "v0.2.0-beta.1",
        "source": {"repository": "lkhkhk/AgentCollab", "commit": "1a5def1de57f8abccade2dcb4697fab26d1d45f5"},
        "service_branch": "main", "execution_contract_version": contract,
        "managed_paths": list(managed), "files_sha256": {name: digest(data) for name, data in managed.items()},
    }
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f".agentcollab/{kind}-manifest.json", json.dumps(manifest))
        for name, data in managed.items():
            archive.writestr(name, data)
    return result.getvalue()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentcollab-bootstrap-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.setup_bytes = b"# verified setup fixture\n"
        self.runtime = package("runtime", self.setup_bytes)
        self.execution = package("execution")
        self.runtime_name = "agentcollab-runtime-v0.2.0-beta.1.zip"
        self.execution_name = "agentcollab-execution-v0.2.0-beta.1.zip"
        self.release = {
            "schema_version": 1, "product": "AgentCollab", "channel": "beta",
            "release_tag": "v0.2.0-beta.1", "release_version": "v0.2.0-beta.1",
            "source": {"repository": "lkhkhk/AgentCollab", "commit": "1a5def1de57f8abccade2dcb4697fab26d1d45f5"},
            "service_branch": "main", "execution_contract_version": "1.0.0",
            "setup": {"package_path": "deploy/setup.py", "sha256": digest(self.setup_bytes)},
            "packages": {
                "runtime": {"filename": self.runtime_name, "sha256": digest(self.runtime)},
                "execution": {"filename": self.execution_name, "sha256": digest(self.execution)},
            },
        }
        self.release_raw = json.dumps(self.release, sort_keys=True).encode()
        self.manifest = {
            "schema_version": 1, "channel": "beta", "version": "v0.2.0-beta.1",
            "public_repository": "lkhkhk/AgentCollab-Public",
            "source": {"repository": "lkhkhk/AgentCollab", "commit": "1a5def1de57f8abccade2dcb4697fab26d1d45f5", "service_branch": "main"},
            "distribution": {"repository": "lkhkhk/AgentCollab-Distribution", "visibility": "private",
                "release_tag": "v0.2.0-beta.1",
                "release_manifest": {"name": "agentcollab-release-manifest.json", "sha256": digest(self.release_raw)},
                "packages": self.release["packages"]},
            "setup": {"path": "deploy/setup.py", "sha256": digest(self.setup_bytes)},
            "bootstrap": {"name": "agentcollab-bootstrap.py", "sha256": "0" * 64},
        }
        self.manifest_path = self.root / "manifest.json"
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.assets = {"agentcollab-release-manifest.json": self.release_raw,
                       self.runtime_name: self.runtime, self.execution_name: self.execution}

    def auth_ok(self, argv, **_kwargs):
        return SimpleNamespace(returncode=0, stdout="lkhkhk\n", stderr="")

    def downloader(self, argv, **_kwargs):
        result = self.auth_ok(argv)
        if argv[:3] == ["gh", "release", "download"]:
            directory = Path(argv[argv.index("--dir") + 1])
            patterns = [argv[i + 1] for i, value in enumerate(argv[:-1]) if value == "--pattern"]
            for name in patterns:
                (directory / name).write_bytes(self.assets[name])
        return result

    def test_authenticated_public_plan_verifies_pair_and_never_creates_install_root(self):
        captured = {}
        def setup_runner(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            self.assertTrue(Path(argv[1]).is_file())
            self.assertTrue(Path(argv[argv.index("--runtime-package") + 1]).is_file())
            self.assertTrue(Path(argv[argv.index("--execution-package") + 1]).is_file())
            return SimpleNamespace(returncode=0)
        install_root = self.root / "work" / "agentcollab"
        result = bootstrap.run_bootstrap(["plan", "--manifest", str(self.manifest_path)],
            command_fn=self.downloader, which=lambda _name: "/usr/bin/gh", setup_command_fn=setup_runner,
            cwd=self.root / "work")
        self.assertEqual(0, result)
        self.assertEqual("plan", captured["argv"][2])
        self.assertIn(str(install_root), captured["argv"])
        self.assertFalse(install_root.exists())
        self.assertFalse(Path(captured["argv"][2]).exists(), "verified temporary setup should be cleaned")

    def test_missing_github_identity_requests_interactive_auth_before_any_download(self):
        calls = []
        def no_auth(argv, **_kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        result = bootstrap.run_bootstrap(["plan", "--manifest", str(self.manifest_path)],
            command_fn=no_auth, which=lambda _name: "/usr/bin/gh", cwd=self.root)
        self.assertEqual(1, result)
        self.assertEqual(["gh", "auth", "status", "--hostname", "github.com"], calls[0])
        self.assertEqual(1, len(calls), "private release download must not start before auth")

    def test_private_repository_access_failure_is_actionable(self):
        calls = []
        def denied(argv, **_kwargs):
            calls.append(argv)
            if argv[:2] == ["gh", "release"]:
                return SimpleNamespace(returncode=1, stdout="", stderr="private detail")
            return SimpleNamespace(returncode=0, stdout="lkhkhk", stderr="")
        result = bootstrap.run_bootstrap(["plan", "--manifest", str(self.manifest_path)],
            command_fn=denied, which=lambda _name: "/usr/bin/gh", cwd=self.root)
        self.assertEqual(1, result)
        self.assertEqual("gh", calls[-1][0])
        self.assertEqual("release", calls[-1][1])

    def test_package_tampering_and_mismatched_pair_fail_closed(self):
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(self.manifest, self.release_raw, self.runtime + b"tamper", self.execution)
        wrong_release = dict(self.release, service_branch="work/untrusted")
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(self.manifest, json.dumps(wrong_release).encode(), self.runtime, self.execution)

    def test_setup_digest_mismatch_and_incompatible_package_contract_fail_closed(self):
        wrong_public = json.loads(json.dumps(self.manifest))
        wrong_release = json.loads(json.dumps(self.release))
        wrong_public["setup"]["sha256"] = "f" * 64
        wrong_release["setup"]["sha256"] = "f" * 64
        wrong_release_raw = json.dumps(wrong_release, sort_keys=True).encode()
        wrong_public["distribution"]["release_manifest"]["sha256"] = digest(wrong_release_raw)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(wrong_public, wrong_release_raw, self.runtime, self.execution)

        incompatible = package("execution", contract="2.0.0")
        pair_public = json.loads(json.dumps(self.manifest))
        pair_release = json.loads(json.dumps(self.release))
        pair_release["packages"]["execution"]["sha256"] = digest(incompatible)
        pair_raw = json.dumps(pair_release, sort_keys=True).encode()
        pair_public["distribution"]["packages"]["execution"]["sha256"] = digest(incompatible)
        pair_public["distribution"]["release_manifest"]["sha256"] = digest(pair_raw)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(pair_public, pair_raw, self.runtime, incompatible)


if __name__ == "__main__":
    unittest.main()
