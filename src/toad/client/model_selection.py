"""Toolkit-neutral searchable, recent-first model picker core shared by Textual and Qt.

`ModelSelectionCore` owns fuzzy subsequence scoring, recent-first / current-first ranking,
highlight placement across refilters, status-line formatting, and recent-choice generation
fencing. `CatalogModelField` and `CatalogChoiceSelection` own the binding between a
`ModelConfigOption` form field (`PreparedChoices`) and the picker. Textual's
`ModelSelection` / `CatalogField` and Qt's `QtModelSelection` / `QtCatalogField` inherit
these bases and supply only native widgets.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from toad.acp.agent_configuration import ModelConfigurationSetting
from toad.client.command_draft import PreparedChoices


def match_score(query: str, candidate: str) -> float:
    """Linear subsequence matching, with exact/prefix/substring preference."""
    if query == candidate:
        return 100
    if candidate.startswith(query):
        return 80
    if query in candidate:
        return 60
    previous = -1
    first = -1
    for character in query:
        previous = candidate.find(character, previous + 1)
        if previous == -1:
            return 0
        if first == -1:
            first = previous
    return 10 + len(query) / max(1, previous - first + 1)


class ModelChoice(Protocol):
    @property
    def value(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str | None: ...


class HighlightPlacement(ABC):
    """Where a refilter puts the highlight."""

    @abstractmethod
    def index(self, ids: list[str | None], previous_id: str | None) -> int: ...


class ResetsHighlight(HighlightPlacement):
    """Nothing touched since the picker opened: the best match, first in the list."""

    def index(self, ids: list[str | None], previous_id: str | None) -> int:
        return 0


class KeepsHighlight(HighlightPlacement):
    """The user moved or typed: stay on their option while the filter still lists it."""

    def index(self, ids: list[str | None], previous_id: str | None) -> int:
        return ids.index(previous_id) if previous_id in ids else 0


@dataclass(frozen=True)
class RankedModel:
    """One ranked model choice ready for any frontend to render."""

    choice: ModelChoice
    is_current: bool
    is_recent: bool

    @property
    def plain_label(self) -> str:
        prefix = "✓ " if self.is_current else "  "
        recent = " · recent" if self.is_recent else ""
        detail = f" · {self.choice.value}" if self.choice.value != self.choice.name else ""
        return f"{prefix}{self.choice.name}{recent}{detail}"


class ModelSelectionCore:
    """Search, recents ranking and provider-connection contract for model pickers."""

    choice_name: str = "models"
    history_scope: str = ""

    def init_model_selection(self) -> None:
        self.recent_ids: list[str] = []
        self._open_generation = 0
        self.refilter: HighlightPlacement = ResetsHighlight()

    @property
    @abstractmethod
    def choices(self) -> Sequence[ModelChoice]: ...

    @property
    @abstractmethod
    def current(self) -> str: ...

    @property
    @abstractmethod
    def selection_active(self) -> bool: ...

    @abstractmethod
    def select_model(self, model_id: str) -> None: ...

    @abstractmethod
    def connect_provider(self) -> None: ...

    @abstractmethod
    def search_query(self) -> str: ...

    @abstractmethod
    def highlighted_model_id(self) -> str | None: ...

    @abstractmethod
    def present_filtered_models(
        self,
        ranked: list[RankedModel],
        highlighted_index: int | None,
        summary: str,
    ) -> None: ...

    def filter_models(self, placement: HighlightPlacement) -> None:
        previous_id = self.highlighted_model_id()
        ranked, summary = self.rank_models(self.search_query())
        highlighted = (
            placement.index([entry.choice.value for entry in ranked], previous_id)
            if ranked
            else None
        )
        self.present_filtered_models(ranked, highlighted, summary)

    def search_changed(self) -> None:
        self.filter_models(ResetsHighlight())
        self.refilter = KeepsHighlight()

    def note_highlight_moved(self) -> None:
        self.refilter = KeepsHighlight()

    def submit(self) -> None:
        if (model_id := self.highlighted_model_id()) is not None:
            self.select_model(model_id)

    async def recent_choices(self, scope: str) -> list[str]:
        return await ModelConfigurationSetting().recent_choices(scope)

    def apply_recents(self, generation: int, scope: str, recent: list[str]) -> bool:
        """Apply loaded recent model IDs if the picker is still on the same open generation."""
        if (
            self.selection_active
            and generation == self._open_generation
            and scope == self.history_scope
        ):
            self.recent_ids = recent
            self.filter_models(self.refilter)
            return True
        return False

    def rank_models(self, query: str) -> tuple[list[RankedModel], str]:
        """Filter and rank `self.choices` against `query`, returning `(ranked, summary)`."""
        terms = query.casefold().split()
        recent = {model_id: index for index, model_id in enumerate(self.recent_ids)}
        models, current = self.choices, self.current
        scored = []
        for model in models:
            fields = {model.name.casefold(), model.value.casefold()}
            scores = [
                max(
                    *(match_score(term, field) for field in fields),
                    match_score(term, (model.description or "").casefold()) * 0.5,
                )
                for term in terms
            ]
            if scores and not all(scores):
                continue
            rank = recent.get(model.value, len(recent) + (model.value != current))
            scored.append((-sum(scores), rank, model.name.casefold(), model.value, model))
        scored.sort(key=lambda item: item[:4])
        ranked = [
            RankedModel(
                choice=model,
                is_current=model.value == current,
                is_recent=model.value in recent,
            )
            for *_, model in scored
        ]
        if ranked:
            ordering = "best matches" if terms else "recent first" if recent else "current first"
            summary = f"{len(ranked)} / {len(models)} {self.choice_name} · {ordering}"
        else:
            summary = f"No matching {self.choice_name}"
        return ranked, summary


class CatalogModelField:
    """Shared binding between a `ModelConfigOption` form field and its model picker."""

    empty_catalog_label: str = "Choose / connect a provider…"

    def catalog_parameter(self):
        return self.field.metadata(PreparedChoices).parameter

    def catalog_choices(self) -> tuple[ModelChoice, ...]:
        return tuple(
            choice for choice in self.catalog_parameter().options
            if choice.value is not None
        )

    def catalog_current(self) -> str:
        return self.catalog_parameter().choice_value(self.field.value)

    def catalog_label(self) -> str:
        current = self.catalog_current()
        return next(
            (choice.name for choice in self.catalog_parameter().options if choice.value == current),
            self.empty_catalog_label,
        )

    def apply_catalog_choice(self, value: str) -> None:
        self.send(self.catalog_parameter().editor_value(value))


class CatalogChoiceSelection(ModelSelectionCore):
    """A model selection bound to a `CatalogModelField` editor."""

    editor: CatalogModelField

    @property
    def choices(self) -> tuple[ModelChoice, ...]:
        return self.editor.catalog_choices()

    @property
    def current(self) -> str:
        return self.editor.catalog_current()


class SessionChoiceSelection(ModelSelectionCore):
    """A model selection bound to a live agent's `ModelConfigurationSetting`."""

    @abstractmethod
    def model_setting(self) -> ModelConfigurationSetting:
        """The session's current advertised model configuration setting."""

    @property
    def choices(self) -> tuple[ModelChoice, ...]:
        return self.model_setting().choices

    @property
    def current(self) -> str:
        return self.model_setting().current
