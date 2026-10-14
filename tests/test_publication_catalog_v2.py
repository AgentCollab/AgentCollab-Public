"""Read-only channel-v2 catalog verification; never touches live Distribution."""
import unittest

from publication_catalog_v2 import validate_v2_channel_catalog
from publication_approval import ApprovalBlocked
from tests.test_publication_approval import fixture


class PublicationCatalogV2Tests(unittest.TestCase):
    def verify(self, *, mutate=None, fail=None):
        record, manifest, approval, pointer = fixture()
        files = {pointer["version_record"]["path"]: record,
                 pointer["approval"]["path"]: approval}
        if mutate:
            mutate(pointer, files)
        def catalog(path):
            if fail == "catalog":
                raise OSError("offline")
            return files[path]
        def release(version, record_raw):
            if fail == "manifest":
                raise OSError("manifest offline")
            return manifest
        return validate_v2_channel_catalog(
            channel="default", pointer=pointer, read_catalog=catalog,
            read_manifest=release,
        )

    def test_pinned_candidate_catalog_can_be_verified_offline(self):
        result = self.verify()
        self.assertEqual("v0.3.0-rc.1", result["version"])

    def test_untrusted_channel_or_changed_catalog_bytes_block(self):
        def change_channel(pointer, files):
            pointer["channel"] = "beta"
        def change_version(pointer, files):
            path = pointer["version_record"]["path"]
            files[path] = files[path] + b" "
        def change_approval(pointer, files):
            path = pointer["approval"]["path"]
            files[path] = files[path] + b" "
        for mutation in (change_channel, change_version, change_approval):
            with self.subTest(mutation=mutation.__name__), self.assertRaises(ApprovalBlocked):
                self.verify(mutate=mutation)

    def test_missing_catalog_or_manifest_blocks_without_fallback(self):
        for step in ("catalog", "manifest"):
            with self.subTest(step=step), self.assertRaises(ApprovalBlocked):
                self.verify(fail=step)

    def test_malformed_v2_pointer_blocks(self):
        for mutation in (
            lambda pointer, files: pointer.update(schema_version=1),
            lambda pointer, files: pointer.pop("approval"),
            lambda pointer, files: pointer["version_record"].update(path="versions/other.json"),
        ):
            with self.subTest(mutation=mutation), self.assertRaises(ApprovalBlocked):
                self.verify(mutate=mutation)


if __name__ == "__main__":
    unittest.main()
