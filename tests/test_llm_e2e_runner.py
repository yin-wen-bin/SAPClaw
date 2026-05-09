from sap_odata_agent.tools.run_llm_e2e_tests import (
    _compare,
    _expected_api_matches,
    _is_rate_limited_result,
    _iter_step_bindings,
)


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


def test_iter_step_bindings_supports_multiple_binding_shapes() -> None:
    step = {
        "bind": {"source_step": "a", "source_field": "Document", "target_field": "ReferenceDocument"},
        "bindings": [
            {"source_step": "b", "source_field": "Item", "target_field": "ReferenceItem"},
            {"source_step_id": "c", "source_field": "Group", "field": "TargetGroup"},
        ],
    }

    assert _iter_step_bindings(step) == [
        {"source_step": "a", "source_field": "Document", "target_field": "ReferenceDocument"},
        {"source_step": "b", "source_field": "Item", "target_field": "ReferenceItem"},
        {"source_step": "c", "source_field": "Group", "target_field": "TargetGroup"},
    ]


def test_compare_key_subset_passes_when_baseline_and_frontend_are_empty() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "key_subset",
            "keys": ["Document"],
            "required_fields": ["Document"],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 0,
            "keys": [],
            "results": [],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "needs_clarification": False,
        "result_count": 0,
        "results": [],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True
    assert result["failed_layer"] is None


def test_rate_limit_result_detection() -> None:
    result = {
        "comparison": {
            "reason": "Planner did not produce an executable schema plan: HTTP Error 429: Too Many Requests"
        }
    }

    assert _is_rate_limited_result(result) is True


def test_expected_apis_allow_single_relevant_api_by_default() -> None:
    case = {"expected_apis": ["API_A", "API_B"]}
    frontend = {"selected_api": "API_B", "selected_apis": ["API_B"]}

    assert _expected_api_matches(case, frontend) is True


def test_expected_apis_can_require_all_services() -> None:
    case = {"expected_apis": ["API_A", "API_B"], "require_all_expected_apis": True}
    frontend = {"selected_api": "API_B", "selected_apis": ["API_B"]}

    assert _expected_api_matches(case, frontend) is False


def test_key_subset_allows_count_match_when_baseline_page_is_smaller() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "key_subset",
            "keys": ["Document"],
            "required_fields": ["Document"],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 3,
            "returned_count": 1,
            "keys": [{"Document": "1"}],
            "results": [{"Document": "1"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "selected_apis": ["API_TEST"],
        "needs_clarification": False,
        "result_count": 3,
        "results": [{"Document": "1"}, {"Document": "2"}, {"Document": "3"}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True
    assert result["key_check_limited_by_baseline_page"] is True


def test_key_subset_allows_frontend_superset_when_upstream_baseline_step_is_limited() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "key_subset",
            "keys": ["Document", "Item"],
            "required_fields": ["Document", "Item"],
        },
    }
    baseline = {
        "success": True,
        "steps": [
            {
                "id": "headers",
                "result_count": 100,
                "returned_count": 20,
                "keys": [{"Document": "1"}],
                "results": [{"Document": "1"}],
            },
            {
                "id": "items",
                "result_count": 1,
                "returned_count": 1,
                "keys": [{"Document": "1", "Item": "10"}],
                "results": [{"Document": "1", "Item": "10"}],
            },
        ],
        "final": {
            "result_count": 1,
            "returned_count": 1,
            "keys": [{"Document": "1", "Item": "10"}],
            "results": [{"Document": "1", "Item": "10"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "selected_apis": ["API_TEST"],
        "needs_clarification": False,
        "result_count": 2,
        "results": [{"Document": "1", "Item": "10"}, {"Document": "2", "Item": "10"}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True
    assert result["key_check_limited_by_baseline_page"] is True


def test_compare_accepts_required_any_field_group() -> None:
    case = {
        "expected_api": "API_TEST",
        "expected_capability": {},
        "comparison": {
            "type": "count_only",
            "keys": ["Document"],
            "required_fields": ["Document"],
            "required_any_fields": [["GLAccountType", "IsBalanceSheetAccount", "ProfitLossAccountType"]],
        },
    }
    baseline = {
        "success": True,
        "final": {
            "result_count": 1,
            "keys": [{"Document": "1"}],
            "results": [{"Document": "1", "GLAccountType": "X"}],
        },
    }
    frontend = {
        "success": True,
        "selected_api": "API_TEST",
        "selected_apis": ["API_TEST"],
        "needs_clarification": False,
        "result_count": 1,
        "results": [{"Document": "1", "IsBalanceSheetAccount": True}],
    }

    result = _compare(case, baseline, frontend, baseline_only=False, front_only=False)

    assert result["passed"] is True
