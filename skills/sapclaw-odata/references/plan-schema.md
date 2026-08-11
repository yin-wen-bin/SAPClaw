# Runtime QueryPlan Reference

## Direct plan

```json
{
  "service_name": "<indexed-service>",
  "entity_set": "<schema-entity>",
  "http_method": "GET",
  "select_fields": ["<field>"],
  "response_summary_fields": ["<field>"],
  "output_contract": {
    "mode": "inferred",
    "display_grain": "<business row grain>",
    "requested_fields": [],
    "display_fields": ["<field shown to user>"],
    "support_fields": ["<field fetched but hidden>"],
    "reason": "<why this is the smallest complete business view>"
  },
  "filters": [
    {"field": "<field>", "operator": "eq", "value": "<value>", "value_type": "string"}
  ],
  "order_by": [],
  "top": null,
  "plan_kind": "direct"
}
```

Allowed filter operators: `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `contains`, `in`.

Use schema-compatible `value_type` values such as `string`, `boolean`, `number`, `decimal`, `date`, `datetime`, `datetimeoffset`, or `null`.

## Multi-step plan

Set `plan_kind` to `multi_step` or `lookup` and provide ordered `steps`. Each step after the first must have a direct filter or a binding.

```json
{
  "service_name": "<primary-service>",
  "entity_set": "<final-entity>",
  "plan_kind": "multi_step",
  "steps": [
    {
      "step_id": "step_1",
      "service_name": "<service-a>",
      "entity_set": "<entity-a>",
      "select_fields": ["<source-key>"],
      "filters": [],
      "filter_from_previous": [],
      "top": null
    },
    {
      "step_id": "step_2",
      "service_name": "<service-b>",
      "entity_set": "<entity-b>",
      "select_fields": ["<answer-field>"],
      "filters": [],
      "filter_from_previous": [
        {
          "field": "<target-filter-field>",
          "source_step_id": "step_1",
          "source_field": "<source-key>",
          "fanout": false,
          "fetch_all_for_binding": true
        }
      ],
      "top": null
    }
  ]
}
```

The source field must be selected in its source step. The target field must exist and be filterable on the target entity.

## Function import

Set `plan_kind` to `function_import`, use the indexed function name as `entity_set`, and provide every required parameter.

```json
{
  "service_name": "<indexed-service>",
  "entity_set": "<function-name>",
  "plan_kind": "function_import",
  "function_parameters": [
    {"name": "<parameter>", "value": "<value>", "value_type": "string"}
  ],
  "top": null
}
```

## Aggregate transform

Use only fields selected from the final result entity.

```json
{
  "result_transform": {
    "type": "aggregate",
    "group_by": ["CompanyCode", "CompanyCodeCurrency"],
    "deduplicate_by": [
      "CompanyCode",
      "FiscalYear",
      "AccountingDocument",
      "AccountingDocumentItem",
      "Ledger"
    ],
    "metrics": [
      {"operation": "count", "output_field": "SourceItemCount"},
      {
        "operation": "count_distinct",
        "output_field": "DistinctItemCount",
        "distinct_fields": [
          "CompanyCode",
          "FiscalYear",
          "AccountingDocument",
          "AccountingDocumentItem",
          "Ledger"
        ]
      },
      {
        "operation": "sum_abs",
        "output_field": "AbsoluteAmount",
        "field": "AmountInCompanyCodeCurrency",
        "currency_field": "CompanyCodeCurrency"
      }
    ]
  }
}
```

Supported operations are `count`, `count_distinct`, `sum`, and `sum_abs`. `sum_fields`
remains available for compatibility and is equivalent to `sum` with the source field as
the output name.

Aggregation automatically pages the complete source in stable indexed-key order and is
bounded by the runtime safety limit. It fails closed for incomplete sources, missing
deduplication keys, invalid numeric values, or unresolved/mixed currencies. Diagnostics
include source/fetched/deduplicated row counts, completeness, truncation, stable keys, and
currency groups.

If source pagination is interrupted after at least one saved page, call
`sapclaw_execute_plan` again with the identical plan and the failed response's `case_id`
as `resume_case_id`. The runtime resumes from the saved stable-key cursor and combines the
saved and newly fetched rows before aggregation.

## Output contract

`output_contract` is optional only for compatibility with older clients. New Codex-authored plans must provide it.

- `explicit`: `requested_fields` and `display_fields` must match exactly and use schema field names.
- `inferred`: Codex selects the smallest complete business view from the user intent and schema.
- `support_fields`: fields requested from SAP but hidden from the result table.
- `display_fields`: ordered fields visible in the table, result summary, and local viewer.
- Aggregate plans may display only `group_by` fields, legacy `sum_fields`, and metric `output_field` values.
