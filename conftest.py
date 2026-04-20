"""
conftest.py — pytest configuration and shared fixtures.
"""
import sys
import os

# Ensure the repo root is on sys.path so all modules are importable
sys.path.insert(0, os.path.dirname(__file__))

# Set required environment variables for the test environment so that modules
# (e.g. core.knowledge_ledger) that validate secrets at import time don't
# abort test collection.  These values are never used in real requests; they
# satisfy minimum-length requirements and provide a reproducible test key.
os.environ.setdefault(
    "DASHBOARD_SECRET_KEY",
    "ci-test-dashboard-secret-key-replace-in-production",
)
os.environ.setdefault(
    "CSRF_SECRET_KEY",
    "ci-test-csrf-secret-key-replace-in-production-00000",
)
