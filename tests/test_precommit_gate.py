from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1]


class PrecommitGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.root = base / "workspace"
        tool = SOURCE / ".agents/skills/bootstrap-ai-workspace/scripts/workspace_tool.py"
        plan = base / "plan.json"
        subprocess.run(
            [
                "python3",
                str(tool),
                "plan",
                str(self.root),
                "--mode",
                "new",
                "--template-root",
                str(SOURCE),
                "--output",
                str(plan),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "python3",
                str(tool),
                "review",
                str(plan),
                "--reviewer",
                "test-reviewer",
                "--output",
                str(base / "plan.review.json"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "python3",
                str(tool),
                "apply",
                str(plan),
                "--review-receipt",
                str(base / "plan.review.json"),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "core.hooksPath", ".githooks"], check=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_gate(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", "scripts/precommit_gate.py"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def test_safe_staged_file_passes(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "add", "README.md"], check=True)
        result = self.run_gate()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("scope:", result.stdout)

    def test_runtime_gitkeep_is_allowed(self) -> None:
        subprocess.run(
            ["git", "-C", str(self.root), "add", "-f", ".workspace/runtime/.gitkeep"],
            check=True,
        )
        result = self.run_gate()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_force_added_runtime_file_is_rejected(self) -> None:
        runtime = self.root / "debug.log"
        runtime.write_text("runtime output\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "-f", "debug.log"], check=True)
        result = self.run_gate()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("runtime log", result.stdout)

    def test_force_added_maintenance_report_is_rejected(self) -> None:
        report = self.root / ".workspace/runtime/audit-latest.json"
        report.write_text("{}\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "-f", ".workspace/runtime/audit-latest.json"],
            check=True,
        )
        result = self.run_gate()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("derived maintenance report", result.stdout)


if __name__ == "__main__":
    unittest.main()
