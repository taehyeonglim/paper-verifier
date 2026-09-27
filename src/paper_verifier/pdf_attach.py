"""SourcePDF attachment — match each reference against a local paper library.

Only local-library matching is implemented; source_kind reserves an "unpaywall"
kind for a possible open-access lookup fallback.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class SourcePDF:
    id: str
    ref_id: str
    pdf_path: Optional[str] = None
    source_kind: str = "library-collected"  # library-collected / library-collected-yearfuzzy / ambiguous / not-found
    extracted_quote: str = ""
    span_page: str = ""
    extracted_at: Optional[str] = None


def _normalize(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", s).casefold() if ch.isalnum())


def _tokens(s: str) -> list[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", s).casefold())


def _contains_tokens(haystack: list[str], needle: list[str]) -> bool:
    return bool(needle) and any(
        haystack[i:i + len(needle)] == needle for i in range(len(haystack) - len(needle) + 1)
    )


def _doi_key(s: str) -> str:
    return re.sub(r"^https?://(?:dx\.)?doi\.org/", "", s.strip().casefold()).rstrip(".,;")


def _metadata(path: Path) -> dict[str, str]:
    """Read only local Markdown frontmatter, never DOI mentions in body citations."""
    if path.suffix != ".md":
        return {}
    try:
        with path.open(encoding="utf-8") as stream:
            text = stream.read(8192)
    except (OSError, UnicodeError):
        return {}
    if not text.startswith("---\n"):
        return {}
    frontmatter, separator, _ = text[4:].partition("\n---")
    if not separator:
        return {}
    return {
        key: value.strip().strip("\"'")
        for key, value in re.findall(r"^(doi|title):[ \t]*(.*)$", frontmatter, re.MULTILINE)
    }


def _select_pdf(
    first_author_last: str, year: int, library_root: Optional[Path],
    doi: Optional[str] = None, title: str = "",
) -> tuple[Optional[Path], str]:
    if library_root is None or not library_root.is_dir() or not _normalize(first_author_last):
        return None, "not-found"
    author_tokens = _tokens(first_author_last)
    target_doi = _doi_key(doi) if doi else ""
    title_tokens = set(_tokens(title)) - {"a", "an", "the", "of", "and", "in", "on", "for", "to", "with"}
    distinctive_title = len(title_tokens) >= 2 or any(len(t) >= 4 for t in title_tokens)
    candidates: list[tuple[tuple[int, int], Path, str]] = []
    for ext in ("*.md", "*.pdf"):
        for path in library_root.rglob(ext):
            if not path.is_file():
                continue
            name_tokens = _tokens(path.stem)
            metadata = _metadata(path)
            local_doi = _doi_key(metadata.get("doi", ""))
            # Explicit conflicting identifiers must not fall back to author/year.
            if target_doi and local_doi and local_doi != target_doi:
                continue
            doi_tokens = _tokens(target_doi)
            doi_match = bool(target_doi) and (
                local_doi == target_doi or name_tokens[-len(doi_tokens):] == doi_tokens
            )
            exact_year = str(year) in name_tokens
            neighboring_year = any(str(y) in name_tokens for y in (year - 1, year + 1))
            author_match = _contains_tokens(name_tokens, author_tokens)
            title_match = author_match and (exact_year or neighboring_year) and distinctive_title and (
                title_tokens <= set(name_tokens)
                or _normalize(title) == _normalize(metadata.get("title", ""))
            )
            if doi_match or title_match:
                rank, kind = (0 if doi_match else 1, 0), "library-collected"
            elif author_match and (exact_year or neighboring_year):
                rank = (2, 0 if exact_year else 1)
                kind = "library-collected" if exact_year else "library-collected-yearfuzzy"
            else:
                continue
            candidates.append((rank, path, kind))
    if not candidates:
        return None, "not-found"
    best_rank = min(rank for rank, _, _ in candidates)
    best = [(path, kind) for rank, path, kind in candidates if rank == best_rank]
    if len(best) != 1:
        return None, "ambiguous"
    return best[0]


def find_pdf_for_ref(
    first_author_last: str,
    year: int,
    library_root: Optional[Path] = None,
) -> Optional[Path]:
    """Find a unique author/year token match (exact year preferred over ±1).

    The legacy Optional[Path] API returns None for both missing and ambiguous
    matches. attach_pdfs additionally uses reference DOI/title metadata and
    exposes ambiguity through SourcePDF.source_kind.
    """
    path, _ = _select_pdf(first_author_last, year, library_root)
    return path


def attach_pdfs(refs: list, library_root: Optional[Path] = None) -> list[SourcePDF]:
    """Attempt a SourcePDF attachment for each ReferenceEntry."""
    results: list[SourcePDF] = []
    for idx, r in enumerate(refs, 1):
        pdf_path, kind = _select_pdf(
            r.first_author_last, r.year, library_root,
            doi=getattr(r, "doi", None), title=getattr(r, "title", ""),
        )
        if pdf_path:
            # Record whether the year matched exactly: a ±1-year fuzzy match may be a
            # different paper, so a distinct source_kind lets downstream verification
            # WARN instead of confidently PASSing. (Author + neighboring year alone,
            # with no DOI/title check, is not enough to certify a SourcePDF.)
            results.append(SourcePDF(
                id=f"pdf-{idx:03d}",
                ref_id=r.id,
                pdf_path=str(pdf_path.resolve()),
                source_kind=kind,
            ))
            r.pdf_attached = True
        else:
            results.append(SourcePDF(
                id=f"pdf-{idx:03d}",
                ref_id=r.id,
                pdf_path=None,
                source_kind=kind,
            ))
            r.pdf_attached = False
    return results


def to_records(pdfs: list[SourcePDF]) -> list[dict]:
    return [asdict(p) for p in pdfs]
