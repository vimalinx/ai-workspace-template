
---
name: checkpoint-handoff
description: Finish or pause an Agent run with reconciled files, validation evidence, Git base/head state, durable handoff, rebuilt indexes, and released leases so another fresh Agent can continue safely.
---

# Checkpoint and Handoff

A handoff is a verified entry point, not a narrative diary.

## Reconcile reality

Read actual Git status, active leases, Assignment states, Experiment/Evaluation results, Agenda and current Handoff. Resolve direct state drift or register precise debt. Do not copy stale Handoff claims forward.

## Verify

Run relevant tests, `workspace_protocol.py validate`, `index rebuild`, and `workspace_audit.py`. Report skipped external checks as unknown. Preserve failed output rather than hiding it.

## Record Git state

Capture base SHA, head SHA, branch/worktree and dirty paths. A commit is optional and requires authority; without it, make the dirty state explicit. Push, merge and release require separate authority.

## Write Handoff

Use `workspace_protocol.py handoff` and include summary, completed, incomplete/next, tests, unknowns, risks and Git state. Reference object IDs and evidence rather than pasting logs.

## Release

Release leases owned by the current run. Mark unfinished Assignment/Experiment accurately as blocked, waiting or active. Do not mark complete simply because the context window is ending.
