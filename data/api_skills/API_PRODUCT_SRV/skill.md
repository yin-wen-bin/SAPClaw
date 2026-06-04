# API_PRODUCT_SRV Skill

## Purpose

Use this API for product or material master data. It covers product master records, descriptions, plant data, procurement data, sales data, storage data, units of measure, valuation data, quality management, forecasting, and work scheduling views.

Keep `data/index/API_PRODUCT_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for product/material master attributes, descriptions, base data, product type, plant view, procurement view, sales view, storage view, valuation view, or unit of measure data.
- The user asks to list or identify products by master-data attributes.

## When Not To Use

- Do not use this API for current stock quantities, stock availability, material movement history, purchase orders, purchase requisitions, supplier invoices, or goods receipt history.
- Do not use this API for stock-context base-unit wording such as `库存基本单位`, `stock base unit`, or `inventory base unit`; route those requests to `API_MATERIAL_STOCK_SRV`, which exposes `MaterialBaseUnit` in stock context.
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
- Product/material tax classification in the sales view is usually sales tax classification detail. For generic "tax classification" questions, prefer `A_ProductSalesTax.Product`, `A_ProductSalesTax.Country`, `A_ProductSalesTax.TaxCategory`, and `A_ProductSalesTax.TaxClassification`.
- `A_ProductSales.TaxClassification` is a similarly named basic sales field, but it is not sufficient evidence for sales tax classification detail. If it is blank, do not conclude that tax classification is not maintained while `A_ProductSalesTax` is available.
- Preserve product/material IDs, plants, languages, sales organizations, distribution channels, storage locations, and valuation areas exactly.

## Common Planning Patterns

### Product Basic Data

- Query `A_Product` for product-level master data.
- For stock-context base-unit wording such as `蠎灘ｭ伜渕譛ｬ蜊穂ｽ港, `stock base unit`, or `inventory base unit`, do not use `API_PRODUCT_SRV`; route those requests to `API_MATERIAL_STOCK_SRV`, which exposes `MaterialBaseUnit` in stock context.
- For product master data, material master data, "产品主数据", "物料主数据", or basic product details by material/product ID, select only `A_Product.Product`, `A_Product.ProductType`, `A_Product.ProductGroup`, and `A_Product.BaseUnit` when available.
- For wording such as `查询物料...的base unit和物料组`, `查询物料...的基本单位和物料组`, or `material base unit and material group`, use `API_PRODUCT_SRV` and `A_Product`; do not route these master-attribute questions to stock, purchase order, info record, or material document APIs.

### Product Description

- Query `A_ProductDescription` when the user asks for name or description.
- Include language filtering when the user specifies a language.

### Plant-Specific Product Data

- Query `A_ProductPlant` or a plant-specific sub-entity when the user asks for plant-level attributes.
- For wording such as `产品主数据中的工厂视图数据`, `产品工厂视图`, `物料工厂视图`, `plant view data`, or `plant-specific product data`, select only `A_ProductPlant.Product`, `A_ProductPlant.Plant`, `A_ProductPlant.PurchasingGroup`, and `A_ProductPlant.CountryOfOrigin`.

### Product Sales Tax Classification

- Query `A_ProductSalesTax` when the user asks for material/product tax classification, sales tax classification, or tax classification in the sales organization data view.
- Select `Product`, `Country`, `TaxCategory`, and `TaxClassification`.
- Filter by `Product eq <material>` when the user only provides a material/product number.
- If the user provides country or tax category, also filter `Country` or `TaxCategory`.
- If the user asks for sales organization or distribution channel context, query `A_ProductSalesDelivery` for `ProductSalesOrg` and `ProductDistributionChnl` and use `to_SalesTax` or a second query to `A_ProductSalesTax` for the tax classification details.
- Do not answer "not maintained" from blank `A_ProductSales.TaxClassification`; first check `A_ProductSalesTax`.

### Units And Valuation

- Query `A_ProductUnitsOfMeasure` for units of measure.
- Query `A_ProductValuation` for valuation-area data.

## Pitfalls

- Do not answer current stock from product master views.
- Do not route material purchase order questions to this API unless the user asks for product master data about that material.
- If the user asks for availability on a date, use the availability API when function import support is available.
- Do not confuse `A_ProductSales.TaxClassification` with `A_ProductSalesTax.TaxClassification`. For tax classification detail, `A_ProductSalesTax` is the more specific entity.

## Needs Verification

- Some plant-specific or sales-specific attributes may live in a more specific product sub-entity; use schema context to choose the exact entity.
