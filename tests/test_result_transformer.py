import pytest

from sap_odata_agent.application.result_transformer import ResultTransformError, ResultTransformer
from sap_odata_agent.domain.models import AggregateMetric, QueryPlan, ResultTransform


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


def test_result_transformer_supports_complete_auditable_aggregate_metrics() -> None:
    plan = QueryPlan(
        service_name="API_GLACCOUNTLINEITEM",
        entity_set="GLAccountLineItem",
        result_transform=ResultTransform(
            type="aggregate",
            group_by=["CompanyCode", "CompanyCodeCurrency"],
            deduplicate_by=["CompanyCode", "FiscalYear", "AccountingDocument", "AccountingDocumentItem", "Ledger"],
            metrics=[
                AggregateMetric(operation="count", output_field="RowCount"),
                AggregateMetric(
                    operation="count_distinct",
                    output_field="DistinctItemCount",
                    distinct_fields=[
                        "CompanyCode",
                        "FiscalYear",
                        "AccountingDocument",
                        "AccountingDocumentItem",
                        "Ledger",
                    ],
                ),
                AggregateMetric(
                    operation="sum",
                    output_field="NetAmount",
                    field="AmountInCompanyCodeCurrency",
                    currency_field="CompanyCodeCurrency",
                ),
                AggregateMetric(
                    operation="sum_abs",
                    output_field="AbsoluteAmount",
                    field="AmountInCompanyCodeCurrency",
                    currency_field="CompanyCodeCurrency",
                ),
            ],
        ),
    )
    rows = [
        {
            "CompanyCode": "1710",
            "CompanyCodeCurrency": "CNY",
            "FiscalYear": "2026",
            "AccountingDocument": "1000000001",
            "AccountingDocumentItem": "001",
            "Ledger": "0L",
            "AmountInCompanyCodeCurrency": "-10",
        },
        {
            "CompanyCode": "1710",
            "CompanyCodeCurrency": "CNY",
            "FiscalYear": "2026",
            "AccountingDocument": "1000000002",
            "AccountingDocumentItem": "001",
            "Ledger": "0L",
            "AmountInCompanyCodeCurrency": "5",
        },
    ]
    data = {
        "result_count": 3,
        "returned_count": 3,
        "_all_results": [rows[0], rows[0].copy(), rows[1]],
        "source_complete": True,
        "source_truncated": False,
        "source_stable_order_fields": ["ID"],
    }

    transformed = ResultTransformer().apply(plan, data)

    assert transformed is not None
    assert transformed["results"] == [
        {
            "CompanyCode": "1710",
            "CompanyCodeCurrency": "CNY",
            "RowCount": 2,
            "DistinctItemCount": 2,
            "NetAmount": "-5",
            "AbsoluteAmount": "15",
        }
    ]
    diagnostics = transformed["result_transform"]
    assert diagnostics["source_row_count"] == 3
    assert diagnostics["fetched_row_count"] == 3
    assert diagnostics["deduplicated_row_count"] == 2
    assert diagnostics["duplicate_row_count"] == 1
    assert diagnostics["source_complete"] is True
    assert diagnostics["currency_groups"] == {"CompanyCodeCurrency": ["CNY"]}
    assert diagnostics["stable_order_fields"] == ["ID"]


@pytest.mark.parametrize("invalid_value", [None, "", "not-a-number", "NaN"])
def test_result_transformer_fails_closed_for_invalid_numeric_values(invalid_value) -> None:
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Test",
        result_transform=ResultTransform(
            type="aggregate",
            metrics=[AggregateMetric(operation="sum", output_field="Total", field="Amount")],
        ),
    )

    with pytest.raises(ResultTransformError) as captured:
        ResultTransformer().apply(
            plan,
            {
                "result_count": 1,
                "returned_count": 1,
                "results": [{"Amount": invalid_value}],
                "source_complete": True,
            },
        )

    assert captured.value.code == "aggregate_invalid_numeric_value"


def test_result_transformer_fails_closed_for_incomplete_or_mixed_currency_source() -> None:
    plan = QueryPlan(
        service_name="API_TEST",
        entity_set="A_Test",
        result_transform=ResultTransform(
            type="aggregate",
            group_by=["CompanyCode"],
            metrics=[
                AggregateMetric(
                    operation="sum_abs",
                    output_field="AbsoluteAmount",
                    field="Amount",
                    currency_field="Currency",
                )
            ],
        ),
    )

    with pytest.raises(ResultTransformError) as incomplete:
        ResultTransformer().apply(
            plan,
            {
                "result_count": 2,
                "returned_count": 1,
                "results": [{"CompanyCode": "1710", "Currency": "CNY", "Amount": "1"}],
                "source_complete": False,
                "source_truncated": True,
            },
        )
    assert incomplete.value.code == "aggregate_source_incomplete"

    with pytest.raises(ResultTransformError) as mixed_currency:
        ResultTransformer().apply(
            plan,
            {
                "result_count": 2,
                "returned_count": 2,
                "results": [
                    {"CompanyCode": "1710", "Currency": "CNY", "Amount": "1"},
                    {"CompanyCode": "1710", "Currency": "USD", "Amount": "2"},
                ],
                "source_complete": True,
            },
        )
    assert mixed_currency.value.code == "aggregate_currency_unresolved"
