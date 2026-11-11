"""Entry point kept for `python -m evals.run_eval`. The implementation is in evals/suite.py."""
from __future__ import annotations

import sys

from .suite import main, run_suite, render_tables  # noqa: F401

if __name__ == "__main__":
    sys.exit(main())
