# API_CUSTOMER_RETURN_SRV Skill

## Purpose

Use this API for Customer Return (A2X). You can use this service to integrate external applications with customer return processing. In every API call, you can make use of the following operations:
 - You can retrieve returns orders. Apply any of the filters provided or retrieve all existing data.
 - You can create returns orders. Note that you must use “deep insert” requests (a header plus at least one of the following entities: header partner, header pricing element, item, item partner, and item pricing element). You cannot create headers without including any related entities.
 - You can create items for existing returns orders. Note that you must use “deep insert” requests (an item plus at least one of the following entities: item partner and item pricing element). You cannot create items without including any related entities.
 - For existing returns orders, you can update the header, header partner, header pricing element, item, item partner, and item pricing element.
 - For existing returns orders, you can delete the header, header partner, header pricing element, item, item partner, and item pricing element.
 - You can approve or reject existing returns orders.

Note: Certain elements and entities can only be used if you activate the business function ISR_RETAILSYSTEM. For more information, see Business Documentation.

Keep `data/index/API_CUSTOMER_RETURN_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about customer return (a2x) or the business objects exposed by this service: A Customer Return, A Customer Return Related Object, A Customer Return Item, A Customer Return Item Related Obj, A Customer Return Partner, A Customer Return Prcg Elmnt.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_CUSTOMER_RETURN_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_CustomerReturn`: Reads all returns order headers.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_CustomerReturnRelatedObject`: Reads the related objects from the headers of all returns orders.. Methods: DELETE, GET, POST. runtime metadata available.
- `A_CustomerReturnItem`: Reads all returns order items.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_CustomerReturnItemRelatedObj`: Reads the related objects of all returns order items.. Methods: DELETE, GET, POST. runtime metadata available.
- `A_CustomerReturnPartner`: Reads all header-level business partners.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CustomerReturnPrcgElmnt`: Reads all header-level pricing elements.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CustomerReturnItemPartner`: Reads all item-level business partners.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CustomerReturnItemPrcgElmnt`: Reads all item-level pricing elements.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CustomerReturnText`: Reads all header-level texts.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CustomerReturnItemText`: Reads all item-level texts.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CustomerReturnOverviewStatus`: Reads all customer return overview statuses.. Methods: GET. runtime metadata available.
- `A_CustomerReturnProcessStep`: Reads all advanced returns process steps.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Customer Return (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_CUSTOMER_RETURN_SRV` to infer user intent.
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

- If this skill says the index is documentation-only, route and plan only when the schema is sufficient, and expect SAP execution to require service authorization or metadata activation.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_CUSTOMER_RETURN_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
