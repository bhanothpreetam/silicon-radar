"""Versioned private-corpus ingestion for the learning engine."""

from .build import (
    CORPUS_SCHEMA_VERSION,
    CorpusBuildError,
    build_corpus,
)

__all__ = ["CORPUS_SCHEMA_VERSION", "CorpusBuildError", "build_corpus"]
