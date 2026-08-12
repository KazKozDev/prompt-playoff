# Security policy

## Supported versions

The latest release on PyPI. This is a single-maintainer project; older versions
receive no backports.

## Reporting a vulnerability

Report privately through GitHub's
[security advisory form](https://github.com/KazKozDev/prompt-playoff/security/advisories/new)
rather than a public issue. Expect a first reply within a week.

Please include what you did, what happened, and the version you ran.

## What is in scope

The parts of this project that touch untrusted input or credentials:

- **API keys.** They are resolved from environment variables or an in-memory
  request key and must never reach a log, a trace span, a saved report, or the
  jobs store. A leak of a key into any persisted file is a vulnerability.
- **The code sandbox.** `mbpp` grading executes model-written Python in a
  restricted interpreter. An escape from it is a vulnerability.
- **Registry loading.** Technique and model files are parsed as YAML with
  `safe_load` and validated against Pydantic schemas. A file that executes code
  or reads outside the registry directory during load is a vulnerability.
- **The HTTP API and web UI.** They bind to `127.0.0.1` by default.

## What is not in scope

- **Prompts and model output.** This tool sends text you supply to a model you
  choose and reports what came back. It does not filter, moderate or sanitize
  either direction, and a model producing bad output is not a vulnerability here.
- **Running the server on a public interface.** `serve --host 0.0.0.0` exposes
  an unauthenticated API that can spend your API credits. That is your decision
  to make, and the default is the loopback address.
- **Third-party endpoints.** Where your data goes once it reaches a provider is
  governed by that provider.
