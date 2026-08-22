# Contributing

Thank you for helping improve AI Workspace Template.

## Before opening a change

1. Search existing issues and keep the proposal scoped to one governance invariant or user-facing workflow.
2. Do not include credentials, private chat content, native-session IDs, local `.ai/` data, or customer/project identifiers.
3. Preserve the distinction between observation, additive governance, reorganization, operation, and publication authority.

## Development setup

Requirements: Git, a POSIX shell, and Python 3.11 or newer. Runtime code uses only the Python standard library.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/workspace_audit.py --run-adapters
python3 scripts/release_check.py
```

Every new machine check needs both a normal fixture and a fixture that proves the violation fails. Changes to adoption or activation must also exercise plan review, drift rejection, receipt generation, and rollback.

## Pull requests

- Explain the user problem and authority boundary.
- List exact verification commands and outcomes.
- Update `CHANGELOG.md` when behavior or a public contract changes.
- Keep generated reports, `.ai/`, `.workspace/plans/`, receipts, backups, and runtime output out of the pull request.

By submitting a contribution, you agree that it is licensed under Apache License 2.0.
