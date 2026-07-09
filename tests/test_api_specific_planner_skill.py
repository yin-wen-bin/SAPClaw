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
                    "field_name": "LineItemIsCompleted",
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
                    "field_name": "CompanyCode",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "GLAccount",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "Supplier",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "CompanyCodeCurrency",
                    "data_type": "Edm.String",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "PostingDate",
                    "data_type": "Edm.DateTime",
                    "filterable": True,
                    "selectable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "field_name": "ClearingDate",
                    "data_type": "Edm.DateTime",
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


def test_api_specific_planner_shortcuts_gl_balance_drilldown_cross_api() -> None:
    planner = LlmApiSpecificPlanner(llm_client=FailingClient(), enabled=True)
    user_input = "\u4ece\u516c\u53f81710\u603b\u8d26\u79d1\u76ee10010000\u57282023\u5e74\u7b2c12\u671f\u7684\u4f59\u989d\u4e0b\u94bb\u67e5\u770b\u51ed\u8bc1\u660e\u7ec6"
    route = ApiRouteDecision(
        selected_apis=[
            SelectedApi("C_TRIALBALANCE_CDS", 0.8, "G/L account balance"),
            SelectedApi("API_GLACCOUNTLINEITEM", 0.7, "journal entry line items"),
        ],
        requires_multi_api=True,
        intent_summary="Drill down from G/L account balance to accounting line items.",
        business_domain="Finance",
        business_object="G/L Account Balance",
        raw_response={"requires_multi_api": True},
    )
    schema_context = {
        "service_name": "C_TRIALBALANCE_CDS",
        "service_names": ["C_TRIALBALANCE_CDS", "API_GLACCOUNTLINEITEM"],
        "multi_api": True,
    }

    plan = planner.plan_for_api(AgentRequest(user_input=user_input), route, schema_context)

    assert plan.plan_kind == "multi_step"
    assert plan.planner_diagnostics["planner_winner"] == "skill_shortcut"
    assert plan.planner_diagnostics["shortcut"] == "gl_balance_drilldown_to_line_items"
    assert [step.service_name for step in plan.steps] == ["C_TRIALBALANCE_CDS", "API_GLACCOUNTLINEITEM"]
    assert plan.steps[0].entity_set == (
        "C_TRIALBALANCE("
        "P_FromPostingDate=datetime'2023-12-01T00:00:00',"
        "P_ToPostingDate=datetime'2023-12-31T00:00:00'"
        ")/Results"
    )
    assert plan.steps[1].entity_set == "GLAccountLineItem"
    balance_filters = {filter_condition.field: filter_condition.value for filter_condition in plan.steps[0].filters}
    assert balance_filters == {
        "Ledger": "0L",
        "CompanyCode": "1710",
        "FiscalYear": "2023",
        "FiscalPeriod": "012",
        "GLAccount": "10010000",
    }
    assert [(binding.field, binding.source_step_id, binding.source_field) for binding in plan.steps[1].filter_from_previous] == [
        ("CompanyCode", "balance", "CompanyCode"),
        ("FiscalYear", "balance", "FiscalYear"),
        ("GLAccount", "balance", "GLAccount"),
    ]


def test_api_specific_planner_shortcuts_gl_line_items_by_account_month() -> None:
    planner = LlmApiSpecificPlanner(llm_client=FailingClient(), enabled=True)
    user_input = "\u67e5\u8be2\u516c\u53f81710\u4e0b\u603b\u8d26\u79d1\u76ee10010000\u57282023\u5e7412\u6708\u7684\u6240\u6709\u53d1\u751f\u660e\u7ec6"
    route = ApiRouteDecision(
        selected_apis=[SelectedApi("API_GLACCOUNTLINEITEM", 0.9, "G/L account line items")],
        intent_summary="G/L account line items by company, account, and posting month.",
        business_domain="Finance",
        business_object="G/L Account Line Item",
        raw_response={"selected_apis": [{"service_name": "API_GLACCOUNTLINEITEM"}]},
    )
    schema_context = {
        "service_name": "API_GLACCOUNTLINEITEM",
        "service_names": ["API_GLACCOUNTLINEITEM"],
    }

    plan = planner.plan_for_api(AgentRequest(user_input=user_input), route, schema_context)

    assert plan.plan_kind == "direct"
    assert plan.service_name == "API_GLACCOUNTLINEITEM"
    assert plan.entity_set == "GLAccountLineItem"
    assert plan.planner_diagnostics["shortcut"] == "gl_line_items_by_account_period"
    filters = [(item.field, item.operator, item.value, item.value_type) for item in plan.filters]
    assert filters == [
        ("CompanyCode", "eq", "1710", "string"),
        ("GLAccount", "eq", "10010000", "string"),
        ("PostingDate", "ge", "2023-12-01T00:00:00", "datetime"),
        ("PostingDate", "le", "2023-12-31T23:59:59", "datetime"),
    ]
    assert "AccountingDocument" in plan.select_fields
    assert "AmountInCompanyCodeCurrency" in plan.select_fields
    assert "ID" not in plan.select_fields
    assert "ID" not in plan.response_summary_fields


