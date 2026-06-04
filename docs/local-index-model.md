# Local Documentation Index Model

## 1. 作用定位

本地文档索引结构不是单纯存放 OData 文档，而是把 SAP OData 知识整理成两类资产：

1. 结构化索引
   - 给规划、校验、编译使用
   - 解决 service、entity set、field、filter operator 的精确匹配问题
2. 文本索引
   - 给语义检索使用
   - 解决“业务说法”和“SAP 技术字段”之间的语义映射问题

## 2. 当前目录结构

```text
data/
  index/
    <service_name>/
      raw/
        <service_name>.metadata.xml
        <openapi-json-file-name>.json
      services.json
      entities.json
      fields.json
      relations.json
      business_terms.json
      doc_chunks.jsonl
      vector_documents.jsonl
      build_summary.json
  api_skills/
    <service_name>/
      skill.md
  cases/
    cases.jsonl
    feedback_memory.jsonl
    feedback_events.jsonl
```

当前仓库会提交 `data/index/<service_name>/` 下的运行时索引文件，但不提交 `data/index/*/raw/*.json` 原始 OpenAPI specification。

## 3. 结构化索引

### 3.1 `services.json`

存放 service 级别元数据。

```json
[
  {
    "service_name": "API_BUSINESS_PARTNER",
    "service_version": "v1",
    "base_path": "/sap/opu/odata/sap/API_BUSINESS_PARTNER",
    "description": "Business partner master data service",
    "entity_sets": ["A_BusinessPartner", "A_BusinessPartnerAddress"],
    "allowed_methods": ["GET"],
    "source": "metadata.xml"
  }
]
```

字段建议：

- `service_name`
- `service_version`
- `base_path`
- `description`
- `entity_sets`
- `allowed_methods`
- `source`

### 3.2 `entities.json`

存放 entity set 级别信息。

```json
[
  {
    "service_name": "API_BUSINESS_PARTNER",
    "entity_set": "A_BusinessPartner",
    "entity_type": "A_BusinessPartnerType",
    "key_fields": ["BusinessPartner"],
    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName", "Customer"],
    "supports_filter": true,
    "supports_orderby": true,
    "supports_top": true,
    "navigations": ["to_BusinessPartnerAddress"],
    "description": "Business partner header data"
  }
]
```

### 3.3 `fields.json`

这是最关键的一层，给校验器和 planner 使用。

```json
[
  {
    "service_name": "API_BUSINESS_PARTNER",
    "entity_set": "A_BusinessPartner",
    "field_name": "BusinessPartner",
    "label": "Business Partner",
    "business_aliases": ["客户", "客户编码", "业务伙伴", "BP"],
    "data_type": "Edm.String",
    "nullable": false,
    "is_key": true,
    "selectable": true,
    "filterable": true,
    "sortable": true,
    "allowed_operators": ["eq", "ne", "in"],
    "description": "Business partner identifier"
  }
]
```

字段建议：

- `field_name`
- `label`
- `business_aliases`
- `data_type`
- `nullable`
- `is_key`
- `selectable`
- `filterable`
- `sortable`
- `allowed_operators`
- `description`

### 3.4 `relations.json`

保存 entity 之间的导航关系，后面做复杂查询会用到。

```json
[
  {
    "service_name": "API_BUSINESS_PARTNER",
    "from_entity_set": "A_BusinessPartner",
    "navigation_name": "to_BusinessPartnerAddress",
    "to_entity_set": "A_BusinessPartnerAddress",
    "cardinality": "1:n"
  }
]
```

## 4. 术语别名索引

### 4.1 `business_terms.json`

它解决“用户怎么说”和“SAP 里怎么叫”之间的映射问题。

```json
[
  {
    "term": "客户",
    "intent_type": "entity_lookup",
    "mapped_service": "API_BUSINESS_PARTNER",
    "mapped_entity_set": "A_BusinessPartner",
    "mapped_fields": ["BusinessPartner", "Customer", "BusinessPartnerFullName"],
    "synonyms": ["客商", "客户主数据", "BP"],
    "confidence": 0.95
  }
]
```

这个文件很重要，因为真实业务里，用户几乎不会按 SAP 官方字段名说话。

## 5. 文本索引

