# Security Policy

SAPClaw is intended for private SAP environments. Do not publish real SAP credentials, LLM API keys, raw SAP metadata, local API indexes, request histories, or generated test cases.

## Supported Versions

Security updates currently target the `main` branch.

## Reporting A Vulnerability

Do not open a public issue containing credentials, SAP hostnames, customer data, or raw SAP responses. Report privately to the repository owner or through the private channel used by your deployment team.

Include:

- The affected version or commit.
- The vulnerable endpoint or component.
- Steps to reproduce using sanitized data.
- The expected impact.

## Secrets

Store credentials in `env/.env` or environment variables only. The repository ignores `.env`, `env/`, key files, certificates, generated indexes, raw metadata, and test case assets.

If a key is exposed:

1. Revoke or rotate it immediately in the provider system.
2. Remove it from local files and logs.
3. Check Git history before publishing.

## External Deployment Policy

Local development may run without `SAPCLAW_API_KEYS` on `127.0.0.1`.

Any external, shared, or reverse-proxy deployment must:

- Set `SAPCLAW_API_KEYS` to high-entropy keys.
- Require the `X-API-Key` header for public query calls.
- Use HTTPS.
- Restrict network access to trusted users and services.
- Keep `env/`, `data/index/`, `data/metadata/`, `raw/`, and test case assets off public hosts.
- Avoid exposing `/api/v1/agent/*` directly unless equivalent gateway authentication is enforced.
