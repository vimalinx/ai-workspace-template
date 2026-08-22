#!/usr/bin/env python3
"""Plan, apply, verify, and roll back governed workspace adoption.

The tool is intentionally conservative:
- inspect is read-only;
- plan writes only to an explicit --output path;
- apply accepts an unchanged plan and never overwrites an unowned file;
- moves require an extra flag and are blocked when textual references exist;
- every changed existing file is backed up and every apply emits a receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE_ROOT = SKILL_ROOT.parents[2]
FINGERPRINT_SKIP = {".ai", ".git", ".workspace"}
WALK_SKIP = {
    ".ai",
    ".git",
    ".pytest_cache",
    ".tmp",
    ".venv",
    ".workspace",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "profiles",
    "venv",
}
SENSITIVE_NAMES = re.compile(r"(^|[._-])(secrets?|tokens?|passwords?|credentials?|wallet|cookies?|keys?)([._-]|$)", re.I)
TEXT_SUFFIXES = {".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".py", ".sh", ".js", ".ts"}
CORE_COPY_PATHS = [
    ".workspace/runtime/.gitkeep",
    "assets/README.md",
    "assets/catalog.toml",
    "archive/README.md",
    "docs/ACTIVATION.md",
    "docs/GOVERNANCE.md",
    "docs/INFORMATION-FLOW.md",
    "docs/SCHEMAS.md",
    "docs/decisions/README.md",
    "governance/adapters/README.md",
    "governance/adapters/catalog.toml",
    "knowledge/README.md",
    "knowledge/curated/README.md",
    "knowledge/raw/README.md",
    "projects/README.md",
    "services/README.md",
    "tools/README.md",
    "workbench/README.md",
    "scripts/precommit_gate.py",
    "scripts/workspace_audit.py",
    "scripts/workspace_maintenance.py",
    "scripts/workspace_activate.py",
    "tests/test_precommit_gate.py",
    "tests/test_workspace_activate.py",
    "tests/test_workspace_audit.py",
    "tests/test_workspace_tool.py",
    ".githooks/pre-commit",
]
DEFAULT_DIRS = [
    ".workspace/runtime",
    "archive",
    "assets",
    "docs/decisions",
    "governance",
    "knowledge/raw",
    "knowledge/curated",
    "projects",
    "services",
    "tools",
    "workbench",
]
DEFAULT_ALLOWED = {
    ".agents",
    ".ai",
    ".github",
    ".githooks",
    ".gitignore",
    ".workspace",
    "AGENTS.md",
    "README.md",
    "archive",
    "assets",
    "docs",
    "governance",
    "knowledge",
    "projects",
    "scripts",
    "services",
    "tests",
    "tools",
    "workbench",
    "workspace.toml",
}
DEFAULT_IGNORED_TOP = {
    ".git",
    ".pytest_cache",
    ".tmp",
    ".venv",
    "__pycache__",
    "logs",
    "node_modules",
    "profiles",
    "venv",
}


class WorkspaceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def safe_rel(raw: str) -> str:
    path = Path(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise WorkspaceError(f"unsafe workspace-relative path: {raw!r}")
    normalized = path.as_posix().strip("/")
    if not normalized or normalized == ".":
        raise WorkspaceError(f"unsafe workspace-relative path: {raw!r}")
    return normalized


def resolve_under(root: Path, raw: str) -> Path:
    rel = safe_rel(raw)
    candidate = (root / rel).resolve(strict=False)
    try:
        candidate.relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise WorkspaceError(f"path escapes workspace: {raw}") from exc
    return candidate


def path_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "missing"


def shallow_entry(path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"name": path.name, "kind": path_kind(path)}
    try:
        st = path.lstat()
    except OSError:
        return info
    info.update({"mode": stat.S_IMODE(st.st_mode), "size": st.st_size, "mtime_ns": st.st_mtime_ns})
    if path.is_symlink():
        info["target"] = os.readlink(path)
    return info


def root_fingerprint(root: Path) -> str:
    if not root.exists():
        return "EMPTY"
    if not root.is_dir():
        return "NOT_A_DIRECTORY"
    entries = [
        shallow_entry(path)
        for path in sorted(root.iterdir(), key=lambda item: item.name)
        if path.name not in FINGERPRINT_SKIP
    ]
    protected: dict[str, str] = {}
    for rel in (
        "AGENTS.md",
        "README.md",
        ".gitignore",
        "workspace.toml",
        "governance/catalog.toml",
        "governance/debts.toml",
        "governance/automations.toml",
    ):
        path = root / rel
        if path.is_file() and not path.is_symlink():
            protected[rel] = file_sha256(path)
    if not entries and not protected:
        return "EMPTY"
    return sha256_bytes(json_bytes({"entries": entries, "protected": protected}))


def directory_fingerprint(path: Path) -> str:
    if path.is_file() and not path.is_symlink():
        return f"file:{file_sha256(path)}"
    if path.is_symlink():
        return f"symlink:{os.readlink(path)}"
    if not path.is_dir():
        return "missing"
    rows: list[dict[str, Any]] = []
    for base, dirs, files in os.walk(path):
        dirs[:] = sorted(name for name in dirs if name not in WALK_SKIP)
        base_path = Path(base)
        for name in sorted(files):
            child = base_path / name
            rel = child.relative_to(path).as_posix()
            try:
                st = child.lstat()
            except OSError:
                continue
            rows.append({"path": rel, "size": st.st_size, "mtime_ns": st.st_mtime_ns, "mode": stat.S_IMODE(st.st_mode)})
    return f"directory:{sha256_bytes(json_bytes(rows))}"


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def git_state(root: Path) -> dict[str, Any]:
    probe = run_git(root, "rev-parse", "--show-toplevel")
    if probe.returncode != 0 or Path(probe.stdout.strip()).resolve() != root.resolve():
        return {"is_repo": False, "dirty": False, "changes": 0, "sample": []}
    status = run_git(root, "status", "--porcelain=v1", "-z").stdout
    rows = [item for item in status.split("\0") if item]
    return {
        "is_repo": True,
        "dirty": bool(rows),
        "changes": len(rows),
        "sample": rows[:20],
        "branch": run_git(root, "branch", "--show-current").stdout.strip() or None,
        "hooks_path": run_git(root, "config", "core.hooksPath").stdout.strip() or None,
    }


def ignored_by_git(root: Path, rel: str) -> bool | None:
    if not (root / ".git").exists():
        return None
    result = run_git(root, "check-ignore", "--quiet", "--no-index", rel)
    return result.returncode == 0


def inspect_workspace(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve(strict=False)
    exists = root.exists()
    if exists and not root.is_dir():
        raise WorkspaceError(f"target is not a directory: {root}")
    entries = [] if not exists else [shallow_entry(path) for path in sorted(root.iterdir(), key=lambda p: p.name)]
    instruction_files = []
    if exists:
        for name in ("AGENTS.md", "CLAUDE.md", "README.md", "STATUS.md", "memory.md"):
            if (root / name).is_file():
                instruction_files.append(name)

    sensitive: list[dict[str, Any]] = []
    if exists:
        for path in root.iterdir():
            if (path.is_file() or path.is_dir()) and (path.name.startswith(".env") or SENSITIVE_NAMES.search(path.name)):
                mode = stat.S_IMODE(path.stat().st_mode)
                sensitive.append(
                    {
                        "path": path.name,
                        "kind": path_kind(path),
                        "mode": f"{mode:o}",
                        "git_ignored": ignored_by_git(root, path.name),
                    }
                )

    nested_repos: list[str] = []
    if exists:
        for first in root.iterdir():
            if not first.is_dir() or first.name in WALK_SKIP or first.name.startswith("."):
                continue
            if (first / ".git").exists():
                nested_repos.append(first.name)
            for second in first.iterdir():
                if second.is_dir() and (second / ".git").exists():
                    nested_repos.append(second.relative_to(root).as_posix())

    git = git_state(root) if exists else {"is_repo": False, "dirty": False, "changes": 0, "sample": []}
    warnings: list[dict[str, str]] = []
    if git.get("dirty"):
        warnings.append({"code": "DIRTY_WORKTREE", "message": f"Git worktree has {git['changes']} changed/untracked entries; use additive adoption unless moves are explicitly approved."})
    for item in sensitive:
        expected_mode = "700" if item["kind"] == "directory" else "600"
        if item["mode"] != expected_mode:
            warnings.append({"code": "SENSITIVE_MODE", "message": f"{item['path']} mode is {item['mode']}, not {expected_mode}."})
        if item["git_ignored"] is False:
            warnings.append({"code": "SENSITIVE_NOT_IGNORED", "message": f"{item['path']} is not ignored by Git."})
    if exists and (root / ".ai/skills").is_dir():
        warnings.append({"code": "LEGACY_SKILL_HOME", "message": ".ai/skills mixes reusable procedures with evidence; migrate deliberately to a project skill root."})
    if exists and (root / "STATUS.md").is_file() and (root / "STATUS.md").stat().st_size > 30_000:
        warnings.append({"code": "STATUS_MONOLITH", "message": "STATUS.md exceeds 30 KiB; keep it append-only for now and plan a curated status/index split."})
    script_count = 0
    if exists and (root / "scripts").is_dir():
        script_count = sum(1 for path in (root / "scripts").iterdir() if path.is_file())
        if script_count > 40:
            warnings.append({"code": "SCRIPT_SPRAWL", "message": f"scripts/ has {script_count} direct files; add an index before moving or deleting anything."})

    mode = "new" if not exists or not entries else "adopt"
    return {
        "schema_version": 1,
        "target": str(root),
        "exists": exists,
        "recommended_mode": mode,
        "fingerprint": root_fingerprint(root),
        "git": git,
        "instruction_files": instruction_files,
        "top_level": entries,
        "sensitive_files": sensitive,
        "nested_repositories": sorted(nested_repos),
        "script_count": script_count,
        "governance": {
            "workspace_toml": (root / "workspace.toml").is_file() if exists else False,
            "catalog": (root / "governance/catalog.toml").is_file() if exists else False,
            "audit": (root / "scripts/workspace_audit.py").is_file() if exists else False,
            "skill": (root / ".agents/skills/bootstrap-ai-workspace/SKILL.md").is_file() if exists else False,
        },
        "warnings": warnings,
    }


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def toml_list(values: Iterable[str], indent: str = "") -> str:
    values = list(values)
    if not values:
        return "[]"
    body = ",\n".join(f"{indent}  {toml_string(value)}" for value in values)
    return f"[\n{body},\n{indent}]"


def render_workspace_toml(
    name: str,
    allowed: set[str],
    ignored: set[str],
    layers: list[dict[str, Any]],
    scan_skip: set[str],
) -> str:
    required = [
        "AGENTS.md",
        "README.md",
        ".agents/skills/bootstrap-ai-workspace/SKILL.md",
        "governance/catalog.toml",
        "governance/debts.toml",
        "governance/automations.toml",
        "governance/adapters/catalog.toml",
        "assets/catalog.toml",
        "knowledge/catalog.toml",
        "docs/SCHEMAS.md",
        "docs/INFORMATION-FLOW.md",
        "docs/ACTIVATION.md",
        "docs/workspace-status.md",
        "scripts/workspace_audit.py",
        "scripts/workspace_maintenance.py",
        "scripts/precommit_gate.py",
        ".githooks/pre-commit",
    ]
    chunks = [
        "schema_version = 1",
        "",
        "[workspace]",
        f"name = {toml_string(name)}",
        "raw_ttl_days = 7",
        "max_text_scan_bytes = 1048576",
        'allowed_statuses = ["unknown", "idea", "active", "paused", "blocked", "maintained", "completed", "retired", "archived", "superseded"]',
        f"allowed_top_level = {toml_list(sorted(allowed))}",
        f"ignored_top_level = {toml_list(sorted(ignored))}",
        f"scan_skip_dirs = {toml_list(sorted(scan_skip))}",
        f"required_paths = {toml_list(required)}",
    ]
    for layer in layers:
        chunks.extend(
            [
                "",
                "[[layers]]",
                f"path = {toml_string(layer['path'])}",
                f"purpose = {toml_string(layer['purpose'])}",
                f"catalog_required = {str(bool(layer['catalog_required'])).lower()}",
                f"child_readme_required = {str(bool(layer['child_readme_required'])).lower()}",
            ]
        )
    return "\n".join(chunks) + "\n"


def render_new_workspace_readme(name: str) -> str:
    return f"""# {name}

