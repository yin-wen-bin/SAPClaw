import json
from pathlib import Path

from sap_odata_agent.domain.models import AgentRequest, ApiRouteDecision, ExecutionStep, QueryPlan, SelectedApi, StepBinding
from sap_odata_agent.infrastructure.llm.api_specific_planner import LlmApiSpecificPlanner
from sap_odata_agent.infrastructure.llm.plan_repairer import LlmPlanRepairer


class CapturingClient:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.system_prompt = ""
        self.user_prompt = ""

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return json.dumps(self.response)


class FailingClient:
    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        raise AssertionError("shortcut plan should not call the LLM")


def _write_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST", "entity_sets": ["A_Test", "A_Extra"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "entity_type": "A_TestType",
                    "key_fields": ["Document"],
                    "default_select_fields": ["Document", "IsClosed"],
                    "supported_methods": ["GET"],
                    "description": "Test document items",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Extra",
                    "entity_type": "A_ExtraType",
                    "key_fields": ["Document"],
                    "default_select_fields": ["Document", "Name"],
                    "supported_methods": ["GET"],
                    "description": "Optional enrichment records",
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "Document",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "IsClosed",
                    "data_type": "Edm.Boolean",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "FunctionalArea",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "Amount",
                    "data_type": "Edm.Decimal",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "Period",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "FiscalYear",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Extra",
                    "field_name": "Document",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Extra",
                    "field_name": "Name",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    for name in ["relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"]:
        (service_dir / name).write_text("[]", encoding="utf-8")


def _api_test_schema_context() -> dict:
    return {
        "service_name": "API_TEST",
        "entities": [
            {
                "service_name": "API_TEST",
                "entity_set": "A_Test",
                "key_fields": ["Document"],
                "default_select_fields": ["Document", "Amount"],
                "fields": [
                    {"entity_set": "A_Test", "field_name": "Document", "data_type": "Edm.String", "filterable": True},
                    {"entity_set": "A_Test", "field_name": "Amount", "data_type": "Edm.Decimal", "filterable": True},
                    {"entity_set": "A_Test", "field_name": "Period", "data_type": "Edm.String", "filterable": True},
                ],
            }
        ],
        "candidate_fields": [
            {"entity_set": "A_Test", "field_name": "Document", "data_type": "Edm.String", "filterable": True},
            {"entity_set": "A_Test", "field_name": "Amount", "data_type": "Edm.Decimal", "filterable": True},
            {"entity_set": "A_Test", "field_name": "Period", "data_type": "Edm.String", "filterable": True},
        ],
    }


def test_api_specific_planner_shortcuts_po_supplier_contact_cross_api(monkeypatch) -> None:
    import sap_odata_agent.infrastructure.llm.api_specific_planner as planner_module

    real_date = planner_module.date

    class FixedDate:
        @classmethod
        def today(cls):
            return real_date(2026, 5, 13)

    monkeypatch.setattr(planner_module, "date", FixedDate)
    planner = LlmApiSpecificPlanner(llm_client=FailingClient(), enabled=True)
    user_input = "\u67e5\u8be2\u5de5\u53821710\u660e\u5929\u5230\u8d27\u7684\u91c7\u8d2d\u8ba2\u5355\u7684\u4f9b\u5e94\u5546\u8054\u7cfb\u4eba\u4fe1\u606f"
    route = ApiRouteDecision(
        selected_apis=[
            SelectedApi("API_PURCHASEORDER_PROCESS_SRV", 0.8, "purchase orders"),
            SelectedApi("API_BUSINESS_PARTNER", 0.7, "supplier contact"),
        ],
        requires_multi_api=True,
        intent_summary="Purchase orders arriving tomorrow for plant 1710 with supplier contact details.",
        business_domain="Purchasing",
        business_object="Purchase Order",
        raw_response={"requires_multi_api": True},
    )
    schema_context = {
        "service_name": "API_PURCHASEORDER_PROCESS_SRV",
        "service_names": ["API_PURCHASEORDER_PROCESS_SRV", "API_BUSINESS_PARTNER"],
        "multi_api": True,
    }

    plan = planner.plan_for_api(AgentRequest(user_input=user_input), route, schema_context)

    assert plan.plan_kind == "multi_step"
    assert plan.planner_diagnostics["planner_winner"] == "skill_shortcut"
    assert [step.service_name for step in plan.steps] == [
        "API_PURCHASEORDER_PROCESS_SRV",
        "API_PURCHASEORDER_PROCESS_SRV",
        "API_PURCHASEORDER_PROCESS_SRV",
        "API_BUSINESS_PARTNER",
        "API_BUSINESS_PARTNER",
    ]
    assert plan.steps[0].entity_set == "A_PurchaseOrderScheduleLine"
    assert plan.steps[0].filters[0].field == "ScheduleLineDeliveryDate"
    assert plan.steps[0].filters[0].value == "2026-05-14"
    assert plan.steps[1].filters[0].field == "Plant"
    assert plan.steps[1].filters[0].value == "1710"
    assert plan.steps[-1].entity_set == "A_BusinessPartnerAddress"


