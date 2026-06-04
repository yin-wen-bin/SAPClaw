# SAP OData API 索引清单

本文档记录当前仓库中已提交的本地 API 索引资产，目录位于 `data/index/`。

最后核对日期：2026-06-04。

## 当前状态

- 当前 `data/index/` 下共有 53 个 API 索引目录。
- 每个目录的核心运行时文件来自 `build_summary.json`、`services.json`、`entities.json`、`fields.json`、`relations.json`、`doc_chunks.jsonl` 和 `vector_documents.jsonl`。
- `data/index/*/raw/*.json` 下的原始 OpenAPI specification JSON 已被 `.gitignore` 排除，当前没有被 Git 跟踪。
- `data/index/*/raw/*.metadata.xml` 可作为 schema grounding 的可复现来源，当前允许提交。
- `C_TRIALBALANCE_CDS/vector_documents.jsonl` 体积较大，GitHub 会提示超过 50 MB 的建议上限。如果后续要更严格控制公开仓库体积，应优先考虑压缩该索引、拆分索引，或改用 Git LFS。

## 当前索引目录

| API | Entities | Fields | Vector docs | Doc chunks |
| --- | ---: | ---: | ---: | ---: |
| API_BATCH_SRV | 6 | 64 | 85 | 146 |
| API_BILL_OF_MATERIAL_SRV_0002 | 14 | 198 | 198 | 359 |
| API_BILLING_DOCUMENT_SRV | 11 | 339 | 365 | 602 |
| API_BUSINESS_PARTNER | 62 | 1054 | 1097 | 2230 |
| API_COMPANYCODE_SRV | 1 | 21 | 21 | 35 |
| API_COSTCENTER_SRV | 2 | 38 | 38 | 64 |
| API_CREDIT_MEMO_REQUEST_SRV | 22 | 315 | 401 | 636 |
| API_CUSTOMER_MATERIAL_SRV | 1 | 22 | 44 | 42 |
| API_CUSTOMER_RETURN_SRV | 17 | 301 | 418 | 580 |
| API_DEBIT_MEMO_REQUEST_SRV | 11 | 265 | 291 | 517 |
| API_GLACCOUNTINCHARTOFACCOUNTS_SRV | 2 | 25 | 25 | 51 |
| API_GLACCOUNTLINEITEM | 1 | 249 | 747 | 316 |
| API_INFORECORD_PROCESS_SRV | 7 | 204 | 301 | 419 |
| API_JOURNALENTRYITEMBASIC_SRV | 5 | 263 | 420 | 368 |
| API_LEDGER_SRV | 2 | 7 | 7 | 19 |
| API_MASTER_RECIPE | 10 | 444 | 651 | 672 |
| API_MATERIAL_DOCUMENT_SRV | 5 | 112 | 296 | 180 |
| API_MATERIAL_STOCK_SRV | 3 | 30 | 86 | 63 |
| API_MRP_MATERIALS_SRV_01 | 3 | 165 | 165 | 220 |
| API_OPLACCTGDOCITEMCUBE_SRV | 1 | 271 | 813 | 375 |
| API_OUTBOUND_DELIVERY_SRV | 28 | 449 | 577 | 512 |
| API_PARTNERCOMPANY_SRV | 1 | 3 | 3 | 6 |
| API_PAYMENT_ADVICE_SRV | 2 | 82 | 82 | 149 |
| API_PHYSICAL_INVENTORY_DOC_SRV | 7 | 77 | 169 | 136 |
| API_PLANNED_ORDERS | 5 | 136 | 195 | 223 |
| API_PLND_INDEP_RQMT_SRV | 2 | 34 | 34 | 64 |
| API_PROCESS_ORDER_2_SRV | 17 | 339 | 372 | 557 |
| API_PRODUCT_AVAILY_INFO_BASIC | 3 | 0 | 0 | 3 |
| API_PRODUCT_SRV | 32 | 494 | 494 | 1014 |
| API_PRODUCTGROUP_SRV | 2 | 6 | 6 | 16 |
| API_PRODUCTION_ORDER_2_SRV | 20 | 524 | 557 | 854 |
| API_PRODUCTION_ROUTING | 25 | 684 | 905 | 953 |
| API_PROFITCENTER_SRV | 3 | 45 | 45 | 75 |
| API_PUR_QUOTA_ARRANGEMENT_SRV | 2 | 33 | 55 | 74 |
| API_PURCHASECONTRACT_PROCESS_SRV_0002 | 17 | 397 | 459 | 745 |
| API_PURCHASEORDER_PROCESS_SRV | 11 | 310 | 484 | 568 |
| API_PURCHASEREQ_PROCESS_SRV | 8 | 234 | 344 | 417 |
| API_PURGPRCGCONDITIONRECORD_SRV | 4 | 135 | 180 | 265 |
| API_QTN_PROCESS_SRV | 7 | 76 | 113 | 146 |
| API_RESERVATION_DOCUMENT_SRV | 2 | 51 | 102 | 97 |
| API_RFQ_PROCESS_SRV | 6 | 63 | 67 | 131 |
| API_SALES_CONTRACT_SRV | 11 | 222 | 248 | 426 |
| API_SALES_ORDER_SRV | 25 | 582 | 624 | 1172 |
| API_SALES_QUOTATION_SRV | 17 | 290 | 316 | 598 |
| API_SCHED_AGRMT_PROCESS_SRV | 12 | 244 | 381 | 477 |
| API_SEGMENT_SRV | 2 | 4 | 4 | 14 |
| API_SERVICE_ENTRY_SHEET_SRV | 6 | 114 | 139 | 213 |
| API_SLSPRICINGCONDITIONRECORD_SRV | 6 | 305 | 651 | 541 |
| API_SUPPLIERINVOICE_PROCESS_SRV | 15 | 336 | 336 | 603 |
| API_WORK_CENTERS | 19 | 398 | 398 | 703 |
| C_TRIALBALANCE_CDS | 279 | 28556 | 84942 | 29371 |
| I_ProductionVersion | 1 | 46 | 47 | 47 |
| I_PurchaseOrderHistoryAPI01 | 1 | 56 | 57 | 57 |

## 使用注意

- 是否能执行 SAP OData 请求，取决于该 API 是否在目标 SAP 系统中激活、是否暴露为 Gateway OData 服务，以及当前用户权限。
- `API_PRODUCT_AVAILY_INFO_BASIC` 是 function-style API，当前索引没有普通实体字段，执行时需要 Function Import 参数规划能力。
- `I_*` 命名的索引可能来自 CDS/API View。若目标系统未通过 Gateway OData 暴露对应服务，运行时不能直接按 `/sap/opu/odata/sap/<service>` 调用。
- API 专属业务知识应沉淀在 `data/api_skills/<service_name>/skill.md`，不要把单个业务场景写入通用 Router 或通用 Planner 规则。
