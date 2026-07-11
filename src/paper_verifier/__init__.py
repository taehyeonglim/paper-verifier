"""paper-verifier — deterministic manuscript audit.

Cross-checks the statistical claims in a manuscript against your own
pre-computed analysis outputs, and audits reference/citation integrity
(reference list ↔ in-text citations ↔ attached source PDFs).

Determinism first: Python parses, matches, and diffs; an LLM is only ever
consulted for paraphrase semantic matching (Phase 2, opt-in) — never for
the numbers.
"""

__version__ = "0.1.0"