def _write_company_gl_index(root: Path) -> None:
    company_dir = root / "API_COMPANYCODE_SRV"
    company_dir.mkdir(parents=True)
    (company_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_COMPANYCODE_SRV", "entity_sets": ["A_CompanyCode"]}]),
        encoding="utf-8",
    )
    (company_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_COMPANYCODE_SRV",
                    "entity_set": "A_CompanyCode",
                    "entity_type": "A_CompanyCodeType",
                    "key_fields": ["CompanyCode"],
                    "default_select_fields": ["CompanyCode", "ChartOfAccounts"],
                    "supported_methods": ["GET"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (company_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_COMPANYCODE_SRV",
                    "entity_set": "A_CompanyCode",
                    "field_name": "CompanyCode",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_COMPANYCODE_SRV",
                    "entity_set": "A_CompanyCode",
                    "field_name": "ChartOfAccounts",
                    "data_type": "Edm.String",
                    "filterable": False,
                    "selectable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    gl_dir = root / "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"
    gl_dir.mkdir(parents=True)
    (gl_dir / "services.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                    "entity_sets": ["A_GLAccountInChartOfAccounts"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (gl_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "entity_type": "A_GLAccountInChartOfAccountsType",
                    "key_fields": ["ChartOfAccounts", "GLAccount"],
                    "default_select_fields": ["ChartOfAccounts", "GLAccount"],
                    "supported_methods": ["GET"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (gl_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "field_name": "ChartOfAccounts",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "field_name": "GLAccount",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "field_name": "GLAccountType",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    for service_dir in (company_dir, gl_dir):
        for name in ["relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"]:
            (service_dir / name).write_text("[]", encoding="utf-8")


def _write_profit_center_index(root: Path) -> None:
    service_dir = root / "API_PROFITCENTER_SRV"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_PROFITCENTER_SRV", "entity_sets": ["A_PrftCtrCompanyCodeAssignment", "A_ProfitCenter"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_PROFITCENTER_SRV",
                    "entity_set": "A_PrftCtrCompanyCodeAssignment",
                    "entity_type": "AssignmentType",
                    "key_fields": ["ControllingArea", "ProfitCenter", "CompanyCode"],
                    "default_select_fields": ["ControllingArea", "ProfitCenter", "CompanyCode"],
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "API_PROFITCENTER_SRV",
                    "entity_set": "A_ProfitCenter",
                    "entity_type": "ProfitCenterType",
                    "key_fields": ["ControllingArea", "ProfitCenter"],
                    "default_select_fields": ["ControllingArea", "ProfitCenter"],
                    "supported_methods": ["GET"],
                },
            ]
        ),
        encoding="utf-8",
    )
    fields = []
    for entity_set in ("A_PrftCtrCompanyCodeAssignment", "A_ProfitCenter"):
        for field_name in ("ControllingArea", "ProfitCenter", "CompanyCode", "ProfitCenterStandardHierarchy"):
            fields.append(
                {
                    "service_name": "API_PROFITCENTER_SRV",
                    "entity_set": entity_set,
                    "field_name": field_name,
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                }
            )
    (service_dir / "fields.json").write_text(json.dumps(fields), encoding="utf-8")
    for name in ["relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"]:
        (service_dir / name).write_text("[]", encoding="utf-8")


def test_api_specific_planner_materializes_llm_result_transform(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "select_fields": ["Document"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "summarized list"},
            "result_transform": {
                "type": "aggregate",
                "group_by": ["Document"],
                "sum_fields": ["Amount"],
            },
        }
    )
    planner = LlmApiSpecificPlanner(index_root=str(tmp_path), llm_client=client)

    plan = planner.plan_for_api(
        AgentRequest(user_input="show amount by document"),
        ApiRouteDecision(selected_apis=[SelectedApi("API_TEST", 0.9)]),
        _api_test_schema_context(),
    )

    assert plan.result_transform is not None
    assert plan.result_transform.group_by == ["Document"]
    assert plan.result_transform.sum_fields == ["Amount"]
    assert plan.select_fields == ["Document", "Amount"]
    assert plan.response_summary_fields == ["Document", "Amount"]


def test_api_specific_planner_applies_skill_result_transform_pattern(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "select_fields": ["Document", "Amount", "Period"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "raw list"},
        }
    )
    planner = LlmApiSpecificPlanner(index_root=str(tmp_path), llm_client=client)
    schema_context = {
        **_api_test_schema_context(),
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For requests such as document level amount, answer from `A_Test`. "
                "Select only `A_Test.Document` and `A_Test.Amount`. "
                "Use result_transform aggregate: group_by: `A_Test.Document`; sum_fields: `A_Test.Amount`."
            ),
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show document level amount"),
        ApiRouteDecision(selected_apis=[SelectedApi("API_TEST", 0.9)]),
        schema_context,
    )

    assert plan.result_transform is not None
    assert plan.result_transform.group_by == ["Document"]
    assert plan.result_transform.sum_fields == ["Amount"]
    assert plan.select_fields == ["Document", "Amount"]


