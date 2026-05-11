# Persona Daily SAP Query E2E Cases

This folder stores 15 role-based daily SAP query scenarios:

- General finance staff: 5 cases.
- Finance manager: 5 cases.
- CIO: 5 cases.

The cases use normal business wording and are intended to test LLM routing, field selection, query planning, execution, and presentation across FI, MM, SD, and PP.

Rules:

- Baselines are deterministic SAP OData requests.
- Frontend runs must use the LLM-first agent chain.
- API-specific business fixes should be captured in `data/api_skills/{API}/skill.md`.
- Shared behavior fixes should go into common routing/planning/validation/execution logic only when they are reusable across APIs.
