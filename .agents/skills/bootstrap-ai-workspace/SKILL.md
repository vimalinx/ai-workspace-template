---
name: bootstrap-ai-workspace
description: Initialize a new governed AI workspace or safely adopt and organize an existing workspace using a reviewable plan, additive scaffolding, backups, apply receipts, verification, and drift-aware rollback. Use when asked to create a human-and-AI workspace, bring order to an existing repository or folder, extract a reusable governance model from a mature workspace, add AI auto-maintenance, reconcile workspace structure, or reorganize a live or dirty worktree without losing current conventions. Also trigger for near-miss requests such as “clean up this repo,” “make this folder maintain itself,” “turn this into the same kind of workspace as another project,” or “standardize this workspace for agents.”
---

# Bootstrap AI Workspace

Build a governed workspace whose AI maintenance is observable, bounded, and reversible. Treat the reference workspace as a maturity target, not as a directory tree to copy blindly.

## Load the contracts

Read these references before planning:

- `references/contracts.md` for authority, plan, apply, verification, and rollback rules.
- `references/maturity-patterns.md` for the domain-neutral governance model extracted from a mature workspace.
- `references/live-adoption-case.md` when adopting a dirty, live, production-like workspace.

Use `scripts/workspace_tool.py` for inspection and mutations. Do not reimplement its guarded operations with ad hoc shell commands.

## Choose the mode

- Use **new** for a missing or empty target. Create the generic skeleton and then adapt its name, layers, catalog, and domain checks.
- Use **adopt** for any non-empty target. Preserve all existing business files and instructions; add the governance control plane around them.
- Use **reorganize** only as an adopt phase followed by separately reviewed moves. Never bundle inferred moves into the initial adoption.
- When Git is dirty or the target is actively operated, default to additive adoption with no moves, deletes, commits, permission changes, deployments, or external scheduler changes.

## Execute the workflow

### 1. Inspect without writing

Run:

```bash
python3 .agents/skills/bootstrap-ai-workspace/scripts/workspace_tool.py inspect /absolute/target --json
```

If the Skill is not installed in the target yet, run the copy in this Skill directory. Review:

- Git state and existing instructions;
- root entries and domain-native layers;
- nested repositories and large runtime areas;
- sensitive-looking files, modes, and Git-ignore status;
- existing governance, evidence, knowledge, status, and automation surfaces;
- warnings that should become explicit debt rather than speculative cleanup.

Inspection is permission to observe, not permission to repair.

### 2. Create a reviewable plan

Write the plan to a private path, normally `.workspace/plans/`:

```bash
python3 /path/to/bootstrap-ai-workspace/scripts/workspace_tool.py plan /absolute/target \
  --mode adopt \
  --template-root /absolute/Ai-Workspace_template \
  --name "Workspace name" \
  --catalog-layer existing-domain-layer \
  --scan-skip existing-agent-mirror \
  --protect .env \
  --protect runtime-data \
  --output /absolute/target/.workspace/plans/adopt.json
```

For a new target, use `--mode new`. Repeat `--catalog-layer`, `--scan-skip`, and `--protect` as needed. `--scan-skip` excludes an existing path from broad text/link/secret scans without changing Git rules. `--protect` additionally adds a path to the managed Git-ignore block; it does not change permissions or move content.

Review the exact JSON operations before apply. Confirm:

- no existing business file is overwritten;
- adopt mode only appends owned managed blocks to `AGENTS.md`, `README.md`, and `.gitignore`;
- each copied or generated path is absent or explicitly owned by this governance layer;
- catalog entries reflect existing first-level work items without declaring guessed lifecycle facts;
- protected runtime, profile, data, secret, cache, and nested-repository areas are excluded;
- any unresolved warning has an owner, reason, and due date before claiming governance is green.

If the target changes after planning, discard the plan and generate a new one. Do not weaken drift checks.

### 3. Seal and apply only the approved plan

After reviewing the exact plan bytes, create a private review sidecar:

```bash
python3 /path/to/bootstrap-ai-workspace/scripts/workspace_tool.py review \
  /absolute/target/.workspace/plans/adopt.json \
  --reviewer "human-or-accountable-agent" \
  --output /absolute/target/.workspace/plans/adopt.review.json
```

Any edit to the plan after this step invalidates the review. Reseal only after reviewing the changed operations.

Run:

```bash
python3 /path/to/bootstrap-ai-workspace/scripts/workspace_tool.py apply \
  /absolute/target/.workspace/plans/adopt.json \
  --review-receipt /absolute/target/.workspace/plans/adopt.review.json
```

The tool backs up modified existing files under `.workspace/backups/` and writes a mode-600 receipt under `.workspace/receipts/`. Preserve both until verification and user acceptance.

Moves require all of the following:

1. the user explicitly authorized reorganization, not merely initialization or cleanup;
2. every move appears as `--move SOURCE=DEST` in a newly reviewed plan;
3. `--allow-moves` is passed at apply time;
4. textual reference hits are repaired first, or the user explicitly accepts the listed breakage and `--allow-reference-breakage` is passed.

For an atomic reorganization, use repeatable `--rewrite 'PATH::OLD::NEW'` arguments to place exact text repairs before the move. Use `--post-copy SOURCE=DEST` only for a reviewed compatibility entry that must be created after its old directory has moved. Both operations are hash-pinned, backed up or receipted, and reversed with the same rollback. Use `--reference-exempt PATH` only for an immutable historical record whose old path must remain truthful; the hit stays visible in the plan. When all reported reference hits are resolved or explicitly exempted, apply requires `--allow-moves` but not `--allow-reference-breakage`.

