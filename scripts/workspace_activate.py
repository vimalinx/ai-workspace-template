#!/usr/bin/env python3
"""Plan, apply, inspect, and roll back local workspace activation.

Activation is deliberately separate from additive bootstrap because Git
initialization, hook configuration, and evidence-ledger initialization are
operational changes. Every apply is drift checked and receipted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parent.parent
SKIP_FINGERPRINT = {".ai", ".git", ".workspace", "__pycache__", ".pytest_cache"}


class ActivationError(RuntimeError):
    pass


def validate_workspace_root(root: Path) -> Path:
    root = root.expanduser().resolve()
    if root in {Path("/"), Path.home().resolve()}:
        raise ActivationError(f"refusing broad activation target: {root}")
    if not root.is_dir() or not (root / "workspace.toml").is_file():
        raise ActivationError(f"not a governed workspace root: {root}")
    return root


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def atomic_write(path: Path, payload: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def tree_fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    rows: list[str] = []
    for child in sorted(path.rglob("*")):
        rel = child.relative_to(path).as_posix()
        if child.is_symlink():
            rows.append(f"L\0{rel}\0{os.readlink(child)}")
        elif child.is_file():
            rows.append(f"F\0{rel}\0{file_sha256(child)}\0{child.stat().st_mode & 0o777}")
        elif child.is_dir():
            rows.append(f"D\0{rel}")
    return sha256_bytes("\n".join(rows).encode())


def target_fingerprint(root: Path) -> str:
    if not root.exists():
        return sha256_bytes(b"missing")
    rows: list[str] = []
    for child in sorted(root.rglob("*")):
        rel = child.relative_to(root)
        if set(rel.parts) & SKIP_FINGERPRINT:
            continue
        if child.is_symlink():
            rows.append(f"L\0{rel.as_posix()}\0{os.readlink(child)}")
        elif child.is_file():
            rows.append(f"F\0{rel.as_posix()}\0{file_sha256(child)}")
        elif child.is_dir():
            rows.append(f"D\0{rel.as_posix()}")
    return sha256_bytes("\n".join(rows).encode())


def run(root: Path, command: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ActivationError(f"command failed ({result.returncode}): {command!r}: {detail}")
    return result


def git_repo(root: Path) -> bool:
    result = run(root, ["git", "rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return False
    return Path(result.stdout.strip()).resolve() == root.resolve()


def hooks_path(root: Path) -> str | None:
    if not git_repo(root):
        return None
    value = run(root, ["git", "config", "--local", "--get", "core.hooksPath"])
    return value.stdout.strip() if value.returncode == 0 else None


def activation_status(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    declared = (root / "governance/automations.toml").is_file()
    workflow = (root / ".github/workflows/workspace-governance.yml").is_file()
    return {
        "schema_version": 1,
        "kind": "workspace-activation-status",
        "root": str(root),
        "git_initialized": git_repo(root) if root.is_dir() else False,
        "hook_file_present": (root / ".githooks/pre-commit").is_file(),
        "hook_file_executable": os.access(root / ".githooks/pre-commit", os.X_OK),
        "hook_installed": hooks_path(root) == ".githooks" if root.is_dir() else False,
        "hooks_path": hooks_path(root) if root.is_dir() else None,
        "ai_ledger_initialized": (root / ".ai/config.json").is_file(),
        "ai_ledger_initializer": "built-in",
        "ai_ledger_cli_available": shutil.which("ai-ledger") is not None,
        "maintenance_declared": declared,
        "github_workflow_present": workflow,
        "external_scheduler_state": "unknown",
        "external_scheduler_note": "cron/systemd 属于工作区外部状态；只有环境专用探针才能证明已安装。",
    }


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_plan(root: Path, *, init_git: bool, init_ledger: bool, install_hook: bool) -> dict[str, Any]:
    root = validate_workspace_root(root)
    status = activation_status(root)
    operations: list[dict[str, Any]] = []
    if init_git and not status["git_initialized"]:
        operations.append({"op": "init_git"})
    if init_ledger and not status["ai_ledger_initialized"]:
        operations.append({"op": "init_ledger"})
    if install_hook and not status["hook_file_present"]:
        raise ActivationError("cannot install hook: .githooks/pre-commit is missing")
    if install_hook and not (status["git_initialized"] or init_git):
        raise ActivationError("--install-hook requires an existing Git repo or --init-git")
    if install_hook and not status["hook_installed"]:
        operations.append({"op": "install_hook", "before": status["hooks_path"]})
    seed = f"{root}|{utc_now()}|{target_fingerprint(root)}|{operations}"
    return {
        "schema_version": 1,
        "kind": "workspace-activation-plan",
        "id": "ACTPLAN-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + sha256_bytes(seed.encode())[:8],
        "created_at": utc_now(),
        "target": str(root),
        "target_fingerprint": target_fingerprint(root),
        "observed_before": status,
        "operations": operations,
        "external_scheduler_state": "unknown",
    }


def review_plan(path: Path, reviewer: str, output: Path) -> Path:
    path = path.resolve()
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1 or plan.get("kind") != "workspace-activation-plan":
        raise ActivationError("unsupported activation plan")
    if not reviewer.strip():
        raise ActivationError("reviewer must not be empty")
    review = {
        "schema_version": 1,
        "kind": "workspace-activation-review",
        "id": "ACTREVIEW-" + str(plan["id"]).removeprefix("ACTPLAN-"),
        "reviewed_at": utc_now(),
        "reviewer": reviewer.strip(),
        "plan_id": plan["id"],
        "plan_sha256": file_sha256(path),
        "target": plan["target"],
        "target_fingerprint": plan["target_fingerprint"],
        "operation_count": len(plan.get("operations", [])),
    }
    output = output.expanduser().resolve()
    atomic_json(output, review)
    return output


def validate_review(plan: dict[str, Any], path: Path, review_path: Path) -> dict[str, Any]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("schema_version") != 1 or review.get("kind") != "workspace-activation-review":
        raise ActivationError("unsupported activation review")
    expected = {
        "plan_id": plan.get("id"),
        "plan_sha256": file_sha256(path),
        "target": plan.get("target"),
        "target_fingerprint": plan.get("target_fingerprint"),
    }
    for field, value in expected.items():
        if review.get(field) != value:
            raise ActivationError(f"activation review does not match current plan: {field}")
    return review


def initialize_portable_ledger(root: Path) -> None:
    ledger = root / ".ai"
    if ledger.exists() and any(ledger.iterdir()):
        raise ActivationError("refusing to initialize a non-empty partial .ai directory")
    for relative in (
        "decisions",
        "experiments",
        "handoffs",
        "native-sessions",
        "promotions",
        "runs",
        "sessions",
    ):
        (ledger / relative).mkdir(parents=True, exist_ok=True)
    project_slug = re.sub(r"[^a-z0-9]+", "-", root.name.lower()).strip("-") or "workspace"
    project_id = f"PRJ-{project_slug[:48]}-{sha256_bytes(str(root).encode())[:8]}"
    atomic_write(
        ledger / "config.json",
        json.dumps(
            {
                "created_at": utc_now(),
                "project_id": project_id,
                "project_name": root.name,
                "promotion_targets": [],
                "raw_evidence_policy": "local-private",
                "schema_version": "1.0",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    atomic_write(
        ledger / "README.md",
        "# Project AI evidence ledger\n\n"
        "This directory is local-private by default. It stores evidence manifests, "
        "experiment records, decisions, and optional native-session pointers. Export "
        "only deliberately reviewed evidence to a separate public path.\n",
    )
    atomic_write(
        ledger / ".gitignore",
        "# Raw/private evidence stays local.\n"
        ".native-sessions.lock\n"
        "native-sessions/\n"
        "sessions/*/private-notes/\n"
        "runs/*/stdout.log\n"
        "runs/*/stderr.log\n",
    )
    atomic_write(ledger / "ledger.jsonl", "")


def apply_plan(path: Path, review_path: Path) -> Path:
    path = path.resolve()
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("schema_version") != 1 or plan.get("kind") != "workspace-activation-plan":
        raise ActivationError("unsupported activation plan")
    review = validate_review(plan, path, review_path.resolve())
    root = validate_workspace_root(Path(plan["target"]))
    if target_fingerprint(root) != plan["target_fingerprint"]:
        raise ActivationError("target drifted after activation planning")
    actions: list[dict[str, Any]] = []
    try:
        for operation in plan.get("operations", []):
            if operation["op"] == "init_git":
                run(root, ["git", "init", "-q"], check=True)
                actions.append({"kind": "created_git"})
            elif operation["op"] == "init_ledger":
                initialize_portable_ledger(root)
                actions.append({"kind": "created_ledger"})
            elif operation["op"] == "install_hook":
                before = hooks_path(root)
                run(root, ["git", "config", "--local", "core.hooksPath", ".githooks"], check=True)
                actions.append({"kind": "configured_hook", "before": before})
            else:
                raise ActivationError(f"unknown activation operation: {operation['op']}")
    except Exception:
        undo(root, actions, strict=False)
        raise
    receipt = {
        "schema_version": 1,
        "kind": "workspace-activation-receipt",
        "id": "ACTIVATE-" + str(plan["id"]).removeprefix("ACTPLAN-"),
        "activated_at": utc_now(),
        "plan_id": plan["id"],
        "plan_sha256": file_sha256(path),
        "review_id": review["id"],
        "review_sha256": file_sha256(review_path),
        "target": str(root),
        "actions": actions,
        "git_fingerprint": tree_fingerprint(root / ".git"),
        "ledger_fingerprint": tree_fingerprint(root / ".ai"),
        "status_after": activation_status(root),
    }
    output = root / ".workspace/receipts" / f"{receipt['id']}.json"
    atomic_json(output, receipt)
    return output


def undo(root: Path, actions: list[dict[str, Any]], *, strict: bool, receipt: dict[str, Any] | None = None) -> None:
    if strict and receipt:
        if any(action["kind"] == "created_git" for action in actions) and tree_fingerprint(root / ".git") != receipt.get("git_fingerprint"):
            raise ActivationError("Git state drifted; refusing activation rollback")
        if any(action["kind"] == "created_ledger" for action in actions) and tree_fingerprint(root / ".ai") != receipt.get("ledger_fingerprint"):
            raise ActivationError("AI ledger drifted; refusing activation rollback")
        if any(action["kind"] == "configured_hook" for action in actions) and hooks_path(root) != ".githooks":
            raise ActivationError("hook configuration drifted; refusing activation rollback")
    for action in reversed(actions):
        if action["kind"] == "configured_hook":
            if action.get("before") is None:
                run(root, ["git", "config", "--local", "--unset", "core.hooksPath"])
            else:
                run(root, ["git", "config", "--local", "core.hooksPath", action["before"]], check=True)
        elif action["kind"] == "created_ledger" and (root / ".ai").is_dir():
            shutil.rmtree(root / ".ai")
        elif action["kind"] == "created_git" and (root / ".git").is_dir():
            shutil.rmtree(root / ".git")


def rollback(path: Path) -> Path:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("schema_version") != 1 or receipt.get("kind") != "workspace-activation-receipt":
        raise ActivationError("unsupported activation receipt")
    root = validate_workspace_root(Path(receipt["target"]))
    undo(root, receipt.get("actions", []), strict=True, receipt=receipt)
    result = {
        "schema_version": 1,
        "kind": "workspace-activation-rollback-receipt",
        "id": "ACTROLLBACK-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "source_receipt": receipt["id"],
        "rolled_back_at": utc_now(),
        "target": str(root),
        "status_after": activation_status(root),
    }
    output = root / ".workspace/receipts" / f"{result['id']}.json"
    atomic_json(output, result)
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    status_parser = sub.add_parser("status", help="observe activation state without writing")
    status_parser.add_argument("root", type=Path, nargs="?", default=DEFAULT_ROOT)
    plan_parser = sub.add_parser("plan", help="write an exact private activation plan")
    plan_parser.add_argument("root", type=Path)
    plan_parser.add_argument("--init-git", action="store_true")
    plan_parser.add_argument("--init-ledger", action="store_true")
    plan_parser.add_argument("--install-hook", action="store_true")
    plan_parser.add_argument("--output", type=Path, required=True)
    apply_parser = sub.add_parser("apply", help="apply an unchanged activation plan")
    apply_parser.add_argument("plan", type=Path)
    apply_parser.add_argument("--review-receipt", type=Path, required=True)
    review_parser = sub.add_parser("review", help="seal the exact activation plan")
    review_parser.add_argument("plan", type=Path)
    review_parser.add_argument("--reviewer", required=True)
    review_parser.add_argument("--output", type=Path, required=True)
    rollback_parser = sub.add_parser("rollback", help="roll back unchanged activation state")
    rollback_parser.add_argument("receipt", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "status":
            print(json.dumps(activation_status(args.root), ensure_ascii=False, indent=2))
        elif args.command == "plan":
            plan = build_plan(args.root, init_git=args.init_git, init_ledger=args.init_ledger, install_hook=args.install_hook)
            output = args.output.expanduser().resolve()
            atomic_json(output, plan)
            print(output)
        elif args.command == "apply":
            print(apply_plan(args.plan.expanduser().resolve(), args.review_receipt.expanduser().resolve()))
        elif args.command == "review":
            print(review_plan(args.plan, args.reviewer, args.output))
        elif args.command == "rollback":
            print(rollback(args.receipt.expanduser().resolve()))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, ActivationError) as exc:
        print(f"workspace-activate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
