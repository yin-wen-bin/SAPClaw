# SAPClaw Local Knowledge Graph

SAPClaw Local Knowledge Graph 是内部语义 grounding 层，用于增强 API Router、Schema Context、Planner、Repairer 和 Result Verifier。它不替代 schema validator、OData compiler 或 SAP executor，也不改变 HTTP API 和 MCP tool 的公开协议。

## 配置

默认配置位于 `env/.env`：

```env
LOCAL_KG_ENABLED=true
LOCAL_KG_ROOT=data/knowledge_graph
LOCAL_KG_MAX_EVIDENCE=5
```

如果 KG 行为不符合预期，可以关闭：

```env
LOCAL_KG_ENABLED=false
```

关闭后，Provider 返回空 evidence，Router、Planner、Verifier 会继续走原有逻辑。

## 数据文件

KG 第一版使用本地 JSON 文件：

```text
data/knowledge_graph/
  business_terms.json
  field_semantics.json
  business_paths.json
  api_candidates.json
  candidate_kg_facts.json
  build_summary.json
```

这些文件由本地索引和 API skill 生成：

- `data/index/*` 生成 confirmed API、entity、field、relation facts。
- `data/api_skills/*/skill.md` 生成 confirmed 业务术语、字段语义和常用规划路径。
- `data/cases/feedback_memory.jsonl` 只能生成 candidate facts，不能参与 blocking 判断。

默认构建不会读取 feedback memory，避免把本地历史反馈写入可提交文件。需要生成 candidate facts 时显式添加 `--include-feedback`。

## 构建

在仓库根目录执行：

```powershell
$env:PYTHONPATH='src'
python -m sap_odata_agent.tools.build_local_knowledge_graph
```

包含 candidate feedback facts：

```powershell
$env:PYTHONPATH='src'
python -m sap_odata_agent.tools.build_local_knowledge_graph --include-feedback
```

## 运行时接入

KG 只作为内部 evidence：

- Router：把 `kg_api_evidence` 作为额外选择依据，但不能绕过 OData runtime、service kind 或 catalog 约束。
- Schema Context：追加 `kg_business_terms`、`kg_recommended_fields`、`kg_recommended_paths`、`kg_semantic_warnings`。
- Planner/Repairer：只把 KG 当作语义 guidance；字段、实体、function import 和路径必须存在于 schema context。
- Result Verifier：confirmed KG warning 可以阻断错误业务结论；candidate/unconfirmed facts 只能作为参考，不能阻断。

## 兼容性

Local KG 不新增公开 endpoint，不新增 MCP tool，不要求前端、HTTP API caller 或 MCP caller 传入新字段。

允许新增的输出仅为 optional debug metadata，例如：

```json
{
  "kg_enabled": true,
  "kg_build_version": "1766441886a3b5a6",
  "kg_evidence_used": [],
  "kg_semantic_warnings": []
}
```
