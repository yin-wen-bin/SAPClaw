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
- Prefer this API for G/L account activity detail, open item, cleared item, and clearing-status questions. Chinese wording such as `总账科目...发生明细`, `总账科目的未清项目`, `还没有清账的项目`, `已清项目`, or `清账日期` should stay on `GLAccountLineItem` because this service exposes `PostingDate` and `ClearingDate`.
- When a user combines G/L account balance wording with open-item wording, such as `科目...余额` plus `未清项目日期`, treat it as an open-item balance as of a key date, not as a trial balance request.
- For balance drilldown wording such as `余额下钻`, `从余额下钻查看凭证明细`, or `drill down from G/L account balance to line items`, use companion API `C_TRIALBALANCE_CDS` with `API_GLACCOUNTLINEITEM`: first establish the balance scope, then query `GLAccountLineItem` for the underlying accounting document line items.
- Do not use this API for standalone ledger master data, ledger names, or ledger configuration records. Route those requests to `API_LEDGER_SRV` when available.
- Do not use this API for accounting exception queries such as `手工凭证`, `凭证类型`, `过账用户`, or `大额总账项目`; route those to `API_OPLACCTGDOCITEMCUBE_SRV`, which exposes accounting document type, creator, and amount fields for operational accounting items.
- For wording such as "include", "show fields", or "with ... details", treat named concepts as `$select` fields, not as filters. Do not invent placeholder filters for fields such as `GLAccountLineItem.AccountingDocCreatedByUser` unless the user supplies a concrete user name.
- For created-by-user, account assignment, reference document, service document, clearing, amount, quantity, and organization questions, keep the query on `GLAccountLineItem` and select the requested fields.
- `GLAccountLineItem.ID` is not a sufficient stable business key across different analytical `$select` dimensions. For record/list outputs, keep stable row-identifying dimensions in `$select`: `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, and `GLAccountLineItem.GLAccount`.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Balance Drilldown

- For balance drilldown wording such as `余额下钻`, `从余额下钻查看凭证明细`, or `drill down from G/L account balance to line items`, use companion API `C_TRIALBALANCE_CDS` with `API_GLACCOUNTLINEITEM`: first establish the balance scope, then query `GLAccountLineItem` for the underlying accounting document line items.

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Line Item Field Lists

- For Chinese wording such as `总账行项目清单`, select only `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`.
- For Chinese wording such as `主导ledger的总账行项目`, first resolve the leading ledger with `API_LEDGER_SRV.A_Ledger.IsLeadingLedger eq true`, then query `GLAccountLineItem` and select only `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`.
- For broad "list G/L account line item records" requests, select `GLAccountLineItem.ID`, `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.LedgerFiscalYear`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.PostingDate`, `GLAccountLineItem.DocumentDate`, and fields needed by the user request.
- For broad "main identifying details" requests, do not add optional dimensions such as `GLAccountLineItem.AccountingDocCreatedByUser`, `GLAccountLineItem.LedgerGLLineItem`, `GLAccountLineItem.GLRecordType`, `GLAccountLineItem.ControllingArea`, `GLAccountLineItem.DebitCreditCode`, or `GLAccountLineItem.DocumentItemText` unless the user explicitly asks for them. Extra analytical dimensions change result granularity and total counts.
- If the user asks for `AccountingDocCreatedByUser` without providing a user value, select `GLAccountLineItem.AccountingDocCreatedByUser`; do not add a filter with a placeholder value.
- When the user asks for clearing, amount, quantity, assignment, reference, service document, customer, supplier, company code, controlling area, cost center, profit center, or distribution channel details, select those fields on `GLAccountLineItem` and keep the stable row-identifying dimensions listed above.
- For Chinese open item wording such as `未清项目`, `还没有清账`, `尚未清账`, or `没有清账`, select only `GLAccountLineItem.ID`, `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.PostingDate`, `GLAccountLineItem.ClearingDate`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`; filter `GLAccountLineItem.ClearingDate eq null`. If the user provides a key date such as `截至2024年12月31日`, also filter `GLAccountLineItem.PostingDate le <user_date>`. For stable paged results, order_by: `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.PostingDate`.
- For open item / not cleared wording such as `未清项目`, `还没有清账`, `尚未清账`, `open items`, or `not cleared`, do not filter `GLAccountLineItem.LineItemIsCompleted` unless the user explicitly asks for line item completion status.
- For open item / not cleared wording (`未清项目`, `还没有清账`, `open items`, `not cleared`), filter `GLAccountLineItem.ClearingDate eq null`. If the user provides a key date such as `截至2024年12月31日`, also filter `GLAccountLineItem.PostingDate le datetime'<date>T23:59:59'`.
- For Chinese open-item balance wording such as `科目...余额` with `未清项目日期`, `未清项目余额`, or `open item balance`, select only `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.CompanyCodeCurrency`, `GLAccountLineItem.PostingDate`, `GLAccountLineItem.ClearingDate`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`; filter `GLAccountLineItem.ClearingDate eq null` and `GLAccountLineItem.PostingDate le <user_date>` when the user provides a key date such as `今天`, `today`, or `截至2024年12月31日`; result_transform: aggregate; group_by: `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.CompanyCodeCurrency`; sum_fields: `GLAccountLineItem.AmountInCompanyCodeCurrency`.
- For wording `未清项目日期`, `open item date`, or `key date`, do not filter `GLAccountLineItem.ClearingDate eq <user_date>`; use `GLAccountLineItem.ClearingDate eq null` plus `GLAccountLineItem.PostingDate le <user_date>`.
- For cleared item wording (`已清项目`, `已经清账`, `cleared items`), select only `GLAccountLineItem.ID`, `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.PostingDate`, `GLAccountLineItem.ClearingDate`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`; filter `GLAccountLineItem.ClearingDate ne null`. If the user provides a clearing year such as `2024年`, filter `GLAccountLineItem.ClearingDate ge <user_year_start>` and `GLAccountLineItem.ClearingDate le <user_year_end>`. If the user provides a clearing date or range, apply it to `GLAccountLineItem.ClearingDate`. For stable paged results, order_by: `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.PostingDate`.
- For cleared item wording (`已清项目`, `已经清账`, `cleared items`), do not filter `GLAccountLineItem.FiscalYear` unless the user explicitly asks for accounting year, fiscal year, or `会计年度`.
- For Chinese wording such as `总账科目...按成本中心和利润中心归集的费用明细`, select only `GLAccountLineItem.ID`, `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.AccountingDocumentItem`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.CostCenter`, `GLAccountLineItem.ProfitCenter`, `GLAccountLineItem.PostingDate`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`; filter `GLAccountLineItem.CostCenter ne ''`; result_transform: aggregate; group_by: `GLAccountLineItem.CostCenter`, `GLAccountLineItem.ProfitCenter`; sum_fields: `GLAccountLineItem.AmountInCompanyCodeCurrency`.
- For Chinese wording such as `成本中心相关的总账行项目`, select only `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.CostCenter`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`, and add filter `GLAccountLineItem.CostCenter ne ''`.
- For Chinese wording such as `利润中心相关的总账行项目`, select only `GLAccountLineItem.CompanyCode`, `GLAccountLineItem.FiscalYear`, `GLAccountLineItem.AccountingDocument`, `GLAccountLineItem.Ledger`, `GLAccountLineItem.GLAccount`, `GLAccountLineItem.ProfitCenter`, and `GLAccountLineItem.AmountInCompanyCodeCurrency`, and add filter `GLAccountLineItem.ProfitCenter ne ''`.

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
