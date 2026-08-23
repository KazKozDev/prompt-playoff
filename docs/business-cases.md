# Business-case evidence policy

The business catalogue records public reports of work performed with an LLM. It does not treat a
vendor customer story as an independent evaluation and does not treat a nearby public benchmark as
proof that the deployment will succeed.

Every case must resolve a `source_ref` into the source registry in `business_cases.yaml` and carry:

- `verified_official` when the cited official source directly supports the described deployment;
- `qualified_official` when the source supports a related capability, aggregate customer use, a
  planned rollout, or a weaker formulation;
- `unverified` when the exact deployment claim was not located in a primary source.

Each card links the source and exposes the qualification. Figures are self-reported customer or
vendor claims unless a source explicitly identifies an independent measurement. `match` is a
different axis: it describes whether a public dataset has the same input-to-output shape as the
business work.

Sources were last reviewed on 2026-08-23. Run `python scripts/audit_publication.py --check-links`
before a release to revalidate their availability; a successful HTTP response proves availability,
not truth.
