"""Manuscript ingestion — .md files → Manifest + sha256.

Files are pinned by sha256 so every report is traceable to the exact
manuscript bytes it audited.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class Manuscript:
    id: str
    file_path: str  # absolute path
    section: str
    version: str
    sha256: str
    word_count: int
    last_modified: str


# File-name substring → section label. First match wins; combined hints are
# checked first so "proceedings_v1.md" is not mislabeled by a section hint.
_COMBINED_HINTS: tuple[str, ...] = ("proceeding", "combined", "full")
_SECTION_HINTS: tuple[tuple[str, str], ...] = (
    ("introduction", "intro"),
    ("intro", "intro"),
    ("method", "methods"),
    ("result", "results"),
    ("discussion", "discussion"),
    ("conclusion", "conclusion"),
    ("reference", "refs"),
    ("refs", "refs"),
    ("bibliography", "refs"),
)


def infer_section(path: Path) -> str:
    """Best-effort section label from the file name.

    "combined" marks a full-manuscript file that duplicates the individual
    sections (the pipeline skips it for claim/citation extraction when
    sections are present, to avoid double counting). "refs" marks the
    reference list (skipped for in-text citation extraction). Anything
    unrecognized is "body".
    """
    stem = path.stem.lower()
    for hint in _COMBINED_HINTS:
        if hint in stem:
            return "combined"
    for hint, section in _SECTION_HINTS:
        if hint in stem:
            return section
    return "body"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def ingest_file(path: Path, section: str | None = None, version: str = "v1",
                idx: int = 1) -> Manuscript:
    path = Path(path).resolve()
    text = path.read_text(encoding="utf-8")
    word_count = len(text.split())
    mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    return Manuscript(
        id=f"mss-{idx:03d}",
        file_path=str(path),
        section=section if section is not None else infer_section(path),
        version=version,
        sha256=sha256_of(path),
        word_count=word_count,
        last_modified=mtime,
    )


def ingest_files(paths: list[Path], version: str = "v1") -> list[Manuscript]:
    """Ingest the given manuscript files in order (sections inferred from names)."""
    return [ingest_file(p, None, version, idx) for idx, p in enumerate(paths, 1)]


def to_manifest(manuscripts: list[Manuscript], project: str = "manuscript") -> dict:
    return {
        "project": project,
        "audit_target": ", ".join(Path(m.file_path).name for m in manuscripts) or "empty",
        "ingested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": [asdict(m) for m in manuscripts],
        "manifest_sha256_prefix8": (
            hashlib.sha256(
                "".join(m.sha256 for m in manuscripts).encode("utf-8")
            ).hexdigest()[:8]
            if manuscripts else "empty"
        ),
    }