def test_api_specific_planner_shortcuts_parameterized_trial_balance_year() -> None:
    planner = LlmApiSpecificPlanner(llm_client=FailingClient(), enabled=True)
    route = ApiRouteDecision(
        selected_apis=[SelectedApi("C_TRIALBALANCE_CDS", 0.9, "G/L account balances")],
        intent_summary="Trial balance for all G/L accounts by company and fiscal year.",
        business_domain="Finance",
        business_object="G/L Account Balance",
        raw_response={"selected_apis": [{"service_name": "C_TRIALBALANCE_CDS"}]},
    )
    schema_context = {
        "service_name": "C_TRIALBALANCE_CDS",
        "service_names": ["C_TRIALBALANCE_CDS"],
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="\u67e5\u8be22020\u5e74\u516c\u53f81710\u6240\u6709\u79d1\u76ee\u7684\u4f59\u989d"),
        route,
        schema_context,
    )

    assert plan.plan_kind == "direct"
    assert plan.service_name == "C_TRIALBALANCE_CDS"
    assert plan.entity_set == (
        "C_TRIALBALANCE("
        "P_FromPostingDate=datetime'2020-01-01T00:00:00',"
        "P_ToPostingDate=datetime'2020-12-31T00:00:00'"
        ")/Results"
    )
    assert plan.planner_diagnostics["shortcut"] == "trial_balance_parameterized_results"
    assert plan.planner_diagnostics["metadata_entity_set"] == "C_TRIALBALANCEResults"
    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("Ledger", "eq", "0L", "string"),
        ("CompanyCode", "eq", "1710", "string"),
        ("FiscalYear", "eq", "2020", "string"),
    ]
    assert "ID" not in plan.select_fields
    assert "ID" not in plan.response_summary_fields
    assert "EndingBalanceAmtInCoCodeCrcy" in plan.select_fields
    assert plan.response_summary_fields[:6] == [
        "CompanyCode",
        "FiscalYear",
        "FiscalPeriod",
        "GLAccount",
        "GLAccountHierarchyName",
        "EndingBalanceAmtInCoCodeCrcy",
    ]


def test_api_specific_planner_trial_balance_account_year_prioritizes_balance_field() -> None:
    planner = LlmApiSpecificPlanner(llm_client=FailingClient(), enabled=True)
    route = ApiRouteDecision(
        selected_apis=[SelectedApi("C_TRIALBALANCE_CDS", 0.9, "G/L account balance")],
        intent_summary="G/L account balance by company and fiscal year.",
        business_domain="Finance",
        business_object="G/L Account Balance",
        raw_response={"selected_apis": [{"service_name": "C_TRIALBALANCE_CDS"}]},
    )
    schema_context = {
        "service_name": "C_TRIALBALANCE_CDS",
        "service_names": ["C_TRIALBALANCE_CDS"],
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询科目11002050在公司1710下，2020年的余额"),
        route,
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("Ledger", "eq", "0L", "string"),
        ("CompanyCode", "eq", "1710", "string"),
        ("FiscalYear", "eq", "2020", "string"),
        ("GLAccount", "eq", "11002050", "string"),
    ]
    assert "ID" not in plan.select_fields
    assert "ID" not in plan.response_summary_fields
    assert "EndingBalanceAmtInCoCodeCrcy" in plan.response_summary_fields[:8]


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


