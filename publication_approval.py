"""Pure publication approval identity checks; no channel write or authorization.

Only a trusted Release Admin may assert that UAT/approval evidence is genuine and
GitHub main currently equals the approved candidate. This validator merely checks
that supplied immutable catalog records agree byte-for-byte by SHA-256 identity.
"""
from __future__ import annotations

import hashlib
import json
import re

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ApprovalBlocked(ValueError):
    """Catalog evidence does not match an immutable approved candidate."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_digest(value: object) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ApprovalBlocked("invalid SHA-256")


def verify_approval_identity(*, version_record_raw: bytes,
                             release_manifest_raw: bytes,
                             approval_raw: bytes, channel_pointer: dict) -> dict:
    """Validate candidate publication identity; does NOT authenticate the approver.

    All four objects must be supplied from trusted/authenticated Distribution
    catalog reads, and their immutable origin enforced separately by publisher.
    """
    try:
        version = json.loads(version_record_raw)
        release = json.loads(release_manifest_raw)
        approval = json.loads(approval_raw)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ApprovalBlocked("invalid catalog JSON") from exc
    if any(not isinstance(value, dict) for value in (version, release, approval, channel_pointer)):
        raise ApprovalBlocked("catalog objects must be dictionaries")
    if (version.get("schema_version") != 1 or version.get("kind") != "candidate"
            or version.get("product") != "AgentCollab"):
        raise ApprovalBlocked("only immutable candidate records are eligible")
    name = version.get("version")
    source = release.get("source")
    pkgs = release.get("packages")
    if (not isinstance(name, str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,63}", name)
            or not isinstance(source, dict) or not isinstance(pkgs, dict)):
        raise ApprovalBlocked("release identity missing")
    commit = source.get("commit")
    origin = release.get("service_branch")
    if (source.get("repository") != "lkhkhk/AgentCollab"
            or not isinstance(commit, str) or not _SHA40.fullmatch(commit)
            or not isinstance(origin, str) or not origin.startswith("release/")
            or ".." in origin or "@{" in origin or "//" in origin):
        raise ApprovalBlocked("source is not a valid release candidate")
    if (release.get("release_version") != name or release.get("release_tag") != name
            or version.get("release_tag") != name):
        raise ApprovalBlocked("version identity mismatch")
    manifest_ref = version.get("release_manifest")
    if not isinstance(manifest_ref, dict):
        raise ApprovalBlocked("release manifest reference missing")
    _require_digest(manifest_ref.get("sha256"))
    if manifest_ref["sha256"] != _sha256(release_manifest_raw):
        raise ApprovalBlocked("release manifest bytes changed")
    digests = {}
    for kind in ("runtime", "execution"):
        obj = pkgs.get(kind)
        if not isinstance(obj, dict):
            raise ApprovalBlocked("package identity missing")
        digest = obj.get("sha256")
        _require_digest(digest)
        digests[kind] = digest
    record_hash = _sha256(version_record_raw)
    approval_hash = _sha256(approval_raw)
    channel_record = channel_pointer.get("version_record")
    channel_approval = channel_pointer.get("approval")
    if (channel_pointer.get("schema_version") != 2
            or channel_pointer.get("product") != "AgentCollab"
            or channel_pointer.get("channel") not in ("default", "beta", "stable")
            or channel_pointer.get("version") != name
            or not isinstance(channel_record, dict)
            or channel_record != {"path": f"versions/{name}.json", "sha256": record_hash}
            or not isinstance(channel_approval, dict)
            or channel_approval != {"path": f"approvals/{name}.json", "sha256": approval_hash}):
        raise ApprovalBlocked("channel is not pinned to immutable approval/record")
    if (approval.get("schema_version") != 1 or approval.get("product") != "AgentCollab"
            or approval.get("version") != name
            or approval.get("source") != source
            or approval.get("service_branch") != origin
            or approval.get("version_record") != channel_record
            or approval.get("release_manifest") != manifest_ref
            or approval.get("packages") != {k: {"sha256": v} for k, v in digests.items()}):
        raise ApprovalBlocked("approval has mismatched immutable identity")
    uat = approval.get("uat")
    user = approval.get("approval")
    main = approval.get("main")
    if (not isinstance(uat, dict) or uat.get("status") != "PASS"
            or not isinstance(uat.get("evidence_ref"), str) or not uat["evidence_ref"]
            or not isinstance(user, dict) or user.get("decision") != "APPROVED"
            or not isinstance(user.get("evidence_ref"), str) or not user["evidence_ref"]
            or not isinstance(user.get("approver_identity"), str) or not user["approver_identity"]
            or not isinstance(main, dict) or main.get("sha") != commit):
        raise ApprovalBlocked("acceptance claims missing or mismatched")
    # Self-reported PASS/APPROVED/main must be independently proved by Release Admin.
    return {"version": name, "source_sha": commit, "version_record_sha256": record_hash,
            "approval_sha256": approval_hash, "packages": digests}
