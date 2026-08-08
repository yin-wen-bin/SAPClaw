from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sap_odata_agent.infrastructure.config.settings import get_settings
from sap_odata_agent.infrastructure.repositories.file_case_repository import JsonlCaseRepository
from sap_odata_agent.tools.run_llm_e2e_tests import _compare, _expected_api_matches, _run_baseline


DEFAULT_MODULES = ("FI", "CO", "SD", "MM", "PP")
DEFAULT_SOURCE_ROOT = Path("data/cross_api_test_cases")
DEFAULT_CASE_ROOT = Path("data/thin_runtime_test_cases")
DEFAULT_RUN_ROOT = Path("data/thin_runtime_test_runs")
DEFAULT_SKILL_PATH = Path("skills/sapclaw-thin-odata/SKILL.md")
DEFAULT_RUNTIME_BASE_URL = "http://127.0.0.1:8000"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run deterministic SAP baselines and isolated Codex + Thin MCP E2E cases."
    )
    parser.add_argument("--prepare", action="store_true", help="Create the 10-case-per-module Thin suite.")
    parser.add_argument("--baseline-only", action="store_true", help="Run only deterministic SAP baselines.")
    parser.add_argument("--codex-only", action="store_true", help="Run only isolated Codex + Thin MCP cases.")
    parser.add_argument("--use-existing-baseline", action="store_true")
    parser.add_argument("--module", action="append", choices=DEFAULT_MODULES)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--limit-per-module", type=int, default=10)
    parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    parser.add_argument("--case-root", default=str(DEFAULT_CASE_ROOT))
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    parser.add_argument("--run-id", default="")
    parser.add_argument("--codex-cli", default=os.getenv("CODEX_CLI", "codex"))
    parser.add_argument("--codex-model", default="")
    parser.add_argument("--codex-timeout-seconds", type=int, default=900)
    parser.add_argument(
        "--runtime-base-url",
        default=os.getenv("THIN_RUNTIME_BASE_URL", DEFAULT_RUNTIME_BASE_URL),
        help="Base URL for the isolated Thin Runtime backend.",
    )
    parser.add_argument("--baseline-sap-timeout-ms", type=int, default=120_000)
    parser.add_argument("--baseline-retries", type=int, default=2)
    parser.add_argument("--baseline-retry-delay-seconds", type=float, default=2.0)
    parser.add_argument("--case-delay-seconds", type=float, default=0.0)
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--skip-passed", action="store_true")
    parser.add_argument("--max-consecutive-provider-failures", type=int, default=3)
    args = parser.parse_args()

    modules = tuple(args.module or DEFAULT_MODULES)
    runtime_base_url = str(args.runtime_base_url or DEFAULT_RUNTIME_BASE_URL).rstrip("/")
    case_root = Path(args.case_root)
    if args.prepare or not all((case_root / module / "cases.json").exists() for module in modules):
        prepare_suite(
            source_root=Path(args.source_root),
            case_root=case_root,
            modules=modules,
            limit_per_module=max(1, args.limit_per_module),
        )
        if args.prepare and not args.baseline_only and not args.codex_only:
            return

    cases = load_cases(case_root, modules, set(args.case_id or []))
    run_id = args.run_id or datetime.now().strftime("thin_%Y%m%d_%H%M%S")
    run_dir = Path(args.run_root) / run_id
    per_case_dir = run_dir / "per_case"
    per_case_dir.mkdir(parents=True, exist_ok=True)
    output_schema = write_output_schema(run_dir)
    workspace = Path("data/cases/thin_codex_workspace")
    workspace.mkdir(parents=True, exist_ok=True)

    run_baseline = not args.codex_only
    run_codex = not args.baseline_only
    if run_baseline:
        os.environ["SAP_ODATA_TIMEOUT_MS"] = str(max(1_000, args.baseline_sap_timeout_ms))
    results: list[dict[str, Any]] = []
    consecutive_provider_failures = 0
    for case in cases:
        output_path = per_case_dir / f"{case['id']}.json"
        if output_path.exists() and (args.skip_existing or args.skip_passed):
            existing = json.loads(output_path.read_text(encoding="utf-8"))
            if args.skip_existing or existing.get("status") == "passed":
                results.append(existing)
                continue

        started_at = datetime.now().astimezone().isoformat()
        baseline = load_or_run_baseline(
            case,
            case_root,
            run_baseline=run_baseline,
            use_existing=args.use_existing_baseline,
            retries=max(0, args.baseline_retries),
            retry_delay_seconds=max(0.0, args.baseline_retry_delay_seconds),
        )
        codex_result = None
        if run_codex:
            codex_result = run_codex_case(
                case=case,
                run_dir=run_dir,
                output_schema=output_schema,
                workspace=workspace,
                codex_cli=args.codex_cli,
                codex_model=args.codex_model,
                timeout_seconds=max(30, args.codex_timeout_seconds),
                runtime_base_url=runtime_base_url,
            )
        comparison = compare_case(case, baseline, codex_result, baseline_only=args.baseline_only)
        result = {
            "run_id": run_id,
            "case_id": case["id"],
            "source_case_id": case.get("source_case_id"),
            "api": case["api"],
            "scenario": case["scenario"],
            "user_input": case["user_input"],
            "started_at": started_at,
            "finished_at": datetime.now().astimezone().isoformat(),
            "status": "passed" if comparison.get("passed") else "failed",
            "failed_layer": comparison.get("failed_layer"),
            "comparison": comparison,
            "baseline": baseline,
            "codex": codex_result,
        }
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
        print(f"{case['id']}: {result['status']} ({result.get('failed_layer') or 'ok'})", flush=True)
        if provider_capacity_failure(result):
            consecutive_provider_failures += 1
        else:
            consecutive_provider_failures = 0
        failure_limit = max(0, args.max_consecutive_provider_failures)
        if failure_limit and consecutive_provider_failures >= failure_limit:
            print(
                f"Stopped after {consecutive_provider_failures} consecutive provider capacity failures.",
                flush=True,
            )
            break
        if args.case_delay_seconds > 0:
            time.sleep(args.case_delay_seconds)

    summary = build_summary(run_id, results, baseline_only=args.baseline_only)
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failures = [item for item in results if item["status"] != "passed"]
    (run_dir / "failures.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def prepare_suite(
    *,
    source_root: Path,
    case_root: Path,
    modules: tuple[str, ...],
    limit_per_module: int,
) -> None:
    for module in modules:
        source_path = source_root / module / "cases.json"
        if not source_path.exists():
            raise FileNotFoundError(f"Missing source cases: {source_path}")
        source_cases = json.loads(source_path.read_text(encoding="utf-8-sig"))
        selected = source_cases[:limit_per_module]
        if len(selected) < limit_per_module:
            raise ValueError(f"{module} has only {len(selected)} source cases.")
        prepared: list[dict[str, Any]] = []
        for index, source in enumerate(selected, start=1):
            prepared.append(
                {
                    **source,
                    "id": f"THIN-{module}-{index:03d}",
                    "api": module,
                    "source_case_id": source.get("id"),
                    "test_surface": "codex_thin_mcp",
                }
            )
        target = case_root / module / "cases.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(prepared, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Prepared {len(prepared)} {module} cases at {target}")