def test_api_specific_planner_does_not_apply_example_filter_without_trigger_phrase(tmp_path: Path) -> None:
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
            "rationale": "The user asks for a general list.",
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
            "summary": (
                "For wording such as \"closed documents\", query `A_Test`, "
                "filter `A_Test.IsClosed eq true`, and select only `A_Test.Document`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show document records with their main identifying details"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.filters == []
    assert "api_skill_applied_filters" not in plan.planner_diagnostics


def test_api_specific_planner_does_not_apply_when_user_asks_for_filter_without_trigger_phrase(
    tmp_path: Path,
) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "ClearingDate"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks to display clearing date.",
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
                    {"field_name": "ClearingDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "Use this API when the user asks for `open items`, `not cleared`, or `cleared items`. "
                "Filter open items with `A_Test.ClearingDate eq null`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show records with clearing date"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.filters == []
    assert "api_skill_applied_filters" not in plan.planner_diagnostics


def test_api_specific_planner_does_not_apply_example_select_only_without_trigger_phrase(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "FunctionalArea"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for a general list with functional area.",
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
                    {"field_name": "CompanyCodeCurrency", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For wording such as \"company code currency\", query `A_Test` "
                "and select only `A_Test.Document` and `A_Test.CompanyCodeCurrency`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show document records with functional area"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "FunctionalArea"]
    assert "api_skill_applied_select_only" not in plan.planner_diagnostics


def test_api_specific_planner_can_switch_direct_plan_to_skill_select_only_entity(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Extra",
            "http_method": "GET",
            "select_fields": ["Document", "Name"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The LLM picked a related detail entity.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "service_name": "API_TEST",
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "Amount", "filterable": True},
                ],
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_Extra",
                "fields": [
                    {"field_name": "Document", "filterable": True},
                    {"field_name": "Name", "filterable": True},
                ],
            },
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For wording such as \"main document list\", query `A_Test` and select only "
                "`A_Test.Document` and `A_Test.Amount`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show main document list"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.entity_set == "A_Test"
    assert plan.select_fields == ["Document", "Amount"]
    assert plan.planner_diagnostics["api_skill_applied_select_only"][0]["entity_switched_from"] == "A_Extra"


def test_api_specific_planner_uses_item_fields_for_production_order_target_quantity() -> None:
    from sap_odata_agent.infrastructure.indexing.api_skill_provider import ApiSkillProvider
    from sap_odata_agent.infrastructure.indexing.schema_context_provider import SchemaContextProvider

    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_PRODUCTION_ORDER_2_SRV",
            "entity_set": "A_ProductionOrder_2",
            "http_method": "GET",
            "select_fields": ["ManufacturingOrder", "Material", "ManufacturingOrderType"],
            "filters": [
                {
                    "field": "Material",
                    "operator": "eq",
                    "value": "EWMS4-50",
                    "value_type": "string",
                }
            ],
            "presentation": {"kind": "table", "reason": "production order list"},
            "rationale": "The LLM initially chose the header entity.",
        }
    )
    provider = SchemaContextProvider(index_root="data/index")
    skill = ApiSkillProvider(skill_root="data/api_skills").load("API_PRODUCTION_ORDER_2_SRV")
    assert skill is not None
    schema_context = provider.build(
        "API_PRODUCTION_ORDER_2_SRV",
        "查询物料EWMS4-50的生产订单",
    )
    schema_context = provider.enrich_with_api_skill(schema_context, skill.as_prompt_payload())
    assert {
        field["field_name"]
        for field in schema_context["candidate_fields"]
        if field["entity_set"] == "A_ProductionOrderItem_2"
    }.issuperset({"MfgOrderItemPlannedTotalQty", "ProductionUnit"})
    schema_context = provider.enrich_with_requested_fields(
        schema_context,
        [
            "ManufacturingOrder",
            "Material",
            "ManufacturingOrderType",
            "MfgOrderItemPlannedTotalQty",
            "ProductionUnit",
        ],
    )
    schema_context["api_skill"] = skill.as_prompt_payload()

    planner = LlmApiSpecificPlanner(index_root="data/index", llm_client=client)
    plan = planner.plan_for_api(
        AgentRequest(
            user_input=(
                "查询物料EWMS4-50的生产订单，在输出中请包含，生产订单号，物料号，"
                "生产订单类型，目标数量，单位"
            )
        ),
        ApiRouteDecision(
            selected_apis=[
                SelectedApi(
                    service_name="API_PRODUCTION_ORDER_2_SRV",
                    confidence=1.0,
                    reason="production orders",
                )
            ]
        ),
        schema_context,
    )

    assert plan.entity_set == "A_ProductionOrderItem_2"
    assert plan.select_fields == [
        "ManufacturingOrder",
        "Material",
        "ManufacturingOrderType",
        "MfgOrderItemPlannedTotalQty",
        "ProductionUnit",
    ]
    assert [(item.field, item.operator, item.value) for item in plan.filters] == [
        ("Material", "eq", "EWMS4-50")
    ]
    assert plan.needs_clarification is False
    assert plan.planner_diagnostics["api_skill_applied_select_only"][0]["entity_switched_from"] == (
        "A_ProductionOrder_2"
    )
    assert "MfgOrderItemPlannedTotalQty" in client.user_prompt
    assert "ProductionUnit" in client.user_prompt


