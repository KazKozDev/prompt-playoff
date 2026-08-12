# Custom registry

The packaged registry lives under `src/prompt_playoff/data` so it is included in wheels.

To use an external registry, copy the `techniques/` and `models/` directories and set:

```bash
export PROMPT_PLAYOFF_REGISTRY=/absolute/path/to/your/registry
```

The external registry is validated with the same Pydantic schemas at startup.
