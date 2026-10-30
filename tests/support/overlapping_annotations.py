"""Two annotations on one context segment that start at the same offset, authored without a model or a wire turn."""

from __future__ import annotations

from agent_comms.repo import Checkout

from dataclasses import dataclass, replace
from pathlib import Path

from agent_comms.context_store import AbsentContext, ContextManifestPage
from agent_comms.session_revision import NoSessionObservation
from agent_comms.thread_identity import RecordedThreadIncarnation, TurnId, TurnIdentity
from agent_comms.turn_context import (
    ContextManifest, ContextSpan, ContributionCoordinates, RecordedContextTurn,
    UnattributedProvenance, UserInputSegment,
)
from agent_comms.working_memory_labels import (
    AnswerProbability, HumanLabel, JevClassifier, ModelLabel, QuestionVersion,
)
from agent_comms.working_memory_questions import CommitmentSpan, KindQuestion, OtherSpan, RuleSpan
from agent_comms.threads import Thread
from toad.core.context_inspection import ContextInspection
from support.roots import installed_wire


@dataclass(frozen=True)
class OverlappingAnnotations:
    observed: object
    spans: tuple
    labels: tuple
    inspection: ContextInspection
    short: object
    long: object
    corrected: HumanLabel
    refined_groups: tuple


def overlapping_annotations(directory: Path) -> OverlappingAnnotations:
    """A short and a long annotation over one segment, as an inspection shows them, and the same after correcting the short one."""
    service = installed_wire(directory / "unused-wire")
    owner = service.registry.declare(Thread(
        "authored-navigation", frozenset(), Checkout(directory), created_at=1.0))
    segment = UserInputSegment(content="Keep the original instruction.",
                               provenance=(UnattributedProvenance(),))
    observed = segment.manifest(0)
    spans = tuple(ContextSpan(observed.sha256, ContributionCoordinates.capture(
        type(segment), segment.provenance, 0, text))
        for text in ("Keep", segment.content))
    classifier = JevClassifier.version()
    labels = tuple(ModelLabel(span, QuestionVersion.current(KindQuestion), RuleSpan,
        classifier, (AnswerProbability(RuleSpan, .7), AnswerProbability(CommitmentSpan, .2),
                     AnswerProbability(OtherSpan, .1)), .8, f"authored-answer-{index}", classifier.pin)
        for index, span in enumerate(spans))
    # A locally captured context exercises navigation without a native request,
    # wire message or saved session.
    manifest = ContextManifest(owner.incarnation,
        RecordedContextTurn(TurnId.mint(), TurnIdentity(owner.incarnation, 1)),
        (observed,), "authored-navigation")
    captured = service.contexts.record_after(AbsentContext(), manifest)
    inspection = ContextInspection(service.registry.entry(owner.name).entry,
        ContextManifestPage((captured,)), NoSessionObservation(), service, labels)
    ((_, (source,), _),) = inspection.working_memory()
    short, long = source.children()
    corrected = HumanLabel.correct(labels[0], RuleSpan, RecordedThreadIncarnation("authored-user", 2.0))
    refined = replace(inspection, annotations=(corrected, labels[1]))
    return OverlappingAnnotations(observed, spans, labels, inspection, short, long, corrected,
                                  refined.working_memory())
