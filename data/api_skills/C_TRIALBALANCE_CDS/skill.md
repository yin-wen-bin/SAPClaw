# C_TRIALBALANCE_CDS Skill

## Purpose

Use this API for The service enables you to retrieve starting, credit and debit balances for G/L accounts per fiscal year period. You can read data for period-based balances. You cannot read data for day-based balances. You need to provide the time frame for the selection in a date format and you need to provide the level of aggregation in a $select clause.. The service enables you to retrieve starting, credit and debit balances for G/L accounts per fiscal year period. You can read data for period-based balances. You cannot read data for day-based balances. You need to provide the time frame for the selection in a date format and you need to provide the level of aggregation in a $select clause.

Keep `data/index/C_TRIALBALANCE_CDS` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about the service enables you to retrieve starting, credit and debit balances for g/l accounts per fiscal year period. you can read data for period-based balances. you cannot read data for day-based balances. you need to provide the time frame for the selection in a date format and you need to provide the level of aggregation in a $select clause. or the business objects exposed by this service: TRIALBALANCE, Chart Of Accounts, Chart Of Accounts Results, Clearing Accounting Document, Clearing Accounting Document Results, Corporate Group Account, Corporate Group Account Results, Corporate Group Chart Of Accounts.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/C_TRIALBALANCE_CDS`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `C_TRIALBALANCE`: Get entities from related Results. Methods: GET.
- `ChartOfAccounts`: Get entities from ChartOfAccounts. Methods: GET.
- `ChartOfAccountsResults`: ChartOfAccountsResult. Methods: GET.
- `ClearingAccountingDocument`: Get entities from ClearingAccountingDocument. Methods: GET.
- `ClearingAccountingDocumentResults`: ClearingAccountingDocumentResult. Methods: GET.
- `CorporateGroupAccount`: Get entities from CorporateGroupAccount. Methods: GET.
- `CorporateGroupAccountResults`: CorporateGroupAccountResult. Methods: GET.
- `CorporateGroupChartOfAccounts`: Get entities from CorporateGroupChartOfAccounts. Methods: GET.
- `CorporateGroupChartOfAccountsResults`: CorporateGroupChartOfAccountsResult. Methods: GET.
- `CountryChartOfAccounts`: Get entities from CountryChartOfAccounts. Methods: GET.
- `CountryChartOfAccountsResults`: CountryChartOfAccountsResult. Methods: GET.
- `C_TRIALBALANCEResults`: Get related LedgerDetails. Methods: GET.

## Business Semantics

- Primary business scope: The service enables you to retrieve starting, credit and debit balances for G/L accounts per fiscal year period. You can read data for period-based balances. You cannot read data for day-based balances. You need to provide the time frame for the selection in a date format and you need to provide the level of aggregation in a $select clause..
- Use the service description, entity descriptions, and field descriptions from `data/index/C_TRIALBALANCE_CDS` to infer user intent.
- Use the parameterized resource path `C_TRIALBALANCE(P_FromPostingDate=datetime'<start>',P_ToPostingDate=datetime'<end>')/Results` for user questions about trial balance rows, G/L account balances, debit amounts, credit amounts, ending balances, and balance sheet account indicators. Validate fields against metadata entity `C_TRIALBALANCEResults`.
- Do not execute `C_TRIALBALANCEResults` as a bare entity set. SAP requires the date parameters on `C_TRIALBALANCE` before navigating to `/Results`.
- Do not use this API when a balance question also asks for open items, clearing status, `未清项目`, `未清项目日期`, `open item date`, or key-date open-item balance. Route those requests to `API_GLACCOUNTLINEITEM` and aggregate `GLAccountLineItem.AmountInCompanyCodeCurrency` after applying open-item filters.
- `Ledger`, `CompanyCode`, and `GLAccount` are valid selectable/filterable fields on `C_TRIALBALANCEResults`. If the user supplies ledger and company code, apply both filters directly on `C_TRIALBALANCEResults`.
- `ProfitCenter`, `ProfitCenterName`, `Segment`, and `SegmentName` are valid trial-balance dimensions on `C_TRIALBALANCEResults`. When the user asks to view trial balance, P&L, or financial statement balances by profit center or segment, select those fields and filter the requested dimension with `ne ''` unless the user provides a concrete value.
- When the user asks for balances under different ledgers, all ledgers, parallel ledgers, or `不同分类账`, do not default to `Ledger eq '0L'`. Select `Ledger` and omit the ledger filter unless the user gives a specific ledger.
- Trial balance amount fields on `C_TRIALBALANCEResults` include `StartingBalanceAmtInCoCodeCrcy`, `DebitAmountInCoCodeCrcy`, `CreditAmountInCoCodeCrcy`, and `EndingBalanceAmtInCoCodeCrcy`. These fields are selectable result measures; do not reject a plan just because they are not filter fields.
- For financial statement or G/L balance drilldown wording such as `下钻`, `凭证明细`, or `行项目`, use this API together with companion API `API_GLACCOUNTLINEITEM`: first establish the trial-balance scope, then query the underlying G/L line items.
- In a trial balance question, "order balances" means balances by the `OrderID` dimension on `C_TRIALBALANCEResults`. Select `OrderID` plus balance amount fields. Do not route this wording to `OrderIDResults` or `IsBalanceSheetAccountResults`.
- `IsBalanceSheetAccount` is a valid selectable/filterable string indicator on `C_TRIALBALANCEResults` for balance sheet account questions.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Trial Balance Rows

- For "trial balance" or "G/L account balance" questions, use `C_TRIALBALANCE(P_FromPostingDate=datetime'<start>',P_ToPostingDate=datetime'<end>')/Results`, with fields and filters validated against `C_TRIALBALANCEResults`.
- For G/L account balance questions that mention open items, clearing status, `未清项目`, `未清项目日期`, `open item date`, or key date, do not plan on `C_TRIALBALANCEResults`; route to `API_GLACCOUNTLINEITEM`.
- If the user provides company code and ledger, use filters such as `CompanyCode eq '1710'` and `Ledger eq '0L'`.
- Do not return `C_TRIALBALANCEResults.ID` as an answer or main output field. It is a generated technical CDS/OData key, not a business identifier.
- If the user asks by profit center, select `Ledger`, `CompanyCode`, `FiscalYear`, `FiscalPeriod`, `GLAccount`, `ProfitCenter`, `ProfitCenterName`, `Segment`, `SegmentName`, and balance amount fields; add `ProfitCenter ne ''` when no concrete profit center is supplied.
- If the user asks by segment, select `Ledger`, `CompanyCode`, `FiscalYear`, `FiscalPeriod`, `GLAccount`, `Segment`, `SegmentName`, and balance amount fields; add `Segment ne ''` when no concrete segment is supplied.
- If the user asks for P&L or `损益金额`, keep the request on `C_TRIALBALANCE_CDS` when the result is a period balance or amount view, and include `IsBalanceSheetAccount` when useful to distinguish balance-sheet vs profit-and-loss accounts.
- If the user gives only a fiscal year such as `2020年`, set `P_FromPostingDate=datetime'2020-01-01T00:00:00'` and `P_ToPostingDate=datetime'2020-12-31T00:00:00'`.
- If the user gives a fiscal period or month, set `P_FromPostingDate` and `P_ToPostingDate` to the corresponding calendar month range, then also filter `FiscalYear` and `FiscalPeriod` when those fields are needed.
- For Chinese wording such as `总账科目...在2023年第12期的期初、借方、贷方和期末余额`, select only `C_TRIALBALANCEResults.Ledger`, `C_TRIALBALANCEResults.CompanyCode`, `C_TRIALBALANCEResults.FiscalYear`, `C_TRIALBALANCEResults.FiscalPeriod`, `C_TRIALBALANCEResults.GLAccount`, `C_TRIALBALANCEResults.StartingBalanceAmtInCoCodeCrcy`, `C_TRIALBALANCEResults.DebitAmountInCoCodeCrcy`, `C_TRIALBALANCEResults.CreditAmountInCoCodeCrcy`, and `C_TRIALBALANCEResults.EndingBalanceAmtInCoCodeCrcy`; filter `C_TRIALBALANCEResults.Ledger eq '0L'`, `C_TRIALBALANCEResults.FiscalYear eq <user_year>`, and `C_TRIALBALANCEResults.FiscalPeriod eq <user_period>` unless the user explicitly provides another ledger.
- `C_TRIALBALANCEResults` requires a concrete `CompanyCode` filter. If the user asks for `各公司代码`, `所有公司代码`, or all company codes without listing explicit company codes, ask for the company-code scope instead of planning an unfiltered trial-balance request.
- For debit/credit amount questions, select `Ledger`, `CompanyCode`, `GLAccount`, `DebitAmountInCoCodeCrcy`, `CreditAmountInCoCodeCrcy`, and an ending balance field such as `EndingBalanceAmtInCoCodeCrcy`.
- For order balance dimension questions, select `Ledger`, `CompanyCode`, `GLAccount`, `OrderID`, and `EndingBalanceAmtInCoCodeCrcy`; include debit/credit fields when the user asks for movements.
- For balance sheet account indicator questions, select `Ledger`, `CompanyCode`, `GLAccount`, `IsBalanceSheetAccount`, and any requested balance fields.
- If the user asks for trial balance but omits company code or ledger, ask a concise clarification instead of selecting an unrelated ledger master-data API.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/C_TRIALBALANCE_CDS` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/C_TRIALBALANCE_CDS` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
