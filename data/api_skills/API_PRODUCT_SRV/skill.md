# API_PRODUCT_SRV Skill

## Purpose

Use this API for product or material master data. It covers product master records, descriptions, plant data, procurement data, sales data, storage data, units of measure, valuation data, quality management, forecasting, and work scheduling views.

Keep `data/index/API_PRODUCT_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for product/material master attributes, descriptions, base data, product type, plant view, procurement view, sales view, storage view, valuation view, or unit of measure data.
- The user asks to list or identify products by master-data attributes.

## When Not To Use

- Do not use this API for current stock quantities, stock availability, material movement history, purchase orders, purchase requisitions, supplier invoices, or goods receipt history.
- Do not use product descriptions as evidence that a product has stock or purchase orders.

## Key Entities

- `A_Product`: product master header/basic data.
- `A_ProductDescription`: product descriptions by language.
- `A_ProductPlant`: plant-specific product data.
- `A_ProductPlantProcurement`: plant procurement view.
- `A_ProductPlantStorage`: plant storage view.
- `A_ProductProcurement`: basic procurement data.
- `A_ProductSales`: basic sales data.
- `A_ProductSalesDelivery`: sales organization and delivery data.
- `A_ProductStorage`: basic storage data.
- `A_ProductStorageLocation`: storage-location data.
- `A_ProductUnitsOfMeasure`: units of measure.
- `A_ProductValuation`: valuation-area data.

## Business Semantics

- Product master data describes the product/material. It is not transaction history or current stock.
- Basic product master data normally includes `A_Product.Product`, `A_Product.ProductType`, `A_Product.BaseUnit`, status fields, and lifecycle dates.
- Product descriptions are language-dependent; when language matters, use the description entity.
- Plant-specific questions usually require plant-view entities instead of only `A_Product`.
- Preserve product/material IDs, plants, languages, sales organizations, distribution channels, storage locations, and valuation areas exactly.

## Common Planning Patterns

### Product Basic Data

- Query `A_Product` for product-level master data.
- For "产品主数据", "物料主数据", or basic product details by material/product ID, select at least `Product`, `ProductType`, and `BaseUnit` when available.

### Product Description

- Query `A_ProductDescription` when the user asks for name or description.
- Include language filtering when the user specifies a language.

### Plant-Specific Product Data

- Query `A_ProductPlant` or a plant-specific sub-entity when the user asks for plant-level attributes.

### Units And Valuation

- Query `A_ProductUnitsOfMeasure` for units of measure.
- Query `A_ProductValuation` for valuation-area data.

## Pitfalls

- Do not answer current stock from product master views.
- Do not route material purchase order questions to this API unless the user asks for product master data about that material.
- If the user asks for availability on a date, use the availability API when function import support is available.

## Needs Verification

- Some plant-specific or sales-specific attributes may live in a more specific product sub-entity; use schema context to choose the exact entity.