This workspace uses the governed AI Workspace model. It keeps work identity, debt, automation declarations, evidence, and curated knowledge in separate authoritative surfaces so humans and agents can maintain it without turning guesses into facts.

## Start here

1. Read `AGENTS.md` and `workspace.toml`.
2. Put uncertain or exploratory work in `workbench/`; graduate durable work to `projects/` or `services/`.
3. Register each direct work item in `governance/catalog.toml` and give it a `README.md`.
4. Initialize local Git, the private evidence ledger, and the hook through the reviewed flow in `docs/ACTIVATION.md`.
5. Verify the workspace:

   ```bash
   python3 -m unittest discover -s tests -v
   python3 scripts/workspace_audit.py --run-adapters
   ```

## Boundaries

- `.ai/` and `.workspace/` are local operational surfaces, not public source or curated knowledge.
- Maintenance reports are derived state; they do not authorize deletion, migration, deployment, knowledge promotion, or external scheduler changes.
- Machine schemas are documented in `docs/SCHEMAS.md`; information flow is documented in `docs/INFORMATION-FLOW.md`.
"""


def render_workspace_scripts_readme() -> str:
    return """# Governance Scripts

| Script | Purpose | Writes |
|---|---|---|
| `workspace_audit.py` | Configuration-driven reconciliation of catalogs, lifecycle, evidence, links, secrets, hooks, and adapters | No, except explicitly enabled probes/verifiers |
| `workspace_maintenance.py` | Runs the audit and refreshes the latest derived report | `.workspace/runtime/audit-latest.json` only |
| `workspace_activate.py` | Reviewed and receipted Git, built-in ledger, and hook activation/rollback | Only planned operations |
| `precommit_gate.py` | Rejects runtime artifacts, secrets, missing ignores, and audit errors from staged changes | No |

