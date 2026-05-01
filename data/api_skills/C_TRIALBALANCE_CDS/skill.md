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
- Use `C_TRIALBALANCEResults` for user questions about trial balance rows, G/L account balances, debit amounts, credit amounts, ending balances, and balance sheet account indicators.
- `Ledger`, `CompanyCode`, and `GLAccount` are valid selectable/filterable fields on `C_TRIALBALANCEResults`. If the user supplies ledger and company code, apply both filters directly on `C_TRIALBALANCEResults`.
- Trial balance amount fields on `C_TRIALBALANCEResults` include `StartingBalanceAmtInCoCodeCrcy`, `DebitAmountInCoCodeCrcy`, `CreditAmountInCoCodeCrcy`, and `EndingBalanceAmtInCoCodeCrcy`. These fields are selectable result measures; do not reject a plan just because they are not filter fields.
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

- For "trial balance" or "G/L account balance" questions, prefer a direct query on `C_TRIALBALANCEResults`.
- If the user provides company code and ledger, use filters such as `CompanyCode eq '1710'` and `Ledger eq '0L'`.
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
