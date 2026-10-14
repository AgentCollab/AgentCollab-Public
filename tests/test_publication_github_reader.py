from __future__ import annotations

import base64
import hashlib
import json
import unittest
from types import SimpleNamespace

from publication_github_reader import (
    DISTRIBUTION_REPOSITORY,
    PUBLIC_REPOSITORY,
    SOURCE_REPOSITORY,
    GitHubReadBlocked,
    ReadOnlyGitHubReader,
)


def git_blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


class FakeGitHub:
    def __init__(self):
        self.calls = []
        self.fail_endpoints = set()
        self.source_sha = "a" * 40
        self.pages = {
            PUBLIC_REPOSITORY: [[
                {"login": "lkhkhk", "permissions": {"admin": True}},
                {"login": "agentcollab-admin", "permissions": {"admin": True}},
            ]],
            DISTRIBUTION_REPOSITORY: [[
                {"login": "lkhkhk", "permissions": {"admin": True}},
                {"login": "agentcollab-admin", "permissions": {"admin": True}},
                {"login": "dev01acservice", "permissions": {"pull": True}},
            ]],
        }
        self.raw = b'{"schema_version":1,"kind":"release"}\n'

    def __call__(self, argv):
        self.calls.append(list(argv))
        endpoint = argv[2] if len(argv) > 2 else ""
        if endpoint in self.fail_endpoints:
            return SimpleNamespace(returncode=1, stdout="", stderr="forbidden")
        if endpoint == "user":
            value = {"login": "lkhkhk", "id": 12345}
        elif endpoint.startswith("repos/") and "/collaborators?" in endpoint:
            repo = endpoint.split("/collaborators?", 1)[0].removeprefix("repos/")
            return SimpleNamespace(returncode=0,
                                   stdout="\n".join(json.dumps(person) for page in self.pages[repo] for person in page),
                                   stderr="")
        elif endpoint == f"repos/{SOURCE_REPOSITORY}/git/ref/heads/main":
            value = {"object": {"type": "commit", "sha": self.source_sha}}
        elif endpoint.startswith(f"repos/{DISTRIBUTION_REPOSITORY}/contents/"):
            value = {"encoding": "base64", "content": base64.b64encode(self.raw).decode(),
                     "sha": git_blob_sha(self.raw)}
        else:
            return SimpleNamespace(returncode=1, stdout="", stderr="unexpected endpoint")
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr="")


class GitHubReaderTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGitHub()
        self.reader = ReadOnlyGitHubReader(self.fake)

    def test_observed_admin_permissions_do_not_authorize_release_apply(self):
        report = self.reader.inspect_authority()
        self.assertEqual({"login": "lkhkhk", "id": 12345}, report["authenticated_actor"])
        self.assertEqual(self.fake.source_sha, report["source_main_sha"])
        self.assertEqual(("agentcollab-admin", "lkhkhk"), report["distribution_write_capable_accounts"])
        self.assertTrue(report["actor_can_write_distribution"])
        self.assertFalse(report["release_admin_designated"])
        self.assertFalse(report["independent_approval_provider_configured"])
        self.assertFalse(report["apply_permitted"])
        self.assertTrue(any("exactly one" in item for item in report["blockers"]))
        self.assertTrue(any("approval evidence provider" in item for item in report["blockers"]))
        self.assertTrue(all("token" not in str(item).lower() for item in report.values()))

    def test_reads_distribution_bytes_and_checks_github_blob_identity(self):
        result = self.reader.read_distribution_file("channels/beta.json")
        self.assertEqual(DISTRIBUTION_REPOSITORY, result.repository)
        self.assertEqual("channels/beta.json", result.path)
        self.assertEqual("main", result.ref)
        self.assertEqual(self.fake.raw, result.raw)
        self.assertEqual(git_blob_sha(self.fake.raw), result.git_blob_sha)
        self.assertIn(["gh", "api", f"repos/{DISTRIBUTION_REPOSITORY}/contents/channels/beta.json?ref=main"],
                      self.fake.calls)

    def test_channel_snapshot_exposes_expected_git_blob_sha_without_write_api(self):
        value = self.reader.read_channel_snapshot("default")
        self.assertEqual(git_blob_sha(self.fake.raw), value["sha"])
        self.assertEqual(self.fake.raw, value["content"])
        self.assertTrue(all(call[:2] == ["gh", "api"] for call in self.fake.calls))
        self.assertFalse(any("PUT" in call or "PATCH" in call or "DELETE" in call
                             for call in self.fake.calls))

    def test_unapproved_repository_path_or_ref_fails_before_api(self):
        for path, ref in (("../channels/beta.json", "main"), ("channels/other.json", "main"),
                          ("channels/beta.json", "work/branch")):
            with self.subTest(path=path, ref=ref), self.assertRaises(GitHubReadBlocked):
                self.reader.read_distribution_file(path, ref=ref)
        self.assertEqual([], self.fake.calls)

    def test_invalid_blob_hash_and_unavailable_api_fail_closed(self):
        self.fake.raw = b"payload"
        original = self.fake.__call__

        def bad_sha(argv):
            result = original(argv)
            if "/contents/" in (argv[2] if len(argv) > 2 else "") and result.returncode == 0:
                value = json.loads(result.stdout)
                value["sha"] = "0" * 40
                result.stdout = json.dumps(value)
            return result

        reader = ReadOnlyGitHubReader(bad_sha)
        with self.assertRaisesRegex(GitHubReadBlocked, "Git blob SHA"):
            reader.read_distribution_file("channels/default.json")

        self.fake.fail_endpoints.add("user")
        with self.assertRaisesRegex(GitHubReadBlocked, "API read failed"):
            self.reader.identity()

    def test_source_ref_must_resolve_to_a_commit(self):
        original = self.fake.__call__

        def annotated_tag(argv):
            result = original(argv)
            if argv[2] == f"repos/{SOURCE_REPOSITORY}/git/ref/heads/main":
                result.stdout = json.dumps({"object": {"type": "tag", "sha": self.fake.source_sha}})
            return result

        with self.assertRaisesRegex(GitHubReadBlocked, "exact commit"):
            ReadOnlyGitHubReader(annotated_tag).source_main_sha()


if __name__ == "__main__":
    unittest.main()
