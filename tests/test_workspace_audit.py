from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from workspace_audit import audit_workspace  # noqa: E402


POLICY = """\
schema_version = 1
[workspace]
name = "fixture"
raw_ttl_days = 7
max_text_scan_bytes = 1048576
allowed_statuses = ["active", "archived"]
allowed_top_level = [".ai", ".githooks", "AGENTS.md", "archive", "assets", "docs", "governance", "knowledge", "projects", "services", "tools", "workbench", "workspace.toml"]
ignored_top_level = [".git", "__pycache__"]
scan_skip_dirs = []
required_paths = []
[[layers]]
path = "workbench"
catalog_required = true
child_readme_required = true
[[layers]]
path = "projects"
catalog_required = true
child_readme_required = true
[[layers]]
path = "services"
catalog_required = true
child_readme_required = true
[[layers]]
path = "tools"
catalog_required = true
child_readme_required = true
[[layers]]
path = "archive"
catalog_required = false
child_readme_required = true
"""


class WorkspaceAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for rel in (
            ".githooks",
            "archive",
            "assets",
            "docs",
            "governance",
            "governance/adapters",
            "knowledge/raw",
            "knowledge/curated",
            "projects",
            "services",
            "tools",
            "workbench",
        ):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "AGENTS.md").write_text("# Fixture rules\n", encoding="utf-8")
        (self.root / "workspace.toml").write_text(POLICY, encoding="utf-8")
        (self.root / "governance/catalog.toml").write_text("schema_version = 1\n", encoding="utf-8")
        (self.root / "governance/debts.toml").write_text("schema_version = 1\n", encoding="utf-8")
        (self.root / "governance/automations.toml").write_text("schema_version = 1\n", encoding="utf-8")
        (self.root / "knowledge/catalog.toml").write_text("schema_version = 1\n", encoding="utf-8")
        (self.root / "assets/catalog.toml").write_text("schema_version = 1\n", encoding="utf-8")
        (self.root / "governance/adapters/catalog.toml").write_text("schema_version = 1\n", encoding="utf-8")
        hook = self.root / ".githooks/pre-commit"
        hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        hook.chmod(0o755)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def issues(self):
        return audit_workspace(self.root, today=date(2026, 8, 20), skip_git_hook=True)

    def codes(self) -> list[str]:
        return [issue.code for issue in self.issues()]

    def test_minimal_contract_passes(self) -> None:
        self.assertEqual([], [issue for issue in self.issues() if issue.severity != "NOTE"])

    def test_unknown_root_entry_is_an_error(self) -> None:
        (self.root / "stray.txt").write_text("stray\n", encoding="utf-8")
        self.assertIn("ROOT_ENTRY_UNKNOWN", self.codes())

    def test_unregistered_child_is_visible_and_unowned(self) -> None:
        child = self.root / "projects/new-project"
        child.mkdir()
        (child / "README.md").write_text("# New project\n", encoding="utf-8")
        codes = self.codes()
        self.assertIn("CATALOG_ENTRY_MISSING", codes)
        self.assertIn("UNOWNED_WARNING", codes)

    def test_secret_scanner_detects_positive_fixture(self) -> None:
        fake_secret = "sk-" + "A" * 24
        (self.root / "docs/leak.md").write_text(fake_secret + "\n", encoding="utf-8")
        self.assertIn("SECRET_DETECTED", self.codes())

    def test_broken_markdown_link_is_an_error(self) -> None:
        (self.root / "docs/link.md").write_text("[missing](not-there.md)\n", encoding="utf-8")
        self.assertIn("MARKDOWN_LINK_BROKEN", self.codes())

    def test_configured_nested_scan_skip_avoids_runtime_content(self) -> None:
        policy = (self.root / "workspace.toml").read_text(encoding="utf-8")
        policy = policy.replace("scan_skip_dirs = []", 'scan_skip_dirs = ["docs/runtime"]')
        (self.root / "workspace.toml").write_text(policy, encoding="utf-8")
        (self.root / "docs/runtime").mkdir()
        (self.root / "docs/runtime/leak.md").write_text("sk-" + "A" * 24 + "\n", encoding="utf-8")
        self.assertNotIn("SECRET_DETECTED", self.codes())

    def test_stale_raw_requires_exact_debt(self) -> None:
        rel = "knowledge/raw/2026-08-01-observation.md"
        (self.root / rel).write_text("unfinished\n", encoding="utf-8")
        first = self.issues()
        self.assertTrue(any(issue.code == "RAW_STALE" for issue in first))
        self.assertTrue(any(issue.code == "UNOWNED_WARNING" for issue in first))

        debt = f'''\
schema_version = 1
[[debts]]
id = "DEBT-001"
check = "RAW_STALE"
subject = "{rel}"
kind = "debt"
owner = "tester"
due = "2026-09-01"
reason = "waiting for a second observation"
state = "open"
'''
        (self.root / "governance/debts.toml").write_text(debt, encoding="utf-8")
        second = self.issues()
        self.assertTrue(any(issue.code == "RAW_STALE" for issue in second))
        self.assertFalse(any(issue.code == "UNOWNED_WARNING" for issue in second))

    def test_non_executable_hook_is_an_error(self) -> None:
        hook = self.root / ".githooks/pre-commit"
        hook.chmod(0o644)
        self.assertIn("HOOK_NOT_EXECUTABLE", self.codes())

    def test_unsupported_schema_version_is_an_error(self) -> None:
        (self.root / "assets/catalog.toml").write_text("schema_version = 99\n", encoding="utf-8")
        self.assertIn("SCHEMA_VERSION_UNSUPPORTED", self.codes())

    def test_catalog_requires_kind_and_argv_verifier(self) -> None:
        child = self.root / "projects/example"
        child.mkdir()
        (child / "README.md").write_text("# Example\n", encoding="utf-8")
        (self.root / "governance/catalog.toml").write_text(
            '''schema_version = 1
[[items]]
id = "example"
path = "projects/example"
status = "active"
owner = "tester"
verify = "python3 -m unittest"
''',
            encoding="utf-8",
        )
        codes = self.codes()
        self.assertIn("CATALOG_KIND_MISSING", codes)
        self.assertIn("CATALOG_VERIFY_INVALID", codes)

    def test_service_requires_healthcheck_and_runbooks(self) -> None:
        child = self.root / "services/api"
        child.mkdir()
        (child / "README.md").write_text("# API\n", encoding="utf-8")
        (self.root / "governance/catalog.toml").write_text(
            '''schema_version = 1
[[items]]
id = "api"
path = "services/api"
kind = "service"
status = "active"
owner = "tester"
verify = ["python3", "-c", "pass"]
''',
            encoding="utf-8",
        )
        codes = self.codes()
        self.assertIn("SERVICE_HEALTHCHECK_INVALID", codes)
        self.assertIn("SERVICE_RUNBOOK_MISSING", codes)

    def test_curated_knowledge_requires_real_evidence_and_sections(self) -> None:
        rel = "knowledge/curated/rule.md"
        (self.root / rel).write_text("# Rule\n\nOnly a claim.\n", encoding="utf-8")
        (self.root / "knowledge/catalog.toml").write_text(
            f'''schema_version = 1
[[entries]]
id = "rule"
title = "Rule"
path = "{rel}"
status = "active"
evidence = ["RUN-NOT-REAL"]
''',
            encoding="utf-8",
        )
        codes = self.codes()
        self.assertIn("KNOWLEDGE_EVIDENCE_UNRESOLVED", codes)
        self.assertIn("KNOWLEDGE_SECTION_MISSING", codes)

    def test_curated_knowledge_accepts_resolvable_evidence_and_sections(self) -> None:
        evidence_id = "RUN-20260820T000000Z-fixture"
        manifest = self.root / f".ai/runs/{evidence_id}/manifest.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{"id": "fixture"}\n', encoding="utf-8")
        rel = "knowledge/curated/rule.md"
        (self.root / rel).write_text(
            "# Rule\n\n## 结论\nC\n\n## 证据与试错\nE\n\n## 边界与反例\nB\n\n## 关联\nR\n",
            encoding="utf-8",
        )
        (self.root / "knowledge/catalog.toml").write_text(
            f'''schema_version = 1
[[entries]]
id = "rule"
title = "Rule"
path = "{rel}"
status = "active"
evidence = ["{evidence_id}"]
''',
            encoding="utf-8",
        )
        codes = self.codes()
        self.assertNotIn("KNOWLEDGE_EVIDENCE_UNRESOLVED", codes)
        self.assertNotIn("KNOWLEDGE_SECTION_MISSING", codes)

    def test_asset_catalog_enforces_owner_and_boolean_boundaries(self) -> None:
        (self.root / "assets/catalog.toml").write_text(
            '''schema_version = 1
[[assets]]
id = "credentials"
path = ".secrets"
kind = "secret-location"
tracked = "no"
movable = false
required = false
''',
            encoding="utf-8",
        )
        codes = self.codes()
        self.assertIn("ASSET_OWNER_MISSING", codes)
        self.assertIn("ASSET_POLICY_INVALID", codes)

    def test_untracked_asset_policy_detects_git_tracking(self) -> None:
        runtime = self.root / "assets/private.txt"
        runtime.write_text("placeholder\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "assets/private.txt"], check=True)
        (self.root / "assets/catalog.toml").write_text(
            '''schema_version = 1
[[assets]]
id = "private-runtime"
path = "assets/private.txt"
kind = "private-runtime"
owner = "tester"
tracked = false
movable = false
required = true
''',
            encoding="utf-8",
        )
        self.assertIn("ASSET_TRACKING_VIOLATION", self.codes())

    def test_adapter_is_only_executed_when_explicitly_requested(self) -> None:
        probe = self.root / "governance/adapters/probe.py"
        probe.write_text(
            'import json\nprint(json.dumps({"schema_version": 1, "issues": [{"severity": "ERROR", "code": "BROKEN", "subject": "fixture", "message": "broken", "remediation": "fix"}]}))\n',
            encoding="utf-8",
        )
        (self.root / "governance/adapters/catalog.toml").write_text(
            '''schema_version = 1
[[adapters]]
id = "probe"
purpose = "fixture"
command = ["python3", "governance/adapters/probe.py"]
timeout_seconds = 10
owner = "tester"
status = "active"
''',
            encoding="utf-8",
        )
        self.assertNotIn("ADAPTER_BROKEN", self.codes())
        explicit = audit_workspace(self.root, today=date(2026, 8, 20), skip_git_hook=True, run_adapters=True)
        self.assertIn("ADAPTER_BROKEN", [issue.code for issue in explicit])


if __name__ == "__main__":
    unittest.main()
