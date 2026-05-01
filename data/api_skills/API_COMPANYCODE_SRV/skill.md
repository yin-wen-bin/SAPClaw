# API_COMPANYCODE_SRV Skill

## Purpose

Use this API for Company Code - Read. The service enables you to retrieve company code master data. It contains a header and nodes with business information. You can read company codes and their properties like name, country and currency.

Keep `data/index/API_COMPANYCODE_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about company code - read or the business objects exposed by this service: A Company Code.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_COMPANYCODE_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_CompanyCode`: Reads the items of all company codes.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Company Code - Read.
- Use the service description, entity descriptions, and field descriptions from `data/index/API_COMPANYCODE_SRV` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Bridge To Chart-Of-Accounts APIs

- Company-code scoped G/L account questions need `A_CompanyCode.ChartOfAccounts` as a bridge value. This API can answer the company-code-to-chart lookup, but it cannot list G/L accounts by itself.
- For requests such as `查询公司1710的费用类科目`, use this API only as step 1: filter `A_CompanyCode.CompanyCode eq '1710'`, select `CompanyCode`, `CompanyCodeName`, and `ChartOfAccounts`, then continue in the routed G/L account API.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- If this skill says the index is documentation-only, route and plan only when the schema is sufficient, and expect SAP execution to require service authorization or metadata activation.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_COMPANYCODE_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
