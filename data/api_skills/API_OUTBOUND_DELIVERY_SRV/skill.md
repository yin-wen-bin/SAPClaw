# API_OUTBOUND_DELIVERY_SRV Skill

## Purpose

Use this API for Outbound Delivery (A2X). This service enables you to create, read, update and delete outbound deliveries. It can be consumed in Fiori apps and on other user interfaces.

Keep `data/index/API_OUTBOUND_DELIVERY_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about outbound delivery (a2x) or the business objects exposed by this service: A Serial Nmbr Delivery, A Handling Unit Header Delivery, A Outb Delivery Header, A Handling Unit Item Delivery, A Maintenance Item Object, A Outb Delivery Item.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_OUTBOUND_DELIVERY_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_SerialNmbrDelivery`: Reads maintenance item object lists of specific outbound delivery maintenance item object list header.. Methods: GET. runtime metadata available.
- `A_HandlingUnitHeaderDelivery`: Creates handling unit headers.. Methods: GET, POST. runtime metadata available.
- `A_OutbDeliveryHeader`: Reads outbound delivery headers.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_HandlingUnitItemDelivery`: Creates handling unit items.. Methods: GET, POST. runtime metadata available.
- `A_MaintenanceItemObject`: A_MaintenanceItemObjectType. Methods: GET. runtime metadata available.
- `A_OutbDeliveryItem`: Reads outbound delivery items.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_OutbDeliveryDocFlow`: Reads outbound delivery document flows by key.. Methods: GET, PATCH. runtime metadata available.
- `A_OutbDeliveryHeaderText`: Creates outbound delivery header texts.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_OutbDeliveryItemText`: Creates outbound delivery item texts.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_OutbDeliveryAddress`: A_OutbDeliveryAddressType. Methods: GET. runtime metadata available.
- `A_OutbDeliveryAddress2`: Reads outbound delivery partner addresses.. Methods: GET, PATCH. runtime metadata available.
- `A_OutbDeliveryPartner`: Reads addresses of specific outbound delivery partner.. Methods: GET. runtime metadata available.

## Business Semantics

