# Extracting a reusable governance model

This template was derived from a mature, continuously maintained workspace. The extraction retained relationships that generalized across domains and removed all project-specific accounts, services, hosts, ports, schedules, and credential rules.

The retained loop is:

```text
intent routing → lifecycle placement → single sources of truth
→ machine reconciliation → commit gate → bounded maintenance
→ accountable debt → experiment evidence → curated knowledge
```

The decisive design choice was to separate normative rules, current operational facts, evidence, and reusable knowledge. Filesystem reality and TOML catalogs own dynamic facts; Markdown explains intent and runbooks; local-private evidence preserves what was tried; curated knowledge contains only validated conclusions with boundaries.

Domain-specific checks enter through the adapter JSON protocol rather than through hard-coded names in the core audit. A research workspace can probe studies and pipelines, a content workspace can probe publishing channels, and a software workspace can probe services without changing the core issue contract.

See the Skill reference [`maturity-patterns.md`](../.agents/skills/bootstrap-ai-workspace/references/maturity-patterns.md) for the compact invariant matrix.
