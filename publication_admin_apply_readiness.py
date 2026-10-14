"""Release-admin apply readiness: read-only fail-closed revalidation.

NO GitHub writes. The authorized release service must authenticate and bind
reader functions, human approval evidence and actual atomic writer separately.
"""
from __future__ import annotations

import hashlib
import json
import re

from publication_admin_plan import plan_channel_promotion
from publication_approval import ApprovalBlocked

_BLOB = re.compile(r"[0-9a-f]{40}\\Z")


def validate_channel_apply_readiness(*, planned: dict, channel: str,
                                     record_raw: bytes, manifest_raw: bytes,
                                     approval_raw: bytes, source_sha: str,
                                     read_source_main_sha, check_external_approval,
                                     read_channel_snapshot):
    """Recompute plan with fresh evidence; block stale base or changed bytes."""
    if not isinstance(planned, dict) or planned.get("channel") != channel:
        raise ApprovalBlocked("publication plan identity missing")
    if not isinstance(source_sha, str) or len(source_sha) != 40:
        raise ApprovalBlocked("source SHA invalid")
    current = plan_channel_promotion(
        channel=channel, record_raw=record_raw, manifest_raw=manifest_raw,
        approval_raw=approval_raw, expected_main_sha=source_sha,
        read_source_main_sha=read_source_main_sha,
        check_external_approval=check_external_approval,
        read_channel_snapshot=read_channel_snapshot,
    )
    required = ("version", "source_sha", "channel", "expected_channel_blob_sha",
                "proposed_pointer_raw", "proposed_pointer_sha256")
    if any(planned.get(field) != current[field] for field in required):
        raise ApprovalBlocked("publication plan is stale or candidate bytes changed")
    if current["no_change"]:
        return {"status": "NO_CHANGE_REQUIRED", "apply_authorized": False,
                "channel": channel, "pointer_sha256": current["proposed_pointer_sha256"],
                "blockers": current["apply_blockers"]}
    return {"status": "APPLY_BLOCKED", "apply_authorized": False,
            "channel": channel,
            "expected_blob_sha": current["expected_channel_blob_sha"],
            "pointer_raw": current["proposed_pointer_raw"],
            "pointer_sha256": current["proposed_pointer_sha256"],
            "blockers": current["apply_blockers"]}
