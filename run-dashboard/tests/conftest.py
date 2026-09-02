"""Import and credential isolation for the standalone run-history application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

RUN_DASHBOARD_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUN_DASHBOARD_ROOT))

os.environ.setdefault("DASHBOARD_USERNAME", "synthetic-operator")
os.environ.setdefault("DASHBOARD_PASSWORD", "synthetic-dashboard-password")
os.environ.setdefault("DASHBOARD_SECRET_KEY", "synthetic-session-key-for-tests-only")
os.environ.setdefault("DASHBOARD_ENV", "test")
os.environ.setdefault("RUN_DASHBOARD_DB_MODE", "direct")
os.environ.setdefault(
    "RUN_DASHBOARD_DATABASE_URL",
    "postgresql://synthetic-monitor:synthetic-password@localhost/synthetic-dashboard",
)
os.environ.setdefault("RUN_DASHBOARD_EXPECTED_DATABASE", "synthetic-dashboard")
os.environ.setdefault("RUN_DASHBOARD_EXPECTED_ROLE", "synthetic-monitor")
