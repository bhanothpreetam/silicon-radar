"""Radar's mystery-first learning engine.

This package is intentionally separate from the existing news-driven
``intelligence.learning_track`` module.  The latter produces occasional cards
from current signals; this package owns the versioned textbook corpus,
learner-independent concept graph, and eventually the interactive case runtime.
"""

from .contracts import (
    CONTENT_LIFECYCLE,
    EDGE_TYPES,
    EXPERIENCE_TYPES,
    LEARNER_LIFECYCLE,
    ContractError,
    validate_case_bundle,
    validate_concept_graph,
)

__all__ = [
    "CONTENT_LIFECYCLE",
    "EDGE_TYPES",
    "EXPERIENCE_TYPES",
    "LEARNER_LIFECYCLE",
    "ContractError",
    "validate_case_bundle",
    "validate_concept_graph",
]
