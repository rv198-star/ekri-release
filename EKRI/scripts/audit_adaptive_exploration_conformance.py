#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
import sys
EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
from ekri.adaptive_exploration_conformance import run_adaptive_exploration_conformance

if __name__ == "__main__":
    print(json.dumps(run_adaptive_exploration_conformance(), ensure_ascii=False, indent=2, sort_keys=True))
