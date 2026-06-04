# API_MATERIAL_STOCK_SRV Skill

## Purpose

Use this API for current material stock balances and serial-number stock data. It covers stock by material, plant, storage location, batch, stock type, special stock, supplier, customer, and serial number where available.

Keep `data/index/API_MATERIAL_STOCK_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for current stock, inventory balance, stock quantity, stock by plant, stock by storage location, stock by batch, or stock by serial number.
- The user asks "库存", "当前库存", "物料库存", "库存数量", "工厂库存", "库存地点库存", "批次库存", "物料层级库存", "物料级库存", or "序列号库存".
- Use this API for stock-balance questions, not for movement history.

## When Not To Use

- Do not use this API for material movement history, goods receipt history, purchase orders, purchase requisitions, supplier invoices, product master attributes, or ATP availability calculations.
- Do not use this API to explain how stock changed over time.
- Do not route availability-check wording such as "是否有货", "是否可用", "可用量", "能否满足", or "今天/明天/某日期是否有货" here when `API_PRODUCT_AVAILY_INFO_BASIC` is available.

## Key Entities

- `A_MaterialStock`: material-level master stock record and base unit.
- `A_MatlStkInAcctMod`: current stock balances in account model. Use this for quantities and stock dimensions.
- `A_MaterialSerialNumber`: serial-number level stock data.

## Business Semantics

- This API is a current stock view. It is not a ledger of movements.
- Material, plant, storage location, batch, stock type, special stock, customer, supplier, and serial number are stock dimensions.
- Preserve material IDs, plants, storage locations, batches, and serial numbers exactly.
- For stock history or goods movement details, use the material document API.
- `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit` is the quantity field for stock balance in material base unit.
- `A_MatlStkInAcctMod.MaterialBaseUnit` is the stock quantity unit.

## Stock Output Levels

- "物料层级库存", "物料级库存", "物料层面库存", "material level stock", or "by material stock" means the answer must be aggregated by material, plant, and unit. It must not be displayed at batch, storage-location, stock-type, or special-stock detail unless the user explicitly asks for those breakdowns.
- "批次层级库存", "按批次库存", or "batch stock" means include `A_MatlStkInAcctMod.Batch`.
- "库存地点层级库存", "按库存地点库存", or "storage-location stock" means include `A_MatlStkInAcctMod.StorageLocation`.
- "库存类型层级库存", "按库存类型库存", or "stock-type stock" means include `A_MatlStkInAcctMod.InventoryStockType`.

## Common Planning Patterns

### Stock By Material

- Query `A_MaterialStock` for stock master records only when the user asks for stock, inventory, or quantity context.
- Do not use `API_MATERIAL_STOCK_SRV` for product/material master attributes such as `base unit`, `basic unit`, `物料组`, `material group`, or product type unless the user also asks for stock or inventory quantity. Route those master-attribute questions to `API_PRODUCT_SRV`.
- For stock-context base-unit wording such as `库存基本单位`, `stock base unit`, or `inventory base unit`, use `API_MATERIAL_STOCK_SRV.A_MaterialStock` and select `A_MaterialStock.Material` plus `A_MaterialStock.MaterialBaseUnit`; this is not the same as a standalone product master `BaseUnit` request.
- Query `A_MatlStkInAcctMod` when the user asks for stock quantity.
- Filter `A_MaterialStock.Material` or `A_MatlStkInAcctMod.Material` when the user provides a material.
- Select `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit` when the user asks for stock quantity.

### Material-Level Stock

- For requests such as "查询物料2211在工厂1710的物料层级库存", answer from `A_MatlStkInAcctMod`.
- Filter `A_MatlStkInAcctMod.Material` and `A_MatlStkInAcctMod.Plant` when material and plant are provided.
- For material-level stock requests such as "物料层级", "物料层级库存", "物料层级的库存", or "物料级库存", select only `A_MatlStkInAcctMod.Material`, `A_MatlStkInAcctMod.Plant`, `A_MatlStkInAcctMod.MaterialBaseUnit`, and `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit`.
- For material-level stock requests such as "物料层级", "物料层级库存", "物料层级的库存", or "物料级库存", use result_transform aggregate: group_by: `A_MatlStkInAcctMod.Material`, `A_MatlStkInAcctMod.Plant`, `A_MatlStkInAcctMod.MaterialBaseUnit`; sum_fields: `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit`.
- Do not select `A_MatlStkInAcctMod.Batch`, `A_MatlStkInAcctMod.StorageLocation`, `A_MatlStkInAcctMod.InventoryStockType`, or `A_MatlStkInAcctMod.InventorySpecialStockType` unless the user explicitly asks for that detail level.

### Stock By Location

- Use `A_MatlStkInAcctMod.Plant`, `A_MatlStkInAcctMod.StorageLocation`, and `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit` for plant/storage-location stock breakdowns.
- For plant/storage-location breakdown wording such as `按工厂和库存地点区分的库存`, `stock by plant and storage location`, or `plant storage-location stock breakdown`, use result_transform aggregate: group_by: `A_MatlStkInAcctMod.Plant`, `A_MatlStkInAcctMod.StorageLocation`; sum_fields: `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit`, unless the user explicitly asks for material-level rows.
- Include `A_MatlStkInAcctMod.Batch` only when the user asks for batch-level stock.
- Include `A_MatlStkInAcctMod.InventoryStockType` only when the user asks for stock-type breakdown.

### Production Order Component Stock

- For production order component stock requests, use `API_PRODUCTION_ORDER_2_SRV` together with `API_MATERIAL_STOCK_SRV`.
- Step 1: query `API_PRODUCTION_ORDER_2_SRV.A_ProductionOrderComponent_2` filtered by plant and select `ManufacturingOrder`, `Material`, and `Plant`.
- Step 2: query `API_MATERIAL_STOCK_SRV.A_MatlStkInAcctMod` filtered by the same plant and bind component `Material` to stock `Material`.
- Select stock dimensions and quantity fields such as `Material`, `Plant`, `StorageLocation`, `InventoryStockType`, and `MatlWrhsStkQtyInMatlBaseUnit`.
- Do not ask for a specific production order number when the user asks for plant-level production order component stock.

### MRP Material Stock

- For MRP material stock requests, use `API_MRP_MATERIALS_SRV_01` together with `API_MATERIAL_STOCK_SRV`.
- Step 1: query `API_MRP_MATERIALS_SRV_01.A_MRPMaterial` by `API_MRP_MATERIALS_SRV_01.A_MRPMaterial.MRPPlant` when the user provides a plant. Select `API_MRP_MATERIALS_SRV_01.A_MRPMaterial.Material`, `API_MRP_MATERIALS_SRV_01.A_MRPMaterial.MRPPlant`, and `API_MRP_MATERIALS_SRV_01.A_MRPMaterial.MRPArea`.
- Step 2: query `A_MatlStkInAcctMod` by binding `A_MatlStkInAcctMod.Material` from Step 1 and filtering/binding `A_MatlStkInAcctMod.Plant` to the same plant. Select `A_MatlStkInAcctMod.Material`, `A_MatlStkInAcctMod.Plant`, `A_MatlStkInAcctMod.StorageLocation`, `A_MatlStkInAcctMod.InventoryStockType`, and `A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit`.
- Do not answer MRP material stock by querying stock with only `A_MatlStkInAcctMod.Plant`; first constrain materials through `API_MRP_MATERIALS_SRV_01.A_MRPMaterial`.

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
