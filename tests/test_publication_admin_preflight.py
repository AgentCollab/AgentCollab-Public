"""Publication preflight negative cases. No real GitHub/API credentials."""
import unittest

from publication_admin_preflight import verify_publication_preflight
from publication_approval import ApprovalBlocked
from tests.test_publication_approval import SHA, fixture


class PublicationAdminPreflightTests(unittest.TestCase):
    def run_gate(self, *, main=SHA, expected=SHA, permitted=True, reader=None, verifier=None):
        record, release, approval, pointer = fixture()
        return verify_publication_preflight(
            record_raw=record, manifest_raw=release,
            approval_raw=approval, channel_pointer=pointer,
            observed_main_sha=expected,
            read_source_main_sha=reader or (lambda repository, ref: main),
            check_external_approval=verifier or (lambda **kw: permitted),
        )

    def test_independent_main_and_approval_proofs_pass(self):
        seen = []
        def read(repo, ref):
            seen.append(("main", repo, ref))
            return SHA
        def approve(**kw):
            seen.append(("approval", kw["version"], kw["source_sha"]))
            return True
        result = self.run_gate(reader=read, verifier=approve)
        self.assertEqual(SHA, result["source_sha"])
        self.assertEqual(["main", "approval"], [item[0] for item in seen])

    def test_mismatched_expected_or_live_main_blocks(self):
        for args in ({"expected": "b"*40}, {"main": "c"*40}, {"expected": "bad"}):
            with self.subTest(args=args), self.assertRaises(ApprovalBlocked):
                self.run_gate(**args)

    def test_unapproved_or_exception_blocks(self):
        with self.assertRaisesRegex(ApprovalBlocked, "not proven"):
            self.run_gate(permitted=False)
        with self.assertRaisesRegex(ApprovalBlocked, "unavailable"):
            self.run_gate(reader=lambda *_: (_ for _ in ()).throw(RuntimeError("network")))
        with self.assertRaisesRegex(ApprovalBlocked, "evidence failed"):
            self.run_gate(verifier=lambda **_: (_ for _ in ()).throw(RuntimeError("invalid")))

    def test_missing_trusted_callbacks_block(self):
        record, release, approval, pointer = fixture()
        with self.assertRaises(ApprovalBlocked):
            verify_publication_preflight(
                record_raw=record, manifest_raw=release,
                approval_raw=approval, channel_pointer=pointer,
                observed_main_sha=SHA,
                read_source_main_sha=None, check_external_approval=None,
            )


if __name__ == "__main__":
    unittest.main()
