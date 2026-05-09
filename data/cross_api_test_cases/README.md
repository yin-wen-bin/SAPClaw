# Cross-API Natural Language E2E Test Assets

This folder stores module-oriented cross-API test scenarios for FI, CO, SD, MM, and PP.

Each module has 20 business-language cases. A case contains deterministic SAP OData baseline
steps and an LLM-first frontend-chain question. Baselines are captured under
`{MODULE}/baselines/`; run outputs are stored separately under `data/cross_api_test_runs`.

Rules:

- User inputs must use normal business wording and avoid API/entity/field names.
- Different parameter values do not count as different scenarios.
- Cross-API intent is declared with `expected_apis`.
- General fixes should stay in shared routing/planning/schema logic.
- API-specific business knowledge should be captured in that API's `skill.md`.
