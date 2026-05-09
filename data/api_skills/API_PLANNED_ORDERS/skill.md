# API_PLANNED_ORDERS Skill

## Purpose

Use this API for planned order header/component/capacity records. In field-list wording, "with issued quantity / BOM is fixed / capacity is dispatched / is convertible" means select those fields, never filter them unless the user says only/where/true/nonzero. The service contains planned order header, planned order capacity and planned order components. You can read, create, change and delete components of orders and use this service to schedule planned order operations.

Keep `data/index/API_PLANNED_ORDERS` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about the service contains planned order header, planned order capacity and planned order components. the information is sent in the request as a payload. you can read, create, change and delete components of orders and also use this service to schedule planned order operations. or the business objects exposed by this service: Planned Order, Planned Order Component, Planned Order Capacity, Planned Order Schedule, Schedule Planned Order Operation.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_PLANNED_ORDERS`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_PlannedOrder`: Reads information on the header data of planned orders.. Methods: DELETE, GET, PATCH, POST.
- `A_PlannedOrderComponent`: Reads the data of planned order components.. Methods: DELETE, GET, PATCH, POST.
- `A_PlannedOrderCapacity`: Reads the capacity data of planned orders.. Methods: GET.
- `PlannedOrderSchedule`: Performs detailed scheduling of a planned order. Methods: POST. documentation-only; verify against metadata before execution.
- `SchedulePlannedOrderOperation`: Schedules order operations. Methods: POST. documentation-only; verify against metadata before execution.

## Business Semantics

- Primary business scope: The service contains planned order header, planned order capacity and planned order components. The information is sent in the request as a payload. You can read, create, change and delete components of orders and also use this service to schedule planned order operations..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_PLANNED_ORDERS` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For planned order component / 计划订单组件 requests, use `A_PlannedOrderComponent` and select `A_PlannedOrderComponent.PlannedOrder`, `A_PlannedOrderComponent.Material`, `A_PlannedOrderComponent.Plant`, `A_PlannedOrderComponent.BillOfMaterialItemNumber`, and `A_PlannedOrderComponent.GoodsMovementEntryQty`.
- Do not use `BOMItem` as a replacement for component `Material` when the user asks for components.
- For planned order component text requests, `A_PlannedOrderComponent.BOMItemDescription` and `A_PlannedOrderComponent.BOMItemDescriptionLine2` are direct fields on `A_PlannedOrderComponent`; do not ask for BOM relationship clarification when the user only wants to display these component fields.
- For planned order material/product master data requests (`计划订单物料的产品主数据`) without component wording, use planned order header material from `A_PlannedOrder`, not `A_PlannedOrderComponent`.
- Step 1: query `A_PlannedOrder` by `A_PlannedOrder.MRPPlant` when the user provides a plant. Select `A_PlannedOrder.PlannedOrder`, `A_PlannedOrder.Material`, `A_PlannedOrder.MRPPlant`, and `A_PlannedOrder.MRPController`.
- Step 2: query `API_PRODUCT_SRV.A_Product` by binding `A_PlannedOrder.Material` to `A_Product.Product`. Select `A_Product.Product`, `A_Product.ProductType`, and `A_Product.ProductGroup`.
- For planned order header wording such as "with issued quantity", "with planned order BOM is fixed", "with planned order capacity is dispatched", or "with planned order is convertible", treat `A_PlannedOrder.IssuedQuantity`, `A_PlannedOrder.PlannedOrderBOMIsFixed`, `A_PlannedOrder.PlannedOrderCapacityIsDsptchd`, and `A_PlannedOrder.PlannedOrderIsConvertible` as output fields unless the user explicitly asks for only records where the value is true/nonzero. Do not add filters by default.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_PLANNED_ORDERS` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_PLANNED_ORDERS` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