Never infer permission to delete files, purge caches, change modes, commit, push, deploy, install hooks, edit cron/systemd, rotate credentials, close debt, or promote knowledge. Those are separate actions requiring task-specific authority.

### 4. Activate local operational surfaces separately

For a new target, initialize Git, the `.ai/` evidence ledger, and the commit hook through a separate activation plan. For an adopted target, request only the missing operations that are in scope:

```bash
python3 /absolute/target/scripts/workspace_activate.py status /absolute/target
python3 /absolute/target/scripts/workspace_activate.py plan /absolute/target \
  --init-git --init-ledger --install-hook \
  --output /absolute/target/.workspace/plans/activate.json
python3 /absolute/target/scripts/workspace_activate.py review \
  /absolute/target/.workspace/plans/activate.json \
  --reviewer "human-or-accountable-agent" \
  --output /absolute/target/.workspace/plans/activate.review.json
python3 /absolute/target/scripts/workspace_activate.py apply \
  /absolute/target/.workspace/plans/activate.json \
  --review-receipt /absolute/target/.workspace/plans/activate.review.json
```

Review `observed_before` and `operations` before activation apply. The activation receipt supports drift-aware rollback. Never claim cron/systemd installation from a declaration or workflow file; external scheduler state remains `unknown` until an environment-specific adapter observes it.

### 5. Verify the adopted control plane

Run the target audit without assuming a Git hook is installed:

```bash
python3 /path/to/bootstrap-ai-workspace/scripts/workspace_tool.py verify /absolute/target --skip-git-hook
```

Then run the target's relevant tests. For real tests, prompt/model comparisons, migration trials, or consequential decisions, use the nearest project `.ai/` experiment ledger and retain both failed and successful runs.

Run `scripts/workspace_audit.py --run-adapters` when active domain probes are safe and expected. Add `--run-verifiers` only when the catalog validation and service health commands should really execute; plain audit validates their contracts without executing them.

Treat results as follows:

- Fix governance-owned files when the intended correction is clear.
- Preserve domain-owned files; register precise debt instead of broad rewriting.
- Distinguish “not observable” from “broken.”
- Do not claim automatic maintenance is active merely because an automation is declared.
- Install `.githooks` only after the audit is green, the hook is tested against the current worktree, and installation is explicitly in scope.

### 6. Roll back when needed

If verification fails in a way that should not be fixed in scope, run:

```bash
python3 /path/to/bootstrap-ai-workspace/scripts/workspace_tool.py rollback /absolute/target/.workspace/receipts/APPLY-....json
```

Rollback refuses to overwrite post-apply files that have drifted. Preserve the failure evidence, stop, and reconcile manually rather than forcing restoration.

Operational activation has its own rollback receipt:

```bash
python3 /absolute/target/scripts/workspace_activate.py rollback \
  /absolute/target/.workspace/receipts/ACTIVATE-....json
```

## Maintain the governance loop

Use this loop in every adopted domain:

```text
intent routing -> lifecycle layer -> single source of truth
-> machine audit -> commit gate -> periodic read-only reconciliation
-> accountable debt -> experiment evidence -> curated knowledge
```

Keep automatic maintenance in two safe classes:

- observation: inspect, audit, compare, and detect drift;
- derivation: refresh reproducible reports under `.workspace/runtime/`.

Keep authoritative writes—moves, deletion, lifecycle transitions, debt closure, knowledge promotion, deployments, credentials, and external automation—behind explicit approval and verification.

## Reject common rationalizations

| Rationalization | Required response |
|---|---|
| “The repo is messy, so a checkpoint commit is safest.” | A commit changes shared history and scope. Do not commit unless explicitly requested. Use a plan and receipt. |
| “This secret file should obviously be mode 600.” | Report the observed mode and register debt; do not chmod without authority. |
| “Caches and empty logs are safe to delete.” | Inspection does not authorize deletion. Protect or ignore them; propose a separate cleanup. |
| “The reference workspace already proves this layout.” | Copy governance invariants, not domain directories or names. Preserve the target's native topology. |
| “The cron entry is stale, so fix it while here.” | External state is outside workspace adoption. Declare desired automation and leave installation status truthful. |
| “Moving one subsystem will make the audit pass.” | Audit compliance never justifies an unapproved move. Add an adopted layer or debt first. |
| “The worktree was already dirty.” | Existing dirt increases the preservation burden; it does not grant broader authority. |

## Completion checklist

Do not report completion until all applicable items are true:

- the target was inspected and its mode was justified;
- the applied plan is preserved and matches its receipt;
- the review sidecar matches the exact applied plan;
- a new workspace has an initialized `.ai` ledger, or the missing dependency/authority is explicitly reported;
- existing instructions and business files remain intact except for reviewed managed blocks;
- the audit and focused tests were recorded and passed, or remaining warnings are precisely owned debt;
- declared automation is not misreported as installed;
- no unauthorized move, deletion, commit, permission change, deployment, or external write occurred;
- the final handoff names the receipt, rollback command, verification evidence, and remaining boundaries;
- the result is compared with the maturity invariants in `references/maturity-patterns.md`, not merely with its directory names.