def test_api_specific_planner_applies_matching_skill_null_filter(tmp_path: Path) -> None:
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
            "rationale": "The user asks for open items.",
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
                    {"field_name": "ClearingDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For open items or not cleared wording, add filter `A_Test.ClearingDate eq null`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show not cleared open items"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("ClearingDate", "eq", "null", "null")
    ]
    assert plan.planner_diagnostics["api_skill_applied_filters"][0]["source"] == "api_skill_filter"


def test_api_specific_planner_corrects_existing_skill_null_filter_value_type(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "ClearingDate"],
            "filters": [{"field": "ClearingDate", "operator": "eq", "value": "null", "value_type": "null_keyword"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The LLM used a nonstandard null value type.",
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
                    {"field_name": "ClearingDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For open items or not cleared wording, add filter `A_Test.ClearingDate eq null`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show not cleared open items"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("ClearingDate", "eq", "null", "null")
    ]


def test_api_specific_planner_ignores_numeric_only_skill_match_and_removes_null_conflict(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "ClearingDate"],
            "filters": [
                {"field": "FiscalYear", "operator": "eq", "value": "2024", "value_type": "string"},
                {"field": "ClearingDate", "operator": "eq", "value": "null", "value_type": "null"},
            ],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The LLM incorrectly mixed open-item and cleared-item semantics.",
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
                    {"field_name": "FiscalYear", "filterable": True},
                    {"field_name": "ClearingDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For Chinese open item wording such as `未清项目`, `还没有清账`, or `尚未清账`, "
                "filter `A_Test.ClearingDate eq null`. If the user provides a key date such as "
                "`截至2024年12月31日`, also filter `A_Test.PostingDate le <user_date>`.\n"
                "For cleared item wording such as `已清项目` or `已经清账`, "
                "filter `A_Test.ClearingDate ne null`. If the user provides a clearing year such as `2024年`, "
                "filter `A_Test.ClearingDate ge <user_year_start>` and "
                "`A_Test.ClearingDate le <user_year_end>`.\n"
                "For cleared item wording such as `已清项目` or `已经清账`, do not filter `A_Test.FiscalYear` "
                "unless the user explicitly asks for accounting year."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询公司1710下总账科目21100000在2024年已经清账的项目和清账日期"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("ClearingDate", "ne", "null", "null"),
        ("ClearingDate", "ge", "2024-01-01T00:00:00", "datetime"),
        ("ClearingDate", "le", "2024-12-31T23:59:59", "datetime"),
    ]


def test_api_specific_planner_applies_matching_skill_user_date_filter(tmp_path: Path) -> None:
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
            "rationale": "The user asks for open items by key date.",
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
                    {"field_name": "ClearingDate", "filterable": True},
                    {"field_name": "PostingDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For Chinese open item wording such as `未清项目`, `还没有清账`, or `尚未清账`, "
                "filter `A_Test.ClearingDate eq null`. If the user provides a key date such as "
                "`截至2024年12月31日`, also filter `A_Test.PostingDate le <user_date>`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询公司1710下总账科目21100000截至2024年12月31日还没有清账的项目"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("ClearingDate", "eq", "null", "null"),
        ("PostingDate", "le", "2024-12-31T23:59:59", "datetime"),
    ]
    assert [item["field"] for item in plan.planner_diagnostics["api_skill_applied_filters"]] == [
        "ClearingDate",
        "PostingDate",
    ]


def test_api_specific_planner_applies_open_item_balance_key_date_transform(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sap_odata_agent.infrastructure.llm.api_specific_planner as planner_module

    real_date = planner_module.date

    class FixedDate:
        @classmethod
        def today(cls):
            return real_date(2026, 5, 14)

    monkeypatch.setattr(planner_module, "date", FixedDate)
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["CompanyCode", "GLAccount", "Amount"],
            "filters": [
                {"field": "CompanyCode", "operator": "eq", "value": "1710", "value_type": "string"},
                {"field": "GLAccount", "operator": "eq", "value": "13100000", "value_type": "string"},
            ],
            "presentation": {"kind": "table", "reason": "open item balance"},
            "rationale": "The user asks for an open item balance by key date.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "CompanyCode", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "GLAccount", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "CompanyCodeCurrency", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "Amount", "data_type": "Edm.Decimal", "filterable": True},
                    {"field_name": "PostingDate", "data_type": "Edm.DateTime", "filterable": True},
                    {"field_name": "ClearingDate", "data_type": "Edm.DateTime", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For Chinese open-item balance wording such as `科目...余额` with `未清项目日期`, "
                "`未清项目余额`, or `open item balance`, select only `A_Test.CompanyCode`, "
                "`A_Test.GLAccount`, `A_Test.CompanyCodeCurrency`, `A_Test.PostingDate`, "
                "`A_Test.ClearingDate`, and `A_Test.Amount`; filter `A_Test.ClearingDate eq null` "
                "and `A_Test.PostingDate le <user_date>` when the user provides a key date such as "
                "`今天`, `today`, or `截至2024年12月31日`; result_transform: aggregate; "
                "group_by: `A_Test.CompanyCode`, `A_Test.GLAccount`, `A_Test.CompanyCodeCurrency`; "
                "sum_fields: `A_Test.Amount`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询科目13100000的余额，公司代码为1710，未清项目日期为今天"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("CompanyCode", "eq", "1710", "string"),
        ("GLAccount", "eq", "13100000", "string"),
        ("ClearingDate", "eq", "null", "null"),
        ("PostingDate", "le", "2026-05-14T23:59:59", "datetime"),
    ]
    assert plan.result_transform is not None
    assert plan.result_transform.group_by == ["CompanyCode", "GLAccount", "CompanyCodeCurrency"]
    assert plan.result_transform.sum_fields == ["Amount"]
    assert plan.response_summary_fields == ["CompanyCode", "GLAccount", "CompanyCodeCurrency", "Amount"]


def test_api_specific_planner_applies_supplier_payable_total_as_of_now_transform(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import sap_odata_agent.infrastructure.llm.api_specific_planner as planner_module

    real_date = planner_module.date

    class FixedDate:
        @classmethod
        def today(cls):
            return real_date(2026, 6, 8)

    monkeypatch.setattr(planner_module, "date", FixedDate)
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["CompanyCode", "Supplier", "Amount"],
            "filters": [
                {"field": "CompanyCode", "operator": "eq", "value": "1710", "value_type": "string"},
                {"field": "Supplier", "operator": "eq", "value": "17300003", "value_type": "string"},
            ],
            "presentation": {"kind": "table", "reason": "supplier payable total"},
            "rationale": "The user asks for a supplier payable total.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "CompanyCode", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "Supplier", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "CompanyCodeCurrency", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "Amount", "data_type": "Edm.Decimal", "filterable": True},
                    {"field_name": "PostingDate", "data_type": "Edm.DateTime", "filterable": True},
                    {"field_name": "ClearingDate", "data_type": "Edm.DateTime", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For supplier AP balance wording such as `供应商...应付款总额`, "
                "`供应商应付账款余额`, `供应商未清应付款余额`, `供应商应付余额`, "
                "`vendor payable balance`, or `supplier payable total`, select only "
                "`A_Test.CompanyCode`, `A_Test.Supplier`, `A_Test.CompanyCodeCurrency`, "
                "`A_Test.PostingDate`, `A_Test.ClearingDate`, and `A_Test.Amount`; "
                "filter `A_Test.CompanyCode` and `A_Test.Supplier` when provided, "
                "filter `A_Test.ClearingDate eq null`, and filter `A_Test.PostingDate le <user_date>` "
                "when the user provides a key date such as `今天`, `截止目前`, `截至目前`, "
                "`today`, `as of now`, or `截至2024年12月31日`; result_transform: aggregate; "
                "group_by: `A_Test.CompanyCode`, `A_Test.Supplier`, `A_Test.CompanyCodeCurrency`; "
                "sum_fields: `A_Test.Amount`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询供应商17300003在公司代码1710下，截止目前的应付款总额。"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("CompanyCode", "eq", "1710", "string"),
        ("Supplier", "eq", "17300003", "string"),
        ("ClearingDate", "eq", "null", "null"),
        ("PostingDate", "le", "2026-06-08T23:59:59", "datetime"),
    ]
    assert plan.result_transform is not None
    assert plan.result_transform.group_by == ["CompanyCode", "Supplier", "CompanyCodeCurrency"]
    assert plan.result_transform.sum_fields == ["Amount"]
    assert plan.response_summary_fields == ["CompanyCode", "Supplier", "CompanyCodeCurrency", "Amount"]
    assert plan.top is None


def test_api_specific_planner_does_not_apply_cost_center_pattern_to_balance_drilldown(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "CompanyCode", "GLAccount", "Amount"],
            "filters": [
                {"field": "CompanyCode", "operator": "eq", "value": "1710", "value_type": "string"},
                {"field": "GLAccount", "operator": "eq", "value": "10010000", "value_type": "string"},
            ],
            "presentation": {"kind": "table", "reason": "balance drilldown"},
            "rationale": "The user asks to drill down from balance to accounting document details.",
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [
                    {"field_name": "Document", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "CompanyCode", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "GLAccount", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "CostCenter", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "ProfitCenter", "data_type": "Edm.String", "filterable": True},
                    {"field_name": "Amount", "data_type": "Edm.Decimal", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For Chinese wording such as `总账科目...按成本中心和利润中心归集的费用明细`, "
                "select only `A_Test.Document`, `A_Test.CompanyCode`, `A_Test.GLAccount`, "
                "`A_Test.CostCenter`, `A_Test.ProfitCenter`, and `A_Test.Amount`; "
                "filter `A_Test.CostCenter ne ''`; result_transform: aggregate; "
                "group_by: `A_Test.CostCenter`, `A_Test.ProfitCenter`; sum_fields: `A_Test.Amount`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="从公司1710总账科目10010000在2023年第12期的余额下钻查看凭证明细"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value) for item in plan.filters] == [
        ("CompanyCode", "eq", "1710"),
        ("GLAccount", "eq", "10010000"),
    ]
    assert plan.result_transform is None
    assert "CostCenter" not in plan.select_fields


def test_api_specific_planner_applies_matching_skill_year_and_amount_filters(tmp_path: Path) -> None:
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
            "rationale": "The user asks for large manual accounting items.",
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
                    {"field_name": "AccountingDocumentType", "filterable": True},
                    {"field_name": "FiscalYear", "filterable": True},
                    {"field_name": "Amount", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For wording such as `手工凭证产生且金额超过10000的大额总账项目`, "
                "filter `A_Test.AccountingDocumentType eq 'SA'`, `A_Test.FiscalYear eq <user_year>`, "
                "and `A_Test.Amount ge <user_amount>`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询公司1710在2024年由手工凭证产生且金额超过10000的大额总账项目"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("AccountingDocumentType", "eq", "SA", "string"),
        ("FiscalYear", "eq", "2024", "string"),
        ("Amount", "ge", "10000", "decimal"),
    ]


def test_api_specific_planner_applies_matching_skill_period_filter(tmp_path: Path) -> None:
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
            "rationale": "The user asks for period balance.",
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
                    {"field_name": "Ledger", "filterable": True},
                    {"field_name": "FiscalYear", "filterable": True},
                    {"field_name": "FiscalPeriod", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For Chinese wording such as `总账科目...在2023年第12期的期初、借方、贷方和期末余额`, "
                "filter `A_Test.Ledger eq '0L'`, `A_Test.FiscalYear eq <user_year>`, "
                "and `A_Test.FiscalPeriod eq <user_period>`."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询公司1710下总账科目10010000在2023年第12期的期初、借方、贷方和期末余额"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("Ledger", "eq", "0L", "string"),
        ("FiscalYear", "eq", "2023", "string"),
        ("FiscalPeriod", "eq", "012", "string"),
    ]


def test_api_specific_planner_replaces_duplicate_skill_filter_operator(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "PostingDate"],
            "filters": [{"field": "PostingDate", "operator": "le", "value": "2024-12-31", "value_type": "date"}],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The LLM used a start-of-day date filter.",
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
                    {"field_name": "PostingDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For key date wording such as `截至2024年12月31日`, filter `A_Test.PostingDate le <user_date>`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询截至2024年12月31日的项目"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert [(item.field, item.operator, item.value, item.value_type) for item in plan.filters] == [
        ("PostingDate", "le", "2024-12-31T23:59:59", "datetime")
    ]


def test_api_specific_planner_removes_matching_skill_discouraged_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "LineItemIsCompleted"],
            "filters": [
                {"field": "LineItemIsCompleted", "operator": "eq", "value": "false", "value_type": "boolean"}
            ],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The LLM chose a less stable completion flag for open items.",
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
                    {"field_name": "LineItemIsCompleted", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For open items or not cleared wording, do not filter `A_Test.LineItemIsCompleted` "
                "unless the user explicitly asks for line item completion status."
            ),
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show not cleared open items"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.filters == []
    assert plan.planner_diagnostics["api_skill_removed_filters"][0]["field"] == "LineItemIsCompleted"


def test_api_specific_planner_applies_matching_skill_order_by(tmp_path: Path) -> None:
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
            "summary": "For open documents, add filter `A_Test.IsClosed eq false`; order_by: `A_Test.Document`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show open documents"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.order_by == ["Document"]
    assert plan.planner_diagnostics["api_skill_applied_order_by"][0]["fields"] == ["Document"]


def test_api_specific_planner_does_not_apply_unmatched_skill_order_by(tmp_path: Path) -> None:
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
            "rationale": "The user asks for a general document list.",
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
                    {"field_name": "PostingDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For open documents, add filter `A_Test.IsClosed eq false`; order_by: `A_Test.Document`, `A_Test.PostingDate`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show document records"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.order_by == []
    assert "api_skill_applied_order_by" not in plan.planner_diagnostics


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


def test_api_specific_planner_does_not_apply_unmatched_for_prefix_select_only(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "PostingDate"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list result"},
            "rationale": "The user asks for a general document list.",
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
                    {"field_name": "PostingDate", "filterable": True},
                    {"field_name": "DueDate", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": "For supplier payable due-date list outputs, select only `A_Test.Document` and `A_Test.DueDate`.",
            "content": "",
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show document list with posting date"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST", confidence=1.0, reason="test")]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "PostingDate"]
    assert "api_skill_applied_select_only" not in plan.planner_diagnostics


def test_api_specific_planner_removes_skill_discouraged_output_fields(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "Amount", "IsClosed"],
            "response_summary_fields": ["Document", "Amount", "IsClosed"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "profile"},
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
                    {"field_name": "IsClosed", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For basic information requests, do not make `A_Test.IsClosed` the main output fields "
                "unless the user asks for status/control information."
            ),
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show document basic information"),
        ApiRouteDecision(selected_apis=[SelectedApi("API_TEST", 1.0)]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "Amount"]
    assert plan.response_summary_fields == ["Document", "Amount"]
    assert plan.planner_diagnostics["api_skill_removed_select_fields"] == [
        {"entity_set": "A_Test", "field": "IsClosed"}
    ]


def test_api_specific_planner_keeps_discouraged_output_when_user_requests_status(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "IsClosed"],
            "response_summary_fields": ["Document", "IsClosed"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "status"},
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
            "summary": (
                "For basic information requests, do not make `A_Test.IsClosed` the main output fields "
                "unless the user asks for status/control information."
            ),
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show document status"),
        ApiRouteDecision(selected_apis=[SelectedApi("API_TEST", 1.0)]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "IsClosed"]
    assert plan.response_summary_fields == ["Document", "IsClosed"]


def test_api_specific_planner_applies_global_skill_discouraged_output_fields(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "http_method": "GET",
            "select_fields": ["Document", "Amount", "IsClosed"],
            "response_summary_fields": ["Document", "Amount", "IsClosed"],
            "filters": [],
            "presentation": {"kind": "table", "reason": "list"},
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
                    {"field_name": "IsClosed", "filterable": True},
                ],
            }
        ],
        "api_skill": {
            "service_name": "API_TEST",
            "summary": (
                "For all `A_Test` record/list outputs, do not return `A_Test.IsClosed` as an answer "
                "or main output field because it is a technical key."
            ),
        },
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="show customer open items"),
        ApiRouteDecision(selected_apis=[SelectedApi("API_TEST", 1.0)]),
        schema_context,
    )

    assert plan.select_fields == ["Document", "Amount"]
    assert plan.response_summary_fields == ["Document", "Amount"]
    assert plan.planner_diagnostics["api_skill_removed_select_fields"] == [
        {"entity_set": "A_Test", "field": "IsClosed"}
    ]


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


def test_api_specific_planner_keeps_week_temporal_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "direct",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "select_fields": ["Document", "PostingDate"],
            "response_summary_fields": ["Document", "PostingDate"],
            "filters": [
                {"field": "PostingDate", "operator": "ge", "value": "2026-05-25T00:00:00", "value_type": "datetime"},
                {"field": "PostingDate", "operator": "le", "value": "2026-05-31T23:59:59", "value_type": "datetime"},
            ],
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
                "fields": [{"field_name": "Document"}, {"field_name": "PostingDate"}],
            }
        ],
        "candidate_fields": [
            {"entity_set": "A_Test", "field_name": "Document"},
            {"entity_set": "A_Test", "field_name": "PostingDate", "filterable": True},
        ],
    }

    plan = planner.plan_for_api(
        AgentRequest(user_input="查询本周到货的采购订单"),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST")]),
        schema_context,
    )

    assert [(condition.field, condition.operator) for condition in plan.filters] == [
        ("PostingDate", "ge"),
        ("PostingDate", "le"),
    ]
    assert "removed_unrequested_temporal_filters" not in plan.planner_diagnostics


