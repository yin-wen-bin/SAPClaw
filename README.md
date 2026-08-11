# SAPClaw

SAPClaw 是一个通过SAP OData用自然语言操作SAP的Agent（目标是在SAP中进行增删改查，第一版只实现“查”）。它使用 LLM 将用户的业务问题路由到合适的 SAP API，生成可执行的 OData 查询计划，用本地索引的 SAP metadata 做 schema 校验，执行只读 SAP 请求，并以更贴近业务语义的形式展示结果。

## 架构

- FastAPI 后端，用于查询编排和 UI API。
- React 前端，位于 `frontend/`。
- LLM-first SAP OData 查询链路：API Router、Schema Context Provider、API-specific Planner、Plan Repair、Schema Validator、SAP Executor、Result Verifier 和 Result Presenter。
- API skill 文件位于 `data/api_skills/`，用于沉淀每个 API 的业务知识和规划提示。
- 运行时本地索引位于 `data/index/`。
- 可选 Codex-first Thin Runtime 与现有 Agent 并行，提供严格只读 MCP 执行面。

## 仓库内容

- `src/`：后端应用和 Agent 工具。
- `frontend/`：前端源代码。
- `data/api_skills/`：API 专属规划指导。
- `data/knowledge_graph/`：本地语义 grounding 数据，由 `data/index/` 和 `data/api_skills/` 构建。
- `docs/`：项目说明文档。
- `skills/`：可选的 SAPClaw Agent skill 集成。
- `tests/`：不包含 SAP 凭据的单元测试和集成测试。

## 本地环境最低要求

使用当前项目的标准本地运行方式前，本机必须已经安装：

- Python `>= 3.11`，并且 `python`、`pip` 可以在命令行中直接调用。
- Node.js 和 npm。前端使用 Vite，建议使用 Node.js `18`、`20` 或 `22+`。
- 可访问本地地址 `http://127.0.0.1:8000` 的浏览器。

`start_agent_ui.bat` 会调用 Python、Node 和 npm，但不会安装这些软件。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev,agent]
```

创建本地配置：

```powershell
Copy-Item .env.example env\.env
```

然后编辑 `env/.env`，填入你的 SAP 和 LLM 连接信息。

## 运行时数据

SAPClaw 需要本地 API 索引文件来完成 API 路由和 SAP OData 请求校验。后端默认从以下目录读取索引：

```text
data/index/
```

当前项目中包含了根据V2版本的API Specification生成的Index文档。
如果需要使用V4版本的API，或者新增当前项目中没有的API，请使用下边的工具构建索引。

### 构建单个 API 索引

仓库内提供了一个单 API 的双源索引构建工具：

```powershell
python -m sap_odata_agent.tools.build_dual_source_index `
  --sap-service-name API_PURCHASEORDER_PROCESS_SRV `
  --openapi-json data\index\API_PURCHASEORDER_PROCESS_SRV\raw\OP_API_PURCHASEORDER_PROCESS_SRV_0001.json `
  --output-root data\index
```

