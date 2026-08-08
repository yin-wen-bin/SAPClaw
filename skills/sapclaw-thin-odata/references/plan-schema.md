# Thin QueryPlan Reference

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
    "group_by": ["<dimension>"],
    "sum_fields": ["<numeric-measure>"]
  }
}
```

Aggregation requires a complete source result and is bounded by runtime safety limits.

## Output contract

`output_contract` is optional only for compatibility with older clients. New Codex-authored plans must provide it.

- `explicit`: `requested_fields` and `display_fields` must match exactly and use schema field names.
- `inferred`: Codex selects the smallest complete business view from the user intent and schema.
- `support_fields`: fields requested from SAP but hidden from the result table.
- `display_fields`: ordered fields visible in the table, result summary, and local viewer.
- Aggregate plans may display only `group_by` and `sum_fields`.
