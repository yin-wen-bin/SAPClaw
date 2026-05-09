# API_BILLING_DOCUMENT_SRV Skill

## Purpose

Use this API for Billing Document - Read, Cancel, Get PDF, Complete Pro Forma Invoice. Consumers of this inbound service can read and cancel billing documents in your system, as well as fetch entire billing documents in PDF format, by sending OData requests. In addition, they can complete specific pro forma invoices. The service makes billing document data available through its header, item, business partner, and pricing element entities.

Keep `data/index/API_BILLING_DOCUMENT_SRV` as the schema ground truth. This skill provides business usage guidance only. This index was built from SAP metadata plus OpenAPI documentation.

## When To Use

- The user asks about billing document - read, cancel, get pdf, complete pro forma invoice or the business objects exposed by this service: A Billing Document, A Billing Document Partner, A Billing Document Prcg Elmnt, A Billing Document Item, A Billing Document Item Partner, A Billing Document Item Prcg Elmnt.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_BILLING_DOCUMENT_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_BillingDocument`: Reads all billing document headers.. Methods: GET. runtime metadata available.
- `A_BillingDocumentPartner`: Reads the header business partners of all billing documents.. Methods: GET. runtime metadata available.
- `A_BillingDocumentPrcgElmnt`: Reads header pricing elements of all billing documents.. Methods: GET. runtime metadata available.
- `A_BillingDocumentItem`: Reads all billing document Items.. Methods: GET. runtime metadata available.
- `A_BillingDocumentItemPartner`: Reads item business partners for all billing documents.. Methods: GET. runtime metadata available.
- `A_BillingDocumentItemPrcgElmnt`: Reads item pricing elements of all billing documents.. Methods: GET. runtime metadata available.
- `A_BillingDocumentText`: Reads the header texts of all billing documents.. Methods: GET. runtime metadata available.
- `A_BillingDocumentItemText`: Reads item texts of all billing documents.. Methods: GET. runtime metadata available.
- `Cancel`: Cancels one specific billing document.. Methods: POST. documentation-only until SAP metadata is accessible.
- `CompleteProFormaInvoice`: Completes one specific pro forma invoice.. Methods: POST. documentation-only until SAP metadata is accessible.
- `GetPDF`: Retrieves a specific billing document in PDF format.. Methods: GET. documentation-only until SAP metadata is accessible.

## Business Semantics

- Primary business scope: Billing Document - Read, Cancel, Get PDF, Complete Pro Forma Invoice.
- Use the service description, entity descriptions, and field descriptions from `data/index/API_BILLING_DOCUMENT_SRV` to infer user intent.
- Use this API when the user asks for actual billing documents, invoice numbers, invoice dates, billing document items, billing partners, billing pricing elements, PDFs, cancellation, or pro forma invoice completion.
- Do not use this API merely to determine whether an outbound delivery is billed when the outbound delivery API exposes delivery billing status fields directly.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.

### Customer Billing Documents

- For requests such as `query billing documents for customer 17100003` or `query customer 17100003 invoices`, prefer a direct `A_BillingDocument` header query when the user asks for billing document headers or invoice documents.
- Filter `A_BillingDocument.SoldToParty eq '<customer>'`.
- Select only `A_BillingDocument.BillingDocument`, `A_BillingDocument.SoldToParty`, `A_BillingDocument.CompanyCode`, and `A_BillingDocument.BillingDocumentDate`.
- Do not route through `A_BillingDocumentPartner` unless the user explicitly asks for a non-sold-to partner role. If a partner bridge is required, the final result must still include the customer relationship needed by the user question.
- Do not continue to pricing, item pricing, text, or PDF/function operations unless the user explicitly asks for those details.

### Sales Order Billing Items

- For requests such as `query billing documents for sales order 3773` or `query invoices for sales order 3773`, query `A_BillingDocumentItem` directly.
- Use filter field `A_BillingDocumentItem.SalesDocument` with the sales order number from the user; do not use `A_BillingDocumentItem.OrderID` for this business meaning because it can return no rows even when `SalesDocument` has the source sales order.
- Select only `A_BillingDocumentItem.BillingDocument`, `A_BillingDocumentItem.BillingDocumentItem`, `A_BillingDocumentItem.SalesDocument`, `A_BillingDocumentItem.SalesDocumentItem`, `A_BillingDocumentItem.Material`, and `A_BillingDocumentItem.BillingQuantity`.

### Delivery Billing Items

- For requests such as `query billing items for delivery documents of customer 17100003`, use a cross-API plan with `API_OUTBOUND_DELIVERY_SRV` and this API.
- Step 1: query `API_OUTBOUND_DELIVERY_SRV.A_OutbDeliveryHeader` by `SoldToParty` when the user provides a customer, selecting `DeliveryDocument`, `SoldToParty`, `OverallGoodsMovementStatus`, and `OverallDelivReltdBillgStatus`.
- Step 2: query `A_BillingDocumentItem` by binding `API_OUTBOUND_DELIVERY_SRV.A_OutbDeliveryHeader.DeliveryDocument` to `A_BillingDocumentItem.ReferenceSDDocument`.
- Select only `A_BillingDocumentItem.BillingDocument`, `A_BillingDocumentItem.BillingDocumentItem`, `A_BillingDocumentItem.ReferenceSDDocument`, `A_BillingDocumentItem.ReferenceSDDocumentItem`, `A_BillingDocumentItem.Material`, and `A_BillingDocumentItem.BillingQuantity`.
- Do not ask for clarification merely because the user did not provide specific delivery document numbers; the customer filter in step 1 provides the delivery-document scope.

### Product Master Data For Customer Billing Items

- For requests such as `查询客户17100003开票项目里的物料主数据`, use this API as the source step and `API_PRODUCT_SRV` as the target API.
- Step 1: query `A_BillingDocument` by `A_BillingDocument.SoldToParty` and select only `A_BillingDocument.BillingDocument` and `A_BillingDocument.SoldToParty`.
- Step 2: query `A_BillingDocumentItem` by binding `A_BillingDocument.BillingDocument` to `A_BillingDocumentItem.BillingDocument`; select only `A_BillingDocumentItem.BillingDocument`, `A_BillingDocumentItem.BillingDocumentItem`, and `A_BillingDocumentItem.Material`; add filter `A_BillingDocumentItem.Material ne ''`.
- Step 3: query `API_PRODUCT_SRV.A_Product` by binding `A_BillingDocumentItem.Material` to `A_Product.Product`; select only `A_Product.Product`, `A_Product.ProductType`, `A_Product.ProductGroup`, and `A_Product.BaseUnit`.
- Keep upstream billing/item scope bounded to the first page unless the user explicitly asks for every matching billing item.

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

- Verify entity and field availability against `data/index/API_BILLING_DOCUMENT_SRV` before execution.
- Verify SAP runtime authorization for documentation-only fallback indexes before relying on execution results.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
