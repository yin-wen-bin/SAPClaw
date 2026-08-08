import { useEffect, useMemo, useRef, useState } from "react";

const quickPrompts = [
  "查询客户300001的基本信息",
  "查询供应商643266的邮编",
  "供应商17300003的统驭科目是什么？",
  "供应商17300003的 shipping condition 是什么？",
];

function Icon({ children }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

function SearchIcon() {
  return (
    <Icon>
      <path d="m15.8 15.8 4.2 4.2" />
      <circle cx="10.5" cy="10.5" r="6.5" />
    </Icon>
  );
}

function RefreshIcon() {
  return (
    <Icon>
      <path d="M20 6v5h-5" />
      <path d="M4 18v-5h5" />
      <path d="M18.1 9A7 7 0 0 0 6.2 6.4L4 8.7" />
      <path d="M5.9 15A7 7 0 0 0 17.8 17.6L20 15.3" />
    </Icon>
  );
}

const initialForm = {
  user_input: quickPrompts[0],
  conversation_id: "",
  mode: "read_only",
  llm_profile_id: "",
};

function readViewerLocation() {
  if (typeof window === "undefined") {
    return { caseId: "", page: 1 };
  }
  const params = new URLSearchParams(window.location.search);
  const caseId = params.get("case_id") || "";
  const rawPage = Number(params.get("page") || 1);
  return {
    caseId,
    page: Number.isFinite(rawPage) && rawPage > 0 ? Math.floor(rawPage) : 1,
  };
}

function syncViewerPage(caseId, page) {
  if (typeof window === "undefined" || !caseId) {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set("case_id", caseId);
  url.searchParams.set("page", String(page));
  window.history.replaceState({}, "", url);
}

function generateConversationId(now = new Date()) {
  const pad = (value, length = 2) => String(value).padStart(length, "0");
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds()),
    pad(now.getMilliseconds(), 3),
  ].join("");
}

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

function formatDisplayValue(value) {
  if (typeof value !== "string") {
    return value;
  }
  const match = value.trim().match(/^\/?Date\((-?\d+)(?:[+-]\d+)?\)\/?$/);
  if (!match) {
    return value;
  }
  const date = new Date(Number(match[1]));
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, "0");
  const day = String(date.getUTCDate()).padStart(2, "0");
  return `${year}.${month}.${day}`;
}

function cleanResultRow(row) {
  if (!row || typeof row !== "object") {
    return {};
  }
  return Object.fromEntries(
    Object.entries(row)
      .filter(([key]) => key !== "__metadata")
      .map(([key, value]) => [key, formatDisplayValue(value)]),
  );
}

function buildLocalDisplayPage(current, nextSkip) {
  const data = current?.data || {};
  const pagination = data.pagination || {};
  const allResults = Array.isArray(data._all_results) ? data._all_results : null;
  if (!allResults || allResults.length === 0) {
    return null;
  }

  const displayLimit = Number(pagination.display_limit || 50);
  const windowStart = Number(data._result_window_start ?? pagination.skip ?? 0);
  const absoluteSkip = Number(nextSkip);
  const localOffset = absoluteSkip - windowStart;
  if (!Number.isFinite(displayLimit) || displayLimit <= 0 || !Number.isFinite(localOffset)) {
    return null;
  }
  if (localOffset < 0 || localOffset >= allResults.length) {
    return null;
  }

  const rawRows = allResults.slice(localOffset, localOffset + displayLimit);
  const cleanRows = rawRows.map(cleanResultRow);
  const existingColumns = Array.isArray(current?.presentation?.columns) ? current.presentation.columns : [];
  const columns = existingColumns.length > 0 ? existingColumns : Object.keys(cleanRows[0] || {});
  const rows = cleanRows.map((row) => Object.fromEntries(columns.map((column) => [column, row[column] ?? ""])));
  const totalCount = Number(data.result_count || allResults.length);
  const displayedCount = rows.length;
  const absoluteEnd = absoluteSkip + displayedCount;
  const localHasNext = localOffset + rawRows.length < allResults.length;
  const sapHasNext = windowStart + allResults.length < totalCount;
  const nextLocalSkip = localHasNext ? absoluteEnd : sapHasNext ? windowStart + allResults.length : null;
  const text =
    absoluteSkip <= 0
      ? `查询结果总共${totalCount}条，当前显示前${displayedCount}条`
      : `查询结果总共${totalCount}条，当前显示第${absoluteSkip + 1}-${absoluteEnd}条`;

  return {
    ...current,
    final_message: text,
    data: {
      ...data,
      results: rawRows,
      displayed_count: displayedCount,
      pagination: {
        ...pagination,
        skip: absoluteSkip,
        page_number: Math.floor(absoluteSkip / displayLimit) + 1,
        has_next: nextLocalSkip != null,
        next_skip: nextLocalSkip,
      },
    },
    presentation: {
      ...(current?.presentation || {}),
      kind: "table",
      text,
      columns,
      rows,
    },
  };
}

