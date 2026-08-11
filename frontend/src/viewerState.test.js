import assert from "node:assert/strict";
import test from "node:test";

import { classifyViewerState, rowsFromData } from "./viewerState.js";


test("classifies Runtime readiness without a case id", () => {
  assert.equal(classifyViewerState({ caseId: "", health: { ok: true } }), "ready");
  assert.equal(classifyViewerState({ caseId: "", health: { ok: false, status: "not_ready" } }), "not_ready");
});

test("classifies single, multiple and empty result snapshots", () => {
  assert.equal(classifyViewerState({ caseId: "one", data: { results: [{ ID: "1" }] } }), "single");
  assert.equal(classifyViewerState({ caseId: "many", data: { results: [{ ID: "1" }, { ID: "2" }] } }), "multiple");
  assert.equal(classifyViewerState({ caseId: "empty", data: { results: [] } }), "empty");
  assert.deepEqual(rowsFromData({ result: { ID: "singleton" } }), [{ ID: "singleton" }]);
});

test("classifies pagination and error states", () => {
  assert.equal(
    classifyViewerState({ caseId: "paged", data: { results: [{ ID: "1" }] }, pagination: { has_next: true } }),
    "paginated",
  );
  assert.equal(classifyViewerState({ caseId: "failed", error: "SAP unavailable" }), "error");
});
