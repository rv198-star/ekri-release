#!/usr/bin/env python3
"""Run the WFF v1.8 P2 physical Core extraction audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


EKRI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EKRI_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from ekri.core_extraction import (  # noqa: E402
    CoreExtractionError,
    run_core_extraction_audit,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the physical wff-core package against the accepted P1 contract."
    )
    parser.add_argument("--repository-root", default=str(EKRI_ROOT.parent))
    parser.add_argument("--target-ref", default="HEAD")
    parser.add_argument("--no-write", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = run_core_extraction_audit(
            args.repository_root,
            target_ref=args.target_ref,
            write_outputs=not args.no_write,
        )
    except CoreExtractionError as exc:
        print(
            json.dumps(
                {"status": "blocked", "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
