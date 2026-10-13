"""Read-only authenticated channel-v2 catalog rehearsal.

This is deliberately NOT invoked by the live installer. Catalog hash checks
cannot prove a human approved the release or that the publisher is authorized.
"""
from __future__ import annotations
import hashlib

from publication_approval import ApprovalBlocked, verify_approval_identity


def validate_v2_channel_catalog(*, channel: str, pointer: object, read_catalog,
                                read_manifest):
    """Verify pinned candidate bytes from authenticated catalog and manifest readers.

    Both readers are provided by a caller that authenticates and fixes the
    Distribution repo and exact asset tag; never treat supplied callbacks as
    a trusted production implementation without reviewing that binding.
    """
    if channel not in ("default", "beta", "stable"):
        raise ApprovalBlocked("channel is not supported")
    if not isinstance(pointer, dict) or pointer.get("schema_version") != 2:
        raise ApprovalBlocked("v2 channel pointer required")
    if pointer.get("channel") != channel:
        raise ApprovalBlocked("channel pointer selector mismatch")
    version = pointer.get("version")
    record_ref, approval_ref = pointer.get("version_record"), pointer.get("approval")
    if not isinstance(version, str) or not 1 <= len(version) <= 64:
        raise ApprovalBlocked("version missing")
    if not isinstance(record_ref, dict) or not isinstance(approval_ref, dict):
        raise ApprovalBlocked("missing pinned catalog refs")
    if (record_ref.get("path") != f"versions/{version}.json"
            or approval_ref.get("path") != f"approvals/{version}.json"):
        raise ApprovalBlocked("catalog path differs from channel selector")
    try:
        record_raw = read_catalog(record_ref["path"])
        approval_raw = read_catalog(approval_ref["path"])
        if not isinstance(record_raw, bytes) or not isinstance(approval_raw, bytes):
            raise ApprovalBlocked("catalog reader did not return raw bytes")
        if (hashlib.sha256(record_raw).hexdigest() != record_ref.get("sha256")
                or hashlib.sha256(approval_raw).hexdigest() != approval_ref.get("sha256")):
            raise ApprovalBlocked("catalog record bytes mismatch")
        release_raw = read_manifest(version, record_raw)
        if not isinstance(release_raw, bytes):
            raise ApprovalBlocked("release manifest must be exact raw bytes")
    except ApprovalBlocked:
        raise
    except Exception as exc:
        raise ApprovalBlocked("authenticated catalog or manifest unavailable") from exc
    return verify_approval_identity(
        version_record_raw=record_raw,
        release_manifest_raw=release_raw,
        approval_raw=approval_raw, channel_pointer=pointer,
    )
