"""Read-only publication preflight; this module never writes Distribution refs.

A privileged Release Admin must independently authenticate the requester and
human/UAT evidence. Caller-supplied catalog claims are not authorization.
"""
from __future__ import annotations
import re

from publication_approval import ApprovalBlocked, verify_approval_identity

_SHA = re.compile(r"[0-9a-f]{40}\Z")


def verify_publication_preflight(*, record_raw: bytes, manifest_raw: bytes,
                                 approval_raw: bytes, channel_pointer: dict,
                                 observed_main_sha: str, read_source_main_sha,
                                 check_external_approval):
    """Check exact source main and independently authorized approval.

    The two callbacks MUST be privileged trusted implementations. The return
    value only provides a read-only recommendation; it does not safely lock
    concurrent main/channel updates or authorize a write by itself.
    """
    details = verify_approval_identity(
        version_record_raw=record_raw,
        release_manifest_raw=manifest_raw,
        approval_raw=approval_raw,
        channel_pointer=channel_pointer,
    )
    source = details["source_sha"]
    if not isinstance(observed_main_sha, str) or _SHA.fullmatch(observed_main_sha) is None:
        raise ApprovalBlocked("expected main SHA invalid")
    if observed_main_sha != source:
        raise ApprovalBlocked("approved source does not equal expected main")
    if not callable(read_source_main_sha) or not callable(check_external_approval):
        raise ApprovalBlocked("trusted proof functions unavailable")
    try:
        actual = read_source_main_sha("lkhkhk/AgentCollab", "main")
    except Exception as exc:
        raise ApprovalBlocked("trusted main reference unavailable") from exc
    if actual != source:
        raise ApprovalBlocked("source main has changed or disagrees with approval")
    try:
        approved = check_external_approval(
            version=details["version"], source_sha=source,
            version_record_sha256=details["version_record_sha256"],
            approval_sha256=details["approval_sha256"],
            packages=details["packages"],
        )
    except Exception as exc:
        raise ApprovalBlocked("independent approval evidence failed") from exc
    if approved is not True:
        raise ApprovalBlocked("independent UAT and user approval not proven")
    return details
