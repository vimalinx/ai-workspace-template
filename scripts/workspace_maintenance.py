#!/usr/bin/env python3
"""Run the read-only audit and refresh a disposable machine-readable report."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from workspace_audit import DEFAULT_ROOT, audit_workspace, counts, render_text
from workspace_protocol import ProtocolError, WorkspaceProtocol


def write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--no-write", action="store_true", help="只检查，不刷新派生报告")
    parser.add_argument("--strict-warnings", action="store_true")
    parser.add_argument("--skip-git-hook", action="store_true")
    parser.add_argument("--run-adapters", action="store_true", help="执行 active 领域适配器")
    parser.add_argument("--run-verifiers", action="store_true", help="执行 catalog verify/healthcheck")
    parser.add_argument("--no-index-rebuild", action="store_true", help="不重建 .workspace/views 派生索引")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    protocol_summary: dict[str, object] = {"installed": False, "indexes_rebuilt": False}
    if (root / "governance/protocol.toml").is_file():
        protocol_summary["installed"] = True
        try:
            protocol = WorkspaceProtocol(root)
            before = protocol.validate()
            protocol_summary["preflight_errors"] = sum(1 for item in before if item.severity == "ERROR")
            if not protocol_summary["preflight_errors"] and not args.no_index_rebuild and not args.no_write:
                protocol_summary["index_result"] = protocol.rebuild_indexes()
                protocol_summary["indexes_rebuilt"] = True
        except (ProtocolError, OSError, ValueError) as exc:
            protocol_summary["error"] = str(exc)

    issues = audit_workspace(
        root,
        skip_git_hook=args.skip_git_hook,
        run_adapters=args.run_adapters,
        run_verifiers=args.run_verifiers,
    )
    summary = counts(issues)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "source_of_truth": [
            "workspace.toml",
            "governance/catalog.toml",
            "governance/debts.toml",
            "governance/automations.toml",
            "governance/adapters/catalog.toml",
            "knowledge/catalog.toml",
            "assets/catalog.toml",
            "governance/protocol.toml",
            "governance/read-routes.toml",
            "governance/agent-roles.toml",
            "work-item .agent objects",
        ],
        "derived": True,
        "protocol": protocol_summary,
        "counts": summary,
        "issues": [asdict(issue) for issue in issues],
    }
    if not args.no_write:
        write_atomic(
            root / ".workspace/runtime/audit-latest.json",
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
    print(render_text(issues))
    if summary["ERROR"] or (args.strict_warnings and summary["WARN"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
