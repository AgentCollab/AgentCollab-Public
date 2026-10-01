#!/usr/bin/env python3
"""Private, source-independent entry for the canonical AgentCollab DEV installer.

The installer acquires and verifies source only after host/auth checks, then
delegates topology, profiles, services, and readiness to development_setup.py.
It never accepts secret values as arguments or records them in its state.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

READY = "READY"
ACTION_REQUIRED = "ACTION_REQUIRED"
BLOCKED = "BLOCKED"
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
DEV_ROLES = ("DEV0", "DEV1", "DEV2")
ENVIRONMENTS = ("PROD", "UAT", "TEST", "DUT")
PROFILE_ENVIRONMENTS = {
    "RUN": {"prod": "PROD"}, "UAT": {"uat": "UAT"},
    "DEV0": {"test": "TEST", "dut": "DUT"},
    "DEV1": {"test": "TEST", "dut": "DUT"},
    "DEV2": {"test": "TEST", "dut": "DUT"},
}
TIER_BY_ROLE = {"RUN": "prod", "UAT": "uat", "DEV0": "dev0", "DEV1": "dev1", "DEV2": "dev2"}
STATUS_CODES = {READY: 0, ACTION_REQUIRED: 1, BLOCKED: 2}


@dataclass
class InstallRequest:
    repository: str
    revision: str
    source_dir: Path
    installation_root: Path
    workspace_role: str
    profile: str
    callback_urls: dict[str, str] = field(default_factory=dict)
    expected_github_login: str = ""

    @property
    def target(self) -> str:
        return f"{self.workspace_role}/{self.profile}"


def command(args, *, timeout=60, env=None):
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                              check=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _completed(args, stdout="", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout, "")


def _path_inside(path: Path, home: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(home.resolve(strict=False))
        return True
    except ValueError:
        return False


def _has_symlink_component(path: Path, stop: Path) -> bool:
    cursor = path.expanduser().absolute()
    stop = stop.expanduser().absolute()
    while cursor != stop and stop in cursor.parents:
        if cursor.is_symlink():
            return True
        cursor = cursor.parent
    return cursor.is_symlink()


def _directory_state(path: Path) -> tuple[bool, str]:
    if path.is_symlink():
        return False, "selected path is a symbolic link"
    if not path.exists():
        return True, "absent"
    if not path.is_dir():
        return False, "selected path is not a directory"
    try:
        empty = not any(path.iterdir())
        return empty, "empty" if empty else "non-empty"
    except OSError:
        return False, "selected directory cannot be inspected"


def validate_request(request: InstallRequest) -> str | None:
    if not REPOSITORY_RE.fullmatch(request.repository):
        return "repository must use OWNER/REPOSITORY form"
    if not REVISION_RE.fullmatch(request.revision):
        return "revision must be an exact full commit SHA"
    if request.workspace_role not in DEV_ROLES or request.profile not in {"test", "dut"}:
        return "target must be a fixed DEV role and TEST or DUT profile"
    home = Path.home().resolve(strict=False)
    source_input = request.source_dir.expanduser().absolute()
    install_input = request.installation_root.expanduser().absolute()
    if _has_symlink_component(source_input, home) or _has_symlink_component(install_input, home):
        return "source and installation roots must not traverse symbolic links"
    source = source_input.resolve(strict=False)
    install = install_input.resolve(strict=False)
    if source == home or install == home or source == Path("/") or install == Path("/"):
        return "source and installation roots must be distinct, non-root paths below the current HOME"
    if not _path_inside(source, home) or not _path_inside(install, home):
        return "source and installation roots must be below the current HOME"
    if source == install or source in install.parents or install in source.parents:
        return "source and installation roots must not overlap"
    for environment in ENVIRONMENTS:
        callback = request.callback_urls.get(environment, "")
        if not callback:
            continue
        parsed = urlsplit(callback)
        local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (parsed.scheme != "https" and not local_http) or not parsed.hostname or parsed.username or parsed.password:
            return f"{environment} callback must be HTTPS or a loopback HTTP URL without embedded credentials"
    return None


def build_development_config(request: InstallRequest, *, port_start=19000) -> dict:
    install = request.installation_root.expanduser().resolve(strict=False)
    callback_urls = request.callback_urls
    roles = {}
    port = int(port_start)
    for role, profiles in PROFILE_ENVIRONMENTS.items():
        workspace = install / role
        runner = install / ".runners" / role.lower()
        selector = [f"agentcollab-{role.lower()}"]
        roles[role] = {}
        for profile, environment in profiles.items():
            roles[role][profile] = {
                "web_port": port,
                "service_name": f"agentcollab-{role.lower()}-{profile}.service",
                "runner_selector": selector,
                "runner_tier": TIER_BY_ROLE[role],
                "runner_root": str(runner),
                "callback_url": callback_urls[environment],
            }
            port += 1
    return {
        "version": 1,
        "installation_root": str(install),
        "self_repository": request.repository,
        "repository_owner": request.repository.split("/", 1)[0],
        "source_ref": request.revision,
        "roles": roles,
        "targets": [request.target],
    }


def _source_status(source: Path, repository: str, revision: str, run=command) -> tuple[bool, str]:
    if source.is_symlink() or not source.is_dir():
        return False, "acquired source directory is unavailable or unsafe"
    remote = run(["git", "-C", str(source), "remote", "get-url", "origin"])
    if not remote or remote.returncode:
        return False, "acquired source origin could not be verified"
    match = re.search(r"(?:github\.com[:/])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$", remote.stdout.strip())
    if not match or match.group(1).casefold() != repository.casefold():
        return False, "acquired source repository identity does not match the requested repository"
    head = run(["git", "-C", str(source), "rev-parse", "HEAD"])
    if not head or head.returncode or head.stdout.strip() != revision:
        return False, "acquired source revision does not match the requested exact SHA"
    state = run(["git", "-C", str(source), "status", "--porcelain"])
    if not state or state.returncode or state.stdout.strip():
        return False, "acquired source is dirty or its worktree state cannot be verified"
    return True, "exact source repository, revision, and clean worktree verified"


class GitSourceProvider:
    """Replaceable authenticated-Git source adapter; no credentials enter argv."""

    def __init__(self, run=command):
        self.run = run

    def acquire(self, repository: str, revision: str, destination: Path) -> tuple[str, str]:
        if destination.exists():
            valid, reason = _source_status(destination, repository, revision, self.run)
            if valid:
                return "REUSE", reason
            return "BLOCKED", reason
        if destination.is_symlink():
            return "BLOCKED", "source destination is a symbolic link"
        parent = destination.parent
        try:
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            staging_parent = Path(tempfile.mkdtemp(prefix=".agentcollab-source-", dir=parent))
        except OSError:
            return "BLOCKED", "safe source staging directory could not be created"
        staging = staging_parent / "checkout"
        try:
            cloned = self.run(["gh", "repo", "clone", repository, str(staging)], timeout=300)
            if not cloned or cloned.returncode:
                return "ACTION_REQUIRED", "authenticated source clone failed; verify GitHub source access and rerun"
            remote = self.run(["git", "-C", str(staging), "remote", "get-url", "origin"])
            match = re.search(r"(?:github\.com[:/])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?$",
                              remote.stdout.strip() if remote and remote.returncode == 0 else "")
            if not match or match.group(1).casefold() != repository.casefold():
                return "BLOCKED", "cloned repository identity does not match the requested source"
            fetched = self.run(["git", "-C", str(staging), "fetch", "--no-tags", "origin", revision], timeout=300)
            if not fetched or fetched.returncode:
                return "BLOCKED", "requested exact source revision could not be fetched"
            checked_out = self.run(["git", "-C", str(staging), "checkout", "--detach", revision], timeout=120)
            if not checked_out or checked_out.returncode:
                return "BLOCKED", "requested exact source revision could not be checked out"
            valid, reason = _source_status(staging, repository, revision, self.run)
            if not valid:
                return "BLOCKED", reason
            if destination.exists() or destination.is_symlink():
                return "BLOCKED", "source destination changed during acquisition"
            os.replace(staging, destination)
            return "ACQUIRED", reason
        except OSError:
            return "BLOCKED", "source acquisition could not be committed safely"
        finally:
            shutil.rmtree(staging_parent, ignore_errors=True)


def _json_command(args, run=command):
    result = run(args)
    if not result or result.returncode:
        return None
    try:
        return json.loads(result.stdout)
    except (TypeError, json.JSONDecodeError):
        return None


def preflight(request: InstallRequest, *, run=command, which=shutil.which,
              environ=None, host_system=None) -> dict:
    environ = dict(os.environ if environ is None else environ)
    checks = []

    def add(name, status, reason, action=""):
        checks.append({"check": name, "status": status, "reason": reason, **({"next_action": action} if action else {})})

    if not (host_system or platform.system()).casefold().startswith("linux"):
        add("host", BLOCKED, "This private installer currently supports Linux user-systemd hosts.")
    else:
        add("host", READY, "Linux host detected.")
    home = Path(environ.get("HOME", str(Path.home()))).expanduser()
    if not home.is_dir() or not os.access(home, os.W_OK):
        add("home", BLOCKED, "Current user HOME is unavailable or not writable.")
    else:
        add("home", READY, "Current user HOME is available.")
    issue = validate_request(request)
    if issue:
        add("install-paths", BLOCKED, issue)
    else:
        add("install-paths", READY, "Selected roots are distinct, user-local, and do not traverse symlinks.")
    for tool in ("git", "gh", "python3", "systemctl"):
        if not which(tool, path=environ.get("PATH")):
            add("tool-" + tool, ACTION_REQUIRED, f"Required tool {tool} is unavailable.",
                f"Install {tool} using the supported host instructions, then rerun this installer.")
        else:
            add("tool-" + tool, READY, f"Required tool {tool} is available.")
    if not sys.platform.startswith("linux") and not host_system:
        pass
    elif which("systemctl", path=environ.get("PATH")):
        result = run([which("systemctl", path=environ.get("PATH")) or "systemctl", "--user", "show-environment"])
        if result and result.returncode == 0:
            add("systemd-user", READY, "User systemd manager is available.")
        else:
            add("systemd-user", ACTION_REQUIRED, "User systemd manager is not available in this session.",
                "Start a systemd-enabled user session, then rerun this installer.")
    return {"checks": checks}


def inspect_github_access(repository: str, *, expected_login="", run=command) -> dict:
    auth = run(["gh", "auth", "status", "--hostname", "github.com"])
    if not auth or auth.returncode:
        return {"status": ACTION_REQUIRED, "next_action": "Authenticate the intended GitHub account with `gh auth login`, then rerun."}
    login = run(["gh", "api", "user", "--jq", ".login"])
    if not login or login.returncode or not login.stdout.strip():
        return {"status": ACTION_REQUIRED, "next_action": "Complete GitHub CLI authentication, then rerun."}
    actual_login = login.stdout.strip()
    if expected_login and actual_login.casefold() != expected_login.casefold():
        return {"status": ACTION_REQUIRED, "operator_login": actual_login,
                "next_action": f"Authenticate GitHub CLI as {expected_login}, then rerun."}
    repo = _json_command(["gh", "api", f"repos/{repository}"], run)
    if not isinstance(repo, dict):
        return {"status": ACTION_REQUIRED, "operator_login": actual_login,
                "next_action": "Grant the authenticated account read access to the intended source repository, then rerun."}
    canonical = repo.get("full_name", "")
    if canonical.casefold() != repository.casefold():
        return {"status": BLOCKED, "reason": "GitHub resolved a different repository identity than requested."}
    permissions = repo.get("permissions") if isinstance(repo.get("permissions"), dict) else {}
    return {"status": READY, "operator_login": actual_login, "repository": canonical,
            "contents_readable": True, "repository_admin": permissions.get("admin") is True,
            "repository_push": permissions.get("push") is True}


def _managed_state_path(root: Path) -> Path:
    return root / ".agentcollab-guided-installer" / "state.json"


def _read_state(root: Path) -> dict | None:
    path = _managed_state_path(root)
    if path.is_symlink() or not path.is_file():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return state if isinstance(state, dict) else None


def _write_json(path: Path, value: dict, mode=0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise OSError("managed state path is a symbolic link")
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass


def _installation_root_gate(request: InstallRequest) -> tuple[str, str]:
    root = request.installation_root.expanduser().resolve(strict=False)
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        return BLOCKED, "selected installation root is unsafe"
    if not root.exists() or not any(root.iterdir()):
        return READY, "selected installation root is absent or empty"
    state = _read_state(root)
    if not state:
        return BLOCKED, "selected installation root contains unrecognized state; it will not be reused or removed"
    expected = {"repository": request.repository, "revision": request.revision,
                "workspace_role": request.workspace_role, "profile": request.profile}
    if any(state.get(key) != value for key, value in expected.items()):
        return BLOCKED, "installer state belongs to a different source revision or target"
    return READY, "matching guided-installer state found; safe rerun may continue"


def _write_setup_config(request: InstallRequest) -> Path:
    state_dir = request.installation_root.expanduser().resolve(strict=False) / ".agentcollab-guided-installer"
    path = state_dir / "development-setup.json"
    _write_json(path, build_development_config(request))
    return path


def _parse_json_result(result, name: str) -> tuple[dict | None, str | None]:
    if not result:
        return None, f"canonical {name} command could not be started"
    try:
        payload = json.loads(result.stdout or result.stderr)
    except (TypeError, json.JSONDecodeError):
        return None, f"canonical {name} command returned unreadable output"
    if not isinstance(payload, dict):
        return None, f"canonical {name} command returned an invalid result"
    return payload, None


def _setup_command(source: Path, phase: str, config_path: Path, plan_path: Path | None = None,
                   target: str | None = None, *, sync=False, start=False) -> list[str]:
    args = [sys.executable, str(source / "deploy/development_setup.py"), phase,
            "--config", str(config_path)]
    if plan_path:
        args.extend(["--plan-file", str(plan_path)])
    if target:
        args.extend(["--target", target])
    if sync:
        args.append("--sync-github")
    if start:
        args.append("--start-services")
    return args




def run_installer(request: InstallRequest, *, command_fn=command, which=shutil.which,
                  environ=None, input_fn=input, source_provider=None) -> dict:
    environ = dict(os.environ if environ is None else environ)
    invalid = validate_request(request)
    if invalid:
        return {"status": BLOCKED, "reason": invalid}
    checks = preflight(request, run=command_fn, which=which, environ=environ)
    blocked = next((item for item in checks["checks"] if item["status"] == BLOCKED), None)
    if blocked:
        return {"status": BLOCKED, "phase": "preflight", "first_cause": blocked}
    missing_tools = [item for item in checks["checks"] if item["status"] == ACTION_REQUIRED]
    if missing_tools:
        return {"status": ACTION_REQUIRED, "phase": "preflight", "actions": missing_tools}
    auth = inspect_github_access(request.repository,
                                 expected_login=request.expected_github_login, run=command_fn)
    if auth["status"] != READY:
        return {"status": auth["status"], "phase": "github-auth", **auth}
    root_status, root_reason = _installation_root_gate(request)
    if root_status != READY:
        return {"status": root_status, "phase": "install-root", "reason": root_reason}
    provider = source_provider or GitSourceProvider(command_fn)
    source_status, source_reason = provider.acquire(request.repository, request.revision,
                                                    request.source_dir.expanduser().resolve(strict=False))
    if source_status not in {"ACQUIRED", "REUSE"}:
        return {"status": source_status, "phase": "source-acquisition", "reason": source_reason}
    valid, source_reason = _source_status(request.source_dir.expanduser().resolve(strict=False),
                                          request.repository, request.revision, command_fn)
    if not valid:
        return {"status": BLOCKED, "phase": "source-verification", "reason": source_reason}
    if not all(request.callback_urls.get(environment) for environment in ENVIRONMENTS):
        missing_callbacks = [environment for environment in ENVIRONMENTS if not request.callback_urls.get(environment)]
        return {"status": ACTION_REQUIRED, "phase": "configuration",
                "missing_callbacks": missing_callbacks,
                "next_action": "Provide an explicit callback URL for each listed GitHub Environment, then rerun."}
    setup_config = build_development_config(request)
    try:
        state_path = _managed_state_path(request.installation_root.expanduser().resolve(strict=False))
        state = {"repository": request.repository, "revision": request.revision,
                 "workspace_role": request.workspace_role, "profile": request.profile,
                 "phase": "source_verified"}
        _write_json(state_path, state)
        config_path = _write_setup_config(request)
    except OSError:
        return {"status": BLOCKED, "phase": "configuration", "reason": "non-secret installer state could not be written safely"}
    source = request.source_dir.expanduser().resolve(strict=False)
    target_root = request.installation_root.expanduser().resolve(strict=False) / request.workspace_role
    target_env = target_root / "web" / f".env.{request.profile}"
    plan_path = request.installation_root.expanduser().resolve(strict=False) / ".agentcollab-guided-installer" / "reviewed-plan.json"
    plan_cmd = _setup_command(source, "plan", config_path, target=request.target)
    raw_plan = command_fn(plan_cmd, timeout=180)
    plan, error = _parse_json_result(raw_plan, "plan")
    if error:
        return {"status": BLOCKED, "phase": "canonical-plan", "reason": error}
    try:
        _write_json(plan_path, plan)
    except OSError:
        return {"status": BLOCKED, "phase": "canonical-plan", "reason": "reviewed PLAN could not be saved safely"}
    if plan.get("status") == ACTION_REQUIRED:
        return {"status": ACTION_REQUIRED, "phase": "canonical-plan", "plan": plan,
                "next_action": "Complete the bounded setup-time runner-administration action in the canonical PLAN, then rerun."}
    if plan.get("status") != "PLAN_READY":
        return {"status": BLOCKED, "phase": "canonical-plan", "plan": plan,
                "first_cause": next((item for item in plan.get("actions", []) if item.get("action") == "BLOCKED"), None)}
    target_exists = target_env.is_file()
    credentials_missing = plan.get("missing_operator_inputs", [])
    root_exists = target_root.exists()
    if not root_exists or not target_exists:
        try:
            answer = input_fn("Review the canonical PLAN above. Apply this reviewed foundation plan (creates the selected Workspace/profile and unit only; it will not sync secrets or start services)? [y/N] ").strip().casefold()
        except (EOFError, OSError):
            answer = ""
        if answer not in {"y", "yes"}:
            return {"status": ACTION_REQUIRED, "phase": "plan-review", "plan": plan,
                    "next_action": "Review the saved non-secret PLAN and rerun to continue."}
        applied = command_fn(_setup_command(source, "apply", config_path, plan_path,
                                            request.target), timeout=300)
        payload, error = _parse_json_result(applied, "apply")
        if payload and payload.get("status") == ACTION_REQUIRED:
            return {"status": ACTION_REQUIRED, "phase": "foundation-apply", "plan": plan,
                    "next_action": payload.get("reason", "Complete the canonical setup-time action, then rerun.")}
        if error or not applied or applied.returncode or not payload or payload.get("status") != "APPLIED":
            return {"status": BLOCKED, "phase": "foundation-apply",
                    "first_cause": error or "canonical development setup foundation APPLY failed"}
        state["phase"] = "foundation_applied"
        _write_json(state_path, state)
        current_env = target_env
        credential_names = sorted({item.get("credential_name") for item in credentials_missing
                                   if item.get("credential_name")})
        return {"status": ACTION_REQUIRED, "phase": "operator-inputs", "plan": plan,
                "profile": str(current_env), "missing_credential_names": credential_names,
                "next_action": ("Add only the listed credential roles to the selected mode-0600 Workspace Web profile using a secure editor; never put values in shell history or installer arguments, then rerun." if credential_names else
                                "Complete the selected runner registration/service/runtime action shown by canonical PLAN, then rerun.")}
    credential_names = sorted({item.get("credential_name") for item in credentials_missing
                               if item.get("credential_name")})
    if credential_names:
        return {"status": ACTION_REQUIRED, "phase": "operator-inputs", "plan": plan,
                "profile": str(target_env), "missing_credential_names": credential_names,
                "next_action": "Add only the listed credential roles to the selected mode-0600 Workspace Web profile using a secure editor; never put values in shell history or installer arguments, then rerun."}
    try:
        answer = input_fn("Review the exact canonical PLAN above. Synchronize only the selected GitHub Environment and start the selected Web service now? [y/N] ").strip().casefold()
    except (EOFError, OSError):
        answer = ""
    if answer not in {"y", "yes"}:
        return {"status": ACTION_REQUIRED, "phase": "plan-review", "plan": plan,
                "next_action": "Review the saved non-secret PLAN and rerun to continue."}
    applied = command_fn(_setup_command(source, "apply", config_path, plan_path,
                                        request.target, sync=True, start=True), timeout=300)
    payload, error = _parse_json_result(applied, "apply")
    if error or not applied or applied.returncode or not payload or payload.get("status") != "APPLIED":
        return {"status": BLOCKED, "phase": "canonical-apply",
                "first_cause": error or "canonical development setup APPLY failed; inspect canonical remediation without exposing credential output"}
    verified_result = command_fn(_setup_command(source, "verify", config_path,
                                                target=request.target), timeout=300)
    verified, error = _parse_json_result(verified_result, "verify")
    if error or not verified_result or verified_result.returncode or not verified:
        return {"status": BLOCKED, "phase": "canonical-verify",
                "first_cause": error or "canonical development setup VERIFY failed"}
    if verified.get("status") == "BLOCKED_OPERATOR_CREDENTIAL_ONLY":
        return {"status": ACTION_REQUIRED, "phase": "canonical-verify", "verify": verified,
                "next_action": "Provide the missing orchestration credential through the selected secure profile input, then rerun."}
    if verified.get("status") != READY:
        return {"status": BLOCKED, "phase": "canonical-verify", "verify": verified,
                "first_cause": "canonical VERIFY/doctor did not report READY"}
    state["phase"] = "ready"
    _write_json(state_path, state)
    return {"status": READY, "handoff": {"repository": request.repository,
            "revision": request.revision, "installation_root": str(request.installation_root.expanduser().resolve(strict=False)),
            "workspace_role": request.workspace_role, "profile": request.profile,
            "setup_status": READY, "doctor_status": READY,
            "next_action": "Open the selected Web profile and continue the intended DEV lifecycle."},
            "verify": verified}


def _ask(label, default="", input_fn=input):
    suffix = f" [{default}]" if default else ""
    try:
        value = input_fn(f"{label}{suffix}: ").strip()
    except (EOFError, OSError):
        value = ""
    return value or default


def _interactive_request(args, input_fn=input) -> InstallRequest:
    repository = args.repository or _ask("Private AgentCollab source repository OWNER/REPOSITORY", input_fn=input_fn)
    revision = args.revision or _ask("Exact full source revision SHA", input_fn=input_fn)
    home = Path.home()
    source_default = str(home / ".local/share/agentcollab/source" / revision) if revision else ""
    source_dir = Path(args.source_dir) if args.source_dir else Path(_ask("Fresh source acquisition destination", source_default, input_fn))
    install_default = str(home / "AgentCollab")
    installation_root = Path(args.installation_root) if args.installation_root else Path(_ask("Fresh development installation root", install_default, input_fn))
    role = args.workspace_role or _ask("Target development Workspace Role (DEV0, DEV1, DEV2)", input_fn=input_fn).upper()
    profile = args.profile or _ask("Target profile (TEST or DUT)", "DUT", input_fn).lower()
    callbacks = {}
    for environment in ENVIRONMENTS:
        callbacks[environment] = getattr(args, "callback", {}).get(environment, "")
        if not callbacks[environment]:
            callbacks[environment] = _ask(f"Explicit {environment} workflow callback URL", input_fn=input_fn)
    return InstallRequest(repository=repository, revision=revision, source_dir=source_dir,
                          installation_root=installation_root, workspace_role=role,
                          profile=profile, callback_urls=callbacks,
                          expected_github_login=args.github_login or "")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", help="private source OWNER/REPOSITORY")
    parser.add_argument("--revision", help="exact full candidate SHA")
    parser.add_argument("--source-dir", type=Path, help="fresh source acquisition destination")
    parser.add_argument("--installation-root", type=Path, help="fresh development installation root")
    parser.add_argument("--workspace-role", choices=DEV_ROLES)
    parser.add_argument("--profile", choices=("test", "dut"))
    parser.add_argument("--github-login", default="", help="optional expected authenticated GitHub login")
    parser.add_argument("--callback", action="append", default=[], metavar="ENV=URL",
                        help="explicit workflow callback URL; repeat for PROD/UAT/TEST/DUT")
    args = parser.parse_args(argv)
    callbacks = {}
    for raw in args.callback:
        if "=" not in raw:
            parser.error("--callback must use ENV=URL")
        environment, url = raw.split("=", 1)
        environment = environment.upper()
        if environment not in ENVIRONMENTS or environment in callbacks:
            parser.error("--callback must name each supported Environment at most once")
        callbacks[environment] = url
    args.callback = callbacks
    request = _interactive_request(args)
    result = run_installer(request)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return STATUS_CODES.get(result.get("status"), 2)


if __name__ == "__main__":
    raise SystemExit(main())