Runtime scripts use only the Python standard library. The built-in ledger initializer has no external CLI dependency.
"""


def render_workspace_ci() -> str:
    return """name: workspace-governance

on:
  push:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: python3 -m unittest discover -s tests -v
      - run: python3 scripts/workspace_audit.py --skip-git-hook --run-adapters
"""


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if slug:
        return slug[:64]
    return "item-" + hashlib.sha256(value.encode()).hexdigest()[:10]


def render_catalog(target: Path, catalog_layers: list[str]) -> str:
    rows = ["schema_version = 1", ""]
    used_ids: set[str] = set()
    for layer in catalog_layers:
        base = target / layer
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or child.name.startswith("."):
                continue
            ident = slugify(f"{layer}-{child.name}")
            suffix = 2
            original = ident
            while ident in used_ids:
                ident = f"{original[:58]}-{suffix}"
                suffix += 1
            used_ids.add(ident)
            rows.extend(
                [
                    "[[items]]",
                    f"id = {toml_string(ident)}",
                    f"path = {toml_string(f'{layer}/{child.name}')}",
                    f"kind = {toml_string({'workbench': 'experiment', 'projects': 'project', 'services': 'service', 'tools': 'tool'}.get(layer, layer[:-3] + 'y' if layer.endswith('ies') else layer.rstrip('s') or 'item'))}",
                    'status = "unknown"',
                    'owner = "unassigned"',
                    'verify = ["python3", "-c", "raise SystemExit(\'replace placeholder verifier\')"]',
                    "",
                ]
            )
    if len(rows) == 2:
        rows.append("# No cataloged work items yet. Add [[items]] entries when work begins.")
    return "\n".join(rows).rstrip() + "\n"


def render_automations() -> str:
    return """schema_version = 1