def test_api_specific_planner_includes_api_skill_in_prompt(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "IsClosed"],
            "filters": [{"field": "IsClosed", "operator": "eq", "value": False, "value_type": "boolean"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "response_directive": "Show open documents.",
            "rationale": "The API skill says open documents use IsClosed=false.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [{"entity_set": "A_Test", "fields": [{"field_name": "Document"}, {"field_name": "IsClosed"}]}],
        "candidate_fields": [{"entity_set": "A_Test", "field_name": "IsClosed"}],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "Open documents use IsClosed eq false.",
            "content": "## Business Semantics\n- Open documents use `A_Test.IsClosed eq false`.",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="query open documents"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.entity_set == "A_Test"
    assert plan.filters[0].field == "IsClosed"
    assert "api_skill" in client.user_prompt
    assert "Open documents use" in client.user_prompt
    assert "API skills are not schema authority" in client.system_prompt
    assert "less specific similarly named field" in client.user_prompt
    assert "document history requests" in client.user_prompt


def test_api_specific_planner_applies_matching_skill_nonblank_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for records with functional area.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "FunctionalArea", "filterable": True},
                ],
            }
        ],
        "candidate_fields": [{"entity_set": "A_Test", "field_name": "FunctionalArea", "filterable": True}],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "## Common Planning Patterns\n"
                "- For line items with functional area, select only `A_Test.Document` and "
                "`A_Test.FunctionalArea`, and add filter `A_Test.FunctionalArea ne ''`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show line items with functional area"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value) for item in plan.filters] == [("FunctionalArea", "ne", "")]
    assert plan.select_fields == ["Document", "FunctionalArea"]
    assert plan.planner_diagnostics["api_skill_applied_filters"][0]["source"] == "api_skill_nonblank_filter"


