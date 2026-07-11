"""SourcePDF attachment — match each reference against a local paper library.

Only local-library matching is implemented; source_kind reserves an "unpaywall"
kind for a possible open-access lookup fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class SourcePDF:
    id: str
    ref_id: str
    pdf_path: Optional[str] = None
    source_kind: str = "library-collected"  # library-collected / unpaywall / manual-upload / not-found
    extracted_quote: str = ""
    span_page: str = ""
    extracted_at: Optional[str] = None


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_pdf_for_ref(
    first_author_last: str,
    year: int,
    library_root: Optional[Path] = None,
) -> Optional[Path]:
    """Search the local library for a PDF/fulltext matching first author + year.

    Matching heuristic: the lowercase file name must contain both the author's
    last name and the year (exact or ±1).
    """
    if library_root is None or not library_root.exists():
        return None
    target_author = _normalize(first_author_last)
    target_year = str(year)
    # Allow year ±1: the reference year and the library filename year can differ
    # by one (e.g. online-first vs print year, or a filing error).
    year_neighbors = {target_year, str(year - 1), str(year + 1)}
    candidates: list[tuple[int, Path]] = []
    # Both .md fulltext surrogates and .pdf originals are matched, under either
    # naming convention: `{YYYY}_{Author}_*` or `{Author}_{YYYY}_*`.
    for ext in ("*.md", "*.pdf"):
        for f in library_root.rglob(ext):
            name_norm = _normalize(f.stem)
            if target_author not in name_norm:
                continue
            # exact or ±1 year match
            matched_year = None
            for y in year_neighbors:
                if y in f.stem:
                    matched_year = y
                    break
            if matched_year is None:
                continue
            # Score: prefer an exact year, then .md, then shorter file names
            year_penalty = 0 if matched_year == target_year else 5
            ext_penalty = 0 if f.suffix == ".md" else 1
            score = year_penalty + ext_penalty + len(f.stem) * 0.01
            candidates.append((score, f))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def attach_pdfs(refs: list, library_root: Optional[Path] = None) -> list[SourcePDF]:
    """Attempt a SourcePDF attachment for each ReferenceEntry."""
    results: list[SourcePDF] = []
    for idx, r in enumerate(refs, 1):
        pdf_path = find_pdf_for_ref(r.first_author_last, r.year, library_root)
        if pdf_path:
            # Record whether the year matched exactly: a ±1-year fuzzy match may be a
            # different paper, so a distinct source_kind lets downstream verification
            # WARN instead of confidently PASSing. (Author + neighboring year alone,
            # with no DOI/title check, is not enough to certify a SourcePDF.)
            exact_year = str(r.year) in pdf_path.stem
            results.append(SourcePDF(
                id=f"pdf-{idx:03d}",
                ref_id=r.id,
                pdf_path=str(pdf_path.resolve()),
                source_kind="library-collected" if exact_year else "library-collected-yearfuzzy",
            ))
            r.pdf_attached = True
        else:
            results.append(SourcePDF(
                id=f"pdf-{idx:03d}",
                ref_id=r.id,
                pdf_path=None,
                source_kind="not-found",
            ))
            r.pdf_attached = False
    return results


def to_records(pdfs: list[SourcePDF]) -> list[dict]:
    return [asdict(p) for p in pdfs]
