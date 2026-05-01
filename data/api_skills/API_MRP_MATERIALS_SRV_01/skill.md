# API_MRP_MATERIALS_SRV_01 Skill

## Purpose

Use this API for MRP material records; `A_MRPMaterial` directly includes `CrossPlantStatus`, `CrossPlantStatusName`, `IsSafetyTime`, and `MaterialIsConfigurable`. The service contains entities for material master data, supply and demand information, and information about the coverage of materials. You can read master data for one or more materials. You can read supply and demand information over a certain time period, or you can aggregate the quantities on category group level. You can read material coverage information.

Keep `data/index/API_MRP_MATERIALS_SRV_01` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about the service contains entities for material master data, supply and demand information, and information about the coverage of materials. you can read master data for one or more materials. you can read supply and demand information over a certain time period, or you can aggregate the quantities on category group level. you can read material coverage information. or the business objects exposed by this service: MRPMaterial, Supply Demand Items, Material Coverages.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_MRP_MATERIALS_SRV_01`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_MRPMaterial`: Reads master data for MRP materials.. Methods: GET.
- `SupplyDemandItems`: Reads information on the supply and demand for an MRP material.. Methods: GET.
- `MaterialCoverages`: Reads information on material coverages.. Methods: GET.

## Business Semantics

- Primary business scope: The service contains entities for material master data, supply and demand information, and information about the coverage of materials. You can read master data for one or more materials. You can read supply and demand information over a certain time period, or you can aggregate the quantities on category group level. You can read material coverage information..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_MRP_MATERIALS_SRV_01` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For MRP material descriptive-name requests, `A_MRPMaterial.MaterialTypeName`, `A_MRPMaterial.MRPGroupName`, and `A_MRPMaterial.PlantName` are direct fields on `A_MRPMaterial`; do not require `MRPArea` unless the user asks for MRP area.
- For MRP material status/indicator requests, `A_MRPMaterial.CrossPlantStatus`, `A_MRPMaterial.CrossPlantStatusName`, `A_MRPMaterial.IsSafetyTime`, and `A_MRPMaterial.MaterialIsConfigurable` are direct fields on `A_MRPMaterial`. Do not reroute to product master data or ask for clarification when the user asks for these fields on MRP material records.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_MRP_MATERIALS_SRV_01` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_MRP_MATERIALS_SRV_01` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
