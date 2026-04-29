from sap_odata_agent.tools.run_llm_e2e_tests import _compare, _is_rate_limited_result


def test_compare_fails_when_frontend_omits_required_fields() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "count_only",
            "keys": ["Document"],
            "required_fields": ["Document", "Amount"],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 1,
            "keys": [{"Document": "1"}],
            "results": [{"Document": "1", "Amount": "10"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "needs_clarification": False,
        "result_count": 1,
        "results": [{"Document": "1"}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is False
    assert result["failed_layer"] == "planner"
    assert result["missing_required_fields"] == ["Amount"]


def test_rate_limit_result_detection() -> None:
    result = {
        "comparison": {
            "reason": "Planner did not produce an executable schema plan: HTTP Error 429: Too Many Requests"
        }
    }

    assert _is_rate_limited_result(result) is True
