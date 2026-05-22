"""Shared pytest configuration for the rfq-normalizer test suite.

Adds the skill's scripts/ folder to sys.path so tests can `import cache`,
`import credentials`, etc. without packaging the skill.
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
