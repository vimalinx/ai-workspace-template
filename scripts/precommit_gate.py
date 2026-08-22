#!/usr/bin/env python3
"""Pre-commit gate for staged scope, runtime artifacts, secrets, and audit."""
from __future__ import annotations

import subprocess
import sys
from collections import Counter
from pathlib import Path

from workspace_audit import DEFAULT_ROOT, SECRET_ALLOW_MARK, SECRET_PATTERNS, audit_workspace, counts


ROOT = DEFAULT_ROOT
FORBIDDEN = [
    ("Python bytecode", lambda p: "__pycache__" in p or p.endswith((".pyc", ".pyo"))),
    ("virtual environment", lambda p: p.startswith((".venv/", "venv/")) or "/.venv/" in p),
    ("runtime log", lambda p: p.endswith(".log")),
    ("runtime database/state", lambda p: p.endswith((".db", ".sqlite3", ".pid", ".sock"))),
    ("environment file", lambda p: Path(p).name.startswith(".env") and Path(p).name != ".env.example"),
    (
        "derived maintenance report",
        lambda p: p.startswith(".workspace/runtime/") and p != ".workspace/runtime/.gitkeep",
    ),
    ("raw AI run output", lambda p: p.startswith(".ai/runs/") and p.endswith(("stdout.log", "stderr.log"))),
]


def git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def staged_files() -> list[str]:
    output = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").stdout
    return [item for item in output.split("\0") if item]


def show_scope(files: list[str]) -> None:
    layers = Counter(path.split("/", 1)[0] if "/" in path else "(root)" for path in files)
    print(f"[gate] staged {len(files)} files")
    print("[gate] scope: " + ", ".join(f"{name}={number}" for name, number in sorted(layers.items())))
    if len(files) <= 12:
        for path in files:
            print(f"       {path}")


def forbidden_problems(files: list[str]) -> list[str]:
    problems: list[str] = []
    for label, predicate in FORBIDDEN:
        hits = [path for path in files if predicate(path)]
        if hits:
            tail = "" if len(hits) <= 4 else f" (+{len(hits) - 4} more)"
            problems.append(f"{label}: {', '.join(hits[:4])}{tail}")
    return problems


def force_added_problems(files: list[str]) -> list[str]:
    if not files:
        return []
    result = git("check-ignore", "--no-index", *files)
    hits = [line for line in result.stdout.splitlines() if line.strip()]
    return [f"ignored file was force-added: {', '.join(hits[:4])}"] if hits else []


def secret_problems() -> list[str]:
    diff = git("diff", "--cached", "--unified=0").stdout
    current = "?"
    problems: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++") or SECRET_ALLOW_MARK in line:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                problems.append(f"{current}: added line resembles a complete {label}")
                break
    return problems


def main() -> int:
    files = staged_files()
    if not files:
        print("[gate] staging area is empty")
        return 0
    show_scope(files)
    problems = forbidden_problems(files)
    problems.extend(force_added_problems(files))
    problems.extend(secret_problems())

    audit_issues = audit_workspace(ROOT)
    summary = counts(audit_issues)
    if summary["ERROR"]:
        samples = [f"[{item.code}] {item.subject}" for item in audit_issues if item.severity == "ERROR"][:5]
        problems.append(f"workspace audit has {summary['ERROR']} ERROR: " + "; ".join(samples))

    if not problems:
        print("[gate] passed")
        return 0
    for problem in problems:
        print(f"[gate] ERROR {problem}")
    print("[gate] commit rejected; fix the findings and stage again")
    return 1


if __name__ == "__main__":
    sys.exit(main())
