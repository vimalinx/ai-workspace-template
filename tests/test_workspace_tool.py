from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1]
TOOL = TEMPLATE / ".agents/skills/bootstrap-ai-workspace/scripts/workspace_tool.py"


class WorkspaceToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_tool(self, *args: object, check: bool = False) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["python3", str(TOOL), *(str(arg) for arg in args)],
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            self.fail(result.stdout + result.stderr)
        return result

    def plan(self, target: Path, *extra: object) -> Path:
        output = self.base / f"{target.name}-plan.json"
        self.run_tool(
            "plan",
            target,
            "--template-root",
            TEMPLATE,
            "--output",
            output,
            *extra,
            check=True,
        )
        return output

    def apply(self, plan: Path, *extra: object) -> Path:
        review = plan.with_suffix(plan.suffix + ".review.json")
        self.run_tool("review", plan, "--reviewer", "test-reviewer", "--output", review, check=True)
        result = self.run_tool("apply", plan, "--review-receipt", review, *extra, check=True)
        return Path(result.stdout.strip())

    def sealed_apply_result(self, plan: Path, *extra: object) -> subprocess.CompletedProcess[str]:
        review = plan.with_suffix(plan.suffix + ".review.json")
        self.run_tool("review", plan, "--reviewer", "test-reviewer", "--output", review, check=True)
        return self.run_tool("apply", plan, "--review-receipt", review, *extra)

    def test_new_workspace_plan_apply_verify_and_rollback(self) -> None:
        target = self.base / "new-workspace"
        plan = self.plan(target, "--mode", "new", "--name", "New Workspace")
        receipt = self.apply(plan)

        self.assertTrue((target / "workspace.toml").is_file())
        self.assertTrue((target / ".agents/skills/bootstrap-ai-workspace/SKILL.md").is_file())
        self.assertTrue((target / "scripts/workspace_activate.py").is_file())
        self.assertTrue((target / "scripts/workspace_protocol.py").is_file())
        self.assertTrue((target / "governance/protocol.toml").is_file())
        self.assertTrue((target / "docs/INDEX.md").is_file())
        self.assertTrue((target / ".agents/skills/delegate-subagents/SKILL.md").is_file())
        self.assertFalse((target / "docs/LIVE-ADOPTION-CASE.md").exists())
        self.assertFalse((target / "docs/MATURITY-EXTRACTION.md").exists())
        generated_readme = (target / "README.md").read_text(encoding="utf-8")
        self.assertIn(".agents/skills/bootstrap-ai-workspace/SKILL.md", generated_readme)
        self.assertIn("不要重复接管", generated_readme)
        self.assertEqual(0o600, receipt.stat().st_mode & 0o777)
        self.assertEqual(0, self.run_tool("verify", target, "--skip-git-hook").returncode)

        inspection = json.loads(self.run_tool("inspect", target, "--json", check=True).stdout)
        self.assertEqual("governed", inspection["entry_state"])
        self.assertEqual("configure-and-activate", inspection["recommended_action"])
        duplicate = self.run_tool("plan", target, "--template-root", TEMPLATE)
        self.assertEqual(2, duplicate.returncode)
        self.assertIn("do not re-adopt", duplicate.stderr)

        rollback = self.run_tool("rollback", receipt, check=True)
        self.assertIn("ROLLBACK-", rollback.stdout)
        self.assertFalse((target / "workspace.toml").exists())

    def test_new_plan_may_live_inside_target_private_directory(self) -> None:
        target = self.base / "inside-plan"
        output = target / ".workspace/plans/adopt.json"
        self.run_tool(
            "plan",
            target,
            "--mode",
            "new",
            "--template-root",
            TEMPLATE,
            "--output",
            output,
            check=True,
        )
        self.apply(output)
        self.assertTrue((target / "README.md").is_file())

    def test_adopt_preserves_existing_content_and_updates_owned_block_once(self) -> None:
        target = self.base / "existing"
        target.mkdir()
        original_agents = "# Domain rules\n\nNever touch production.\n"
        original_readme = "# Existing workspace\n\nBusiness context.\n"
        original_ignore = "local-only\n"
        (target / "AGENTS.md").write_text(original_agents, encoding="utf-8")
        (target / "README.md").write_text(original_readme, encoding="utf-8")
        (target / ".gitignore").write_text(original_ignore, encoding="utf-8")
        (target / "domain.txt").write_text("keep me\n", encoding="utf-8")

        first_plan = self.plan(target, "--mode", "adopt", "--protect", "local-only")
        self.apply(first_plan)
        self.assertTrue((target / "AGENTS.md").read_text().startswith(original_agents))
        adopted_readme = (target / "README.md").read_text()
        self.assertTrue(adopted_readme.startswith(original_readme))
        self.assertIn(".agents/skills/bootstrap-ai-workspace/SKILL.md", adopted_readme)
        self.assertIn("不要重复接管", adopted_readme)
        self.assertTrue((target / ".gitignore").read_text().startswith(original_ignore))
        self.assertEqual("keep me\n", (target / "domain.txt").read_text())
        self.assertEqual(0o700, (target / ".workspace/backups").stat().st_mode & 0o777)

        second_plan = self.plan(target, "--mode", "adopt", "--protect", "local-only")
        self.apply(second_plan)
        self.assertEqual(1, (target / "AGENTS.md").read_text().count("<!-- AI-WORKSPACE:BEGIN -->"))
        self.assertEqual(1, (target / "README.md").read_text().count("<!-- AI-WORKSPACE:BEGIN -->"))
        self.assertEqual(1, (target / ".gitignore").read_text().count("# AI-WORKSPACE:BEGIN"))

    def test_adopt_without_agents_creates_valid_normative_header(self) -> None:
        target = self.base / "existing-without-agents"
        target.mkdir()
        (target / "README.md").write_text("# Existing workspace\n\nKeep this content.\n", encoding="utf-8")
        (target / "business.txt").write_text("preserve me\n", encoding="utf-8")

        plan = self.plan(target, "--mode", "adopt", "--name", "Existing Workspace")
        self.apply(plan)

        agents = (target / "AGENTS.md").read_text(encoding="utf-8")
        first_nonempty = next(line for line in agents.splitlines() if line.strip())
        self.assertTrue(first_nonempty.startswith("# "))
        self.assertIn("<!-- AI-WORKSPACE:BEGIN -->", agents)
        self.assertEqual("preserve me\n", (target / "business.txt").read_text(encoding="utf-8"))
        self.assertEqual(0, self.run_tool("verify", target, "--skip-git-hook").returncode)

    def test_inspect_reports_dirty_repository_without_mutating_it(self) -> None:
        target = self.base / "dirty"
        target.mkdir()
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        (target / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        before = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if ".git" not in path.parts)
        result = self.run_tool("inspect", target, "--json", check=True)
        after = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if ".git" not in path.parts)
        report = json.loads(result.stdout)
        self.assertTrue(report["git"]["dirty"])
        self.assertIn("DIRTY_WORKTREE", {item["code"] for item in report["warnings"]})
        self.assertEqual(before, after)

    def test_inspect_reports_sensitive_directories(self) -> None:
        target = self.base / "sensitive-directory"
        (target / ".secrets").mkdir(parents=True)
        (target / ".secrets/token.txt").write_text("placeholder\n", encoding="utf-8")
        result = self.run_tool("inspect", target, "--json", check=True)
        report = json.loads(result.stdout)
        sensitive = {item["path"]: item for item in report["sensitive_files"]}
        self.assertEqual("directory", sensitive[".secrets"]["kind"])

    def test_scan_skip_does_not_add_gitignore_rule(self) -> None:
        target = self.base / "scan-skip"
        target.mkdir()
        (target / ".gitignore").write_text("existing\n", encoding="utf-8")
        (target / "mirror").mkdir()
        plan = self.plan(target, "--mode", "adopt", "--scan-skip", "mirror")
        self.apply(plan)
        self.assertIn('"mirror"', (target / "workspace.toml").read_text())
        self.assertNotIn("mirror/", (target / ".gitignore").read_text())

    def test_adopted_catalog_keeps_unknown_facts_and_debts_have_review_dates(self) -> None:
        target = self.base / "uncertain-facts"
        (target / "bounties/example").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        plan = self.plan(target, "--mode", "adopt", "--catalog-layer", "bounties")
        self.apply(plan)
        catalog = (target / "governance/catalog.toml").read_text(encoding="utf-8")
        debts = (target / "governance/debts.toml").read_text(encoding="utf-8")
        self.assertIn('kind = "bounty"', catalog)
        self.assertIn('status = "unknown"', catalog)
        self.assertIn('owner = "unassigned"', catalog)
        self.assertEqual(debts.count("[[debts]]"), debts.count("due = "))

    def test_apply_refuses_target_drift(self) -> None:
        target = self.base / "drift"
        target.mkdir()
        plan = self.plan(target, "--mode", "adopt")
        (target / "new-after-plan.txt").write_text("change\n", encoding="utf-8")
        result = self.sealed_apply_result(plan)
        self.assertEqual(2, result.returncode)
        self.assertIn("target drifted", result.stderr)
        self.assertFalse((target / "workspace.toml").exists())

    def test_move_requires_flags_and_reports_reference_risk(self) -> None:
        target = self.base / "move"
        target.mkdir()
        (target / "old").mkdir()
        (target / "old/file.txt").write_text("payload\n", encoding="utf-8")
        (target / "notes.md").write_text("See old/file.txt for details.\n", encoding="utf-8")
        plan = self.plan(target, "--mode", "adopt", "--move", "old=new")
        data = json.loads(plan.read_text())
        move = next(item for item in data["operations"] if item["op"] == "move")
        self.assertEqual(["notes.md"], move["reference_hits"])

        no_move_flag = self.sealed_apply_result(plan)
        self.assertIn("--allow-moves", no_move_flag.stderr)
        ref_block = self.sealed_apply_result(plan, "--allow-moves")
        self.assertIn("--allow-reference-breakage", ref_block.stderr)
        self.apply(plan, "--allow-moves", "--allow-reference-breakage")
        self.assertTrue((target / "new/file.txt").is_file())

    def test_atomic_rewrite_move_post_copy_and_rollback(self) -> None:
        target = self.base / "atomic-move"
        target.mkdir()
        (target / "old").mkdir()
        (target / "old/file.txt").write_text("payload\n", encoding="utf-8")
        (target / "old/internal.md").write_text("relative file.txt stays valid\n", encoding="utf-8")
        (target / "notes.md").write_text("Read old/file.txt\n", encoding="utf-8")
        shim = self.base / "shim.txt"
        shim.write_text("compatibility shim\n", encoding="utf-8")
        plan = self.plan(
            target,
            "--mode",
            "adopt",
            "--rewrite",
            "notes.md::old/::new/",
            "--rewrite",
            "old/internal.md::relative::updated",
            "--move",
            "old=new",
            "--post-copy",
            f"{shim}=old/shim.txt",
        )
        payload = json.loads(plan.read_text())
        move = next(item for item in payload["operations"] if item["op"] == "move")
        self.assertEqual(["notes.md"], move["reference_hits"])
        self.assertEqual([], move["unresolved_reference_hits"])
        self.assertFalse(payload["has_reference_risk"])

        receipt = self.apply(plan, "--allow-moves")
        self.assertEqual("Read new/file.txt\n", (target / "notes.md").read_text())
        self.assertTrue((target / "new/file.txt").is_file())
        self.assertEqual("updated file.txt stays valid\n", (target / "new/internal.md").read_text())
        self.assertEqual("compatibility shim\n", (target / "old/shim.txt").read_text())

        self.run_tool("rollback", receipt, check=True)
        self.assertEqual("Read old/file.txt\n", (target / "notes.md").read_text())
        self.assertTrue((target / "old/file.txt").is_file())
        self.assertEqual("relative file.txt stays valid\n", (target / "old/internal.md").read_text())
        self.assertFalse((target / "new").exists())
        self.assertFalse((target / "old/shim.txt").exists())

    def test_historical_reference_exemption_is_visible_but_not_breakage(self) -> None:
        target = self.base / "reference-exempt"
        target.mkdir()
        (target / "old").mkdir()
        (target / "old/file.txt").write_text("payload\n", encoding="utf-8")
        (target / "history.md").write_text("Historical path: old/file.txt\n", encoding="utf-8")
        plan = self.plan(
            target,
            "--mode",
            "adopt",
            "--reference-exempt",
            "history.md",
            "--move",
            "old=new",
        )
        payload = json.loads(plan.read_text())
        move = next(item for item in payload["operations"] if item["op"] == "move")
        self.assertEqual(["history.md"], move["exempt_reference_hits"])
        self.assertEqual([], move["unresolved_reference_hits"])
        receipt = self.apply(plan, "--allow-moves")
        self.assertTrue((target / "new/file.txt").is_file())
        self.run_tool("rollback", receipt, check=True)

    def test_replace_from_is_hash_guarded_and_rollback_safe(self) -> None:
        target = self.base / "replace-from"
        target.mkdir()
        (target / "policy.toml").write_text('state = "old"\n', encoding="utf-8")
        replacement = self.base / "new-policy.toml"
        replacement.write_text('state = "new"\n', encoding="utf-8")
        plan = self.plan(
            target,
            "--mode",
            "adopt",
            "--replace-from",
            f"{replacement}=policy.toml",
        )
        receipt = self.apply(plan)
        self.assertEqual('state = "new"\n', (target / "policy.toml").read_text())
        self.run_tool("rollback", receipt, check=True)
        self.assertEqual('state = "old"\n', (target / "policy.toml").read_text())

    def test_rollback_refuses_to_erase_post_apply_edits(self) -> None:
        target = self.base / "rollback-drift"
        plan = self.plan(target, "--mode", "new")
        receipt = self.apply(plan)
        (target / "README.md").write_text("new user work\n", encoding="utf-8")
        result = self.run_tool("rollback", receipt)
        self.assertEqual(2, result.returncode)
        self.assertIn("refusing rollback", result.stderr)
        self.assertEqual("new user work\n", (target / "README.md").read_text())

    def test_copy_source_drift_prevents_partial_install(self) -> None:
        target = self.base / "source-drift"
        plan = self.plan(target, "--mode", "new")
        payload = json.loads(plan.read_text())
        copy = next(item for item in payload["operations"] if item["op"] == "copy_file")
        copy["source_sha256"] = "0" * 64
        plan.write_text(json.dumps(payload), encoding="utf-8")
        result = self.sealed_apply_result(plan)
        self.assertEqual(2, result.returncode)
        self.assertIn("template source drifted", result.stderr)
        self.assertFalse((target / "workspace.toml").exists())

    def test_apply_requires_matching_review_receipt(self) -> None:
        target = self.base / "review-required"
        plan = self.plan(target, "--mode", "new")
        missing = self.run_tool("apply", plan)
        self.assertEqual(2, missing.returncode)
        self.assertIn("--review-receipt", missing.stderr)

        review = plan.with_suffix(".review.json")
        self.run_tool("review", plan, "--reviewer", "test-reviewer", "--output", review, check=True)
        payload = json.loads(plan.read_text(encoding="utf-8"))
        payload["created_at"] = "changed-after-review"
        plan.write_text(json.dumps(payload), encoding="utf-8")
        mismatch = self.run_tool("apply", plan, "--review-receipt", review)
        self.assertEqual(2, mismatch.returncode)
        self.assertIn("review receipt does not match", mismatch.stderr)


if __name__ == "__main__":
    unittest.main()