[[automations]]
id = "workspace-maintenance"
purpose = "Run the read-only governance audit and refresh a derived report"
command = ["python3", "scripts/workspace_maintenance.py", "--skip-git-hook"]
schedule = "Declare here; install in cron, systemd, or CI only after environment verification"
owner = "workspace-owner"
status = "declared"
"""


def render_debts(inspection: dict[str, Any], protected: set[str]) -> str:
    rows = [
        "schema_version = 1",
        "",
        "# Inspection findings are manual adoption debts. Re-observe and close them only with explicit authority.",
    ]
    index = 1
    review_due = (datetime.now(timezone.utc).date() + timedelta(days=14)).isoformat()
    for warning in inspection["warnings"]:
        code = str(warning["code"])
        message = str(warning["message"])
        if code == "SENSITIVE_NOT_IGNORED" and any(message.startswith(f"{path} ") for path in protected):
            continue
        subject = {
            "DIRTY_WORKTREE": "git-worktree",
            "SENSITIVE_MODE": message.split(" mode is ", 1)[0],
            "SENSITIVE_NOT_IGNORED": message.split(" is not ignored", 1)[0],
            "LEGACY_SKILL_HOME": ".ai/skills",
            "STATUS_MONOLITH": "STATUS.md",
            "SCRIPT_SPRAWL": "scripts",
        }.get(code, "workspace-inspection")
        rows.extend(
            [
                "",
                "[[debts]]",
                f'id = "ADOPT-{index:03d}"',
                f"check = {toml_string(code)}",
                f"subject = {toml_string(subject)}",
                'kind = "manual"',
                'owner = "workspace-owner"',
                f"due = {toml_string(review_due)}",
                f"reason = {toml_string(message)}",
                'state = "open"',
            ]
        )
        index += 1
    if index == 1:
        rows.extend(["", "# No unresolved inspection findings were imported."])
    return "\n".join(rows) + "\n"


def managed_block(before: str, begin: str, end: str, body: str) -> str:
    block = f"{begin}\n{body.rstrip()}\n{end}"
    if begin in before or end in before:
        if before.count(begin) != 1 or before.count(end) != 1 or before.index(begin) > before.index(end):
            raise WorkspaceError(f"managed block markers are damaged: {begin}")
        start = before.index(begin)
        finish = before.index(end, start) + len(end)
        return before[:start] + block + before[finish:]
    separator = "" if not before else ("\n" if before.endswith("\n") else "\n\n")
    return before + separator + block + "\n"


def contains_workspace_reference(text: str, root: Path, source_rel: str, *, is_directory: bool) -> bool:
    needle = source_rel + "/" if is_directory else source_rel
    relative = re.compile(rf"(?<![A-Za-z0-9_./-]){re.escape(needle)}")
    absolute = f"{root.as_posix().rstrip('/')}/{needle}"
    return bool(relative.search(text) or absolute in text)


def find_reference_hits(root: Path, source_rel: str) -> list[str]:
    source = root / source_rel
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        rel_parts = path.relative_to(root).parts
        if set(rel_parts) & WALK_SKIP or path.stat().st_size > 1_048_576:
            continue
        if path == source or source in path.parents:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if contains_workspace_reference(text, root, source_rel, is_directory=source.is_dir()):
            hits.append(path.relative_to(root).as_posix())
            if len(hits) >= 100:
                break
    return hits


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    target = args.target.expanduser().resolve(strict=False)
    template = args.template_root.expanduser().resolve()
    if not (template / "workspace.toml").is_file():
        raise WorkspaceError(f"template root is missing workspace.toml: {template}")
    inspection = inspect_workspace(target)
    mode = inspection["recommended_mode"] if args.mode == "auto" else args.mode
    if mode == "new" and target.exists() and any(target.iterdir()):
        raise WorkspaceError("new mode requires a missing or empty target; use adopt mode")
    if mode == "adopt" and not target.exists():
        raise WorkspaceError("adopt mode requires an existing target; use new mode")

    name = args.name or target.name or "AI Workspace"
    current_names = {entry["name"] for entry in inspection["top_level"]}
    ignored = set(DEFAULT_IGNORED_TOP)
    allowed = (current_names - ignored - {".git"}) | set(DEFAULT_ALLOWED)
    scan_skip = set(WALK_SKIP) | set(args.scan_skip) | set(args.protect)
    catalog_layers = [safe_rel(item) for item in args.catalog_layer]
    for layer in catalog_layers:
        allowed.add(layer.split("/", 1)[0])

    layers = [
        {"path": "workbench", "purpose": "Exploration and experiments", "catalog_required": True, "child_readme_required": True},
        {"path": "projects", "purpose": "Long-lived projects and deliverables", "catalog_required": True, "child_readme_required": True},
        {"path": "services", "purpose": "Continuously operated services", "catalog_required": True, "child_readme_required": True},
        {"path": "tools", "purpose": "Reusable deterministic tools", "catalog_required": True, "child_readme_required": True},
        {"path": "archive", "purpose": "Retired objects with tombstones", "catalog_required": False, "child_readme_required": True},
    ]
    for layer in catalog_layers:
        if layer not in {item["path"] for item in layers}:
            layers.append({"path": layer, "purpose": f"Adopted domain layer: {layer}", "catalog_required": True, "child_readme_required": False})

    seed = f"{target}|{utc_now()}|{inspection['fingerprint']}"
    plan_id = "PLAN-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(seed.encode()).hexdigest()[:8]
    operations: list[dict[str, Any]] = []

    for rel in DEFAULT_DIRS:
        if not (target / rel).exists():
            operations.append({"op": "mkdir", "dest": rel})

    def add_copy(source: Path, dest_rel: str) -> None:
        dest_rel = safe_rel(dest_rel)
        if (target / dest_rel).exists():
            return
        if not source.is_file():
            raise WorkspaceError(f"template source missing: {source}")
        operations.append(
            {
                "op": "copy_file",
                "source": str(source),
                "source_sha256": file_sha256(source),
                "dest": dest_rel,
                "mode": stat.S_IMODE(source.stat().st_mode),
            }
        )

    for rel in CORE_COPY_PATHS:
        add_copy(template / rel, rel)
    for source in sorted(SKILL_ROOT.rglob("*")):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        rel = source.relative_to(SKILL_ROOT).as_posix()
        add_copy(source, f".agents/skills/bootstrap-ai-workspace/{rel}")

    dynamic_files = {
        "workspace.toml": render_workspace_toml(name, allowed, ignored, layers, scan_skip),
        "governance/catalog.toml": render_catalog(target, catalog_layers),
        "governance/debts.toml": render_debts(inspection, set(args.protect)),
        "governance/automations.toml": render_automations(),
        "knowledge/catalog.toml": "schema_version = 1\n\n# Add [[entries]] only after a raw observation has been validated and curated.\n",
        "docs/workspace-status.md": f"# {name} Status\n\nMachine-readable state lives in `governance/*.toml`; keep only human context, blockers, and recent changes here.\n",
        "scripts/README.md": render_workspace_scripts_readme(),
        ".github/workflows/workspace-governance.yml": render_workspace_ci(),
    }
    for rel, content in dynamic_files.items():
        if not (target / rel).exists():
            operations.append({"op": "write_file", "dest": rel, "content": content, "mode": 0o644})

    if mode == "new":
        add_copy(template / "AGENTS.md", "AGENTS.md")
        if not (target / "README.md").exists():
            operations.append({"op": "write_file", "dest": "README.md", "content": render_new_workspace_readme(name), "mode": 0o644})
        add_copy(template / ".gitignore", ".gitignore")
    else:
        agents_body = """## 通用工作区治理入口

