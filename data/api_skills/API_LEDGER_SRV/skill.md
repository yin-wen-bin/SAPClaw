# API_LEDGER_SRV Skill

## Purpose

Use this API for standalone Ledger master records, ledger lists, ledger names/texts, leading-ledger indicators, and ledger application attributes. Do not route standalone ledger master-data questions to G/L line item APIs. The service enables you to retrieve ledger master data. It contains a header and nodes with business information. You can read ledgers, their properties like leading ledger and their names in the respective language.

Keep `data/index/API_LEDGER_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about ledger - read or the business objects exposed by this service: A Ledger, A Ledger Text.
- Use this API for standalone ledger master data questions such as "ledger records", "list ledgers", "ledger names", "leading ledger", "ledger application", or "ledger text".
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_LEDGER_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_Ledger`: Reads the items of all ledgers.. Methods: GET. runtime metadata available.
- `A_LedgerText`: Reads the texts of all ledgers.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Ledger - Read.
- Use the service description, entity descriptions, and field descriptions from `data/index/API_LEDGER_SRV` to infer user intent.
- `A_Ledger` is for ledger master records and indicators such as `A_Ledger.Ledger`, `A_Ledger.IsLeadingLedger`, `A_Ledger.LedgerApplication`, and `A_Ledger.LedgerSubApplication`.
- `A_LedgerText` is for ledger names/texts such as `A_LedgerText.LedgerName`.
- Do not route standalone ledger master data questions to G/L line item APIs merely because line items contain a Ledger field.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For wording such as "general ledger line items", "G/L account line items", or "journal entry line items", do not use `API_LEDGER_SRV`; use `API_GLACCOUNTLINEITEM` for broad line-item detail unless the user asks for ledger master records, ledger names, leading ledger flags, ledger application, or ledger text.
- For broad "ledger records with main identifying details" requests, prefer `A_LedgerText` and select `A_LedgerText.Language`, `A_LedgerText.Ledger`, and `A_LedgerText.LedgerName`, because the human-readable ledger name is part of the identifying details. If the user asks in English and gives no language, use `A_LedgerText.Language eq 'EN'` to avoid returning duplicate ledger names across all maintained languages.
- Use `A_Ledger` when the user specifically asks for leading-ledger flags, ledger application, or ledger sub-application attributes.

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

- Verify entity and field availability against `data/index/API_LEDGER_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
