from datetime import date

from sap_odata_agent.application.temporal_normalizer import TemporalNormalizer


def test_temporal_normalizer_resolves_common_chinese_relative_ranges() -> None:
    normalizer = TemporalNormalizer(today=date(2026, 6, 4))

    cases = {
        "查询本周到货的采购订单": ("本周", "2026-06-01T00:00:00", "2026-06-07T23:59:59"),
        "查询上周到货的采购订单": ("上周", "2026-05-25T00:00:00", "2026-05-31T23:59:59"),
        "查询下周到货的采购订单": ("下周", "2026-06-08T00:00:00", "2026-06-14T23:59:59"),
        "查询下月到货的采购订单": ("下月", "2026-07-01T00:00:00", "2026-07-31T23:59:59"),
        "查询明天到货的采购订单": ("明天", "2026-06-05T00:00:00", "2026-06-05T23:59:59"),
        "查询后天到货的采购订单": ("后天", "2026-06-06T00:00:00", "2026-06-06T23:59:59"),
        "查询昨天到货的采购订单": ("昨天", "2026-06-03T00:00:00", "2026-06-03T23:59:59"),
        "查询去年的采购订单": ("去年", "2025-01-01T00:00:00", "2025-12-31T23:59:59"),
    }

    for query, expected in cases.items():
        detected = normalizer.detect(query)
        assert detected, query
        assert (detected[0]["text"], detected[0]["range_start"], detected[0]["range_end"]) == expected


def test_temporal_normalizer_supports_week_synonyms() -> None:
    normalizer = TemporalNormalizer(today=date(2026, 6, 4))

    detected = normalizer.detect("查询上个周到货的采购订单")

    assert detected[0]["normalized_type"] == "calendar_week"
    assert detected[0]["range_start"] == "2026-05-25T00:00:00"
    assert detected[0]["range_end"] == "2026-05-31T23:59:59"
