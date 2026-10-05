"""Authored navigation models, not captured requests or runtime acceptance."""

import asyncio
from dataclasses import replace

from agent_comms.comms import Comms
from agent_comms.selected_source import SessionRevision
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
from textual.app import App
from toad.core.context_inspection import ContextInspection
from toad.widgets.context_explorer import ContextTree, ContextTreeIntent


def test_overlapping_annotation_addresses_restore_their_own_range(tmp_path):
    owner = Thread("authored-navigation", frozenset(), str(tmp_path), created_at=1.0)
    segment = UserInputSegment(content="Keep the original instruction.",
                               provenance=(UnattributedProvenance(),))
    observed = segment.manifest(0)
    spans = tuple(ContextSpan(observed.sha256, ContributionCoordinates.capture(
        type(segment), segment.provenance, 0, text))
        for text in ("Keep", segment.content))
    assert all(observed.contains_span(span) for span in spans)
    assert spans[0].coordinates.offset == spans[1].coordinates.offset
    assert spans[0].coordinates.length != spans[1].coordinates.length
    classifier = JevClassifier.version()
    labels = tuple(ModelLabel(span, QuestionVersion.current(KindQuestion), RuleSpan,
        classifier, (AnswerProbability(RuleSpan, .7), AnswerProbability(CommitmentSpan, .2),
                     AnswerProbability(OtherSpan, .1)), .8, f"authored-answer-{index}", classifier.pin)
        for index, span in enumerate(spans))
    # This unsealed model only exercises navigation. No request ID, captured
    # public text, wire publication, native owner, or original session is made.
    manifest = ContextManifest(owner.incarnation,
        RecordedContextTurn(TurnId("authored-unsealed-navigation"), TurnIdentity(owner.incarnation, 1)),
        (observed,), "authored-navigation")
    inspection = ContextInspection(owner, (manifest,), SessionRevision.observe(None),
                                   Comms(tmp_path / "unused-wire"), labels)
    ((_, (source,), _),) = inspection.working_memory()
    short, long = source.children()
    assert short.key != long.key
    assert short.annotation.span == spans[0] and long.annotation.span == spans[1]
    assert source.reader_path(short.key)[-1] == short
    assert source.reader_path(long.key)[-1] == long
    corrected = HumanLabel.correct(labels[0], RuleSpan, ThreadIncarnation("authored-user", 2.0))
    refined = replace(inspection, annotations=(corrected, labels[1]))
    groups = refined.working_memory()
    answers = tuple(answer for _, sources, _ in groups
                    for current_source in sources for answer in current_source.children())
    corrected_short = next(answer for answer in answers if answer.annotation is corrected)
    retained_long = next(answer for answer in answers if answer.annotation is labels[1])
    assert corrected_short.key == short.key and retained_long.key == long.key
    assert corrected.working_memory_section == "Obeys"

    async def mounted():
        intent = ContextTreeIntent(selected=short)
        detail = []
        tree = ContextTree(intent, detail.append, lambda text: None)

        class TreeApp(App):
            def compose(self):
                yield tree

        app = TreeApp()
        async with app.run_test() as pilot:
            tree.present(inspection.working_memory())
            await pilot.pause()
            short_node, long_node = tree.reveal(short.key), tree.reveal(long.key)
            assert short_node is not long_node
            assert tree.owns_node(short_node) and tree.owns_node(long_node)
            assert tree.cursor_node is short_node and intent.selected is short_node.data
            assert short_node.data.annotation.span == spans[0]
            assert long_node.data.annotation.span == spans[1]

            tree.present(groups)
            await pilot.pause()
            short_node, long_node = tree.reveal(short.key), tree.reveal(long.key)
            assert tree.owns_node(short_node) and tree.owns_node(long_node)
            assert tree.cursor_node is short_node and intent.selected is short_node.data
            assert short_node.data.annotation == corrected
            assert long_node.data.annotation == labels[1]
            assert detail[-1] is short_node.data

            await tree.remove()
            restored = ContextTree(intent, detail.append, lambda text: None)
            await app.mount(restored)
            restored.present(groups)
            await pilot.pause()
            short_node, long_node = restored.reveal(short.key), restored.reveal(long.key)
            assert restored.owns_node(short_node) and restored.owns_node(long_node)
            assert restored.cursor_node is short_node and intent.selected is short_node.data
            assert short_node.data.annotation == corrected and long_node.data.annotation == labels[1]
            assert detail[-1] is short_node.data
        assert app._exception is None

    asyncio.run(mounted())
