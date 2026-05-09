# API_PROFITCENTER_SRV Skill

## Purpose

Use this API for Profit Center - Read (A2X). This service enables you to read profit center master data in an API call. It is based on the OData protocol and can be consumed in SAP Fiori apps and other user interfaces.

Keep `data/index/API_PROFITCENTER_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about profit center - read (a2x) or the business objects exposed by this service: A Prft Ctr Company Code Assignment, A Profit Center, A Profit Center Text.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_PROFITCENTER_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_PrftCtrCompanyCodeAssignment`: Reads company code assignments for all profit centers.. Methods: GET. runtime metadata available.
- `A_ProfitCenter`: Reads all available profit centers.. Methods: GET. runtime metadata available.
- `A_ProfitCenterText`: Reads all language-dependent fields for all profit centers.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Profit Center - Read (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_PROFITCENTER_SRV` to infer user intent.
- Use `A_PrftCtrCompanyCodeAssignment` for company-code to profit-center assignment lists. Use `A_ProfitCenterText` only when the user explicitly asks for names, descriptions, text, or a specific language.
- Do not infer `Language eq 'ZH'` just because the user asks in Chinese. Add a language filter only when the requested output is language-dependent; for "English name" use `A_ProfitCenterText.Language eq 'EN'`.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Company And Cost Center Mapping

- For wording such as "公司1710利润中心的英文名称", query `A_PrftCtrCompanyCodeAssignment` first by `A_PrftCtrCompanyCodeAssignment.CompanyCode`, then query `A_ProfitCenterText` by `ProfitCenter` binding with `A_ProfitCenterText.Language eq 'EN'`.
- For wording such as "公司1710分配了哪些利润中心" or "profit centers assigned to company 1710", query `A_PrftCtrCompanyCodeAssignment` by `A_PrftCtrCompanyCodeAssignment.CompanyCode` and select only `A_PrftCtrCompanyCodeAssignment.ControllingArea`, `A_PrftCtrCompanyCodeAssignment.ProfitCenter`, and `A_PrftCtrCompanyCodeAssignment.CompanyCode`. Do not query `A_ProfitCenterText` unless the user asks for profit center names, descriptions, or text.
- For wording such as "公司1710被冻结的利润中心", "blocked profit centers", or "frozen profit centers", query `A_ProfitCenter`, filter `A_ProfitCenter.CompanyCode` and `A_ProfitCenter.ProfitCenterIsBlocked eq 'X'`, and select only `A_ProfitCenter.ControllingArea`, `A_ProfitCenter.ProfitCenter`, `A_ProfitCenter.CompanyCode`, and `A_ProfitCenter.ProfitCenterIsBlocked`.
- For wording such as "公司1710利润中心负责人信息", Step 1 query `A_PrftCtrCompanyCodeAssignment` by `A_PrftCtrCompanyCodeAssignment.CompanyCode` and select only `A_PrftCtrCompanyCodeAssignment.ControllingArea`, `A_PrftCtrCompanyCodeAssignment.ProfitCenter`, and `A_PrftCtrCompanyCodeAssignment.CompanyCode`; Step 2 query `A_ProfitCenter` by `ProfitCenter` binding only, not by `ControllingArea`, and select only `A_ProfitCenter.ControllingArea`, `A_ProfitCenter.ProfitCenter`, `A_ProfitCenter.ProfitCtrResponsiblePersonName`, and `A_ProfitCenter.ProfitCtrResponsibleUser`.
- For wording such as "公司1710利润中心的标准层级", Step 1 query `A_PrftCtrCompanyCodeAssignment` by `A_PrftCtrCompanyCodeAssignment.CompanyCode` and select only `A_PrftCtrCompanyCodeAssignment.ControllingArea`, `A_PrftCtrCompanyCodeAssignment.ProfitCenter`, and `A_PrftCtrCompanyCodeAssignment.CompanyCode`; Step 2 query `A_ProfitCenter` by `ProfitCenter` binding only, not by `ControllingArea`, and select only `A_ProfitCenter.ControllingArea`, `A_ProfitCenter.ProfitCenter`, and `A_ProfitCenter.ProfitCenterStandardHierarchy`.
- For wording such as "成本中心对应的利润中心", "成本中心关联利润中心", or "cost center profit center mapping", use `API_COSTCENTER_SRV.A_CostCenter.ProfitCenter` as the mapping source, then use `A_ProfitCenterText` only if the user asks for profit center names.
- Do not ask whether the user wants all profit centers or a specific cost center when the wording includes a company code and "成本中心对应利润中心"; the natural meaning is a list mapping for that company.

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

- Verify entity and field availability against `data/index/API_PROFITCENTER_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
