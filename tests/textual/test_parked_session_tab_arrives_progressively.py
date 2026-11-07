"""A session tab that missed a run of committed entries has them when the reader returns.

Tristan, 2026-11-07: "when a tab is open and its not focused ... when I go back, it doesn't have
anything new loaded it only shows last message unless I wait a bit and then all the new messages
come in a massive burst". The channel history already loads its backlog while it is parked
(`test_parked_tab_arrives_progressively`); a session transcript is the same requirement against
a different source.
"""

import json
from dataclasses import replace

from support.journals import assistant_entry, write_journal


def loaded(conversation) -> int:
    """The entries the view holds, drawn or not: what a reader would see on return."""
    history = next(iter(conversation.contents.line_histories()))
    return sum(len(page.prepared.fragments) for page in history.pages)


def append(journal, *bodies: str, prefix: str) -> None:
    with journal.open('a', encoding='utf-8') as handle:
        for index, body in enumerate(bodies):
            handle.write(json.dumps(assistant_entry(body, id=f'{prefix}-{index}')) + '\n')


async def test_a_parked_session_tab_reads_the_change_while_parked(workspace):
    """Core publishes ExternalTranscriptChanged for every owned transcript; a parked tab must
    read it rather than wait for its return, where the missed range arrives in one burst."""
    from toad.core.events import ExternalTranscriptChanged

    from agent_comms.session_file import RegistrySessionLocation

    saved = workspace.thread('parked-session')
    journal = write_journal(workspace.project / 'parked-session.jsonl',
                            assistant_entry('FIRST_BODY', id='first'))
    workspace.comms.registry.declare(replace(saved, session_file=
        RegistrySessionLocation.from_path(journal, workspace.comms.root)))

    missed = [f'PARKED_LINE_{index:02d}' for index in range(6)]
    async with workspace.app(size=(110, 35), resume='parked-session') as ui:
        app, _pilot = ui.textual
        await ui.until_shows('FIRST_BODY')
        conversation = ui.conversation
        owner = ui.selected_tab
        await ui.new_session()
        before = loaded(conversation)
        append(journal, *missed, prefix='parked')
        app.events.publish(ExternalTranscriptChanged())
        await ui.step(0.6)
        while_parked = loaded(conversation)
        await ui.select_tab(owner)
        await ui.step(0.05)
        assert while_parked >= before + len(missed), (
            f'the parked session tab held {while_parked - before} of {len(missed)} missed '
            f'entries while it was away; the rest load on return as a burst'
        )
