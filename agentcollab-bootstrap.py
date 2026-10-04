#!/usr/bin/env python3
"""Authenticated bootstrap for the AgentCollab package installer."""
from __future__ import annotations

import argparse
import base64
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
INSTALLER_PROTOCOL = "distribution-catalog-v1"
VERSION_PATTERN = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}")
CHANNELS = {"default", "beta", "stable"}
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


def validate_installer_manifest(manifest: object, bootstrap_bytes: bytes) -> dict:
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("protocol") != INSTALLER_PROTOCOL
            or manifest.get("public_repository") != PUBLIC_REPOSITORY
            or set(manifest) != {"schema_version", "protocol", "public_repository", "bootstrap"}):
        raise BootstrapError("BLOCKED", "installer-identity", "Generic Public installer metadata is invalid.")
    bootstrap = manifest.get("bootstrap")
    if (not isinstance(bootstrap, dict) or set(bootstrap) != {"name", "sha256"}
            or bootstrap.get("name") != "agentcollab-bootstrap.py"
            or not _digest(bootstrap.get("sha256")) or _sha256(bootstrap_bytes) != bootstrap["sha256"]):
        raise BootstrapError("BLOCKED", "installer-identity", "Public bootstrap does not match its checked-in identity digest.")
    return manifest


def _valid_version(value: object) -> bool:
    return isinstance(value, str) and VERSION_PATTERN.fullmatch(value) is not None


def _validate_version_record(record: object, version: str) -> dict:
    release_manifest = record.get("release_manifest") if isinstance(record, dict) else None
    if (not isinstance(record, dict) or record.get("schema_version") != 1
            or record.get("product") != "AgentCollab" or record.get("version") != version
            or record.get("release_tag") != version or not isinstance(release_manifest, dict)
            or not _asset_name(release_manifest.get("name"))
            or not release_manifest["name"].startswith("agentcollab-release-manifest")
            or not release_manifest["name"].endswith(".json")
            or not _digest(release_manifest.get("sha256"))):
        raise BootstrapError("BLOCKED", "version-record", "Distribution version record is invalid or mismatched.")
    return record


def _validate_channel_pointer(pointer: object, channel: str) -> tuple[str, dict]:
    version = pointer.get("version") if isinstance(pointer, dict) else None
    record_ref = pointer.get("version_record") if isinstance(pointer, dict) else None
    expected_path = f"versions/{version}.json" if _valid_version(version) else None
    if (not isinstance(pointer, dict) or pointer.get("schema_version") != 1
            or pointer.get("product") != "AgentCollab" or pointer.get("channel") != channel
            or expected_path is None or not isinstance(record_ref, dict)
            or record_ref.get("path") != expected_path or not _digest(record_ref.get("sha256"))):
        raise BootstrapError("BLOCKED", "channel-pointer", "Distribution channel pointer is invalid or mismatched.")
    return version, record_ref


