from sap_odata_agent.infrastructure.llm.result_verifier_agent import LlmResultVerifierAgent


def test_result_verifier_prompt_allows_empty_list_results() -> None:
    prompt = LlmResultVerifierAgent._user_prompt(
        request=type("Request", (), {"resolved_user_input": "", "user_input": "查询传真号码列表"})(),
        plan=type(
            "Plan",
            (),
            {
                "plan_kind": "direct",
                "entity_set": "A_AddressFaxNumber",
                "select_fields": ["AddressID", "FaxNumber"],
                "response_summary_fields": ["AddressID", "FaxNumber"],
                "filters": [],
                "steps": [],
            },
        )(),
        data={"result_count": 0, "results": []},
        schema_research={},
        schema_context_summary={},
    )

    assert "result_count=0 can be a correct answer" in prompt
    assert "Do not require enrichment identifiers" in prompt
    assert "business object name" in prompt
