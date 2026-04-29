# API_BILL_OF_MATERIAL_SRV_0002 Skill

## Purpose

Use this API for This service enables you to read, create, and update bills of material with and without version. The service contains either no header, one header, or multiple headers for the specified material and none or more items for each header. The service is based on the OData protocol and can be consumed in SAP Fiori apps and on other user interfaces.. This service enables you to read, create, and update bills of material with and without version. The service contains either no header, one header, or multiple headers for the specified material and none or more items for each header. The service is based on the OData protocol and can be consumed in SAP Fiori apps and on other user interfaces.

Keep `data/index/API_BILL_OF_MATERIAL_SRV_0002` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about this service enables you to read, create, and update bills of material with and without version. the service contains either no header, one header, or multiple headers for the specified material and none or more items for each header. the service is based on the odata protocol and can be consumed in sap fiori apps and on other user interfaces. or the business objects exposed by this service: Material BOMItem, Material BOMSub Item, Bill Of Material Usage, Material BOM, Bill Of Material Usage Text, BOMItem Category, MBOMItm Obj Dpn Assignment, Delete BOMHeader With ECN.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_BILL_OF_MATERIAL_SRV_0002`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `MaterialBOMItem`: Get entities from MaterialBOMItem. Methods: DELETE, GET, PATCH, POST.
- `MaterialBOMSubItem`: Get entities from MaterialBOMSubItem. Methods: DELETE, GET, PATCH, POST.
- `A_BillOfMaterialUsage`: Get entities from A_BillOfMaterialUsage. Methods: GET.
- `MaterialBOM`: Get entities from MaterialBOM. Methods: DELETE, GET, PATCH, POST.
- `A_BillOfMaterialUsageText`: Get entities from A_BillOfMaterialUsageText. Methods: GET.
- `A_BOMItemCategory`: Get entities from A_BOMItemCategory. Methods: GET.
- `MBOMItmObjDpnAssignment`: Get entities from MBOMItmObjDpnAssignment. Methods: DELETE, GET, PATCH.
- `DeleteBOMHeaderWithECN`: Invoke action DeleteBOMHeaderWithECN. Methods: POST. documentation-only; verify against metadata before execution.
- `ConvertItem`: Invoke action ConvertItem. Methods: POST. documentation-only; verify against metadata before execution.
- `DeleteBOMItemWithECN`: Invoke action DeleteBOMItemWithECN. Methods: POST. documentation-only; verify against metadata before execution.
- `UpdateBOMItemWithECN`: Invoke action UpdateBOMItemWithECN. Methods: POST. documentation-only; verify against metadata before execution.
- `A_BOMItemCategoryText`: Get entities from A_BOMItemCategoryText. Methods: GET.

## Business Semantics

- Primary business scope: This service enables you to read, create, and update bills of material with and without version. The service contains either no header, one header, or multiple headers for the specified material and none or more items for each header. The service is based on the OData protocol and can be consumed in SAP Fiori apps and on other user interfaces..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_BILL_OF_MATERIAL_SRV_0002` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_BILL_OF_MATERIAL_SRV_0002` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_BILL_OF_MATERIAL_SRV_0002` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
