
---
name: delegate-subagents
description: Split bounded work among specialized subagents using persistent Assignment contracts, non-overlapping scopes, explicit budgets, independent evaluation, Git baselines, and a single integrator. Use when parallel research, implementation, review, evaluation, or curation would improve throughput or reliability.
---

# Delegate Subagents

Subagents are scoped workers, not copies of the principal Agent's authority.

## Decide whether to delegate

Delegate only when the work has clear inputs, outputs, write scope, verification and stopping conditions. Keep tightly coupled edits serial. Use an Evaluator for fresh-context judgment rather than asking the Implementer to grade itself.

## Create the contract first

Read `docs/SUBAGENTS.md` and `governance/agent-roles.toml`. Create an Assignment with `workspace_protocol.py create assignment`. Include role, objective, integrator, input paths, read/write/forbidden scopes, deliverables, verification, base SHA, budgets and `may_delegate`.

Run protocol validation before launching. Active Assignment write scopes must not overlap.

## Prompt the worker

Tell the worker to read the Assignment path, relevant work-item README and Mission. State that the Assignment is the complete authority boundary. It must report unknowns, preserve failures, stop on scope conflicts and write only agreed deliverables.

## Monitor

Use an external supervisor or runtime heartbeat for long jobs. A worker claiming it is running is not proof of progress. Enforce budget and terminate repeated output or stale heartbeat.

## Integrate

The named Integrator checks base SHA drift, scope, actual changes, test evidence and conflicts. Transition submitted → integrating. For substantive work, obtain a separate Evaluation before accepted/rejected. The worker never merges, deploys or closes the parent Agenda by itself.
