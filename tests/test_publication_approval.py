"""Pure checks of immutable candidate publication identity; no GitHub writes."""
import copy
import hashlib
import json
import unittest

from publication_approval import ApprovalBlocked, verify_approval_identity

SHA = "a" * 40
def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

def digest(value):
    return hashlib.sha256(value).hexdigest()

def fixture():
    version = "v0.3.0-rc.1"
    release = {"source": {"repository": "lkhkhk/AgentCollab", "commit": SHA},
               "service_branch": "release/v0.3.0-rc.1",
               "release_version": version, "release_tag": version,
               "packages": {"runtime": {"sha256": "b"*64},
                            "execution": {"sha256": "c"*64}}}
    release_raw = raw(release)
    record = {"schema_version": 1, "product": "AgentCollab", "version": version,
              "kind": "candidate", "release_tag": version,
              "release_manifest": {"name": "agentcollab-release-manifest.json",
                                   "sha256": digest(release_raw)}}
    record_raw = raw(record)
    record_ref = {"path": f"versions/{version}.json", "sha256": digest(record_raw)}
    approval = {"schema_version": 1, "product": "AgentCollab", "version": version,
                "source": release["source"], "service_branch": release["service_branch"],
                "version_record": record_ref, "release_manifest": record["release_manifest"],
                "packages": {"runtime": {"sha256": "b"*64},
                             "execution": {"sha256": "c"*64}},
                "uat": {"status": "PASS", "evidence_ref": "run/42"},
                "approval": {"decision": "APPROVED", "approver_identity": "user",
                             "evidence_ref": "approval/42"},
                "main": {"sha": SHA}}
    approval_raw = raw(approval)
    pointer = {"schema_version": 2, "product": "AgentCollab", "channel": "default",
               "version": version, "version_record": record_ref,
               "approval": {"path": f"approvals/{version}.json",
                            "sha256": digest(approval_raw)}}
    return record_raw, release_raw, approval_raw, pointer


class PublicationApprovalContractTests(unittest.TestCase):
    def check(self, data):
        record, release, approval, pointer = data
        return verify_approval_identity(version_record_raw=record,
                                        release_manifest_raw=release,
                                        approval_raw=approval,
                                        channel_pointer=pointer)

    def test_exact_digest_pair_and_candidate_identity_pass(self):
        value = self.check(fixture())
        self.assertEqual(SHA, value["source_sha"])
        self.assertEqual("b"*64, value["packages"]["runtime"])

    def test_modified_version_record_and_approval_bytes_block(self):
        for index in (0, 2):
            data = list(fixture())
            obj = json.loads(data[index])
            obj["extra"] = "mutation"
            data[index] = raw(obj)
            with self.subTest(index=index), self.assertRaises(ApprovalBlocked):
                self.check(data)

    def test_mismatched_package_origin_or_main_blocks(self):
        for key, invalid in (("main", {"sha": "d"*40}),
                             ("source", {"repository": "other/repo", "commit": SHA}),
                             ("packages", {"runtime": {"sha256": "d"*64},
                                           "execution": {"sha256": "c"*64}}),
                             ("uat", {"status": "FAIL", "evidence_ref": "run/42"}),
                             ("approval", {"decision": "REJECTED",
                                           "approver_identity": "user",
                                           "evidence_ref": "approval/42"})):
            data = list(fixture())
            obj = json.loads(data[2])
            obj[key] = invalid
            data[2] = raw(obj)
            data[3]["approval"]["sha256"] = digest(data[2])
            with self.subTest(key=key), self.assertRaises(ApprovalBlocked):
                self.check(data)

    def test_candidate_channel_v1_or_missing_attestation_blocks(self):
        for action in ("v1", "remove", "wrong_hash"):
            data = list(fixture())
            if action == "v1":
                data[3]["schema_version"] = 1
            if action == "remove":
                del data[3]["approval"]
            if action == "wrong_hash":
                data[3]["approval"]["sha256"] = "d"*64
            with self.subTest(action=action), self.assertRaises(ApprovalBlocked):
                self.check(data)

    def test_legacy_release_record_cannot_enter_candidate_v2_path(self):
        data = list(fixture())
        obj = json.loads(data[0])
        obj["kind"] = "release"
        data[0] = raw(obj)
        with self.assertRaises(ApprovalBlocked):
            self.check(data)


if __name__ == "__main__":
    unittest.main()
