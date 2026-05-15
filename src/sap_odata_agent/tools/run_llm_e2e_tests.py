from __future__ import annotations

import argparse
import json
import time
import traceback
import urllib.parse
from dataclasses import asdict, is_dataclass
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any
from uuid import uuid4

from sap_odata_agent.api.app_dependencies import get_orchestrator, get_sap_executor
from sap_odata_agent.application.result_transformer import ResultTransformer
from sap_odata_agent.domain.models import AgentRequest, CompiledRequest, QueryPlan, ResultTransform
from sap_odata_agent.infrastructure.config.settings import get_settings


CASE_ROOT = Path("data/api_test_cases")
RUN_ROOT = Path("data/api_test_runs")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run natural-language SAP API e2e evaluation cases.")
    parser.add_argument("--api", action="append", help="API service name to run. Can be repeated.")
    parser.add_argument("--module", action="append", help="Cross-API module folder to run. Alias of --api for cross-api case roots.")
    parser.add_argument("--case-root", default=str(CASE_ROOT), help="Case asset root. Defaults to data/api_test_cases.")
    parser.add_argument("--run-root", default=str(RUN_ROOT), help="Run output root. Defaults to data/api_test_runs.")
    parser.add_argument("--case-id", action="append", help="Single case id to run. Can be repeated.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of cases to run.")
    parser.add_argument("--run-id", default="", help="Existing or new run id.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip cases already present in the run folder.")
    parser.add_argument("--baseline-only", action="store_true", help="Only refresh deterministic baseline data.")
    parser.add_argument("--front-only", action="store_true", help="Only run the LLM-first agent chain.")
    parser.add_argument("--use-existing-baseline", action="store_true", help="Read existing baseline files instead of refreshing them.")
    parser.add_argument("--case-delay-seconds", type=float, default=0.0, help="Delay between cases to avoid LLM rate limits.")
    parser.add_argument("--rate-limit-retries", type=int, default=1, help="Retry a case when the LLM provider returns HTTP 429.")
    parser.add_argument("--rate-limit-sleep-seconds", type=float, default=30.0, help="Sleep before retrying an HTTP 429 case.")
    parser.add_argument("--shared-conversation", action="store_true", help="Reuse one conversation across cases. Default is one isolated conversation per case.")
    args = parser.parse_args()

    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    case_root = Path(args.case_root)
    run_root = Path(args.run_root)
    run_dir = run_root / run_id
    per_case_dir = run_dir / "per_case"
    per_case_dir.mkdir(parents=True, exist_ok=True)

    selected_groups = args.api or args.module
    cases = _load_cases(case_root, selected_groups, args.case_id)
    if args.limit > 0:
        cases = cases[: args.limit]

    results: list[dict[str, Any]] = []
    for case in cases:
        out_path = per_case_dir / f"{case['id']}.json"
        if args.skip_existing and out_path.exists():
            results.append(json.loads(out_path.read_text(encoding="utf-8")))
            continue
        result = _run_case_with_retries(
            case,
            run_id,
            case_root,
            baseline_only=args.baseline_only,
            front_only=args.front_only,
            use_existing_baseline=args.use_existing_baseline,
            rate_limit_retries=max(0, args.rate_limit_retries),
            rate_limit_sleep_seconds=max(0.0, args.rate_limit_sleep_seconds),
            shared_conversation=args.shared_conversation,
        )
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
        print(f"{case['id']}: {result['status']} ({result.get('failed_layer') or 'ok'})")
        if args.case_delay_seconds > 0:
            time.sleep(args.case_delay_seconds)

    summary = _build_summary(run_id, results)
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    failures = [item for item in results if item["status"] != "passed"]
    (run_dir / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _load_cases(
    case_root: Path,
    api_names: list[str] | None,
    case_ids: list[str] | None,
) -> list[dict[str, Any]]:
    selected_apis = api_names or [
        path.name for path in sorted(case_root.iterdir()) if (path / "cases.json").exists()
    ]
    selected_case_ids = set(case_ids or [])
    cases: list[dict[str, Any]] = []
    for api_name in selected_apis:
        path = case_root / api_name / "cases.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing cases file: {path}")
        api_cases = json.loads(path.read_text(encoding="utf-8-sig"))
        for case in api_cases:
            if selected_case_ids and case["id"] not in selected_case_ids:
                continue
            cases.append(case)
    return cases


