# API_MATERIAL_STOCK_SRV Skill

## Purpose

Use this API for current material stock balances and serial-number stock data. It covers stock by material, plant, storage location, batch, stock type, special stock, supplier, customer, and serial number where available.

Keep `data/index/API_MATERIAL_STOCK_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for current stock, inventory balance, stock quantity, stock by plant, stock by storage location, stock by batch, or stock by serial number.
- The user asks for stock in account model or stock-specific inventory attributes.

## When Not To Use

- Do not use this API for material movement history, goods receipt history, purchase orders, purchase requisitions, supplier invoices, product master attributes, or ATP availability calculations.
- Do not use this API to explain how stock changed over time.

## Key Entities

- `A_MaterialStock`: material-level stock data and base unit.
- `A_MatlStkInAcctMod`: stock balances in account model.
- `A_MaterialSerialNumber`: serial-number level stock data.

## Business Semantics

- This API is a current stock view. It is not a ledger of movements.
- Material, plant, storage location, batch, stock type, special stock, customer, supplier, and serial number are common stock dimensions.
- For stock history or goods movement details, use the material document API.
- Preserve material IDs, plants, storage locations, batches, and serial numbers exactly.

## Common Planning Patterns

### Stock By Material

- Query `A_MaterialStock` for general stock records by material.
- Query `A_MatlStkInAcctMod` when the user asks for detailed stock quantities by stock account dimensions.

### Stock By Location

- Use plant, storage location, and batch filters on the stock entity that contains the requested dimensions.

### Serial Number Stock

- Query `A_MaterialSerialNumber` when the user asks for serial-number-specific stock.

## Pitfalls

- Do not infer movement dates or receipt history from current stock.
- Do not use product master data to answer current stock quantities.
- If the user asks whether stock will be available on a future date, route to the availability API if function import support is available; otherwise report the limitation.

## Needs Verification

- Special stock and inventory stock type semantics may require business-owner confirmation for user-facing wording.
