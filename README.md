# SAP Claw

这是一个面向 SAP OData 场景的 Agent 骨架项目。

当前版本先解决三件事：

1. 把用户自然语言请求转成结构化查询意图，而不是直接让模型自由拼 OData。
2. 在执行前增加规则校验和 OData 编译层，降低幻觉和危险写操作风险。
3. 把成功和失败案例都沉淀下来，为后续 RAG、向量检索和本地小模型提供训练素材。

## 当前架构

- `src/sap_odata_agent/api`
  - FastAPI 接口层，承接 UI 请求。
- `src/sap_odata_agent/application`
  - Agent 编排层，负责检索、规划、校验、执行、自修复和案例保存。
- `src/sap_odata_agent/domain`
  - 核心数据结构和端口协议。
- `src/sap_odata_agent/infrastructure`
  - LLM、SAP OData、文档检索、案例存储等基础设施实现。
- `docs/architecture.md`
  - 详细架构说明和演进路线。

## 请求链路

`UI -> Retriever -> Planner -> Validator -> Compiler -> SAP Executor -> Repair Loop -> Case Memory`

## MVP 范围

- 只读查询优先
- 最多有限次自修复
- 支持本地文档检索和案例沉淀
- 为后续接入向量库和小模型预留接口

## 快速启动

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
uvicorn sap_odata_agent.api.app:create_app --factory --reload
```

启动后可访问：

- `GET /health`
- `POST /api/v1/agent/query`
- `GET /` React 前端页面（当 `frontend/dist` 已构建时）

## 前端开发

最小 React 前端在 `frontend/` 目录下。

开发模式：

```bash
cd frontend
npm install
npm run dev
```

生产构建并由 FastAPI 托管：

```bash
cd frontend
npm run build
cd ..
uvicorn sap_odata_agent.api.app:create_app --factory --reload
```

Windows 一键启动：

```bat
start_agent_ui.bat
```

这个脚本会自动：

1. 检查并安装前端依赖
2. 构建 React 前端
3. 设置 `PYTHONPATH`
4. 启动 FastAPI 并打开浏览器

## 下一步建议

1. 导入真实 SAP OData `$metadata` 并做结构化解析。
2. 接入真实 LLM planner，而不是当前的占位实现。
3. 把成功/失败案例与检索上下文一起落盘。
4. 增加只读/写操作权限控制和人工确认机制。