def test_api_specific_planner_applies_matching_skill_boolean_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for open documents.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "IsClosed", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For open documents, add filter `A_Test.IsClosed eq false`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show open documents"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("IsClosed", "eq", "false", "boolean")
    ]
    assert plan.planner_diagnostics["api_skill_applied_filters"][0]["source"] == "api_skill_filter"


def test_api_specific_planner_applies_matching_skill_string_status_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for incomplete documents.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "FunctionalArea", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For incomplete documents, add filter `A_Test.FunctionalArea ne 'C'`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show incomplete documents"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("FunctionalArea", "ne", "C", "string")
    ]
    assert plan.planner_diagnostics["api_skill_applied_filters"][0]["source"] == "api_skill_filter"


def test_api_specific_planner_applies_skill_preferred_filter_field(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document"],
            "filters": [{"field": "Period", "operator": "eq", "value": "3773", "value_type": "string"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The LLM chose the wrong similarly named filter.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "Period", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For sales order billing document lookups, use filter field `A_Test.Document` with the document "
                "number from the user; do not use `A_Test.Period` for this business meaning."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="query billing documents for sales order 3773"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value) for item in plan.filters] == [("Document", "eq", "3773")]
    assert plan.planner_diagnostics["api_skill_preferred_filter_fields"][0]["from_field"] == "Period"


def test_api_specific_planner_applies_matching_skill_select_only_without_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "IsClosed", "FunctionalArea"],
            "filters": [{"field": "IsClosed", "operator": "eq", "value": False, "value_type": "boolean"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for a compact document list.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "IsClosed", "filterable": True},
                    {"field_name": "FunctionalArea", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For compact document list requests, select only `A_Test.Document` and "
                "`A_Test.IsClosed`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show compact document list"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "IsClosed"]
    assert plan.response_summary_fields == ["Document", "IsClosed"]
    assert plan.planner_diagnostics["api_skill_applied_select_only"][0]["source"] == "api_skill_select_only"


def test_api_specific_planner_promotes_skill_target_step_when_enrichment_is_forbidden(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "multi_step",
            "service_name": "API_TEST",
            "entity_set": "A_Extra",
            "http_method": "GET",
            "select_fields": ["Document", "Name"],
            "filters": [],
            "steps": [
                {
                    "step_id": "step_1",
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "select_fields": ["Document"],
                    "filters": [{"field": "IsClosed", "operator": "eq", "value": False, "value_type": "boolean"}],
                    "filter_from_previous": [],
                    "top": 50,
                },
                {
                    "step_id": "step_2",
                    "service_name": "API_TEST",
                    "entity_set": "A_Extra",
                    "select_fields": ["Document", "Name"],
                    "filters": [],
                    "filter_from_previous": [
                        {"field": "Document", "source_step_id": "step_1", "source_field": "Document"}
                    ],
                    "top": 50,
                },
            ],
            "presentation": {"kind": "table", "reason": "list result"},
            "response_directive": "Show enrichment names.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "IsClosed", "filterable": True},
                ],
            },
            {
                "entity_set": "A_Extra",
                "fields": [{"field_name": "Document", "filterable": True}, {"field_name": "Name"}],
            },
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For compact document list requests, answer from `A_Test`; select only "
                "`A_Test.Document` and `A_Test.IsClosed`; do not add `A_Extra` enrichment."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show compact document list"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.entity_set == "A_Test"
    assert plan.select_fields == ["Document", "IsClosed"]
    assert [step.entity_set for step in plan.steps] == ["A_Test"]
    assert plan.response_directive == ""
    assert plan.planner_diagnostics["api_skill_promoted_target_step"]["step_id"] == "step_1"


