#!/usr/bin/env python3
"""Entry point: python run_pipeline.py --image diagram.png  (same as python -m vision_pipeline)."""

from vision_pipeline.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
