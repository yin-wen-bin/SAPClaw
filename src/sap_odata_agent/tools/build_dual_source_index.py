from __future__ import annotations

import argparse
import json
from pathlib import Path

from sap_odata_agent.infrastructure.indexing.dual_source_index_builder import (
    DualSourceIndexBuilder,
    build_connection_config,
)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build local SAP OData index files from runtime metadata and OpenAPI JSON.")
    parser.add_argument("--sap-service-name", required=True, help="Actual SAP OData service name exposed by the runtime system.")
    parser.add_argument("--openapi-json", required=True, help="Path to the local OpenAPI JSON document.")
    parser.add_argument("--env-file", default="env/.env", help="Path to the .env file containing SAP connection information.")
    parser.add_argument("--output-root", default="data/index", help="Directory where merged index files will be written.")
    parser.add_argument(
        "--index-service-name",
        default=None,
        help="Optional logical service name for the output directory. Defaults to the SAP service name.",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()

    builder = DualSourceIndexBuilder()
    bundle = builder.build(
        sap_config=build_connection_config(args.env_file),
        sap_service_name=args.sap_service_name,
        openapi_json_path=args.openapi_json,
        output_root=args.output_root,
        index_service_name=args.index_service_name,
    )

    service_name = args.index_service_name or args.sap_service_name
    summary_path = Path(args.output_root) / service_name / "build_summary.json"
    print(
        json.dumps(
            {"output_service": service_name, "summary_path": str(summary_path), **bundle.summary},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
