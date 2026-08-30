# Changelog

All notable changes are documented here. This project follows semantic versioning after `0.1.0` and uses prerelease identifiers while public contracts may still change.

## [Unreleased]

## [0.2.0-alpha.1] - 2026-08-31

### Added

- Add an Agent-native autonomous workspace protocol with progressive-disclosure read routes, persistent Mission/Agenda/Search/Hypothesis/Experiment/Evaluation/Assignment objects, strict state transitions, append-only events, disposable indexes, runtime leases, and explicit handoffs.
- Add detailed operating, autonomous exploration, subagent, indexing, Git, self-evolution, schema, and CLI documentation.
- Add reusable Skills for governed work-item operation, autonomous exploration, subagent delegation, and checkpoint handoff.
- Add deterministic protocol validation and integration with workspace maintenance, audit, bootstrap, CI, and release checks.
- Add a self-contained natural-language handoff that lets any coding Agent with local file and terminal access detect a template copy, empty target, or existing folder and complete safe additive initialization plus separately receipted local activation.

### Changed

- Treat the workspace rather than a model session as the durable orchestration and continuity layer.
- Extend bootstrap adoption so newly governed workspaces receive the autonomous protocol and its complete indexes instead of an incomplete prompt-only convention.
- Rewrite the public README around human-AI workflows and practical use cases, front-load a public-repository URL instruction that any web-capable coding Agent can follow, add a formal project entry, and use native Mermaid diagrams for the evidence loop, complete work-item routing and state transitions, approval boundaries, and adoption/activation/rollback.

### Fixed

- Make additive adoption of an existing folder without `AGENTS.md` generate a valid top-level normative heading instead of failing final verification with `NORMATIVE_HEADER`.

## [0.1.0-alpha.2] - 2026-08-22

### Changed

- Upgrade the official checkout and Python setup actions to their current Node 24-based v7 major versions, eliminating runner deprecation annotations.
- Redact public commit and annotated-tag emails to the maintainer's ID-based GitHub noreply address and add a release guard that prevents recurrence.

## [0.1.0-alpha.1] - 2026-08-22

### Added

- Governed new-workspace and existing-workspace adoption with immutable plans, hash-bound review receipts, apply receipts, backups, drift checks, and rollback.
- Machine audits for schemas, lifecycle catalogs, service runbooks, automations, debt ownership, knowledge evidence, assets, secrets, links, hooks, and domain adapters.
- Built-in, dependency-free initialization of a local-private `.ai` evidence ledger.
- Privacy-first public release boundary, community governance documents, release checks, and Python 3.11–3.14 regression coverage.

### Known limitations

- POSIX environments are supported first; Windows is not yet supported.
- External cron/systemd state requires an environment-specific adapter.
- The repository is distributed as a GitHub template, not as a pip package.

### Fixed

- Allow the tracked `.workspace/runtime/.gitkeep` placeholder while continuing to reject real derived maintenance reports at commit time.
