import json
from pathlib import Path

from sap_odata_agent.application.schema_feasibility_validator import SchemaFeasibilityValidator
from sap_odata_agent.domain.models import (
    AgentRequest,
    ExecutionStep,
    FilterCondition,
    FunctionParameter,
    QueryConstraints,
    QueryPlan,
    QueryShape,
    StepBinding,
)
from sap_odata_agent.infrastructure.llm.planner import IndexAwareRepairEngine


def _write_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST", "entity_sets": ["A_BusinessPartner", "A_BPContactToAddress"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "Customer", "BusinessPartnerFullName"],
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BPContactToAddress",
                    "key_fields": ["RelationshipNumber", "BusinessPartnerCompany", "BusinessPartnerPerson"],
                    "default_select_fields": ["BusinessPartnerCompany", "BusinessPartnerPerson", "RelationshipNumber"],
                    "supported_methods": ["GET"],
                },
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartner",
                    "filterable": True,
                    "label": "业务伙伴",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "Customer",
                    "filterable": True,
                    "label": "客户",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartnerFullName",
                    "filterable": False,
                    "label": "名称",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BPContactToAddress",
                    "field_name": "BusinessPartnerCompany",
                    "filterable": True,
                    "label": "业务伙伴公司",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BPContactToAddress",
                    "field_name": "BusinessPartnerPerson",
                    "filterable": True,
                    "label": "业务伙伴个人",
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BPContactToAddress",
                    "field_name": "RelationshipNumber",
                    "filterable": True,
                    "label": "关系编号",
                },
            ]
        ),
        encoding="utf-8",
    )
    for name in ("relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
        (service_dir / name).write_text("[]", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def _request() -> AgentRequest:
    return AgentRequest(
        user_input="查询客户300001的业务伙伴",
        constraints=QueryConstraints(
            query_shape=QueryShape.SINGLE_FACT,
            target_object="customer",
            target_field_concepts=["BusinessPartner"],
            filter_concepts=["Customer"],
            filter_values=["300001"],
        ),
    )


def _write_function_index(root: Path) -> None:
    service_dir = root / "API_FUNC"
    raw_dir = service_dir / "raw"
    raw_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_FUNC", "entity_sets": []}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_FUNC",
                    "entity_set": "DetermineAvailabilityAt",
                    "description": "Invoke function DetermineAvailabilityAt",
                    "supported_methods": ["GET"],
                }
            ]
        ),
        encoding="utf-8",
    )
    for name in ("fields.json", "relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
        (service_dir / name).write_text("[]", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")
    (raw_dir / "API_FUNC.metadata.xml").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx Version="1.0" xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
  <edmx:DataServices>
    <Schema Namespace="API_FUNC" xmlns="http://schemas.microsoft.com/ado/2008/09/edm">
      <ComplexType Name="AvailabilityRecord">
        <Property Name="AvailableQuantityInBaseUnit" Type="Edm.Decimal" />
        <Property Name="BaseUnit" Type="Edm.String" />
      </ComplexType>
      <EntityContainer Name="API_FUNC_Entities">
        <FunctionImport Name="DetermineAvailabilityAt" ReturnType="API_FUNC.AvailabilityRecord" m:HttpMethod="GET">
          <Parameter Name="Material" Type="Edm.String" Mode="In" MaxLength="40" />
          <Parameter Name="SupplyingPlant" Type="Edm.String" Mode="In" MaxLength="4" />
          <Parameter Name="ATPCheckingRule" Type="Edm.String" Mode="In" MaxLength="2" />
          <Parameter Name="RequestedUTCDateTime" Type="Edm.DateTimeOffset" Mode="In" Precision="7" />
        </FunctionImport>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>""",
        encoding="utf-8",
    )


def _write_trial_balance_index(root: Path) -> None:
    service_dir = root / "C_TRIALBALANCE_CDS"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "C_TRIALBALANCE_CDS", "entity_sets": ["C_TRIALBALANCE", "C_TRIALBALANCEResults"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "C_TRIALBALANCE_CDS",
                    "entity_set": "C_TRIALBALANCE",
                    "entity_type": "C_TRIALBALANCEParameters",
                    "key_fields": ["P_FromPostingDate", "P_ToPostingDate"],
                    "navigation_properties": ["Results"],
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "C_TRIALBALANCE_CDS",
                    "entity_set": "C_TRIALBALANCEResults",
                    "entity_type": "C_TRIALBALANCEResult",
                    "key_fields": ["ID"],
                    "supported_methods": ["GET"],
                },
            ]
        ),
        encoding="utf-8",
    )
    fields = []
    for field_name in [
        "Ledger",
        "CompanyCode",
        "FiscalYear",
        "FiscalPeriod",
        "GLAccount",
        "EndingBalanceAmtInCoCodeCrcy",
    ]:
        fields.append(
            {
                "service_name": "C_TRIALBALANCE_CDS",
                "entity_set": "C_TRIALBALANCEResults",
                "field_name": field_name,
                "data_type": "Edm.Decimal" if field_name.endswith("Crcy") else "Edm.String",
                "filterable": not field_name.endswith("Crcy"),
                "selectable": True,
            }
        )
    (service_dir / "fields.json").write_text(json.dumps(fields), encoding="utf-8")
    for name in ("relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
        (service_dir / name).write_text("[]", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def _write_cross_service_index(root: Path) -> None:
    company_dir = root / "API_COMPANY"
    gl_dir = root / "API_GL"
    company_dir.mkdir(parents=True)
    gl_dir.mkdir(parents=True)
    (company_dir / "services.json").write_text(json.dumps([{"service_name": "API_COMPANY"}]), encoding="utf-8")
    (company_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_COMPANY",
                    "entity_set": "A_CompanyCode",
                    "key_fields": ["CompanyCode"],
                    "default_select_fields": ["CompanyCode", "ChartOfAccounts"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (company_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_COMPANY",
                    "entity_set": "A_CompanyCode",
                    "field_name": "CompanyCode",
                    "filterable": True,
                },
                {
                    "service_name": "API_COMPANY",
                    "entity_set": "A_CompanyCode",
                    "field_name": "ChartOfAccounts",
                    "filterable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    (gl_dir / "services.json").write_text(json.dumps([{"service_name": "API_GL"}]), encoding="utf-8")
    (gl_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_GL",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "key_fields": ["ChartOfAccounts", "GLAccount"],
                    "default_select_fields": ["ChartOfAccounts", "GLAccount", "IsBalanceSheetAccount"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (gl_dir / "fields.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_GL",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "field_name": "ChartOfAccounts",
                    "filterable": True,
                },
                {
                    "service_name": "API_GL",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "field_name": "GLAccount",
                    "filterable": True,
                },
                {
                    "service_name": "API_GL",
                    "entity_set": "A_GLAccountInChartOfAccounts",
                    "field_name": "IsBalanceSheetAccount",
                    "filterable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    for service_dir in (company_dir, gl_dir):
        for name in ("relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
            (service_dir / name).write_text("[]", encoding="utf-8")
        (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
        (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def test_schema_feasibility_rejects_entity_without_required_filter_and_answer(tmp_path: Path) -> None:
    _write_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_TEST")
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BPContactToAddress",
        select_fields=["BusinessPartnerCompany", "BusinessPartnerPerson"],
        filters=[],
    )

    result = validator.validate(_request(), plan)

    assert result.passed is False
    assert {violation.code for violation in result.violations} == {
        "missing_required_answer_field",
        "missing_required_filter_field",
        "filter_value_dropped",
    }


def test_schema_feasibility_reports_planner_failure_for_unknown_placeholder(tmp_path: Path) -> None:
    _write_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_TEST")
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="UNKNOWN_ENTITY",
        planner_diagnostics={
            "llm_dynamic_path_planner": {
                "accepted": False,
                "reason": "llm_error:The read operation timed out",
            }
        },
    )

    result = validator.validate(AgentRequest(user_input="query"), plan)
    codes = {violation.code for violation in result.violations}

    assert result.passed is False
    assert "planner_llm_timeout" in codes
    assert "entity_not_found" not in codes
    findings = validator.to_critic_findings(result)
    assert findings[0].code == "planner_llm_timeout"
    assert findings[0].message == "Planner LLM timed out before producing an executable query plan. No SAP request was executed."


def test_schema_feasibility_localizes_planner_failure_for_chinese_request(tmp_path: Path) -> None:
    _write_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_TEST")
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="UNKNOWN_ENTITY",
        planner_diagnostics={
            "llm_dynamic_path_planner": {
                "accepted": False,
                "reason": "repair_llm_error:HTTP Error 429: Too Many Requests",
            }
        },
    )

    result = validator.validate(
        AgentRequest(user_input="\u67e5\u8be2\u5de5\u53821710\u4e0b\uff0c\u6240\u6709\u672a\u786e\u8ba4\u7684\u751f\u4ea7\u8ba2\u5355"),
        plan,
    )

    assert result.passed is False
    assert result.violations[0].code == "planner_failed"
    assert result.violations[0].message.startswith("Planner \u672a\u80fd\u751f\u6210\u53ef\u6267\u884c")


def test_schema_feasibility_accepts_direct_entity_covering_answer_and_filter(tmp_path: Path) -> None:
    _write_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_TEST")
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BusinessPartner",
        select_fields=["BusinessPartner", "Customer"],
        filters=[FilterCondition(field="Customer", operator="eq", value="300001")],
    )

    result = validator.validate(_request(), plan)

    assert result.passed is True
    assert result.coverage["answer_fields"] == ["BusinessPartner"]
    assert result.coverage["filter_fields"] == ["Customer"]


def test_schema_feasibility_validates_function_import_parameters(tmp_path: Path) -> None:
    _write_function_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_FUNC")
    plan = QueryPlan(
        service_name="API_FUNC",
        entity_set="DetermineAvailabilityAt",
        plan_kind="function_import",
        function_parameters=[
            FunctionParameter(name="Material", value="TG0011", value_type="string"),
            FunctionParameter(name="SupplyingPlant", value="1710", value_type="string"),
            FunctionParameter(name="RequestedUTCDateTime", value="2026-04-29", value_type="datetimeoffset"),
        ],
    )

    result = validator.validate(AgentRequest(user_input="query availability"), plan)

    assert result.passed is False
    assert "missing_function_import_parameter" in {violation.code for violation in result.violations}
    assert any(violation.field == "ATPCheckingRule" for violation in result.violations)


def test_schema_feasibility_accepts_complete_function_import_plan(tmp_path: Path) -> None:
    _write_function_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_FUNC")
    plan = QueryPlan(
        service_name="API_FUNC",
        entity_set="DetermineAvailabilityAt",
        plan_kind="function_import",
        function_parameters=[
            FunctionParameter(name="Material", value="TG0011", value_type="string"),
            FunctionParameter(name="SupplyingPlant", value="1710", value_type="string"),
            FunctionParameter(name="ATPCheckingRule", value="A", value_type="string"),
            FunctionParameter(name="RequestedUTCDateTime", value="2026-04-29", value_type="datetimeoffset"),
        ],
    )

    result = validator.validate(AgentRequest(user_input="query availability"), plan)

    assert result.passed is True
    assert result.coverage["filter_fields"] == []


def test_schema_feasibility_accepts_parameterized_trial_balance_results_path(tmp_path: Path) -> None:
    _write_trial_balance_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="C_TRIALBALANCE_CDS")
    plan = QueryPlan(
        service_name="C_TRIALBALANCE_CDS",
        entity_set=(
            "C_TRIALBALANCE("
            "P_FromPostingDate=datetime'2020-01-01T00:00:00',"
            "P_ToPostingDate=datetime'2020-12-31T00:00:00'"
            ")/Results"
        ),
        select_fields=["Ledger", "CompanyCode", "FiscalYear", "GLAccount", "EndingBalanceAmtInCoCodeCrcy"],
        filters=[
            FilterCondition(field="Ledger", operator="eq", value="0L"),
            FilterCondition(field="CompanyCode", operator="eq", value="1710"),
            FilterCondition(field="FiscalYear", operator="eq", value="2020"),
        ],
        top=50,
    )

    result = validator.validate(AgentRequest(user_input="query 2020 company 1710 account balances"), plan)

    assert result.passed is True
    assert any(item.startswith("entity_path_normalized:") for item in result.evidence)


def test_schema_feasibility_accepts_cross_service_multistep_plan(tmp_path: Path) -> None:
    _write_cross_service_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_COMPANY")
    plan = QueryPlan(
        service_name="API_GL",
        entity_set="A_GLAccountInChartOfAccounts",
        plan_kind="multi_step",
        target_entity_set="A_GLAccountInChartOfAccounts",
        steps=[
            ExecutionStep(
                step_id="resolve_chart",
                service_name="API_COMPANY",
                entity_set="A_CompanyCode",
                select_fields=["CompanyCode", "ChartOfAccounts"],
                filters=[FilterCondition(field="CompanyCode", operator="eq", value="1710")],
            ),
            ExecutionStep(
                step_id="read_gl_accounts",
                service_name="API_GL",
                entity_set="A_GLAccountInChartOfAccounts",
                select_fields=["ChartOfAccounts", "GLAccount", "IsBalanceSheetAccount"],
                filters=[FilterCondition(field="IsBalanceSheetAccount", operator="eq", value="false")],
                filter_from_previous=[
                    StepBinding(
                        field="ChartOfAccounts",
                        source_step_id="resolve_chart",
                        source_field="ChartOfAccounts",
                    )
                ],
            ),
        ],
    )

    result = validator.validate(AgentRequest(user_input="query company 1710 expense accounts"), plan)

    assert result.passed is True
    assert result.evidence == ["steps_validated:2"]


def test_schema_feasibility_rejects_unbounded_downstream_multistep_query(tmp_path: Path) -> None:
    _write_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_TEST")
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BPContactToAddress",
        plan_kind="multi_step",
        steps=[
            ExecutionStep(
                step_id="find_customer",
                entity_set="A_BusinessPartner",
                select_fields=["BusinessPartner", "Customer"],
                filters=[FilterCondition(field="Customer", operator="eq", value="300001")],
            ),
            ExecutionStep(
                step_id="read_contacts",
                entity_set="A_BPContactToAddress",
                select_fields=["BusinessPartnerCompany", "BusinessPartnerPerson"],
                filters=[],
                filter_from_previous=[],
            ),
        ],
    )

    result = validator.validate(_request(), plan)

    assert result.passed is False
    assert "step_missing_filter_or_binding" in {violation.code for violation in result.violations}


def test_schema_feasibility_reports_invalid_binding_target_instead_of_missing_binding(tmp_path: Path) -> None:
    _write_index(tmp_path)
    validator = SchemaFeasibilityValidator(index_root=tmp_path, service_name="API_TEST")
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BPContactToAddress",
        plan_kind="multi_step",
        steps=[
            ExecutionStep(
                step_id="find_customer",
                entity_set="A_BusinessPartner",
                select_fields=["BusinessPartner", "Customer"],
                filters=[FilterCondition(field="Customer", operator="eq", value="300001")],
            ),
            ExecutionStep(
                step_id="read_contacts",
                entity_set="A_BPContactToAddress",
                select_fields=["BusinessPartnerCompany", "BusinessPartnerPerson"],
                filter_from_previous=[
                    StepBinding(
                        field="BusinessPartner",
                        source_step_id="find_customer",
                        source_field="BusinessPartner",
                    )
                ],
            ),
        ],
    )

    result = validator.validate(_request(), plan)
    codes = {violation.code for violation in result.violations}

    assert result.passed is False
    assert "step_binding_target_not_in_entity" in codes
    assert "step_missing_filter_or_binding" not in codes


def test_repair_rebuilds_schema_feasible_direct_plan_from_required_constraints(tmp_path: Path) -> None:
    _write_index(tmp_path)
    engine = IndexAwareRepairEngine(index_root=tmp_path, service_name="API_TEST")
    bad_plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_BPContactToAddress",
        select_fields=["BusinessPartnerCompany", "BusinessPartnerPerson"],
        filters=[],
        rationale="Wrong entity selected.",
    )

    repaired = engine.repair(
        _request(),
        context=None,
        previous_plan=bad_plan,
        error_message="schema_missing_required_answer_field; schema_missing_required_filter_field",
    )

    assert repaired.entity_set == "A_BusinessPartner"
    assert repaired.select_fields[:2] == ["BusinessPartner", "Customer"]
    assert repaired.filters[0].field == "Customer"
    assert repaired.filters[0].value == "300001"
