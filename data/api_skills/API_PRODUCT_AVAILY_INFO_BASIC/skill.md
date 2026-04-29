# API_PRODUCT_AVAILY_INFO_BASIC Skill

## Purpose

Use this API for product availability and ATP-style availability checks. It exposes function imports for availability at a date, availability of a quantity, and availability time series.

Keep `data/index/API_PRODUCT_AVAILY_INFO_BASIC` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks whether a product is available, how much is available, whether a requested quantity can be confirmed, or availability over time.
- The user provides material/product, plant, date, quantity, or ATP checking rule for an availability calculation.
- The user says "是否有货", "是否可用", "可用量", "能否满足", "今天/明天/某日期是否有货", or asks whether a product can be supplied at a plant/date.

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
- Required inputs must be passed as function import parameters, not as `$filter`.
- `DetermineAvailabilityAt` requires `Material` (string), `SupplyingPlant` (string), `ATPCheckingRule` (string), and `RequestedUTCDateTime` (datetimeoffset).
- `DetermineAvailabilityOf` requires `RequestedQuantityInBaseUnit` (decimal), `Material` (string), `SupplyingPlant` (string), and `ATPCheckingRule` (string).
- `CalculateAvailabilityTimeseries` requires `ATPCheckingRule` (string), `Material` (string), and `SupplyingPlant` (string).
- Preserve product/material IDs, plant, dates, quantities, and checking rule values exactly.
- In this local SAP system, generic availability checks should use `ATPCheckingRule` value `A` when the user does not provide a checking rule. Preserve a user-provided checking rule if present. Mention in `response_directive` when the default rule `A` is used.

## Common Planning Patterns

### Availability At Date

- Use `DetermineAvailabilityAt` when the user asks available quantity on a specific date.
- Map material/product wording to `Material`.
- Map plant/factory wording to `SupplyingPlant`.
- Map today/tomorrow/specific date to `RequestedUTCDateTime` as an OData `datetimeoffset` value.
- Use `plan_kind=function_import` and put all inputs in `function_parameters`.

### Availability Of Quantity

- Use `DetermineAvailabilityOf` when the user asks whether a requested quantity can be supplied.
- Map the requested quantity to `RequestedQuantityInBaseUnit` with value_type `decimal`.
- Use `plan_kind=function_import` and put all inputs in `function_parameters`.

### Availability Time Series

- Use `CalculateAvailabilityTimeseries` when the user asks for availability over a date range or time series.
- Use `plan_kind=function_import` and put all inputs in `function_parameters`.

## Pitfalls

- Do not invent an entity-set `$filter` plan for these operations.
- Do not add `$top`, `$select`, `$filter`, `$orderby`, `$skip`, or `$inlinecount` to function import requests.
- Current stock and ATP availability are different business concepts.
- Do not route availability wording to the stock API just because stock quantity fields exist. Stock balance can support inventory listing, but it does not replace ATP/date-based availability calculation.

## Needs Verification

- `ATPCheckingRule=A` has been runtime-verified for `DetermineAvailabilityAt` in this local SAP system. Confirm with business owners before treating it as a universal policy outside this system.
