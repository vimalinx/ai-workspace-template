# Workspace adoption contracts

## Authority boundary

Initialization authorizes creating governance files in a missing or empty target. Adoption authorizes additive governance in an existing target. Neither phrase alone authorizes reorganizing business content.

Treat these as separate, explicit authorities:

| Authority | Examples |
|---|---|
| Observe | inspect files, Git state, modes, ignore rules, links, catalogs, and schedulers |
| Add governance | create absent control-plane files; append owned managed blocks |
| Reorganize | move named paths after reference analysis |
| Clean up | delete named files or classes of files |
| Operate | change permissions, install hooks, edit cron/systemd, deploy, rotate credentials |
| Publish | commit, push, open PRs, or write to external systems |

Authorization for one row does not imply another.

## Plan contract

A plan is an immutable JSON proposal containing:

- target absolute path and mode;
- target fingerprint at planning time;
- inspection result and risks;
- exact ordered operations;
- template source path and digest for every copied file;
- expected pre-change digest for every managed existing file;
- source fingerprint and reference hits for every move;
- protected paths and adopted catalog layers.

Planning may only write the explicitly requested plan file. Store it with mode 600. A changed target or changed template source invalidates the plan.

## Review contract

Review is a separate artifact, not a comment inside a mutable plan. `workspace_tool.py review` writes a mode-600 sidecar containing the plan ID, SHA-256, target, target fingerprint, reviewer, operation count, and move/reference-risk flags. Apply requires this sidecar and rejects any mismatch. Editing either operations or metadata after review requires a fresh review.

## Apply contract

Apply must:

- accept only the supported schema and an unchanged target;
- require a review sidecar that matches the exact current plan bytes;
- create absent directories and files without overwriting;
- replace only this Skill's complete, undamaged managed block;
- back up every changed existing file byte-for-byte;
- require a second flag for moves and another flag for known reference breakage;
- undo completed actions if a later operation fails;
- emit a mode-600 receipt that records all actions and post-change digests.

The receipt proves what this tool changed. It does not claim that unrelated concurrent workspace changes are safe or correct.

## Rollback contract

Rollback reverses receipt actions in reverse order. It restores modified files from backups, moves paths back, and removes created files only when their current digests still equal the receipt's post-apply values. It removes created directories only when empty.

If a governed file has changed after apply, rollback must stop rather than erase the newer work. Reconcile that file manually using the backup and receipt.

Rollback receipts remain under `.workspace/receipts/`. Backups are local-private operational evidence; do not commit them.

## Human CLI examples

Inspect an existing workspace:

```bash
python3 /absolute/skill/scripts/workspace_tool.py inspect /absolute/workspace --json
```

Plan additive adoption:

```bash
python3 /absolute/skill/scripts/workspace_tool.py plan /absolute/workspace \
  --mode adopt \
  --template-root /absolute/Ai-Workspace_template \
  --catalog-layer projects \
  --scan-skip existing-agent-mirror \
  --protect .env \
  --protect data \
  --preserve tests \
  --output /absolute/workspace/.workspace/plans/adopt.json
```

`--protect` keeps local material outside governance and adds it to the managed ignore block.
`--preserve` keeps an existing path governed and versionable while preventing the template from
adding or rewriting files beneath it.

Review, apply, verify, and roll back:

```bash
python3 /absolute/skill/scripts/workspace_tool.py review \
  /absolute/workspace/.workspace/plans/adopt.json \
  --reviewer "human-or-accountable-agent" \
  --output /absolute/workspace/.workspace/plans/adopt.review.json
python3 /absolute/skill/scripts/workspace_tool.py apply \
  /absolute/workspace/.workspace/plans/adopt.json \
  --review-receipt /absolute/workspace/.workspace/plans/adopt.review.json
python3 /absolute/skill/scripts/workspace_tool.py verify /absolute/workspace --skip-git-hook
python3 /absolute/skill/scripts/workspace_tool.py rollback /absolute/workspace/.workspace/receipts/APPLY-....json
```

Plan a separately authorized move:

```bash
python3 /absolute/skill/scripts/workspace_tool.py plan /absolute/workspace \
  --mode adopt \
  --template-root /absolute/Ai-Workspace_template \
  --move old/path=new/path \
  --output /absolute/workspace/.workspace/plans/move.json
```

Review `reference_hits`, update references, then apply with `--allow-moves`. Do not pass `--allow-reference-breakage` merely to silence the guard.

To repair exact references inside the same receipt, add `--rewrite 'PATH::OLD::NEW'`. To leave a small compatibility file after a directory moves, stage its reviewed bytes privately and add `--post-copy /absolute/staged/file=old/path/file`. The plan records source hashes, expected pre-edit hashes, replacement counts, resolved and unresolved reference hits, and operation order.

To replace an existing regular file with separately staged reviewed bytes, use `--replace-from SOURCE=DEST`. The source and destination pre-change hashes are recorded. Use `--reference-exempt PATH` only for immutable historical text that must retain the old reference; exemptions remain visible in the plan.

## Activation contract

File adoption does not imply operating authority. `scripts/workspace_activate.py` separately observes, plans, reviews, applies, and rolls back local Git initialization, `.ai` ledger initialization, and hook configuration. Its plan, hash-bound review sidecar, and receipt are mode 600 and drift checked. A newly created Git or ledger directory is removed on rollback only if its full tree fingerprint is unchanged; once real work or evidence has been added, rollback refuses deletion.

External cron/systemd installation is not inferred or performed by the generic activation tool. Its state remains `unknown` until an environment-specific read-only adapter proves it; any installation needs its own environment-scoped authority, plan, receipt, and uninstall path.
