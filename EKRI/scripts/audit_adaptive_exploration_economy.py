#!/usr/bin/env python3
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
from ekri.adaptive_exploration_economy import run_adaptive_exploration_economy_audit
print(json.dumps(run_adaptive_exploration_economy_audit(ROOT.parent), ensure_ascii=False, indent=2, sort_keys=True))
