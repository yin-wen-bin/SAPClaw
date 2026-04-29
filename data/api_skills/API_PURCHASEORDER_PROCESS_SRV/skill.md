# API_PURCHASEORDER_PROCESS_SRV Skill

## Purpose

Use this API for purchase order transaction questions. It covers purchase order headers, items, schedule lines, account assignments, pricing elements, notes, and subcontracting components.

Keep `data/index/API_PURCHASEORDER_PROCESS_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for purchase orders by supplier, material, plant, company code, creation date, delivery date, item status, invoice status, or goods receipt status.
- The user asks for purchase order items, item-level quantities, item-level material, delivery completion, final invoice status, schedule lines, account assignments, pricing, notes, or subcontracting components.
- The user asks for "未收货采购订单", "未完全交货采购订单", "未清发票采购订单", "物料采购订单", or "交货日期相关采购订单".

## When Not To Use

- Do not use this API for supplier/customer master data, purchase requisitions, current stock balances, product master data, or general material document history.
- Do not use this API for supplier invoice documents unless the user means purchase orders that are not finally invoiced.
- Do not use this API alone to answer true purchase order history when the user means goods receipts, invoice receipts, material documents, GR/IR history, or change history. Ask for clarification or use a history-capable API if available.

## Key Entities

- `A_PurchaseOrder`: purchase order header. Use for header-level attributes such as `PurchaseOrder`, `Supplier`, `CompanyCode`, `CreationDate`, `PurchasingProcessingStatus`, and deletion/status fields.
- `A_PurchaseOrderItem`: purchase order item. Use for item-level attributes such as `PurchaseOrder`, `PurchaseOrderItem`, `Material`, `Plant`, `IsCompletelyDelivered`, `IsFinallyInvoiced`, `GoodsReceiptIsExpected`, quantities, and item deletion/status fields.
- `A_PurchaseOrderScheduleLine`: schedule line. Use for delivery schedule questions such as `ScheduleLineDeliveryDate`.
- `A_PurOrdAccountAssignment`: account assignment lines for purchase order items.
- `A_PurOrdPricingElement`: pricing condition lines for purchase order items.
- `A_POSubcontractingComponent`: subcontracting component details for purchase order items.

## Business Semantics

- For "未收货", "未完全收货", "未完全交货", or "undelivered purchase orders", prefer `A_PurchaseOrderItem.IsCompletelyDelivered eq false`.
- For "需要收货但未收货", "待收货", or "needs goods receipt but not yet received", use both `A_PurchaseOrderItem.GoodsReceiptIsExpected eq true` and `A_PurchaseOrderItem.IsCompletelyDelivered eq false`.
- `GoodsReceiptIsExpected` alone is not enough to prove unreceived status. It means goods receipt is expected or required, not whether receipt has been completed. It can be used together with `IsCompletelyDelivered eq false` when the user explicitly asks for orders that need goods receipt but are not yet received.
- For "未清发票", "未完成发票", or "open invoice purchase orders", prefer `A_PurchaseOrderItem.IsFinallyInvoiced eq false`.
- For material-based purchase order questions, filter on `A_PurchaseOrderItem.Material`.
- For supplier-based purchase order questions, filter on `A_PurchaseOrder.Supplier`. If final output needs item-level fields, use a multi-step plan from header to item through `PurchaseOrder`.
- For delivery-date purchase order questions, filter on `A_PurchaseOrderScheduleLine.ScheduleLineDeliveryDate`.
- "Purchase order history", "PO history", or "采购订单历史记录" is ambiguous. It can mean purchase order structure/details, or follow-on history such as goods receipt, invoice receipt, material documents, and changes. Do not treat it as pricing by default.
- `A_PurOrdPricingElement` contains pricing condition lines only. It is not purchase order history and must not be used as the main answer for a history request unless the user explicitly asks for pricing, price conditions, or pricing elements.
- User-specified values such as supplier IDs, material IDs, purchase order numbers, dates, plants, and company codes must be preserved exactly.

## Common Planning Patterns

### Supplier Purchase Orders

- Header-level answer: query `A_PurchaseOrder` with `Supplier eq <supplier>`.
- Item-level answer: first query `A_PurchaseOrder` by supplier and select `PurchaseOrder`, then query `A_PurchaseOrderItem` bound by `PurchaseOrder`.

### Material Purchase Orders

- Query `A_PurchaseOrderItem` with `Material eq <material>`.
- Select `PurchaseOrder`, `PurchaseOrderItem`, `Material`, and any requested item-level fields.
- Enrich from `A_PurchaseOrder` only when supplier, company code, header status, or creation date is needed.

### Unreceived Or Not Completely Delivered Purchase Orders

- Use `A_PurchaseOrderItem.IsCompletelyDelivered eq false`.
- If the user also provides supplier, use `A_PurchaseOrder.Supplier` to find purchase orders, then query `A_PurchaseOrderItem` by `PurchaseOrder` and `IsCompletelyDelivered eq false`.
- Avoid `GoodsReceiptIsExpected` as the only status filter for this scenario.

### Needs Goods Receipt But Not Yet Received

- Use this pattern when the user asks for "需要收货但未收货", "待收货", or "needs goods receipt but not yet received".
- If supplier is provided, first query `A_PurchaseOrder` with `Supplier eq <supplier>` and select `PurchaseOrder`.
- Then query `A_PurchaseOrderItem` bound by `PurchaseOrder`.
- Add both item-level filters:
  - `GoodsReceiptIsExpected eq true`
  - `IsCompletelyDelivered eq false`
- Select `PurchaseOrder`, `PurchaseOrderItem`, `GoodsReceiptIsExpected`, `IsCompletelyDelivered`, and requested item fields such as `Material`, `Plant`, `StorageLocation`, and `OrderQuantity`.

### Open Invoice Purchase Orders

- Use `A_PurchaseOrderItem.IsFinallyInvoiced eq false`.
- If the user provides supplier, combine supplier filtering from `A_PurchaseOrder` with item filtering on `A_PurchaseOrderItem.IsFinallyInvoiced`.

### Delivery Date Purchase Orders

- Use `A_PurchaseOrderScheduleLine.ScheduleLineDeliveryDate` for delivery date filters.
- Select `PurchaseOrder`, `PurchaseOrderItem`, `ScheduleLine`, and `ScheduleLineDeliveryDate`.
- Enrich to item or header only when the user asks for fields not present on schedule lines.

### Purchase Order History Wording

- If the user asks for "purchase order history", "PO history", or "采购订单历史记录" without specifying the history type, ask a clarification before execution.
- Clarify whether the user wants purchase order structure/details, or follow-on history such as goods receipts, invoice receipts, material documents, or change history.
- If the user clarifies that they want purchase order structure/details, a multi-step plan may retrieve header, items, schedule lines, account assignments, notes, subcontracting components, and pricing as separate sections.
- If the user clarifies that they want pricing history or pricing conditions, query `A_PurOrdPricingElement`.
- If the user wants goods receipt, invoice receipt, material document, or change history, do not answer from `A_PurOrdPricingElement`; this API may be insufficient by itself.

## Pitfalls

- `GoodsReceiptIsExpected` alone is not proof that goods have not been received. It must be paired with `IsCompletelyDelivered eq false` for "needs goods receipt but not yet received" questions.
- Do not answer item-level questions from header-only data when item fields are required.
- Do not answer schedule-line delivery date questions from header creation date or item-level generic dates.
- Do not label `A_PurOrdPricingElement` results as purchase order history. Pricing elements are only price condition details.
- Do not treat `$top` as a user-requested semantic limit unless the user explicitly asks for "前 N 条", "top N", or a similar limit.
- Date filters must use the OData V2 literal syntax accepted by this SAP service. For `Edm.DateTime`, use a datetime literal such as `datetime'2018-11-23T00:00:00'`.

## Needs Verification

- Whether `IsFinallyInvoiced eq false` alone is sufficient for every business interpretation of "未清发票订单" may require business-owner confirmation.
- More complex receipt status questions may require material document history APIs in addition to purchase order item status.
