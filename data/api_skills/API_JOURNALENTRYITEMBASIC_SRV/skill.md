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
- Use this API, not `API_GLACCOUNTLINEITEM`, when journal entry item wording asks for master-data names or codes used on journal entry items: company code name, cost center name, profit center name, G/L account name, functional area name, or lists of cost/profit/company codes used by journal entry items.
- Do not use this API merely to answer standalone company code, cost center, or profit center master-data questions; route those to the dedicated master-data APIs. Use this API when the wording anchors those fields to journal entry items, for example "company codes used by journal entry items".
- Do not use this API for broad general ledger line item lists without master-data name requests; route those to `API_GLACCOUNTLINEITEM`.
- Do not use this API for G/L-account open item, cleared item, or clearing-status questions such as `总账科目的未清项目`, `还没有清账的项目`, `已清项目`, or `清账日期`; route those to `API_GLACCOUNTLINEITEM`, which exposes `ClearingDate`.
- Do not use this API for G/L account expense detail requests such as `总账科目...按成本中心和利润中心归集的费用明细`; route those to `API_GLACCOUNTLINEITEM`, which exposes stable G/L account line item dimensions for detail-level comparison.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For broad general ledger line item lists without master-data name requests, do not use `API_JOURNALENTRYITEMBASIC_SRV`; use `API_GLACCOUNTLINEITEM`.

### Journal Entry Item Master References

- `A_JournalEntryItemBasic` is an analytical service: optional dimensions in `$select` change aggregation grain and total counts. For list/count comparisons, select only fields needed by the user's wording plus stable identifiers.
- For wording such as "journal entry line item IDs with company code, cost center, and profit center names", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.CompanyCodeName`, `A_JournalEntryItemBasic.CostCenter`, `A_JournalEntryItemBasic.CostCenterName`, `A_JournalEntryItemBasic.ProfitCenter`, and `A_JournalEntryItemBasic.ProfitCenterName`.
- For wording such as "company code and company code name for journal entry line items", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, and `A_JournalEntryItemBasic.CompanyCodeName`.
- For wording such as "cost centers used by journal entry line items" or "cost center names used by journal entry items", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CostCenter`, `A_JournalEntryItemBasic.CostCenterName`, `A_JournalEntryItemBasic.ControllingArea`, and `A_JournalEntryItemBasic.CompanyCode`. Do not add `A_JournalEntryItemBasic.CostCenter ne ''` for broad list requests because this analytical service can time out on that non-blank filter.
- For Chinese wording such as `日记账行项目和对应科目金额`, select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and `A_JournalEntryItemBasic.CompanyCodeCurrency`. Do not add ledger, cost center, profit center, functional area, or name dimensions unless explicitly requested.
- For Chinese wording such as `科目10010000的日记账行项目` or company-and-G/L-account journal item requests, select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.GLAccount`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`. Do not add ledger, cost center, profit center, functional area, or name dimensions unless explicitly requested.
- For "company code names used by journal entry items", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, and `A_JournalEntryItemBasic.CompanyCodeName`.
- For Chinese wording such as "职能范围", "功能范围", or English "functional area" on financial/journal line items, use `A_JournalEntryItemBasic.FunctionalArea` and `A_JournalEntryItemBasic.FunctionalAreaName`. Do not ask whether the user meant cost center or profit center unless the wording explicitly says cost center/profit center.
- For wording such as "带职能范围的财务行项目", "有职能范围的财务行项目", or "line items with functional area", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.FunctionalArea`, and `A_JournalEntryItemBasic.FunctionalAreaName`, and add filter `A_JournalEntryItemBasic.FunctionalArea ne ''` so blank functional-area rows are excluded. This is an explicit business condition, not merely an output-field request. Do not add ledger, cost center, profit center, or amount fields unless the user explicitly asks for them because extra dimensions can change the row count on this analytical service.
- For wording such as "带成本中心的财务行项目", "有成本中心的日记账行项目", or "line items with cost center", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.CostCenter`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and add filter `A_JournalEntryItemBasic.CostCenter ne ''`.
- For wording such as "成本中心上的财务行项目" or "financial line items on cost centers", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.CostCenter`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and add filter `A_JournalEntryItemBasic.CostCenter ne ''`.
- For wording such as "带利润中心的财务行项目", "有利润中心的日记账行项目", or "line items with profit center", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.ProfitCenter`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and add filter `A_JournalEntryItemBasic.ProfitCenter ne ''`.
- For wording such as "利润中心上的财务行项目" or "financial line items on profit centers", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.GLAccount`, `A_JournalEntryItemBasic.ProfitCenter`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and add filter `A_JournalEntryItemBasic.ProfitCenter ne ''`.
- For wording such as "带客户信息的财务行项目", "有客户的日记账行项目", or "line items with customer", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.Customer`, `A_JournalEntryItemBasic.CustomerName`, `A_JournalEntryItemBasic.GLAccount`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and add filter `A_JournalEntryItemBasic.Customer ne ''`.
- For wording such as "带工厂信息的财务行项目", "有工厂的日记账行项目", or "line items with plant", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.Plant`, `A_JournalEntryItemBasic.PlantName`, `A_JournalEntryItemBasic.GLAccount`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and add filter `A_JournalEntryItemBasic.Plant ne ''`.
- For wording such as "会计期间2016.012的日记账行项目" or "journal entry items for fiscal year period 2016.012", select only `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CompanyCode`, `A_JournalEntryItemBasic.FiscalYearPeriod`, `A_JournalEntryItemBasic.GLAccount`, and `A_JournalEntryItemBasic.AmountInCompanyCodeCurrency`, and filter `A_JournalEntryItemBasic.FiscalYearPeriod eq '<period>'` using the period value provided by the user.
- For "cost center names used by journal entry items", select `A_JournalEntryItemBasic.ID`, `A_JournalEntryItemBasic.CostCenter`, `A_JournalEntryItemBasic.CostCenterName`, `A_JournalEntryItemBasic.ControllingArea`, and `A_JournalEntryItemBasic.CompanyCode`; do not add a non-blank `CostCenter` filter unless the user explicitly requests non-blank cost centers.
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