def load_cases(case_root: Path, modules: tuple[str, ...], case_ids: set[str]) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for module in modules:
        path = case_root / module / "cases.json"
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        cases.extend(case for case in payload if not case_ids or case["id"] in case_ids)
    return cases


def load_or_run_baseline(
    case: dict[str, Any],
    case_root: Path,
    *,
    run_baseline: bool,
    use_existing: bool,
    retries: int = 0,
    retry_delay_seconds: float = 0.0,
) -> dict[str, Any] | None:
    path = case_root / case["api"] / "baselines" / f"{case['id']}.json"
    if (use_existing or not run_baseline) and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if not run_baseline:
        return None
    baseline: dict[str, Any] | None = None
    for attempt in range(retries + 1):
        baseline = _run_baseline(case, case_root)
        if baseline.get("success") or not baseline_retryable(baseline):
            return baseline
        if attempt < retries and retry_delay_seconds > 0:
            time.sleep(retry_delay_seconds)
    return baseline


def baseline_retryable(baseline: dict[str, Any]) -> bool:
    text = json.dumps(baseline, ensure_ascii=False, default=str).lower()
    return any(
        token in text
        for token in (
            "timed out",
            "timeout",
            "unexpected_eof",
            "connection reset",
            "temporarily unavailable",
            "winerror 10053",
            "winerror 10054",
            "winerror 10060",
            "status_code\": 502",
            "status_code\": 503",
            "status_code\": 504",
        )
    )


