"""JSONL append/read helpers for audit report artifacts (one JSON object per line)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Iterator


def append(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_all(path: Path, records: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for r in records:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_all(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fp:
        for lineno, line in enumerate(fp, 1):
            line = line.strip()
            if not line:
                continue
            # Skip malformed lines with a loud WARN instead of crashing the whole
            # pipeline: on truncated input an audit tool must neither succeed
            # silently nor die without context.
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                print(f"WARN: malformed JSONL skipped — {path.name}:{lineno} ({e})",
                      file=sys.stderr)
                continue
