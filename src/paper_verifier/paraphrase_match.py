"""Paraphrase semantic matching (Phase 2).

Extracts the cited passage from the attached source (PDF via pdfplumber, or a
markdown fulltext surrogate) and delegates the semantic-equivalence judgment
to a local LLM CLI (see paper_verifier.llm). Everything around the judgment —
quote extraction, thresholds, purpose routing, fail-safes — is deterministic.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from paper_verifier import llm

# Active provider + timeout; rebound by paper_verifier.config.apply().
_PROVIDER: Optional[llm.LLMProvider] = llm.PRESETS["codex"]
_TIMEOUT: int = 120


@dataclass
class ParaphraseMatch:
    id: str
    citation_id: str
    ref_id: str
    pdf_path: Optional[str]
    paraphrase_text: str         # context_paraphrase from InTextCitation
    extracted_quote: str         # passage extracted from the source
    score: Optional[float]       # semantic equivalence 0~1 (LLM-judged)
    verifier: str = "paraphrase-llm"
    status: str = "PENDING"      # PASS / FAIL / PENDING / MANUAL
    citation_purpose: str = "background-cite"
    threshold_applied: Optional[float] = None  # None = evaluation skipped (MANUAL)


# Threshold policy per citation purpose
def threshold_for(purpose: str) -> Optional[float]:
    """Semantic-equivalence threshold for a citation purpose.

    Returns:
        - finding-cite: 0.85 strict (must match the cited paper's own claim)
        - method-cite / theory-cite: 0.40 loose (instrument/theory name-level match)
        - background-cite: None → LLM call skipped, status="MANUAL" (a generic
          acknowledgment is not a paraphrase-matching task, so scoring it would
          be meaningless)
    """
    if purpose == "finding-cite":
        return 0.85
    if purpose in ("method-cite", "theory-cite"):
        return 0.40
    return None  # background-cite


_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "their", "have", "been",
    "are", "was", "were", "may", "can", "not", "but", "all", "these", "those",
    "such", "which", "who", "what", "when", "where", "how", "more", "less",
    "than", "into", "over", "also", "they", "them", "its", "his", "her",
    "some", "any", "our", "your", "out", "off", "yet", "via", "per", "due",
    "between", "within", "across", "during", "while", "about", "above", "below",
    "would", "could", "should", "will", "shall", "must", "might", "does", "did",
    "had", "has", "having", "being", "other", "same", "each", "much",
    "many", "most", "few", "either", "neither", "both", "two", "three", "four",
}


def strip_frontmatter(text: str) -> str:
    """Strip a YAML frontmatter block (`---` ... `---`).

    Markdown fulltext surrogates typically open with a `---` YAML header.
    Text without one is returned unchanged.
    """
    if not text.startswith("---"):
        return text
    # Split on whole `---` lines; with maxsplit=2 the parts are [pre, yaml, body].
    parts = re.split(r"^---\s*$", text, flags=re.M, maxsplit=2)
    if len(parts) >= 3:
        return parts[2].lstrip("\n")
    return text


def extract_keywords(paraphrase: str, max_keywords: int = 8) -> list[str]:
    """Extract matching keywords from the paraphrase (4+ chars, stopwords excluded).

    Takes up to max_keywords in order of appearance, not frequency — academic
    paraphrases are already dense, so first-appearance order is a safe pick.
    """
    words = re.findall(r"\b[A-Za-z][A-Za-z\-]{3,}\b", paraphrase)
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        wl = w.lower()
        if wl in _STOPWORDS or wl in seen:
            continue
        seen.add(wl)
        result.append(w)
        if len(result) >= max_keywords:
            break
    return result


def find_keyword_window(
    text: str, keywords: list[str], window_size: int = 1000, min_matches: int = 1,
) -> Optional[str]:
    """Return the window_size stretch of text with the highest keyword-match count.

    Sliding-window search (stride = window_size//5), expanded by window_size//4
    on each side of the best position. Returns None when fewer than min_matches
    keywords hit, so the caller can fall back.
    """
    if not keywords or not text:
        return None
    text_lower = text.lower()
    kw_lower = [k.lower() for k in keywords]
    text_len = len(text_lower)
    if text_len <= window_size:
        return text  # short text: use it whole
    best_pos = -1
    best_count = 0
    stride = max(100, window_size // 5)
    for start in range(0, text_len - window_size + 1, stride):
        chunk = text_lower[start:start + window_size]
        count = sum(1 for kw in kw_lower if kw in chunk)
        if count > best_count:
            best_count = count
            best_pos = start
    if best_pos < 0 or best_count < min_matches:
        return None
    actual_start = max(0, best_pos - window_size // 4)
    actual_end = min(text_len, best_pos + window_size + window_size // 4)
    return text[actual_start:actual_end]


def extract_quote_from_pdf(
    pdf_path: Path,
    keywords: list[str] | None = None,
    page_hint: Optional[int] = None,
) -> str:
    """Extract the passage a citation refers to from the attached source.

    For a .md surrogate: skip the YAML frontmatter, then run the keyword-window
    search over the body; if no keyword matches, return the first 3000 chars
    (frontmatter already stripped). For a PDF, extract text with pdfplumber and
    run the same window search:
      - with page_hint (1-based), read that page ±1 — covers citations deep in
        the document, past any fixed front-page range;
      - without a hint, read the first 15 pages (a full scan of large PDFs
        costs too much).
    """
    if pdf_path.suffix == ".md":
        raw = pdf_path.read_text(encoding="utf-8", errors="ignore")
        text = strip_frontmatter(raw)
    else:
        try:
            import pdfplumber  # noqa
        except ImportError:
            return ""
        try:
            with pdfplumber.open(pdf_path) as pdf:
                total = len(pdf.pages)
                if page_hint is not None and 1 <= page_hint <= total:
                    center = page_hint - 1  # 0-based
                    lo, hi = max(0, center - 1), min(total, center + 2)
                    pages = [pdf.pages[i].extract_text() or "" for i in range(lo, hi)]
                else:
                    pages = [p.extract_text() or "" for p in pdf.pages[:15]]
            text = "\n".join(pages)
        except (OSError, ValueError, TypeError):
            return ""

    if keywords:
        window = find_keyword_window(text, keywords)
        if window:
            return window
    # Fallback: first 3000 chars of the (frontmatter-stripped) body
    return text[:3000]


def _llm_available() -> bool:
    return _PROVIDER is not None and shutil.which(_PROVIDER.argv[0]) is not None


def _provider_name() -> str:
    return _PROVIDER.name if _PROVIDER is not None else "llm"


# LLM-augmented citation classifier — heuristic first-pass + LLM 4-way reclassification.
_VALID_PURPOSES = ("finding-cite", "method-cite", "theory-cite", "background-cite")
_PURPOSE_RX = re.compile(r'"(?:purpose|classification)"\s*:\s*"([\w\-]+)"')
# Sentinel for classification failure (CLI missing / parse failure / call failure).
# It must NOT be a valid purpose: if "background-cite" doubled as the failure
# default, the augmented classifier could not tell failure from a real verdict,
# and a heuristic finding/method cite would silently demote to background —
# skipping its paraphrase evaluation entirely (fail-open). A distinct sentinel
# lets the caller preserve the heuristic result instead (fail-safe).
_CLASSIFY_UNKNOWN = "unknown"


def dispatch_classify_citation(
    paraphrase: str, raw_citation: str, citation_type: str = "parenthetical",
) -> tuple[str, str]:
    """LLM call — citation 4-way classification.

    Returns (purpose ∈ _VALID_PURPOSES, raw_response) on success, or
    (_CLASSIFY_UNKNOWN, reason) on failure (CLI missing / parse / call error).
    Failures return a sentinel rather than a valid purpose so the caller
    (classify_citation_purpose_augmented) preserves the heuristic result.
    """
    if not _llm_available():
        return _CLASSIFY_UNKNOWN, f"{_provider_name()} CLI not available — heuristic preserved (fail-safe)"
    prompt = (
        "Classify this in-text citation by its rhetorical purpose. Return ONLY a JSON object: "
        '{"purpose": "finding-cite|method-cite|theory-cite|background-cite", "reason": "short"}\n\n'
        "Definitions:\n"
        "- finding-cite: the sentence reports a specific empirical finding/result of the cited paper "
        "(e.g., 'Klepsch et al. (2017) showed that X correlates with Y').\n"
        "- method-cite: the sentence uses an instrument/scale/tool/algorithm from the cited paper "
        "(e.g., 'using the lme4 package (Bates et al., 2015)').\n"
        "- theory-cite: the sentence references a theory/framework/principle by name "
        "(e.g., 'Cognitive Theory of Multimedia Learning (CTML; Mayer, 2009)').\n"
        "- background-cite: general background acknowledgment, not a specific finding/method/theory "
        "(e.g., 'AI digital humans have been studied in education (Smith, 2023)').\n\n"
        f"Sentence: {paraphrase[:600]}\n"
        f"Citation raw text: {raw_citation[:120]}\n"
        f"Citation form: {citation_type}\n"
    )
    try:
        result = subprocess.run(
            list(_PROVIDER.argv),
            input=prompt, text=True, capture_output=True, timeout=_TIMEOUT,
        )
        out = result.stdout[:2000]
        m = _PURPOSE_RX.search(out)
        if m and m.group(1) in _VALID_PURPOSES:
            return m.group(1), out
        # Parse failure → sentinel (preserve heuristic; do not demote to background).
        rc = getattr(result, "returncode", 0)
        if rc != 0:
            return _CLASSIFY_UNKNOWN, f"{_provider_name()} rc={rc}: {out[:200]}"
        return _CLASSIFY_UNKNOWN, out
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as e:
        return _CLASSIFY_UNKNOWN, f"{_provider_name()} call failed: {e}"


def classify_citation_purpose_augmented(
    paraphrase: str,
    citation_type: str,
    raw_text: str,
    heuristic_purpose: str,
    llm_callable=None,
    cache: Optional[dict] = None,
) -> tuple[str, str]:
    """Heuristic first-pass + LLM resolution of the ambiguous zone.

    Args:
        heuristic_purpose: result of the deterministic first-pass classifier
        llm_callable: (paraphrase, raw, citation_type) -> (purpose, raw_response);
                      defaults to dispatch_classify_citation
        cache: (paraphrase[:200], raw_text[:120]) -> purpose, injected by the call site

    Returns: (final_purpose, classifier_used) with
        classifier_used ∈ {"heuristic", "llm-cached", "llm", "llm-fallback"}

    Only method-cite/finding-cite are delegated: spot-checks showed the
    heuristic is accurate for background/theory cites but over-classifies
    method/finding. The cache avoids repeat calls when the same paraphrase
    cites the same paper multiple times.
    """
    if heuristic_purpose in ("background-cite", "theory-cite"):
        return heuristic_purpose, "heuristic"
    # method-cite or finding-cite — the known over-classification zone
    key = (paraphrase[:200], raw_text[:120])
    if cache is not None and key in cache:
        return cache[key], "llm-cached"
    if llm_callable is None:
        llm_callable = dispatch_classify_citation
    llm_purpose, _raw = llm_callable(paraphrase, raw_text, citation_type)
    if llm_purpose not in _VALID_PURPOSES:
        # Classification failed — preserve the heuristic result.
        if cache is not None:
            cache[key] = heuristic_purpose
        return heuristic_purpose, "llm-fallback"
    if cache is not None:
        cache[key] = llm_purpose
    return llm_purpose, "llm"


def _first_json_object(text: str) -> dict:
    """Decode the first balanced object, tolerating fences and surrounding prose."""
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object in response")
    depth = 0
    in_string = escaped = False
    for end in range(start, len(text)):
        ch = text[end]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:end + 1])
    raise ValueError("incomplete JSON object in response")


def dispatch_paraphrase_check(paraphrase: str, original_quote: str) -> tuple[float, str]:
    """LLM call — semantic-equivalence score for paraphrase vs original quote.

    Returns (score 0~1, raw_response); (-1.0, reason) when the provider is
    unavailable or the call/parse fails (callers route -1.0 to FAIL with no score).
    """
    if not _llm_available():
        return -1.0, f"{_provider_name()} CLI not available — semantic check skipped"
    prompt = (
        "Compare these two passages for semantic equivalence.\n"
        "Return a single JSON object: {\"score\": 0.0-1.0, \"reason\": \"...\"}.\n"
        "score 1.0 = same claim, 0.5 = related but different claim, 0.0 = unrelated.\n\n"
        f"PARAPHRASE: {paraphrase}\n\n"
        f"ORIGINAL: {original_quote}\n"
    )
    try:
        result = subprocess.run(
            list(_PROVIDER.argv),
            input=prompt, text=True, capture_output=True, timeout=_TIMEOUT,
        )
        out = result.stdout
        # Never trust stdout after an abnormal exit — stale/partial JSON there
        # must not become a valid score.
        rc = getattr(result, "returncode", 0)
        if rc != 0:
            return -1.0, f"{_provider_name()} rc={rc}: {out[:300]}"
        score = _first_json_object(out).get("score")
        # JSON booleans/strings are not numeric scores. Preserve exponent syntax
        # (1e-3 is 0.001) and reject non-finite/out-of-range values.
        if type(score) not in (int, float):
            return -1.0, f"score is not a JSON number: {score!r} — {out[:300]}"
        if not (0.0 <= score <= 1.0) or not math.isfinite(score):
            return -1.0, f"score out of range [0,1]: {score} — {out[:300]}"
        return float(score), out[:500]
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as e:
        return -1.0, f"{_provider_name()} call failed: {e}"


def match_paraphrases(
    citations: list,
    pdfs: list,
    refs: list,
    augment_with_llm: bool = True,
) -> list[ParaphraseMatch]:
    """For each in-text citation: extract the source quote + judge equivalence.

    Purpose-based thresholds:
      - finding-cite: 0.85 strict (must match the cited paper's claim)
      - method-cite / theory-cite: 0.40 loose (instrument/theory name-level match)
      - background-cite: evaluation skipped → MANUAL (a generic acknowledgment
        is not a paraphrase-matching task)

    With augment_with_llm=True, cites the heuristic classified as
    method/finding are reclassified by the LLM (the heuristic's known
    over-classification zone); a demotion to background skips the paraphrase
    call — cutting cost and FAIL inflation at once. The cache deduplicates
    repeat (paraphrase, raw) pairs.
    """
    pdf_by_ref = {p.ref_id: p for p in pdfs}
    results: list[ParaphraseMatch] = []
    llm_cache: dict = {} if augment_with_llm else None
    for idx, c in enumerate(citations, 1):
        if c.ref_id is None or c.ref_id not in pdf_by_ref:
            continue
        pdf = pdf_by_ref[c.ref_id]
        if not pdf.pdf_path:
            continue
        # pdf_attach stores absolute paths; a relative path (e.g. from an
        # externally produced JSONL) is interpreted against the current directory.
        pdf_path = Path(pdf.pdf_path)
        if not pdf_path.exists():
            continue
        heuristic_purpose = getattr(c, "citation_purpose", "background-cite")
        if augment_with_llm:
            purpose, _classifier = classify_citation_purpose_augmented(
                paraphrase=c.context_paraphrase,
                citation_type=getattr(c, "citation_type", "parenthetical"),
                raw_text=getattr(c, "raw_text", ""),
                heuristic_purpose=heuristic_purpose,
                cache=llm_cache,
            )
        else:
            purpose = heuristic_purpose
        threshold = threshold_for(purpose)

        # background-cite: skip the LLM call (cost + not a paraphrase task)
        if threshold is None:
            results.append(ParaphraseMatch(
                id=f"para-{idx:04d}",
                citation_id=c.id,
                ref_id=c.ref_id,
                pdf_path=str(pdf_path),
                paraphrase_text=c.context_paraphrase[:300],
                extracted_quote="(background-cite — evaluation skipped by policy)",
                score=None,
                verifier=f"paraphrase-{_provider_name()}",
                status="MANUAL",
                citation_purpose=purpose,
                threshold_applied=None,
            ))
            continue

        keywords = extract_keywords(c.context_paraphrase)
        quote = extract_quote_from_pdf(pdf_path, keywords=keywords)
        score = None
        if quote.strip():
            score, _reason = dispatch_paraphrase_check(
                c.context_paraphrase, quote[:2000],
            )
        if (type(score) not in (int, float) or not 0.0 <= score <= 1.0
                or not math.isfinite(score)):
            score = None
            status = "FAIL"
        elif score >= threshold:
            status = "PASS"
        else:
            status = "FAIL"
        results.append(ParaphraseMatch(
            id=f"para-{idx:04d}",
            citation_id=c.id,
            ref_id=c.ref_id,
            pdf_path=str(pdf_path),
            paraphrase_text=c.context_paraphrase[:300],
            extracted_quote=quote[:300],
            score=score,
            verifier=f"paraphrase-{_provider_name()}",
            status=status,
            citation_purpose=purpose,
            threshold_applied=threshold,
        ))
    return results


def to_records(matches: list[ParaphraseMatch]) -> list[dict]:
    return [asdict(m) for m in matches]
