from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any


SAP_JSON_DATE_PATTERN = re.compile(r"/?Date\((-?\d+)(?:[+-]\d+)?\)/?")
UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def format_sap_json_date_for_display(value: Any) -> Any:
    """Format SAP OData V2 JSON date strings without relying on OS timestamp range."""
    if not isinstance(value, str):
        return value

    match = SAP_JSON_DATE_PATTERN.fullmatch(value.strip())
    if not match:
        return value

    try:
        milliseconds = int(match.group(1))
        return (UTC_EPOCH + timedelta(milliseconds=milliseconds)).strftime("%Y.%m.%d")
    except (OverflowError, OSError, ValueError):
        return value
