# API Natural Language E2E Test Assets

This folder stores business-language test cases for the SAP OData agent.

These assets are intentionally separate from `data/index`, which remains the schema/index ground truth.

## Layout

- `{API}/cases.json`: natural-language cases and deterministic baseline requests.
- `{API}/baselines/{case_id}.json`: baseline result captured from real SAP OData.
- `../api_test_runs/{run_id}`: per-run frontend/main-chain execution results and summaries.

## Case Rules

- `user_input` should use normal business wording, not API names, entity names, or field names.
- Different parameter values do not count as different scenarios.
- Baseline requests must be deterministic SAP OData requests and must not go through the LLM router/planner.
- The runner records failures and suggested failure layer; it does not modify production code.
