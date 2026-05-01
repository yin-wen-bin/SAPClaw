# API_PHYSICAL_INVENTORY_DOC_SRV Skill

## Purpose

Use this API for You can count items and post differences on both document and item level. The service can be consumed by external systems.. You can count items and post differences on both document and item level. The service can be consumed by external systems.

Keep `data/index/API_PHYSICAL_INVENTORY_DOC_SRV` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about you can count items and post differences on both document and item level. the service can be consumed by external systems. or the business objects exposed by this service: Phys Inventory Doc Header, Phys Inventory Doc Item, Serial Number Phys Inventory Doc, Initiate Recount On Item, Post Differences On Item, Initiate Recount, Post Differences.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_PHYSICAL_INVENTORY_DOC_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_PhysInventoryDocHeader`: Reads information on physical inventory document header level. Methods: GET, POST.
- `A_PhysInventoryDocItem`: Reads information on physical inventory items level. Methods: GET, PATCH.
- `A_SerialNumberPhysInventoryDoc`: Reads information of serial numbers on physical inventory document items level. Methods: GET, PATCH.
- `InitiateRecountOnItem`: Initiates a recount for the specific physical inventory document. Methods: POST. documentation-only; verify against metadata before execution.
- `PostDifferencesOnItem`: Creates the material document for the differences for a specific physical inventory document item. Methods: POST. documentation-only; verify against metadata before execution.
- `InitiateRecount`: Initiates a recount for the physical inventory document. Methods: POST. documentation-only; verify against metadata before execution.
- `PostDifferences`: Creates the material document for the differences. Methods: POST. documentation-only; verify against metadata before execution.

## Business Semantics

- Primary business scope: You can count items and post differences on both document and item level. The service can be consumed by external systems..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_PHYSICAL_INVENTORY_DOC_SRV` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For wording such as "with is handled in alternative unit of measure", "with is value only material", or "with physical inventory difference is posted", treat `A_PhysInventoryDocItem.IsHandledInAltvUnitOfMsr`, `A_PhysInventoryDocItem.IsValueOnlyMaterial`, and `A_PhysInventoryDocItem.PhysInvtryDifferenceIsPosted` as output fields unless the user explicitly asks for only records where the indicator is true or false. Do not add boolean filters just because the user asks to display those fields.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_PHYSICAL_INVENTORY_DOC_SRV` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_PHYSICAL_INVENTORY_DOC_SRV` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
