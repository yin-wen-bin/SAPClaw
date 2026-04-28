from sap_odata_agent.infrastructure.sap.date_formatting import format_sap_json_date_for_display


def test_formats_sap_json_date_without_os_timestamp_dependency() -> None:
    assert format_sap_json_date_for_display("/Date(1777852800000)/") == "2026.05.04"
    assert format_sap_json_date_for_display("Date(1777852800000)") == "2026.05.04"


def test_formats_large_sap_json_date_or_preserves_when_out_of_range() -> None:
    assert format_sap_json_date_for_display("/Date(253402214400000)/") == "9999.12.31"
    assert format_sap_json_date_for_display("/Date(999999999999999999999)/") == "/Date(999999999999999999999)/"


def test_non_sap_json_date_values_are_preserved() -> None:
    assert format_sap_json_date_for_display("TG0011") == "TG0011"
    assert format_sap_json_date_for_display(None) is None