- Primary business scope: Outbound Delivery (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_OUTBOUND_DELIVERY_SRV` to infer user intent.
- When the user asks for delivery documents related to a sales order, this API is the target-object API. Prefer a direct outbound delivery item query using `A_OutbDeliveryItem.ReferenceSDDocument` instead of routing through the sales order API only to validate the order.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Actual Shipping Date For Delivery Documents

- For Chinese wording such as `发货日期`, `实际发货日期`, `出货日期`, or English wording such as `goods issue date`, `actual goods movement date`, and shipped-after/shipped-before delivery lists, use `A_OutbDeliveryHeader.ActualGoodsMovementDate`.
- For date comparisons on that wording, filter `A_OutbDeliveryHeader.ActualGoodsMovementDate` with the user's date and select `DeliveryDocument`, `ActualGoodsMovementDate`, `SoldToParty`, `ShipToParty`, and `OverallGoodsMovementStatus`.
- Do not use `A_OutbDeliveryHeader.DeliveryDate` for `发货日期`; `DeliveryDate` means `交货日期`. Use `DeliveryDate` only when the user explicitly says `交货日期`, requested delivery date, or delivery due date.

### Delivery Documents For A Sales Order

- For requests such as `query delivery documents for sales order 3773` or `查询销售订单3773的交货单`, use `API_OUTBOUND_DELIVERY_SRV` directly.
- Start with `A_OutbDeliveryItem` for sales-order-related delivery documents: filter `A_OutbDeliveryItem.ReferenceSDDocument eq '3773'`, and select `DeliveryDocument`, `DeliveryDocumentItem`, `ReferenceSDDocument`, `ReferenceSDDocumentItem`, `OrderID`, `Material`, and quantity/status fields.
- If the user only asks for delivery documents corresponding to a sales order and does not ask for header-only fields, answer from `A_OutbDeliveryItem`; select only `A_OutbDeliveryItem.DeliveryDocument`, `A_OutbDeliveryItem.DeliveryDocumentItem`, `A_OutbDeliveryItem.ReferenceSDDocument`, `A_OutbDeliveryItem.ReferenceSDDocumentItem`, `A_OutbDeliveryItem.Material`, and `A_OutbDeliveryItem.ActualDeliveryQuantity`; do not add an `A_OutbDeliveryHeader` enrichment step.
- `A_OutbDeliveryHeader.OrderID` can be blank in this SAP service for sales-order-created deliveries. Do not conclude that no delivery exists from an empty `OrderID` result until `A_OutbDeliveryItem.ReferenceSDDocument` has been checked.
- If the user asks for header-level delivery dates, ship-to party, sold-to party, shipping point, or overall status, use a second step from `A_OutbDeliveryItem.DeliveryDocument` to `A_OutbDeliveryHeader.DeliveryDocument`.
- Do not build a multi-API plan through `API_SALES_ORDER_SRV` merely to confirm the sales order exists when the delivery API exposes the sales order reference as a filter field.

### Delivered But Not Billed Delivery Documents

- For requests such as `delivered but not billed deliveries`, `shipped but not invoiced delivery documents`, `已发货但未开票的交货单`, or `已发货但还没开票的交货单`, prefer a direct `API_OUTBOUND_DELIVERY_SRV` plan before considering `API_BILLING_DOCUMENT_SRV`.
- Use `A_OutbDeliveryHeader` when the user asks for delivery documents at header/list level.
- For customer wording without a more specific partner role, filter `A_OutbDeliveryHeader.SoldToParty eq '<customer>'`. If the user explicitly says ship-to or receiver, use `A_OutbDeliveryHeader.ShipToParty eq '<customer>'`.
- For already shipped / goods issue completed semantics, filter `A_OutbDeliveryHeader.OverallGoodsMovementStatus eq 'C'`.
- For Chinese wording such as `还没开票`, `未开票`, `未完成开票`, `未完全开票`, and for open/not-fully-billed wording, filter `A_OutbDeliveryHeader.OverallDelivReltdBillgStatus ne 'C'`. This keeps partially billed but still open deliveries in scope. Billing-status value `A` alone is only suitable when the user explicitly asks for deliveries where billing has not started at all.
- Do not combine the open-billing filter above with a separate billing-status value `A` restriction for the same user phrase. For `还没开票` or open billing wording, use only `ne 'C'`; adding a value `A` restriction narrows the result incorrectly.
- Select `DeliveryDocument`, `DeliveryDate`, `SoldToParty`, `ShipToParty`, `OverallGoodsMovementStatus`, and `OverallDelivReltdBillgStatus`.
- Use `API_BILLING_DOCUMENT_SRV` only when the user asks for actual billing documents, invoice numbers, invoice dates, or billing document details, or when the outbound delivery billing status fields cannot answer the business question.

### Billing Items For Customer Delivery Documents

- For requests such as `query customer 17100003 delivery documents' billing items`, use this API as the source step and `API_BILLING_DOCUMENT_SRV` as the target API.
- Step 1: query `A_OutbDeliveryHeader` by `A_OutbDeliveryHeader.SoldToParty` and select only `A_OutbDeliveryHeader.DeliveryDocument`, `A_OutbDeliveryHeader.SoldToParty`, `A_OutbDeliveryHeader.OverallGoodsMovementStatus`, and `A_OutbDeliveryHeader.OverallDelivReltdBillgStatus`.
- Step 2: query `API_BILLING_DOCUMENT_SRV.A_BillingDocumentItem` by binding `A_OutbDeliveryHeader.DeliveryDocument` to `API_BILLING_DOCUMENT_SRV.A_BillingDocumentItem.ReferenceSDDocument`.
- Do not ask the user for specific delivery document numbers when the customer filter can produce the delivery document scope.

### Product Master Data For Customer Delivery Items

- For requests such as `查询客户17100003交货单里的物料主数据`, use this API as the source step and `API_PRODUCT_SRV` as the target API.
- Step 1: query `A_OutbDeliveryHeader` by `A_OutbDeliveryHeader.SoldToParty` and select only `A_OutbDeliveryHeader.DeliveryDocument` and `A_OutbDeliveryHeader.SoldToParty`.
- Step 2: query `A_OutbDeliveryItem` by binding `A_OutbDeliveryHeader.DeliveryDocument` to `A_OutbDeliveryItem.DeliveryDocument`; select only `A_OutbDeliveryItem.DeliveryDocument`, `A_OutbDeliveryItem.DeliveryDocumentItem`, and `A_OutbDeliveryItem.Material`; add filter `A_OutbDeliveryItem.Material ne ''`.
- Step 3: query `API_PRODUCT_SRV.A_Product` by binding `A_OutbDeliveryItem.Material` to `API_PRODUCT_SRV.A_Product.Product`; select only `API_PRODUCT_SRV.A_Product.Product`, `API_PRODUCT_SRV.A_Product.ProductType`, `API_PRODUCT_SRV.A_Product.ProductGroup`, and `API_PRODUCT_SRV.A_Product.BaseUnit`.
- Keep upstream delivery/item scope bounded to the first page unless the user explicitly asks for every matching delivery item.

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
- Do not use a cross-API anti-join against billing documents for delivered-but-not-billed delivery lists when `A_OutbDeliveryHeader.OverallDelivReltdBillgStatus` is available.

## Needs Verification

- Verify entity and field availability against `data/index/API_OUTBOUND_DELIVERY_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
