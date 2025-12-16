#!/usr/bin/env python3
"""Main entry point module for the launcher package."""

# Re-export main function from the root main.py
import sys
from pathlib import Path

# Add parent directory to path so we can import the root main module
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import main

if __name__ == "__main__":
    sys.exit(main())
