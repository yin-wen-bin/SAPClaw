# Changelog

All notable changes to SAPClaw are documented in this file.

## [2.0.0] - 2026-08-11

### Changed

- Made the guarded SAPClaw Runtime the only execution architecture and enabled it by default.
- Promoted the Runtime developed on the former Thin Runtime branch and renamed its models, skill, metadata and configuration to stable SAPClaw names.
- Replaced the natural-language query UI with a loopback-only Runtime status and case viewer.
- Added structured `not_ready` health diagnostics for missing SAP URL, credentials, indexes or live-schema support.

### Removed

- Removed the v1 LLM-first Router, Planner, Repairer, Critic, Verifier, Presenter and orchestrator.
- Removed `/api/v1/agent/*`, `/api/v1/queries*`, `sapclaw-mcp`, LLM profiles and provider configuration.
- Removed the Runtime enable switch; the Runtime is always available and fails closed when dependencies are not ready.

### Migration

- Configure `sapclaw-runtime-mcp` and use the `sapclaw-odata` skill.
- Replace legacy Agent API calls with `/api/v1/runtime/*` contracts.
- Continue using v1.0.0 if the embedded LLM-first workflow is required.

## [1.0.0] - 2026-08-11

### Added

- Natural-language routing across indexed SAP OData services.
- LLM-first planning, repair, schema research, result verification, and presentation.
- Strict local schema validation before read-only SAP execution.
- React query UI, result pagination, case history, feedback, and MCP integration.
- Local API skills and knowledge-graph evidence for business-aware grounding.

### Safety

- SAP execution is restricted to read-only OData requests.
- Credentials and locally persisted case files are excluded from source control. When a remote LLM profile is configured, query context and selected SAP result records can be sent to that provider for planning, verification, or presentation; operators must apply the provider's privacy and data-handling controls.
- Query results must be verified in the source SAP system before critical use.

### Known limitations

- SAP service availability and field support depend on the connected system and local indexes.
- LLM routing, plans, summaries, and business interpretations can be incorrect.
- The project is distributed as GitHub source; no PyPI package is published for this release.

[1.0.0]: https://github.com/yin-wen-bin/SAPClaw/releases/tag/v1.0.0
[2.0.0]: https://github.com/yin-wen-bin/SAPClaw/releases/tag/v2.0.0
