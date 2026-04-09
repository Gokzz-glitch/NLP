"""
conftest.py — pytest configuration and shared fixtures.
"""
import sys
import os

# Ensure the repo root is on sys.path so all modules are importable
sys.path.insert(0, os.path.dirname(__file__))
