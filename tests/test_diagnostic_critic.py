from sap_odata_agent.application.diagnostic_critic import DiagnosticCritic
from sap_odata_agent.application.failure_attributor import FailureAttributor
from sap_odata_agent.domain.models import (
    AgentRequest,
    CardinalityPolicy,
    CriticFinding,
    FilterCondition,
    GuardrailDecision,
    QueryConstraints,
    QueryPlan,
    QueryShape,
    RetrievedContext,
    RetrievedDocument,
)


def test_diagnostic_critic_flags_anchor_field_as_wrong_required_target() -> None:
    request = AgentRequest(
        user_input="\u4e1a\u52a1\u4f19\u4f341000561\u7684\u5ba2\u6237\u7f16\u53f7\u548c\u5ba2\u6237\u79d1\u76ee\u7ec4\u662f\u4ec0\u4e48\uff1f",
        constraints=QueryConstraints(
            query_shape=QueryShape.SINGLE_FACT,
            cardinality=CardinalityPolicy.ONE,
            target_object="business_partner",
            target_field_concepts=["BusinessPartner"],
            filter_values=["1000561"],
        ),
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Customer",
        select_fields=["Customer", "CustomerAccountGroup"],
        filters=[FilterCondition(field="BusinessPartner", operator="eq", value="1000561")],
    )

    findings = DiagnosticCritic().review(request, RetrievedContext(), plan)

    assert any(
        item.code == "anchor_field_misclassified_as_target" and item.blocking
        for item in findings
    )


def test_diagnostic_critic_flags_recalled_answer_field_dropped_from_constraints() -> None:
    request = AgentRequest(
        user_input="\u4e1a\u52a1\u4f19\u4f341000561\u7684\u5ba2\u6237\u7f16\u53f7\u548c\u5ba2\u6237\u79d1\u76ee\u7ec4\u662f\u4ec0\u4e48\uff1f",
        constraints=QueryConstraints(
            query_shape=QueryShape.SINGLE_FACT,
            cardinality=CardinalityPolicy.ONE,
            target_object="business_partner",
            target_field_concepts=["Customer"],
            filter_values=["1000561"],
        ),
    )
    context = RetrievedContext(
        documents=[
            RetrievedDocument(
                source="field-exact",
                title="A_Customer.CustomerAccountGroup",
                content="Exact metadata field match.",
                score=67.25,
                metadata={
                    "entity_set": "A_Customer",
                    "field_name": "CustomerAccountGroup",
                    "label": "\u5ba2\u6237\u79d1\u76ee\u7ec4",
                    "description": "\u5ba2\u6237\u79d1\u76ee\u7ec4",
                    "business_aliases": ["\u5ba2\u6237\u79d1\u76ee\u7ec4"],
                    "matched_alias": "\u5ba2\u6237\u79d1\u76ee\u7ec4",
                },
            )
        ]
    )
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Customer",
        select_fields=["Customer"],
    )

    findings = DiagnosticCritic().review(
        request,
        context,
        plan,
        critic_findings=[
            CriticFinding(
                code="required_target_field_missing",
                message="The final select list does not include the requested target field(s): CustomerAccountGroup",
                severity="error",
                blocking=True,
            )
        ],
    )

    assert any(
        item.code == "recalled_answer_field_not_in_constraints" and item.blocking
        for item in findings
    )


def test_failure_attributor_prioritizes_guardrail_over_diagnostic_root_cause() -> None:
    finding = CriticFinding(
        code="anchor_field_misclassified_as_target",
        message="BusinessPartner is an anchor field, not an answer field.",
        severity="error",
        blocking=True,
    )

    attribution = FailureAttributor().attribute(
        AgentRequest(user_input="test"),
        QueryPlan(service_name="API_TEST", entity_set="A_Customer"),
        success=False,
        final_message="Unable to produce a valid SAP OData request within the configured retry limit.",
        guardrail_decision=GuardrailDecision(
            accepted=False,
            winner="repair",
            reasons=["required_target_field_missing:BusinessPartner"],
            severity="blocking",
        ),
        critic_findings=[finding],
    )

    assert attribution is not None
    assert attribution.category == "plan_guardrail_blocked"


def test_failure_attributor_prioritizes_schema_filter_failures_over_diagnostics() -> None:
    findings = [
        CriticFinding(
            code="recalled_answer_field_not_in_constraints",
            message="Metadata recall found a likely answer field that constraints dropped.",
            severity="error",
            blocking=True,
        ),
        CriticFinding(
            code="schema_missing_required_filter_field",
            message="The plan does not apply any required filter field: Region",
            severity="error",
            blocking=True,
        ),
        CriticFinding(
            code="schema_filter_value_dropped",
            message="The plan does not preserve required filter value(s): HH",
            severity="error",
            blocking=True,
        ),
    ]

    attribution = FailureAttributor().attribute(
        AgentRequest(user_input="test"),
        QueryPlan(service_name="API_TEST", entity_set="A_BusinessPartner"),
        success=False,
        final_message="Unable to produce a valid SAP OData request within the configured retry limit.",
        critic_findings=findings,
    )

    assert attribution is not None
    assert attribution.category == "schema_filter_value_dropped"
