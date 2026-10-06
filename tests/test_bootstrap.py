from __future__ import annotations

import base64
import contextlib
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


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def package(kind: str, version: str, source_commit: str, setup: bytes = b"", contract: str = "1.0.0",
            service_branch: str = "main", source_repository: str = "lkhkhk/AgentCollab") -> bytes:
    managed = {"deploy/setup.py": setup} if kind == "runtime" else {"execution/task.json": b"{}"}
    manifest = {
        "product": "AgentCollab", "release_version": version,
        "source": {"repository": source_repository, "commit": source_commit},
        "service_branch": service_branch, "execution_contract_version": contract,
        "managed_paths": list(managed), "files_sha256": {name: digest(data) for name, data in managed.items()},
    }
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f".agentcollab/{kind}-manifest.json", json_bytes(manifest))
        for name, data in managed.items():
            archive.writestr(name, data)
    return result.getvalue()


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentcollab-bootstrap-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.version = "v9.1.0-beta.3"
        self.source_repository = "lkhkhk/AgentCollab"
        self.source_commit = "1a5def1de57f8abccade2dcb4697fab26d1d45f5"
        self.setup_bytes = b"# verified setup fixture\n"
        self.runtime = package("runtime", self.version, self.source_commit, self.setup_bytes)
        self.execution = package("execution", self.version, self.source_commit)
        self.runtime_name = f"agentcollab-runtime-{self.version}.zip"
        self.execution_name = f"agentcollab-execution-{self.version}.zip"
        self.release = {
            "schema_version": 1, "product": "AgentCollab", "channel": "beta",
            "release_tag": self.version, "release_version": self.version,
            "source": {"repository": self.source_repository, "commit": self.source_commit},
            "service_branch": "main", "execution_contract_version": "1.0.0",
            "setup": {"package_path": "deploy/setup.py", "sha256": digest(self.setup_bytes)},
            "packages": {
                "runtime": {"filename": self.runtime_name, "sha256": digest(self.runtime)},
                "execution": {"filename": self.execution_name, "sha256": digest(self.execution)},
            },
        }
        self.release_raw = json_bytes(self.release)
        self.record = {
            "schema_version": 1, "product": "AgentCollab", "version": self.version,
            "kind": "release", "release_tag": self.version,
            "release_manifest": {"name": f"agentcollab-release-manifest-{self.version}.json",
                                 "sha256": digest(self.release_raw)},
        }
        self.record_raw = json_bytes(self.record)
        self.pointer = {
            "schema_version": 1, "product": "AgentCollab", "channel": "default",
            "version": self.version,
            "version_record": {"path": f"versions/{self.version}.json", "sha256": digest(self.record_raw)},
        }
        self.beta_pointer = dict(self.pointer, channel="beta")
        self.stable_pointer = dict(self.pointer, channel="stable")
        self.catalog = {
            f"channels/default.json": json_bytes(self.pointer),
            f"channels/beta.json": json_bytes(self.beta_pointer),
            f"channels/stable.json": json_bytes(self.stable_pointer),
            f"versions/{self.version}.json": self.record_raw,
        }
        self.assets = {self.record["release_manifest"]["name"]: self.release_raw,
                       self.runtime_name: self.runtime, self.execution_name: self.execution}
        self.manifest_path = self.root / "installer-manifest.json"
        self.manifest_path.write_text(json.dumps({
            "schema_version": 1, "protocol": "distribution-catalog-v1",
            "public_repository": "AgentCollab/AgentCollab-Public",
            "bootstrap": {"name": "agentcollab-bootstrap.py",
                          "sha256": digest((ROOT / "agentcollab-bootstrap.py").read_bytes())},
        }), encoding="utf-8")
        self.command_calls = []
        self.downloaded = []
        self.capture = {}
        self.catalog_failures = set()
        self.release_failures = set()

    def configure_kind_and_branch(self, kind="release", service_branch="main"):
        self.release["service_branch"] = service_branch
        self.runtime = package("runtime", self.version, self.source_commit, self.setup_bytes,
                               service_branch=service_branch,
                               source_repository=self.source_repository)
        self.execution = package("execution", self.version, self.source_commit,
                                 service_branch=service_branch,
                                 source_repository=self.source_repository)
        self.release["packages"]["runtime"]["sha256"] = digest(self.runtime)
        self.release["packages"]["execution"]["sha256"] = digest(self.execution)
        self.release_raw = json_bytes(self.release)
        self.record["kind"] = kind
        self.record["release_manifest"]["sha256"] = digest(self.release_raw)
        self.record_raw = json_bytes(self.record)
        self.pointer["version_record"]["sha256"] = digest(self.record_raw)
        self.beta_pointer["version_record"]["sha256"] = digest(self.record_raw)
        self.stable_pointer["version_record"]["sha256"] = digest(self.record_raw)
        self.catalog[f"versions/{self.version}.json"] = self.record_raw
        self.catalog["channels/default.json"] = json_bytes(self.pointer)
        self.catalog["channels/beta.json"] = json_bytes(self.beta_pointer)
        self.catalog["channels/stable.json"] = json_bytes(self.stable_pointer)
        self.assets[self.record["release_manifest"]["name"]] = self.release_raw
        self.assets[self.runtime_name] = self.runtime
        self.assets[self.execution_name] = self.execution

    def configure_source_repository(self, source_repository):
        self.source_repository = source_repository
        self.runtime = package("runtime", self.version, self.source_commit, self.setup_bytes,
                               service_branch=self.release["service_branch"],
                               source_repository=source_repository)
        self.execution = package("execution", self.version, self.source_commit,
                                 service_branch=self.release["service_branch"],
                                 source_repository=source_repository)
        self.release["source"]["repository"] = source_repository
        self.release["packages"]["runtime"]["sha256"] = digest(self.runtime)
        self.release["packages"]["execution"]["sha256"] = digest(self.execution)
        self.release_raw = json_bytes(self.release)
        self.record["release_manifest"]["sha256"] = digest(self.release_raw)
        self.record_raw = json_bytes(self.record)
        self.pointer["version_record"]["sha256"] = digest(self.record_raw)
        self.beta_pointer["version_record"]["sha256"] = digest(self.record_raw)
        self.stable_pointer["version_record"]["sha256"] = digest(self.record_raw)
        self.catalog[f"versions/{self.version}.json"] = self.record_raw
        self.catalog["channels/default.json"] = json_bytes(self.pointer)
        self.catalog["channels/beta.json"] = json_bytes(self.beta_pointer)
        self.catalog["channels/stable.json"] = json_bytes(self.stable_pointer)
        self.assets[self.record["release_manifest"]["name"]] = self.release_raw
        self.assets[self.runtime_name] = self.runtime
        self.assets[self.execution_name] = self.execution

    def command(self, argv, *, timeout=120, **_kwargs):
        self.command_calls.append(list(argv))
        if argv == ["gh", "auth", "status", "--hostname", "github.com"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if argv[:3] == ["gh", "api", "user"]:
            return SimpleNamespace(returncode=0, stdout="user01\n", stderr="")
        if argv[:2] == ["gh", "api"] and "/contents/" in argv[2]:
            path = argv[2].split("/contents/", 1)[1]
            if path in self.catalog_failures or path not in self.catalog:
                return SimpleNamespace(returncode=1, stdout="", stderr="not found")
            payload = {"encoding": "base64", "content": base64.b64encode(self.catalog[path]).decode("ascii")}
            return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")
        if argv[:3] == ["gh", "release", "download"]:
            tag = argv[3]
            self.downloaded.append((tag, timeout, list(argv)))
            if tag in self.release_failures:
                return SimpleNamespace(returncode=1, stdout="", stderr="not found")
            destination = Path(argv[argv.index("--dir") + 1])
            patterns = [argv[index + 1] for index, token in enumerate(argv[:-1]) if token == "--pattern"]
            for name in patterns:
                if name not in self.assets:
                    return SimpleNamespace(returncode=1, stdout="", stderr="asset missing")
                (destination / name).write_bytes(self.assets[name])
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        self.fail(f"unexpected command: {argv}")

    def setup_runner(self, argv, **kwargs):
        self.capture["argv"] = argv
        self.capture["kwargs"] = kwargs
        self.assertTrue(Path(argv[1]).is_file())
        self.assertTrue(Path(argv[argv.index("--runtime-package") + 1]).is_file())
        self.assertTrue(Path(argv[argv.index("--execution-package") + 1]).is_file())
        return SimpleNamespace(returncode=0)

    def run_bootstrap(self, extra=(), *, cwd=None, runner=None, phase="plan"):
        args = [phase, "--manifest", str(self.manifest_path), *extra]
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = bootstrap.run_bootstrap(args, command_fn=self.command,
                which=lambda _name: "/usr/bin/gh", setup_command_fn=runner or self.setup_runner,
                cwd=cwd or self.root)
        return result, stderr.getvalue()

    def test_default_selector_uses_authenticated_default_pointer_and_current_directory_root(self):
        work = self.root / "work"
        result, stderr = self.run_bootstrap(cwd=work)
        self.assertEqual(0, result)
        catalog_calls = [call[2].split("/contents/", 1)[1] for call in self.command_calls
                         if call[:2] == ["gh", "api"] and "/contents/" in call[2]]
        self.assertEqual(["channels/default.json", f"versions/{self.version}.json"], catalog_calls)
        self.assertLess(self.command_calls.index(["gh", "auth", "status", "--hostname", "github.com"]),
                        next(i for i, call in enumerate(self.command_calls) if call[:2] == ["gh", "api"]))
        self.assertIn(str(work / "agentcollab"), self.capture["argv"])
        self.assertNotIn("--web-port", self.capture["argv"])
        self.assertFalse((work / "agentcollab").exists())
        evidence = json.loads(stderr)
        self.assertEqual({"kind": "default", "value": "default"}, evidence["requested_selector"])
        self.assertEqual(self.version, evidence["resolved_version"])
        self.assertEqual(self.source_commit, evidence["source"]["commit"])
        self.assertEqual("AgentCollab/AgentCollab-Distribution", evidence["distribution"]["repository"])
        self.assertEqual(self.version, evidence["distribution"]["release_tag"])

    def test_channel_selector_uses_only_requested_channel_pointer(self):
        result, stderr = self.run_bootstrap(["--channel", "beta"])
        self.assertEqual(0, result)
        paths = [call[2].split("/contents/", 1)[1] for call in self.command_calls
                 if call[:2] == ["gh", "api"] and "/contents/" in call[2]]
        self.assertEqual(["channels/beta.json", f"versions/{self.version}.json"], paths)
        self.assertEqual("channel", json.loads(stderr)["requested_selector"]["kind"])

    def test_stable_channel_selector_uses_stable_pointer(self):
        result, _stderr = self.run_bootstrap(["--channel", "stable"])
        self.assertEqual(0, result)
        paths = [call[2].split("/contents/", 1)[1] for call in self.command_calls
                 if call[:2] == ["gh", "api"] and "/contents/" in call[2]]
        self.assertEqual(["channels/stable.json", f"versions/{self.version}.json"], paths)

    def test_exact_version_bypasses_channel_pointer(self):
        result, _stderr = self.run_bootstrap(["--version", self.version])
        self.assertEqual(0, result)
        paths = [call[2].split("/contents/", 1)[1] for call in self.command_calls
                 if call[:2] == ["gh", "api"] and "/contents/" in call[2]]
        self.assertEqual([f"versions/{self.version}.json"], paths)
        self.assertEqual(self.version, json.loads(_stderr)["requested_selector"]["value"])

    def test_exact_candidate_with_safe_work_branch_is_accepted(self):
        self.configure_kind_and_branch("candidate", "work/694-auto-web-port")
        result, stderr = self.run_bootstrap(["--version", self.version])
        self.assertEqual(0, result)
        self.assertEqual("work/694-auto-web-port", json.loads(stderr)["source"]["service_branch"])

    def test_unsafe_candidate_service_branches_are_blocked(self):
        for branch in ("work/../bad", "work/@{bad}", "work//topic", "work/.hidden", "work/topic.lock"):
            with self.subTest(branch=branch):
                self.configure_kind_and_branch("candidate", branch)
                self.capture.clear()
                result, stderr = self.run_bootstrap(["--version", self.version])
                self.assertEqual(2, result)
                self.assertEqual("release-verification", json.loads(stderr)["phase"])
                self.assertNotIn("argv", self.capture, "invalid provenance must not execute setup")

    def test_channel_candidate_kind_is_blocked_before_release_download(self):
        self.configure_kind_and_branch("candidate", "work/694-auto-web-port")
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("version-record", json.loads(stderr)["phase"])
        self.assertEqual([], self.downloaded)
        self.assertNotIn("argv", self.capture)

    def test_channel_release_with_non_main_branch_is_blocked_before_setup(self):
        self.configure_kind_and_branch("release", "work/694-auto-web-port")
        for selector in ([], ["--channel", "beta"]):
            with self.subTest(selector=selector):
                self.capture.clear()
                self.downloaded.clear()
                result, stderr = self.run_bootstrap(selector)
                self.assertEqual(2, result)
                self.assertEqual("release-verification", json.loads(stderr)["phase"])
                self.assertEqual(1, len(self.downloaded),
                                 "packages must not download after invalid channel provenance")
                self.assertNotIn("argv", self.capture)

    def test_version_and_channel_conflict_before_any_remote_access(self):
        result, stderr = self.run_bootstrap(["--version", self.version, "--channel", "beta"])
        self.assertEqual(2, result)
        self.assertEqual([], self.command_calls)
        self.assertEqual("selector", json.loads(stderr)["phase"])

    def test_apply_requires_exact_resolved_version(self):
        result, stderr = self.run_bootstrap(phase="apply")
        self.assertEqual(1, result)
        self.assertEqual("selector", json.loads(stderr)["phase"])
        self.assertEqual([], self.command_calls)

    def test_unavailable_or_malformed_channel_pointer_blocks(self):
        self.catalog_failures.add("channels/default.json")
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("distribution-catalog", json.loads(stderr)["phase"])

        self.catalog_failures.clear()
        self.catalog["channels/default.json"] = b"{malformed"
        self.command_calls.clear()
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("distribution-catalog", json.loads(stderr)["phase"])

        self.catalog["channels/default.json"] = json_bytes({
            "schema_version": 1, "product": "AgentCollab", "channel": "beta",
            "version": self.version, "version_record": self.pointer["version_record"],
        })
        self.command_calls.clear()
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("channel-pointer", json.loads(stderr)["phase"])

    def test_pointer_version_record_hash_mismatch_blocks(self):
        invalid = dict(self.pointer)
        invalid["version_record"] = dict(self.pointer["version_record"], sha256="0" * 64)
        self.catalog["channels/default.json"] = json_bytes(invalid)
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("version-record", json.loads(stderr)["phase"])
        self.assertEqual(["channels/default.json", f"versions/{self.version}.json"],
                         [call[2].split("/contents/", 1)[1] for call in self.command_calls
                          if call[:2] == ["gh", "api"] and "/contents/" in call[2]])

    def test_catalog_schemas_reject_duplicated_package_hashes(self):
        pointer_with_packages = dict(self.pointer, packages=self.release["packages"])
        self.catalog["channels/default.json"] = json_bytes(pointer_with_packages)
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("channel-pointer", json.loads(stderr)["phase"])

        self.catalog["channels/default.json"] = json_bytes(self.pointer)
        record_with_packages = dict(self.record, packages=self.release["packages"])
        self.catalog[f"versions/{self.version}.json"] = json_bytes(record_with_packages)
        result, stderr = self.run_bootstrap(["--version", self.version])
        self.assertEqual(2, result)
        self.assertEqual("version-record", json.loads(stderr)["phase"])

    def test_malformed_version_record_and_nonexistent_exact_version_block(self):
        self.catalog[f"versions/{self.version}.json"] = b"{}"
        result, stderr = self.run_bootstrap(["--version", self.version])
        self.assertEqual(2, result)
        self.assertEqual("version-record", json.loads(stderr)["phase"])

        result, stderr = self.run_bootstrap(["--version", "v9.1.0-beta.99"])
        self.assertEqual(2, result)
        self.assertEqual("distribution-catalog", json.loads(stderr)["phase"])

    def test_release_manifest_hash_mismatch_blocks_before_package_download(self):
        self.assets[self.record["release_manifest"]["name"]] = self.release_raw + b"tamper"
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("release-verification", json.loads(stderr)["phase"])
        self.assertEqual(1, len(self.downloaded))

    def test_exact_resolved_tag_has_no_fallback_when_release_is_unavailable(self):
        self.release_failures.add(self.version)
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("distribution-download", json.loads(stderr)["phase"])
        self.assertEqual([self.version], [tag for tag, _timeout, _argv in self.downloaded])

    def test_release_manifest_and_package_hashes_and_provenance_are_verified(self):
        result, _stderr = self.run_bootstrap()
        self.assertEqual(0, result)
        self.assertEqual([self.version, self.version], [tag for tag, _timeout, _argv in self.downloaded])
        self.assertEqual(300, self.downloaded[0][1])
        self.assertEqual(300, self.downloaded[1][1])

        self.assets[self.runtime_name] += b"tampered"
        self.command_calls.clear()
        self.downloaded.clear()
        result, stderr = self.run_bootstrap()
        self.assertEqual(2, result)
        self.assertEqual("package-verification", json.loads(stderr)["phase"])

    def test_alternate_source_repository_is_accepted_when_release_and_packages_match(self):
        alternate = "renamed-owner/new-product-source"
        self.configure_source_repository(alternate)
        result, stderr = self.run_bootstrap()
        self.assertEqual(0, result, stderr)
        self.assertEqual(alternate, json.loads(stderr)["source"]["repository"])

    def test_invalid_source_repository_syntax_is_rejected(self):
        invalid_release = json.loads(json.dumps(self.release))
        invalid_release["source"]["repository"] = "renamed-owner/../source"
        raw = json_bytes(invalid_release)
        record = dict(self.record, release_manifest={
            **self.record["release_manifest"], "sha256": digest(raw)})
        with self.assertRaises(bootstrap.BootstrapError) as raised:
            bootstrap.validate_release_manifest(record, raw, {"kind": "version", "value": self.version})
        self.assertEqual("release-verification", raised.exception.phase)

    def test_runtime_source_repository_must_match_release_provenance(self):
        alternate = "renamed-owner/new-product-source"
        self.configure_source_repository(alternate)
        mismatched_runtime = package(
            "runtime", self.version, self.source_commit, self.setup_bytes,
            source_repository="other-owner/new-product-source")
        release = json.loads(json.dumps(self.release))
        release["packages"]["runtime"]["sha256"] = digest(mismatched_runtime)
        with self.assertRaises(bootstrap.BootstrapError) as raised:
            bootstrap.verify_bundle(release, mismatched_runtime, self.execution)
        self.assertEqual("package-verification", raised.exception.phase)

    def test_execution_source_commit_must_match_release_provenance(self):
        mismatched_execution = package(
            "execution", self.version, "a" * 40, source_repository=self.source_repository)
        release = json.loads(json.dumps(self.release))
        release["packages"]["execution"]["sha256"] = digest(mismatched_execution)
        with self.assertRaises(bootstrap.BootstrapError) as raised:
            bootstrap.verify_bundle(release, self.runtime, mismatched_execution)
        self.assertEqual("package-verification", raised.exception.phase)

    def test_package_source_setup_and_runtime_execution_pair_are_bound_to_manifest(self):
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(self.release, self.runtime + b"tamper", self.execution)

        wrong_source = package("runtime", self.version, "a" * 40, self.setup_bytes)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(self.release, wrong_source, self.execution)

        wrong_setup = package("runtime", self.version, self.source_commit, b"different setup\n")
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(self.release, wrong_setup, self.execution)

        incompatible = package("execution", self.version, self.source_commit, contract="2.0.0")
        incompatible_release = json.loads(json.dumps(self.release))
        incompatible_release["packages"]["execution"]["sha256"] = digest(incompatible)
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.verify_bundle(incompatible_release, self.runtime, incompatible)

    def test_authenticated_catalog_reads_use_gh_api_not_anonymous_urls(self):
        result, _stderr = self.run_bootstrap()
        self.assertEqual(0, result)
        self.assertTrue(all(call[:2] == ["gh", "api"] for call in self.command_calls
                            if "/contents/" in " ".join(call)))
        self.assertFalse(any("raw.githubusercontent.com" in " ".join(call) for call in self.command_calls))

    def test_explicit_web_port_is_forwarded_exactly(self):
        result, _stderr = self.run_bootstrap(["--web-port", "18123"])
        self.assertEqual(0, result)
        index = self.capture["argv"].index("--web-port")
        self.assertEqual("18123", self.capture["argv"][index + 1])

    def test_installer_metadata_is_generic_and_public_has_no_private_package_bytes(self):
        metadata = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertNotIn("version", metadata)
        self.assertNotIn("channel", metadata)
        self.assertNotIn("distribution", metadata)
        self.assertEqual([], list(ROOT.glob("*.zip")))
        self.assertFalse(any(path.name.startswith(("agentcollab-runtime-", "agentcollab-execution-"))
                             for path in ROOT.iterdir()))

    def test_generic_installer_metadata_rejects_mismatched_bootstrap_digest(self):
        invalid = {"schema_version": 1, "protocol": "distribution-catalog-v1",
                   "public_repository": "AgentCollab/AgentCollab-Public",
                   "bootstrap": {"name": "agentcollab-bootstrap.py", "sha256": "0" * 64}}
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.validate_installer_manifest(invalid, b"other bootstrap")


if __name__ == "__main__":
    unittest.main()