def test_api_specific_planner_recognizes_common_week_temporal_phrases() -> None:
    phrases = [
        "查询这周到货的采购订单",
        "查询本星期到货的采购订单",
        "查询下周到货的采购订单",
        "查询上周到货的采购订单",
        "show purchase orders arriving this week",
        "show purchase orders arriving next week",
        "show purchase orders from last week",
    ]

    for phrase in phrases:
        assert LlmApiSpecificPlanner._has_temporal_intent(phrase), phrase


def test_api_specific_planner_recognizes_real_chinese_temporal_phrases() -> None:
    phrases = [
        "查询本周到货的采购订单",
        "查询上周到货的采购订单",
        "查询下周到货的采购订单",
        "查询下月到货的采购订单",
        "查询明天到货的采购订单",
    ]

    for phrase in phrases:
        assert LlmApiSpecificPlanner._has_temporal_intent(phrase), phrase


def test_api_specific_planner_preserves_detected_temporal_filters(tmp_path: Path) -> None:
    _write_index(tmp_path)
    client = CapturingClient(
        {
            "plan_kind": "multi_step",
            "service_name": "API_TEST",
            "entity_set": "A_Test",
            "steps": [
                {
                    "step_id": "step_1",
                    "service_name": "API_TEST",
                    "entity_set": "A_Test",
                    "select_fields": ["Document", "PostingDate"],
                    "filters": [
                        {
                            "field": "PostingDate",
                            "operator": "ge",
                            "value": "2026-05-25T00:00:00",
                            "value_type": "datetime",
                        },
                        {
                            "field": "PostingDate",
                            "operator": "le",
                            "value": "2026-05-31T23:59:59",
                            "value_type": "datetime",
                        },
                    ],
                    "filter_from_previous": [],
                    "top": 50,
                }
            ],
            "target_entity_set": "A_Test",
            "presentation": {"kind": "table", "reason": "list result"},
        }
    )
    planner = LlmApiSpecificPlanner(index_root=tmp_path, llm_client=client)
    schema_context = {
        "service_name": "API_TEST",
        "entities": [
            {
                "entity_set": "A_Test",
                "fields": [{"field_name": "Document"}, {"field_name": "PostingDate"}],
            }
        ],
        "candidate_fields": [
            {"entity_set": "A_Test", "field_name": "Document"},
            {"entity_set": "A_Test", "field_name": "PostingDate", "filterable": True},
        ],
    }

    plan = planner.plan_for_api(
        AgentRequest(
            user_input="查询上周到货的采购订单",
            detected_time_expressions=[
                {
                    "text": "上周",
                    "normalized_type": "calendar_week",
                    "range_start": "2026-05-25T00:00:00",
                    "range_end": "2026-05-31T23:59:59",
                    "granularity": "week",
                }
            ],
        ),
        ApiRouteDecision(selected_apis=[SelectedApi(service_name="API_TEST")]),
        schema_context,
    )

    assert [(condition.field, condition.operator) for condition in plan.steps[0].filters] == [
        ("PostingDate", "ge"),
        ("PostingDate", "le"),
    ]
    assert "removed_unrequested_temporal_filters" not in plan.planner_diagnostics


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
            "filters": [
                {"field": "FunctionalArea", "operator": "ne", "value": "", "value_type": "string"},
                {"field": "LineItemIsCompleted", "operator": "eq", "value": "false", "value_type": "boolean"},
            ],
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
                "filter `A_Test.FunctionalArea ne ''`; order_by: `A_Test.Document`.\n"
                "For wording such as `line items with functional area`, do not filter "
                "`A_Test.LineItemIsCompleted` unless the user explicitly asks for completion status."
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
    assert plan.order_by == ["Document"]
    assert plan.planner_diagnostics["api_skill_removed_filters"][0]["field"] == "LineItemIsCompleted"


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
