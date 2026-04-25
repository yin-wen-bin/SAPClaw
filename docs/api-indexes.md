# SAP OData API Indexes

This file records local API index assets under `data/index`.

## Additional API Batch

Built on 2026-04-25 from local OpenAPI JSON files plus live SAP `$metadata`.

| API | Raw OpenAPI file | Entities | Fields | Vector docs | Doc chunks | Status |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| API_INFORECORD_PROCESS_SRV | OP_API_INFORECORD_PROCESS_SRV_0001.json | 7 | 204 | 301 | 419 | Indexed |
| API_MATERIAL_DOCUMENT_SRV | OP_API_MATERIAL_DOCUMENT_SRV.json | 5 | 112 | 296 | 180 | Indexed |
| API_MATERIAL_STOCK_SRV | OP_API_MATERIAL_STOCK_SRV.json | 3 | 30 | 86 | 63 | Indexed |
| API_PRODUCT_AVAILY_INFO_BASIC | OP_API_PRODUCT_AVAILY_INFO_BASIC_0001.json | 3 | 0 | 0 | 3 | Limited: function-style API, no entity fields in current index |
| API_PRODUCT_SRV | OP_API_PRODUCT_SRV_0001.json | 32 | 494 | 494 | 1014 | Indexed |
| API_PURCHASEORDER_PROCESS_SRV | OP_API_PURCHASEORDER_PROCESS_SRV_0001.json | 11 | 310 | 484 | 568 | Indexed |
| API_PURCHASEREQ_PROCESS_SRV | OP_API_PURCHASEREQ_PROCESS_SRV_0001.json | 8 | 234 | 344 | 417 | Indexed |
| API_SUPPLIERINVOICE_PROCESS_SRV | OP_API_SUPPLIERINVOICE_PROCESS_SRV.json | 15 | 336 | 336 | 603 | Indexed |

## Notes

- All eight raw OpenAPI specs parse successfully.
- Each spec's first `servers.url` service name matches its index directory name.
- `API_PRODUCT_AVAILY_INFO_BASIC` exposes function-style paths such as `DetermineAvailabilityAt`, not normal entity sets with field metadata. It is available in the catalog, but full execution will need function import planning/compiler support.
- Generated JSON files were validated with Python's runtime JSON parser, matching how the application loads indexes.