def run_codex_case(
    *,
    case: dict[str, Any],
    run_dir: Path,
    output_schema: Path,
    workspace: Path,
    codex_cli: str,
    codex_model: str,
    timeout_seconds: int,
    runtime_base_url: str,
) -> dict[str, Any]:
    case_id = case["id"]
    last_message_path = run_dir / "codex_outputs" / f"{case_id}.json"
    log_path = run_dir / "codex_logs" / f"{case_id}.log"
    last_message_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path = DEFAULT_SKILL_PATH.resolve()
    prompt = (
        f"Read and follow `{skill_path}`. This is an isolated E2E evaluation. "
        "Do not inspect repository test cases, baselines, prior run files, history records, or expected APIs. "
        "Use only the sapclaw_runtime MCP tools for SAP evidence and read-only execution. "
        "Start with health, then catalog, schema/guidance, validate, and execute as required by the skill. "
        "Answer the user's question in the same language. Do not modify files. "
        "Your final response must match the supplied JSON schema; set case_id to the Thin Runtime case id.\n\n"
        f"User question: {case['user_input']}"
    )
    command = [
        codex_cli,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "remote_plugin",
        "--disable",
        "guardian_approval",
        "--disable",
        "tool_call_mcp_elicitation",
        "--sandbox",
        "read-only",
        "--cd",
        str(workspace.resolve()),
        "--output-schema",
        str(output_schema.resolve()),
        "--output-last-message",
        str(last_message_path.resolve()),
        "-c",
        'approval_policy="never"',
    ]
    command.extend(isolated_runtime_mcp_config(skill_path.parents[2], runtime_base_url=runtime_base_url))
    if codex_model:
        command.extend(["--model", codex_model])
    command.append(prompt)

    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        log_path.write_text(
            f"STDOUT\n{completed.stdout}\n\nSTDERR\n{completed.stderr}",
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        log_path.write_text(
            f"Codex process timed out after {timeout_seconds} seconds.\n{exc.stdout or ''}\n{exc.stderr or ''}",
            encoding="utf-8",
        )
        return {
            "success": False,
            "error_type": "codex_timeout",
            "error_message": f"Codex timed out after {timeout_seconds} seconds.",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    raw_message = last_message_path.read_text(encoding="utf-8") if last_message_path.exists() else ""
    parsed = parse_json_object(raw_message)
    if completed.returncode != 0 or parsed is None:
        combined = f"{completed.stdout}\n{completed.stderr}\n{raw_message}"
        return {
            "success": False,
            "error_type": classify_codex_failure(combined),
            "error_message": compact_error(combined),
            "return_code": completed.returncode,
            "duration_ms": duration_ms,
        }

    thin_case_id = str(parsed.get("case_id") or "")
    entry = get_case_repository().get_by_case_id(thin_case_id) if thin_case_id else None
    frontend = runtime_entry_payload(entry)
    if not frontend:
        failure_text = " ".join(
            str(parsed.get(key) or "")
            for key in ("status", "answer", "error")
        )
        return {
            "success": False,
            "case_id": thin_case_id or None,
            "status": parsed.get("status"),
            "answer": parsed.get("answer"),
            "error": parsed.get("error"),
            "error_type": classify_codex_failure(failure_text),
            "error_message": compact_error(failure_text),
            "duration_ms": duration_ms,
            "runtime": None,
        }
    return {
        "success": bool(frontend and frontend.get("success")),
        "case_id": thin_case_id or None,
        "status": parsed.get("status"),
        "answer": parsed.get("answer"),
        "error": parsed.get("error"),
        "duration_ms": duration_ms,
        "runtime": frontend,
    }


def get_case_repository() -> JsonlCaseRepository:
    return JsonlCaseRepository(get_settings().case_store_path)


def isolated_runtime_mcp_config(
    repo_root: Path,
    *,
    runtime_base_url: str = DEFAULT_RUNTIME_BASE_URL,
) -> list[str]:
    def quote(value: Path) -> str:
        return json.dumps(str(value), ensure_ascii=True)

    server_args = [
        "-m",
        "sap_odata_agent.agent_tools.runtime_mcp_server",
        "--base-url",
        runtime_base_url.rstrip("/"),
        "--timeout",
        "500",
    ]
    return [
        "-c",
        'mcp_servers.sapclaw_runtime.command="python"',
        "-c",
        f"mcp_servers.sapclaw_runtime.args={json.dumps(server_args)}",
        "-c",
        f"mcp_servers.sapclaw_runtime.cwd={quote(repo_root)}",
        "-c",
        f"mcp_servers.sapclaw_runtime.env={{ PYTHONPATH = {quote(repo_root / 'src')} }}",
        "-c",
        'mcp_servers.sapclaw_runtime.env_vars=["SAPCLAW_API_KEY"]',
        "-c",
        "mcp_servers.sapclaw_runtime.enabled=true",
        "-c",
        "mcp_servers.sapclaw_runtime.startup_timeout_sec=30",
        "-c",
        "mcp_servers.sapclaw_runtime.tool_timeout_sec=600",
    ]


def runtime_entry_payload(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not entry:
        return None
    plan = entry.get("final_plan") or entry.get("initial_plan") or {}
    steps = plan.get("steps") or []
    selected_apis = list(
        dict.fromkeys(
            [
                str(plan.get("service_name") or ""),
                *[str(step.get("service_name") or plan.get("service_name") or "") for step in steps],
            ]
        )
    )
    selected_apis = [item for item in selected_apis if item]
    data = entry.get("response_preview") or {}
    rows = data.get("results")
    if not isinstance(rows, list):
        rows = data.get("primary_results")
    if not isinstance(rows, list):
        rows = []
    return {
        "success": entry.get("final_status") == "success",
        "needs_clarification": False,
        "selected_api": selected_apis[0] if selected_apis else "",
        "selected_apis": selected_apis,
        "results": [row for row in rows if isinstance(row, dict)],
        "result_count": _safe_int(data.get("result_count"), len(rows)),
        "final_message": (entry.get("presentation") or {}).get("text") or entry.get("error_summary") or "",
        "failure_attribution": None,
        "execution_origin": entry.get("execution_origin"),
        "request_kind": entry.get("request_kind"),
    }


def compare_case(
    case: dict[str, Any],
    baseline: dict[str, Any] | None,
    codex_result: dict[str, Any] | None,
    *,
    baseline_only: bool,
) -> dict[str, Any]:
    if baseline_only:
        return {
            "passed": bool(baseline and baseline.get("success")),
            "mode": "baseline_only",
            "failed_layer": None if baseline and baseline.get("success") else "baseline",
        }
    if not codex_result or not codex_result.get("success"):
        return {
            "passed": False,
            "failed_layer": codex_result.get("error_type", "codex") if codex_result else "codex",
            "reason": codex_result.get("error_message", "Codex result is missing.") if codex_result else "Codex result is missing.",
        }
    frontend = codex_result.get("runtime")
    if not frontend or frontend.get("execution_origin") != "thin_mcp":
        return {
            "passed": False,
            "failed_layer": "thin_runtime_audit",
            "reason": "Codex did not return a saved Thin Runtime case.",
        }

    # A deterministic baseline identifies one valid implementation path. Codex
    # may legitimately choose another indexed API when its returned business
    # data still matches that baseline, so route matching is measured rather
    # than treated as a blocking result-correctness condition.
    route_matches_baseline = _expected_api_matches(case, frontend)
    comparison_case = dict(case)
    for key in ("expected_api", "expected_apis", "require_all_expected_apis"):
        comparison_case.pop(key, None)
    comparison = _compare(
        comparison_case,
        baseline,
        frontend,
        baseline_only=False,
        front_only=False,
    )
    comparison["route_matches_baseline"] = route_matches_baseline
    comparison["expected_api"] = case.get("expected_api")
    comparison["expected_apis"] = case.get("expected_apis")
    comparison["actual_api"] = frontend.get("selected_api")
    comparison["actual_apis"] = frontend.get("selected_apis", [])
    if comparison.get("passed") and not route_matches_baseline:
        comparison["route_variance"] = "alternate_executable_route"
    return comparison


def build_summary(run_id: str, results: list[dict[str, Any]], *, baseline_only: bool) -> dict[str, Any]:
    passed = sum(1 for item in results if item["status"] == "passed")
    baseline_valid = sum(1 for item in results if (item.get("baseline") or {}).get("success"))
    failures_by_layer: dict[str, int] = {}
    for item in results:
        if item["status"] == "passed":
            continue
        layer = str(item.get("failed_layer") or "unknown")
        failures_by_layer[layer] = failures_by_layer.get(layer, 0) + 1
    codex_durations = [
        float((item.get("codex") or {}).get("duration_ms"))
        for item in results
        if item.get("status") == "passed" and (item.get("codex") or {}).get("duration_ms") is not None
    ]
    route_comparisons = [
        item.get("comparison") or {}
        for item in results
        if "route_matches_baseline" in (item.get("comparison") or {})
    ]
    route_matches = sum(1 for comparison in route_comparisons if comparison.get("route_matches_baseline"))
    return {
        "run_id": run_id,
        "mode": "baseline_only" if baseline_only else "codex_thin_mcp",
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "baseline_valid": baseline_valid,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "acceptance_target": 45 if len(results) == 50 and not baseline_only else None,
        "acceptance_met": passed >= 45 if len(results) == 50 and not baseline_only else None,
        "failures_by_layer": failures_by_layer,
        "codex_latency_ms": {
            "sample_count": len(codex_durations),
            "p50": percentile(codex_durations, 50),
            "p95": percentile(codex_durations, 95),
        }
        if codex_durations
        else None,
        "route_accuracy": {
            "checked": len(route_comparisons),
            "matched_baseline_route": route_matches,
            "alternate_executable_route": len(route_comparisons) - route_matches,
            "match_rate": round(route_matches / len(route_comparisons), 4) if route_comparisons else None,
        },
        "finished_at": datetime.now().astimezone().isoformat(),
    }


def provider_capacity_failure(result: dict[str, Any]) -> bool:
    return str(result.get("failed_layer") or "") in {
        "codex_quota_limited",
        "codex_rate_limited",
    }


def percentile(values: list[float], percentile_value: int) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    rank = max(1, math.ceil((max(0, min(100, percentile_value)) / 100) * len(ordered)))
    return round(ordered[rank - 1], 2)


def write_output_schema(run_dir: Path) -> Path:
    path = run_dir / "codex_output_schema.json"
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "case_id": {"type": ["string", "null"]},
            "status": {"type": "string"},
            "answer": {"type": "string"},
            "error": {"type": ["string", "null"]},
        },
        "required": ["case_id", "status", "answer", "error"],
    }
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def parse_json_object(value: str) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def classify_codex_failure(value: str) -> str:
    lowered = value.lower()
    if "usage limit" in lowered or "purchase more credits" in lowered:
        return "codex_quota_limited"
    if (
        "rate limit" in lowered
        or "too many requests" in lowered
        or "selected model is at capacity" in lowered
        or "model at capacity" in lowered
    ):
        return "codex_rate_limited"
    if "timed out" in lowered or "timeout" in lowered:
        return "codex_timeout"
    if "mcp" in lowered and ("startup failed" in lowered or "handshaking" in lowered):
        return "mcp_startup_failed"
    if "tool call" in lowered and ("cancelled" in lowered or "canceled" in lowered):
        return "mcp_tool_cancelled"
    return "codex_failed"


def compact_error(value: str, limit: int = 1200) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    selected = [
        line
        for line in lines
        if any(
            token in line.lower()
            for token in ("error", "failed", "usage limit", "rate limit", "timed out", "timeout")
        )
    ]
    text = " | ".join(selected[-6:] or lines[-3:])
    return text[-limit:]


def _safe_int(value: Any, fallback: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return fallback


if __name__ == "__main__":
    main()
