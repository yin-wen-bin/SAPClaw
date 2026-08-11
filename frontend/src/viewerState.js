export const rowsFromData = (data) => {
  if (Array.isArray(data?.results)) return data.results.filter((row) => row && typeof row === "object");
  if (data?.result && typeof data.result === "object") return [data.result];
  return [];
};

export const classifyViewerState = ({ caseId, loading, error, health, data, pagination }) => {
  if (!caseId) return health?.ok ? "ready" : "not_ready";
  if (loading) return "loading";
  if (error) return "error";
  const rows = rowsFromData(data);
  if (!rows.length) return "empty";
  if (pagination?.has_next || Number(pagination?.skip || 0) > 0) return "paginated";
  return rows.length === 1 ? "single" : "multiple";
};