该工具会从 `env/.env` 读取 SAP 连接信息，在线请求指定服务的 `$metadata`，同时读取data/index/*/raw/文件夹下的API Specification（可以从SAP Business Accelerator Hub下载后放到指定目录），然后合并生成 `data/index/<service_name>/` 下的运行时索引文件。

如果本地索引目录名需要和 SAP Gateway 服务名不同，可以增加：

```powershell
--index-service-name <LOCAL_INDEX_SERVICE_NAME>
```

注意：

- 该工具当前按单个 API 执行，不会自动扫描所有 `data/index/*/raw/*.json` 批量重建。
- 该工具不是纯离线构建器；它需要能够访问 SAP 系统以获取 `$metadata`。

## 本地 Knowledge Graph

SAPClaw Local Knowledge Graph 是内部语义 grounding 层，只增强 Router、Schema Context、Planner、Repairer 和 Result Verifier，不改变 HTTP API 或 MCP tool 的公开协议。

默认配置：

```env
LOCAL_KG_ENABLED=true
LOCAL_KG_ROOT=data/knowledge_graph
LOCAL_KG_MAX_EVIDENCE=5
```

构建本地 KG：

```powershell
$env:PYTHONPATH='src'
python -m sap_odata_agent.tools.build_local_knowledge_graph
```

默认构建只使用 `data/index/` 和 `data/api_skills/` 生成 confirmed facts，不读取本地 feedback memory。如需把 feedback memory 生成为 candidate-only facts，可显式添加 `--include-feedback`。

更多说明见 `docs/local-knowledge-graph.md`。

## 启动本地 UI

推荐在 Windows 本地开发时使用仓库根目录下的一键启动脚本：

```powershell
.\start_agent_ui.bat
```

该脚本会执行以下步骤：

- 如果 `frontend/node_modules/` 不存在，自动运行 `npm install --prefix frontend`。
- 运行 `npm run build --prefix frontend` 构建前端。
- 设置本次进程的 `PYTHONPATH` 为 `<SAPClaw>\src`。
- 启动 FastAPI 后端：`http://127.0.0.1:8000`。
- 自动打开浏览器访问本地 UI。

脚本运行期间不要关闭该命令行窗口；关闭窗口会停止本地服务。

## 手动启动后端

```powershell
python -m uvicorn sap_odata_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## 手动启动前端

```powershell
npm install --prefix frontend
npm run dev --prefix frontend
```

生产构建：

```powershell
npm run build --prefix frontend
```

## 安装完成后测试前后端是否能正常工作

```powershell
python -m pytest -q
npm run build --prefix frontend
```

部分测试会检查本地 API 索引行为，需要开发环境中存在 `data/index/`。

## API 与 MCP 说明

### HTTP API

SAPClaw 后端基于 FastAPI 提供本地 HTTP API，用于把自然语言请求转换为受控的 SAP OData 查询流程。启动后端后，默认服务地址为：

```text
http://127.0.0.1:8000
```

常用接口包括：

- `GET /health`：检查本地后端是否可用。
- `POST /api/v1/agent/query`：面向本地 UI 的自然语言查询入口，返回路由、计划、执行结果、展示内容和诊断信息。
- `GET /api/v1/agent/progress/{conversation_id}`：查询执行进度的 SSE 流。
- `GET /api/v1/agent/model-profiles`：查看可用的 LLM 配置。
- `POST /api/v1/agent/feedback`：记录用户对查询结果的反馈。
- `POST /api/v1/queries`：面向外部工具或内部集成的只读查询接口，需要内部 API key。
- `GET /api/v1/queries/{case_id}/pages`：按 `case_id` 获取后续分页结果。

### MCP

SAPClaw 也提供 MCP（Model Context Protocol）stdio server，方便支持 MCP 的客户端或智能体把 SAPClaw 当作本地工具调用。MCP server 本身不直接连接 SAP，而是调用已经启动的 SAPClaw FastAPI 服务。

安装可选 MCP 依赖：

```powershell
pip install -e .[agent]
```

先启动本地后端，再启动 MCP server：

```powershell
sapclaw-mcp --base-url http://127.0.0.1:8000
```

MCP 暴露的主要工具包括：

- `sapclaw_health`：检查本地 SAPClaw 服务是否可达。
- `sapclaw_query`：提交自然语言 SAP OData 查询。
- `sapclaw_page`：读取某次查询的后续分页结果。
- `sapclaw_feedback`：写入查询结果反馈。
- `sapclaw_model_profiles`：列出本地可用的 LLM profile。

### Codex-first Thin Runtime（实验功能）

Thin Runtime 不替换现有 UI、HTTP API 或 `sapclaw-mcp`。Codex 负责业务理解、API 选择、QueryPlan 和最终回答，SAPClaw 负责 Catalog/Skill/KG evidence、Schema 权威、严格校验、只读 OData 执行、分页和审计。

默认关闭；在 `env/.env` 中显式启用：

```env
THIN_RUNTIME_ENABLED=true
THIN_RUNTIME_PAGE_SIZE=50
THIN_RUNTIME_MAX_BINDING_ROWS=5000
THIN_RUNTIME_LIVE_SCHEMA_ENABLED=true
THIN_RUNTIME_LIVE_SCHEMA_TTL_SECONDS=300
THIN_RUNTIME_LIVE_SCHEMA_MAX_STALE_SECONDS=86400
THIN_RUNTIME_VIEWER_ENABLED=true
THIN_RUNTIME_VIEWER_BASE_URL=http://127.0.0.1:8000
```

启动独立 Runtime MCP：

```powershell
.\start_sapclaw_runtime_mcp.bat
```

它提供 `sapclaw_catalog`、`sapclaw_schema`、`sapclaw_guidance`、`sapclaw_validate_plan`、`sapclaw_execute_plan`、`sapclaw_execute_get`、分页、系统浏览器结果查看器和反馈工具，不会调用旧 `sapclaw_query`。成功执行后，Thin workflow 会调用 `sapclaw_runtime_open_viewer`：多行、可分页或字段较多的结果会在系统默认浏览器中打开本地结果页，避免 Codex 内嵌浏览器加载该页面；可用一句话表达的单行结果保留在 Codex 中。Catalog 会返回可选的 KG 与 API Skill 候选 evidence；它们只帮助 Codex 找到需要检查的服务，不能自动选择 API 或绕过 schema 校验。

完整配置、MCP client 示例、安全边界和本地结果查看器说明见 `docs/thin-runtime.md`。Codex workflow skill 位于 `skills/sapclaw-thin-odata/`。

## 免责声明

SAPClaw 是一个用于探索 SAP OData API 自然语言访问能力的个人测试和实验工具。

本项目仅用于学习、原型验证和内部评估，不适用于生产环境、财务报告、合规判断或任何关键业务操作。

本工具可能生成错误的 API 路由、查询计划、过滤条件、字段选择、结果摘要或业务解释。用户在依赖任何结果前，应直接到源 SAP 系统中核实。

本项目不对准确性、完整性、可用性、安全性或特定用途适用性提供任何保证。使用风险由使用者自行承担。

不要提交或公开真实凭据、API key、SAP 连接信息、客户数据、供应商数据、财务数据或其他机密业务信息。

SAP、SAP S/4HANA 及相关产品名称是 SAP SE 或其关联公司的商标或注册商标。
