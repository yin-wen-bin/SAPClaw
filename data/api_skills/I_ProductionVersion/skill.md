# I_ProductionVersion Skill

## Purpose

Use this CDS view for production version master data. A production version defines how a material is manufactured in a plant, including validity dates, lot-size range, assigned BOM usage and alternative BOM, bill of operations assignment such as routing or master recipe, production line, and production supply area.

Keep `data/index/I_ProductionVersion` as the schema ground truth. This skill provides business usage guidance only. This index is CDS documentation based and is marked `CDS_VIEW_ONLY`. It is not a SAP Gateway OData service and must not be planned or executed as `/sap/opu/odata/sap/I_ProductionVersion/...`.

## When To Use

- The user asks for production versions, manufacturing versions, production alternatives, or "sheng chan ban ben" for a material/product and plant.
- The user asks which BOM, alternative BOM, BOM usage, routing, task list, master recipe, production line, or production supply area is assigned through a production version.
- The user asks whether a production version is valid for a date, lot size, material, and plant.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/I_ProductionVersion`.

## When Not To Use

- Do not use this view for actual production order execution, confirmations, goods movements, or order status. Use production order, process order, or material document APIs for those domains.
- Do not use this view for full BOM item explosion. Use the BOM API when the user asks for components or BOM item details.
- Do not use this view for full routing operation details. Use the production routing API or master recipe API when the user asks for operation steps, work centers, phases, or standard values.
- Do not plan OData execution directly for this service unless a real exposed OData binding is added later.

## Key Entities

- `I_ProductionVersion`: Production Version. CDS_VIEW_ONLY; documentation-only for this OData agent.

## Business Semantics

- Primary business scope: production version master data by `Material`, `Plant`, and `ProductionVersion`.
- A production version connects a material and plant to manufacturing master data: BOM usage/alternative BOM and bill of operations group/variant.
- `BillOfOperationsType`, `BillOfOperationsGroup`, and `BillOfOperationsVariant` identify the routing, rate routing, or master recipe assignment level. Do not treat them as production order operation records.
- `BillOfMaterialVariantUsage` and `BillOfMaterialVariant` identify BOM usage and alternative BOM. They are not BOM components.
- `MaterialMinLotSizeQuantity` and `MaterialMaxLotSizeQuantity` define lot-size applicability.
- `ValidityStartDate` and `ValidityEndDate` define date applicability.
- `ProductionVersionIsLocked`, `ProductionVersionStatus`, `BOMCheckStatus`, `RateBasedPlanningStatus`, and `PreliminaryPlanningStatus` are status/eligibility fields; do not infer execution success from them.

## Common Planning Patterns

### Production Versions For A Material And Plant

- Query `I_ProductionVersion`.
- Filter by `Material` and `Plant` when provided.
- Select `I_ProductionVersion.Material`, `I_ProductionVersion.Plant`, `I_ProductionVersion.ProductionVersion`, `I_ProductionVersion.ProductionVersionText`, `I_ProductionVersion.ValidityStartDate`, `I_ProductionVersion.ValidityEndDate`, `I_ProductionVersion.MaterialMinLotSizeQuantity`, `I_ProductionVersion.MaterialMaxLotSizeQuantity`, and `I_ProductionVersion.ProductionVersionStatus`.

### BOM And Routing Assignment

- Use `I_ProductionVersion` when the user asks which BOM/routing/master recipe is assigned by the production version.
- Select `I_ProductionVersion.Material`, `I_ProductionVersion.Plant`, `I_ProductionVersion.ProductionVersion`, `I_ProductionVersion.BillOfMaterialVariantUsage`, `I_ProductionVersion.BillOfMaterialVariant`, `I_ProductionVersion.BillOfOperationsType`, `I_ProductionVersion.BillOfOperationsGroup`, and `I_ProductionVersion.BillOfOperationsVariant`.
- If the user asks for BOM components, route to the BOM API after identifying the assigned BOM information.
- If the user asks for routing operations or master recipe phases, route to the production routing or master recipe API after identifying the assignment information.

### Valid Production Version For Date Or Lot Size

- Filter by `Material` and `Plant`.
- Apply date logic against `ValidityStartDate` and `ValidityEndDate` when the user gives a date.
- Apply lot-size logic against `MaterialMinLotSizeQuantity` and `MaterialMaxLotSizeQuantity` when the user gives a quantity.
- Select the production version plus status fields and assigned BOM/routing fields needed to explain the choice.

### Production Line Or Supply Area

- Use `I_ProductionVersion.ProductionLine` when the user asks which production line is assigned.
- Use `I_ProductionVersion.ProductionSupplyArea` when the user asks for PSA, supply area, staging area, or production supply area.

## Runtime Availability

- This index is `CDS_VIEW_ONLY`. Use it only for schema/business semantics in the current OData-only agent.
- If the user expects execution, explain that the view requires an exposed OData binding or a CDS/ABAP SQL-capable access path before this OData agent can execute it.

## Pitfalls

- Do not confuse a production version with a production order, planned order, BOM header, BOM item, routing operation, or master recipe phase.
- Do not answer component-level or operation-level details from the production version assignment fields alone.
- Do not compile this service into a SAP Gateway OData URL.

## Needs Verification

- Verify entity and field availability against `data/index/I_ProductionVersion` before planning.
- Verify backend exposure if execution is required.
