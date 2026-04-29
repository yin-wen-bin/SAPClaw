# API_PURCHASECONTRACT_PROCESS_SRV_0002 Skill

## Purpose

Use this API for It enables you to read, create, and update purchase contracts through an API call from a source system outside SAP S/4 HANA. The service contains header, item, item conditions, account assignment, address, header notes, item notes and partner nodes. Note: Certain elements and entities can only be used if you activate the business function ISR RETAILSYSTEM. For more information, see Business Documentation.. It enables you to read, create, and update purchase contracts through an API call from a source system outside SAP S/4HANA. The service contains header, item, item conditions, account assignment, address, header notes, item notes and partner nodes. Note: Certain elements and entities can only be used if you activate the business function ISR_RETAILSYSTEM. For more information, see Business Documentation.

Keep `data/index/API_PURCHASECONTRACT_PROCESS_SRV_0002` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about it enables you to read, create, and update purchase contracts through an api call from a source system outside sap s/4 hana. the service contains header, item, item conditions, account assignment, address, header notes, item notes and partner nodes. note: certain elements and entities can only be used if you activate the business function isr retailsystem. for more information, see business documentation. or the business objects exposed by this service: Purchase Contract, Purchase Contract Item, Purchase Contract Notes, Purchase Contract Item Notes, Pur Ctr Account, Pur Ctr Address, Pur Ctr Partners, Pur Contr Hdr Cndn Amount.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_PURCHASECONTRACT_PROCESS_SRV_0002`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_PurchaseContract`: Gets the header details of all the purchase contracts in the system. Methods: GET, PATCH, POST.
- `A_PurchaseContractItem`: Gets the details of all the items, in all the purchase contracts in the system. Methods: GET, PATCH, POST.
- `A_PurchaseContractNotes`: Gets all the header notes in the system. Methods: GET, PATCH, POST.
- `A_PurchaseContractItemNotes`: Gets all the item notes in the system. Methods: GET, PATCH, POST.
- `A_PurCtrAccount`: Gets the details of all the accounting assignments of all the items, in all the purchase contracts in the system. Methods: GET, PATCH, POST.
- `A_PurCtrAddress`: Gets the details of all the delivery addresses of all the items, in all the purchase contracts in the system. Methods: GET, PATCH, POST.
- `A_PurCtrPartners`: Gets the details of all the partners of all the purchase contracts in the system. Methods: GET, PATCH, POST.
- `A_PurContrHdrCndnAmount`: Gets the details of the condition amounts of all the validities of the header in the system. Methods: GET.
- `A_PurContrHdrCndnScale`: Gets the details of the condition scales of all the condition amounts of all the validities of the header in the system. Methods: GET.
- `A_PurContrHdrCndnValdty`: Gets the details of the validities of the header in the system. Methods: GET.
- `A_PurContrItmCndnAmount`: Gets the details of the condition amounts of all the validities of all the items in the system. Methods: GET.
- `A_PurContrItmCndnScales`: Gets the details of the condition scales of all the condition amounts of all the validities of all the items in the system. Methods: GET.

## Business Semantics

- Primary business scope: It enables you to read, create, and update purchase contracts through an API call from a source system outside SAP S/4 HANA. The service contains header, item, item conditions, account assignment, address, header notes, item notes and partner nodes. Note: Certain elements and entities can only be used if you activate the business function ISR RETAILSYSTEM. For more information, see Business Documentation..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_PURCHASECONTRACT_PROCESS_SRV_0002` to infer user intent.
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

- SAP $metadata was available when this index was built. Use `data/index/API_PURCHASECONTRACT_PROCESS_SRV_0002` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_PURCHASECONTRACT_PROCESS_SRV_0002` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
