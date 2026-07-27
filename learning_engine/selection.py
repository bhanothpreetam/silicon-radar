"""Prerequisite-gated random decks for Frontier and Cold Probe selection."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Protocol

from learning_engine.repository import CorpusRepository


MASTERED_FOR_PREREQUISITE = frozenset(
    {
        "delayed_retrieval_passed",
        "transferred",
        "operationally_mastered",
    }
)


class Randomizer(Protocol):
    def shuffle(self, values: list[str]) -> None: ...

    def randrange(self, stop: int) -> int: ...


@dataclass
class LearnerConceptState:
    lifecycle_state: str = "unseen"
    unresolved_critical_misconceptions: list[str] = field(default_factory=list)
    last_attempt_at: str | None = None
    successful_delayed_retrievals: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "LearnerConceptState":
        value = value or {}
        return cls(
            lifecycle_state=str(value.get("lifecycle_state") or "unseen"),
            unresolved_critical_misconceptions=list(
                value.get("unresolved_critical_misconceptions") or []
            ),
            last_attempt_at=value.get("last_attempt_at"),
            successful_delayed_retrievals=int(
                value.get("successful_delayed_retrievals") or 0
            ),
        )

    @property
    def mastered_for_prerequisite(self) -> bool:
        return (
            self.lifecycle_state in MASTERED_FOR_PREREQUISITE
            and self.successful_delayed_retrievals >= 1
            and not self.unresolved_critical_misconceptions
        )


def eligible_frontier(
    repository: CorpusRepository,
    learner_states: Mapping[str, Mapping[str, Any]],
    *,
    available_case_concepts: Iterable[str],
) -> list[str]:
    """Return unseen, case-ready concepts whose hard prerequisites are mastered."""

    available = set(available_case_concepts)
    eligible: list[str] = []
    for concept in repository.concepts:
        concept_id = concept["concept_id"]
        if concept_id not in available:
            continue
        state = LearnerConceptState.from_mapping(learner_states.get(concept_id))
        if state.lifecycle_state != "unseen":
            continue
        prerequisites = repository.hard_prerequisites(concept_id)
        if all(
            LearnerConceptState.from_mapping(
                learner_states.get(prerequisite)
            ).mastered_for_prerequisite
            for prerequisite in prerequisites
        ):
            eligible.append(concept_id)
    return eligible


def eligible_authoring_candidates(
    repository: CorpusRepository,
    *,
    allowed_statuses: Iterable[str] = ("extracted", "graph_reviewed"),
) -> list[str]:
    """Return source-backed concepts that may enter the human authoring queue.

    Authoring can happen before a learner unlocks a concept. This is distinct
    from Frontier delivery, which always applies the learner prerequisite gate.
    """

    statuses = set(allowed_statuses)
    return [
        concept["concept_id"]
        for concept in repository.concepts
        if concept.get("content_status") in statuses
        and repository.concept_links(concept["concept_id"])
    ]


class PersistentShuffleBag:
    """Draw without replacement and persist the remaining randomized order."""

    def __init__(
        self,
        state_path: str | Path,
        *,
        corpus_version: str,
        deck_name: str,
        randomizer: Randomizer | None = None,
    ):
        self.state_path = Path(state_path)
        self.corpus_version = corpus_version
        self.deck_name = deck_name
        self.randomizer = randomizer or random.SystemRandom()

    def _load(self) -> MutableMapping[str, Any]:
        if not self.state_path.exists():
            return {
                "schema_version": "1.0.0",
                "corpus_version": self.corpus_version,
                "decks": {},
            }
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        if state.get("corpus_version") != self.corpus_version:
            return {
                "schema_version": "1.0.0",
                "corpus_version": self.corpus_version,
                "decks": {},
            }
        state.setdefault("decks", {})
        return state

    def _save(self, state: Mapping[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_path)

    def draw(self, eligible_ids: Iterable[str]) -> str | None:
        eligible = list(dict.fromkeys(eligible_ids))
        if not eligible:
            return None
        eligible_set = set(eligible)
        state = self._load()
        deck = state["decks"].setdefault(
            self.deck_name,
            {"remaining": [], "drawn_in_cycle": []},
        )

        remaining = [
            concept_id
            for concept_id in deck.get("remaining", [])
            if concept_id in eligible_set
        ]
        already_present = set(remaining) | set(deck.get("drawn_in_cycle", []))
        newly_eligible = [
            concept_id for concept_id in eligible if concept_id not in already_present
        ]
        for concept_id in newly_eligible:
            position = self.randomizer.randrange(len(remaining) + 1)
            remaining.insert(position, concept_id)

        if not remaining:
            remaining = list(eligible)
            self.randomizer.shuffle(remaining)
            deck["drawn_in_cycle"] = []

        selected = remaining.pop(0)
        deck["remaining"] = remaining
        deck.setdefault("drawn_in_cycle", []).append(selected)
        self._save(state)
        return selected
