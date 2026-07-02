from sap_odata_agent.application.result_transformer import ResultTransformer
from sap_odata_agent.domain.models import QueryPlan, ResultTransform


def test_result_transformer_aggregates_rows_by_group_fields() -> None:
    plan = QueryPlan(
        service_name="API_MATERIAL_STOCK_SRV",
        entity_set="A_MatlStkInAcctMod",
        select_fields=["Material", "Plant", "MaterialBaseUnit", "Batch", "MatlWrhsStkQtyInMatlBaseUnit"],
        result_transform=ResultTransform(
            type="aggregate",
            group_by=["Material", "Plant", "MaterialBaseUnit"],
            sum_fields=["MatlWrhsStkQtyInMatlBaseUnit"],
        ),
    )
    data = {
        "result_count": 3,
        "returned_count": 3,
        "displayed_count": 3,
        "results": [
            {
                "Material": "2211",
                "Plant": "1710",
                "MaterialBaseUnit": "PC",
                "Batch": "B1",
                "MatlWrhsStkQtyInMatlBaseUnit": "2.500",
            },
            {
                "Material": "2211",
                "Plant": "1710",
                "MaterialBaseUnit": "PC",
                "Batch": "B2",
                "MatlWrhsStkQtyInMatlBaseUnit": "3.500",
            },
            {
                "Material": "2211",
                "Plant": "1720",
                "MaterialBaseUnit": "PC",
                "Batch": "B3",
                "MatlWrhsStkQtyInMatlBaseUnit": "1.000",
            },
        ],
    }

    transformed = ResultTransformer().apply(plan, data)

    assert transformed is not None
    assert transformed["result_count"] == 2
    assert transformed["results"] == [
        {
            "Material": "2211",
            "Plant": "1710",
            "MaterialBaseUnit": "PC",
            "MatlWrhsStkQtyInMatlBaseUnit": "6",
        },
        {
            "Material": "2211",
            "Plant": "1720",
            "MaterialBaseUnit": "PC",
            "MatlWrhsStkQtyInMatlBaseUnit": "1",
        },
    ]
    assert transformed["result_transform"]["source_result_count"] == 3


def test_result_transformer_marks_local_next_page_for_many_aggregate_groups() -> None:
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Test",
        result_transform=ResultTransform(
            type="aggregate",
            group_by=["Group"],
            sum_fields=["Amount"],
        ),
    )
    data = {
        "result_count": 51,
        "returned_count": 51,
        "_all_results": [{"Group": f"G{index:02d}", "Amount": "1"} for index in range(51)],
        "pagination": {"display_limit": 50},
    }

    transformed = ResultTransformer().apply(plan, data)

    assert transformed is not None
    assert transformed["result_count"] == 51
    assert transformed["displayed_count"] == 50
    assert transformed["pagination"]["has_next"] is True
    assert transformed["pagination"]["next_skip"] == 50
    assert transformed["pagination"]["sap_next_skip"] is None
