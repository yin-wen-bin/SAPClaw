# API_JOURNALENTRYITEMBASIC_SRV Skill

## Purpose

Use this API for Journal Entry Item - Read (A2X). The service contains journal entry items and master data of the referenced company code, cost center, profit center. This API call is based on the OData protocol, and can be consumed in Fiori apps and on other user interfaces

Keep `data/index/API_JOURNALENTRYITEMBASIC_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about journal entry item - read (a2x) or the business objects exposed by this service: A Company Code, A Cost Center, A GLAccount In Chart Of Accounts, A Journal Entry Item Basic, A Profit Center.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_JOURNALENTRYITEMBASIC_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_CompanyCode`: Reads the items of all company codes.. Methods: GET. runtime metadata available.
- `A_CostCenter`: Reads the items of all cost centers.. Methods: GET. runtime metadata available.
- `A_GLAccountInChartOfAccounts`: Reads the items of all chart of accounts.. Methods: GET. runtime metadata available.
- `A_JournalEntryItemBasic`: Reads universal journal entry items.. Methods: GET. runtime metadata available.
- `A_ProfitCenter`: Reads the items of all profit centers.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Journal Entry Item - Read (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_JOURNALENTRYITEMBASIC_SRV` to infer user intent.
- Use `A_JournalEntryItemBasic` when the user asks for journal entry item records or for company code, cost center, profit center, controlling area, ledger, G/L account, amount, or name fields as they appear on journal entry items.
- Do not use this API merely to answer standalone company code, cost center, or profit center master-data questions; route those to the dedicated master-data APIs. Use this API when the wording anchors those fields to journal entry items, for example "company codes used by journal entry items".
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Journal Entry Item Master References

- For "company code names used by journal entry items", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, and `A_JournalEntryItemBasic.CompanyCodeName`.
- For "cost center names used by journal entry items", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CostCenter`, `A_JournalEntryItemBasic.CostCenterName`, `A_JournalEntryItemBasic.ControllingArea`, and `A_JournalEntryItemBasic.CompanyCode`.
- For "profit center names used by journal entry items", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.ProfitCenter`, `A_JournalEntryItemBasic.ProfitCenterName`, `A_JournalEntryItemBasic.ControllingArea`, and `A_JournalEntryItemBasic.CompanyCode`.
- For "G/L account name and company code name on journal entry item basic records", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.GLAccountName`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.CompanyCodeName`, `A_JournalEntryItemBasic.Ledger`, and `A_JournalEntryItemBasic.LedgerName`.
- For "company code name and controlling area name on journal entry item records", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.Ledger`, `A_JournalEntryItemBasic.LedgerName`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.CompanyCodeName`, `A_JournalEntryItemBasic.ControllingArea`, `A_JournalEntryItemBasic.ControllingAreaName`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.GLAccountName`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`.
- For "cost center, cost center name, and company code context on journal entry item records", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.CompanyCodeName`, `A_JournalEntryItemBasic.CostCenter`, `A_JournalEntryItemBasic.CostCenterName`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.Ledger`, and `A_JournalEntryItemBasic.ControllingArea`.

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

- Verify entity and field availability against `data/index/API_JOURNALENTRYITEMBASIC_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
