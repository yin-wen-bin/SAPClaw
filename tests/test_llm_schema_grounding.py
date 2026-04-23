import json
from pathlib import Path

from sap_odata_agent.domain.models import CardinalityPolicy, QueryConstraints, QueryShape
from sap_odata_agent.infrastructure.llm.schema_reranker import LlmSchemaReranker


class GroundingLlm:
    def __init__(self) -> None:
        self.last_prompt = ""

    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        self.last_prompt = user_prompt
        assert "A_SupplierPartnerFunc" in user_prompt
        assert "PartnerFunction" in user_prompt
        return json.dumps(
            {
                "answer_fields": [
                    {
                        "entity_set": "A_SupplierPartnerFunc",
                        "field_name": "PartnerFunction",
                        "confidence": 0.94,
                    }
                ],
                "filter_fields": [
                    {
                        "entity_set": "A_SupplierPartnerFunc",
                        "field_name": "Supplier",
                        "confidence": 0.96,
                    }
                ],
                "ranked_fields": [
                    {
                        "entity_set": "A_SupplierPartnerFunc",
                        "field_name": "PartnerFunction",
                        "role": "answer",
                        "confidence": 0.94,
                        "reason": "Supplier partner functions are exposed on the supplier partner function entity.",
                    },
                    {
                        "entity_set": "A_SupplierPartnerFunc",
                        "field_name": "Supplier",
                        "role": "filter",
                        "confidence": 0.96,
                        "reason": "The user supplied a supplier identifier.",
                    },
                ],
                "reason": "Broad schema grounding selected supplier partner function fields.",
            }
        )


class FailingGroundingLlm:
    def complete_json(self, system_prompt: str, user_prompt: str, max_tokens: int = 900) -> str:
        raise RuntimeError("llm unavailable")


def _write_index(root: Path) -> None:
    service_dir = root / "API_TEST"
    service_dir.mkdir(parents=True)
    (service_dir / "services.json").write_text(
        json.dumps([{"service_name": "API_TEST", "entity_sets": ["A_Supplier", "A_SupplierPartnerFunc"]}]),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_Supplier",
                    "entity_type": "A_SupplierType",
                    "key_fields": ["Supplier"],
                    "default_select_fields": ["Supplier", "SupplierName"],
                    "description": "Supplier master data.",
                    "supported_methods": ["GET"],
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "entity_type": "A_SupplierPartnerFuncType",
                    "key_fields": ["Supplier", "PurchasingOrganization", "PartnerFunction", "PartnerCounter"],
                    "default_select_fields": [
                        "Supplier",
                        "PurchasingOrganization",
                        "PartnerFunction",
                        "PartnerCounter",
                    ],
                    "description": "Retrieves supplier purchasing organization partner function records.",
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
                    "entity_set": "A_Supplier",
                    "field_name": "Supplier",
                    "label": "供应商",
                    "description": "供应商",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "field_name": "Supplier",
                    "label": "供应商",
                    "description": "供应商",
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "field_name": "PartnerFunction",
                    "label": "合作伙伴职能",
                    "description": "合作伙伴职能",
                    "business_aliases": ["合作伙伴职能"],
                    "filterable": True,
                },
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_SupplierPartnerFunc",
                    "field_name": "PurchasingOrganization",
                    "label": "采购组织",
                    "description": "采购组织",
                    "filterable": True,
                },
            ]
        ),
        encoding="utf-8",
    )
    for name in ("relations.json", "entity_graph.json", "lookup_paths.json", "business_terms.json"):
        (service_dir / name).write_text("[]", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")


def test_broad_schema_grounding_fills_missing_answer_and_filter_fields(tmp_path: Path) -> None:
    _write_index(tmp_path)
    llm = GroundingLlm()
    reranker = LlmSchemaReranker(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=llm,
        enabled=True,
    )
    constraints = QueryConstraints(
        query_shape=QueryShape.LIST_QUERY,
        cardinality=CardinalityPolicy.MANY,
        target_object="supplier",
        target_field_concepts=[],
        filter_concepts=[],
        filter_values=["17300003"],
    )

    result = reranker.rerank(
        "供应商17300003的合作伙伴功能有哪些？",
        constraints,
        retrieved_documents=[],
    )

    assert result["grounding_mode"] == "broad_schema"
    assert result["grounding_reason"] == "llm_first_broad_schema_grounding"
    assert result["answer_fields"] == ["PartnerFunction"]
    assert result["filter_fields"] == ["Supplier"]
    assert result["ranked_fields"][0]["entity_set"] == "A_SupplierPartnerFunc"


def test_schema_grounding_can_keep_old_local_trigger_mode(tmp_path: Path) -> None:
    _write_index(tmp_path)
    llm = GroundingLlm()
    reranker = LlmSchemaReranker(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=llm,
        enabled=True,
        llm_first=False,
    )
    constraints = QueryConstraints(
        query_shape=QueryShape.LIST_QUERY,
        cardinality=CardinalityPolicy.MANY,
        target_object="supplier",
        target_field_concepts=[],
        filter_concepts=[],
        filter_values=["17300003"],
    )

    result = reranker.rerank(
        "\u4f9b\u5e94\u554617300003\u7684\u5408\u4f5c\u4f19\u4f34\u529f\u80fd\u6709\u54ea\u4e9b\uff1f",
        constraints,
        retrieved_documents=[],
    )

    assert result["grounding_reason"] == "target_field_missing_after_local_recall"


def test_llm_first_grounding_failure_does_not_inject_broad_fallback_fields(tmp_path: Path) -> None:
    _write_index(tmp_path)
    reranker = LlmSchemaReranker(
        index_root=tmp_path,
        service_name="API_TEST",
        llm_client=FailingGroundingLlm(),
        enabled=True,
    )
    constraints = QueryConstraints(
        query_shape=QueryShape.LIST_QUERY,
        cardinality=CardinalityPolicy.MANY,
        target_object="supplier",
        target_field_concepts=[],
        filter_concepts=[],
        filter_values=["17300003"],
    )

    result = reranker.rerank(
        "\u4f9b\u5e94\u554617300003\u7684\u5408\u4f5c\u4f19\u4f34\u529f\u80fd\u6709\u54ea\u4e9b\uff1f",
        constraints,
        retrieved_documents=[],
    )

    assert result["accepted"] is False
    assert result["answer_fields"] == []
    assert result["filter_fields"] == []
