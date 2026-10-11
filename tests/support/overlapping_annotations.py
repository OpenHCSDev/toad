"""Two annotations on one context segment that start at the same offset, authored without a model or a wire turn."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from agent_comms.comms import Comms
from agent_comms.session_revision import SessionRevision
from agent_comms.thread_identity import ThreadIncarnation, TurnId, TurnIdentity
from agent_comms.threads import Thread
from agent_comms.turn_context import (
    ContextManifest, ContextSpan, ContributionCoordinates, RecordedContextTurn,
    UnattributedProvenance, UserInputSegment,
)
from agent_comms.working_memory_labels import (
    AnswerProbability, HumanLabel, JevClassifier, ModelLabel, QuestionVersion,
)
from agent_comms.working_memory_questions import CommitmentSpan, KindQuestion, OtherSpan, RuleSpan
from toad.core.context_inspection import ContextInspection


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
    owner = Thread("authored-navigation", frozenset(), str(directory), created_at=1.0)
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
    # This unsealed model only exercises navigation: no request, no captured
    # public text, no wire message, no native owner and no saved session.
    manifest = ContextManifest(owner.incarnation,
        RecordedContextTurn(TurnId("authored-unsealed-navigation"), TurnIdentity(owner.incarnation, 1)),
        (observed,), "authored-navigation")
    inspection = ContextInspection(owner, (manifest,), SessionRevision.observe(None),
                                   Comms(directory / "unused-wire"), labels)
    ((_, (source,), _),) = inspection.working_memory()
    short, long = source.children()
    corrected = HumanLabel.correct(labels[0], RuleSpan, ThreadIncarnation("authored-user", 2.0))
    refined = replace(inspection, annotations=(corrected, labels[1]))
    return OverlappingAnnotations(observed, spans, labels, inspection, short, long, corrected,
                                  refined.working_memory())
