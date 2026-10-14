"""Immutable GitHub single-ref CAS request contract for publication.

This module intentionally has no GitHub transport and cannot perform APPLY.
It describes the Git Data API sequence a separately approved publisher would
need to execute after a trusted authority provider exists. The commit parent
binds the update to the observed Distribution ref; force=false makes a
competing, divergent ref advance reject the final update. This does not create
a cross-repository transaction with Source main or an approval record.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass

from publication_approval import ApprovalBlocked

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_CHANNELS = frozenset(("default", "beta", "stable"))
_REPOSITORY = "AgentCollab/AgentCollab-Distribution"


class ReleaseAuthorityUnavailable(ApprovalBlocked):
    """No independently authenticated Release Admin/provider is configured."""


@dataclass(frozen=True)
class GitHubRequestTemplate:
    """One immutable API request shape; response-derived values are markers."""

    method: str
    endpoint: str
    body_raw: bytes

    @property
    def body(self) -> dict:
        return json.loads(self.body_raw)


@dataclass(frozen=True)
class ChannelCASContract:
    repository: str
    branch: str
    channel: str
    pointer_path: str
    expected_ref_sha: str
    expected_channel_blob_sha: str
    intended_pointer_raw: bytes
    requests: tuple[GitHubRequestTemplate, ...]
    apply_authorized: bool = False


def _sha40(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA40.fullmatch(value) is None:
        raise ApprovalBlocked(f"{label} must be an exact lowercase Git SHA")
    return value


def _json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def plan_channel_cas_contract(*, channel: str, expected_ref_sha: str,
                              observed_ref_sha: str,
                              expected_channel_blob_sha: str,
                              observed_channel_blob_sha: str,
                              intended_pointer_raw: bytes) -> ChannelCASContract:
    """Build a single-ref Git Data API sequence after exact read-only checks.

    `expected_ref_sha` and the pointer blob SHA must come from authenticated
    GitHub reads. This pure builder cannot establish that trust; it only rejects
    stale/mismatched evidence and binds the proposed commit's parent to the
    expected ref. Placeholders are filled from preceding API responses.
    """
    if channel not in _CHANNELS:
        raise ApprovalBlocked("channel is not supported")
    expected_ref_sha = _sha40(expected_ref_sha, "expected Distribution ref SHA")
    observed_ref_sha = _sha40(observed_ref_sha, "observed Distribution ref SHA")
    expected_channel_blob_sha = _sha40(expected_channel_blob_sha, "expected channel blob SHA")
    observed_channel_blob_sha = _sha40(observed_channel_blob_sha, "observed channel blob SHA")
    if observed_ref_sha != expected_ref_sha:
        raise ApprovalBlocked("Distribution ref moved after plan")
    if observed_channel_blob_sha != expected_channel_blob_sha:
        raise ApprovalBlocked("channel pointer blob changed after plan")
    if not isinstance(intended_pointer_raw, bytes) or not intended_pointer_raw:
        raise ApprovalBlocked("intended pointer bytes are missing")
    try:
        pointer = json.loads(intended_pointer_raw)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ApprovalBlocked("intended pointer is malformed") from exc
    if (not isinstance(pointer, dict) or pointer.get("schema_version") != 2
            or pointer.get("product") != "AgentCollab" or pointer.get("channel") != channel):
        raise ApprovalBlocked("intended pointer identity does not match channel-v2")

    pointer_path = f"channels/{channel}.json"
    blob_content = base64.b64encode(intended_pointer_raw).decode("ascii")
    requests = (
        GitHubRequestTemplate(
            "POST", f"repos/{_REPOSITORY}/git/blobs",
            _json_bytes({"content": blob_content, "encoding": "base64"}),
        ),
        GitHubRequestTemplate(
            "POST", f"repos/{_REPOSITORY}/git/trees",
            _json_bytes({
                "base_tree": "<tree_sha_from_expected_ref_commit>",
                "tree": [{"path": pointer_path, "mode": "100644", "type": "blob",
                          "sha": "<blob_sha_from_create_blob>"}],
            }),
        ),
        GitHubRequestTemplate(
            "POST", f"repos/{_REPOSITORY}/git/commits",
            _json_bytes({
                "message": f"publication: update {channel} channel pointer",
                "tree": "<tree_sha_from_create_tree>",
                "parents": [expected_ref_sha],
            }),
        ),
        GitHubRequestTemplate(
            "PATCH", f"repos/{_REPOSITORY}/git/refs/heads/main",
            _json_bytes({"sha": "<commit_sha_from_create_commit>", "force": False}),
        ),
    )
    return ChannelCASContract(
        _REPOSITORY, "main", channel, pointer_path, expected_ref_sha,
        expected_channel_blob_sha, intended_pointer_raw, requests,
    )


def apply_channel_cas(_contract: ChannelCASContract) -> None:
    """Fail closed: no configured provider or live Distribution writer exists."""
    raise ReleaseAuthorityUnavailable(
        "APPLY unavailable: no authenticated designated Release Admin, independent "
        "UAT/user-approval provider, or approved Distribution writer is configured"
    )


def verify_channel_cas(*, contract: ChannelCASContract, resulting_ref_sha: str,
                       resulting_pointer_raw: bytes, resulting_blob_sha: str,
                       observed_commit_parent_sha: str) -> dict:
    """Compare post-commit identity; this cannot authenticate the observation."""
    if not isinstance(contract, ChannelCASContract):
        raise ApprovalBlocked("CAS contract identity is missing")
    resulting_ref_sha = _sha40(resulting_ref_sha, "resulting Distribution ref SHA")
    resulting_blob_sha = _sha40(resulting_blob_sha, "resulting channel blob SHA")
    observed_commit_parent_sha = _sha40(observed_commit_parent_sha, "observed commit parent SHA")
    if observed_commit_parent_sha != contract.expected_ref_sha:
        raise ApprovalBlocked("resulting commit was not based on expected Distribution ref")
    if resulting_pointer_raw != contract.intended_pointer_raw:
        raise ApprovalBlocked("post-commit channel bytes differ from intended pointer")
    actual_blob_sha = hashlib.sha1(
        b"blob " + str(len(resulting_pointer_raw)).encode("ascii") + b"\0" + resulting_pointer_raw
    ).hexdigest()
    if actual_blob_sha != resulting_blob_sha:
        raise ApprovalBlocked("post-commit channel bytes disagree with Git blob SHA")
    return {
        "status": "BYTE_IDENTITY_MATCH_ONLY",
        "repository": contract.repository,
        "branch": contract.branch,
        "channel": contract.channel,
        "ref_sha": resulting_ref_sha,
        "channel_blob_sha": resulting_blob_sha,
        "publication_verified": False,
        "apply_authorized": False,
    }
