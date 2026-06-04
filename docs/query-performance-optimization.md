# 查询耗时优化备忘

## 当前优先级

当前阶段的首要目标是提高查询成功率，并尽可能用通用机制覆盖不同 SAP OData API、实体、字段和用户话术。耗时优化暂时作为后续 backlog，不应为了降低延迟牺牲以下能力：

- 对用户自然语言的容错理解。
- 基于 metadata 的字段、实体、路径通用匹配。
- LLM Critic / Guardrail 对错误计划的拦截。
- 多跳路径规划和失败反馈学习闭环。

## 已加入的观测能力

系统现在会在每次查询中记录关键步骤耗时，并通过 `/api/v1/agent/query` 返回：

- `total_duration_ms`：后端查询总耗时。
- `timings`：各步骤耗时明细。
- `timing_summary`：按步骤 key 聚合的耗时。

历史记录也会保存这些字段，便于后续对比不同查询类型的耗时分布。

## 现有瓶颈判断

基于一次典型查询“业务伙伴USSU-VSF54的统御科目是什么”的观测，主要耗时集中在 LLM 相关步骤，而不是 SAP OData 请求本身：

| 步骤 | 典型耗时 | 判断 |
| --- | ---: | --- |
| LLM Schema 候选重排 | 约 37.7s | 最大瓶颈 |
| LLM 语义解析 | 约 19.7s | 第二瓶颈 |
| Planner 计划生成 | 约 12.6s | 内部可能包含 LLM 调用 |
| LLM 计划审查 | 约 8.1s | 可按置信度裁剪 |
| 结果呈现生成 | 约 5.4s | 可模板化部分场景 |
| SAP OData 执行 | 约 1.8s | 不是当前主要瓶颈 |

结论：如果后续优化性能，应优先优化 LLM 调用次数、上下文大小、缓存和 gating 逻辑，而不是优先优化 SAP 请求。

## 后续优化方向

### 1. LLM 调用分级

不要每次都完整执行语义解析、Schema rerank、Planner、Plan Critic、结果呈现。可以按查询复杂度分级：

- 简单单字段查询：优先使用 metadata 召回 + 确定性计划生成，LLM 只做兜底。
- 多字段、多约束、多跳查询：启用 LLM 语义解析和 Schema rerank。
- 高风险计划或校验失败：启用 LLM Plan Critic。

### 2. Schema 候选压缩

当前 Schema rerank 是最大耗时点。后续可以在送入 LLM 前做候选压缩：

- 先用字段名、`sap:label`、`sap:quickinfo`、业务别名、模糊匹配和向量检索召回 top N。
- 按实体覆盖、字段覆盖、路径覆盖去重。
- 只把最有区分度的字段摘要交给 LLM，而不是大范围 schema。

### 3. 缓存

当前已经加入基础缓存，避免每次查询重复读取相同的本地资产：

- `ApiCatalogProvider` 会按索引文件签名缓存 compact API catalog。
- `ApiSkillProvider` 会按 `skill.md` 文件签名缓存 API skill。
- `LocalIndexLoader` 使用 LRU 缓存加载后的本地索引快照。
- `FileCaseRepository` 会缓存历史记录、反馈记忆和反馈事件，并在文件签名变化后失效。

后续可继续对 LLM 级别的可复用结果做缓存，减少相同或相似查询重复调用 LLM：

- 语义解析缓存：`normalized_query + service + index_version`。
- Schema rerank 缓存：`normalized_query + metadata_version + candidate_hash`。
- 计划缓存：`semantic_frame + schema_rerank + metadata_version`。
- 结果呈现缓存：只对相同数据快照可用，优先级较低。

### 4. Critic Gating

不是所有查询都需要 LLM Critic。可以先用确定性校验判断是否需要升级：

- 必填目标字段已覆盖。
- 必填过滤条件已覆盖。
- 计划实体包含所有 select/filter 字段。
- 多跳绑定字段完整。
- Guardrail 与 Schema Feasibility 均通过。

满足以上条件时，可以跳过 LLM Critic 或只做轻量 critic。

### 5. 结果呈现模板化

对于常见结果形态，后续可以减少 LLM 呈现调用：

- 单行单字段：直接生成自然语言答案。
- 列表查询：直接生成表格。
- 布尔查询：直接生成“是/否 + 依据字段”。

LLM 呈现保留给复杂解释、多字段归纳、异常数据说明等场景。

### 6. 存储层优化

当前历史记录和反馈以 JSONL 为主，适合脚手架阶段。后续数据量增大后可迁移到 SQLite：

- 查询历史按 `created_at`、`conversation_id`、`case_id` 建索引。
- 反馈记忆按业务对象、字段、错误类别建索引。
- 耗时记录可单独建表，便于统计 p50/p95。

### 7. 并行化

部分步骤可并行，但要避免破坏成功率：

- 历史反馈检索、反馈记忆检索、本地索引检索可并行。
- 确定性字段召回和 LLM 语义解析可并行。
- Critic 之间可在输入固定时并行。

并行化应放在缓存和 gating 之后做，否则会增加复杂度但收益不稳定。

## 建议目标

后续做性能优化时，可以用以下目标衡量：

- 简单单字段查询：3-5 秒。
- 普通多字段查询：5-10 秒。
- 多跳查询：10-20 秒。
- 复杂歧义查询：允许更慢，但必须给出清晰的澄清或失败归因。

这些目标不应覆盖“查询是否正确”这个主指标。当前阶段应继续优先投入到 metadata 驱动的通用召回、Schema 可行性、LLM 规划纠错和反馈学习闭环。