def test_api_specific_planner_removes_unrequested_temporal_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "select_fields": ["Document", "Amount"],
            "response_summary_fields": ["Document", "Amount"],
            "filters": [{"field": "FiscalYear", "operator": "eq", "value": "2026", "value_type": "string"}],
            "top": 50,
            "presentation": {"kind": "table", "reason": "list result"},
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [{"field_name": "Document"}, {"field_name": "Amount"}, {"field_name": "FiscalYear"}],
            }
        ],
        "candidate_fields": [
            {"entity_set": "A_Test", "field_name": "Document"},
            {"entity_set": "A_Test", "field_name": "Amount"},
            {"entity_set": "A_Test", "field_name": "FiscalYear", "filterable": True},
        ],
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show accounting documents"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST")]),
        schema_context,
    )

    assert plan.filters == []
    assert plan.planner_diagnostics["removed_unrequested_temporal_filters"][0]["field"] == "FiscalYear"


def test_api_specific_planner_skill_pattern_can_clear_clarification(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "clarification",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "select_fields": [],
            "response_summary_fields": [],
            "filters": [],
            "needs_clarification": True,
            "clarification_question": "Which functional area?",
            "presentation": {"kind": "text", "reason": "needs scope"},
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [{"field_name": "Document"}, {"field_name": "FunctionalArea"}],
            }
        ],
        "candidate_fields": [{"entity_set": "A_Test", "field_name": "FunctionalArea", "filterable": True}],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For functional area line items, select only `A_Test.Document` and "
                "`A_Test.FunctionalArea`, and add filter `A_Test.FunctionalArea ne ''`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show functional area line items"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.needs_clarification is False
    assert [(item.field, item.operator, item.value) for item in plan.filters] == [("FunctionalArea", "ne", "")]
    assert plan.select_fields == ["Document", "FunctionalArea"]
    assert plan.planner_diagnostics["api_skill_cleared_clarification"] is True


