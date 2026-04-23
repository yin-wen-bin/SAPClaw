# Dual-Source Indexing

这套脚手架把两类来源合并成一份本地索引：

1. SAP 实例运行时 `$metadata`
2. 本地 OpenAPI JSON 文档

## 为什么要双源

- `$metadata` 提供运行时真实可用的 entity、field、navigation
- OpenAPI JSON 提供更丰富的字段描述、操作说明和外部文档链接
- 两者冲突时，以 `$metadata` 作为运行时事实来源

## 输出目录

```text
data/index/<service_name>/
  raw/
    <service_name>.metadata.xml
    <openapi-json-file-name>
  services.json
  entities.json
  fields.json
  relations.json
  business_terms.json
  doc_chunks.jsonl
  build_summary.json
```

## 命令

```bash
python -m sap_odata_agent.tools.build_dual_source_index \
  --sap-service-name API_BUSINESS_PARTNER \
  --openapi-json "C:\\Users\\Fujitsu\\Desktop\\OP_API_BUSINESS_PARTNER_SRV.json"
```

如果希望输出目录名和 SAP 实际服务名不同，可以补：

```bash
--index-service-name API_BUSINESS_PARTNER
```

## 当前脚手架会做什么

- 从 `env/.env` 读取 SAP 连接配置
- 请求 `/$metadata`
- 解析 entity set、entity type、field、navigation
- 读取本地 OpenAPI JSON
- 解析 path、schema、field description、tag
- 合并为本地索引
- 把原始 XML 和 JSON 一起落盘

## 代码入口

- 构建器：
  [dual_source_index_builder.py](../src/sap_odata_agent/infrastructure/indexing/dual_source_index_builder.py)
- CLI：
  [build_dual_source_index.py](../src/sap_odata_agent/tools/build_dual_source_index.py)
