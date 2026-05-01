# API_WORK_CENTERS Skill

## Purpose

Use this API for Work Center. This service is based on OData protocol and can be consumed in Fiori apps and on other user interfaces. It enables you to create, read and update work centers. The service contains work center header, work center description, cost center allocation, capacity assignment, capacity header, capacity intervals, capacity shifts, queuing operations, today’s operation, capacity per bucket and capacity order per bucket.

Keep `data/index/API_WORK_CENTERS` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about work center or the business objects exposed by this service: A Work Center Capacity, A Work Centers, A Work Center Cap Order Per Bucket, A Work Center Cap Order Per Bucket Set, A Work Center All Capacity, A Work Center All Capacity 2.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_WORK_CENTERS`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_WorkCenterCapacity`: Reads the capacity headers of all work center capacity assignments.. Methods: GET, PATCH, POST. runtime metadata available.
- `A_WorkCenters`: Reads all the headers of all work centers.. Methods: GET, PATCH, POST. runtime metadata available.
- `A_WorkCenterCapOrderPerBucket`: Reads the evaluation and load distribution of an order for a work center capacity.. Methods: GET. runtime metadata available.
- `A_WorkCenterCapOrderPerBucketSet`: A_WorkCenterCapOrderPerBucketType. Methods: GET. runtime metadata available.
- `A_WorkCenterAllCapacity`: Reads the capacity assignments of all work centers.. Methods: GET, POST. runtime metadata available.
- `A_WorkCenterAllCapacity_2`: Reads the capacity assignments of all work centers.. Methods: GET, PATCH, POST. runtime metadata available.
- `A_WorkCenterCapDayOp`: Reads the current day's operations for a work center.. Methods: GET. runtime metadata available.
- `A_WorkCenterCapPerBucket`: Reads the evaluation and load distribution for a work center capacity.. Methods: GET. runtime metadata available.
- `A_WorkCenterCapPerBucketSet`: A_WorkCenterCapPerBucketType. Methods: GET. runtime metadata available.
- `A_WorkCenterCapPplineOp`: Reads work center operations.. Methods: GET. runtime metadata available.
- `A_WorkCenterCapacityInterval`: Reads all the capacity intervals of all workcenter capacities.. Methods: GET, PATCH, POST. runtime metadata available.
- `A_WorkCenterCapacityInterval_2`: Reads the capacity intervals of all capacities.. Methods: GET, PATCH, POST. runtime metadata available.

## Business Semantics

- Primary business scope: Work Center.
- Use the service description, entity descriptions, and field descriptions from `data/index/API_WORK_CENTERS` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- If the user asks for work center capacity records or capacity header details, query `A_WorkCenterCapacity` directly.
- Use `A_WorkCenterAllCapacity` only when the user asks for capacity assignments of work centers or wants the relationship between work centers and capacities.
- Use capacity bucket/day/order entities only when the user asks for load, bucket evaluation, current-day operations, or order capacity distribution.

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

- Verify entity and field availability against `data/index/API_WORK_CENTERS` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
