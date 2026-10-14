"""Unit tests for read-only publication channel plan. No live GitHub writes."""
import json
import unittest

from publication_admin_plan import plan_channel_promotion
from publication_approval import ApprovalBlocked
from tests.test_publication_approval import SHA, fixture


class PublicationAdminPlanTests(unittest.TestCase):
    def plan(self, *, channel="default", main=SHA, approved=True,
             snapshot=None, reader=None):
        record, manifest, approval, _ = fixture()
        return plan_channel_promotion(
            channel=channel, record_raw=record, manifest_raw=manifest,
            approval_raw=approval, expected_main_sha=SHA,
            read_source_main_sha=lambda repo, ref: main,
            check_external_approval=lambda **identities: approved,
            read_channel_snapshot=reader or
            (lambda name: snapshot if snapshot is not None
             else {"sha": "d"*40, "content": b"old pointer"}),
        )

    def test_plan_produces_pinned_v2_pointer_without_writing(self):
        result = self.plan()
        self.assertEqual("d"*40, result["expected_channel_blob_sha"])
        pointer = json.loads(result["proposed_pointer_raw"])
        self.assertEqual(2, pointer["schema_version"])
        self.assertIn("approval", pointer)
        self.assertEqual("default", pointer["channel"])
        self.assertFalse(result["no_change"])

    def test_idempotent_plan_detects_exact_existing_pointer(self):
        initial = self.plan(channel="beta")
        result = self.plan(channel="beta", snapshot={
            "sha": "c"*40, "content": initial["proposed_pointer_raw"]})
        self.assertTrue(result["no_change"])
        self.assertEqual("c"*40, result["expected_channel_blob_sha"])

    def test_no_approval_or_changed_main_blocks_before_snapshot(self):
        def forbidden(_):
            self.fail("channel must not be read when approval or main fails")
        for main, approved in (("b"*40, True), (SHA, False)):
            with self.subTest(main=main, approved=approved), self.assertRaises(ApprovalBlocked):
                self.plan(main=main, approved=approved, reader=forbidden)

    def test_missing_snapshot_and_invalid_channels_block(self):
        for channel in ("", "candidate", "default/../../x"):
            with self.subTest(channel=channel), self.assertRaises(ApprovalBlocked):
                self.plan(channel=channel)
        for snapshot in ({}, {"sha": "not-sha", "content": b"x"},
                         {"sha": "a"*40, "content": "text"}):
            with self.subTest(snapshot=snapshot), self.assertRaises(ApprovalBlocked):
                self.plan(snapshot=snapshot)
        with self.assertRaisesRegex(ApprovalBlocked, "unavailable"):
            self.plan(reader=lambda _: (_ for _ in ()).throw(OSError("offline")))


if __name__ == "__main__":
    unittest.main()