### 5.1 `doc_chunks.jsonl`

把原始文档切成 chunk，供语义检索或向量检索使用。

```json
{
  "chunk_id": "svc_api_business_partner_001",
  "service_name": "API_BUSINESS_PARTNER",
  "entity_set": "A_BusinessPartner",
  "field_names": ["BusinessPartner", "BusinessPartnerFullName"],
  "content": "A_BusinessPartner supports filtering by BusinessPartner and Customer.",
  "source_file": "metadata.xml",
  "section": "entity_fields",
  "keywords": ["客户", "业务伙伴", "BusinessPartner"]
}
```

推荐保留的检索字段：

- `service_name`
- `entity_set`
- `field_names`
- `content`
- `source_file`
- `section`
- `keywords`

### 5.2 `vector_documents.jsonl`

当前实现使用 `vector_documents.jsonl` 保存可供检索和 rerank 的文档化字段、实体和服务内容。

## 6. 案例索引

### 6.1 `cases.jsonl`

记录成功案例。

```json
{
  "case_id": "c1",
  "user_input": "查询客户 1000001 的姓名",
  "service_name": "API_BUSINESS_PARTNER",
  "entity_set": "A_BusinessPartner",
  "query_plan": {
    "select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
    "filters": [
      {"field": "BusinessPartner", "operator": "eq", "value": "1000001"}
    ]
  },
  "compiled_url": "/sap/opu/odata/sap/API_BUSINESS_PARTNER/A_BusinessPartner?$select=BusinessPartner,BusinessPartnerFullName&$filter=BusinessPartner eq '1000001'",
  "result_summary": "Returned 1 record",
  "tags": ["客户", "主数据", "查询"]
}
```

### 6.2 `feedback_memory.jsonl` 和 `feedback_events.jsonl`

反馈记忆和反馈事件用于沉淀用户确认、失败原因、可复用业务提示和后续修复策略。

建议额外保存：

- `error_code`
- `error_message`
- `failed_field`
- `repair_history`

## 7. 查询时怎么用

用户输入一句话后，建议按这个顺序使用索引：

1. 用 `business_terms.json` 做术语粗映射
2. 用 `doc_chunks.jsonl` 做语义召回
3. 用 `services.json / entities.json / fields.json` 做精确校验
4. 用 `success_cases.jsonl` 做相似案例增强
5. 生成结构化 `QueryPlan`
6. 编译 OData 请求

## 8. 为什么要拆成多份文件

因为它们的更新频率不同：

- metadata 类文件通常来自 SAP `$metadata`
- alias 类文件通常来自业务配置或人工维护
- example 类文件来自真实运行积累
- embeddings 类文件来自离线批处理

拆开后更容易增量更新，也更容易做版本管理。

## 9. 已落地的最小版本

当前运行时已经落地这些核心资产：

1. `services.json`
2. `entities.json`
3. `fields.json`
4. `relations.json`
5. `business_terms.json`
6. `doc_chunks.jsonl`
7. `vector_documents.jsonl`
8. `data/api_skills/<service_name>/skill.md`
9. `data/cases/*.jsonl`

这些资产共同支撑：

- service 选择
- entity 选择
- 字段合法性校验
- 历史案例增强
- API 专属业务语义增强
- result transform、status mapping 等 API 级规划提示

## 10. 和当前代码的对应关系

- 检索入口：
  [local_doc_retriever.py](../src/sap_odata_agent/infrastructure/retrieval/local_doc_retriever.py)
- 索引加载：
  [index_loader.py](../src/sap_odata_agent/infrastructure/indexing/index_loader.py)
- Catalog 构建：
  [api_catalog_provider.py](../src/sap_odata_agent/infrastructure/indexing/api_catalog_provider.py)
- API skill 加载：
  [api_skill_provider.py](../src/sap_odata_agent/infrastructure/indexing/api_skill_provider.py)
- 双源索引构建：
  [dual_source_index_builder.py](../src/sap_odata_agent/infrastructure/indexing/dual_source_index_builder.py)
- 核心计划对象：
  [models.py](../src/sap_odata_agent/domain/models.py)
- 编排入口：
  [orchestrator.py](../src/sap_odata_agent/application/orchestrator.py)
