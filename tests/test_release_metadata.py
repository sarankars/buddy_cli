"""Tests for strict release tag validation."""

import unittest

from scripts.release_metadata import ReleaseTagError, parse_release_tag


class ReleaseMetadataTests(unittest.TestCase):
    def test_accepts_stable_semantic_version(self) -> None:
        metadata = parse_release_tag("v0.3.0", "0.3.0")

        self.assertEqual(metadata.version, "0.3.0")
        self.assertFalse(metadata.prerelease)

    def test_marks_prerelease_identifiers(self) -> None:
        metadata = parse_release_tag("v0.3.0-beta.1", "0.3.0")

        self.assertTrue(metadata.prerelease)

    def test_accepts_build_metadata(self) -> None:
        metadata = parse_release_tag("v12.4.0-rc.2+build.5", "12.4.0")

        self.assertTrue(metadata.prerelease)

    def test_rejects_non_semantic_tags(self) -> None:
        invalid_tags = (
            "0.3.0",
            "v0.3",
            "v01.3.0",
            "v0.3.0-01",
            "v0.3.0-beta_1",
            "v0.3.0\nprerelease=true",
        )
        for tag in invalid_tags:
            with self.subTest(tag=tag), self.assertRaises(ReleaseTagError):
                parse_release_tag(tag)

    def test_rejects_project_version_mismatch(self) -> None:
        with self.assertRaisesRegex(ReleaseTagError, "does not match"):
            parse_release_tag("v0.3.0", "0.2.1")


if __name__ == "__main__":
    unittest.main()