def _read_catalog_json(path: str, run=None) -> tuple[dict, bytes]:
    run = run or _run
    result = run(["gh", "api", f"repos/{DISTRIBUTION_REPOSITORY}/contents/{path}"])
    if not result or result.returncode:
        raise BootstrapError("BLOCKED", "distribution-catalog",
                             f"Authenticated Distribution catalog entry is unavailable: {path}.")
    try:
        response = json.loads(result.stdout)
        if not isinstance(response, dict) or response.get("encoding") != "base64":
            raise ValueError("catalog content is not base64")
        content = response.get("content")
        if not isinstance(content, str):
            raise ValueError("catalog content is missing")
        raw = base64.b64decode("".join(content.split()), validate=True)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("catalog JSON is not an object")
        return value, raw
    except (TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise BootstrapError("BLOCKED", "distribution-catalog",
                             f"Authenticated Distribution catalog entry is malformed: {path}.") from error


def resolve_version(*, requested_version: str | None, requested_channel: str | None,
                    run=None) -> tuple[str, dict, dict, str]:
    run = run or _run
    if requested_version is not None and requested_channel is not None:
        raise BootstrapError("BLOCKED", "selector", "--version and --channel cannot be used together.")
    if requested_version is not None:
        if not _valid_version(requested_version):
            raise BootstrapError("BLOCKED", "selector", "Requested version is not path-safe.")
        version = requested_version
        record, raw = _read_catalog_json(f"versions/{version}.json", run)
        return version, _validate_version_record(record, version), {
            "kind": "version", "value": version,
        }, _sha256(raw)

    channel = requested_channel or "default"
    if channel not in CHANNELS:
        raise BootstrapError("BLOCKED", "selector", "Requested channel is unsupported.")
    pointer, _raw = _read_catalog_json(f"channels/{channel}.json", run)
    version, record_ref = _validate_channel_pointer(pointer, channel)
    record, record_raw = _read_catalog_json(record_ref["path"], run)
    if _sha256(record_raw) != record_ref["sha256"]:
        raise BootstrapError("BLOCKED", "version-record", "Distribution version record SHA-256 mismatch.")
    return version, _validate_version_record(record, version), {
        "kind": "default" if requested_channel is None else "channel",
        "value": channel,
    }, _sha256(record_raw)


def _read_zip(raw: bytes, kind: str, release: dict) -> tuple[dict, bytes]:
    expected = release["packages"][kind]
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
    expected_source = release["source"]
    expected_release = release["release_tag"]
    if (package_manifest.get("product") != "AgentCollab"
            or package_manifest.get("release_version") != expected_release
            or package_manifest.get("source") != {
                "repository": expected_source["repository"], "commit": expected_source["commit"]}
            or package_manifest.get("service_branch") != release["service_branch"]):
        raise BootstrapError("BLOCKED", "package-verification", f"{kind.title()} package source provenance mismatch.")
    if kind == "runtime" and _sha256(setup_bytes) != release["setup"]["sha256"]:
        raise BootstrapError("BLOCKED", "package-verification", "Packaged deploy/setup.py SHA-256 mismatch.")
    return package_manifest, setup_bytes


def validate_release_manifest(version_record: dict, release_manifest_raw: bytes) -> dict:
    if _sha256(release_manifest_raw) != version_record["release_manifest"]["sha256"]:
        raise BootstrapError("BLOCKED", "release-verification", "Private release manifest SHA-256 mismatch.")
    try:
        release = json.loads(release_manifest_raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BootstrapError("BLOCKED", "release-verification", "Private release manifest is invalid.") from error
    source = release.get("source") if isinstance(release, dict) else None
    packages = release.get("packages") if isinstance(release, dict) else None
    setup = release.get("setup") if isinstance(release, dict) else None
    version = version_record["version"]
    if (not isinstance(release, dict) or release.get("schema_version") != 1
            or release.get("product") != "AgentCollab"
            or not isinstance(release.get("channel"), str) or release.get("channel") not in {"beta", "stable"}
            or release.get("release_tag") != version or release.get("release_version") != version
            or not isinstance(source, dict) or source.get("repository") != SOURCE_REPOSITORY
            or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("commit", "")))
            or release.get("service_branch") != "main"
            or not isinstance(setup, dict) or setup.get("package_path") != SETUP_PATH
            or not _digest(setup.get("sha256")) or not isinstance(release.get("execution_contract_version"), str)
            or not release["execution_contract_version"]
            or not isinstance(packages, dict)):
        raise BootstrapError("BLOCKED", "release-verification", "Private release provenance or identity is invalid.")
    for kind in ("runtime", "execution"):
        item = packages.get(kind)
        if (not isinstance(item, dict) or not _asset_name(item.get("filename"))
                or not _digest(item.get("sha256"))):
            raise BootstrapError("BLOCKED", "release-verification",
                                 f"Private {kind.title()} package identity or SHA-256 is invalid.")
    return release


def verify_bundle(release: dict, runtime_raw: bytes,
                  execution_raw: bytes) -> tuple[dict, dict, bytes]:
    runtime, setup_bytes = _read_zip(runtime_raw, "runtime", release)
    execution, _ = _read_zip(execution_raw, "execution", release)
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


def _download_release_manifest(record: dict, directory: Path, run=None) -> bytes:
    run = run or _run
    name = record["release_manifest"]["name"]
    result = run(["gh", "release", "download", record["release_tag"], "--repo", DISTRIBUTION_REPOSITORY,
                  "--dir", str(directory), "--pattern", name], timeout=300)
    if not result or result.returncode:
        raise BootstrapError("BLOCKED", "distribution-download", "The exact Distribution release manifest is unavailable.")
    try:
        return (directory / name).read_bytes()
    except OSError as error:
        raise BootstrapError("BLOCKED", "distribution-download", "The exact release manifest asset is missing.") from error


