# Public release runbook

Publishing is a separate authority from implementation. This runbook prepares and verifies a release; it does not authorize creating a remote, pushing a branch, publishing a tag, or changing repository settings.

## 1. Prepare

1. Choose the public owner and repository location.
2. Confirm that Apache-2.0 is the intended license before the first public commit.
3. Update `VERSION` and add the exact bracketed version to `CHANGELOG.md`.
4. Review every staged path. Local `.ai/`, `.workspace/`, credentials, logs, databases, native conversations, and customer data must remain outside the public tree.

## 2. Verify

```bash
python3 -m unittest discover -s tests -v
python3 scripts/workspace_audit.py --run-adapters
python3 scripts/release_check.py
git add -n .
```

The first three commands must exit zero. The dry-run staging list must contain only deliberate public source files. After the repository has an initial commit and remote, run `python3 scripts/release_check.py --strict-git` as the final publication preflight.

## 3. Publish with explicit authority

Create a reviewed commit, configure the intended remote, push the branch, enable the template-repository setting, and then create an annotated tag matching `v$(cat VERSION)`. The tag workflow rejects a tag whose name does not match `VERSION`.

## 4. Verify from the outside

Create a fresh repository with **Use this template**, then exercise bootstrap, activation, audit, rollback, and a private-reference search from a clean environment. Record only sanitized outcomes in the release notes; retain raw evidence locally.

## Rollback boundary

Before publication, correct or replace local commits normally. After publication, do not rewrite a consumed release silently: publish a corrective version, mark the affected version, and keep the original evidence and changelog history.
