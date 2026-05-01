# API_GLACCOUNTLINEITEM Skill

## Purpose

Use this API for G/L Account Line Items - Read (A2X), not for standalone ledger master records. This service enables you to retrieve accounting-specific information from all journal entries in Financials. You can read journal entry items and detailed information for ledger, company code, ledger fiscal year, G/L account and optionally segment, profit center, cost center and other fields.

Keep `data/index/API_GLACCOUNTLINEITEM` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about g/l account line items - read (a2x) or the business objects exposed by this service: GLAccount Line Item.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_GLACCOUNTLINEITEM`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `GLAccountLineItem`: Get entities from GLAccountLineItem. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: G/L Account Line Items - Read (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_GLACCOUNTLINEITEM` to infer user intent.
- Use `GLAccountLineItem` for journal-entry line-item reporting by G/L account, company code, fiscal year, ledger, accounting document, posting date, amounts, quantities, reference documents, assignments, and partner/service-document fields.
- Do not use this API for standalone ledger master data, ledger names, or ledger configuration records. Route those requests to `API_LEDGER_SRV` when available.
- For wording such as "include", "show fields", or "with ... details", treat named concepts as `$select` fields, not as filters. Do not invent placeholder filters for fields such as `GLAccountLineItem.AccountingDocCreatedByUser` unless the user supplies a concrete user name.
- For created-by-user, account assignment, reference document, service document, clearing, amount, quantity, and organization questions, keep the query on `GLAccountLineItem` and select the requested fields.
- `GLAccountLineItem.ID` is not a sufficient stable business key across different analytical `$select` dimensions. For record/list outputs, keep stable row-identifying dimensions in `$select`: `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, and `GLAccountLineItem.GLAccount`.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Line Item Field Lists

- For broad "list G/L account line item records" requests, select `GLAccountLineItem.ID`, `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.LedgerFiscalYear`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.PostingDate`, `GLAccountLineItem.DocumentDate`, and fields needed by the user request.
- For broad "main identifying details" requests, do not add optional dimensions such as `GLAccountLineItem.AccountingDocCreatedByUser`, `GLAccountLineItem.LedgerGLLineItem`, `GLAccountLineItem.GLRecordType`, `GLAccountLineItem.ControllingArea`, `GLAccountLineItem.DebitCreditCode`, or `GLAccountLineItem.DocumentItemText` unless the user explicitly asks for them. Extra analytical dimensions change result granularity and total counts.
- If the user asks for `AccountingDocCreatedByUser` without providing a user value, select `GLAccountLineItem.AccountingDocCreatedByUser`; do not add a filter with a placeholder value.
- When the user asks for clearing, amount, quantity, assignment, reference, service document, customer, supplier, company code, controlling area, cost center, profit center, or distribution channel details, select those fields on `GLAccountLineItem` and keep the stable row-identifying dimensions listed above.

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

- Verify entity and field availability against `data/index/API_GLACCOUNTLINEITEM` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
