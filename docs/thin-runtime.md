# SAPClaw Thin Runtime

Thin Runtime 是面向 Codex-first 查询方式的独立只读执行层。Codex 负责理解业务问题、选择 API、生成和修复计划、组织最终回答；SAPClaw 只负责提供 evidence、Schema 权威、严格校验、OData 编译执行、分页与审计。

现有 React 查询界面、`/api/v1/agent/*`、`/api/v1/queries` 和旧 `sapclaw-mcp` 均保留。Thin Runtime 不调用旧 `sapclaw_query`，也不导入 SAPClaw 的 LLM infrastructure。

## 启用

Thin Runtime 默认关闭。在 `env/.env` 中显式配置：

```env
THIN_RUNTIME_ENABLED=true
THIN_RUNTIME_PAGE_SIZE=50
THIN_RUNTIME_MAX_BINDING_ROWS=5000
THIN_RUNTIME_VIEWER_ENABLED=true
THIN_RUNTIME_VIEWER_BASE_URL=http://127.0.0.1:8000
```

`THIN_RUNTIME_PAGE_SIZE` 是传输和展示页大小，不是业务数量限制。QueryPlan 的 `top` 默认为 `null`；只有用户明确要求限制数量时才应设置。

## HTTP API

以下接口位于 `/api/v1/runtime`，并复用 `SAPCLAW_API_KEYS` 与 `X-API-Key` 鉴权：

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | 检查 Runtime、索引和只读状态 |
| POST | `/catalog` | 分页读取 API Catalog、KG API evidence 和 API Skill 候选 evidence |
| POST | `/schema` | 读取实体、字段、类型、关系和 function import |
| POST | `/guidance` | 读取 API Skill、KG 和 feedback evidence |
| POST | `/validate-plan` | 严格校验 QueryPlan，不访问 SAP |
| POST | `/execute-plan` | 重新校验并执行结构化只读计划 |
| POST | `/execute-get` | 执行受控相对 OData GET |
| POST | `/page` | 按 `case_id` 和 `skip` 读取结果页 |
| POST | `/feedback` | 保存 Thin case 的结果反馈 |

响应统一包含：

```json
{
  "schema_version": "1.0",
  "ok": true,
  "status": "success",
  "case_id": "<case-id>",
  "data": {},
  "pagination": {
    "page_size": 50,
    "skip": 0,
    "total_count": 0,
    "has_next": false,
    "next_skip": null
  },
  "viewer_url": "http://127.0.0.1:8000/?case_id=<case-id>&page=1",
  "validation_issues": [],
  "executed_requests": [],
  "error": null,
  "metadata": {
    "origin": "thin_mcp",
    "read_only": true
  }
}
```

MCP/HTTP 输出会移除 `__metadata`、内部 `_all_results` 和敏感配置。完整本地分页窗口只保存在 ignored case store 中。

## 输出字段契约

新的 Codex 结构化计划应包含可选的 `output_contract`。它将请求字段和展示字段分开：

```json
{
  "mode": "explicit",
  "display_grain": "supplier",
  "requested_fields": ["SupplierName"],
  "display_fields": ["SupplierName"],
  "support_fields": ["Supplier"],
  "reason": "用户明确要求供应商名称。"
}
```

- `explicit`：用户明确要求字段时使用。`requested_fields` 与 `display_fields` 必须完全一致且顺序一致；不能静默替换或追加展示字段。
- `inferred`：用户未要求具体字段时使用。Codex 根据问题意图、业务粒度和 schema 选择最小完整业务视图。
- `display_fields` 是表格、关键字段、分页和本地 Viewer 的唯一展示列；`support_fields` 仍会被请求，但只用于执行、关联或校验。
- 对 aggregate 计划，展示字段必须属于 `group_by` 或 `sum_fields`，避免展示聚合后不存在的字段。

该字段保持 optional，以兼容旧 Thin API caller；未提供时保留原有 `response_summary_fields + select_fields` 展示行为。
`/execute-get` 也接受同一可选契约；Runtime 会将 `display_fields` 和 `support_fields` 合并进受控 `$select` 后再做 schema 校验。

`/catalog` 可选返回 `kg_api_evidence` 和 `skill_api_evidence`。两者都只用于把潜在服务提供给 Codex 进一步检查；它们不会自动选择 API、修改 QueryPlan 或绕过 schema/guardrail。Codex 必须对候选服务继续调用 `/schema` 和 `/guidance`。

