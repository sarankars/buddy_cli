"""Tests for standalone build command construction."""

import unittest
from pathlib import Path

from scripts.build_standalone import build_command


class BuildStandaloneTests(unittest.TestCase):
    def test_adds_requested_codesign_identity(self) -> None:
        command = build_command(
            Path("/project"),
            "Developer ID Application: Buddy (TEAMID)",
        )

        self.assertIn("--codesign-identity", command)
        self.assertIn("Developer ID Application: Buddy (TEAMID)", command)

    def test_omits_codesign_option_by_default(self) -> None:
        command = build_command(Path("/project"))

        self.assertNotIn("--codesign-identity", command)


if __name__ == "__main__":
    unittest.main()
