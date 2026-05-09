# API_GLACCOUNTINCHARTOFACCOUNTS_SRV Skill

## Purpose

Use this API for G/L Account - Read. The service enables you to retrieve G/L account master data. It contains a header and nodes with business information. You can read G/L accounts in a chart of accounts and their names in the respective language.

Keep `data/index/API_GLACCOUNTINCHARTOFACCOUNTS_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about g/l account - read or the business objects exposed by this service: A GLAccount In Chart Of Accounts, A GLAccount Text.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_GLACCOUNTINCHARTOFACCOUNTS_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_GLAccountInChartOfAccounts`: Reads the items of all G/L accounts.. Methods: GET. runtime metadata available.
- `A_GLAccountText`: Reads the texts of all G/L accounts.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: G/L Account - Read.
- Use the service description, entity descriptions, and field descriptions from `data/index/API_GLACCOUNTINCHARTOFACCOUNTS_SRV` to infer user intent.
- Use `A_GLAccountInChartOfAccounts` for G/L account master attributes, chart of accounts assignments, account groups, balance sheet/profit-and-loss account type, creation/change dates, and blocking/deletion indicators.
- Use `A_GLAccountText` when the user asks for G/L account names, long names, descriptions, or language-dependent text. If the user asks for English names, filtering by language is acceptable, but do not require the language field in the output unless requested.
- Do not use this API for the standalone question "which chart of accounts is assigned to company code 1710"; that is a company code master-data attribute on `API_COMPANYCODE_SRV.A_CompanyCode.ChartOfAccounts`.
- For wording such as "include blocking indicators" or "show deletion indicators", select `A_GLAccountInChartOfAccounts.AccountIsBlockedForCreation`, `A_GLAccountInChartOfAccounts.AccountIsBlockedForPlanning`, `A_GLAccountInChartOfAccounts.AccountIsBlockedForPosting`, and `A_GLAccountInChartOfAccounts.AccountIsMarkedForDeletion`. Do not convert the request into filters unless the user asks for blocked-only or deleted-only accounts.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### G/L Account Text And Indicators

- For G/L account names or long names, query `A_GLAccountText` and select `A_GLAccountText.ChartOfAccounts`, `A_GLAccountText.GLAccount`, `A_GLAccountText.GLAccountName`, and `A_GLAccountText.GLAccountLongName`.
- For account creation/change dates or blocking/deletion indicators, query `A_GLAccountInChartOfAccounts`.
- Treat indicator-field wording as an output request unless the user provides explicit filter values.
- For sample G/L account relationship questions, including Chinese wording such as `样本科目关系`, keep the final answer on `A_GLAccountInChartOfAccounts` and select `A_GLAccountInChartOfAccounts.SampleGLAccount`. A relationship exists only when `SampleGLAccount` is not blank, so filter `SampleGLAccount ne ''` when the user asks for sample-account relationships. Do not switch the final answer to `A_GLAccountText` unless `SampleGLAccount` remains selected in the final result.

### Company-Code Scoped G/L Account Lookup

- Use this pattern only when the user asks for G/L account records under a company code, such as expense accounts or P&L accounts. Do not use it when the requested answer is only the assigned chart of accounts for the company code.
- This API is chart-of-accounts scoped, not company-code scoped. If the user provides a company code such as `1710`, use `API_COMPANYCODE_SRV.A_CompanyCode` first to retrieve `ChartOfAccounts`, then bind that value to `API_GLACCOUNTINCHARTOFACCOUNTS_SRV.A_GLAccountInChartOfAccounts.ChartOfAccounts`.
- For Chinese wording such as `公司1710科目表下...`, the number after `公司` is a company code, not the chart of accounts value. Do not filter `A_GLAccountInChartOfAccounts.ChartOfAccounts eq '1710'`; first query `API_COMPANYCODE_SRV.A_CompanyCode` with `CompanyCode eq '1710'` and bind the returned `ChartOfAccounts`.
- For Chinese wording such as `损益类科目`, `利润表科目`, `费用类科目`, `费用科目`, `expense accounts`, or similar P&L account requests, filter `A_GLAccountInChartOfAccounts.IsProfitLossAccount eq true` and select `ProfitLossAccountType`, `GLAccountType`, `IsProfitLossAccount`, and `GLAccount` so the result remains auditable. Do not use `GLAccountType eq 'X'` as a blind rule.
- If account names are requested, add a final text step against `A_GLAccountText` by binding `ChartOfAccounts` and `GLAccount`; filter `Language` only when the user requests a specific language.

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

- Verify entity and field availability against `data/index/API_GLACCOUNTINCHARTOFACCOUNTS_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
