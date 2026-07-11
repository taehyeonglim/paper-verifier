"""Shared test fixtures.

The library ships with intentionally EMPTY domain knowledge (fail-safe
defaults). Unit tests exercise realistic behavior through a demo profile
applied by an autouse fixture; it is restored to library defaults after each
test. Tests that need the pristine defaults call
``config.apply(config.VerifierConfig())`` at their start.

The demo profile mirrors the real study this tool was battle-tested on
(anonymized): 8 DVs, two conditions (HQ/LQ), reliability and sample-size
ground truth. One Korean alias ("조작점검") is kept on purpose as a
regression case for the multilingual row-label mapping.
"""
from __future__ import annotations

import pytest

from paper_verifier import config

DEMO_PROFILE = config.VerifierConfig(
    dv_keywords={
        "manipulation_check": ["uncanniness", "manipulation check", "perceived eeriness"],
        "ECL": ["ECL", "extraneous cognitive load"],
        "ICL": ["ICL", "intrinsic cognitive load"],
        "GCL": ["GCL", "germane cognitive load"],
        "learning": ["Learning accuracy", "learning accuracy", "learning test"],
        "ET_face_dwell": ["face dwell", "Face Dwell", "avatar's face"],
        "ET_slide_dwell": ["slide dwell", "Slide Dwell", "slide content"],
        "ET_face_fix": ["face fix", "fix count", "Fixation count", "fixation count"],
    },
    dv_aliases={
        "Manipulation Check": "manipulation_check",
        "조작점검": "manipulation_check",  # multilingual alias regression case
        "ECL": "ECL",
        "ICL": "ICL",
        "GCL": "GCL",
        "Learning": "learning",
        "ET Face Dwell": "ET_face_dwell",
        "ET Slide Dwell": "ET_slide_dwell",
        "ET Fix Count": "ET_face_fix",
    },
    alpha={
        "manipulation_check": 0.689,
        "ECL": 0.938,
        "ICL": 0.428,
        "GCL": 0.710,
        "learning_A": 0.010,
        "learning_B": 0.582,
    },
    n={"analytic": 38, "collected": 40, "excluded": 2, "power": 34, "pilot": 8},
    condition_labels=("HQ", "LQ"),
    percent_dvs=frozenset({"learning", "ET_face_dwell", "ET_slide_dwell"}),
    modifier_keywords=(
        "topic", "order", "interaction", "×", "approached significance",
        "topic main effect", "order interactions", "× topic", "× order",
        "spearman", "correlation between",
    ),
)


@pytest.fixture(autouse=True)
def demo_profile():
    config.apply(DEMO_PROFILE)
    yield
    config.apply(config.VerifierConfig())
