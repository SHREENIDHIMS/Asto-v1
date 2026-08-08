"""Integration test fixtures.

Adds the repository root to sys.path so integration tests can import the
``evaluation`` package (repo-root level) — the same layout the benchmark
runner assumes.
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BACKEND_DIR.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
