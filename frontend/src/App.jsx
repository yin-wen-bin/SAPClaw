import { useEffect, useMemo, useState } from "react";

const quickPrompts = [
  "查询客户300001的基本信息",
  "查询供应商643266的邮编",
  "供应商17300003的统驭科目是什么？",
  "供应商17300003的 shipping condition 是什么？",
];

const initialForm = {
  user_input: quickPrompts[0],
  conversation_id: "demo-001",
  mode: "read_only",
};

function formatJson(value) {
  if (value == null) {
    return "暂无";
  }
  return JSON.stringify(value, null, 2);
}

function formatDuration(value) {
  const ms = Number(value);
  if (!Number.isFinite(ms)) {
    return "暂无";
  }
  if (ms >= 1000) {
    return `${(ms / 1000).toFixed(2)} s`;
  }
  return `${ms.toFixed(0)} ms`;
}

function getTotalDuration(result) {
  if (!result) {
    return null;
  }
  return result.total_duration_ms ?? result.client_duration_ms ?? null;
}

function statusLabel(item) {
  if (item?.needs_clarification) {
    return "待澄清";
  }
  if (item?.success) {
    return "成功";
  }
  return "失败";
}

function feedbackLabel(feedback) {
  if (!feedback?.status) {
    return "";
  }
  return feedback.status === "correct" ? "用户已确认正确" : "用户标记为不正确";
}

function planKindLabel(plan) {
  const labels = {
    direct: "单步直查",
    lookup: "单步查找",
    multi_step: "多步查询",
    address_lookup: "地址补查",
  };
  return labels[plan?.plan_kind || "direct"] || plan?.plan_kind || "direct";
}

function normalizeHistoryResult(item) {
  if (!item?.result_snapshot) {
    return null;
  }
  return {
    ...item.result_snapshot,
    feedback: item.feedback || null,
  };
}

function summarizeResultData(data, preferredFields = []) {
  if (!data) {
    return [];
  }

  let source = null;
  if (Array.isArray(data.results) && data.results.length > 0) {
    source = data.results[0];
  } else if (typeof data.result === "object" && data.result) {
    source = data.result;
  }

  if (!source) {
    return [];
  }

  const entries = Object.entries(source).filter(([key]) => key !== "__metadata");
  const preferred = preferredFields
    .map((field) => entries.find(([key]) => key === field))
    .filter(Boolean);

  return (preferred.length > 0 ? preferred : entries).slice(0, 8);
}

function HealthBadge({ health }) {
  const className = health === "ok" ? "ok" : health === "fail" ? "fail" : "pending";
  const text = health === "ok" ? "后端正常" : health === "fail" ? "后端异常" : "检查中";
  return <span className={`status-pill ${className}`}>{text}</span>;
}

