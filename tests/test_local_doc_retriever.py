import json
from pathlib import Path

from sap_odata_agent.infrastructure.retrieval.local_doc_retriever import LocalDocRetriever


def test_local_doc_retriever_reads_index_and_ranks_matches(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)

    (service_dir / "services.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "description": "Business partner service for customer master data",
                    "entity_sets": ["A_BusinessPartner"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "entities.json").write_text(
        json.dumps(
            [
                {
                    "service_name": "API_TEST",
                    "entity_set": "A_BusinessPartner",
                    "entity_type": "A_BusinessPartnerType",
                    "key_fields": ["BusinessPartner"],
                    "default_select_fields": ["BusinessPartner", "BusinessPartnerFullName"],
                    "supported_methods": ["GET"],
                    "description": "Customer and supplier master data",
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
                    "entity_set": "A_BusinessPartner",
                    "field_name": "BusinessPartner",
                    "label": "客户",
                    "business_aliases": ["客户", "业务伙伴"],
                    "data_type": "Edm.String",
                    "filterable": True,
                    "sortable": True,
                    "description": "客户编号",
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "relations.json").write_text("[]", encoding="utf-8")
    (service_dir / "business_terms.json").write_text(
        json.dumps(
            [
                {
                    "term": "客户",
                    "mapped_service": "API_TEST",
                    "mapped_entity_set": "A_BusinessPartner",
                    "mapped_fields": ["BusinessPartner", "BusinessPartnerFullName"],
                    "synonyms": ["业务伙伴"],
                }
            ]
        ),
        encoding="utf-8",
    )
    (service_dir / "doc_chunks.jsonl").write_text(
        json.dumps(
            {
                "chunk_id": "chunk-1",
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartner",
                "field_names": ["BusinessPartner"],
                "content": "A_BusinessPartner supports filtering by BusinessPartner for customer queries.",
                "keywords": ["客户", "BusinessPartner"],
                "source_type": "openapi_json",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    retriever = LocalDocRetriever(index_root=tmp_path, service_name="API_TEST")
    result = retriever.retrieve("查询客户1000001", top_k=3)

    assert len(result.documents) == 3
    assert result.documents[0].score >= result.documents[-1].score
    assert any("A_BusinessPartner" in item.content or "A_BusinessPartner" in item.title for item in result.documents)


def test_local_doc_retriever_reports_missing_index(tmp_path: Path) -> None:
    retriever = LocalDocRetriever(index_root=tmp_path, service_name="MISSING")
    result = retriever.retrieve("客户", top_k=3)

    assert len(result.documents) == 1
    assert result.documents[0].title == "index-missing"


def test_local_doc_retriever_uses_vector_documents_for_hybrid_recall(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)

    for filename, payload in {
        "services.json": [],
        "entities.json": [],
        "fields.json": [],
        "relations.json": [],
        "lookup_paths.json": [],
        "business_terms.json": [],
    }.items():
        (service_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text(
        json.dumps(
            {
                "doc_id": "field::A_BusinessPartnerAddress.PostalCode",
                "doc_type": "field",
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "PostalCode",
                "content": (
                    "entity: A_BusinessPartnerAddress\n"
                    "field: PostalCode\n"
                    "label: 邮政编码\n"
                    "description: 城市邮政编码\n"
                    "aliases: postal code, zip code"
                ),
                "metadata": {"description": "City postal code"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    retriever = LocalDocRetriever(index_root=tmp_path, service_name="API_TEST")
    result = retriever.retrieve("zip code for supplier", top_k=3)

    assert any(doc.source == "field-vector" for doc in result.documents)
    assert any((doc.metadata or {}).get("field_name") == "PostalCode" for doc in result.documents)


def test_local_doc_retriever_prioritizes_exact_metadata_field_labels(tmp_path: Path) -> None:
    service_dir = tmp_path / "API_TEST"
    service_dir.mkdir(parents=True)

    for filename, payload in {
        "services.json": [
            {
                "service_name": "API_TEST",
                "description": "Business partner service",
                "entity_sets": ["A_BusinessPartner", "A_BusinessPartnerAddress"],
            }
        ],
        "entities.json": [
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartner",
                "entity_type": "A_BusinessPartnerType",
                "key_fields": ["BusinessPartner"],
                "default_select_fields": ["BusinessPartner"],
                "supported_methods": ["GET"],
                "description": "Business partner data",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartnerAddress",
                "entity_type": "A_BusinessPartnerAddressType",
                "key_fields": ["BusinessPartner", "AddressID"],
                "default_select_fields": ["BusinessPartner", "Region"],
                "supported_methods": ["GET"],
                "description": "Business partner address data",
            },
        ],
        "fields.json": [
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartner",
                "field_name": "BusinessPartner",
                "label": "\u4e1a\u52a1\u4f19\u4f34",
                "business_aliases": ["\u4e1a\u52a1\u4f19\u4f34"],
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "\u4e1a\u52a1\u4f19\u4f34\u7f16\u53f7",
            },
            {
                "service_name": "API_TEST",
                "entity_set": "A_BusinessPartnerAddress",
                "field_name": "Region",
                "label": "\u5730\u533a",
                "business_aliases": ["\u5730\u533a"],
                "data_type": "Edm.String",
                "filterable": True,
                "sortable": True,
                "description": "\u5730\u533a\uff08\u7701/\u81ea\u6cbb\u533a/\u76f4\u8f96\u5e02\uff09",
            },
        ],
        "relations.json": [],
        "entity_graph.json": [],
        "lookup_paths.json": [],
        "business_terms.json": [],
    }.items():
        (service_dir / filename).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (service_dir / "doc_chunks.jsonl").write_text("", encoding="utf-8")
    (service_dir / "vector_documents.jsonl").write_text("", encoding="utf-8")

    retriever = LocalDocRetriever(index_root=tmp_path, service_name="API_TEST")
    result = retriever.retrieve("\u4e1a\u52a1\u4f19\u4f341000561\u7684\u5730\u533a\u662f\u54ea\u91cc\uff1f", top_k=5)

    assert any(doc.source == "field-exact" for doc in result.documents)
    assert any((doc.metadata or {}).get("field_name") == "Region" for doc in result.documents)
