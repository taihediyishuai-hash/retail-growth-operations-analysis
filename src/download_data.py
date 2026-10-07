#!/usr/bin/env python3
"""Download and verify the public Online Retail II CSV."""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "data" / "raw" / "online_retail_II.csv"
URL = "https://huggingface.co/datasets/attik/Online-Retail-II-UCI/resolve/main/online_retail_II.csv"
EXPECTED_SHA256 = "32569a66f3842a82b0d8c4d63b263c5d98a76bde5d1f65c6c01bf457e541d3a9"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    if not DESTINATION.exists():
        print(f"Downloading {URL}")
        urllib.request.urlretrieve(URL, DESTINATION)
    else:
        print(f"Using existing file: {DESTINATION}")

    actual = sha256_of(DESTINATION)
    if actual != EXPECTED_SHA256:
        print(f"SHA-256 mismatch: {actual}", file=sys.stderr)
        return 2
    print(f"DATA_OK path={DESTINATION} sha256={actual} bytes={DESTINATION.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

