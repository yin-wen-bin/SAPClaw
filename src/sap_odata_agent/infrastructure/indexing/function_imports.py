from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any


def load_function_imports(index_root: str | Path, service_name: str) -> list[dict[str, Any]]:
    service_dir = Path(index_root) / service_name
    return _load_function_imports(str(service_dir.resolve()))


def function_imports_from_snapshot(snapshot) -> list[dict[str, Any]]:
    return _load_function_imports(str(Path(snapshot.root_dir).resolve()))


@lru_cache(maxsize=16)
def _load_function_imports(service_dir: str) -> list[dict[str, Any]]:
    root_dir = Path(service_dir)
    metadata_files = list((root_dir / "raw").glob("*.metadata.xml"))
    if not metadata_files:
        metadata_files = list((root_dir / "raw").glob("*$metadata*.xml"))
    imports: list[dict[str, Any]] = []
    seen: set[str] = set()
    for metadata_file in metadata_files:
        try:
            root = ET.fromstring(metadata_file.read_text(encoding="utf-8"))
        except (OSError, ET.ParseError, UnicodeDecodeError):
            continue
        complex_types = _complex_type_fields(root)
        for function_import in root.findall(".//{*}FunctionImport"):
            name = str(function_import.attrib.get("Name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            imports.append(
                {
                    "name": name,
                    "entity_set": name,
                    "http_method": function_import.attrib.get(
                        "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}HttpMethod",
                        "GET",
                    ),
                    "return_type": function_import.attrib.get("ReturnType", ""),
                    "return_fields": complex_types.get(_local_type_name(function_import.attrib.get("ReturnType", "")), []),
                    "parameters": [
                        _parameter_payload(parameter)
                        for parameter in function_import.findall("{*}Parameter")
                        if parameter.attrib.get("Name")
                    ],
                }
            )
    return imports


def _complex_type_fields(root: ET.Element) -> dict[str, list[dict[str, Any]]]:
    types: dict[str, list[dict[str, Any]]] = {}
    for complex_type in root.findall(".//{*}ComplexType"):
        name = str(complex_type.attrib.get("Name") or "").strip()
        if not name:
            continue
        fields = []
        for property_node in complex_type.findall("{*}Property"):
            field_name = str(property_node.attrib.get("Name") or "").strip()
            if not field_name:
                continue
            data_type = str(property_node.attrib.get("Type") or "Edm.String")
            fields.append(
                {
                    "field_name": field_name,
                    "data_type": data_type,
                    "value_type": _value_type_from_edm(data_type),
                    "label": property_node.attrib.get("{http://www.sap.com/Protocols/SAPData}label", ""),
                }
            )
        types[name] = fields
    return types


def _local_type_name(return_type: str) -> str:
    value = str(return_type or "").strip()
    if value.startswith("Collection(") and value.endswith(")"):
        value = value[len("Collection(") : -1]
    return value.rsplit(".", 1)[-1]


def _parameter_payload(parameter: ET.Element) -> dict[str, Any]:
    data_type = str(parameter.attrib.get("Type") or "Edm.String")
    max_length = parameter.attrib.get("MaxLength")
    precision = parameter.attrib.get("Precision")
    scale = parameter.attrib.get("Scale")
    label = parameter.attrib.get("{http://www.sap.com/Protocols/SAPData}label", "")
    return {
        "name": parameter.attrib.get("Name", ""),
        "data_type": data_type,
        "value_type": _value_type_from_edm(data_type),
        "required": True,
        "mode": parameter.attrib.get("Mode", "In"),
        "label": label,
        "max_length": int(max_length) if str(max_length or "").isdigit() else None,
        "precision": int(precision) if str(precision or "").isdigit() else None,
        "scale": int(scale) if str(scale or "").isdigit() else None,
    }


def _value_type_from_edm(data_type: str) -> str:
    normalized = data_type.lower()
    if normalized.endswith("datetimeoffset"):
        return "datetimeoffset"
    if normalized.endswith("datetime"):
        return "datetime"
    if normalized.endswith("decimal"):
        return "decimal"
    if normalized.endswith("boolean"):
        return "boolean"
    if any(normalized.endswith(item) for item in ("int16", "int32", "int64", "double", "single")):
        return "number"
    return "string"