function buildPaginationPageItems(currentPage, totalPages) {
  if (!Number.isFinite(totalPages) || totalPages <= 1) {
    return [1];
  }
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const pages = new Set([1, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  if (currentPage <= 3) {
    pages.add(2);
    pages.add(3);
    pages.add(4);
  }
  if (currentPage >= totalPages - 2) {
    pages.add(totalPages - 3);
    pages.add(totalPages - 2);
    pages.add(totalPages - 1);
  }

  const sortedPages = [...pages]
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((left, right) => left - right);

  return sortedPages.flatMap((page, index) => {
    const previous = sortedPages[index - 1];
    if (index > 0 && page - previous > 1) {
      return ["ellipsis", page];
    }
    return [page];
  });
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

function modelProfileLabel(profile) {
  if (!profile?.label) {
    return "Default";
  }
  return profile.enabled ? profile.label : `${profile.label} (not configured)`;
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

  return preferred.length > 0 ? preferred : entries;
}

function HistoryList({ history, historyError, onRefresh, onSelect }) {
  return (
    <section className="panel history-panel" id="history">
      <div className="panel-header">
        <div>
          <h2>最近查询</h2>
        </div>
        <button type="button" className="secondary-button compact-button" onClick={onRefresh}>
          <span className="button-label">
            <RefreshIcon />
            刷新
          </span>
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
              {item.llm_profile?.label ? <span>{item.llm_profile.label}</span> : null}
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

function QueryHistoryStrip({ history, onApply, disabled = false }) {
  const recentItems = history.filter((item) => item?.user_input).slice(0, 3);

  return (
    <div className="query-history-strip" aria-label="历史查询记录">
      <div className="query-history-head">
        <span>历史查询记录</span>
        <strong>最近 3 条</strong>
      </div>
      {recentItems.length > 0 ? (
        <div className="query-history-grid">
          {recentItems.map((item) => (
            <button
              key={item.case_id || item.user_input}
              type="button"
              className="query-history-card"
              onClick={() => onApply(item.user_input)}
              disabled={disabled}
              title="点击后只复制问题到查询框"
            >
              <strong>{item.user_input}</strong>
              <span>{item.entity_set || statusLabel(item)}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="history-empty">暂无历史查询记录。</p>
      )}
    </div>
  );
}

const progressStatusLabels = {
  running: "正在执行",
  succeeded: "已完成",
  failed: "执行失败",
  completed: "已结束",
};

const hiddenProgressKeys = new Set(["frontend.started", "progress.connected", "query.received"]);

function isDisplayableProgressEvent(event) {
  return Boolean(event) && !hiddenProgressKeys.has(event.key);
}

function formatProgressStatus(event) {
  if (!event) {
    return "等待查询步骤返回";
  }
  const status = progressStatusLabels[event.status] || event.status || "处理中";
  const duration =
    Number.isFinite(Number(event.duration_ms)) && Number(event.duration_ms) >= 0
      ? ` · ${formatDuration(Number(event.duration_ms))}`
      : "";
  return `${status}${duration}`;
}

function formatProgressTime(event) {
  if (!event?.created_at) {
    return "--:--:--";
  }
  const createdAt = new Date(event.created_at);
  if (Number.isNaN(createdAt.getTime())) {
    return "--:--:--";
  }
  return createdAt.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function mergeProgressEvent(events, nextEvent) {
  if (!nextEvent) {
    return events;
  }
  const eventKey = nextEvent.key || nextEvent.label || String(nextEvent.sequence || "");
  if (!eventKey) {
    return [...events, nextEvent].slice(-30);
  }
  const existingIndex = events.findIndex((event) => (event.key || event.label || String(event.sequence || "")) === eventKey);
  if (existingIndex < 0) {
    return [...events, nextEvent].slice(-30);
  }
  const merged = [...events];
  merged[existingIndex] = {
    ...merged[existingIndex],
    ...nextEvent,
  };
  return merged.slice(-30);
}

function getProgressDisplayRows(progressEvents, currentEvent) {
  const rows = progressEvents.length > 0 ? [...progressEvents] : [currentEvent].filter(Boolean);
  const statusRank = (status) => {
    if (status === "running") {
      return 0;
    }
    if (status === "failed") {
      return 1;
    }
    return 2;
  };
  const eventOrder = (event, index) => {
    const sequence = Number(event?.sequence);
    if (Number.isFinite(sequence)) {
      return sequence;
    }
    const createdAt = Date.parse(event?.created_at || "");
    if (Number.isFinite(createdAt)) {
      return createdAt;
    }
    return index;
  };
  return rows
    .map((event, index) => ({ event, order: eventOrder(event, index) }))
    .sort((leftItem, rightItem) => {
      const left = leftItem.event;
      const right = rightItem.event;
      const rankDelta = statusRank(left.status) - statusRank(right.status);
      if (rankDelta !== 0) {
        return rankDelta;
      }
      return rightItem.order - leftItem.order;
    })
    .map((item) => item.event);
}

function QueryLoadingPanel({ progressEvent, progressEvents = [], conversationId = "", userInput = "" }) {
  const visibleProgressEvents = progressEvents.filter(isDisplayableProgressEvent);
  const currentEvent = isDisplayableProgressEvent(progressEvent)
    ? progressEvent
    : visibleProgressEvents[visibleProgressEvents.length - 1] || null;
  const terminalRows = getProgressDisplayRows(visibleProgressEvents, currentEvent);
  return (
    <div className="query-terminal-backdrop" role="presentation">
      <section
        className="query-terminal-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="query-terminal-title"
        aria-describedby="query-terminal-current"
      >
        <div className="terminal-titlebar">
          <div className="terminal-window-controls" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <h3 id="query-terminal-title">SAPClaw terminal</h3>
          <span className="terminal-connection">live</span>
        </div>

        <div className="terminal-body" role="status" aria-live="polite" aria-busy="true">
          <div className="terminal-command-block">
            <p>
              <span className="terminal-prompt">$</span>
              <span>sapclaw query --session {conversationId || "auto"}</span>
            </p>
            {userInput ? (
              <p>
                <span className="terminal-prompt">&gt;</span>
                <span>{userInput}</span>
              </p>
            ) : null}
          </div>

          <div className="terminal-current" id="query-terminal-current">
            <span>current</span>
            <strong>{currentEvent?.label || "正在连接后端"}</strong>
            <em>{formatProgressStatus(currentEvent)}</em>
          </div>

          <ol className="terminal-log-list" aria-label="查询执行进度">
            {terminalRows.map((event) => (
              <li className="terminal-log-row" key={event.key || event.label || event.sequence}>
                <span className="terminal-log-time">{formatProgressTime(event)}</span>
                <span className={`terminal-log-status terminal-status-${event.status || "running"}`}>
                  {progressStatusLabels[event.status] || event.status || "处理中"}
                </span>
                <span className="terminal-log-label">{event.label}</span>
                {Number.isFinite(Number(event.duration_ms)) && Number(event.duration_ms) >= 0 ? (
                  <span className="terminal-log-duration">{formatDuration(Number(event.duration_ms))}</span>
                ) : null}
              </li>
            ))}
          </ol>
        </div>
      </section>
    </div>
  );
}

function QueryResultCard({ result, onPageChange, pageLoading }) {
  const presentation = result?.presentation;
  if (!presentation) {
    return null;
  }
  const pagination = result?.data?.pagination || null;
  const displayedCount = result?.data?.displayed_count || presentation.rows?.length || 0;
  const totalCount = result?.data?.result_count || displayedCount;
  const pageSizeValue = Number(pagination?.display_limit || pagination?.page_size || displayedCount || 50);
  const pageSize = Number.isFinite(pageSizeValue) && pageSizeValue > 0 ? pageSizeValue : 50;
  const currentSkip = Number(pagination?.skip || 0);
  const pageNumber = pagination?.page_number || Math.floor(currentSkip / pageSize) + 1;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const pageItems = buildPaginationPageItems(pageNumber, totalPages);

  return (
    <article className="card card-wide result-answer-card">
      <div className="card-header">
        <h3>查询结果</h3>
      </div>

      {presentation.title ? <p className="result-title">{presentation.title}</p> : null}
      {presentation.text ? <p className="answer-text">{presentation.text}</p> : null}
      {pagination ? (
        <div className="pagination-bar">
          <span>总计 {totalCount} 条</span>
          <span>本页显示 {displayedCount} 条</span>
          <div className="pagination-pages" aria-label="结果页码">
            {pageItems.map((item, index) =>
              item === "ellipsis" ? (
                <span key={`ellipsis-${index}`} className="pagination-ellipsis" aria-hidden="true">
                  ...
                </span>
              ) : (
                <button
                  key={item}
                  type="button"
                  className={`secondary-button compact-button pagination-page-button${item === pageNumber ? " active" : ""}`}
                  onClick={() => onPageChange(item)}
                  disabled={pageLoading || item === pageNumber}
                  aria-current={item === pageNumber ? "page" : undefined}
                >
                  {item}
                </button>
              ),
            )}
          </div>
        </div>
      ) : null}

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
  const feedbackMemories = Array.isArray(item.feedback_memories_used) ? item.feedback_memories_used : [];

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
      <div className="history-review-block">
        <span>本次使用的 feedback memory</span>
        {feedbackMemories.length > 0 ? (
          <div className="feedback-memory-list">
            {feedbackMemories.map((memory, index) => (
              <article key={`${memory.case_id || "memory"}-${index}`} className="feedback-memory-item">
                <strong>{memory.lesson || memory.memory_type || `Memory ${index + 1}`}</strong>
                {Array.isArray(memory.preferred_fields) && memory.preferred_fields.length > 0 ? (
                  <span>字段：{memory.preferred_fields.join(", ")}</span>
                ) : null}
                {Array.isArray(memory.preferred_entities) && memory.preferred_entities.length > 0 ? (
                  <span>实体：{memory.preferred_entities.join(", ")}</span>
                ) : null}
                {memory.condition ? <span>条件：{memory.condition}</span> : null}
                {memory.case_id ? <span>来源 case：{memory.case_id}</span> : null}
              </article>
            ))}
          </div>
        ) : (
          <p className="helper-text">本次没有匹配到可用的 feedback memory。</p>
        )}
      </div>
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

function ResultPanel({
  result,
  selectedHistory,
  feedbackProps,
  onPageChange,
  pageLoading,
  loading,
  showFeedback = true,
  showDetails = true,
}) {
  const displayFields = result?.plan?.output_contract?.display_fields || result?.plan?.response_summary_fields || [];
  const summaryRows = useMemo(
    () => summarizeResultData(result?.data, displayFields),
    [result, displayFields],
  );
  const totalDurationMs = getTotalDuration(result);

  if (!result) {
    return (
      <section className="panel result-panel empty-state" id="results">
        <h2>执行结果</h2>
        <p>暂无执行结果。</p>
      </section>
    );
  }

  return (
    <section className="panel result-panel" id="results">
      <div className="panel-header result-header">
        <div>
          <h2>执行结果</h2>
          <p className="panel-subtitle">{result.presentation?.text || result.final_message || "无摘要信息"}</p>
        </div>
        <span className={`status-pill ${result.needs_clarification ? "pending" : result.success ? "ok" : "fail"}`}>
          {statusLabel(result)}
        </span>
      </div>

      <div className="result-main-stack">
        <QueryResultCard result={result} onPageChange={onPageChange} pageLoading={pageLoading} />
        <ClarificationCard result={result} />
      </div>

      <div className="overview-grid">
        <OverviewCard result={result} />
        <KeyFieldsCard rows={summaryRows} />
      </div>

      {showFeedback ? <FeedbackCard result={result} {...feedbackProps} /> : null}

      {showDetails ? <div className="details-stack">
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
      </div> : null}
    </section>
  );
}

export default function App() {
  const [viewerLocation] = useState(readViewerLocation);
  const [form, setForm] = useState(initialForm);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState([]);
  const [historyError, setHistoryError] = useState("");
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackMessage, setFeedbackMessage] = useState("");
  const [lastDurationMs, setLastDurationMs] = useState(null);
  const [pageLoading, setPageLoading] = useState(false);
  const [modelProfiles, setModelProfiles] = useState([]);
  const [defaultProfileId, setDefaultProfileId] = useState("");
  const [progressEvents, setProgressEvents] = useState([]);
  const [currentProgressEvent, setCurrentProgressEvent] = useState(null);
  const [viewerLoading, setViewerLoading] = useState(Boolean(viewerLocation.caseId));
  const progressSourceRef = useRef(null);
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

  async function loadModelProfiles() {
    try {
      const response = await fetch("/api/v1/agent/model-profiles", { cache: "no-store" });
      if (!response.ok) {
        throw new Error("model profile load failed");
      }
      const payload = await response.json();
      const items = Array.isArray(payload.items) ? payload.items : [];
      const preferredProfile =
        items.find((item) => item.id === payload.default_profile && item.enabled)?.id ||
        items.find((item) => item.enabled)?.id ||
        "";
      setModelProfiles(items);
      setDefaultProfileId(payload.default_profile || "");
      setForm((current) => (current.llm_profile_id ? current : { ...current, llm_profile_id: preferredProfile }));
    } catch {
      setModelProfiles([]);
      setDefaultProfileId("");
    }
  }

  async function loadViewerCase(caseId, requestedPage = 1) {
    setViewerLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/v1/agent/cases/${encodeURIComponent(caseId)}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.success || !payload.result_snapshot) {
        throw new Error(payload.detail || "查询结果不存在或已过期");
      }

      let snapshot = payload.result_snapshot;
      const pagination = snapshot?.data?.pagination || {};
      const pageSizeValue = Number(pagination.display_limit || pagination.page_size || 50);
      const pageSize = Number.isFinite(pageSizeValue) && pageSizeValue > 0 ? pageSizeValue : 50;
      const targetSkip = (Math.max(1, requestedPage) - 1) * pageSize;
      if (targetSkip > 0) {
        const pageResponse = await fetch("/api/v1/agent/page", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ case_id: caseId, skip: targetSkip }),
        });
        const pagePayload = await pageResponse.json();
        if (!pageResponse.ok || !pagePayload.success) {
          throw new Error(pagePayload.detail || "请求页码不存在或加载失败");
        }
        snapshot = {
          ...snapshot,
          data: pagePayload.data,
          presentation: pagePayload.presentation,
          attempts: [...(snapshot.attempts || []), ...(pagePayload.attempts || [])],
        };
      }
      setResult(snapshot);
      syncViewerPage(caseId, requestedPage);
    } catch (viewerError) {
      setResult(null);
      setError(viewerError.message || "无法加载本地查询结果");
    } finally {
      setViewerLoading(false);
    }
  }

  useEffect(() => {
    if (viewerLocation.caseId) {
      loadViewerCase(viewerLocation.caseId, viewerLocation.page);
    } else {
      loadModelProfiles();
      loadHistory();
    }
    return () => {
      if (progressSourceRef.current) {
        progressSourceRef.current.close();
        progressSourceRef.current = null;
      }
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

  function closeProgressStream(source = progressSourceRef.current) {
    if (source) {
      source.close();
    }
    if (progressSourceRef.current === source) {
      progressSourceRef.current = null;
    }
  }

  function startProgressStream(conversationId) {
    closeProgressStream();
    const initialProgress = {
      key: "frontend.started",
      label: "准备开始查询",
      status: "running",
      sequence: 0,
    };
    setProgressEvents([]);
    setCurrentProgressEvent(initialProgress);

    if (!conversationId || typeof EventSource === "undefined") {
      return null;
    }

    const source = new EventSource(`/api/v1/agent/progress/${encodeURIComponent(conversationId)}`);
    progressSourceRef.current = source;
    source.addEventListener("progress", (message) => {
      try {
        const event = JSON.parse(message.data);
        if (isDisplayableProgressEvent(event)) {
          setCurrentProgressEvent(event);
          setProgressEvents((current) => mergeProgressEvent(current, event));
        }
        if (event.terminal) {
          closeProgressStream(source);
        }
      } catch {
        // Ignore malformed progress events; the main query response remains authoritative.
      }
    });
    source.onerror = () => {
      closeProgressStream(source);
    };
    return source;
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const startedAt = performance.now();
    const keepConversationId = Boolean(result?.needs_clarification && form.conversation_id);
    const conversationId = keepConversationId ? form.conversation_id : generateConversationId();
    if (!keepConversationId) {
      setForm((current) => ({ ...current, conversation_id: "" }));
    }
    setForm((current) => ({ ...current, conversation_id: conversationId }));
    setLoading(true);
    setError("");
    setResult(null);
    setSelectedHistory(null);
    setFeedbackMessage("");
    setLastDurationMs(null);
    const progressSource = startProgressStream(conversationId);

    try {
      const requestPayload = { ...form, conversation_id: conversationId };
      if (!requestPayload.llm_profile_id) {
        delete requestPayload.llm_profile_id;
      }
      const response = await fetch("/api/v1/agent/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestPayload),
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
      closeProgressStream(progressSource);
      setLoading(false);
    }
  }

  async function handlePageChange(targetPage) {
    const pagination = result?.data?.pagination || null;
    const displayedCount = result?.data?.displayed_count || result?.presentation?.rows?.length || 0;
    const pageSizeValue = Number(pagination?.display_limit || pagination?.page_size || displayedCount || 50);
    const pageSize = Number.isFinite(pageSizeValue) && pageSizeValue > 0 ? pageSizeValue : 50;
    const targetSkip = (Number(targetPage) - 1) * pageSize;
    const currentSkip = Number(pagination?.skip || 0);
    if (!result?.case_id || !pagination || !Number.isFinite(targetSkip) || targetSkip < 0 || targetSkip === currentSkip) {
      return;
    }

    const localPage = buildLocalDisplayPage(result, targetSkip);
    if (localPage) {
      setResult(localPage);
      if (viewerLocation.caseId) {
        syncViewerPage(viewerLocation.caseId, targetPage);
      }
      return;
    }

    setPageLoading(true);
    setError("");
    try {
      const response = await fetch("/api/v1/agent/page", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          case_id: result.case_id,
          skip: targetSkip,
        }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.detail || "页码加载失败");
      }
      setResult((current) =>
        current
          ? {
              ...current,
              data: payload.data,
              presentation: payload.presentation,
              attempts: [...(current.attempts || []), ...(payload.attempts || [])],
              final_message: payload.presentation?.text || payload.final_message || current.final_message,
            }
          : current,
      );
      if (viewerLocation.caseId) {
        syncViewerPage(viewerLocation.caseId, targetPage);
      }
    } catch (pageError) {
      setError(pageError.message || "页码加载失败");
    } finally {
      setPageLoading(false);
    }
  }

  function handleChange(event) {
    const { name, value } = event.target;
    if (loading && name === "user_input") {
      return;
    }
    setForm((current) => ({ ...current, [name]: value }));
  }

  function clearConversationId() {
    setForm((current) => ({ ...current, conversation_id: "" }));
  }

  function loadHistoryItem(item) {
    if (loading) {
      return;
    }
    setForm({
      user_input: item.user_input || "",
      conversation_id: "",
      mode: item.mode || "read_only",
      llm_profile_id: item.llm_profile_id || form.llm_profile_id || defaultProfileId || "",
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
      loadHistory();
    } catch (submitError) {
      setFeedbackMessage(submitError.message || "反馈提交失败");
    } finally {
      setFeedbackSaving(false);
    }
  }

  if (viewerLocation.caseId) {
    return (
      <div className="app-shell viewer-shell">
        <section className="hero viewer-hero">
          <div className="hero-copy">
            <div className="hero-title-block">
              <h1>SAPClaw</h1>
              <p className="hero-tagline">只读结果查看器</p>
            </div>
          </div>
        </section>
        <main className="workspace viewer-workspace">
          <section className="content-column">
            <section className="panel viewer-context-panel">
              <div>
                <span className="viewer-eyebrow">Thin Runtime Case</span>
                <strong>{viewerLocation.caseId}</strong>
              </div>
              <span className="status-pill ok">只读</span>
            </section>
            {viewerLoading ? (
              <section className="panel result-panel empty-state">
                <h2>正在加载结果</h2>
                <p>正在读取本地 case 快照。</p>
              </section>
            ) : null}
            {error ? (
              <section className="panel result-panel empty-state viewer-error-state">
                <h2>无法打开结果</h2>
                <p className="error-text">{error}</p>
              </section>
            ) : null}
            {!viewerLoading && !error ? (
              <ResultPanel
                result={result}
                selectedHistory={null}
                onPageChange={handlePageChange}
                pageLoading={pageLoading}
                loading={false}
                showFeedback={false}
                showDetails={false}
              />
            ) : null}
          </section>
        </main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <section className="hero">
        <div className="hero-copy">
          <div className="hero-title-block">
            <h1>SAPClaw</h1>
            <p className="hero-tagline">用自然语言操作SAP</p>
          </div>
        </div>
      </section>

      <main className="workspace">
        <section className="content-column">
          <section className="panel form-panel form-panel-wide" id="query">
            <div className="panel-header">
              <div>
                <h2>查询内容</h2>
              </div>
              {loading ? <span className="status-pill pending">执行中</span> : null}
            </div>

            <form onSubmit={handleSubmit} className="query-form">
              <label>
                <textarea
                  className="query-textarea"
                  name="user_input"
                  aria-label="查询内容"
                  rows="5"
                  value={form.user_input}
                  onChange={handleChange}
                  readOnly={loading}
                  aria-readonly={loading ? "true" : undefined}
                  placeholder="例如：供应商17300003的 shipping condition 是什么？"
                />
              </label>

              <div className="inline-fields">
                <div className="field-group session-field">
                  <div className="field-label-row">
                    <span>会话 ID</span>
                  </div>
                  <div className="session-input-wrap">
                    <input
                      name="conversation_id"
                      value={form.conversation_id}
                      readOnly
                      aria-readonly="true"
                      placeholder="点击开始查询后自动生成"
                    />
                    <button
                      type="button"
                      className="clear-session-button"
                      onClick={clearConversationId}
                      disabled={loading || !form.conversation_id}
                    >
                      清除
                    </button>
                  </div>
                </div>

                <label>
                  <span>执行模式</span>
                  <select name="mode" value={form.mode} onChange={handleChange}>
                    <option value="read_only">read_only</option>
                    <option value="write_confirm_required">write_confirm_required</option>
                  </select>
                </label>

                <label>
                  <span>Model</span>
                  <select name="llm_profile_id" value={form.llm_profile_id} onChange={handleChange}>
                    <option value="">Default / local fallback</option>
                    {modelProfiles.map((profile) => (
                      <option key={profile.id} value={profile.id} disabled={!profile.enabled}>
                        {modelProfileLabel(profile)}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="actions">
                <button type="submit" disabled={loading}>
                  <span className="button-label">
                    {loading ? null : <SearchIcon />}
                    {loading ? "执行中..." : "开始查询"}
                  </span>
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
            onPageChange={handlePageChange}
            pageLoading={pageLoading}
            loading={loading}
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
      {loading ? (
        <QueryLoadingPanel
          progressEvent={currentProgressEvent}
          progressEvents={progressEvents}
          conversationId={form.conversation_id}
          userInput={form.user_input}
        />
      ) : null}
    </div>
  );
}
