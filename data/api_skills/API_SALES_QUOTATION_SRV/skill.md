# API_SALES_QUOTATION_SRV Skill

## Purpose

Use this API for Sales Quotation (A2X). In every API call, you can make use of the following operations:
 - You can read entire sales quotations or only parts of the data, using the provided filters.
 - You can create sales quotations. You can use “deep insert” requests to create a header together with one or more related entities (for example, header partners or items).
 - For existing sales quotations, you can create new items. You can use “deep insert” requests to create an item together with one or more related entities (for example, item partners).
 - For existing sales quotations, you can update the header, header partner, header pricing element, header text, item, item partner, item pricing element, and item text.
 - For existing sales quotations, you can delete the header, header partner, header pricing element, header text, header related object, item, item partner, item pricing element, item text, and item related object.
 - You can accept or deny approval requests for sales quotations that cannot be processed without the consent of an approver.

Note: Certain elements and entities can only be used if you activate the business function ISR_RETAILSYSTEM. For more information, see Business Documentation.

Keep `data/index/API_SALES_QUOTATION_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about sales quotation (a2x) or the business objects exposed by this service: A Sales Quotation, A Sales Quotation Partner, A Sales Quotation Prcg Elmnt, A Sales Quotation Item, A Sales Quotation Item Partner, A Sales Quotation Item Prcg Elmnt.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_SALES_QUOTATION_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_SalesQuotation`: Reads all sales quotation headers.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesQuotationPartner`: Reads the header partners of all sales quotations.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_SalesQuotationPrcgElmnt`: Reads the header pricing elements of all sales quotations.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_SalesQuotationItem`: Reads all sales quotation items.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesQuotationItemPartner`: Reads the item partners for all sales quotations.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_SalesQuotationItemPrcgElmnt`: Reads the item pricing elements of all sales quotations.. Methods: DELETE, GET, PATCH. runtime metadata available.
- `A_SlsQtanItemRelatedObject`: Reads related objects from all sales quotation items.. Methods: DELETE, GET, POST. runtime metadata available.
- `A_SlsQtanItmPrecdgProcFlow`: Reads the preceding items of all sales quotation items.. Methods: GET. runtime metadata available.
- `A_SlsQtanItmSubsqntProcFlow`: Reads the subsequent items of all sales quotation items.. Methods: GET. runtime metadata available.
- `A_SlsQtanPrecdgProcFlow`: Reads the preceding documents of all sales quotations.. Methods: GET. runtime metadata available.
- `A_SlsQtanSubsqntProcFlow`: Reads the subsequent documents of all sales quotations.. Methods: GET. runtime metadata available.
- `A_SalesQuotationText`: Reads the header texts of all sales quotations.. Methods: DELETE, GET, PATCH. runtime metadata available.

## Business Semantics

- Primary business scope: Sales Quotation (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_SALES_QUOTATION_SRV` to infer user intent.
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

- Verify entity and field availability against `data/index/API_SALES_QUOTATION_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