## MCP

先启动 FastAPI，再启动独立 Runtime MCP：

```powershell
.\start_agent_ui.bat
.\start_sapclaw_runtime_mcp.bat
```

或直接运行：

```powershell
python -m sap_odata_agent.agent_tools.runtime_mcp_server `
  --base-url http://127.0.0.1:8000 `
  --timeout 500
```

Codex 配置示例：

```toml
[mcp_servers.sapclaw_runtime]
command = "python"
args = [
  "-m",
  "sap_odata_agent.agent_tools.runtime_mcp_server",
  "--base-url",
  "http://127.0.0.1:8000",
  "--timeout",
  "500",
]
cwd = "<SAPCLAW_WORKSPACE>"
env = { PYTHONPATH = "<SAPCLAW_WORKSPACE>\\src" }
env_vars = ["SAPCLAW_API_KEY"]
enabled = true
startup_timeout_sec = 30
tool_timeout_sec = 600
```

修改配置后需要重启或重新加载 Codex MCP。实验期间保留旧 `[mcp_servers.sapclaw]` 配置。

Thin MCP tools：

```text
sapclaw_runtime_health
sapclaw_catalog
sapclaw_schema
sapclaw_guidance
sapclaw_validate_plan
sapclaw_execute_plan
sapclaw_execute_get
sapclaw_runtime_page
sapclaw_runtime_open_viewer
sapclaw_runtime_feedback
```

推荐配合仓库内 `skills/sapclaw-thin-odata/` 使用。

## 受控 GET 边界

`execute-get` 只接受已索引可执行服务、相对 `resource_path`、function parameters 和以下 query options：

```text
$select $filter $orderby $top $skip $expand $inlinecount $format $skiptoken
```

在 SAP 请求前拒绝：

- 非 GET 操作。
- 绝对 URL、外部 host、query string 嵌入 path、路径穿越和反斜线。
- 自定义认证 header。
- 未索引或 CDS-only 服务。
- 未知根实体、function import、参数和可解析字段。
- 未允许的 query option。

## 本地结果查看器

成功执行返回本地 `viewer_url`：

```text
http://127.0.0.1:8000/?case_id=<case-id>&page=<page-number>
```

页面仅在本地读取已保存快照，不重新执行自然语言查询。数字页码通过现有 `/api/v1/agent/page` 加载后续页并同步 URL。

Viewer URL 只会为 `localhost`、`127.0.0.1` 或 `::1` 生成。共享部署必须另行配置 HTTPS、认证网关和访问控制。

在 Codex Desktop 中，使用 `sapclaw_runtime_open_viewer(case_id, page=1)` 打开结果。该 MCP 工具会先验证本地 case，再由系统默认浏览器打开结果页，不使用 Codex 的内嵌浏览器，也不返回聊天中的可点击链接。Thin workflow 在每次成功执行后默认调用该工具；多行、可分页或字段较多的单行结果会打开浏览器，空结果和可用一句话表达的单行结果保留在 Codex 中。

## 真实 E2E 验收

测试资产和真实 SAP baseline 保存在 Git ignored 目录，不提交业务数据：

```text
data/thin_runtime_test_cases/
data/thin_runtime_test_runs/
```

生成 FI、CO、SD、MM、PP 各 10 条场景：

```powershell
python -m sap_odata_agent.tools.run_thin_codex_e2e --prepare
```

先刷新 deterministic SAP baseline，再运行真实 Codex + Thin MCP：

```powershell
python -m sap_odata_agent.tools.run_thin_codex_e2e `
  --baseline-only `
  --run-id thin_baseline_<timestamp>

python -m sap_odata_agent.tools.run_thin_codex_e2e `
  --codex-only `
  --use-existing-baseline `
  --run-id thin_codex_<timestamp>
```

如果 Codex provider 出现 quota 或 rate limit，runner 会在连续失败后熔断。配额恢复后使用同一个 `run-id` 续跑，已通过 case 不会重复消耗：

```powershell
python -m sap_odata_agent.tools.run_thin_codex_e2e `
  --codex-only `
  --use-existing-baseline `
  --run-id thin_codex_<timestamp> `
  --skip-passed
```

验收结果以 `summary.json` 和 `failures.json` 为准。provider 容量失败与 Router、Plan、Validator、SAP execution、comparison 失败分层记录。
