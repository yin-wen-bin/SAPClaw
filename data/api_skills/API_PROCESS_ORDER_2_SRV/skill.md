# API_PROCESS_ORDER_2_SRV Skill

## Purpose

Use this API for In addition to create, read, and update process orders, you can also release orders and operations. Besides updating header data of the order including the scheduling type, you can also update some properties of the order components. This service enables you to convert planned orders to process orders, schedule process order operations, and set further statuses for the order such as technically completed, closed, discarded by MES, or released by MES. In addition, you can set the deletion flag, deletion indicator, and delivery completed indicator.. In addition to create, read, and update process orders, you can also release orders and operations. Besides updating header data of the order including the scheduling type, you can also update some properties of the order components. This service enables you to convert planned orders to process orders, schedule process order operations, and set further statuses for the order such as technically completed, closed, discarded by MES, or released by MES. In addition, you can set the deletion flag, deletion indicator, and delivery completed indicator.

Keep `data/index/API_PROCESS_ORDER_2_SRV` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about in addition to create, read, and update process orders, you can also release orders and operations. besides updating header data of the order including the scheduling type, you can also update some properties of the order components. this service enables you to convert planned orders to process orders, schedule process order operations, and set further statuses for the order such as technically completed, closed, discarded by mes, or released by mes. in addition, you can set the deletion flag, deletion indicator, and delivery completed indicator. or the business objects exposed by this service: Order Released By MES, Process Order_2, Process Order Item_2, Process Order Component_2, Process Order Operation_2, Process Order Prodn Rsce Tools_2, Process Order Status_2, Schedule Process Order Operation.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_PROCESS_ORDER_2_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `OrderReleasedByMES`: Sets the status ReleasedByMES for a process order.. Methods: POST. documentation-only; verify against metadata before execution.
- `A_ProcessOrder_2`: Reads information on the header data of process orders.. Methods: GET, PATCH, POST.
- `A_ProcessOrderItem_2`: Reads the data of process order items.. Methods: GET.
- `A_ProcessOrderComponent_2`: Reads the data of process order components.. Methods: GET, PATCH.
- `A_ProcessOrderOperation_2`: Reads the operations of process orders.. Methods: GET.
- `A_ProcessOrderProdnRsceTools_2`: Reads the production resources/tools (PRTs) of process orders.. Methods: GET.
- `A_ProcessOrderStatus_2`: Reads the status of process orders.. Methods: GET.
- `ScheduleProcessOrderOperation`: Schedules order operations.. Methods: POST. documentation-only; verify against metadata before execution.
- `CloseOrder`: Closes a process order.. Methods: POST. documentation-only; verify against metadata before execution.
- `ConvertPlndOrder`: Converts a planned order into a process order.. Methods: POST. documentation-only; verify against metadata before execution.
- `DeletionFlagOrder`: Sets the deletion flag for a process order.. Methods: POST. documentation-only; verify against metadata before execution.
- `DeletionIndOrder`: Sets the deletion indicator for a process order.. Methods: POST. documentation-only; verify against metadata before execution.

## Business Semantics

- Primary business scope: In addition to create, read, and update process orders, you can also release orders and operations. Besides updating header data of the order including the scheduling type, you can also update some properties of the order components. This service enables you to convert planned orders to process orders, schedule process order operations, and set further statuses for the order such as technically completed, closed, discarded by MES, or released by MES. In addition, you can set the deletion flag, deletion indicator, and delivery completed indicator..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_PROCESS_ORDER_2_SRV` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- Treat the trailing `_2` / "2" in this API's entity names as the service/entity version suffix, not as a row count and not as SAP status code 2.
- Exact phrase rule: "process order status 2 records" means records from entity `A_ProcessOrderStatus_2`. It does not mean two rows, SAP status code `2`, released orders, or `OrderIsReleased`.
- For "process order status 2 records" or "process order status records", use `A_ProcessOrderStatus_2` with `ManufacturingOrder`, `StatusCode`, `IsUserStatus`, `StatusShortName`, and `StatusName`. Never replace this with `A_ProcessOrder_2`, `OrderIsReleased`, or `ReleaseOrder` unless the user explicitly says released orders.
- `A_ProcessOrder_2` directly exposes customer and delivery-related descriptive fields such as `CustomerName`, `GoodsRecipientName`, `OrderLongText`, and `UnloadingPointName`. If the user asks for these fields on process order 2 records, query `A_ProcessOrder_2` and select those fields instead of asking a sales/delivery clarification.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_PROCESS_ORDER_2_SRV` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_PROCESS_ORDER_2_SRV` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
