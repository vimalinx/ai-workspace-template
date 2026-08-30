
---
name: operate-ai-workspace
description: Execute one bounded, verifiable work cycle inside a governed AI workspace. Use when implementing, maintaining, fixing, continuing, or reviewing a registered work item while preserving mission, agenda, evidence, Git, indexes, debts, and a reliable handoff.
---

# Operate AI Workspace

Use the workspace as the durable orchestration layer. A chat session is temporary; do not treat it as state.

## Read before acting

1. Read repository `AGENTS.md`.
2. Run `python3 scripts/workspace_protocol.py route --intent work --item <path>`.
3. Read every returned required file in order.
4. Run `status --item <path>` and compare the Handoff with Git and actual files.

Stop if a mandatory route file, Mission, catalog entry, verifier or authority boundary is missing.

## Execute one transaction

Follow ORIENT → CLAIM → SELECT → PLAN → ACT → VERIFY → RECORD → RECONCILE → INDEX → AUDIT → HANDOFF → RELEASE exactly as defined in `docs/OPERATING-PROTOCOL.md`.

Keep one cycle small enough to complete or hand off without preserving a giant context. Record decisions in files as they become stable; do not postpone all state updates to the end.

## Claims and scope

When another Agent or daemon may write, acquire a lease. When delegating, create Assignment objects. Never use broad repository write permission merely because the model can access the repository.

## Verification

Run the narrowest relevant tests first. Preserve command, environment boundary, exit status and useful output as evidence. A model statement that work looks correct is not verification.

## Finish

Rebuild indexes, validate the protocol, run the governance audit, update Handoff, release leases and report exact Git status. Do not commit, push, merge or deploy unless the task explicitly grants that authority.
