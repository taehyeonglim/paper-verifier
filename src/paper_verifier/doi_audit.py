"""DOI/citation audit — parse an APA 7 reference list and match in-text citations.

Fully offline and deterministic: reference-list parsing plus in-text citation
matching is complete on its own. DOI strings are extracted and recorded as
present, but no registry lookup is performed — see the "doi-present" status.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# APA 7 entry pattern: `Author, A., & Author, B. (YYYY). Title. *Journal*, ...`
_ENTRY_AUTHOR_YEAR = re.compile(
    r"^([A-Z][^()]+?)\s*\((\d{4}[a-z]?)\)\.\s*([^.]+(?:\.\s*[^.]+)*?)\.\s*",
    re.MULTILINE,
)

_DOI_PATTERN = re.compile(r"https?://(?:dx\.)?doi\.org/(\S+?)(?:\s|$)")


@dataclass
class ReferenceEntry:
    id: str                  # slug like "Klepsch2017"
    raw_text: str            # full entry text
    authors_raw: str         # "Klepsch, M., Schmitz, F., & Seufert, T."
    first_author_last: str   # "Klepsch"
    year: int
    title: str
    year_suffix: str = ""    # "a"/"b"/"" — disambiguates same author-year refs (2024a/2024b)
    journal: str = ""
    doi: Optional[str] = None
    status: str = "draft"    # doi-present / tbd-doi / software / draft (never "verified" offline)
    crossref_match: str = "unchecked"
    pdf_attached: bool = False
    notes: str = ""


@dataclass
class InTextCitation:
    id: str                  # cite-NNNN
    manuscript_id: str
    section: str
    line: int
    raw_text: str            # "(Klepsch et al., 2017)"
    citation_type: str       # parenthetical / narrative
    first_author_last: str
    year: int
    year_suffix: str = ""    # "a"/"b"/"" — distinguishes 2024a/2024b
    ref_id: Optional[str] = None  # resolves_to (after match)
    context_paraphrase: str = ""
    year_alt: Optional[int] = None  # `Mori (1970/2012)` alternative year (republication)
    citation_purpose: str = "background-cite"  # finding/method/theory/background-cite


# ─── ReferenceEntry parsing ─────────────────────────────────────────────


def _slugify(first_author_last: str, year: int) -> str:
    return f"{first_author_last.replace(' ', '').replace('-', '')}{year}"


def _extract_first_author_last(authors_raw: str) -> str:
    """`Klepsch, M., Schmitz, F., & Seufert, T.` → `Klepsch`."""
    s = authors_raw.strip()
    # Take everything before the first comma
    first_chunk = s.split(",", 1)[0].strip()
    # If still has 'and' / '&', cut there
    first_chunk = re.split(r"\s+(?:&|and)\s+", first_chunk)[0]
    return first_chunk


def parse_references(refs_md: Path) -> list[ReferenceEntry]:
    """Parse an APA 7 references markdown file into ReferenceEntry records."""
    text = refs_md.read_text(encoding="utf-8")
    # Strip YAML frontmatter
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2]
    # Strip heading (#) lines
    text = re.sub(r"^#.*$", "", text, flags=re.MULTILINE)
    # Split into entries on blank lines. Blockquote-only chunks (editorial notes)
    # are skipped; a blockquote trailing an entry inside its chunk becomes `notes`.
    chunks = re.split(r"\n\s*\n", text)
    entries: list[ReferenceEntry] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or chunk.startswith(">"):
            continue
        # Try the author-year entry pattern
        m = _ENTRY_AUTHOR_YEAR.search(chunk)
        if not m:
            continue
        authors_raw = m.group(1).strip()
        _ym = re.match(r"(\d{4})([a-z]?)", m.group(2))
        year = int(_ym.group(1))
        year_suffix = _ym.group(2)  # "a"/"b"/"" — keeps same author-year refs distinct
        title = m.group(3).strip()

        first_author_last = _extract_first_author_last(authors_raw)
        slug = _slugify(first_author_last, year) + year_suffix  # Smith2024a (no key collision)

        # Extract the DOI, stripping trailing punctuation (e.g. the period that ends a
        # reference entry). The lazy \S+? used to absorb that final '.' and capture
        # "10.9999/wrong." — dots are legitimate inside a DOI (10.1000/xyz.123), but
        # trailing sentence punctuation is not part of it, so rstrip removes only the end.
        doi_match = _DOI_PATTERN.search(chunk)
        doi = doi_match.group(1).rstrip(".,;") if doi_match else None

        # Journal: the `*Journal*, ...` pattern after the title
        journal = ""
        jm = re.search(r"\*([^*]+)\*\s*,", chunk[m.end():])
        if jm:
            journal = jm.group(1).strip()

        # Infer status
        chunk_low = chunk.lower()
        if "[tbd-doi" in chunk_low or "tbd:" in chunk_low:
            status = "tbd-doi"
        elif doi:
            # Only the presence of a DOI string is confirmed here — never "verified",
            # which would require a registry lookup. "doi-present" keeps the audit
            # artifact from overclaiming. (True DOI↔paper verification needs a
            # CrossRef/DataCite/doi.org query — a separate, network-bound step.)
            status = "doi-present" if "doi.org" in chunk else "draft"
        elif any(kw in title.lower() for kw in ("software", "package", "r:", "python")) or \
             "r core team" in authors_raw.lower():
            status = "software"
        else:
            status = "draft"

        # Notes: blockquote trailing the entry
        notes = ""
        nm = re.search(r"^>\s*(.+)", chunk, flags=re.MULTILINE)
        if nm:
            notes = nm.group(1).strip()

        entries.append(ReferenceEntry(
            id=slug,
            raw_text=chunk[:300],
            authors_raw=authors_raw,
            first_author_last=first_author_last,
            year=year,
            title=title,
            year_suffix=year_suffix,
            journal=journal,
            doi=doi,
            status=status,
            notes=notes,
        ))
    return entries


# ─── Citation purpose classification ────────────────────────────────────

# Finding-cite: verbs asserting the cited paper's own result/finding.
# `reported` is deliberately absent — it fires on phrases like "self-reported
# outcomes" far too often (false positives). `noted` is also common in background
# prose but stays for now; drop it if spot-checks show excessive false positives.
_FINDING_VERBS = re.compile(
    r"\b(?:found|showed|demonstrated|observed|indicated|"
    r"revealed|concluded|documented|established|noted|identified|"
    r"suggested|argued|proposed|claimed|posited)\b",
    re.IGNORECASE,
)
# Method-cite: instrument/tool usage markers
_METHOD_VERBS = re.compile(
    r"\b(?:used|measured|assessed|administered|applied|computed|"
    r"operationalized|calculated|estimated|derived|adapted|"
    r"following|fitted|analyzed\s+with|using)\b",
    re.IGNORECASE,
)
_METHOD_NOUNS = re.compile(
    r"\b(?:instrument|scale|questionnaire|package|software|library|"
    r"toolkit|procedure|protocol|method|technique|algorithm|"
    r"factor|item|model|test|estimator|tool|measure)s?\b",
    re.IGNORECASE,
)
# Theory-cite: theory/framework nouns, or the (Abbrev; Author, Year) form
_THEORY_NOUNS = re.compile(
    r"\b(?:theory|framework|hypothesis|principle|account|paradigm|approach)\b",
    re.IGNORECASE,
)
_ABBREV_PREFIX = re.compile(r"\(([A-Z]{2,}|[A-Z][A-Za-z]+);\s*[A-Z]")


def classify_citation_purpose(paraphrase: str, citation_type: str, raw_text: str = "") -> str:
    """Heuristic 4-way citation-purpose classification.

      - finding-cite: cites another paper's finding/result (strict paraphrase check)
      - method-cite: instrument/tool usage (loose threshold — name-level match)
      - theory-cite: theory/framework reference (loose threshold)
      - background-cite: default, generic background (paraphrase evaluation skipped → MANUAL)

    Heuristic limits: short or ambiguous context falls back to background-cite, and
    false positives/negatives are possible — see classify_citation_purpose_augmented
    in paraphrase_match for the LLM-assisted refinement.
    """
    # A theory-abbreviation prefix in the raw text wins first,
    # e.g. `(CTML; Mayer, 2009)`, `(SVT; Smith, 2010)`.
    if _ABBREV_PREFIX.search(raw_text):
        return "theory-cite"

    has_method_verb = bool(_METHOD_VERBS.search(paraphrase))
    has_method_noun = bool(_METHOD_NOUNS.search(paraphrase))
    if has_method_verb and has_method_noun:
        return "method-cite"

    # Theory keyword match (theory/framework/hypothesis named in the context)
    if _THEORY_NOUNS.search(paraphrase):
        return "theory-cite"

    # Finding indicator (explicit finding verb)
    if _FINDING_VERBS.search(paraphrase):
        return "finding-cite"

    return "background-cite"


# ─── InTextCitation extraction ──────────────────────────────────────────

# Capture the whole parenthetical, then split sub-citations on `;` — a single
# `(Klepsch et al., 2017)` and a multi `(Pataranutaporn et al., 2022; Xu et al., 2024)`
# take the same path.
_PAREN_OUTER = re.compile(r"\(([^()]+)\)")

# Sub-citation: optional abbrev prefix (`CTML;`) + author + (et al. | & X | possessive) + `,` + year
# `(Mori, 1970/2012)` republication years — both primary and alternative are captured
_SUB_CITE = re.compile(
    r"^(?:[A-Z][\w\-]+;\s*)?"               # optional `Abbrev;` prefix (already split by ;, but defensive)
    r"([A-Z][\w\-]+)"                        # primary author last name (capture)
    r"(?:\s+et\s+al\.|[^,;()]{0,80}?)"       # `et al.` or any non-boundary chars (lazy)
    r"\s*,\s*(\d{4}[a-z]?)"                  # primary year (capture 2)
    r"(?:/(\d{4}[a-z]?))?"                   # optional alternative year (capture 3)
    r"\b"                                     # word boundary (allows `, p. 14` tail)
)

# Narrative: `Klepsch et al. (2017)`, `Klepsch et al.'s (2017)`, `Klepsch and Schmitz (2017)`, `Klepsch (2017)`, `Mori (1970/2012)`
_NARRATIVE_CITE = re.compile(
    r"\b([A-Z][\w\-]+)(?:\s+et\s+al\.(?:'s)?|\s+(?:and|&)\s+[A-Z][\w\-]+(?:'s)?|(?:'s)?)?\s*"
    r"\((\d{4}[a-z]?)(?:/(\d{4}[a-z]?))?\)"  # primary year (cap 2) + optional /alt (cap 3)
)


def _split_paren_sub_citations(content: str) -> list[tuple[str, int, str, Optional[int], str]]:
    """Split parenthetical content on `;` into (author, year, year_suffix, year_alt, sub_raw).

    e.g. `Pataranutaporn et al., 2022; Xu et al., 2024`
      → [("Pataranutaporn", 2022, "", None, ...), ...]
    `Mori, 1970/2012` → [("Mori", 1970, "", 2012, ...)] (republication year alternative)
    `Smith, 2024a` → [("Smith", 2024, "a", None, ...)] (year suffix preserved)
    """
    results: list[tuple[str, int, str, Optional[int], str]] = []
    for sub in content.split(";"):
        sub_strip = sub.strip()
        if not sub_strip:
            continue
        m = _SUB_CITE.match(sub_strip)
        if m:
            _ym = re.match(r"(\d{4})([a-z]?)", m.group(2))
            year = int(_ym.group(1))
            year_suffix = _ym.group(2)  # "a"/"b" suffix preserved
            year_alt = int(re.match(r"\d{4}", m.group(3)).group(0)) if m.group(3) else None
            results.append((m.group(1), year, year_suffix, year_alt, sub_strip))
    return results


def extract_citations(
    text: str,
    manuscript_id: str,
    section: str,
    starting_idx: int = 1,
) -> list[InTextCitation]:
    citations: list[InTextCitation] = []
    next_idx = starting_idx
    for line_num, line in enumerate(text.splitlines(), 1):
        # Skip blockquotes: editorial TODO notes or quoted excerpts from other
        # papers. Either way the line is not the manuscript's own prose, so it
        # must stay out of paraphrase evaluation.
        if line.lstrip().startswith(">"):
            continue
        # Whole-parenthetical capture + sub-citation split (+ year_alt + citation_purpose)
        for m_outer in _PAREN_OUTER.finditer(line):
            paren_full = m_outer.group(0)  # whole paren — input for abbrev-prefix classification
            for author, year, year_suffix, year_alt, sub_raw in _split_paren_sub_citations(m_outer.group(1)):
                purpose = classify_citation_purpose(
                    paraphrase=line.strip(),
                    citation_type="parenthetical",
                    raw_text=paren_full,
                )
                citations.append(InTextCitation(
                    id=f"cite-{next_idx:04d}",
                    manuscript_id=manuscript_id,
                    section=section,
                    line=line_num,
                    raw_text=f"({sub_raw})",
                    citation_type="parenthetical",
                    first_author_last=author,
                    year=year,
                    year_suffix=year_suffix,
                    year_alt=year_alt,
                    context_paraphrase=line.strip(),
                    citation_purpose=purpose,
                ))
                next_idx += 1
        for m in _NARRATIVE_CITE.finditer(line):
            _ym = re.match(r"(\d{4})([a-z]?)", m.group(2))
            year = int(_ym.group(1))
            year_suffix = _ym.group(2)  # "a"/"b" suffix preserved
            year_alt = int(re.match(r"\d{4}", m.group(3)).group(0)) if m.group(3) else None
            purpose = classify_citation_purpose(
                paraphrase=line.strip(),
                citation_type="narrative",
                raw_text=m.group(0),
            )
            citations.append(InTextCitation(
                id=f"cite-{next_idx:04d}",
                manuscript_id=manuscript_id,
                section=section,
                line=line_num,
                raw_text=m.group(0),
                citation_type="narrative",
                first_author_last=m.group(1),
                year=year,
                year_suffix=year_suffix,
                year_alt=year_alt,
                context_paraphrase=line.strip(),
                citation_purpose=purpose,
            ))
            next_idx += 1
    return citations


# ─── Matching + orphan/dangling ─────────────────────────────────────────


def link_citations(
    citations: list[InTextCitation],
    refs: list[ReferenceEntry],
) -> tuple[list[InTextCitation], list[str], list[str]]:
    """Match citations to refs. Returns (linked citations, orphan ref_ids, dangling cite_ids).

    orphan: listed in the references but never cited in the body
    dangling: cited in the body but missing from the reference list
    """
    # Key by (author, year, suffix) so 2024a/2024b stay distinct. Ignoring the suffix
    # made same-(author, year) refs collide: the later ref overwrote the earlier one,
    # producing spurious orphans and mismatched citations.
    ref_index: dict[tuple[str, int, str], ReferenceEntry] = {
        (r.first_author_last.lower(), r.year, r.year_suffix): r for r in refs
    }
    # Fallback index for bare (suffix-less) citations: all refs per (author, year).
    by_author_year: dict[tuple[str, int], list[ReferenceEntry]] = {}
    for r in refs:
        by_author_year.setdefault((r.first_author_last.lower(), r.year), []).append(r)

    def _match(author: str, year: int, suffix: str) -> Optional[ReferenceEntry]:
        exact = ref_index.get((author, year, suffix))
        if exact is not None:
            return exact
        # A bare citation (suffix="") matches only when exactly one ref has that
        # author-year. With several (2024a/2024b), a suffix-less citation is ambiguous
        # and is deliberately left unmatched rather than guessed.
        if not suffix:
            cand = by_author_year.get((author, year), [])
            if len(cand) == 1:
                return cand[0]
        return None

    cited_ref_ids: set[str] = set()
    dangling: list[str] = []
    for c in citations:
        author = c.first_author_last.lower()
        # If the primary year misses, fall back to year_alt (`Mori 1970/2012` → ref Mori2012)
        r = _match(author, c.year, c.year_suffix)
        if r is None and c.year_alt is not None:
            r = _match(author, c.year_alt, c.year_suffix)
        if r is not None:
            c.ref_id = r.id
            cited_ref_ids.add(r.id)
        else:
            dangling.append(c.id)
    orphans = [r.id for r in refs if r.id not in cited_ref_ids]
    return citations, orphans, dangling


def to_ref_records(refs: list[ReferenceEntry]) -> list[dict]:
    return [asdict(r) for r in refs]


def to_cite_records(cites: list[InTextCitation]) -> list[dict]:
    return [asdict(c) for c in cites]
