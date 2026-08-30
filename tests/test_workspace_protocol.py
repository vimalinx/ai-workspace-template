from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/workspace_protocol.py"


class WorkspaceProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()
        for rel in (
            "scripts/workspace_protocol.py",
            "governance/protocol.toml",
            "governance/read-routes.toml",
            "governance/agent-roles.toml",
        ):
            destination = self.root / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / rel, destination)
        shutil.copytree(SOURCE / "governance/schemas", self.root / "governance/schemas")
        for path in (
            "AGENTS.md",
            "docs/INDEX.md",
            "docs/PROGRESSIVE-DISCLOSURE.md",
            "docs/OPERATING-PROTOCOL.md",
            "docs/AUTONOMOUS-WORK.md",
            "docs/SUBAGENTS.md",
            "docs/INDEXES.md",
            "docs/SELF-EVOLUTION.md",
            "docs/GIT-AND-HANDOFF.md",
            "docs/SCHEMAS.md",
            "docs/INFORMATION-FLOW.md",
            "docs/GOVERNANCE.md",
            "docs/ACTIVATION.md",
            "docs/PUBLIC-RELEASE.md",
            "docs/workspace-status.md",
            "knowledge/README.md",
            "SECURITY.md",
            "CHANGELOG.md",
            ".agents/skills/bootstrap-ai-workspace/SKILL.md",
            ".agents/skills/operate-ai-workspace/SKILL.md",
            ".agents/skills/autonomous-exploration/SKILL.md",
            ".agents/skills/delegate-subagents/SKILL.md",
            ".agents/skills/checkpoint-handoff/SKILL.md",
        ):
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            source = SOURCE / path
            if source.is_file():
                shutil.copy2(source, destination)
            else:
                destination.write_text(f"# {path}\n", encoding="utf-8")
        for rel in ("workbench", "projects", "services", "tools", ".workspace/runtime", ".workspace/views"):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "workspace.toml").write_text("schema_version = 1\n", encoding="utf-8")
        (self.root / "governance/catalog.toml").write_text("schema_version = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str, expect: int = 0) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != expect:
            self.fail(
                f"command {args!r} returned {result.returncode}, expected {expect}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def create_item(self, name: str = "example") -> Path:
        item = self.root / "projects" / name
        item.mkdir()
        (item / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        with (self.root / "governance/catalog.toml").open("a", encoding="utf-8") as handle:
            handle.write(
                f'''\n[[items]]\nid = "{name}"\npath = "projects/{name}"\nkind = "project"\nstatus = "active"\nowner = "tester"\nverify = ["python3", "-c", "pass"]\n'''
            )
        self.run_cli(
            "init-item",
            "--item", f"projects/{name}",
            "--title", name,
            "--objective", "Improve the project through verified work",
            "--owner", "tester",
            "--boundary", "Do not deploy",
            "--success-signal", "Verified improvement",
        )
        return item

    @staticmethod
    def parse_created(result: subprocess.CompletedProcess[str]) -> str:
        return str(json.loads(result.stdout)["id"])

    def test_clean_protocol_validates_without_runtime_writes(self) -> None:
        self.run_cli("validate")
        self.assertFalse((self.root / ".workspace/runtime/leases").exists())

    def test_route_is_progressive_and_stops_on_missing_item_control(self) -> None:
        item = self.root / "projects/example"
        item.mkdir()
        (item / "README.md").write_text("# Example\n", encoding="utf-8")
        with (self.root / "governance/catalog.toml").open("a", encoding="utf-8") as handle:
            handle.write('\n[[items]]\nid="example"\npath="projects/example"\nkind="project"\nstatus="active"\nowner="tester"\nverify=["python3","-c","pass"]\n')
        result = self.run_cli("route", "--intent", "work", "--item", "projects/example", "--json", expect=2)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["stop"])
        self.assertIn("projects/example/.agent/mission.toml", payload["missing"])
        self.create_item("ready")
        ready = self.run_cli("route", "--intent", "work", "--item", "projects/ready", "--json")
        self.assertFalse(json.loads(ready.stdout)["stop"])

    def test_agenda_search_and_indexes_preserve_authority(self) -> None:
        item = self.create_item()
        agenda = self.parse_created(
            self.run_cli(
                "create", "agenda", "--item", "projects/example",
                "--title", "Investigate performance", "--rationale", "Performance is measurable",
                "--expected-value", "0.9", "--information-gain", "0.8",
            )
        )
        node = self.parse_created(
            self.run_cli(
                "create", "search-node", "--item", "projects/example",
                "--question", "Which bottleneck dominates?", "--agenda-id", agenda,
            )
        )
        self.run_cli("index", "rebuild", "--item", "projects/example")
        self.assertTrue((self.root / ".workspace/views/workspace-index.json").is_file())
        item_view = self.root / ".workspace/views/items/projects--example/status.json"
        self.assertTrue(item_view.is_file())
        self.assertTrue((item / ".agent/search" / f"{node}.toml").is_file())
        payload = json.loads(item_view.read_text(encoding="utf-8"))
        self.assertTrue(payload["derived"])
        self.assertEqual("projects/example", payload["item"])

    def test_search_cycle_is_reported(self) -> None:
        item = self.create_item()
        first = self.parse_created(self.run_cli("create", "search-node", "--item", "projects/example", "--question", "A"))
        second = self.parse_created(self.run_cli("create", "search-node", "--item", "projects/example", "--question", "B", "--parent-id", first))
        path = item / ".agent/search" / f"{first}.toml"
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        data["parent_ids"] = [second]
        sys.path.insert(0, str(SOURCE / "scripts"))
        from workspace_protocol import dump_object  # type: ignore
        path.write_text(dump_object(data), encoding="utf-8")
        result = self.run_cli("validate", "--item", "projects/example", expect=1)
        self.assertIn("SEARCH_GRAPH_CYCLE", result.stdout)

    def test_experiment_requires_matching_independent_evaluation(self) -> None:
        self.create_item()
        hypothesis = self.parse_created(
            self.run_cli(
                "create", "hypothesis", "--item", "projects/example",
                "--statement", "Caching reduces response time", "--falsification", "No measurable reduction",
            )
        )
        experiment = self.parse_created(
            self.run_cli(
                "create", "experiment", "--item", "projects/example",
                "--objective", "Benchmark caching", "--method", "Compare fixed workloads",
                "--hypothesis-id", hypothesis,
            )
        )
        self.run_cli("transition", "--item", "projects/example", "--type", "experiment", "--id", experiment, "--to", "ready", "--reason", "method reviewed")
        self.run_cli("transition", "--item", "projects/example", "--type", "experiment", "--id", experiment, "--to", "running")
        self.run_cli("transition", "--item", "projects/example", "--type", "experiment", "--id", experiment, "--to", "evaluating", "--evidence", "reports/benchmark.json")
        self.run_cli("transition", "--item", "projects/example", "--type", "experiment", "--id", experiment, "--to", "accepted", expect=2)
        evaluation = self.parse_created(
            self.run_cli(
                "create", "evaluation", "--item", "projects/example",
                "--experiment-id", experiment, "--evaluator", "fresh-reviewer",
                "--result", "passed", "--summary", "The predefined threshold passed",
                "--evidence", "reports/benchmark.json",
            )
        )
        self.run_cli(
            "transition", "--item", "projects/example", "--type", "experiment", "--id", experiment,
            "--to", "accepted", "--evaluation", evaluation,
        )
        self.run_cli("validate", "--item", "projects/example")

    def test_assignment_conflict_is_rejected_before_activation(self) -> None:
        self.create_item()
        first = self.parse_created(
            self.run_cli(
                "create", "assignment", "--item", "projects/example", "--role", "implementer",
                "--objective", "Implement A", "--integrator", "steward",
                "--write-scope", "projects/example/src", "--deliverable", "patch A",
            )
        )
        second = self.parse_created(
            self.run_cli(
                "create", "assignment", "--item", "projects/example", "--role", "implementer",
                "--objective", "Implement B", "--integrator", "steward",
                "--write-scope", "projects/example/src/module", "--deliverable", "patch B",
            )
        )
        self.run_cli("transition", "--item", "projects/example", "--type", "assignment", "--id", first, "--to", "ready", "--reason", "scoped")
        result = self.run_cli("transition", "--item", "projects/example", "--type", "assignment", "--id", second, "--to", "ready", "--reason", "scoped", expect=2)
        self.assertIn("write-scope conflict", result.stderr)

    def test_lease_conflict_release_and_handoff(self) -> None:
        self.create_item()
        first = json.loads(
            self.run_cli(
                "lease", "acquire", "--item", "projects/example", "--holder", "RUN-A",
                "--scope", "projects/example/src", "--ttl", "60",
            ).stdout
        )
        self.run_cli(
            "lease", "acquire", "--item", "projects/example", "--holder", "RUN-B",
            "--scope", "projects/example/src/module", "--ttl", "60", expect=2,
        )
        self.run_cli("lease", "release", "--lease-id", first["id"], "--holder", "RUN-A")
        self.run_cli(
            "handoff", "--item", "projects/example", "--actor", "RUN-A",
            "--summary", "Completed a bounded verified turn", "--completed", "Added protocol fixture",
            "--next", "Select the next Agenda item", "--tests", "unit tests passed",
            "--unknown", "external scheduler state", "--risk", "none observed",
        )
        handoff = (self.root / "projects/example/.agent/handoff.md").read_text(encoding="utf-8")
        for heading in ("## Completed", "## Verification", "## Next", "## Unknowns", "## Risks"):
            self.assertIn(heading, handoff)


if __name__ == "__main__":
    unittest.main()