def _run_case(
    case: dict[str, Any],
    run_id: str,
    case_root: Path,
    *,
    baseline_only: bool,
    front_only: bool,
    use_existing_baseline: bool,
    shared_conversation: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now().astimezone().isoformat()
    expects_unsupported = bool(case.get("expected_capability", {}).get("unsupported"))
    baseline = None if front_only or expects_unsupported else _load_or_run_baseline(case, case_root, use_existing_baseline)
    frontend = None if baseline_only else _run_frontend(case, run_id, shared_conversation=shared_conversation)
    comparison = _compare(case, baseline, frontend, baseline_only=baseline_only, front_only=front_only)
    return {
        "run_id": run_id,
        "case_id": case["id"],
        "api": case["api"],
        "scenario": case["scenario"],
        "user_input": case["user_input"],
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(),
        "status": "passed" if comparison["passed"] else "failed",
        "failed_layer": comparison.get("failed_layer"),
        "comparison": comparison,
        "baseline": baseline,
        "frontend": frontend,
    }


def _run_case_with_retries(
    case: dict[str, Any],
    run_id: str,
    case_root: Path,
    *,
    baseline_only: bool,
    front_only: bool,
    use_existing_baseline: bool,
    rate_limit_retries: int,
    rate_limit_sleep_seconds: float,
    shared_conversation: bool,
) -> dict[str, Any]:
    attempts = max(1, rate_limit_retries + 1)
    last_result: dict[str, Any] | None = None
    for index in range(attempts):
        try:
            result = _run_case(
                case,
                run_id,
                case_root,
                baseline_only=baseline_only,
                front_only=front_only,
                use_existing_baseline=use_existing_baseline,
                shared_conversation=shared_conversation,
            )
        except Exception as exc:  # pragma: no cover - runtime protection for long SAP/LLM runs
            result = _runtime_failure(case, run_id, exc)
        if not _is_rate_limited_result(result) or index >= attempts - 1:
            if index:
                result["rate_limit_retry_count"] = index
            return result
        last_result = result
        time.sleep(rate_limit_sleep_seconds)
    return last_result or _runtime_failure(case, run_id, RuntimeError("Case retry loop did not run."))


def _load_or_run_baseline(
    case: dict[str, Any],
    case_root: Path,
    use_existing_baseline: bool,
) -> dict[str, Any]:
    baseline_path = case_root / case["api"] / "baselines" / f"{case['id']}.json"
    if use_existing_baseline and baseline_path.exists():
        return json.loads(baseline_path.read_text(encoding="utf-8"))
    return _run_baseline(case, case_root)


def _runtime_failure(case: dict[str, Any], run_id: str, exc: Exception) -> dict[str, Any]:
    stack = traceback.format_exc()
    failed_layer = _infer_exception_layer(stack)
    return {
        "run_id": run_id,
        "case_id": case["id"],
        "api": case["api"],
        "scenario": case["scenario"],
        "user_input": case["user_input"],
        "started_at": datetime.now().astimezone().isoformat(),
        "finished_at": datetime.now().astimezone().isoformat(),
        "status": "failed",
        "failed_layer": failed_layer,
        "comparison": {
            "passed": False,
            "failed_layer": failed_layer,
            "reason": f"{type(exc).__name__}: {exc}",
            "traceback": stack,
        },
        "baseline": None,
        "frontend": None,
    }


def _is_rate_limited_result(result: dict[str, Any]) -> bool:
    text = json.dumps(result, ensure_ascii=False, default=str)
    return (
        "HTTP Error 429" in text
        or "Too Many Requests" in text
        or "api_router_failed" in text
        or "api_routing_failed" in text
        or "HTTP Error 400" in text
        or "The read operation timed out" in text
    )


def _infer_exception_layer(stack: str) -> str:
    lowered = stack.lower()
    if "api_router" in lowered:
        return "router"
    if "schema_context" in lowered or "schema_research" in lowered:
        return "schema_context"
    if "planner" in lowered or "plan_repairer" in lowered:
        return "planner"
    if "result_verifier" in lowered:
        return "verifier"
    if "result_presenter" in lowered:
        return "presenter"
    if "odata_client" in lowered:
        return "executor"
    return "runner"


def _run_baseline(case: dict[str, Any], case_root: Path = CASE_ROOT) -> dict[str, Any]:
    executor = get_sap_executor()
    settings = get_settings()
    step_outputs: dict[str, dict[str, Any]] = {}
    baseline_steps: list[dict[str, Any]] = []

    for index, step in enumerate(case["baseline"]["steps"], start=1):
        url = _absolute_url(settings.sap_base_url, step["url"])
        skip_reason = ""
        fanout_bindings: list[dict[str, Any]] = []
        for bind in _iter_step_bindings(step):
            source_output = step_outputs[bind["source_step"]]
            values = _extract_values(source_output["results"], bind["source_field"])
            if not values:
                skip_reason = (
                    f"Skipped because binding source `{bind['source_step']}.{bind['source_field']}` "
                    "returned no values."
                )
                break
            if bind.get("fanout") and len(values) > 1:
                fanout_bindings.append({**bind, "values": values})
                continue
            url = _append_binding_filter(url, bind["target_field"], values)

        if skip_reason:
            step_output = {
                "id": step["id"],
                "success": True,
                "status_code": None,
                "request_url": url,
                "error_message": None,
                "result_count": 0,
                "returned_count": 0,
                "key_fields": step.get("key_fields", []),
                "keys": [],
                "results": [],
                "skipped": True,
                "skip_reason": skip_reason,
                "attempt": None,
            }
            baseline_steps.append(step_output)
            step_outputs[step["id"]] = step_output
            break

        if fanout_bindings:
            step_output = _run_baseline_fanout_step(executor, step, url, fanout_bindings, index)
            baseline_steps.append(step_output)
            step_outputs[step["id"]] = step_output
            if not step_output["success"]:
                break
            continue

        attempt = executor.execute(CompiledRequest(method="GET", url=url), attempt_number=index)
        attempt_dict = _to_jsonable(attempt)
        results = _extract_results(attempt.response_preview)
        step_output = {
            "id": step["id"],
            "success": attempt.success,
            "status_code": attempt.status_code,
            "request_url": attempt.request.url,
            "error_message": attempt.error_message,
            "result_count": _result_count(attempt.response_preview, results),
            "returned_count": len(results),
            "key_fields": step.get("key_fields", []),
            "keys": _key_set(results, step.get("key_fields", [])),
            "results": results,
            "attempt": attempt_dict,
        }
        baseline_steps.append(step_output)
        step_outputs[step["id"]] = step_output
        if not attempt.success:
            break

    final_step = baseline_steps[-1] if baseline_steps else {}
    final_result = _baseline_final_result(case, final_step)
    baseline = {
        "success": bool(final_step.get("success")),
        "steps": baseline_steps,
        "final": final_result,
    }
    baseline_path = case_root / case["api"] / "baselines" / f"{case['id']}.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline


def _run_baseline_fanout_step(
    executor: Any,
    step: dict[str, Any],
    base_url: str,
    fanout_bindings: list[dict[str, Any]],
    attempt_number: int,
) -> dict[str, Any]:
    fields = [str(binding["target_field"]) for binding in fanout_bindings]
    value_sets = [[str(value) for value in binding.get("values", [])] for binding in fanout_bindings]
    attempts: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    result_count = 0
    request_urls: list[str] = []
    for offset, values in enumerate(product(*value_sets)):
        url = base_url
        extracted = dict(zip(fields, values, strict=True))
        for field, value in extracted.items():
            url = _append_binding_filter(url, field, [value])
        attempt = executor.execute(CompiledRequest(method="GET", url=url), attempt_number=attempt_number + offset)
        attempts.append(_to_jsonable(attempt))
        request_urls.append(attempt.request.url)
        step_results = _extract_results(attempt.response_preview)
        results.extend(step_results)
        result_count += _result_count(attempt.response_preview, step_results)
        if not attempt.success:
            return {
                "id": step["id"],
                "success": False,
                "status_code": attempt.status_code,
                "request_url": attempt.request.url,
                "request_urls": request_urls,
                "error_message": attempt.error_message,
                "result_count": result_count,
                "returned_count": len(results),
                "key_fields": step.get("key_fields", []),
                "keys": _key_set(results, step.get("key_fields", [])),
                "results": results,
                "attempts": attempts,
            }
    return {
        "id": step["id"],
        "success": True,
        "status_code": 200,
        "request_url": request_urls[-1] if request_urls else base_url,
        "request_urls": request_urls,
        "error_message": None,
        "result_count": result_count,
        "returned_count": len(results),
        "key_fields": step.get("key_fields", []),
        "keys": _key_set(results, step.get("key_fields", [])),
        "results": results,
        "attempts": attempts,
    }


def _baseline_final_result(case: dict[str, Any], final_step: dict[str, Any]) -> dict[str, Any]:
    result = {
        "result_count": final_step.get("result_count", 0),
        "returned_count": final_step.get("returned_count", 0),
        "key_fields": final_step.get("key_fields", []),
        "keys": final_step.get("keys", []),
        "results": final_step.get("results", []),
    }
    transform_spec = (case.get("baseline") or {}).get("result_transform")
    if not isinstance(transform_spec, dict):
        return result
    if str(transform_spec.get("type") or "").lower() != "aggregate":
        return result
    group_by = [str(item) for item in transform_spec.get("group_by", []) if str(item).strip()]
    sum_fields = [str(item) for item in transform_spec.get("sum_fields", []) if str(item).strip()]
    if not group_by or not sum_fields:
        return result

    transformer = ResultTransformer()
    transformed = transformer.apply(
        QueryPlan(
            service_name=str(case.get("expected_api") or case.get("api") or ""),
            entity_set="",
            result_transform=ResultTransform(type="aggregate", group_by=group_by, sum_fields=sum_fields),
        ),
        {
            "result_count": result["result_count"],
            "returned_count": result["returned_count"],
            "results": result["results"],
            "_all_results": result["results"],
        },
    )
    if not isinstance(transformed, dict):
        return result
    key_fields = case.get("comparison", {}).get("keys") or group_by
    return {
        "result_count": transformed.get("result_count", 0),
        "returned_count": transformed.get("returned_count", 0),
        "key_fields": key_fields,
        "keys": _key_set(transformed.get("results", []), key_fields),
        "results": transformed.get("results", []),
        "result_transform": transformed.get("result_transform"),
    }


def _iter_step_bindings(step: dict[str, Any]) -> list[dict[str, Any]]:
    raw_bindings: list[Any] = []
    for key in ("bind", "binds", "bindings", "filter_from_previous"):
        value = step.get(key)
        if isinstance(value, list):
            raw_bindings.extend(value)
        elif isinstance(value, dict):
            raw_bindings.append(value)

    bindings: list[dict[str, Any]] = []
    for raw in raw_bindings:
        if not isinstance(raw, dict):
            continue
        source_step = raw.get("source_step") or raw.get("source_step_id")
        source_field = raw.get("source_field")
        target_field = raw.get("target_field") or raw.get("field")
        if source_step and source_field and target_field:
            bindings.append(
                {
                    "source_step": str(source_step),
                    "source_field": str(source_field),
                    "target_field": str(target_field),
                    "fanout": bool(raw.get("fanout", False)),
                }
            )
    return bindings


def _run_frontend(case: dict[str, Any], run_id: str, *, shared_conversation: bool = False) -> dict[str, Any]:
    orchestrator = get_orchestrator()
    conversation_id = f"eval-{run_id}" if shared_conversation else f"eval-{run_id}-{case['id']}"
    response = orchestrator.run(
        AgentRequest(
            user_input=case["user_input"],
            conversation_id=conversation_id,
        )
    )
    response_dict = _to_jsonable(response)
    data = response.data or {}
    attempts = response.attempts or []
    return {
        "success": response.success,
        "needs_clarification": response.needs_clarification,
        "case_id": response.case_id,
        "selected_api": response.plan.service_name,
        "selected_apis": _selected_services(response),
        "entity_set": response.plan.entity_set,
        "final_message": response.final_message,
        "result_count": data.get("result_count", 0) if isinstance(data, dict) else 0,
        "returned_count": data.get("returned_count", 0) if isinstance(data, dict) else 0,
        "results": _extract_results(data),
        "final_request_url": attempts[-1].request.url if attempts else None,
        "failure_attribution": response_dict.get("failure_attribution"),
        "critic_findings": response_dict.get("critic_findings", []),
        "presentation": response_dict.get("presentation"),
        "raw_response": response_dict,
    }


def _selected_services(response: Any) -> list[str]:
    services: list[str] = []

    def add_service(value: Any) -> None:
        service_name = str(value or "").strip()
        if service_name:
            services.append(service_name)

    def add_schema_context_services(value: Any) -> None:
        if isinstance(value, dict):
            schema_context = value.get("schema_context")
            if isinstance(schema_context, dict):
                for service_name in schema_context.get("service_names", []) or []:
                    add_service(service_name)
                add_service(schema_context.get("service_name"))
            for nested in value.values():
                add_schema_context_services(nested)
        elif isinstance(value, list):
            for item in value:
                add_schema_context_services(item)

    plan = getattr(response, "plan", None)
    if plan is None:
        return services
    service_name = getattr(plan, "service_name", None)
    add_service(service_name)
    for step in getattr(plan, "steps", []) or []:
        step_service = getattr(step, "service_name", None)
        add_service(step_service)
    add_schema_context_services(getattr(plan, "planner_diagnostics", {}) or {})
    return list(dict.fromkeys(services))


def _expected_api_matches(case: dict[str, Any], frontend: dict[str, Any]) -> bool:
    actual = set(frontend.get("selected_apis") or [])
    selected_api = frontend.get("selected_api")
    if selected_api:
        actual.add(str(selected_api))
    expected_apis = [str(item) for item in case.get("expected_apis") or [] if str(item)]
    if expected_apis:
        if case.get("require_all_expected_apis"):
            return set(expected_apis).issubset(actual)
        return bool(set(expected_apis) & actual)
    expected_api = case.get("expected_api")
    if expected_api:
        return str(expected_api) in actual
    return True


def _compare(
    case: dict[str, Any],
    baseline: dict[str, Any] | None,
    frontend: dict[str, Any] | None,
    *,
    baseline_only: bool,
    front_only: bool,
) -> dict[str, Any]:
    if baseline_only:
        if case.get("expected_capability", {}).get("unsupported"):
            return {"passed": True, "mode": "baseline_only", "reason": "Unsupported case has no deterministic baseline."}
        return {"passed": bool(baseline and baseline["success"]), "mode": "baseline_only"}
    if front_only:
        return {"passed": bool(frontend and frontend["success"]), "mode": "front_only"}
    if case.get("expected_capability", {}).get("unsupported"):
        if frontend is None:
            return {"passed": False, "failed_layer": "runner", "reason": "Frontend result missing."}
        route_passed = _expected_api_matches(case, frontend)
        unsupported_passed = not frontend["success"]
        return {
            "passed": route_passed and unsupported_passed,
            "failed_layer": None if route_passed and unsupported_passed else "unsupported_handling",
            "expected_api": case.get("expected_api"),
            "expected_apis": case.get("expected_apis"),
            "actual_api": frontend["selected_api"],
            "actual_apis": frontend.get("selected_apis", []),
            "frontend_success": frontend["success"],
            "final_message": frontend.get("final_message"),
        }
    if baseline is None or not baseline["success"]:
        return {"passed": False, "failed_layer": "baseline", "reason": "Baseline request failed."}
    if frontend is None:
        return {"passed": False, "failed_layer": "runner", "reason": "Frontend result missing."}
    if not _expected_api_matches(case, frontend):
        return {
            "passed": False,
            "failed_layer": "router",
            "reason": "Selected API mismatch.",
            "expected_api": case.get("expected_api"),
            "expected_apis": case.get("expected_apis"),
            "actual_api": frontend["selected_api"],
            "actual_apis": frontend.get("selected_apis", []),
        }
    if case["expected_capability"].get("clarify"):
        return {
            "passed": bool(frontend["needs_clarification"]),
            "failed_layer": None if frontend["needs_clarification"] else "clarification",
            "reason": "" if frontend["needs_clarification"] else "Expected clarification was not requested.",
        }
    if not frontend["success"]:
        return {
            "passed": False,
            "failed_layer": "planner",
            "reason": frontend.get("final_message") or "Frontend chain failed.",
            "failure_attribution": frontend.get("failure_attribution"),
        }

    comparison = case["comparison"]
    comparison_type = comparison["type"]
    missing_required_fields = _missing_required_fields(
        frontend["results"],
        comparison.get("required_fields", []),
        frontend.get("result_count", 0),
    )
    missing_required_field_groups = _missing_required_field_groups(
        frontend["results"],
        comparison.get("required_any_fields", []),
        frontend.get("result_count", 0),
    )
    if missing_required_fields or missing_required_field_groups:
        return {
            "passed": False,
            "failed_layer": "planner",
            "reason": "Frontend results are missing required fields.",
            "missing_required_fields": missing_required_fields,
            "missing_required_any_fields": missing_required_field_groups,
        }
    baseline_final = baseline["final"]
    baseline_keys = set(_tuple_keys(baseline_final["keys"]))
    actual_keys = set(_tuple_keys(_key_set(frontend["results"], comparison.get("keys", []))))
    baseline_scope_limited = _baseline_scope_limited(baseline)

    if comparison_type == "count_only":
        passed = baseline_final["result_count"] == frontend["result_count"]
        return {
            "passed": passed,
            "failed_layer": None if passed else "planner",
            "baseline_count": baseline_final["result_count"],
            "actual_count": frontend["result_count"],
        }

    if comparison_type == "count_and_key_subset":
        count_passed = baseline_final["result_count"] == frontend["result_count"]
        no_results = baseline_final["result_count"] == 0 and frontend["result_count"] == 0
        baseline_page_too_small = int(baseline_final.get("returned_count", len(baseline_final.get("results", [])))) < len(actual_keys)
        key_passed = no_results or (actual_keys.issubset(baseline_keys) if actual_keys else False)
        frontend_superset_of_limited_baseline = bool(baseline_keys) and baseline_keys.issubset(actual_keys)
        if not count_passed and baseline_scope_limited and frontend.get("result_count", 0) >= baseline_final["result_count"]:
            count_passed = True
        if not key_passed and (
            (count_passed and baseline_page_too_small)
            or (baseline_scope_limited and frontend_superset_of_limited_baseline)
        ):
            key_passed = True
        return {
            "passed": count_passed and key_passed,
            "failed_layer": None if count_passed and key_passed else "planner",
            "baseline_count": baseline_final["result_count"],
            "actual_count": frontend["result_count"],
            "key_check_limited_by_baseline_page": bool(
                (count_passed and baseline_page_too_small) or baseline_scope_limited
            ),
            "actual_keys_not_in_baseline": sorted(actual_keys - baseline_keys),
            "baseline_keys_missing_from_actual_page": sorted(list(baseline_keys - actual_keys))[:50],
        }

    if comparison_type == "key_subset":
        no_results = baseline_final["result_count"] == 0 and frontend["result_count"] == 0
        count_passed = baseline_final["result_count"] == frontend["result_count"]
        baseline_page_too_small = int(baseline_final.get("returned_count", len(baseline_final.get("results", [])))) < len(actual_keys)
        key_passed = no_results or (actual_keys.issubset(baseline_keys) and bool(actual_keys))
        frontend_superset_of_limited_baseline = bool(baseline_keys) and baseline_keys.issubset(actual_keys)
        if not key_passed and (
            (count_passed and baseline_page_too_small)
            or (baseline_scope_limited and frontend_superset_of_limited_baseline)
        ):
            key_passed = True
        return {
            "passed": key_passed,
            "failed_layer": None if key_passed else "planner",
            "baseline_count": baseline_final["result_count"],
            "actual_count": frontend["result_count"],
            "key_check_limited_by_baseline_page": bool(
                (count_passed and baseline_page_too_small) or baseline_scope_limited
            ),
            "actual_keys_not_in_baseline": sorted(actual_keys - baseline_keys),
            "baseline_keys_missing_from_actual_page": sorted(list(baseline_keys - actual_keys))[:50],
        }

    if comparison_type == "key_set":
        passed = baseline_keys == actual_keys
        return {
            "passed": passed,
            "failed_layer": None if passed else "planner",
            "baseline_count": baseline_final["result_count"],
            "actual_count": frontend["result_count"],
            "missing_keys": sorted(list(baseline_keys - actual_keys))[:100],
            "unexpected_keys": sorted(list(actual_keys - baseline_keys))[:100],
        }

    return {"passed": False, "failed_layer": "runner", "reason": f"Unsupported comparison: {comparison_type}"}


def _baseline_scope_limited(baseline: dict[str, Any]) -> bool:
    for step in baseline.get("steps", []) or []:
        try:
            result_count = int(step.get("result_count", 0) or 0)
            returned_count = int(step.get("returned_count", 0) or 0)
        except (TypeError, ValueError):
            continue
        if result_count > returned_count >= 0:
            return True
    final = baseline.get("final", {})
    try:
        return int(final.get("result_count", 0) or 0) > int(final.get("returned_count", 0) or 0)
    except (TypeError, ValueError):
        return False


def _build_summary(run_id: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [item for item in results if item["status"] != "passed"]
    return {
        "run_id": run_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "failure_layers": _count_by(failed, "failed_layer"),
        "cases": [
            {
                "case_id": item["case_id"],
                "api": item["api"],
                "scenario": item["scenario"],
                "status": item["status"],
                "failed_layer": item.get("failed_layer"),
            }
            for item in results
        ],
    }


def _absolute_url(base_url: str, url: str) -> str:
    if url.startswith("http"):
        return url
    return base_url.rstrip("/") + "/" + url.lstrip("/")


def _append_binding_filter(url: str, target_field: str, values: list[Any]) -> str:
    split = urllib.parse.urlsplit(url)
    params = urllib.parse.parse_qsl(split.query, keep_blank_values=True)
    existing_filter = ""
    other_params: list[tuple[str, str]] = []
    for key, value in params:
        if key == "$filter":
            existing_filter = value
        else:
            other_params.append((key, value))
    unique_values = [str(value) for value in dict.fromkeys(values) if str(value)]
    binding_filter = " or ".join(f"{target_field} eq '{value.replace("'", "''")}'" for value in unique_values)
    if binding_filter:
        binding_filter = f"({binding_filter})"
    combined_filter = binding_filter
    if existing_filter and binding_filter:
        combined_filter = f"{existing_filter} and {binding_filter}"
    elif existing_filter:
        combined_filter = existing_filter
    if combined_filter:
        other_params.insert(0, ("$filter", combined_filter))
    query = urllib.parse.urlencode(other_params, safe="$(),'/ ")
    return urllib.parse.urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def _extract_results(preview: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(preview, dict):
        return []
    results = preview.get("_all_results") or preview.get("results") or []
    return [item for item in results if isinstance(item, dict)]


def _result_count(preview: dict[str, Any] | None, results: list[dict[str, Any]]) -> int:
    if isinstance(preview, dict):
        try:
            return int(preview.get("result_count", len(results)))
        except (TypeError, ValueError):
            pass
    return len(results)


def _extract_values(results: list[dict[str, Any]], field: str) -> list[Any]:
    return [item.get(field) for item in results if item.get(field) not in (None, "")]


def _key_set(results: list[dict[str, Any]], fields: list[str]) -> list[dict[str, Any]]:
    if not fields:
        return []
    keys: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in results:
        key = tuple(item.get(field) for field in fields)
        if key in seen:
            continue
        seen.add(key)
        keys.append({field: item.get(field) for field in fields})
    return keys


def _missing_required_fields(
    results: list[dict[str, Any]],
    required_fields: list[str],
    result_count: int,
) -> list[str]:
    required = [str(field or "").strip() for field in required_fields if str(field or "").strip()]
    if not required:
        return []
    if result_count <= 0:
        return []
    if not results:
        return required
    available = set().union(*(set(item) for item in results))
    return [field for field in required if field not in available]


def _missing_required_field_groups(
    results: list[dict[str, Any]],
    required_any_fields: list[list[str]],
    result_count: int,
) -> list[list[str]]:
    groups = [
        [str(field or "").strip() for field in group if str(field or "").strip()]
        for group in required_any_fields
        if isinstance(group, list)
    ]
    groups = [group for group in groups if group]
    if not groups or result_count <= 0:
        return []
    if not results:
        return groups
    available = set().union(*(set(item) for item in results))
    return [group for group in groups if not any(field in available for field in group)]


def _tuple_keys(keys: list[dict[str, Any]]) -> list[tuple[tuple[str, Any], ...]]:
    return [tuple(sorted(item.items())) for item in keys]


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = str(item.get(key) or "unknown")
        counts[value] = counts.get(value, 0) + 1
    return counts


if __name__ == "__main__":
    main()
