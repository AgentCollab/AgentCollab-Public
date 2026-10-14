from __future__ import annotations

import base64
import hashlib
import json
import unittest

from publication_admin_cas_contract import (
    ChannelCASContract,
    ReleaseAuthorityUnavailable,
    apply_channel_cas,
    plan_channel_cas_contract,
    verify_channel_cas,
)
from publication_approval import ApprovalBlocked


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


class PublicationAdminCASContractTests(unittest.TestCase):
    def setUp(self):
        self.ref_sha = "a" * 40
        self.channel_sha = "b" * 40
        self.pointer = json.dumps({
            "schema_version": 2,
            "product": "AgentCollab",
            "channel": "beta",
            "version": "0.3.0-candidate.1",
            "version_record": {"path": "versions/0.3.0-candidate.1.json", "sha256": "c" * 64},
            "approval": {"path": "approvals/0.3.0-candidate.1.json", "sha256": "d" * 64},
        }, sort_keys=True, separators=(",", ":")).encode() + b"\n"

    def make_contract(self):
        return plan_channel_cas_contract(
            channel="beta",
            expected_ref_sha=self.ref_sha,
            observed_ref_sha=self.ref_sha,
            expected_channel_blob_sha=self.channel_sha,
            observed_channel_blob_sha=self.channel_sha,
            intended_pointer_raw=self.pointer,
        )

    def test_request_templates_match_github_git_data_api_and_bind_expected_parent(self):
        contract = self.make_contract()
        self.assertIsInstance(contract, ChannelCASContract)
        self.assertFalse(contract.apply_authorized)
        self.assertEqual(
            ["POST", "POST", "POST", "PATCH"],
            [request.method for request in contract.requests],
        )
        self.assertEqual(
            [
                "repos/AgentCollab/AgentCollab-Distribution/git/blobs",
                "repos/AgentCollab/AgentCollab-Distribution/git/trees",
                "repos/AgentCollab/AgentCollab-Distribution/git/commits",
                "repos/AgentCollab/AgentCollab-Distribution/git/refs/heads/main",
            ],
            [request.endpoint for request in contract.requests],
        )
        blob, tree, commit, update_ref = [request.body for request in contract.requests]
        self.assertEqual(base64.b64encode(self.pointer).decode(), blob["content"])
        self.assertEqual("base64", blob["encoding"])
        self.assertEqual("channels/beta.json", tree["tree"][0]["path"])
        self.assertEqual("100644", tree["tree"][0]["mode"])
        self.assertEqual([self.ref_sha], commit["parents"])
        self.assertEqual({"sha": "<commit_sha_from_create_commit>", "force": False}, update_ref)

    def test_moved_ref_stale_pointer_or_swapped_sha_fails_before_any_request(self):
        variants = (
            {"observed_ref_sha": "e" * 40},
            {"observed_channel_blob_sha": "f" * 40},
            {"expected_channel_blob_sha": "0" * 40},
        )
        for changes in variants:
            kwargs = {
                "channel": "beta",
                "expected_ref_sha": self.ref_sha,
                "observed_ref_sha": self.ref_sha,
                "expected_channel_blob_sha": self.channel_sha,
                "observed_channel_blob_sha": self.channel_sha,
                "intended_pointer_raw": self.pointer,
            }
            kwargs.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ApprovalBlocked):
                plan_channel_cas_contract(**kwargs)

    def test_unsafe_or_malformed_v2_pointer_is_rejected(self):
        for channel, raw in (("work", self.pointer), ("beta", b"{"),
                             ("beta", self.pointer.replace(b'"beta"', b'"stable"'))):
            with self.subTest(channel=channel), self.assertRaises(ApprovalBlocked):
                plan_channel_cas_contract(
                    channel=channel,
                    expected_ref_sha=self.ref_sha,
                    observed_ref_sha=self.ref_sha,
                    expected_channel_blob_sha=self.channel_sha,
                    observed_channel_blob_sha=self.channel_sha,
                    intended_pointer_raw=raw,
                )

    def test_apply_is_unconditionally_blocked_without_provider_and_transport(self):
        contract = self.make_contract()
        for _ in range(2):
            with self.subTest(replay_attempt=_), self.assertRaisesRegex(
                    ReleaseAuthorityUnavailable, "no authenticated designated"):
                apply_channel_cas(contract)

    def test_verify_reports_only_byte_identity_and_never_publication_pass(self):
        contract = self.make_contract()
        result = verify_channel_cas(
            contract=contract,
            resulting_ref_sha="1" * 40,
            resulting_pointer_raw=self.pointer,
            resulting_blob_sha=git_blob_sha(self.pointer),
            observed_commit_parent_sha=self.ref_sha,
        )
        self.assertEqual("BYTE_IDENTITY_MATCH_ONLY", result["status"])
        self.assertFalse(result["publication_verified"])
        self.assertFalse(result["apply_authorized"])

    def test_verify_rejects_partial_commit_wrong_parent_and_changed_pointer(self):
        contract = self.make_contract()
        cases = (
            {"observed_commit_parent_sha": "2" * 40},
            {"resulting_pointer_raw": self.pointer + b"tampered"},
            {"resulting_blob_sha": "3" * 40},
        )
        for changes in cases:
            kwargs = {
                "contract": contract,
                "resulting_ref_sha": "1" * 40,
                "resulting_pointer_raw": self.pointer,
                "resulting_blob_sha": git_blob_sha(self.pointer),
                "observed_commit_parent_sha": self.ref_sha,
            }
            kwargs.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ApprovalBlocked):
                verify_channel_cas(**kwargs)


if __name__ == "__main__":
    unittest.main()
