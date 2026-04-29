# API_MASTER_RECIPE Skill

## Purpose

Use this API for Master recipes are used for planning the manufacture of products. It is used as a reference for process orders and in calculating the costs of products. Master recipe is a description of the operations or phases (steps in a process) that must be carried out in a certain order to manufacture a product.. Master recipes are used for planning the manufacture of products. It is used as a reference for process orders and in calculating the costs of products. Master recipe is a description of the operations or phases (steps in a process) that must be carried out in a certain order to manufacture a product.

Keep `data/index/API_MASTER_RECIPE` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about master recipes are used for planning the manufacture of products. it is used as a reference for process orders and in calculating the costs of products. master recipe is a description of the operations or phases (steps in a process) that must be carried out in a certain order to manufacture a product. or the business objects exposed by this service: Master Recipe Header, Master Recipe Material Assgmt, Master Recipe Op Comp Alloc, Master Recipe Op Secdry Rsce, Master Recipe Operation, Master Recipe Phase, Master Recipe Phse Comp Alloc, Master Recipe Phse Relshp.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_MASTER_RECIPE`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `MasterRecipeHeader`: Get entities from MasterRecipeHeader. Methods: GET, PATCH, POST.
- `MasterRecipeMatlAssgmt`: Get entities from MasterRecipeMatlAssgmt. Methods: GET.
- `MasterRecipeOpCompAlloc`: Get entities from MasterRecipeOpCompAlloc. Methods: GET.
- `MasterRecipeOpSecdryRsce`: Get entities from MasterRecipeOpSecdryRsce. Methods: GET, PATCH, POST.
- `MasterRecipeOperation`: Get entities from MasterRecipeOperation. Methods: GET, PATCH, POST.
- `MasterRecipePhase`: Get entities from MasterRecipePhase. Methods: GET, PATCH, POST.
- `MasterRecipePhseCompAlloc`: Get entities from MasterRecipePhseCompAlloc. Methods: GET, PATCH, POST.
- `MasterRecipePhseRelshp`: Get entities from MasterRecipePhseRelshp. Methods: GET, PATCH, POST.
- `MasterRecipePhseSecdryRsce`: Get entities from MasterRecipePhseSecdryRsce. Methods: GET, PATCH, POST.
- `MasterRecipeInspCharcsAssgmt`: Get entities from MasterRecipeInspCharcsAssgmt. Methods: GET. documentation-only; verify against metadata before execution.

## Business Semantics

- Primary business scope: Master recipes are used for planning the manufacture of products. It is used as a reference for process orders and in calculating the costs of products. Master recipe is a description of the operations or phases (steps in a process) that must be carried out in a certain order to manufacture a product..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_MASTER_RECIPE` to infer user intent.
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

- SAP $metadata was available when this index was built. Use `data/index/API_MASTER_RECIPE` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_MASTER_RECIPE` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
