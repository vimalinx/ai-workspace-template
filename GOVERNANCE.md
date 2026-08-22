# Project governance

The project is maintainer-led during the `0.x` series. Maintainers accept changes based on user impact, safety boundaries, backward-compatibility cost, test evidence, and maintainability.

Public machine contracts follow these rules:

- compatible optional fields may be added within a schema version;
- field removal, renaming, semantic changes, or stricter accepted values require a schema migration;
- deprecations are documented in `CHANGELOG.md` before removal;
- security fixes may accelerate the normal compatibility window.

Major decisions should cite reproducible evidence. A declaration, generated report, conversation, or passing happy-path demo does not by itself prove an external operational state.
