# I_PurchaseOrderHistoryAPI01 Skill

## Purpose

Use this API for Purchase Order History. <p>This CDS view helps to retrieve a history of all the transactions that have occurred referring to a purchase order item to date (for example, goods and invoice receipts relating to the item, incurrence of delivery costs, down-payments, and so on).</p> <p>To help you decide which CDS view to use for your purposes, SAP has introduced the annotation ObjectModel.supportedCapabilities that indicates the most appropriate use cases for each CDS view. To find out what use cases are best supported by this CDS view, access the entry of the CDS view in the View Browser app and find the values for this annotation under the Annotation tab. For more information, see Supported Capabilities for CDS Views.</p>

Keep `data/index/I_PurchaseOrderHistoryAPI01` as the schema ground truth. This skill provides business usage guidance only. This index is CDS documentation based and is marked `CDS_VIEW_ONLY`. It is not a SAP Gateway OData service and must not be planned or executed as `/sap/opu/odata/sap/I_PurchaseOrderHistoryAPI01/...`.

## When To Use

- The user asks about purchase order history or the business objects exposed by this service: I Purchase Order History API01.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/I_PurchaseOrderHistoryAPI01`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not call this API through `/sap/opu/odata/sap/...`. Runtime access requires a backend CDS/ABAP SQL-capable channel or a separately exposed OData service binding.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `I_PurchaseOrderHistoryAPI01`: Purchase Order History. CDS_VIEW_ONLY; documentation-only for this OData agent.

## Business Semantics

- Primary business scope: Purchase Order History.
- Use the service description, entity descriptions, and field descriptions from `data/index/I_PurchaseOrderHistoryAPI01` to infer user intent.
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

- This index is `CDS_VIEW_ONLY`. Use it only for schema/business semantics in the current OData-only agent.
- Do not compile an OData URL for this entry. If the user needs live purchase order history, the runtime needs CDS/ABAP SQL backend access or a custom/released OData service that exposes this view.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/I_PurchaseOrderHistoryAPI01` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
