# API_INFORECORD_PROCESS_SRV Skill

## Purpose

Use this API for purchasing info record master data and related purchasing conditions. It covers supplier-material purchasing references, purchasing-organization and plant data, pricing conditions, validity periods, scales, supplementary conditions, and purchasing text.

Keep `data/index/API_INFORECORD_PROCESS_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for purchasing info records, supplier-material purchasing terms, planned purchase prices, purchasing organization or plant-specific info record data.
- The user asks for pricing conditions, condition validity, condition scales, or supplementary pricing conditions tied to an info record.
- The user asks for purchasing text maintained on an info record.
- Use this API when the user says "采购信息记录", "信息记录", "info record", "supplier-material purchasing record", "采购价格条件", "价格条件", or "价格条件有效期".

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
- "采购信息记录列表" means list `A_PurchasingInfoRecord`.
- "供应商的采购信息记录" should filter `A_PurchasingInfoRecord.Supplier`.
- "物料的采购信息记录" should filter `A_PurchasingInfoRecord.Material`.
- If the user only asks for "采购信息记录" without saying price, condition, validity, scale, or text, stop at `A_PurchasingInfoRecord`. Do not enrich to pricing condition entities by default.
- "价格条件" should use `A_PurInfoRecdPrcgCndn` and should return actual pricing values, not only condition metadata.
- For price condition results, include value and unit fields such as `A_PurInfoRecdPrcgCndn.ConditionRateAmount`, `A_PurInfoRecdPrcgCndn.ConditionCurrency`, `A_PurInfoRecdPrcgCndn.ConditionRateValue`, `A_PurInfoRecdPrcgCndn.ConditionRateValueUnit`, `A_PurInfoRecdPrcgCndn.ConditionQuantity`, and `A_PurInfoRecdPrcgCndn.ConditionQuantityUnit` when available.
- "价格条件有效期" should use `A_PurInfoRecdPrcgCndnValidity`.

## Common Planning Patterns

### Supplier And Material Info Record

- Query `A_PurchasingInfoRecord` when the user asks for the info record itself.
- Filter `A_PurchasingInfoRecord.Supplier` when a supplier is provided.
- Filter `A_PurchasingInfoRecord.Material` when a material is provided.
- Use `A_PurgInfoRecdOrgPlantData` when the user asks for purchasing organization or plant-specific data.
- Do not add pricing condition or validity steps unless the user explicitly asks for price, condition, validity, scale, or pricing details.

### Info Record Pricing

- Query `A_PurInfoRecdPrcgCndn` for condition records.
- Select `A_PurInfoRecdPrcgCndn.ConditionRecord`, `A_PurInfoRecdPrcgCndn.ConditionSequentialNumber`, `A_PurInfoRecdPrcgCndn.ConditionType`, `A_PurInfoRecdPrcgCndn.ConditionRateAmount`, `A_PurInfoRecdPrcgCndn.ConditionCurrency`, `A_PurInfoRecdPrcgCndn.ConditionRateValue`, `A_PurInfoRecdPrcgCndn.ConditionRateValueUnit`, `A_PurInfoRecdPrcgCndn.ConditionQuantity`, and `A_PurInfoRecdPrcgCndn.ConditionQuantityUnit` for price condition list questions.
- Query `A_PurInfoRecdPrcgCndnValidity` when the user asks for validity dates.
- Filter `A_PurInfoRecdPrcgCndnValidity.Material` or `A_PurInfoRecdPrcgCndnValidity.Supplier` when the question includes material or supplier.
- Query `A_PurInfoRecdPrcgCndnScale` when the user asks for scales or quantity breaks.

### Info Record Text

- Query `A_PurgInfoRecdOrgPOText` for purchasing PO text on info records.

## Pitfalls

- Do not treat info record prices as the final price of an already-created purchase order.
- Do not use info records to answer receipt, invoice, or current stock status.
- If the user asks for "purchase orders for material X", route to the purchase order API, not this API.

## Needs Verification

- Whether a user means planned purchasing conditions or actual PO item prices may require clarification when the wording is ambiguous.
