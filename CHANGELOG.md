# Changelog

All notable changes to SAPClaw are documented in this file.

## [1.0.0] - 2026-08-11

### Added

- Natural-language routing across indexed SAP OData services.
- LLM-first planning, repair, schema research, result verification, and presentation.
- Strict local schema validation before read-only SAP execution.
- React query UI, result pagination, case history, feedback, and MCP integration.
- Local API skills and knowledge-graph evidence for business-aware grounding.

### Safety

- SAP execution is restricted to read-only OData requests.
- Credentials and runtime case data remain local and are excluded from source control.
- Query results must be verified in the source SAP system before critical use.

### Known limitations

- SAP service availability and field support depend on the connected system and local indexes.
- LLM routing, plans, summaries, and business interpretations can be incorrect.
- The project is distributed as GitHub source; no PyPI package is published for this release.

[1.0.0]: https://github.com/yin-wen-bin/SAPClaw/releases/tag/v1.0.0