- 目录、状态、债务、知识与自动化分别以 `workspace.toml`、`governance/*.toml`、`knowledge/catalog.toml` 为机器事实源。
- 新探索进入 `workbench/`；长期交付进入 `projects/`；常驻运行进入 `services/`；复用执行器进入 `tools/`。
- 不覆盖现有业务规则。本段只补充治理闭环；发生冲突时先保留更具体、更接近工作对象的现有约束并人工协调。
- 实质性工作结束前运行 `python3 scripts/workspace_audit.py --skip-git-hook`。WARN 当轮修复或精确认领到 `governance/debts.toml`。
- 真实测试与重要决定保存在 `.ai/`；原生聊天正文留在原运行时；未经验证的观察进入 `knowledge/raw/`。
- 自动维护只允许刷新派生报告；移动、删除、关闭债务、知识晋升和外部调度变更需要明确授权与验证。"""
        readme_body = """## Workspace governance

This existing workspace has adopted the governed workspace layer without replacing its domain layout.

- Policy: `workspace.toml`
- Catalog, debt, and automation truth: `governance/`
- Evidence: `.ai/`
- Raw and curated knowledge: `knowledge/`
- Read-only reconciliation: `python3 scripts/workspace_audit.py --skip-git-hook`
- Human/AI initializer: `.agents/skills/bootstrap-ai-workspace/`"""
        protect_lines = [
            ".ai/",
            ".workspace/backups/",
            ".workspace/plans/",
            ".workspace/receipts/",
            ".workspace/runtime/*",
            "!.workspace/runtime/.gitkeep",
        ]
        for rel in sorted(set(args.protect)):
            protect_lines.append(rel.rstrip("/") + ("/" if (target / rel).is_dir() else ""))
        ignore_body = "# Generated governance state and explicitly protected local material\n" + "\n".join(protect_lines)
        for rel, begin, end, body in (
            ("AGENTS.md", "<!-- AI-WORKSPACE:BEGIN -->", "<!-- AI-WORKSPACE:END -->", agents_body),
            ("README.md", "<!-- AI-WORKSPACE:BEGIN -->", "<!-- AI-WORKSPACE:END -->", readme_body),
            (".gitignore", "# AI-WORKSPACE:BEGIN", "# AI-WORKSPACE:END", ignore_body),
        ):
            path = target / rel
            before = path.read_text(encoding="utf-8") if path.is_file() else ""
            after = managed_block(before, begin, end, body)
            if after != before:
                operations.append(
                    {
                        "op": "managed_block",
                        "dest": rel,
                        "content": after,
                        "expected_before_sha256": sha256_bytes(before.encode()) if path.exists() else None,
                        "mode": stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644,
                    }
                )

    rewritten_content: dict[str, str] = {}
    replace_from_paths: set[str] = set()
    for mapping in args.replace_from:
        if "=" not in mapping:
            raise WorkspaceError(f"replace-from must be SOURCE=DEST: {mapping}")
        source_raw, dest_raw = mapping.split("=", 1)
        source = Path(source_raw).expanduser().resolve()
        dest_rel = safe_rel(dest_raw)
        dest = target / dest_rel
        if not source.is_file() or source.is_symlink():
            raise WorkspaceError(f"replace-from source is not a regular file: {source}")
        if not dest.is_file() or dest.is_symlink():
            raise WorkspaceError(f"replace-from destination is not a regular file: {dest_rel}")
        content = source.read_text(encoding="utf-8")
        operations.append(
            {
                "op": "rewrite_file",
                "dest": dest_rel,
                "content": content,
                "expected_before_sha256": file_sha256(dest),
                "mode": stat.S_IMODE(dest.stat().st_mode),
                "replacement_source": str(source),
                "replacement_source_sha256": file_sha256(source),
            }
        )
        rewritten_content[dest_rel] = content
        replace_from_paths.add(dest_rel)

    rewrite_groups: dict[str, list[tuple[str, str]]] = {}
    for mapping in args.rewrite:
        parts = mapping.split("::", 2)
        if len(parts) != 3:
            raise WorkspaceError(f"rewrite must be PATH::OLD::NEW: {mapping}")
        rel, old, new = safe_rel(parts[0]), parts[1], parts[2]
        if not old:
            raise WorkspaceError(f"rewrite OLD text must not be empty: {mapping}")
        rewrite_groups.setdefault(rel, []).append((old, new))

    for rel, replacements in sorted(rewrite_groups.items()):
        if rel in replace_from_paths:
            raise WorkspaceError(f"cannot combine replace-from and rewrite for the same file: {rel}")
        path = target / rel
        if not path.is_file() or path.is_symlink():
            raise WorkspaceError(f"rewrite target is not a regular file: {rel}")
        before = path.read_text(encoding="utf-8")
        after = before
        applied: list[dict[str, Any]] = []
        for old, new in replacements:
            count = after.count(old)
            if not count:
                raise WorkspaceError(f"rewrite text not found in {rel}: {old!r}")
            after = after.replace(old, new)
            applied.append({"old": old, "new": new, "count": count})
        operations.append(
            {
                "op": "rewrite_file",
                "dest": rel,
                "content": after,
                "expected_before_sha256": file_sha256(path),
                "mode": stat.S_IMODE(path.stat().st_mode),
                "replacements": applied,
            }
        )
        rewritten_content[rel] = after

    reference_exemptions = {safe_rel(item) for item in args.reference_exempt}
    moves: list[dict[str, Any]] = []
    for mapping in args.move:
        if "=" not in mapping:
            raise WorkspaceError(f"move must be SOURCE=DEST: {mapping}")
        source_raw, dest_raw = mapping.split("=", 1)
        source_rel, dest_rel = safe_rel(source_raw), safe_rel(dest_raw)
        source, dest = target / source_rel, target / dest_rel
        if not source.exists() and not source.is_symlink():
            raise WorkspaceError(f"move source does not exist: {source_rel}")
        if dest.exists() or dest.is_symlink():
            raise WorkspaceError(f"move destination already exists: {dest_rel}")
        reference_hits = find_reference_hits(target, source_rel)
        exempt_hits = [rel for rel in reference_hits if rel in reference_exemptions]
        unresolved_hits = [
            rel
            for rel in reference_hits
            if rel not in reference_exemptions
            and contains_workspace_reference(
                rewritten_content.get(rel, (target / rel).read_text(encoding="utf-8")),
                target,
                source_rel,
                is_directory=source.is_dir(),
            )
        ]
        moves.append(
            {
                "op": "move",
                "source": source_rel,
                "dest": dest_rel,
                "source_fingerprint": directory_fingerprint(source),
                "reference_hits": reference_hits,
                "exempt_reference_hits": exempt_hits,
                "unresolved_reference_hits": unresolved_hits,
            }
        )
    post_move_rewrites: list[dict[str, Any]] = []
    pre_move_operations: list[dict[str, Any]] = []
    for operation in operations:
        rel = str(operation.get("dest", ""))
        relocated = None
        if operation.get("op") == "rewrite_file":
            for move in moves:
                source_rel, dest_rel = str(move["source"]), str(move["dest"])
                if rel == source_rel or rel.startswith(source_rel + "/"):
                    suffix = rel[len(source_rel) :]
                    relocated = dest_rel + suffix
                    break
        if relocated is None:
            pre_move_operations.append(operation)
        else:
            operation = dict(operation)
            operation["original_dest"] = rel
            operation["dest"] = relocated
            operation["phase"] = "post-move"
            post_move_rewrites.append(operation)
    operations = pre_move_operations + moves + post_move_rewrites

    vacated = [str(item["source"]) for item in moves]
    for mapping in args.post_copy:
        if "=" not in mapping:
            raise WorkspaceError(f"post-copy must be SOURCE=DEST: {mapping}")
        source_raw, dest_raw = mapping.split("=", 1)
        source = Path(source_raw).expanduser().resolve()
        dest_rel = safe_rel(dest_raw)
        dest = target / dest_rel
        will_be_vacated = any(dest_rel == rel or dest_rel.startswith(rel + "/") for rel in vacated)
        if (dest.exists() or dest.is_symlink()) and not will_be_vacated:
            raise WorkspaceError(f"post-copy destination already exists: {dest_rel}")
        if not source.is_file() or source.is_symlink():
            raise WorkspaceError(f"post-copy source is not a regular file: {source}")
        operations.append(
            {
                "op": "copy_file",
                "source": str(source),
                "source_sha256": file_sha256(source),
                "dest": dest_rel,
                "mode": stat.S_IMODE(source.stat().st_mode),
                "phase": "post-move",
            }
        )

    return {
        "schema_version": 1,
        "kind": "workspace-adoption-plan",
        "id": plan_id,
        "created_at": utc_now(),
        "target": str(target),
        "mode": mode,
        "template_root": str(template),
        "target_fingerprint": inspection["fingerprint"],
        "inspection": inspection,
        "catalog_layers": catalog_layers,
        "scan_skip_paths": sorted(set(args.scan_skip)),
        "protected_paths": sorted(set(args.protect)),
        "reference_exemptions": sorted(reference_exemptions),
        "operations": operations,
        "requires_allow_moves": bool(moves),
        "has_reference_risk": any(item["unresolved_reference_hits"] for item in moves),
    }


def backup_existing(target: Path, plan_id: str, rel: str) -> str:
    source = target / rel
    backup_rel = f".workspace/backups/{plan_id}/{rel}"
    backup = target / backup_rel
    backup.parent.mkdir(parents=True, exist_ok=True)
    private_root = target / ".workspace/backups"
    current = backup.parent
    while current == private_root or private_root in current.parents:
        os.chmod(current, 0o700)
        if current == private_root:
            break
        current = current.parent
    shutil.copy2(source, backup)
    return backup_rel


def ensure_parent(target: Path, path: Path, actions: list[dict[str, Any]], created_dirs: set[str]) -> None:
    missing: list[Path] = []
    parent = path.parent
    while parent != target and not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir()
        rel = directory.relative_to(target).as_posix()
        if rel not in created_dirs:
            actions.append({"kind": "created_dir", "path": rel})
            created_dirs.add(rel)


def review_plan(plan_path: Path, reviewer: str, output: Path | None = None) -> Path:
    plan_path = plan_path.resolve()
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("kind") != "workspace-adoption-plan" or plan.get("schema_version") != 1:
        raise WorkspaceError("unsupported or invalid plan")
    if not reviewer.strip():
        raise WorkspaceError("reviewer must not be empty")
    receipt = {
        "schema_version": 1,
        "kind": "workspace-plan-review",
        "id": "REVIEW-" + str(plan["id"]).removeprefix("PLAN-"),
        "reviewed_at": utc_now(),
        "reviewer": reviewer.strip(),
        "plan_id": plan["id"],
        "plan_path": str(plan_path),
        "plan_sha256": file_sha256(plan_path),
        "target": plan["target"],
        "target_fingerprint": plan["target_fingerprint"],
        "operation_count": len(plan.get("operations", [])),
        "requires_allow_moves": bool(plan.get("requires_allow_moves")),
        "has_reference_risk": bool(plan.get("has_reference_risk")),
    }
    destination = output.resolve() if output else plan_path.with_suffix(plan_path.suffix + ".review.json")
    atomic_write(destination, json_bytes(receipt), 0o600)
    return destination


def validate_review(plan: dict[str, Any], plan_path: Path, review_path: Path) -> dict[str, Any]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("kind") != "workspace-plan-review" or review.get("schema_version") != 1:
        raise WorkspaceError("unsupported or invalid review receipt")
    expected = {
        "plan_id": plan.get("id"),
        "plan_sha256": file_sha256(plan_path),
        "target": plan.get("target"),
        "target_fingerprint": plan.get("target_fingerprint"),
    }
    for field, value in expected.items():
        if review.get(field) != value:
            raise WorkspaceError(f"review receipt does not match current plan: {field}")
    return review


def apply_plan(plan_path: Path, review_path: Path, allow_moves: bool, allow_reference_breakage: bool) -> Path:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("kind") != "workspace-adoption-plan" or plan.get("schema_version") != 1:
        raise WorkspaceError("unsupported or invalid plan")
    review = validate_review(plan, plan_path, review_path)
    target = Path(plan["target"]).resolve(strict=False)
    if root_fingerprint(target) != plan["target_fingerprint"]:
        raise WorkspaceError("target drifted after planning; create a fresh plan")
    if plan.get("requires_allow_moves") and not allow_moves:
        raise WorkspaceError("plan contains moves; rerun with --allow-moves after reviewing them")
    if plan.get("has_reference_risk") and not allow_reference_breakage:
        raise WorkspaceError("move references were found; resolve them or explicitly pass --allow-reference-breakage")
    if not target.exists():
        target.mkdir(parents=True)
    actions: list[dict[str, Any]] = []
    created_dirs: set[str] = set()
    plan_id = str(plan["id"])

    try:
        for operation in plan["operations"]:
            kind = operation["op"]
            if kind == "mkdir":
                dest = resolve_under(target, operation["dest"])
                if not dest.exists():
                    ensure_parent(target, dest, actions, created_dirs)
                    dest.mkdir()
                    rel = dest.relative_to(target).as_posix()
                    actions.append({"kind": "created_dir", "path": rel})
                    created_dirs.add(rel)
                elif not dest.is_dir():
                    raise WorkspaceError(f"mkdir target is not a directory: {operation['dest']}")
            elif kind == "copy_file":
                source = Path(operation["source"])
                if file_sha256(source) != operation["source_sha256"]:
                    raise WorkspaceError(f"template source drifted: {source}")
                dest = resolve_under(target, operation["dest"])
                if dest.exists() or dest.is_symlink():
                    raise WorkspaceError(f"refusing to overwrite: {operation['dest']}")
                ensure_parent(target, dest, actions, created_dirs)
                data = source.read_bytes()
                atomic_write(dest, data, int(operation["mode"]))
                actions.append({"kind": "created_file", "path": operation["dest"], "post_sha256": sha256_bytes(data)})
            elif kind in {"write_file", "managed_block", "rewrite_file"}:
                dest = resolve_under(target, operation["dest"])
                content = operation["content"].encode()
                before_hash = file_sha256(dest) if dest.is_file() else None
                if kind == "write_file" and before_hash is not None:
                    raise WorkspaceError(f"refusing to overwrite: {operation['dest']}")
                expected = operation.get("expected_before_sha256")
                if kind in {"managed_block", "rewrite_file"} and before_hash != expected:
                    raise WorkspaceError(f"managed file drifted: {operation['dest']}")
                ensure_parent(target, dest, actions, created_dirs)
                if before_hash is None:
                    atomic_write(dest, content, int(operation["mode"]))
                    actions.append({"kind": "created_file", "path": operation["dest"], "post_sha256": sha256_bytes(content)})
                else:
                    backup_rel = backup_existing(target, plan_id, operation["dest"])
                    atomic_write(dest, content, int(operation["mode"]))
                    actions.append(
                        {
                            "kind": "modified_file",
                            "path": operation["dest"],
                            "before_sha256": before_hash,
                            "post_sha256": sha256_bytes(content),
                            "backup": backup_rel,
                        }
                    )
            elif kind == "move":
                source = resolve_under(target, operation["source"])
                dest = resolve_under(target, operation["dest"])
                if directory_fingerprint(source) != operation["source_fingerprint"]:
                    raise WorkspaceError(f"move source drifted: {operation['source']}")
                if dest.exists() or dest.is_symlink():
                    raise WorkspaceError(f"move destination exists: {operation['dest']}")
                ensure_parent(target, dest, actions, created_dirs)
                source.rename(dest)
                actions.append(
                    {
                        "kind": "moved",
                        "source": operation["source"],
                        "dest": operation["dest"],
                        "post_fingerprint": directory_fingerprint(dest),
                    }
                )
            else:
                raise WorkspaceError(f"unknown operation: {kind}")
    except Exception:
        undo_actions(target, actions, strict=False)
        raise

    receipt = {
        "schema_version": 1,
        "kind": "workspace-adoption-receipt",
        "id": "APPLY-" + plan_id.removeprefix("PLAN-"),
        "plan_id": plan_id,
        "plan_sha256": file_sha256(plan_path),
        "review_id": review["id"],
        "review_sha256": file_sha256(review_path),
        "applied_at": utc_now(),
        "target": str(target),
        "actions": actions,
        "post_fingerprint": root_fingerprint(target),
    }
    receipt_path = target / f".workspace/receipts/{receipt['id']}.json"
    atomic_write(receipt_path, json_bytes(receipt), 0o600)
    return receipt_path


def undo_actions(target: Path, actions: list[dict[str, Any]], *, strict: bool) -> None:
    for action in reversed(actions):
        kind = action["kind"]
        if kind == "created_file":
            path = resolve_under(target, action["path"])
            if not path.exists():
                continue
            if file_sha256(path) != action["post_sha256"]:
                if strict:
                    raise WorkspaceError(f"created file drifted; refusing rollback: {action['path']}")
                continue
            path.unlink()
        elif kind == "modified_file":
            path = resolve_under(target, action["path"])
            backup = resolve_under(target, action["backup"])
            if not path.is_file() or file_sha256(path) != action["post_sha256"]:
                if strict:
                    raise WorkspaceError(f"modified file drifted; refusing rollback: {action['path']}")
                continue
            if not backup.is_file() or file_sha256(backup) != action["before_sha256"]:
                raise WorkspaceError(f"backup missing or damaged: {action['backup']}")
            shutil.copy2(backup, path)
        elif kind == "moved":
            source = resolve_under(target, action["source"])
            dest = resolve_under(target, action["dest"])
            if source.exists() or not dest.exists() or directory_fingerprint(dest) != action["post_fingerprint"]:
                if strict:
                    raise WorkspaceError(f"move drifted; refusing rollback: {action['dest']}")
                continue
            source.parent.mkdir(parents=True, exist_ok=True)
            dest.rename(source)
        elif kind == "created_dir":
            path = resolve_under(target, action["path"])
            if path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass


def rollback_receipt(receipt_path: Path) -> Path:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("kind") != "workspace-adoption-receipt" or receipt.get("schema_version") != 1:
        raise WorkspaceError("unsupported or invalid receipt")
    target = Path(receipt["target"]).resolve()
    undo_actions(target, receipt["actions"], strict=True)
    result = {
        "schema_version": 1,
        "kind": "workspace-rollback-receipt",
        "id": "ROLLBACK-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "source_receipt": receipt["id"],
        "rolled_back_at": utc_now(),
        "target": str(target),
        "post_fingerprint": root_fingerprint(target),
    }
    output = target / f".workspace/receipts/{result['id']}.json"
    atomic_write(output, json_bytes(result), 0o600)
    return output


def verify_workspace(root: Path, skip_git_hook: bool, run_adapters: bool = False, run_verifiers: bool = False) -> int:
    root = root.expanduser().resolve()
    audit = root / "scripts/workspace_audit.py"
    if not audit.is_file():
        raise WorkspaceError(f"audit entry missing: {audit}")
    command = [sys.executable, str(audit), "--root", str(root)]
    if skip_git_hook:
        command.append("--skip-git-hook")
    if run_adapters:
        command.append("--run-adapters")
    if run_verifiers:
        command.append("--run-verifiers")
    return subprocess.run(command).returncode


def render_inspection(data: dict[str, Any]) -> str:
    lines = [
        f"Target: {data['target']}",
        f"Mode: {data['recommended_mode']}",
        f"Git: {'dirty' if data['git'].get('dirty') else 'clean' if data['git'].get('is_repo') else 'not initialized'}",
        f"Top-level entries: {len(data['top_level'])}",
        f"Governance: {json.dumps(data['governance'], ensure_ascii=False)}",
    ]
    for warning in data["warnings"]:
        lines.append(f"WARN [{warning['code']}] {warning['message']}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_parser = sub.add_parser("inspect", help="read-only workspace inventory and risk scan")
    inspect_parser.add_argument("target", type=Path)
    inspect_parser.add_argument("--json", action="store_true")

    plan_parser = sub.add_parser("plan", help="create a receipt-gated adoption plan")
    plan_parser.add_argument("target", type=Path)
    plan_parser.add_argument("--mode", choices=("auto", "new", "adopt"), default="auto")
    plan_parser.add_argument("--template-root", type=Path, default=DEFAULT_TEMPLATE_ROOT)
    plan_parser.add_argument("--name")
    plan_parser.add_argument("--catalog-layer", action="append", default=[])
    plan_parser.add_argument("--scan-skip", action="append", default=[])
    plan_parser.add_argument("--protect", action="append", default=[])
    plan_parser.add_argument("--replace-from", action="append", default=[], metavar="SOURCE=DEST")
    plan_parser.add_argument("--rewrite", action="append", default=[], metavar="PATH::OLD::NEW")
    plan_parser.add_argument("--reference-exempt", action="append", default=[], metavar="PATH")
    plan_parser.add_argument("--move", action="append", default=[])
    plan_parser.add_argument("--post-copy", action="append", default=[], metavar="SOURCE=DEST")
    plan_parser.add_argument("--output", type=Path)

    apply_parser = sub.add_parser("apply", help="apply an unchanged plan and emit a receipt")
    apply_parser.add_argument("plan", type=Path)
    apply_parser.add_argument("--review-receipt", type=Path, required=True)
    apply_parser.add_argument("--allow-moves", action="store_true")
    apply_parser.add_argument("--allow-reference-breakage", action="store_true")

    review_parser = sub.add_parser("review", help="seal the exact reviewed plan in a private sidecar receipt")
    review_parser.add_argument("plan", type=Path)
    review_parser.add_argument("--reviewer", required=True)
    review_parser.add_argument("--output", type=Path)

    verify_parser = sub.add_parser("verify", help="run the adopted workspace audit")
    verify_parser.add_argument("target", type=Path)
    verify_parser.add_argument("--skip-git-hook", action="store_true")
    verify_parser.add_argument("--run-adapters", action="store_true")
    verify_parser.add_argument("--run-verifiers", action="store_true")

    rollback_parser = sub.add_parser("rollback", help="roll back an unchanged apply receipt")
    rollback_parser.add_argument("receipt", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "inspect":
            data = inspect_workspace(args.target)
            print(json.dumps(data, ensure_ascii=False, indent=2) if args.json else render_inspection(data))
            return 0
        if args.command == "plan":
            plan = build_plan(args)
            payload = json_bytes(plan)
            if args.output:
                output = args.output.expanduser().resolve(strict=False)
                atomic_write(output, payload, 0o600)
                print(output)
            else:
                sys.stdout.buffer.write(payload)
            return 0
        if args.command == "apply":
            print(
                apply_plan(
                    args.plan.expanduser().resolve(),
                    args.review_receipt.expanduser().resolve(),
                    args.allow_moves,
                    args.allow_reference_breakage,
                )
            )
            return 0
        if args.command == "review":
            output = args.output.expanduser().resolve() if args.output else None
            print(review_plan(args.plan.expanduser().resolve(), args.reviewer, output))
            return 0
        if args.command == "verify":
            return verify_workspace(args.target, args.skip_git_hook, args.run_adapters, args.run_verifiers)
        if args.command == "rollback":
            print(rollback_receipt(args.receipt.expanduser().resolve()))
            return 0
    except (OSError, ValueError, json.JSONDecodeError, WorkspaceError) as exc:
        print(f"workspace-tool: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
