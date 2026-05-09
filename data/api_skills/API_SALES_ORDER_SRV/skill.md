# API_SALES_ORDER_SRV Skill

## Purpose

Use this API for Sales Order (A2X). In every API call, you can make use of the following operations:

You can read entire sales orders or only parts of the data, using the provided filters.

You can create sales orders. Note that you must use “deep insert” requests (a header plus the following entities: header partner, header pricing element, header text, payment details, item, item partner, item pricing element, and item text). You cannot create entities without including any related entities.

For existing sales orders, you can create new items. Note that you must use “deep insert” requests (with the following entities: item partner, item pricing element, and item text). You cannot create entities without including any related entities.

For existing sales orders, you can update the following entities (that is, you can change the content of their properties): header, header partner, header pricing element, header text, payment plan, item, item partner, item pricing element, and item text.

For existing sales orders, you can delete the header, header partner, header pricing element, header text, payment details, item, item partner, item pricing element, and item text.

You can accept or deny approval requests for sales orders that cannot be processed without the consent of an approver.

Note: Certain elements and entities can only be used if you activate the business function ISR_RETAILSYSTEM. For more information, see Business Documentation.

Keep `data/index/API_SALES_ORDER_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about sales order (a2x) or the business objects exposed by this service: A Sales Order, A Sales Order Header Partner, A Sales Order Header Pr Element, A Sales Order Partner Address, A Sales Order Related Object, A Sales Order Billing Plan Item.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_SALES_ORDER_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_SalesOrder`: Reads all sales order headers.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderHeaderPartner`: Reads the header partners of all sales orders.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderHeaderPrElement`: Reads the header pricing elements of all sales orders.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderPartnerAddress`: Reads all addresses for header partners of sales orders.. Methods: GET, PATCH. runtime metadata available.
- `A_SalesOrderRelatedObject`: Reads related objects from the headers of all sales orders.. Methods: DELETE, GET, POST. runtime metadata available.
- `A_SalesOrderBillingPlanItem`: Reads the billing plan items of all sales orders.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderItem`: Reads all sales order items.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderItemBillingPlan`: Reads the billing plans of all sales order items.. Methods: GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderItemPartner`: Reads the item partners for all sales orders.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderItemPartnerAddress`: Reads all addresses for item partners of sales orders.. Methods: GET, PATCH. runtime metadata available.
- `A_SalesOrderItemPrElement`: Reads the item pricing elements of all sales orders.. Methods: DELETE, GET, PATCH, POST. runtime metadata available.
- `A_SalesOrderItemRelatedObject`: Reads related objects from the items of all sales orders.. Methods: DELETE, GET, POST. runtime metadata available.

## Business Semantics

- Primary business scope: Sales Order (A2X).
- Use the service description, entity descriptions, and field descriptions from `data/index/API_SALES_ORDER_SRV` to infer user intent.
- Use this API for sales order header, item, partner, pricing, text, billing plan, and sales-order-specific fields. If the user asks for delivery documents created for or related to a sales order, route to `API_OUTBOUND_DELIVERY_SRV` because the target object is an outbound delivery.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Related Delivery Documents

- Do not answer `delivery documents for sales order <number>` from this API unless the user explicitly asks for sales-order-side document-flow fields.
- Prefer `API_OUTBOUND_DELIVERY_SRV.A_OutbDeliveryHeader.OrderID` for header-level delivery documents and `API_OUTBOUND_DELIVERY_SRV.A_OutbDeliveryItem.OrderID` or `ReferenceSDDocument` for delivery items.

### Customer Sales Order Items

- For requests such as `query sales order items for customer 17100003` or `query customer 17100003 sales order line items`, use `A_SalesOrder` first and `A_SalesOrderItem` second.
- Step 1: query `A_SalesOrder` with `SoldToParty eq '<customer>'`, selecting `SalesOrder`, `SoldToParty`, `SalesOrganization`, `OverallDeliveryStatus`, and `OverallOrdReltdBillgStatus`.
- Step 2: query `A_SalesOrderItem` by binding `A_SalesOrder.SalesOrder` to `A_SalesOrderItem.SalesOrder`.
- For the final item result, select only `A_SalesOrderItem.SalesOrder`, `A_SalesOrderItem.SalesOrderItem`, `A_SalesOrderItem.Material`, `A_SalesOrderItem.RequestedQuantity`, and `A_SalesOrderItem.ProductionPlant`.
- Do not continue from sales order items to pricing elements, partners, texts, billing plan, or related objects unless the user explicitly asks for price, condition, partner, text, billing plan, or related-object details.

### Customer Sales Orders Not Fully Delivered

- For requests such as `查询客户17100003未完全交货的销售订单`, `customer 17100003 open delivery sales orders`, or `sales orders not fully delivered for customer`, answer from `A_SalesOrder`; do not use item-level quantity comparison unless the user explicitly asks for line items, ordered quantity, delivered quantity, or quantity variance.
- Filter `A_SalesOrder.SoldToParty eq '<customer>'` and `A_SalesOrder.OverallTotalDeliveryStatus ne 'C'`.
- Select only `A_SalesOrder.SalesOrder`, `A_SalesOrder.SoldToParty`, `A_SalesOrder.OverallDeliveryStatus`, and `A_SalesOrder.OverallTotalDeliveryStatus`; answer from this step and do not continue to `A_SalesOrderItem` enrichment.

### Material Sales Orders Not Fully Delivered

- For requests such as `查询物料MZ-TG-Y240的未交货销售订单`, `material <id> undelivered sales orders`, or `open delivery sales orders for material <id>`, answer from `A_SalesOrderItem`; the material identifier is an item-level filter, not a product-master query.
- Filter `A_SalesOrderItem.Material eq '<material>'` and `A_SalesOrderItem.DeliveryStatus ne 'C'`.
- Select only `A_SalesOrderItem.SalesOrder`, `A_SalesOrderItem.SalesOrderItem`, `A_SalesOrderItem.Material`, `A_SalesOrderItem.RequestedQuantity`, `A_SalesOrderItem.ConfdDelivQtyInOrderQtyUnit`, and `A_SalesOrderItem.DeliveryStatus`.
- Do not route this request to `API_PRODUCT_SRV`; product master data cannot answer sales order delivery status.
- Do not start from `A_SalesOrder` for a material-only filter unless header fields are explicitly requested; `A_SalesOrder` does not contain the item material.

### Customer Sales Orders Not Fully Billed

- For requests such as `查询客户17100003未完全开票的销售订单`, `customer 17100003 unbilled sales orders`, or `sales orders not fully billed for customer`, answer from `A_SalesOrder`; do not ask a clarification just because fully unbilled and partially billed are both possible when the wording says not fully billed.
- Filter `A_SalesOrder.SoldToParty eq '<customer>'` and `A_SalesOrder.OverallOrdReltdBillgStatus ne 'C'`.
- Select only `A_SalesOrder.SalesOrder`, `A_SalesOrder.SoldToParty`, and `A_SalesOrder.OverallOrdReltdBillgStatus`; answer from this step and do not continue to billing document or item enrichment unless the user explicitly asks for invoice numbers, billing documents, billing dates, or billing items.

### Sales Order Pricing Conditions

- For requests such as `查询销售订单3773的价格条件`, `sales order 3773 pricing conditions`, or `sales order condition elements`, this API exposes sales order item pricing elements on `A_SalesOrderItemPrElement`; do not ask clarification merely because other SD APIs also expose pricing elements.
- Step 1: query `A_SalesOrder` by `A_SalesOrder.SalesOrder eq '<sales order>'` and select only `A_SalesOrder.SalesOrder`.
- Step 2: query `A_SalesOrderItemPrElement` by binding `A_SalesOrder.SalesOrder` to `A_SalesOrderItemPrElement.SalesOrder`.
- Select only `A_SalesOrderItemPrElement.SalesOrder`, `A_SalesOrderItemPrElement.SalesOrderItem`, `A_SalesOrderItemPrElement.PricingProcedureStep`, `A_SalesOrderItemPrElement.PricingProcedureCounter`, `A_SalesOrderItemPrElement.ConditionType`, `A_SalesOrderItemPrElement.ConditionAmount`, and `A_SalesOrderItemPrElement.ConditionCurrency`.

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

- Verify entity and field availability against `data/index/API_SALES_ORDER_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
