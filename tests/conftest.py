"""Shared test configuration — ensures DB isolation across test modules."""

import os
import sys

# Ensure src is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set a default test DB path early, before any module imports src.database
os.environ.setdefault("SR_DB_PATH", "/tmp/test_superrecruit_default.db")
