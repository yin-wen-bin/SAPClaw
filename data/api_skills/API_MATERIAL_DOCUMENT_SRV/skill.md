# API_MATERIAL_DOCUMENT_SRV Skill

## Purpose

Use this API for material document and goods movement history. It covers material document headers, material document items, and serial numbers linked to material document items.

Keep `data/index/API_MATERIAL_DOCUMENT_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for goods movements, goods receipts, goods issues, transfers, material document numbers, posting dates, document dates, movement types, or historical material movement records.
- The user asks for material document item details by material, plant, storage location, batch, supplier, customer, or purchase order reference when those fields are available in the schema.
- The user asks for serial numbers tied to material documents.

## When Not To Use

- Do not use this API for current stock balances, product master data, purchase order master status, purchase requisitions, or supplier invoice headers.
- Do not use this API to execute cancellation actions in the current read-only query flow.

## Key Entities

- `A_MaterialDocumentHeader`: material document header data, including document and posting dates.
- `A_MaterialDocumentItem`: material document item data, including material movement details.
- `A_SerialNumberMaterialDocument`: serial numbers for material document items.
- `Cancel`: function/action for cancellation; not supported by the current read-only planning flow.
- `CancelItem`: function/action for item cancellation; not supported by the current read-only planning flow.

## Business Semantics

- Material documents represent historical movements, not current inventory snapshots.
- Goods receipt and goods issue questions about actual posted movement history usually belong here.
- Current stock or available quantity questions belong to stock or availability APIs, not material documents.
- Preserve material document numbers, fiscal years, material IDs, movement types, plants, storage locations, and dates exactly.

## Common Planning Patterns

### Material Movement By Material Or Plant

- Query `A_MaterialDocumentItem` when the user asks for movement history by material, plant, storage location, batch, or movement type.
- Select document keys and requested movement fields.

### Movement By Posting Or Document Date

- Query `A_MaterialDocumentHeader` when the requested filter is header-level date or header text.
- If item details are required, use a multi-step plan from header to `A_MaterialDocumentItem`.

### Serial Number Movement

- Query `A_SerialNumberMaterialDocument` when the user asks for serial numbers in material documents.

## Pitfalls

- Do not answer current stock from historical movement records.
- Do not plan `Cancel` or `CancelItem` actions for normal user queries; the current agent is query-focused.
- A purchase order can have related material documents, but purchase order header/item status should still come from the purchase order API.

## Needs Verification

- Movement-type interpretation and receipt/issue business meaning may require business-owner confirmation for complex scenarios.