def _download_packages(release: dict, directory: Path, run=None) -> tuple[bytes, bytes]:
    run = run or _run
    names = [release["packages"][kind]["filename"] for kind in ("runtime", "execution")]
    args = ["gh", "release", "download", release["release_tag"], "--repo", DISTRIBUTION_REPOSITORY,
            "--dir", str(directory)]
    for name in names:
        args.extend(["--pattern", name])
    result = run(args, timeout=300)
    if not result or result.returncode:
        raise BootstrapError("BLOCKED", "distribution-download", "Exact Runtime/Execution release assets are unavailable.")
    try:
        return (directory / names[0]).read_bytes(), (directory / names[1]).read_bytes()
    except OSError as error:
        raise BootstrapError("BLOCKED", "distribution-download", "A required exact release asset is missing.") from error


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", nargs="?", choices=("plan", "apply", "verify"), default="plan")
    parser.add_argument("--manifest", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--version", help="exact immutable Distribution version")
    parser.add_argument("--channel", help="Distribution channel pointer: default, beta, or stable")
    parser.add_argument("--installation-root", type=Path,
                        help="personal installation root (default: ./agentcollab from the current directory)")
    parser.add_argument("--control-repository", help="existing personal Execution repository to reuse")
    parser.add_argument("--web-port", type=int, help="explicit Web port (omitted preserves automatic port selection)")
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
        if args.version is not None and args.channel is not None:
            raise BootstrapError("BLOCKED", "selector", "--version and --channel cannot be used together.")
        if args.phase == "apply" and args.version is None:
            raise BootstrapError("ACTION_REQUIRED", "selector",
                                 "APPLY requires the exact version resolved by the reviewed PLAN.",
                                 "Rerun APPLY with `--version <resolved_version>` from PLAN evidence.")
        if args.phase == "apply" and (not args.approved_plan_sha256 or not _digest(args.approved_plan_sha256)):
            raise BootstrapError("ACTION_REQUIRED", "plan-approval",
                                 "APPLY requires the reviewed PLAN SHA-256.",
                                 "Run `install.sh plan`, review the result, then pass its plan_sha256 to APPLY.")
        if args.phase != "apply" and args.approved_plan_sha256:
            raise BootstrapError("BLOCKED", "plan-approval", "--approved-plan-sha256 is only valid with APPLY.")
        bootstrap_bytes = Path(__file__).read_bytes()
        validate_installer_manifest(
            json.loads(args.manifest.read_text(encoding="utf-8")), bootstrap_bytes)
        require_github_auth(command_fn, which)
        version, version_record, requested_selector, version_record_sha256 = resolve_version(
            requested_version=args.version, requested_channel=args.channel, run=command_fn)
        installation_root = (args.installation_root.expanduser().resolve(strict=False) if args.installation_root
                             else ((cwd or Path.cwd()) / "agentcollab").resolve(strict=False))
        with tempfile.TemporaryDirectory(prefix="agentcollab-private-packages-") as temporary:
            download_dir = Path(temporary)
            release_raw = _download_release_manifest(version_record, download_dir, command_fn)
            release = validate_release_manifest(version_record, release_raw)
            runtime_raw, execution_raw = _download_packages(release, download_dir, command_fn)
            _release, _runtime_manifest, _setup_bytes = verify_bundle(release, runtime_raw, execution_raw)
            runtime_package = download_dir / release["packages"]["runtime"]["filename"]
            execution_package = download_dir / release["packages"]["execution"]["filename"]
            runtime_package.write_bytes(runtime_raw)
            execution_package.write_bytes(execution_raw)
            runtime_root = download_dir / "verified-runtime"
            setup_path = materialize_verified_runtime(runtime_raw, runtime_root)
            setup_args = [sys.executable, str(setup_path), args.phase,
                          "--installation-root", str(installation_root),
                          "--runtime-package", str(runtime_package),
                          "--execution-package", str(execution_package),
                          "--service-name", args.service_name]
            if args.web_port is not None:
                setup_args.extend(["--web-port", str(args.web_port)])
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
                setup_args.extend(["--approved-plan-sha256", args.approved_plan_sha256])
            runner = setup_command_fn or subprocess.run
            environment = dict(os.environ)
            prior_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = str(runtime_root) + (os.pathsep + prior_pythonpath if prior_pythonpath else "")
            print(json.dumps({
                "phase": "distribution-resolution",
                "requested_selector": requested_selector,
                "resolved_version": version,
                "distribution": {
                    "repository": DISTRIBUTION_REPOSITORY,
                    "release_tag": version_record["release_tag"],
                    "version_record_path": f"versions/{version}.json",
                    "version_record_sha256": version_record_sha256,
                    "release_manifest": version_record["release_manifest"],
                },
                "source": release["source"],
            }, sort_keys=True), file=sys.stderr)
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
