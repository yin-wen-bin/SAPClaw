# API_COSTCENTER_SRV Skill

## Purpose

Use this API for Cost Center - Read (A2X). This service enables you to read cost center master data. It is based on the OData protocol and can be consumed in SAP Fiori apps and other user interfaces.

Keep `data/index/API_COSTCENTER_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about cost center - read (a2x) or the business objects exposed by this service: A Cost Center, A Cost Center Text.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_COSTCENTER_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_CostCenter`: Reads all available cost centers.. Methods: GET. runtime metadata available.
- `A_CostCenterText`: Reads all language-dependent fields for all cost centers.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Cost Center - Read (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_COSTCENTER_SRV` to infer user intent.
- Use `A_CostCenter` for cost center master-data fields, organizational assignments, validity dates, responsible persons, currencies, and posting-control indicators.
- Use `A_CostCenterText` only when the user explicitly asks for language-dependent cost center names, descriptions, or text records.
- Cost center posting block and quantity-recording indicator questions map to selectable string indicator fields on `A_CostCenter`: `A_CostCenter.ConsumptionQtyIsRecorded`, `A_CostCenter.IsBlkdForPrimaryCostsPosting`, `A_CostCenter.IsBlkdForSecondaryCostsPosting`, and `A_CostCenter.IsBlockedForCommitmentPosting`. When the user asks to include these indicators, select them; do not convert the request into filters unless the user asks for blocked-only or indicator-specific records.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For generic cost center master list wording such as `Show cost center records with their main identifying details`, use `A_CostCenter` directly. Select `ControllingArea`, `CostCenter`, `ValidityEndDate`, `ValidityStartDate`, `CompanyCode`, and useful master attributes. Do not query `A_CostCenterText` unless the user explicitly asks for name, text, description, or language-specific labels.
- If a plan uses `A_CostCenterText` after `A_CostCenter`, the source step must select every binding key needed by the text step, especially `ControllingArea`, `CostCenter`, and `ValidityEndDate` when that field is part of the target key or binding.

### Cost Center Indicators

- For "posting block", "blocked for posting", or "quantity recording" questions, query `A_CostCenter`.
- Select the cost center identifiers plus the requested indicator fields, especially `A_CostCenter.ConsumptionQtyIsRecorded`, `A_CostCenter.IsBlkdForPrimaryCostsPosting`, `A_CostCenter.IsBlkdForSecondaryCostsPosting`, and `A_CostCenter.IsBlockedForCommitmentPosting`.
- Treat these fields as output indicators for "include/show indicators" wording. Use filters only for wording such as "blocked cost centers" or "where quantity recording is active".
- For wording such as "禁止初级成本过账的成本中心" or "blocked for primary cost posting", query `A_CostCenter`, filter `A_CostCenter.IsBlkdForPrimaryCostsPosting eq 'X'`, and select only `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, `A_CostCenter.CompanyCode`, and `A_CostCenter.IsBlkdForPrimaryCostsPosting`. Do not query `A_CostCenterText` unless the user asks for names or descriptions.
- For wording such as "禁止次级成本过账的成本中心" or "blocked for secondary cost posting", query `A_CostCenter`, filter `A_CostCenter.IsBlkdForSecondaryCostsPosting eq 'X'`, and select only `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, `A_CostCenter.CompanyCode`, and `A_CostCenter.IsBlkdForSecondaryCostsPosting`. Do not query `A_CostCenterText` unless the user asks for names or descriptions.

### Cost Center Currency

- For wording such as "公司1710成本中心使用的货币" or "cost center currency for company 1710", query `A_CostCenter` by `A_CostCenter.CompanyCode` and select only `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, `A_CostCenter.CompanyCode`, and `A_CostCenter.CostCenterCurrency`.
- Do not answer cost center currency from `API_COMPANYCODE_SRV.A_CompanyCode.Currency`; company-code currency is not the same as the currency maintained on each cost center.

### Cost Center Master Attributes

- For wording such as `Show cost center records with city name and responsible person name`, query `A_CostCenter` directly and select `ControllingArea`, `CostCenter`, `ValidityEndDate`, `CityName`, `CostCtrResponsiblePersonName`, `ValidityStartDate`, and `CompanyCode`. Do not replace `CityName` or `CostCtrResponsiblePersonName` with currency or company-code-only fields.

- For wording such as "公司1710成本中心的标准层级区域", query `A_CostCenter` by `A_CostCenter.CompanyCode` and select only `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, `A_CostCenter.CompanyCode`, and `A_CostCenter.CostCenterStandardHierArea`.
- For wording such as "公司1710成本中心类别", query `A_CostCenter` by `A_CostCenter.CompanyCode` and select only `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, `A_CostCenter.CompanyCode`, and `A_CostCenter.CostCenterCategory`.
- For wording such as "公司1710成本中心负责人信息", query `A_CostCenter` by `A_CostCenter.CompanyCode` and select only `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, `A_CostCenter.CompanyCode`, `A_CostCenter.CostCtrResponsiblePersonName`, and `A_CostCenter.CostCtrResponsibleUser`.

### Company Cost Center Names

- For wording such as "公司1710成本中心的英文名称" or "cost center English names for company 1710", do not ask for a specific cost center. Treat it as a list request for all cost centers assigned to that company code.
- Step 1: query `A_CostCenter` by `A_CostCenter.CompanyCode` and select only `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, and `A_CostCenter.CompanyCode`.
- Step 2: query `A_CostCenterText` by `CostCenter` binding and filter `A_CostCenterText.Language eq 'EN'`. Select only `A_CostCenterText.ControllingArea`, `A_CostCenterText.CostCenter`, `A_CostCenterText.Language`, and `A_CostCenterText.CostCenterName`.

### Cost Center To Profit Center Mapping

- For wording such as "成本中心对应的利润中心", "成本中心关联利润中心", or "cost center profit center mapping", do not ask for a specific cost center when the user also provides a company code. Treat it as a list mapping request for all cost centers in that company code.
- Step 1: query `A_CostCenter` by `A_CostCenter.CompanyCode` and select `A_CostCenter.ControllingArea`, `A_CostCenter.CostCenter`, `A_CostCenter.CompanyCode`, and `A_CostCenter.ProfitCenter`.
- If names are requested, Step 2 can query `API_PROFITCENTER_SRV.A_ProfitCenterText` by `ProfitCenter` and select `API_PROFITCENTER_SRV.A_ProfitCenterText.ControllingArea`, `API_PROFITCENTER_SRV.A_ProfitCenterText.ProfitCenter`, `API_PROFITCENTER_SRV.A_ProfitCenterText.Language`, and `API_PROFITCENTER_SRV.A_ProfitCenterText.ProfitCenterName`.

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

- Verify entity and field availability against `data/index/API_COSTCENTER_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
