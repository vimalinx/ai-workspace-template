from __future__ import annotations

import sys
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from release_check import REQUIRED_FILES, check_release  # noqa: E402


class ReleaseCheckTests(unittest.TestCase):
    def test_repository_release_surface_passes(self) -> None:
        self.assertEqual([], check_release(ROOT))

    def test_missing_license_private_reference_and_ledger_boundary_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8")
            (root / "LICENSE").unlink()
            (root / "VERSION").write_text("0.1.0-alpha.1\n", encoding="utf-8")
            (root / "CHANGELOG.md").write_text("## [0.1.0-alpha.1]\n", encoding="utf-8")
            (root / "README.md").write_text("private /home/example/project\n", encoding="utf-8")
            (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
            codes = {finding.code for finding in check_release(root)}
            self.assertIn("RELEASE_FILE_MISSING", codes)
            self.assertIn("PRIVATE_LEDGER_NOT_IGNORED", codes)
            self.assertIn("ABSOLUTE_HOME_PATH", codes)

    def test_strict_git_requires_publication_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in REQUIRED_FILES:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("placeholder\n", encoding="utf-8")
            (root / "LICENSE").write_text(
                "Apache License\nVersion 2.0, January 2004\nEND OF TERMS AND CONDITIONS\n",
                encoding="utf-8",
            )
            (root / "VERSION").write_text("0.1.0-alpha.1\n", encoding="utf-8")
            (root / "CHANGELOG.md").write_text("## [0.1.0-alpha.1]\n", encoding="utf-8")
            (root / ".gitignore").write_text(".ai/\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            codes = {finding.code for finding in check_release(root, strict_git=True)}
            self.assertIn("GIT_HISTORY_MISSING", codes)
            self.assertIn("GIT_REMOTE_MISSING", codes)
            self.assertIn("GIT_WORKTREE_DIRTY", codes)


if __name__ == "__main__":
    unittest.main()
