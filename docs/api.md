# HTTP API

`prompt-playoff serve` exposes a versioned JSON API and an OpenAPI description.

- Interactive Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
- Health check: `GET /health`

The `/v1` prefix is the public compatibility boundary. Additive response fields may appear within
v1; removing or changing a field requires a new API version. The local server has no application
authentication layer, so do not expose it to an untrusted network without a reverse proxy and
access control.

## Select and compile

```bash
curl -sS http://127.0.0.1:8000/v1/recommend \
  -H 'content-type: application/json' \
  -d @examples/task_profile.json
```

The exact request and response schemas are generated from the running Pydantic models in OpenAPI.
Use the interactive docs for required fields rather than copying an old payload from a blog post.

## Business-case portfolios and experiment lineage

Create and manage the business cases that own prompt results:

```bash
curl -sS http://127.0.0.1:8000/v1/business-cases
curl -sS http://127.0.0.1:8000/v1/business-cases \
  -H 'content-type: application/json' \
  -d '{"name":"Support routing","description":"Route incoming tickets"}'
```

`PATCH /v1/business-cases/{id}` renames, describes, archives, or restores a case. `DELETE` is a
safe archive operation: it never erases experiment lineage. Pass the returned id as
`business_case_id` to `/v1/benchmark`, `/v1/compare`, or `/v1/optimize`.

Recorded experiments expose `business_case_id`, `business_case_name`, `prompt_id`, and
`prompt_version`. Re-running identical prompt text keeps the same prompt version; recording changed
text increments it. Version comparison is restricted to the same business case, prompt family, and
dataset so unrelated results cannot be presented as a prompt regression.

## Inspect datasets and provenance

```bash
curl -sS http://127.0.0.1:8000/v1/datasets
curl -sS http://127.0.0.1:8000/v1/datasets/catalog
curl -sS http://127.0.0.1:8000/v1/datasets/entity-extraction
```

Catalogue cases include `source_record`, `evidence_status`, and `evidence_note`. Dataset records
include upstream license, license URL, pinned revision, redistribution status, and whether rows are
bundled. `source_only` datasets deliberately return no packaged rows.

## Errors

Validation failures use HTTP 422 with FastAPI's structured `detail` array. Missing resources use
404. Conflicts such as duplicate identifiers use 409. Long benchmark, comparison and optimization
requests return a job record; poll `GET /v1/jobs/{job_id}` instead of keeping the request open.

Provider credentials are request-scoped or read from environment variables. They are not returned
by the API or written to saved model profiles. See [configuration](configuration.md) and
[integrations](integrations.md).
