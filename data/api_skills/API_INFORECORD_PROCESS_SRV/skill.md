# API_INFORECORD_PROCESS_SRV Skill

## Purpose

Use this API for purchasing info record master data and related purchasing conditions. It covers supplier-material purchasing references, purchasing-organization and plant data, pricing conditions, validity periods, scales, supplementary conditions, and purchasing text.

Keep `data/index/API_INFORECORD_PROCESS_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for purchasing info records, supplier-material purchasing terms, planned purchase prices, purchasing organization or plant-specific info record data.
- The user asks for pricing conditions, condition validity, condition scales, or supplementary pricing conditions tied to an info record.
- The user asks for purchasing text maintained on an info record.

## When Not To Use

- Do not use this API for actual purchase orders, purchase requisitions, supplier invoices, goods receipts, material documents, stock balances, or product master data.
- Do not use this API to determine what was actually ordered, invoiced, or received.

## Key Entities

- `A_PurchasingInfoRecord`: general purchasing info record data.
- `A_PurgInfoRecdOrgPlantData`: purchasing-organization and plant data for a purchasing info record.
- `A_PurInfoRecdPrcgCndn`: pricing condition records.
- `A_PurInfoRecdPrcgCndnValidity`: pricing condition validity details.
- `A_PurInfoRecdPrcgCndnScale`: pricing condition scale details.
- `A_PurInfoRecdSuplmntPrcgCndn`: supplementary pricing conditions.
- `A_PurgInfoRecdOrgPOText`: purchasing PO text maintained on info records.

## Business Semantics

- Purchasing info records are master data/reference data for purchasing. They are not purchase order transactions.
- A supplier-material question about maintained purchasing terms belongs here; a question about actual purchase orders belongs to the purchase order API.
- Pricing conditions and condition validity may require reading condition entities after identifying the relevant info record or condition record.
- Preserve supplier IDs, material IDs, purchasing organizations, plants, condition records, and dates exactly.

## Common Planning Patterns

### Supplier And Material Info Record

- Query `A_PurchasingInfoRecord` when the user asks for the info record itself.
- Use `A_PurgInfoRecdOrgPlantData` when the user asks for purchasing organization or plant-specific data.

### Info Record Pricing

- Query `A_PurInfoRecdPrcgCndn` for condition records.
- Query `A_PurInfoRecdPrcgCndnValidity` when the user asks for validity dates.
- Query `A_PurInfoRecdPrcgCndnScale` when the user asks for scales or quantity breaks.

### Info Record Text

- Query `A_PurgInfoRecdOrgPOText` for purchasing PO text on info records.

## Pitfalls

- Do not treat info record prices as the final price of an already-created purchase order.
- Do not use info records to answer receipt, invoice, or current stock status.
- If the user asks for "purchase orders for material X", route to the purchase order API, not this API.

## Needs Verification

- Whether a user means planned purchasing conditions or actual PO item prices may require clarification when the wording is ambiguous.
