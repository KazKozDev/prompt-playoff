"""Run the CLI as `python -m prompt_playoff`.

The generated console script bakes an absolute interpreter path into its
shebang, so it breaks whenever the checkout or the venv moves. Module
execution keeps working.
"""

from __future__ import annotations

from prompt_playoff.entrypoint import main

if __name__ == "__main__":
    main()
