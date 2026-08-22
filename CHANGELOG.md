# Changelog

All notable changes are documented here. This project follows semantic versioning after `0.1.0` and uses prerelease identifiers while public contracts may still change.

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
