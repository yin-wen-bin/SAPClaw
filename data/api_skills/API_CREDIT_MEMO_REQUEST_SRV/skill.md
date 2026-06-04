# API_CREDIT_MEMO_REQUEST_SRV Skill

## Purpose

Use this API for Credit Memo Request (A2X). In every API call, you can make use of the following operations:

You can read entire credit memo requests or only parts of the data, using the provided filters.

You can create credit memo requests. Note that you must use “deep insert” requests (a header plus the following entities: header partner, header pricing element, item, item partner, and item pricing element). You cannot create entities without including any related entities.

For existing credit memo requests, you can create new items. Note that you must use “deep insert” requests (with the following entities: item partner and item pricing element). You cannot create entities without including any related entities.

For existing credit memo requests, you can update the following entities (that is, you can change the content of their properties): the header, header partner, header pricing element, item, item partner, and item pricing element.

For existing credit memo requests, you can delete the header, header partner, header pricing element, item, item partner, and item pricing element.

You can accept or deny approval requests for credit memo requests that cannot be processed without the consent of an approver.

Note: Certain elements and entities can only be used if you activate the business function ISR_RETAILSYSTEM. For more information, see Business Documentation.

Keep `data/index/API_CREDIT_MEMO_REQUEST_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about credit memo request (a2x) or the business objects exposed by this service: A Crd Mm Req Item Subsqnt Proc Flow, A Credit Memo Req Partner, A Credit Memo Req Prcg Elmnt, A Credit Memo Request, A Credit Memo Req Item Partner, A Credit Memo Req Item Prcg Elmnt.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_CREDIT_MEMO_REQUEST_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_CrdMmReqItemSubsqntProcFlow`: Reads the subsequent documents of all credit memo requests.. Methods: GET. runtime metadata available.
- `A_CreditMemoReqPartner`: Reads the header partners of all credit memo requests.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CreditMemoReqPrcgElmnt`: Reads the header pricing elements of all credit memo requests.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CreditMemoRequest`: Reads all credit memo request headers.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_CreditMemoReqItemPartner`: Reads the item partners for all credit memo requests.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CreditMemoReqItemPrcgElmnt`: Reads the item pricing elements of all credit memo requests.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CreditMemoRequestItem`: Reads all credit memo request items.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_CreditMemoReqSubsqntProcFlow`: Reads the subsequent documents of all credit memo requests.. Methods: GET. runtime metadata available.
- `I_Customer_VH`: Get entities from I_Customer_VH. Methods: GET. runtime metadata available.
- `I_MaterialStdVH`: Get entities from I_MaterialStdVH. Methods: GET. runtime metadata available.
- `A_CreditMemoReqText`: Reads the header texts of all credit memo requests.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_CreditMemoReqItemText`: Reads item texts of all credit memo requests.. Methods: DELETE, GET, PATCH. runtime metadata available.

## Business Semantics

- Primary business scope: Credit Memo Request (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_CREDIT_MEMO_REQUEST_SRV` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For credit memo request header partner wording such as `credit memo request header partners`, `credit memo request partners`, or `with customer and supplier details`, use `A_CreditMemoReqPartner` directly. Select `CreditMemoRequest`, `PartnerFunction`, `Customer`, `Supplier`, `Personnel`, and `ContactPerson`. Do not end the plan on value-help entities such as `I_Customer_VH`; those may enrich names only after the partner rows are returned and must not replace the partner result set.

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

- Verify entity and field availability against `data/index/API_CREDIT_MEMO_REQUEST_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
