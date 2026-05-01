# API_PRODUCTION_ROUTING Skill

## Purpose

Use this API for production routings, production routing headers, production routing operations, production routing material assignments, production routing statuses, routing usages, and routing control profiles. A routing describes the operations or steps used to manufacture a product/material and is used by production orders, scheduling, and product costing.

Keep `data/index/API_PRODUCTION_ROUTING` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about a routing is a description of the operations (or steps in a process) that are performed to manufacture a product (or material). it is used as a reference for production orders, to run schedules and in calculating the costs of products. or the business objects exposed by this service: Production Routing Header, Production Routing, Production Routing Comp Alloc, Production Routing Doc PRTAssgmt, Production Routing Material Assgmt, Production Routing Material PRTAssgmt, Production Routing Misc PRTAssgmt, Production Routing Op Ctrl Prfl.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_PRODUCTION_ROUTING`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `ProductionRoutingHeader`: Get entities from ProductionRoutingHeader. Methods: GET, PATCH, POST.
- `ProductionRouting`: ProductionRouting_Type. Methods: GET.
- `ProductionRoutingCompAlloc`: ProductionRoutingCompAlloc_Type. Methods: GET.
- `ProductionRoutingDocPRTAssgmt`: ProductionRoutingDocPRTAssgmt_Type. Methods: GET.
- `ProductionRoutingMatlAssgmt`: Get entities from ProductionRoutingMatlAssgmt. Methods: GET.
- `ProductionRoutingMatlPRTAssgmt`: ProductionRoutingMatlPRTAssgmt_Type. Methods: GET.
- `ProductionRoutingMiscPRTAssgmt`: ProductionRoutingMiscPRTAssgmt_Type. Methods: GET.
- `ProductionRoutingOpCtrlPrfl`: Get entities from ProductionRoutingOpCtrlPrfl. Methods: GET.
- `ProductionRoutingOpCtrlPrflTxt`: Get entities from ProductionRoutingOpCtrlPrflTxt. Methods: GET.
- `ProductionRoutingOperation`: Get entities from ProductionRoutingOperation. Methods: GET, PATCH, POST.
- `ProductionRoutingSequence`: Get entities from ProductionRoutingSequence. Methods: GET, PATCH, POST.
- `ProductionRoutingStatus`: Get entities from ProductionRoutingStatus. Methods: GET.

## Business Semantics

- Primary business scope: A routing is a description of the operations (or steps in a process) that are performed to manufacture a product (or material). It is used as a reference for production orders, to run schedules and in calculating the costs of products..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_PRODUCTION_ROUTING` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- If the user asks for production routing status records, routing status values, or main identifying details for routing statuses, query `ProductionRoutingStatus` directly and select `BillOfOperationsStatus` and `BillOfOperationsStatusDesc`.
- Do not expand a production routing status list into `ProductionRoutingHeader`, `ProductionRoutingMatlAssgmt`, or other routing detail entities unless the user also asks for concrete routings, products/material assignments, operations, or header-level details.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_PRODUCTION_ROUTING` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_PRODUCTION_ROUTING` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
