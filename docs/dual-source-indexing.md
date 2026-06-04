# 双源索引构建

SAPClaw 的运行时 API 索引由两类信息合并生成：

1. SAP Gateway OData `$metadata`，用于获取实体、字段、类型、导航关系和可执行路径。
2. SAP Business Accelerator Hub OpenAPI JSON specification，用于补充业务描述、文档片段和语义检索材料。

生成后的索引是运行时资产，当前仓库会提交 `data/index/<service_name>/` 下的结构化索引文件，便于本地启动、代码审查和测试复现。

原始 OpenAPI specification JSON 不提交。它们应放在 `data/index/<service_name>/raw/*.json`，并由 `.gitignore` 排除。

## 输出目录

```text
data/index/<service_name>/
  raw/
    <service_name>.metadata.xml
    <openapi-json-file-name>.json       # ignored by Git
  services.json
  entities.json
  fields.json
  relations.json
  business_terms.json
  doc_chunks.jsonl
  vector_documents.jsonl
  build_summary.json
```

当前跟踪策略：

- 跟踪：`services.json`、`entities.json`、`fields.json`、`relations.json`、`business_terms.json`、`doc_chunks.jsonl`、`vector_documents.jsonl`、`build_summary.json`。
- 跟踪：`raw/*.metadata.xml`，因为它是可复现 schema grounding 的主要来源。
- 不跟踪：`data/index/*/raw/*.json`，因为它是外部下载的原始 specification，体积大且可能包含不适合公开的来源信息。
- 不跟踪：`data/index/raw/`、`data/metadata/`、`raw/` 等旧式或临时原始数据目录。

## 构建命令

示例：

```powershell
python -m sap_odata_agent.tools.build_dual_source_index `
  --sap-service-name API_PURCHASEORDER_PROCESS_SRV `
  --openapi-json data\index\API_PURCHASEORDER_PROCESS_SRV\raw\OP_API_PURCHASEORDER_PROCESS_SRV_0001.json `
  --output-root data\index
```

如果 SAP Gateway 服务名和本地索引目录名不同，可以增加：

```powershell
--index-service-name <LOCAL_INDEX_SERVICE_NAME>
```

## 输入要求

- SAP 连接信息从 `env/.env` 或环境变量读取。
- 构建器会在线请求目标 SAP 服务的 `$metadata`。
- 构建器会读取本地 OpenAPI JSON specification。
- 合并结果写入 `data/index/<service_name>/`。

注意：该工具当前是单 API 构建入口，不会自动扫描所有 `data/index/*/raw/*.json` 批量重建。

## 代码入口

- CLI：`src/sap_odata_agent/tools/build_dual_source_index.py`
- Builder：`src/sap_odata_agent/infrastructure/indexing/dual_source_index_builder.py`
- 运行时加载：`src/sap_odata_agent/infrastructure/indexing/index_loader.py`
- Catalog 生成：`src/sap_odata_agent/infrastructure/indexing/api_catalog_provider.py`
