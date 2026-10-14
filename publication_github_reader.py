"""Authenticated, read-only GitHub identity/catalog inspection for publication.

This adapter has no write operations. GitHub repository admin permission is
reported as an observed capability, never promoted into Release Admin authority.
Until an accountable Release Admin identity and independent approval provider
are configured by an approved policy, live APPLY is unconditionally blocked.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Callable

from publication_approval import ApprovalBlocked

SOURCE_REPOSITORY = "lkhkhk/AgentCollab"
PUBLIC_REPOSITORY = "AgentCollab/AgentCollab-Public"
DISTRIBUTION_REPOSITORY = "AgentCollab/AgentCollab-Distribution"
READABLE_REPOSITORIES = frozenset((SOURCE_REPOSITORY, PUBLIC_REPOSITORY, DISTRIBUTION_REPOSITORY))
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}\Z")

# Deliberately unset: repository ADMIN permission alone does not designate a
# human as the Release Admin, and the observed account list has multiple admins.
DESIGNATED_RELEASE_ADMIN: str | None = None
INDEPENDENT_APPROVAL_PROVIDER_CONFIGURED = False


class GitHubReadBlocked(ApprovalBlocked):
    """Authenticated GitHub evidence is missing, malformed, or untrusted."""


@dataclass(frozen=True)
class GitHubIdentity:
    login: str
    numeric_id: int


@dataclass(frozen=True)
class GitHubFile:
    repository: str
    path: str
    ref: str
    raw: bytes
    git_blob_sha: str


def _git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


class ReadOnlyGitHubReader:
    """Read GitHub evidence using the identity authenticated by the local gh CLI."""

    def __init__(self, run: Callable | None = None):
        self._run = run or self._subprocess_run

    @staticmethod
    def _subprocess_run(argv):
        return subprocess.run(argv, check=False, text=True, capture_output=True)

    def _api_json(self, endpoint: str, *args: str):
        if not isinstance(endpoint, str) or not endpoint.startswith("/"):
            raise GitHubReadBlocked("GitHub API endpoint must be a repository-relative path")
        result = self._run(["gh", "api", endpoint.lstrip("/"), *args])
        if not result or getattr(result, "returncode", 1):
            raise GitHubReadBlocked("authenticated GitHub API read failed")
        try:
            return json.loads(result.stdout)
        except (TypeError, ValueError, UnicodeError) as exc:
            raise GitHubReadBlocked("GitHub API returned malformed JSON") from exc

    def identity(self) -> GitHubIdentity:
        value = self._api_json("/user")
        if not isinstance(value, dict):
            raise GitHubReadBlocked("authenticated GitHub identity is malformed")
        login, numeric_id = value.get("login"), value.get("id")
        if (not isinstance(login, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login)
                or not isinstance(numeric_id, int) or isinstance(numeric_id, bool) or numeric_id <= 0):
            raise GitHubReadBlocked("authenticated GitHub identity is incomplete")
        return GitHubIdentity(login, numeric_id)

    def _collaborator_pages(self, repository: str) -> list:
        if repository not in READABLE_REPOSITORIES:
            raise GitHubReadBlocked("repository is outside the fixed publication allowlist")
        endpoint = f"repos/{repository}/collaborators?affiliation=all&per_page=100"
        result = self._run(["gh", "api", endpoint, "--paginate", "--jq", ".[] | {login,permissions}"])
        if not result or getattr(result, "returncode", 1):
            raise GitHubReadBlocked("authenticated GitHub permission read failed")
        people = []
        try:
            for line in result.stdout.splitlines():
                if line.strip():
                    people.append(json.loads(line))
        except (TypeError, ValueError, UnicodeError) as exc:
            raise GitHubReadBlocked("collaborator permission response is malformed") from exc
        if not people:
            raise GitHubReadBlocked("collaborator permission response is empty")
        return people

    def write_capable_accounts(self, repository: str) -> tuple[str, ...]:
        people = self._collaborator_pages(repository)
        accounts = set()
        for person in people:
            if not isinstance(person, dict) or not isinstance(person.get("login"), str):
                raise GitHubReadBlocked("collaborator identity is malformed")
            permissions = person.get("permissions")
            if not isinstance(permissions, dict):
                raise GitHubReadBlocked("collaborator permissions are missing")
            if any(permissions.get(key) is True for key in ("admin", "maintain", "push")):
                accounts.add(person["login"])
        return tuple(sorted(accounts, key=str.casefold))

    def source_main_sha(self) -> str:
        value = self._api_json(f"/repos/{SOURCE_REPOSITORY}/git/ref/heads/main")
        obj = value.get("object") if isinstance(value, dict) else None
        sha = obj.get("sha") if isinstance(obj, dict) else None
        if (not isinstance(obj, dict) or obj.get("type") != "commit"
                or not isinstance(sha, str) or _SHA40.fullmatch(sha) is None):
            raise GitHubReadBlocked("Source main does not resolve to an exact commit")
        return sha

    def read_distribution_file(self, path: str, *, ref: str = "main") -> GitHubFile:
        if not isinstance(ref, str) or ref != "main":
            raise GitHubReadBlocked("publication catalog reads are pinned to Distribution main")
        parts = path.split("/") if isinstance(path, str) else []
        if (len(parts) != 2 or parts[0] not in {"channels", "versions", "approvals"}
                or (parts[0] == "channels" and path not in {
                    "channels/default.json", "channels/beta.json", "channels/stable.json"})
                or (parts[0] != "channels" and
                    (not parts[1].endswith(".json")
                     or _VERSION.fullmatch(parts[1][:-5]) is None))):
            raise GitHubReadBlocked("Distribution catalog path is not allowed")
        value = self._api_json(
            f"/repos/{DISTRIBUTION_REPOSITORY}/contents/{path}?ref=main"
        )
        if not isinstance(value, dict) or value.get("encoding") != "base64":
            raise GitHubReadBlocked("Distribution file response is not base64 content")
        content, blob_sha = value.get("content"), value.get("sha")
        if not isinstance(content, str) or not isinstance(blob_sha, str) or _SHA40.fullmatch(blob_sha) is None:
            raise GitHubReadBlocked("Distribution file identity is incomplete")
        try:
            raw = base64.b64decode("".join(content.split()), validate=True)
        except (ValueError, UnicodeError) as exc:
            raise GitHubReadBlocked("Distribution file content is malformed") from exc
        if _git_blob_sha(raw) != blob_sha:
            raise GitHubReadBlocked("Distribution raw bytes disagree with Git blob SHA")
        return GitHubFile(DISTRIBUTION_REPOSITORY, path, ref, raw, blob_sha)

    def read_channel_snapshot(self, channel: str) -> dict:
        """Read an exact Distribution channel blob for a future CAS plan only."""
        if channel not in ("default", "beta", "stable"):
            raise GitHubReadBlocked("channel is not supported")
        value = self.read_distribution_file(f"channels/{channel}.json", ref="main")
        return {"sha": value.git_blob_sha, "content": value.raw,
                "repository": value.repository, "path": value.path,
                "ref": value.ref}

    def inspect_authority(self) -> dict:
        """Report observed identities and fail closed on absent trust configuration."""
        actor = self.identity()
        public_writers = self.write_capable_accounts(PUBLIC_REPOSITORY)
        distribution_writers = self.write_capable_accounts(DISTRIBUTION_REPOSITORY)
        source_sha = self.source_main_sha()
        blockers = []
        if DESIGNATED_RELEASE_ADMIN is None:
            blockers.append("no designated Release Admin identity is configured")
        elif actor.login != DESIGNATED_RELEASE_ADMIN:
            blockers.append("authenticated actor is not the designated Release Admin")
        if not INDEPENDENT_APPROVAL_PROVIDER_CONFIGURED:
            blockers.append("no independent UAT/user-approval evidence provider is configured")
        if len(distribution_writers) != 1:
            blockers.append("Distribution does not have exactly one observed write-capable account")
        return {
            "authenticated_actor": {"login": actor.login, "id": actor.numeric_id},
            "source_main_sha": source_sha,
            "public_write_capable_accounts": public_writers,
            "distribution_write_capable_accounts": distribution_writers,
            "actor_can_write_public": actor.login in public_writers,
            "actor_can_write_distribution": actor.login in distribution_writers,
            "release_admin_designated": DESIGNATED_RELEASE_ADMIN is not None,
            "independent_approval_provider_configured": INDEPENDENT_APPROVAL_PROVIDER_CONFIGURED,
            "apply_permitted": not blockers,
            "blockers": tuple(blockers),
        }
