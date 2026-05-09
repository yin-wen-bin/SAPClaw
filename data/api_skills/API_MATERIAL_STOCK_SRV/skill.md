# API_MATERIAL_STOCK_SRV Skill

## Purpose

Use this API for current material stock balances and serial-number stock data. It covers stock by material, plant, storage location, batch, stock type, special stock, supplier, customer, and serial number where available.

Keep `data/index/API_MATERIAL_STOCK_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for current stock, inventory balance, stock quantity, stock by plant, stock by storage location, stock by batch, or stock by serial number.
- The user asks for stock in account model or stock-specific inventory attributes.
- Use this API when the user says "库存", "物料库存", "当前库存", "库存数量", "库存地点库存", "工厂库存", "批次库存", "库存基本单位", or "序列号库存".

## When Not To Use

- Do not use this API for material movement history, goods receipt history, purchase orders, purchase requisitions, supplier invoices, product master attributes, or ATP availability calculations.
- Do not use this API to explain how stock changed over time.

## Key Entities

- `A_MaterialStock`: material-level stock data and base unit.
- `A_MatlStkInAcctMod`: stock balances in account model.
- `A_MaterialSerialNumber`: serial-number level stock data.

## Business Semantics

- This API is a current stock view. It is not a ledger of movements.
- Use this API for stock balance/listing wording such as "库存", "当前库存", "库存数量", or "按库存地点/批次/库存类型查看库存".
- Do not treat availability-check wording such as "是否有货", "是否可用", "可用量", "能否满足", or "今天/明天/某日期是否有货" as a stock-balance question when the availability API is available. Those intents belong to `API_PRODUCT_AVAILY_INFO_BASIC`.
- Material, plant, storage location, batch, stock type, special stock, customer, supplier, and serial number are common stock dimensions.
- For stock history or goods movement details, use the material document API.
- Preserve material IDs, plants, storage locations, batches, and serial numbers exactly.
- "库存" without a history or movement phrase means current stock and should route here.
- "物料库存基本单位" uses `A_MaterialStock.MaterialBaseUnit`.
- "按工厂/库存地点/批次/库存类型区分的库存" uses `A_MatlStkInAcctMod`.
- "序列号库存" uses `A_MaterialSerialNumber`.

## Common Planning Patterns

### Stock By Material

- Query `A_MaterialStock` for general stock records by material.
- Query `A_MatlStkInAcctMod` when the user asks for detailed stock quantities by stock account dimensions.
- Filter `A_MaterialStock.Material` or `A_MatlStkInAcctMod.Material` when the user provides a material.
- Select `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit` when the user asks for stock quantity.

### Stock By Location

- Use plant, storage location, and batch filters on the stock entity that contains the requested dimensions.
- Use `A_MatlStkInAcctMod.Plant`, `A_MatlStkInAcctMod.StorageLocation`, and `A_MatlStkInAcctMod.InventoryStockType` for plant/storage-location/stock-type breakdowns.

### Production Order Component Stock

- For production order component stock / 生产订单组件库存 requests, use `API_PRODUCTION_ORDER_2_SRV` together with `API_MATERIAL_STOCK_SRV`.
- Step 1: query `API_PRODUCTION_ORDER_2_SRV.A_ProductionOrderComponent_2` filtered by plant and select `ManufacturingOrder`, `Material`, and `Plant`.
- Step 2: query `API_MATERIAL_STOCK_SRV.A_MatlStkInAcctMod` filtered by the same plant and bind component `Material` to stock `Material`.
- Select stock dimensions and quantity fields such as `Material`, `Plant`, `StorageLocation`, `InventoryStockType`, and `MatlWrhsStkQtyInMatlBaseUnit`.
- Do not ask for a specific production order number when the user asks for plant-level production order component stock.

### MRP Material Stock

- For MRP material stock requests (`MRP物料的库存`), use `API_MRP_MATERIALS_SRV_01` together with `API_MATERIAL_STOCK_SRV`.
- Step 1: query `API_MRP_MATERIALS_SRV_01.A_MRPMaterial` by `A_MRPMaterial.MRPPlant` when the user provides a plant. Select `A_MRPMaterial.Material`, `A_MRPMaterial.MRPPlant`, and `A_MRPMaterial.MRPArea`.
- Step 2: query `A_MatlStkInAcctMod` by binding `A_MatlStkInAcctMod.Material` from Step 1 and filtering/binding `A_MatlStkInAcctMod.Plant` to the same plant. Select `A_MatlStkInAcctMod.Material`, `A_MatlStkInAcctMod.Plant`, `A_MatlStkInAcctMod.StorageLocation`, `A_MatlStkInAcctMod.InventoryStockType`, and `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit`.
- Do not answer MRP material stock by querying stock with only `A_MatlStkInAcctMod.Plant`; first constrain materials through `A_MRPMaterial`.

### Serial Number Stock

- Query `A_MaterialSerialNumber` when the user asks for serial-number-specific stock.
- Filter `A_MaterialSerialNumber.Material` or `A_MaterialSerialNumber.SerialNumber` when provided.

## Pitfalls

- Do not infer movement dates or receipt history from current stock.
- Do not use product master data to answer current stock quantities.
- Do not route current stock questions to `API_PRODUCT_SRV`; product master data does not contain stock balances.
- Do not route current stock questions to `API_MATERIAL_DOCUMENT_SRV`; material documents are movement history.
- If the user asks whether stock will be available on a future date, route to the availability API if function import support is available; otherwise report the limitation.

## Needs Verification

- Special stock and inventory stock type semantics may require business-owner confirmation for user-facing wording.
