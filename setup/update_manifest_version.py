#!/usr/bin/env python
"""Write a copy of AirfoilSpline.manifest with version set to a requested value."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to source AirfoilSpline.manifest")
    parser.add_argument("--output", required=True, help="Path to generated AirfoilSpline.manifest")
    parser.add_argument("--version", required=True, help="Version string to write to manifest version")
    args = parser.parse_args()

    source = Path(args.input)
    target = Path(args.output)

    manifest = source.read_text(encoding="utf-8")
    updated, count = re.subn(r'("version"\s*:\s*)"[^"]+"', rf'\1"{args.version}"', manifest, count=1)
    if count != 1:
        raise RuntimeError("Could not find exactly one manifest version field in AirfoilSpline.manifest")

    target.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
