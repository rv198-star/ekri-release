#!/usr/bin/env python3
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from ekri.v110_gate import run_v110_release_gate
print(json.dumps(run_v110_release_gate(ROOT.parent), ensure_ascii=False, indent=2, sort_keys=True))
