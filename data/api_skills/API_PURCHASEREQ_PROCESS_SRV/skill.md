# API_PURCHASEREQ_PROCESS_SRV Skill

## Purpose

Use this API for purchase requisition transaction data. It covers purchase requisition headers, items, item texts, account assignments, delivery address details, and purchase requisition workflow-related actions.

Keep `data/index/API_PURCHASEREQ_PROCESS_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for purchase requisitions, requisition items, requester-related purchasing demand, material demand before purchase order creation, plant, delivery date, account assignment, item text, or delivery address for purchase requisitions.
- The user explicitly says purchase requisition, PR, requisition, or a local equivalent.

## When Not To Use

- Do not use this API for purchase orders, supplier invoices, material documents, stock balances, product master data, or purchasing info records.
- Do not use this API when the user asks for an already-created purchase order unless they explicitly ask for the originating requisition.

## Key Entities

- `A_PurchaseRequisitionHeader`: purchase requisition header data.
- `A_PurchaseRequisitionItem`: purchase requisition item data.
- `A_PurchaseReqnItemText`: item text for purchase requisition items.
- `A_PurReqnAcctAssgmt`: account assignment lines.
- `A_PurReqAddDelivery`: delivery address details.
- `Validate`: validation operation; not supported by normal read-only query planning.
- `EnableForPurchasing`: action to enable items for purchasing; not supported by normal read-only query planning.
- `DiscardFromPurchasing`: action to discard external processing; not supported by normal read-only query planning.

## Business Semantics

- Purchase requisitions are internal demand/request documents before or separate from purchase orders.
- Purchase order questions belong to the purchase order API unless the user asks for requisition origin or PR conversion.
- Account assignment, delivery address, and item text are item-level details.
- Preserve purchase requisition numbers, item numbers, material IDs, plants, delivery dates, and account assignment values exactly.

## Common Planning Patterns

### Requisition Items

- Query `A_PurchaseRequisitionItem` for item-level PR questions by material, plant, delivery date, requester, status, or item number when available.

### Requisition Header

- Query `A_PurchaseRequisitionHeader` for header-level PR questions.

### Account Assignment And Delivery Address

- Query `A_PurReqnAcctAssgmt` for account assignment details.
- Query `A_PurReqAddDelivery` for delivery address details.

### Requisition Text

- Query `A_PurchaseReqnItemText` when the user asks for item text or notes.

## Pitfalls

- Do not confuse purchase requisitions with purchase orders.
- Do not plan `Validate`, `EnableForPurchasing`, or `DiscardFromPurchasing` actions for ordinary read-only queries.
- Do not use PR status as proof of PO delivery, receipt, or invoice status.

## Needs Verification

- PR-to-PO conversion scenarios may require additional APIs or navigation fields if the exact PO reference is requested.
