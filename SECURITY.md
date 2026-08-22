# Security policy

## Supported versions

Security fixes are provided for the latest tagged prerelease or stable release. Until `1.0`, users should expect public contracts to evolve between minor versions.

## Reporting a vulnerability

Use the repository host's private vulnerability-reporting feature. If it is unavailable, contact the maintainer through a non-public channel listed on the maintainer's profile. Do not open a public issue containing a credential, native-session ID, private workspace path, exploit details, or customer data.

Include the affected version, operating system, reproduction steps, expected impact, and the smallest sanitized evidence needed to verify the issue. Maintainers should acknowledge a report within seven days and provide a remediation or coordination update within fourteen days when practical.

## Security boundary

- `.ai/`, `.workspace/plans/`, receipts, backups, runtime reports, credentials, logs, databases, and native conversations are local-private.
- The project performs no telemetry and does not upload workspace content.
- Domain adapters and catalog verifiers execute only with explicit flags.
- External scheduler installation, deployment, credential operations, commits, pushes, and publication require separate authority.
