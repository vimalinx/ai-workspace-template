from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVATE = ROOT / "scripts/workspace_activate.py"


class WorkspaceActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.target = self.base / "workspace"
        (self.target / ".githooks").mkdir(parents=True)
        (self.target / ".workspace/plans").mkdir(parents=True)
        (self.target / "workspace.toml").write_text("schema_version = 1\n", encoding="utf-8")
        hook = self.target / ".githooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)

        fake_bin = self.base / "bin"
        fake_bin.mkdir()
        ledger = fake_bin / "ai-ledger"
        ledger.write_text(
            "#!/usr/bin/env python3\nraise SystemExit(99)\n",
            encoding="utf-8",
        )
        ledger.chmod(0o755)
        self.env = dict(os.environ)
        self.env["PATH"] = str(fake_bin) + os.pathsep + self.env.get("PATH", "")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_activate(self, *args: object, check: bool = False) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["python3", str(ACTIVATE), *(str(arg) for arg in args)],
            capture_output=True,
            text=True,
            env=self.env,
        )
        if check and result.returncode != 0:
            self.fail(result.stdout + result.stderr)
        return result

    def review(self, plan: Path) -> Path:
        review = plan.with_suffix(plan.suffix + ".review.json")
        self.run_activate("review", plan, "--reviewer", "test-reviewer", "--output", review, check=True)
        return review

    def test_plan_apply_status_and_rollback_are_receipted(self) -> None:
        plan = self.target / ".workspace/plans/activate.json"
        self.run_activate(
            "plan",
            self.target,
            "--init-git",
            "--init-ledger",
            "--install-hook",
            "--output",
            plan,
            check=True,
        )
        self.assertEqual(0o600, plan.stat().st_mode & 0o777)
        review = self.review(plan)
        receipt_result = self.run_activate("apply", plan, "--review-receipt", review, check=True)
        receipt = Path(receipt_result.stdout.strip())
        self.assertEqual(0o600, receipt.stat().st_mode & 0o777)

        status = json.loads(self.run_activate("status", self.target, check=True).stdout)
        self.assertTrue(status["git_initialized"])
        self.assertTrue(status["hook_installed"])
        self.assertTrue(status["ai_ledger_initialized"])
        self.assertEqual("built-in", status["ai_ledger_initializer"])
        self.assertEqual("unknown", status["external_scheduler_state"])
        self.assertEqual("1.0", json.loads((self.target / ".ai/config.json").read_text())["schema_version"])
        self.assertTrue((self.target / ".ai/ledger.jsonl").is_file())
        self.assertTrue((self.target / ".ai/runs").is_dir())

        rollback = self.run_activate("rollback", receipt, check=True)
        self.assertIn("ACTROLLBACK-", rollback.stdout)
        self.assertFalse((self.target / ".git").exists())
        self.assertFalse((self.target / ".ai").exists())

    def test_activation_plan_refuses_target_drift(self) -> None:
        plan = self.target / ".workspace/plans/activate.json"
        self.run_activate("plan", self.target, "--init-git", "--output", plan, check=True)
        review = self.review(plan)
        (self.target / "after-plan.txt").write_text("drift\n", encoding="utf-8")
        result = self.run_activate("apply", plan, "--review-receipt", review)
        self.assertEqual(2, result.returncode)
        self.assertIn("target drifted", result.stderr)

    def test_parent_repository_does_not_count_as_target_git(self) -> None:
        parent = self.base / "parent"
        nested = parent / "nested"
        nested.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(parent)], check=True)
        status = json.loads(self.run_activate("status", nested, check=True).stdout)
        self.assertFalse(status["git_initialized"])

    def test_activation_apply_rejects_plan_changed_after_review(self) -> None:
        plan = self.target / ".workspace/plans/activate.json"
        self.run_activate("plan", self.target, "--init-git", "--output", plan, check=True)
        review = self.review(plan)
        payload = json.loads(plan.read_text(encoding="utf-8"))
        payload["created_at"] = "changed"
        plan.write_text(json.dumps(payload), encoding="utf-8")
        result = self.run_activate("apply", plan, "--review-receipt", review)
        self.assertEqual(2, result.returncode)
        self.assertIn("activation review does not match", result.stderr)


if __name__ == "__main__":
    unittest.main()
