# API_OPLACCTGDOCITEMCUBE_SRV Skill

## Purpose

Use this API for Accounting Document - Read (A2X); `A_OperationalAcctgDocItemCube` directly includes `AccountsReceivableIsPledged`, `CashDiscount1Days`, `CashDiscount1DueDate`, and `CashDiscount1Percent`. This service is based on the OData protocol and can be consumed in Fiori apps and on other user interfaces.

This service only extracts journal entries with an entry view and is not designed to extract large data volumes. It contains the operational accounting document header and item nodes.

Keep `data/index/API_OPLACCTGDOCITEMCUBE_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about accounting document - read (a2x) or the business objects exposed by this service: A Operational Acctg Doc Item Cube.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_OPLACCTGDOCITEMCUBE_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_OperationalAcctgDocItemCube`: Get entities from A_OperationalAcctgDocItemCube. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Accounting Document - Read (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_OPLACCTGDOCITEMCUBE_SRV` to infer user intent.
- Use `A_OperationalAcctgDocItemCube` for AP/AR aging, overdue, due-date, payment-term, payment-block, and operational accounting item questions. This entity exposes `Supplier`, `SupplierName`, `Customer`, `CustomerName`, `ClearingDate`, `IsCleared`, `NetDueDate`, `DueCalculationBaseDate`, `PaymentTerms`, `PaymentBlockingReason`, `SpecialGLCode`, `ProfitCenter`, and amount fields.
- For supplier payable aging or overdue questions, filter `Supplier` when provided, `CompanyCode` when provided, open items with `ClearingDate eq null` or `IsCleared eq false` when available, and compare `NetDueDate` to the key date.
- For customer receivable aging or overdue questions, filter `Customer` when provided, `CompanyCode` when provided, open items with `ClearingDate eq null` or `IsCleared eq false` when available, and compare `NetDueDate` to the key date.
- For due-soon payment questions, use a `NetDueDate ge <start>` and `NetDueDate le <end>` range; select supplier/customer, due date, payment terms, amount, currency, accounting document, and clearing status fields.
- For supplier payable due-date wording such as `到期的应付项目`, `即将到期的应付项目`, `未来...到期的付款`, or `Net due`, `NetDueDate` is the due-date field in `A_OperationalAcctgDocItemCube`. Do not ask whether the schema supports a due-date field when `NetDueDate` is available in the index.
- For payment-blocked invoice or item questions, select and filter `PaymentBlockingReason`; use `PaymentBlockingReason ne ''` when the user asks for all blocked items.
- For AP/AR reconciliation wording such as `核对应付账龄和供应商未清行项目` or `核对应收账龄和客户未清行项目`, use this API together with companion API `API_GLACCOUNTLINEITEM`: this API supplies due-date/aging measures, and `API_GLACCOUNTLINEITEM` supplies the line-item detail side.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For Chinese wording such as `运营会计凭证项目`, select only `A_OperationalAcctgDocItemCube.CompanyCode`, `A_OperationalAcctgDocItemCube.FiscalYear`, `A_OperationalAcctgDocItemCube.AccountingDocument`, `A_OperationalAcctgDocItemCube.AccountingDocumentItem`, `A_OperationalAcctgDocItemCube.GLAccount`, `A_OperationalAcctgDocItemCube.CostCenter`, `A_OperationalAcctgDocItemCube.ProfitCenter`, and `A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency`. Do not drop `GLAccount` because it is part of the normal accounting item context.
- For Chinese wording such as `成本中心的运营会计项目`, select only `A_OperationalAcctgDocItemCube.CompanyCode`, `A_OperationalAcctgDocItemCube.FiscalYear`, `A_OperationalAcctgDocItemCube.AccountingDocument`, `A_OperationalAcctgDocItemCube.AccountingDocumentItem`, `A_OperationalAcctgDocItemCube.GLAccount`, `A_OperationalAcctgDocItemCube.CostCenter`, `A_OperationalAcctgDocItemCube.ProfitCenter`, and `A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency`, and add filter `A_OperationalAcctgDocItemCube.CostCenter ne ''`. Do not add `FiscalYear` or date filters unless the user explicitly provides a year, period, or date.
- For Chinese wording such as `利润中心的运营会计项目`, select only `A_OperationalAcctgDocItemCube.CompanyCode`, `A_OperationalAcctgDocItemCube.FiscalYear`, `A_OperationalAcctgDocItemCube.AccountingDocument`, `A_OperationalAcctgDocItemCube.AccountingDocumentItem`, `A_OperationalAcctgDocItemCube.GLAccount`, `A_OperationalAcctgDocItemCube.CostCenter`, `A_OperationalAcctgDocItemCube.ProfitCenter`, and `A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency`, and add filter `A_OperationalAcctgDocItemCube.ProfitCenter ne ''`. Do not add `FiscalYear` or date filters unless the user explicitly provides a year, period, or date.
- For Chinese wording such as `手工凭证产生且金额超过10000的大额总账项目`, select only `A_OperationalAcctgDocItemCube.CompanyCode`, `A_OperationalAcctgDocItemCube.FiscalYear`, `A_OperationalAcctgDocItemCube.AccountingDocument`, `A_OperationalAcctgDocItemCube.AccountingDocumentItem`, `A_OperationalAcctgDocItemCube.GLAccount`, `A_OperationalAcctgDocItemCube.PostingDate`, `A_OperationalAcctgDocItemCube.AccountingDocumentType`, `A_OperationalAcctgDocItemCube.AccountingDocCreatedByUser`, and `A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency`; filter `A_OperationalAcctgDocItemCube.AccountingDocumentType eq 'SA'`, `A_OperationalAcctgDocItemCube.FiscalYear eq <user_year>`, and `A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency ge <user_amount>`.
- For operational accounting document item cube requests about pledged receivables and cash discount terms, use `A_OperationalAcctgDocItemCube` and select `A_OperationalAcctgDocItemCube.AccountsReceivableIsPledged`, `A_OperationalAcctgDocItemCube.CashDiscount1Days`, `A_OperationalAcctgDocItemCube.CashDiscount1DueDate`, and `A_OperationalAcctgDocItemCube.CashDiscount1Percent` directly. Do not ask for clarification merely because these fields are not in `top_filter_fields`.
- For AP/AR aging list outputs, keep `$select` focused on `CompanyCode`, `FiscalYear`, `AccountingDocument`, `AccountingDocumentItem`, `Supplier` or `Customer`, `GLAccount`, `PostingDate`, `NetDueDate`, `ClearingDate`, `IsCleared`, `AmountInCompanyCodeCurrency`, and currency fields available in schema.
- For supplier payable due-date list outputs, select only `A_OperationalAcctgDocItemCube.CompanyCode`, `A_OperationalAcctgDocItemCube.FiscalYear`, `A_OperationalAcctgDocItemCube.AccountingDocument`, `A_OperationalAcctgDocItemCube.AccountingDocumentItem`, `A_OperationalAcctgDocItemCube.Supplier`, `A_OperationalAcctgDocItemCube.SupplierName`, `A_OperationalAcctgDocItemCube.GLAccount`, `A_OperationalAcctgDocItemCube.NetDueDate`, `A_OperationalAcctgDocItemCube.CashDiscount1DueDate`, `A_OperationalAcctgDocItemCube.ClearingDate`, and `A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency`; filter `A_OperationalAcctgDocItemCube.CompanyCode` and `A_OperationalAcctgDocItemCube.Supplier` when provided, filter open items with `A_OperationalAcctgDocItemCube.ClearingDate eq null`, and for wording such as `2026年5月20日前到期` use `A_OperationalAcctgDocItemCube.NetDueDate le datetime'2026-05-20T23:59:59'`.

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

- Verify entity and field availability against `data/index/API_OPLACCTGDOCITEMCUBE_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