function HistoryList({ history, historyError, onRefresh, onSelect }) {
  return (
    <section className="panel history-panel">
      <div className="panel-header">
        <div>
          <h2>最近查询</h2>
        </div>
        <button type="button" className="secondary-button compact-button" onClick={onRefresh}>
          刷新
        </button>
      </div>

      {historyError ? <p className="error-text">{historyError}</p> : null}

      {history.length === 0 ? (
        <p className="history-empty">暂无历史记录。提交一次查询后，这里会显示最近执行结果。</p>
      ) : (
        <div className="history-list history-list-horizontal">
          {history.map((item) => (
            <button key={item.case_id} type="button" className="history-item" onClick={() => onSelect(item)}>
              <strong>{item.user_input}</strong>
              <span>{item.entity_set || "未确定实体"}</span>
              <span>{statusLabel(item)}</span>
              {item.feedback?.status ? <span>{feedbackLabel(item.feedback)}</span> : null}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function QueryResultCard({ presentation }) {
  if (!presentation) {
    return null;
  }

  return (
    <article className="card card-wide result-answer-card">
      <div className="card-header">
        <h3>查询结果</h3>
      </div>

      {presentation.title ? <p className="result-title">{presentation.title}</p> : null}
      {presentation.text ? <p className="answer-text">{presentation.text}</p> : null}

      {presentation.kind === "table" && Array.isArray(presentation.columns) && presentation.columns.length > 0 ? (
        <div className="table-wrap">
          <table className="result-table">
            <thead>
              <tr>
                {presentation.columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(presentation.rows || []).map((row, index) => (
                <tr key={`${index}-${presentation.columns.join("-")}`}>
                  {presentation.columns.map((column) => (
                    <td key={`${index}-${column}`}>{String(row?.[column] ?? "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </article>
  );
}

function ClarificationCard({ result }) {
  if (!result?.needs_clarification) {
    return null;
  }

  return (
    <article className="card card-wide clarification-card">
      <div className="card-header">
        <h3>需要补充信息</h3>
      </div>
      <p>{result.clarification_question || result.final_message}</p>
      <p className="helper-text">继续用相同的会话 ID 提问，系统会把这次追问和上一轮问题一起理解。</p>
      {Array.isArray(result.clarification_options) && result.clarification_options.length > 0 ? (
        <div className="clarification-options">
          {result.clarification_options.map((option) => (
            <span key={option} className="summary-chip">
              {option}
            </span>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function OverviewCard({ result }) {
  return (
    <article className="card compact-card">
      <div className="card-header">
        <h3>执行概览</h3>
      </div>
      <div className="summary-table">
        <div className="summary-row">
          <span>状态</span>
          <strong>{statusLabel(result)}</strong>
        </div>
        <div className="summary-row">
          <span>实体</span>
          <strong>{result.plan?.entity_set || result.plan?.target_entity_set || "未确定"}</strong>
        </div>
        <div className="summary-row">
          <span>策略</span>
          <strong>{planKindLabel(result.plan)}</strong>
        </div>
        <div className="summary-row">
          <span>方法</span>
          <strong>{result.plan?.http_method || "GET"}</strong>
        </div>
        <div className="summary-row">
          <span>尝试次数</span>
          <strong>{result.attempts?.length || 0}</strong>
        </div>
      </div>
    </article>
  );
}

function KeyFieldsCard({ rows }) {
  return (
    <article className="card compact-card">
      <div className="card-header">
        <h3>关键字段</h3>
      </div>
      {rows.length > 0 ? (
        <div className="summary-table">
          {rows.map(([key, value]) => (
            <div className="summary-row" key={key}>
              <span>{key}</span>
              <strong>{String(value ?? "")}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="helper-text">当前结果没有可直接摘要的字段。</p>
      )}
    </article>
  );
}

function FeedbackCard({
  result,
  feedbackForm,
  feedbackSaving,
  feedbackMessage,
  onChange,
  onMarkCorrect,
  onChooseIncorrect,
  onSubmitIncorrect,
}) {
  if (!result?.case_id) {
    return null;
  }

  const existingFeedback = result.feedback || null;
  const selectedStatus = feedbackForm.status || existingFeedback?.status || "";

  return (
    <article className="card feedback-card">
      <div className="feedback-head">
        <div>
          <h3>结果反馈</h3>
          <p className="helper-text">用来沉淀正确案例和错误案例，作为后续改进依据。</p>
        </div>
        {existingFeedback?.status ? (
          <span className={`status-pill ${existingFeedback.status === "correct" ? "ok" : "pending"}`}>
            {feedbackLabel(existingFeedback)}
          </span>
        ) : null}
      </div>

      <div className="feedback-actions">
        <button type="button" className="secondary-button" onClick={onMarkCorrect} disabled={feedbackSaving}>
          结果正确
        </button>
        <button type="button" className="secondary-button" onClick={onChooseIncorrect} disabled={feedbackSaving}>
          结果不正确
        </button>
      </div>

      {selectedStatus === "incorrect" ? (
        <div className="feedback-form">
          <label>
            <span>哪里不正确</span>
            <textarea
              name="comment"
              rows="3"
              value={feedbackForm.comment}
              onChange={onChange}
              placeholder="说明当前结果错在哪里，例如实体选错、字段缺失、表达方式不对。"
            />
          </label>
          <label>
            <span>期望结果</span>
            <textarea
              name="expected_result"
              rows="3"
              value={feedbackForm.expected_result}
              onChange={onChange}
              placeholder="说明你希望系统如何查询或如何回答。"
            />
          </label>
          <div className="actions">
            <button type="button" onClick={onSubmitIncorrect} disabled={feedbackSaving}>
              {feedbackSaving ? "提交中..." : "提交反馈"}
            </button>
          </div>
        </div>
      ) : null}

      {feedbackMessage ? <p className="helper-text">{feedbackMessage}</p> : null}
    </article>
  );
}

function ExecutionTraceCard({ attempts = [] }) {
  if (!attempts.length) {
    return <p className="helper-text">当前没有执行轨迹。</p>;
  }

  return (
    <div className="attempt-list">
      {attempts.map((attempt, index) => (
        <div className="attempt-item" key={`${attempt.request?.url || "attempt"}-${index}`}>
          <div className="attempt-head">
            <strong>
              第 {index + 1} 步
              {attempt.step_id ? ` · ${attempt.step_id}` : ""}
            </strong>
            <span className={`status-pill ${attempt.success ? "ok" : "fail"}`}>
              {attempt.success ? "成功" : "失败"}
            </span>
          </div>
          <p>{attempt.request?.url || "无请求 URL"}</p>
          <p className="attempt-meta">状态码：{attempt.status_code ?? "n/a"}</p>
          {attempt.extracted_values && Object.keys(attempt.extracted_values).length > 0 ? (
            <pre>{formatJson(attempt.extracted_values)}</pre>
          ) : null}
          {attempt.error_message ? <p className="error-text">{attempt.error_message}</p> : null}
        </div>
      ))}
    </div>
  );
}

function TimingStepsCard({ timings = [] }) {
  if (!Array.isArray(timings) || timings.length === 0) {
    return <p className="helper-text">暂无步骤耗时。旧历史记录可能没有保存耗时数据。</p>;
  }

  return (
    <div className="timing-list">
      {timings.map((item, index) => (
        <div className="timing-row" key={`${item.key || item.label || "timing"}-${index}`}>
          <div>
            <strong>{item.label || item.key || `步骤 ${index + 1}`}</strong>
            {item.key ? <span>{item.key}</span> : null}
            {item.error_message ? <span className="error-text">{item.error_message}</span> : null}
          </div>
          <span className={`status-pill ${item.success === false ? "fail" : "ok"}`}>
            {formatDuration(item.duration_ms)}
          </span>
        </div>
      ))}
    </div>
  );
}

function TimingDistributionCard({ timings = [], totalDurationMs }) {
  const rows = Array.isArray(timings)
    ? timings
        .filter((item) => Number(item?.duration_ms) > 0)
        .map((item) => ({
          key: item.key || item.label || "unknown",
          label: item.label || item.key || "unknown",
          duration_ms: Number(item.duration_ms),
        }))
        .sort((a, b) => b.duration_ms - a.duration_ms)
    : [];

  const measuredTotal = rows.reduce((sum, item) => sum + item.duration_ms, 0);
  const denominator = measuredTotal > 0 ? measuredTotal : Number(totalDurationMs) || 0;

  if (!rows.length || denominator <= 0) {
    return <p className="helper-text">暂无耗时分布。执行新查询后会显示各步骤占比。</p>;
  }

  return (
    <div className="timing-distribution">
      <div className="summary-strip">
        <span>总耗时：{formatDuration(totalDurationMs)}</span>
        <span>已计步骤合计：{formatDuration(measuredTotal)}</span>
      </div>
      {rows.map((item, index) => {
        const percent = Math.max(0, Math.min(100, (item.duration_ms / denominator) * 100));
        return (
          <div className="timing-distribution-row" key={`${item.key}-${index}`}>
            <div className="timing-distribution-head">
              <strong>{item.label}</strong>
              <span>
                {formatDuration(item.duration_ms)} · {percent.toFixed(1)}%
              </span>
            </div>
            <div className="timing-bar">
              <span style={{ width: `${percent}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function DiagnosticsCard({ diagnostics }) {
  const fieldCandidates = diagnostics?.field_candidates || [];
  const entityCandidates = diagnostics?.entity_candidates || [];
  const pathCandidates = diagnostics?.path_candidates || [];
  const lookupResolution = diagnostics?.lookup_resolution || null;

  if (!diagnostics || (!fieldCandidates.length && !entityCandidates.length && !pathCandidates.length && !lookupResolution)) {
    return <p className="helper-text">当前没有可展示的规划诊断。</p>;
  }

  return (
    <div className="diagnostics-card">
      <div className="summary-strip">
        <span>召回策略：{diagnostics.recall_strategy || "unknown"}</span>
        {diagnostics.llm_guardrail ? <span>LLM 护栏：{diagnostics.llm_guardrail}</span> : null}
      </div>

      {pathCandidates.length > 0 ? (
        <div className="diagnostic-section">
          <h4>路径候选</h4>
          <div className="diagnostic-grid">
            {pathCandidates.map((path) => (
              <div key={path.path_id} className="diagnostic-item">
                <strong>{path.path_id}</strong>
                <span>
                  目标：{path.target_entity_set}.{path.target_field}
                </span>
                {path.anchor_object ? <span>锚点：{path.anchor_object}</span> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {entityCandidates.length > 0 ? (
        <div className="diagnostic-section">
          <h4>实体候选</h4>
          <div className="diagnostic-grid">
            {entityCandidates.map((entity) => (
              <div key={`${entity.entity_set}-${entity.description || ""}`} className="diagnostic-item">
                <strong>{entity.entity_set}</strong>
                <span>{entity.description || "无描述"}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {fieldCandidates.length > 0 ? (
        <div className="diagnostic-section">
          <h4>字段候选</h4>
          <div className="diagnostic-grid">
            {fieldCandidates.slice(0, 8).map((field) => (
              <div key={`${field.entity_set}.${field.field_name}`} className="diagnostic-item">
                <strong>
                  {field.entity_set}.{field.field_name}
                </strong>
                <span>分数：{field.score}</span>
                {Array.isArray(field.reasons) && field.reasons.length > 0 ? (
                  <span>命中原因：{field.reasons.join(", ")}</span>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {lookupResolution ? (
        <div className="diagnostic-section">
          <h4>查找解析</h4>
          <div className="diagnostic-grid">
            <div className="diagnostic-item">
              <strong>{lookupResolution.object_type || "unknown"}</strong>
              <span>标识：{lookupResolution.identifier || "n/a"}</span>
              <span>业务伙伴：{lookupResolution.business_partner || "n/a"}</span>
              <span>方式：{lookupResolution.via_plan_kind || "direct"}</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function GuardrailDecisionCard({ result }) {
  const guardrail = result?.guardrail_decision || null;
  const criticFindings = Array.isArray(result?.critic_findings) ? result.critic_findings : [];
  const attribution = result?.failure_attribution || null;
  const verification = result?.presentation_verification || null;
  const diagnostics = result?.plan?.planner_diagnostics || {};
  const fallbackPlan = diagnostics?.fallback_plan_snapshot || null;
  const llmPlan = diagnostics?.llm_plan_snapshot || null;
  const winner = diagnostics?.planner_winner || guardrail?.winner || "unknown";
  const adjudication = diagnostics?.llm_adjudication || null;

  if (!guardrail && !criticFindings.length && !attribution && !fallbackPlan && !llmPlan && !verification) {
    return <p className="helper-text">当前没有可展示的计划裁决信息。</p>;
  }

  return (
    <div className="decision-stack">
      <div className="summary-strip">
        <span>最终采用：{winner}</span>
        {guardrail ? <span>Guardrail：{guardrail.accepted ? "通过" : "拦截"}</span> : null}
        {guardrail?.severity ? <span>级别：{guardrail.severity}</span> : null}
      </div>

      {guardrail?.reasons?.length ? (
        <article className="card compact-card">
          <h4>裁决原因</h4>
          <ul className="flat-list">
            {guardrail.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </article>
      ) : null}

      {criticFindings.length ? (
        <article className="card compact-card">
          <h4>Critic Findings</h4>
          <ul className="flat-list">
            {criticFindings.map((finding, index) => (
              <li key={`${finding.code}-${index}`}>
                <strong>{finding.code}</strong>
                <span>{finding.message}</span>
              </li>
            ))}
          </ul>
        </article>
      ) : null}

      {attribution ? (
        <article className="card compact-card">
          <h4>失败归因</h4>
          <div className="summary-table">
            <div className="summary-row">
              <span>类别</span>
              <strong>{attribution.category || "unknown"}</strong>
            </div>
            <div className="summary-row">
              <span>根因</span>
              <strong>{attribution.root_cause || "unknown"}</strong>
            </div>
          </div>
          {Array.isArray(attribution.evidence) && attribution.evidence.length > 0 ? (
            <ul className="flat-list">
              {attribution.evidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}

      {verification ? (
        <article className="card compact-card">
          <h4>结果呈现校验</h4>
          <div className="summary-strip">
            <span>{verification.passed ? "通过" : "发现问题"}</span>
          </div>
          {Array.isArray(verification.issues) && verification.issues.length > 0 ? (
            <ul className="flat-list">
              {verification.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          ) : null}
        </article>
      ) : null}

      {(fallbackPlan || llmPlan || adjudication) ? (
        <div className="detail-grid">
          <article className="card compact-card">
            <h4>Fallback Plan</h4>
            <pre>{formatJson(fallbackPlan)}</pre>
          </article>
          <article className="card compact-card">
            <h4>LLM Plan</h4>
            <pre>{formatJson(llmPlan)}</pre>
          </article>
          {adjudication ? (
            <article className="card compact-card card-wide">
              <h4>LLM 裁决明细</h4>
              <pre>{formatJson(adjudication)}</pre>
            </article>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function HistoryContextCard({ item }) {
  if (!item) {
    return <p className="helper-text">当前没有选中的历史记录。</p>;
  }

  return (
    <div className="history-review">
      <div className="history-review-row">
        <span>原始问题</span>
        <strong>{item.user_input || "无"}</strong>
      </div>
      <div className="history-review-row">
        <span>状态</span>
        <strong>{statusLabel(item)}</strong>
      </div>
      {item.effective_user_input ? (
        <div className="history-review-block">
          <span>实际参与理解的输入</span>
          <pre>{item.effective_user_input}</pre>
        </div>
      ) : null}
      {item.feedback?.status ? (
        <div className="history-review-block">
          <span>用户反馈</span>
          <pre>{formatJson(item.feedback)}</pre>
        </div>
      ) : null}
    </div>
  );
}

function DetailSection({ title, children, defaultOpen = false }) {
  return (
    <details className="detail-section" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="detail-body">{children}</div>
    </details>
  );
}

function ResultPanel({ result, selectedHistory, feedbackProps }) {
  const summaryRows = useMemo(
    () => summarizeResultData(result?.data, result?.plan?.response_summary_fields || []),
    [result],
  );
  const totalDurationMs = getTotalDuration(result);

  if (!result) {
    return (
      <section className="panel result-panel empty-state">
        <h2>执行结果</h2>
        <p>首屏只保留主结果和必要操作。诊断信息、计划和原始数据收进折叠区，避免页面过载。</p>
      </section>
    );
  }

  return (
    <section className="panel result-panel">
      <div className="panel-header result-header">
        <div>
          <h2>执行结果</h2>
          <p className="panel-subtitle">{result.final_message || "无摘要信息"}</p>
        </div>
        <span className={`status-pill ${result.needs_clarification ? "pending" : result.success ? "ok" : "fail"}`}>
          {statusLabel(result)}
        </span>
      </div>

      <div className="result-main-stack">
        <QueryResultCard presentation={result.presentation} />
        <ClarificationCard result={result} />
      </div>

      <div className="overview-grid">
        <OverviewCard result={result} />
        <KeyFieldsCard rows={summaryRows} />
      </div>

      <FeedbackCard result={result} {...feedbackProps} />

      <div className="details-stack">
        <DetailSection title="执行轨迹" defaultOpen>
          <ExecutionTraceCard attempts={result.attempts || []} />
        </DetailSection>

        <DetailSection title="各步骤耗时" defaultOpen>
          <TimingStepsCard timings={result.timings || []} />
        </DetailSection>

        <DetailSection title="耗时分布">
          <TimingDistributionCard timings={result.timings || []} totalDurationMs={totalDurationMs} />
        </DetailSection>

        <DetailSection title="候选召回诊断">
          <DiagnosticsCard diagnostics={result.plan?.planner_diagnostics} />
        </DetailSection>

        <DetailSection title="计划裁决与归因">
          <GuardrailDecisionCard result={result} />
        </DetailSection>

        <DetailSection title="查询计划与校验">
          <div className="detail-grid">
            <article className="card compact-card">
              <h4>查询计划</h4>
              <pre>{formatJson(result.plan)}</pre>
            </article>
            <article className="card compact-card">
              <h4>校验结果</h4>
              <pre>{formatJson(result.validation_issues)}</pre>
            </article>
          </div>
        </DetailSection>

        <DetailSection title="返回数据">
          <pre>{formatJson(result.data)}</pre>
        </DetailSection>

        <DetailSection title="历史上下文">
          <HistoryContextCard item={selectedHistory} />
        </DetailSection>
      </div>
    </section>
  );
}

export default function App() {
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [health, setHealth] = useState("checking");
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState("");
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [lastDurationMs, setLastDurationMs] = useState(null);
  const [feedbackForm, setFeedbackForm] = useState({
    status: "",
    comment: "",
    expected_result: "",
  });

  async function loadHistory() {
    try {
      const response = await fetch("/api/v1/agent/history?limit=20", { cache: "no-store" });
      if (!response.ok) {
        throw new Error("history load failed");
      }
      const payload = await response.json();
      setHistory(Array.isArray(payload.items) ? payload.items : []);
      setHistoryError("");
    } catch (loadError) {
      setHistoryError(`历史记录加载失败：${loadError.message || "请确认后端服务已启动"}`);
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  useEffect(() => {
    let active = true;

    async function checkHealth() {
      try {
        const response = await fetch("/health");
        if (!response.ok) {
          throw new Error("health check failed");
        }
        if (active) {
          setHealth("ok");
        }
      } catch {
        if (active) {
          setHealth("fail");
        }
      }
    }

    checkHealth();
    return () => {
      active = false;
    };
  }, []);

  function resetFeedback(resultPayload) {
    setFeedbackMessage("");
    setFeedbackForm({
      status: resultPayload?.feedback?.status || "",
      comment: resultPayload?.feedback?.comment || "",
      expected_result: resultPayload?.feedback?.expected_result || "",
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const startedAt = performance.now();
    setLoading(true);
    setError("");
    setLastDurationMs(null);

    try {
      const response = await fetch("/api/v1/agent/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(form),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "查询失败");
      }

      const clientDurationMs = performance.now() - startedAt;
      const normalized = { ...payload, feedback: null, client_duration_ms: clientDurationMs };
      setLastDurationMs(payload.total_duration_ms ?? clientDurationMs);
      setResult(normalized);
      setSelectedHistory(null);
      resetFeedback(normalized);
      await loadHistory();
    } catch (submitError) {
      setLastDurationMs(performance.now() - startedAt);
      setResult(null);
      setError(submitError.message || "查询失败");
    } finally {
      setLoading(false);
    }
  }

  function handleChange(event) {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
  }

  function applyPrompt(prompt) {
    setForm((current) => ({ ...current, user_input: prompt }));
  }

  function loadHistoryItem(item) {
    setForm({
      user_input: item.user_input || "",
      conversation_id: item.conversation_id || "demo-001",
      mode: item.mode || "read_only",
    });
    const snapshot = normalizeHistoryResult(item);
    setResult(snapshot);
    setSelectedHistory(item);
    resetFeedback(snapshot);
    setError("");
  }

  async function submitFeedback(statusOverride = feedbackForm.status) {
    if (!result?.case_id) {
      return;
    }

    const status = statusOverride || feedbackForm.status;
    if (!status) {
      return;
    }

    setFeedbackSaving(true);
    setFeedbackMessage("");

    try {
      const response = await fetch("/api/v1/agent/feedback", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          case_id: result.case_id,
          status,
          comment: feedbackForm.comment,
          expected_result: feedbackForm.expected_result,
        }),
      });

      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error("反馈提交失败");
      }

      const savedFeedback = payload.entry?.feedback || null;
      setResult((current) => (current ? { ...current, feedback: savedFeedback } : current));
      setSelectedHistory(payload.entry || null);
      setFeedbackForm((current) => ({ ...current, status }));
      setFeedbackMessage(status === "correct" ? "已标记为正确。" : "已记录错误反馈。");
      await loadHistory();
    } catch (submitError) {
      setFeedbackMessage(submitError.message || "反馈提交失败");
    } finally {
      setFeedbackSaving(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div className="hero-copy">
          <div className="hero-topline">
            <div>
              <h1>SAP Claw</h1>
            </div>
            <HealthBadge health={health} />
          </div>

          <p className="hero-text">用自然语言操作SAP。</p>

          <div className="quick-prompts">
            {quickPrompts.map((prompt) => (
              <button key={prompt} type="button" className="prompt-chip" onClick={() => applyPrompt(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="workspace">
        <section className="content-column">
          <section className="panel form-panel form-panel-wide">
            <div className="panel-header">
              <div>
                <h2>查询内容</h2>
              </div>
              {loading ? <span className="status-pill pending">执行中</span> : null}
            </div>

            <form onSubmit={handleSubmit} className="query-form">
              <label>
                <textarea
                  name="user_input"
                  rows="5"
                  value={form.user_input}
                  onChange={handleChange}
                  placeholder="例如：供应商17300003的 shipping condition 是什么？"
                />
              </label>

              <div className="inline-fields">
                <label>
                  <span>会话 ID</span>
                  <input
                    name="conversation_id"
                    value={form.conversation_id}
                    onChange={handleChange}
                    placeholder="demo-001"
                  />
                </label>

                <label>
                  <span>执行模式</span>
                  <select name="mode" value={form.mode} onChange={handleChange}>
                    <option value="read_only">read_only</option>
                    <option value="write_confirm_required">write_confirm_required</option>
                  </select>
                </label>
              </div>

              <div className="actions">
                <button type="submit" disabled={loading}>
                  {loading ? "执行中..." : "开始查询"}
                </button>
                <span className="duration-label">
                  查询总耗时：{loading ? "计算中..." : formatDuration(lastDurationMs)}
                </span>
              </div>
            </form>

            {error ? <p className="error-text">{error}</p> : null}
          </section>

          <ResultPanel
            result={result}
            selectedHistory={selectedHistory}
            feedbackProps={{
              feedbackForm,
              feedbackSaving,
              feedbackMessage,
              onChange: (event) => {
                const { name, value } = event.target;
                setFeedbackForm((current) => ({ ...current, [name]: value }));
              },
              onMarkCorrect: () => {
                setFeedbackForm((current) => ({ ...current, status: "correct" }));
                submitFeedback("correct");
              },
              onChooseIncorrect: () => {
                setFeedbackForm((current) => ({ ...current, status: "incorrect" }));
              },
              onSubmitIncorrect: () => submitFeedback("incorrect"),
            }}
          />

          <HistoryList
            history={history}
            historyError={historyError}
            onRefresh={loadHistory}
            onSelect={loadHistoryItem}
          />
        </section>
      </main>
    </div>
  );
}
