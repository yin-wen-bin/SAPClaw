# API_SCHED_AGRMT_PROCESS_SRV Skill

## Purpose

Use this API for This service enables you to create, read, update and delete purchase scheduling agreements from any external system through an API call. Once the purchase scheduling agreement has been created or updated, the scheduling agreement number is sent in the response. If there are any issues while managing (create, read or update) purchase scheduling agreements, the system displays error messages in the response.. This service enables you to create, read, update and delete purchase scheduling agreements from any external system through an API call. Once the purchase scheduling agreement has been created or updated, the scheduling agreement number is sent in the response. If there are any issues while managing (create, read or update) purchase scheduling agreements, the system displays error messages in the response.

Keep `data/index/API_SCHED_AGRMT_PROCESS_SRV` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about this service enables you to create, read, update and delete purchase scheduling agreements from any external system through an api call. once the purchase scheduling agreement has been created or updated, the scheduling agreement number is sent in the response. if there are any issues while managing (create, read or update) purchase scheduling agreements, the system displays error messages in the response. or the business objects exposed by this service: Schedg Agrmt Subcontrg Comp, Schedg Agrmt Delivery Address, Schedg Agrmt Hdr Notes, Schedg Agrmt Itm Notes, Sch Agrmt Ac Cnt, Sch Agrmt Header, Sch Agrmt Item, Sch Agrmt Sch Line.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_SCHED_AGRMT_PROCESS_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_SchedgAgrmtSubcontrgComp`: Gets the subcontracting component details of all the items in all the purchase scheduling agreements in the system. Methods: DELETE, GET, PATCH.
- `A_SchedgAgrmtDeliveryAddress`: Gets the delivery address details of all the items in all the purchase scheduling agreements in the system. Methods: GET, PATCH, POST.
- `A_SchedgAgrmtHdrNotes`: Gets the all the header notes of all purchase scheduling agreement in the system. Methods: DELETE, GET, PATCH, POST.
- `A_SchedgAgrmtItmNotes`: Gets the item notes of all the items in all the purchase scheduling agreements in the system. Methods: DELETE, GET, PATCH, POST.
- `A_SchAgrmtAcCnt`: Gets the details of all the account assignments of all the items, in all the purchase scheduling agreements. Methods: GET, PATCH, POST.
- `A_SchAgrmtHeader`: Gets the header details of all the purchase scheduling agreements in the system. Methods: GET, PATCH, POST.
- `A_SchAgrmtItem`: Gets the details of all the items in all the purchase scheduling agreements in the system. Methods: GET, PATCH, POST.
- `A_SchAgrmtSchLine`: Gets the details of all the scheduling lines of all the items, in all the purchase scheduling agreements in the system. Methods: DELETE, GET, PATCH, POST.
- `A_SchAgrmtPartner`: Gets the details of all the partners of all the purchase scheduling agreements in the system. Methods: GET.
- `HeaderRelease`: Scheduling Agreement Header Release. Methods: POST. documentation-only; verify against metadata before execution.
- `ItemRelease`: Scheduling Agreement Item Release. Methods: POST. documentation-only; verify against metadata before execution.
- `WithdrawFromApproval`: Withdarw Scheduling Agreement from Approval. Methods: POST. documentation-only; verify against metadata before execution.

## Business Semantics

- Primary business scope: This service enables you to create, read, update and delete purchase scheduling agreements from any external system through an API call. Once the purchase scheduling agreement has been created or updated, the scheduling agreement number is sent in the response. If there are any issues while managing (create, read or update) purchase scheduling agreements, the system displays error messages in the response..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_SCHED_AGRMT_PROCESS_SRV` to infer user intent.
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

- SAP $metadata was available when this index was built. Use `data/index/API_SCHED_AGRMT_PROCESS_SRV` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_SCHED_AGRMT_PROCESS_SRV` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
