# Release procedure

Releases are produced only from a clean, reviewed commit on `main`.

1. Set the same version in `pyproject.toml` and `src/prompt_playoff/__init__.py`.
2. Move the relevant changelog entries from Unreleased into a dated version section.
3. Run `make test`, `make lint`, `make validate`, `make audit-links`, and `git diff --check`.
4. Build in a clean environment with `python -m build`; run `python -m twine check dist/*` and
   `python scripts/audit_publication.py --artifact dist/*.whl`.
5. Inspect the wheel: source-only datasets must be absent, while LICENSE and
   THIRD_PARTY_NOTICES must be present.
6. Merge the exact commit, wait for CI on that SHA, then create and push an annotated `vX.Y.Z` tag.

The tag workflow repeats the suite, validates live links, checks the wheel, generates SHA-256
checksums and a CycloneDX SBOM, creates a draft GitHub Release, publishes through PyPI Trusted
Publishing, and makes the GitHub Release public only after PyPI succeeds.

Do not rerun a failed release with the same version after PyPI accepted it. Increment the patch
version and document the correction.
