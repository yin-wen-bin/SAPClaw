# Dual-Source Indexing

SAPClaw builds local API indexes by combining two sources:

1. Live SAP OData `$metadata`.
2. Local SAP OpenAPI JSON specifications.

The generated index is required at runtime, but it is not published in this repository because it can contain customer-specific SAP metadata and large generated artifacts.

## Output Layout

```text
data/index/<service_name>/
  raw/
    <service_name>.metadata.xml
    <openapi-json-file-name>.json
  services.json
  entities.json
  fields.json
  relations.json
  business_terms.json
  doc_chunks.jsonl
  vector_documents.jsonl
  build_summary.json
```

`data/index/`, `data/metadata/`, and raw API files are ignored by Git.

## Build Command

Example:

```powershell
python -m sap_odata_agent.tools.build_dual_source_index `
  --sap-service-name API_BUSINESS_PARTNER `
  --openapi-json "<LOCAL_OPENAPI_JSON_FILE>"
```

If the local index directory name should differ from the SAP service name, pass:

```powershell
--index-service-name <LOCAL_INDEX_SERVICE_NAME>
```

## Inputs

- SAP connection values are read from `env/.env` or environment variables.
- The builder requests the SAP service `$metadata`.
- The builder parses the local OpenAPI JSON file.
- The merged result is written to `data/index/<service_name>/`.

## Code Entry Points

- Builder: `src/sap_odata_agent/infrastructure/indexing/dual_source_index_builder.py`
- CLI: `src/sap_odata_agent/tools/build_dual_source_index.py`