def test_api_specific_planner_prefers_untruncated_skill_line(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "select_fields": ["Document"],
            "response_summary_fields": ["Document"],
            "filters": [],
            "top": 50,
            "presentation": {"kind": "table", "reason": "list result"},
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [{"entity_set": "A_Test", "fields": [{"field_name": "Document"}, {"field_name": "Period"}]}],
        "candidate_fields": [
            {"entity_set": "A_Test", "field_name": "Document"},
            {"entity_set": "A_Test", "field_name": "Period"},
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For period report, select only `A_Test.Document` and `A_Test.Per...`.",
            "content": "For period report, select only `A_Test.Document` and `A_Test.Period`.",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show period report"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "Period"]


def test_api_specific_planner_bridges_profit_center_company_scope(tmp_path: Path) -> None:
    _write_profit_center_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_PROFITCENTER_SRV",
            "entity_set": "A_ProfitCenter",
            "select_fields": ["ControllingArea", "ProfitCenter", "ProfitCenterStandardHierarchy"],
            "response_summary_fields": ["ProfitCenter", "ProfitCenterStandardHierarchy"],
            "filters": [{"field": "CompanyCode", "operator": "eq", "value": "1710", "value_type": "string"}],
            "top": 50,
            "presentation": {"kind": "table", "reason": "list result"},
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_PROFITCENTER_SRV",
        "entities": [
            {"service_name": "API_PROFITCENTER_SRV", "entity_set": "A_PrftCtrCompanyCodeAssignment", "fields": []},
            {"service_name": "API_PROFITCENTER_SRV", "entity_set": "A_ProfitCenter", "fields": []},
        ],
        "candidate_fields": [],
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询公司1710利润中心的标准层级"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_PROFITCENTER_SRV", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.plan_kind == "multi_step"
    assert [step.entity_set for step in plan.steps] == ["A_PrftCtrCompanyCodeAssignment", "A_ProfitCenter"]
    assert plan.steps[1].filter_from_previous[0].field == "ProfitCenter"


def test_api_specific_planner_removes_profit_center_controlling_area_binding() -> None:
    plan = QueryPlan(
        service_name="API_PROFITCENTER_SRV",
        entity_set="A_ProfitCenter",
        plan_kind="multi_step",
        steps=[
            ExecutionStep(
                step_id="step_1",
                service_name="API_PROFITCENTER_SRV",
                entity_set="A_PrftCtrCompanyCodeAssignment",
                select_fields=["ControllingArea", "ProfitCenter", "CompanyCode"],
            ),
            ExecutionStep(
                step_id="step_2",
                service_name="API_PROFITCENTER_SRV",
                entity_set="A_ProfitCenter",
                select_fields=["ControllingArea", "ProfitCenter"],
                filter_from_previous=[
                    StepBinding(field="ProfitCenter", source_step_id="step_1", source_field="ProfitCenter"),
                    StepBinding(field="ControllingArea", source_step_id="step_1", source_field="ControllingArea"),
                ],
            ),
        ],
    )

    normalized = LlmApiSpecificPlanner._normalize_profit_center_assignment_bindings(plan)

    assert [binding.field for binding in normalized.steps[1].filter_from_previous] == ["ProfitCenter"]


def test_api_specific_planner_prefers_more_specific_skill_select_only_pattern(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "Amount"],
            "filters": [{"field": "Period", "operator": "eq", "value": "2016.012", "value_type": "string"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for period-specific records.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "Amount", "filterable": True},
                    {"field_name": "Period", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For Chinese wording such as `日记账行项目`, select only `A_Test.Document` and "
                "`A_Test.Amount`.\n"
                "For Chinese wording such as `会计期间2016.012的日记账行项目`, select only "
                "`A_Test.Document`, `A_Test.Period`, and `A_Test.Amount`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询公司1710会计期间2016.012的日记账行项目"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "Period", "Amount"]
    assert plan.response_summary_fields == ["Document", "Period", "Amount"]


def test_api_specific_planner_prefers_complete_skill_line_on_score_tie(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for functional-area records.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "FunctionalArea", "filterable": True},
                    {"field_name": "Amount", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For wording such as `functional area`, select only "
                "`A_Test.Document`, `A_Test.FunctionalArea`, and `A_Tes..."
            ),
            "content": (
                "For wording such as `functional area`, select only "
                "`A_Test.Document`, `A_Test.FunctionalArea`, and `A_Test.Amount`."
            ),
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show functional area line items"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "FunctionalArea", "Amount"]


def test_api_specific_planner_preserves_empty_string_eq_ne_filters(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "FunctionalArea"],
            "filters": [{"field": "FunctionalArea", "operator": "ne", "value": "", "value_type": "string"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for nonblank functional area records.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)

    plan = planner.plan_for_api(
        AgentRequest(user_input="show documents with functional area"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        {"service_name": "API_TEST"},
    )

    assert [(item.field, item.operator, item.value) for item in plan.filters] == [
        ("FunctionalArea", "ne", "")
    ]


def test_plan_repairer_applies_skill_patterns_to_repaired_plan(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "repair_reason": "Add nonblank functional area filter.",
            "changed_from_previous": [],
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "FunctionalArea"],
            "filters": [{"field": "FunctionalArea", "operator": "ne", "value": "", "value_type": "string"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "Repaired from critic feedback.",
        }
    )
    repairer = LlmPlanRepairer(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "FunctionalArea", "filterable": True},
                    {"field_name": "Amount", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For wording such as `line items with functional area`, select only "
                "`A_Test.Document`, `A_Test.FunctionalArea`, and `A_Test.Amount`, and add "
                "filter `A_Test.FunctionalArea ne ''`."
            ),
            "content": "",
        },
    }

    plan = repairer.repair(
        AgentRequest(user_input="show line items with functional area"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
        previous_plan=QueryPlan(service_name="API_TEST", entity_set="A_Test"),
        attempt_number=2,
        max_attempts=3,
        failure_context={"critic_findings": [{"code": "missing_filter"}]},
    )

    assert plan.select_fields == ["Document", "FunctionalArea", "Amount"]
    assert [(item.field, item.operator, item.value) for item in plan.filters] == [
        ("FunctionalArea", "ne", "")
    ]


def test_api_specific_planner_bridges_company_code_to_chart_of_accounts(tmp_path: Path) -> None:
    _write_company_gl_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
            "entity_set": "A_GLAccountInChartOfAccounts",
            "http_method": "GET",
            "select_fields": ["ChartOfAccounts", "GLAccount", "GLAccountType"],
            "filters": [
                {"field": "ChartOfAccounts", "operator": "eq", "value": "1710", "value_type": "string"}
            ],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for G/L accounts for company 1710.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_COMPANYCODE_SRV",
        "service_names": ["API_COMPANYCODE_SRV", "API_GLACCOUNTINCHARTOFACCOUNTS_SRV"],
        "multi_api": True,
        "entities": [
            {
                "service_name": "API_COMPANYCODE_SRV",
                "entity_set": "A_CompanyCode",
                "fields": [
                    {"field_name": "CompanyCode", "filterable": True},
                    {"field_name": "ChartOfAccounts", "filterable": False},
                ],
            },
            {
                "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                "entity_set": "A_GLAccountInChartOfAccounts",
                "fields": [
                    {"field_name": "ChartOfAccounts", "filterable": True},
                    {"field_name": "GLAccount", "filterable": True},
                    {"field_name": "GLAccountType", "filterable": True},
                ],
            },
        ],
        "api_skills": [
            {
                "service_name": "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
                "summary": "For company-code scoped G/L account lookup, first query A_CompanyCode.ChartOfAccounts.",
            }
        ],
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="query company 1710 chart of accounts G/L accounts"),
        ApiRouteDecision(
            selected_apis=[
                SelectedApi(service_name="API_COMPANYCODE_SRV", confidence=0.7, reason="company bridge"),
                SelectedApi(service_name="API_GLACCOUNTINCHARTOFACCOUNTS_SRV", confidence=0.9, reason="g/l accounts"),
            ],
            requires_multi_api=True,
        ),
        schema_context,
    )

    assert plan.plan_kind == "multi_step"
    assert [step.service_name for step in plan.steps] == [
        "API_COMPANYCODE_SRV",
        "API_GLACCOUNTINCHARTOFACCOUNTS_SRV",
    ]
    assert [(item.field, item.operator, item.value) for item in plan.steps[0].filters] == [
        ("CompanyCode", "eq", "1710")
    ]
    assert plan.steps[1].filter_from_previous[0].field == "ChartOfAccounts"
    assert all(item.field != "ChartOfAccounts" or item.value != "1710" for item in plan.steps[1].filters)
    assert plan.planner_diagnostics["api_skill_company_code_chart_bridge"]["company_code"] == "1710"


def test_api_specific_planner_clarifies_ambiguous_purchase_order_history(tmp_path: Path) -> None:
    client = CapturingClient({})
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)

    plan = planner.plan_for_api(
        AgentRequest(
            user_input="\u67e5\u8be2\u91c7\u8d2d\u8ba2\u53554500001513\u7684\u91c7\u8d2d\u8ba2\u5355\u5386\u53f2\u8bb0\u5f55"
        ),
        ApiRouteDecision(
            selected_apis=[
                SelectedApi(service_name="API_PURCHASEORDER_PROCESS_SRV", confidence=1.0, reason="purchase order")
            ]
        ),
        {"service_name": "API_PURCHASEORDER_PROCESS_SRV"},
    )

    assert plan.needs_clarification is True
    assert plan.plan_kind == "clarification"
    assert "\u91c7\u8d2d\u8ba2\u5355\u5386\u53f2\u8bb0\u5f55" in (plan.clarification_question or "")
    assert "\u6536\u8d27\u5386\u53f2" in plan.clarification_options
    assert client.user_prompt == ""
