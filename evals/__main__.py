"""Eval package entrypoint: uv run python -m evals"""

from evals.run_smoke import main

if __name__ == "__main__":
    raise SystemExit(main())
