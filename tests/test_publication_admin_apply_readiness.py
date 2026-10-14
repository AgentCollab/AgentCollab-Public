"""No-write test suite for immediate pre-APPLY identity revalidation."""
import unittest

from publication_admin_apply_readiness import validate_channel_apply_readiness
from publication_admin_plan import plan_channel_promotion
from publication_approval import ApprovalBlocked
from tests.test_publication_approval import SHA, fixture


class PublicationAdminApplyReadinessTests(unittest.TestCase):
    def inputs(self):
        record, manifest, approval, _ = fixture()
        return dict(channel="default", record_raw=record, manifest_raw=manifest,
                    approval_raw=approval, source_sha=SHA,
                    read_source_main_sha=lambda repo, ref: SHA,
                    check_external_approval=lambda **identity: True,
                    read_channel_snapshot=lambda channel: {
                        "sha": "d" * 40, "content": b"old channel"})

    def make_plan(self, args):
        return plan_channel_promotion(
            channel=args["channel"], record_raw=args["record_raw"],
            manifest_raw=args["manifest_raw"], approval_raw=args["approval_raw"],
            expected_main_sha=args["source_sha"],
            read_source_main_sha=args["read_source_main_sha"],
            check_external_approval=args["check_external_approval"],
            read_channel_snapshot=args["read_channel_snapshot"],
        )

    def test_matching_fresh_evidence_still_blocks_apply_without_trust_or_atomic_writer(self):
        args = self.inputs()
        planned = self.make_plan(args)
        result = validate_channel_apply_readiness(planned=planned, **args)
        self.assertEqual("APPLY_BLOCKED", result["status"])
        self.assertFalse(result["apply_authorized"])
        self.assertEqual("d" * 40, result["expected_blob_sha"])
        self.assertEqual(planned["proposed_pointer_raw"], result["pointer_raw"])
        self.assertTrue(any("Release Admin" in item for item in result["blockers"]))
        self.assertTrue(any("atomically leased" in item for item in result["blockers"]))

    def test_channel_changed_after_plan_blocks(self):
        args = self.inputs()
        planned = self.make_plan(args)
        args["read_channel_snapshot"] = lambda channel: {
            "sha": "e" * 40, "content": b"other channel"}
        with self.assertRaisesRegex(ApprovalBlocked, "stale"):
            validate_channel_apply_readiness(planned=planned, **args)

    def test_main_changed_or_approval_revoked_blocks(self):
        args = self.inputs()
        planned = self.make_plan(args)
        for changed in (
            {"read_source_main_sha": lambda repo, ref: "b" * 40},
            {"check_external_approval": lambda **identity: False},
        ):
            with self.subTest(changed=changed), self.assertRaises(ApprovalBlocked):
                validate_channel_apply_readiness(planned=planned, **{**args, **changed})

    def test_changed_candidate_identity_blocks(self):
        args = self.inputs()
        planned = self.make_plan(args)
        with self.assertRaises(ApprovalBlocked):
            validate_channel_apply_readiness(planned=planned, **{
                **args, "record_raw": args["record_raw"] + b" "})

    def test_same_pointer_is_idempotent(self):
        args = self.inputs()
        planned = self.make_plan(args)
        args["read_channel_snapshot"] = lambda channel: {
            "sha": "d" * 40, "content": planned["proposed_pointer_raw"]}
        result = validate_channel_apply_readiness(planned=planned, **args)
        self.assertEqual("NO_CHANGE_REQUIRED", result["status"])
        self.assertFalse(result["apply_authorized"])


if __name__ == "__main__":
    unittest.main()
