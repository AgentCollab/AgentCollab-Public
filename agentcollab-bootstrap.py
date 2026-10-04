#!/usr/bin/env python3
"""Authenticated bootstrap for the AgentCollab package installer."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

PUBLIC_REPOSITORY = "AgentCollab/AgentCollab-Public"
DISTRIBUTION_REPOSITORY = "AgentCollab/AgentCollab-Distribution"
SOURCE_REPOSITORY = "lkhkhk/AgentCollab"
BETA_VERSION = "v0.2.0-beta.2"
DISTRIBUTION_BETA_TAG = "v0.2.0-beta.1"
SETUP_PATH = "deploy/setup.py"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_CONTENT_BYTES = 1024 * 1024 * 1024


class BootstrapError(RuntimeError):
    def __init__(self, status: str, phase: str, reason: str, next_action: str = ""):
        super().__init__(reason)
        self.status = status
        self.phase = phase
        self.reason = reason
        self.next_action = next_action


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _asset_name(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and len(value) <= 160
            and value not in {".", ".."} and "/" not in value and "\\" not in value)


def validate_public_manifest(manifest: object) -> dict:
    if not isinstance(manifest, dict):
        raise BootstrapError("BLOCKED", "manifest", "Public release manifest is not an object.")
    source = manifest.get("source")
    distribution = manifest.get("distribution")
    packages = distribution.get("packages") if isinstance(distribution, dict) else None
    setup = manifest.get("setup")
    bootstrap = manifest.get("bootstrap")
    release_manifest = distribution.get("release_manifest") if isinstance(distribution, dict) else None
    if (manifest.get("schema_version") != 1 or manifest.get("channel") != "beta"
            or manifest.get("version") != BETA_VERSION
            or manifest.get("public_repository") != PUBLIC_REPOSITORY):
        raise BootstrapError("BLOCKED", "manifest", "Public beta identity or channel is invalid.")
    if (not isinstance(source, dict) or source.get("repository") != SOURCE_REPOSITORY
            or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit", "")))
            or source.get("service_branch") != "main"):
        raise BootstrapError("BLOCKED", "manifest", "Private source provenance or stable service branch is invalid.")
    if (not isinstance(distribution, dict)
            or distribution.get("repository") != DISTRIBUTION_REPOSITORY
            or distribution.get("visibility") != "private"
            or distribution.get("release_tag") != DISTRIBUTION_BETA_TAG
            or not isinstance(release_manifest, dict)
            or not _asset_name(release_manifest.get("name"))
            or not release_manifest["name"].startswith("agentcollab-release-manifest")
            or not release_manifest["name"].endswith(".json")
            or not _digest(release_manifest.get("sha256"))):
        raise BootstrapError("BLOCKED", "manifest", "Private Distribution release identity is invalid.")
    if not isinstance(packages, dict) or not isinstance(setup, dict) or setup.get("path") != SETUP_PATH:
        raise BootstrapError("BLOCKED", "manifest", "Runtime/Execution package metadata is incomplete.")
    for kind in ("runtime", "execution"):
        item = packages.get(kind)
        if (not isinstance(item, dict) or not _asset_name(item.get("filename"))
                or not _digest(item.get("sha256"))):
            raise BootstrapError("BLOCKED", "manifest", f"{kind.title()} package identity or SHA-256 is invalid.")
    if not _digest(setup.get("sha256")):
        raise BootstrapError("BLOCKED", "manifest", "Packaged deploy/setup.py SHA-256 is invalid.")
    if (not isinstance(bootstrap, dict) or bootstrap.get("name") != "agentcollab-bootstrap.py"
            or not _digest(bootstrap.get("sha256"))):
        raise BootstrapError("BLOCKED", "manifest", "Public bootstrap identity or SHA-256 is invalid.")
    return manifest


def _read_zip(raw: bytes, kind: str, public_manifest: dict) -> tuple[dict, bytes]:
    expected = public_manifest["distribution"]["packages"][kind]
    if len(raw) > MAX_ARCHIVE_BYTES or _sha256(raw) != expected["sha256"]:
        raise BootstrapError("BLOCKED", "package-verification", f"{kind.title()} package SHA-256 mismatch.")
    manifest_path = (".agentcollab/runtime-manifest.json" if kind == "runtime"
                     else ".agentcollab/execution-manifest.json")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if len(names) != len(set(names)) or sum(item.file_size for item in infos) > MAX_ARCHIVE_CONTENT_BYTES:
                raise ValueError("archive entries are duplicated or oversized")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    raise ValueError("archive contains an unsafe path")
            package_manifest = json.loads(archive.read(manifest_path))
            managed = package_manifest.get("managed_paths")
            hashes = package_manifest.get("files_sha256")
            if (not isinstance(managed, list) or not isinstance(hashes, dict)
                    or len(managed) != len(set(managed)) or set(managed) != set(hashes)):
                raise ValueError("package file manifest is invalid")
            for path in managed:
                if not isinstance(path, str) or not _digest(hashes.get(path)):
                    raise ValueError("package managed path or digest is invalid")
                if _sha256(archive.read(path)) != hashes[path]:
                    raise ValueError(f"package file digest mismatch: {path}")
            setup_bytes = archive.read(SETUP_PATH) if kind == "runtime" else b""
    except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as error:
        raise BootstrapError("BLOCKED", "package-verification",
                             f"{kind.title()} package provenance or managed-file verification failed.") from error
    expected_source = public_manifest["source"]
    expected_release = public_manifest["distribution"]["release_tag"]
    if (package_manifest.get("product") != "AgentCollab"
            or package_manifest.get("release_version") != expected_release
            or package_manifest.get("source") != {
                "repository": expected_source["repository"], "commit": expected_source["commit"]}
            or package_manifest.get("service_branch") != expected_source["service_branch"]):
        raise BootstrapError("BLOCKED", "package-verification", f"{kind.title()} package source provenance mismatch.")
    if kind == "runtime" and _sha256(setup_bytes) != public_manifest["setup"]["sha256"]:
        raise BootstrapError("BLOCKED", "package-verification", "Packaged deploy/setup.py SHA-256 mismatch.")
    return package_manifest, setup_bytes


def verify_bundle(public_manifest: dict, release_manifest_raw: bytes,
                  runtime_raw: bytes, execution_raw: bytes) -> tuple[dict, dict, bytes]:
    if _sha256(release_manifest_raw) != public_manifest["distribution"]["release_manifest"]["sha256"]:
        raise BootstrapError("BLOCKED", "release-verification", "Private release manifest SHA-256 mismatch.")
    try:
        release = json.loads(release_manifest_raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BootstrapError("BLOCKED", "release-verification", "Private release manifest is invalid.") from error
    expected_source = public_manifest["source"]
    release_setup = release.get("setup") if isinstance(release, dict) else None
    if (not isinstance(release, dict) or release.get("schema_version") != 1
            or release.get("product") != "AgentCollab" or release.get("channel") != "beta"
            or release.get("release_tag") != public_manifest["distribution"]["release_tag"]
            or release.get("release_version") != public_manifest["distribution"]["release_tag"]
            or release.get("source") != {"repository": expected_source["repository"], "commit": expected_source["commit"]}
            or release.get("service_branch") != expected_source["service_branch"]
            or not isinstance(release_setup, dict)
            or release_setup.get("package_path") != public_manifest["setup"]["path"]
            or release_setup.get("sha256") != public_manifest["setup"]["sha256"]
            or release.get("packages") != public_manifest["distribution"]["packages"]):
        raise BootstrapError("BLOCKED", "release-verification", "Private release provenance differs from the Public beta manifest.")
    runtime, setup_bytes = _read_zip(runtime_raw, "runtime", public_manifest)
    execution, _ = _read_zip(execution_raw, "execution", public_manifest)
    pair_fields = ("release_version", "execution_contract_version", "source", "service_branch")
    if any(runtime.get(field) != execution.get(field) for field in pair_fields):
        raise BootstrapError("BLOCKED", "package-verification", "Runtime and Execution packages are not a compatible release pair.")
    if runtime.get("execution_contract_version") != release.get("execution_contract_version"):
        raise BootstrapError("BLOCKED", "package-verification", "Package execution contract version mismatch.")
    return release, runtime, setup_bytes


def materialize_verified_runtime(raw: bytes, destination: Path) -> Path:
    """Materialize the already digest-verified Runtime without honoring links."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for info in archive.infolist():
                relative = PurePosixPath(info.filename)
                if relative.is_absolute() or ".." in relative.parts or "\\" in info.filename:
                    raise ValueError("unsafe runtime path")
                mode = (info.external_attr >> 16) & 0o170000
                if mode not in (0, 0o100000, 0o040000):
                    raise ValueError("runtime archive contains a non-regular entry")
                target = destination.joinpath(*relative.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
                permissions = (info.external_attr >> 16) & 0o777
                if permissions:
                    target.chmod(permissions)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as error:
        raise BootstrapError("BLOCKED", "package-verification",
                             "Verified Runtime package could not be materialized safely.") from error
    setup_path = destination / SETUP_PATH
    if not setup_path.is_file():
        raise BootstrapError("BLOCKED", "package-verification", "Verified Runtime is missing deploy/setup.py.")
    return setup_path


def _run(args: list[str], *, timeout: int = 120):
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def require_github_auth(run=_run, which=shutil.which) -> None:
    if not which("gh"):
        raise BootstrapError("ACTION_REQUIRED", "github-auth", "GitHub CLI is required for private package access.",
                             "Install GitHub CLI, run `gh auth login`, request AgentCollab-Distribution access, then rerun.")
    auth = run(["gh", "auth", "status", "--hostname", "github.com"])
    if not auth or auth.returncode:
        raise BootstrapError("ACTION_REQUIRED", "github-auth", "No authenticated GitHub CLI identity is available.",
                             "Run `gh auth login` and request AgentCollab-Distribution access, then rerun.")
    identity = run(["gh", "api", "user", "--jq", ".login"])
    if not identity or identity.returncode or not identity.stdout.strip():
        raise BootstrapError("ACTION_REQUIRED", "github-auth", "GitHub CLI identity could not be verified.",
                             "Refresh `gh auth login`, then rerun.")


def _download_bundle(manifest: dict, directory: Path, run=_run) -> tuple[bytes, bytes, bytes]:
    distribution = manifest["distribution"]
    release_manifest_name = distribution["release_manifest"]["name"]
    runtime_name = distribution["packages"]["runtime"]["filename"]
    execution_name = distribution["packages"]["execution"]["filename"]
    args = ["gh", "release", "download", distribution["release_tag"],
            "--repo", distribution["repository"], "--dir", str(directory)]
    for name in (release_manifest_name, runtime_name, execution_name):
        args.extend(["--pattern", name])
    result = run(args, timeout=300)
    if not result or result.returncode:
        raise BootstrapError("ACTION_REQUIRED", "distribution-download",
                             "Private beta assets are unavailable to this GitHub identity.",
                             "Confirm AgentCollab-Distribution access with the repository owner, then rerun.")
    try:
        return ((directory / release_manifest_name).read_bytes(),
                (directory / runtime_name).read_bytes(),
                (directory / execution_name).read_bytes())
    except OSError as error:
        raise BootstrapError("BLOCKED", "distribution-download", "A required private release asset is missing.") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", nargs="?", choices=("plan", "apply", "verify"), default="plan")
    parser.add_argument("--manifest", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--installation-root", type=Path,
                        help="personal installation root (default: ./agentcollab from the current directory)")
    parser.add_argument("--control-repository", help="existing personal Execution repository to reuse")
    parser.add_argument("--web-port", type=int, default=8080)
    parser.add_argument("--service-name", default="agentcollab-web.service")
    parser.add_argument("--runner-root", type=Path)
    parser.add_argument("--runner-selector", action="append")
    parser.add_argument("--skip-actions-variable", action="store_true")
    parser.add_argument("--skip-actions-credentials", action="store_true")
    parser.add_argument("--approved-plan-sha256")
    return parser


def run_bootstrap(argv=None, *, command_fn=_run, which=shutil.which,
                  setup_command_fn=None, cwd: Path | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        public_manifest = validate_public_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
        require_github_auth(command_fn, which)
        installation_root = (args.installation_root.expanduser().resolve(strict=False) if args.installation_root
                             else ((cwd or Path.cwd()) / "agentcollab").resolve(strict=False))
        with tempfile.TemporaryDirectory(prefix="agentcollab-private-packages-") as temporary:
            download_dir = Path(temporary)
            release_raw, runtime_raw, execution_raw = _download_bundle(public_manifest, download_dir, command_fn)
            _release, _runtime_manifest, _setup_bytes = verify_bundle(
                public_manifest, release_raw, runtime_raw, execution_raw)
            runtime_package = download_dir / public_manifest["distribution"]["packages"]["runtime"]["filename"]
            execution_package = download_dir / public_manifest["distribution"]["packages"]["execution"]["filename"]
            runtime_package.write_bytes(runtime_raw)
            execution_package.write_bytes(execution_raw)
            runtime_root = download_dir / "verified-runtime"
            setup_path = materialize_verified_runtime(runtime_raw, runtime_root)
            setup_args = [sys.executable, str(setup_path), args.phase,
                          "--installation-root", str(installation_root),
                          "--runtime-package", str(runtime_package),
                          "--execution-package", str(execution_package),
                          "--web-port", str(args.web_port), "--service-name", args.service_name]
            if args.control_repository:
                setup_args.extend(["--control-repository", args.control_repository])
            if args.runner_root:
                setup_args.extend(["--runner-root", str(args.runner_root)])
            for selector in args.runner_selector or []:
                setup_args.extend(["--runner-selector", selector])
            if args.skip_actions_variable:
                setup_args.append("--skip-actions-variable")
            if args.skip_actions_credentials:
                setup_args.append("--skip-actions-credentials")
            if args.phase == "apply":
                if not args.approved_plan_sha256 or not _digest(args.approved_plan_sha256):
                    raise BootstrapError("ACTION_REQUIRED", "plan-approval",
                                         "APPLY requires the reviewed PLAN SHA-256.",
                                         "Run `install.sh plan`, review the result, then pass its plan_sha256 to APPLY.")
                setup_args.extend(["--approved-plan-sha256", args.approved_plan_sha256])
            elif args.approved_plan_sha256:
                parser.error("--approved-plan-sha256 is only valid with APPLY")
            runner = setup_command_fn or subprocess.run
            environment = dict(os.environ)
            prior_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = str(runtime_root) + (os.pathsep + prior_pythonpath if prior_pythonpath else "")
            result = runner(setup_args, check=False, cwd=runtime_root, env=environment)
            return int(getattr(result, "returncode", 2))
    except BootstrapError as error:
        payload = {"status": error.status, "phase": error.phase, "reason": error.reason}
        if error.next_action:
            payload["next_action"] = error.next_action
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1 if error.status == "ACTION_REQUIRED" else 2
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "phase": "manifest",
                          "reason": "Public beta manifest could not be read safely."},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run_bootstrap())
