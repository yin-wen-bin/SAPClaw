# Thin Runtime Examples

## Catalog and schema

```text
sapclaw_catalog(query=<original user question>, skip=0, limit=20)
sapclaw_schema(service_name=<candidate>, entity_sets=[<candidate entity>], query=<question>)
sapclaw_guidance(user_input=<question>, service_names=[<candidate>])
```

Do not select an API from guidance alone. Confirm `odata_runtime_available` and every planned field in schema.

## Validate and execute

```text
sapclaw_validate_plan(plan=<strict plan>, user_input=<original question>)
sapclaw_execute_plan(plan=<same validated plan>, user_input=<original question>)
```

Do not skip validation. `sapclaw_execute_plan` revalidates to prevent time-of-check/time-of-use drift.

For every structured plan, include `output_contract`. For example, a user who explicitly requests only a name receives a strict contract with that one schema field in both `requested_fields` and `display_fields`; any identifier needed for execution belongs in `support_fields`.

## Controlled GET

```text
sapclaw_execute_get(
  service_name=<indexed service>,
  resource_path=<relative entity or function path>,
  query_options={"$select": "FieldA,FieldB", "$filter": "FieldA eq 'value'"},
  output_contract={
    "display_fields": ["FieldA"],
    "reason": "Return the field requested by the user."
  },
  user_input=<original question>
)
```

Never pass a URL, host, authentication header, or query string inside `resource_path`.

## Page navigation

```text
sapclaw_runtime_page(case_id=<case id>, skip=<next_skip>)
```

Use the returned `page_size`, `total_count`, `has_next`, and `next_skip` as authoritative pagination state.
