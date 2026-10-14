"""Release Admin publication PLAN contract; deliberately NO APPLY.

Snapshots are inputs from trusted authenticated readers. The privileged writer
must verify these again atomically during APPLY. No callback here writes refs.
"""
from __future__ import annotations
import hashlib
import json

from publication_admin_preflight import verify_publication_preflight
from publication_approval import ApprovalBlocked


def plan_channel_promotion(*, channel: str, record_raw: bytes,
                           manifest_raw: bytes, approval_raw: bytes,
                           expected_main_sha: str, read_source_main_sha,
                           check_external_approval, read_channel_snapshot):
    """Return an exact-content intended v2 pointer and observed current pointer SHA.

    This is a PLAN only. Even matching snapshots do not grant writer credentials
    or establish a race-free channel update; APPLY must use an expected-SHA lease
    and recheck trusted approval evidence, current main, and immutable bytes.
    """
    if channel not in ("default", "beta", "stable"):
        raise ApprovalBlocked("invalid channel")
    if not callable(read_channel_snapshot):
        raise ApprovalBlocked("trusted channel reader unavailable")
    record_hash = hashlib.sha256(record_raw).hexdigest()
    approval_hash = hashlib.sha256(approval_raw).hexdigest()
    try:
        record = json.loads(record_raw)
    except (TypeError, ValueError) as exc:
        raise ApprovalBlocked("invalid version record") from exc
    if not isinstance(record, dict) or not isinstance(record.get("version"), str):
        raise ApprovalBlocked("missing exact version")
    version = record["version"]
    pointer = {
        "schema_version": 2, "product": "AgentCollab", "channel": channel,
        "version": version,
        "version_record": {"path": f"versions/{version}.json", "sha256": record_hash},
        "approval": {"path": f"approvals/{version}.json", "sha256": approval_hash},
    }
    details = verify_publication_preflight(
        record_raw=record_raw, manifest_raw=manifest_raw,
        approval_raw=approval_raw, channel_pointer=pointer,
        observed_main_sha=expected_main_sha,
        read_source_main_sha=read_source_main_sha,
        check_external_approval=check_external_approval,
    )
    try:
        current = read_channel_snapshot(channel)
    except Exception as exc:
        raise ApprovalBlocked("current channel snapshot unavailable") from exc
    if (not isinstance(current, dict) or not isinstance(current.get("sha"), str)
            or len(current["sha"]) != 40
            or any(c not in "0123456789abcdef" for c in current["sha"])
            or not isinstance(current.get("content"), bytes)):
        raise ApprovalBlocked("channel snapshot identity missing")
    # No action if exact pointer bytes already match; otherwise writer must
    # atomically compare current blob SHA, not just content or Git tree age.
    intended = (json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return {
        "version": version,
        "source_sha": details["source_sha"],
        "channel": channel,
        "expected_channel_blob_sha": current["sha"],
        "proposed_pointer_raw": intended,
        "proposed_pointer_sha256": hashlib.sha256(intended).hexdigest(),
        "no_change": current["content"] == intended,
    }
