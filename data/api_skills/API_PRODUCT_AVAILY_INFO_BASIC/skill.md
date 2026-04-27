# API_PRODUCT_AVAILY_INFO_BASIC Skill

## Purpose

Use this API for product availability and ATP-style availability checks. It exposes function imports for availability at a date, availability of a quantity, and availability time series.

Keep `data/index/API_PRODUCT_AVAILY_INFO_BASIC` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks whether a product is available, how much is available, whether a requested quantity can be confirmed, or availability over time.
- The user provides material/product, plant, date, quantity, or ATP checking rule for an availability calculation.

## When Not To Use

- Do not use this API for product master data, current stock listing, goods movement history, purchase orders, purchase requisitions, or supplier invoices.
- Do not use this API for ordinary entity-set `$filter` queries when the target operation is a function import.

## Key Entities

- `DetermineAvailabilityAt`: function import for availability at a requested date.
- `DetermineAvailabilityOf`: function import for checking availability of a requested quantity.
- `CalculateAvailabilityTimeseries`: function import for availability time series.

## Business Semantics

- This service is calculation-oriented, not entity-list oriented.
- The available operations are function imports, not normal entity sets.
- Required inputs may include product/material, supplying plant, ATP checking rule, requested date, and requested quantity depending on the operation.
- Preserve product/material IDs, plant, dates, quantities, and checking rule values exactly.

## Common Planning Patterns

### Availability At Date

- Use `DetermineAvailabilityAt` when the user asks available quantity on a specific date.

### Availability Of Quantity

- Use `DetermineAvailabilityOf` when the user asks whether a requested quantity can be supplied.

### Availability Time Series

- Use `CalculateAvailabilityTimeseries` when the user asks for availability over a date range or time series.

## Pitfalls

- The current planner/compiler may not reliably execute function imports as SAP requests.
- Do not invent an entity-set `$filter` plan for these operations.
- Current stock and ATP availability are different business concepts.

## Needs Verification

- Full support requires function import planning/compiler support, including parameter mapping and URL generation for function calls.
