"""Disclosure must publish rows while a newer original snapshot waits to update.

Holds delivery of actual worker-prepared row content, not the UI/model/protocol.
No ACP/native owner/provider starts. Uses original private canonical membership.
"""
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from agent_comms.comms import Comms
from agent_comms.threads import Thread
from toad.app import ToadApp
from toad.sidebar_preparation import ThreadRowInput, ThreadRowsWork
from toad.widgets.comms_sidebar import ChannelGroup, CommsSidebar
from toad.widgets.session_thread_sidebar import SessionThreadSidebar
from toad.widgets.thread_comms import ThreadCommsSidebar
from toad.widgets.thread_comms_source import WireRelationshipSource


async def main():
    artifacts = Path(os.environ['CHANNEL_DISCLOSURE_ARTIFACTS']).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=artifacts) as directory:
        root = Path(directory)
        os.environ.update(AGENT_COMMS_ROOT=str(root / 'wire'),
                          XDG_CONFIG_HOME=str(root / 'config'),
                          XDG_STATE_HOME=str(root / 'state'),
                          XDG_DATA_HOME=str(root / 'data'))
        comms = Comms(root / 'wire')
        comms.messaging.initialize_private_initial_protocol()
        comms.registry.declare(Thread('beta', frozenset({'team'}), str(root)))
        comms.registry.declare(Thread('child', frozenset(), str(root), parent='beta'))
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await app.selected_session.wait_content_ready()
            sidebar = app.screen.query_one(CommsSidebar)
            async with asyncio.timeout(5):
                while not sidebar.navigation.ready.is_set():
                    await pilot.pause(.02)
            group = next(item for item in sidebar.query(ChannelGroup)
                         if item.row.target_name == '#team')
            assert next(view for view in sidebar.projection.snapshot.wire.channels
                        if view.channel.name == '#team').members == ('beta',)
            assert not group.expanded and not group.member_container.children
            prepared, newer_prepared = asyncio.Event(), asyncio.Event()
            release, release_newer = asyncio.Event(), asyncio.Event()
            first_done = asyncio.Event()
            submit = app.preparation.submit
            deliveries = 0

            async def held_submit(work):
                nonlocal deliveries
                result = await submit(work)
                if isinstance(work, ThreadRowsWork):
                    deliveries += 1
                    if deliveries == 1:
                        prepared.set()
                        await release.wait()
                    elif deliveries == 2:
                        newer_prepared.set()
                        await release_newer.wait()
                return result

            async def finished_disclosure():
                await group._sync_members()
                first_done.set()

            tasks = []
            with patch.object(app.preparation, 'submit', held_submit):
                try:
                    # The original disclosure owns expansion; this controlled
                    # call uses the same member-reconciliation entrypoint as
                    # its native callback without blocking Pilot.pause on it.
                    group.expanded = True
                    sidebar.navigation.state.expanded[group.row.target_name] = True
                    group.disclosure.update('▾', layout=False)
                    tasks.append(asyncio.create_task(finished_disclosure()))
                    async with asyncio.timeout(5):
                        await prepared.wait()
                    original = sidebar.projection.snapshot
                    newer = replace(original, wire=replace(
                        original.wire,
                        unread={**original.wire.unread, 'beta': 1},
                        thread_unread={**original.wire.thread_unread, 'beta': 1},
                    ))
                    view = next(item for item in newer.wire.channels
                                if item.channel.name == '#team')
                    tasks.append(asyncio.create_task(sidebar.projection.publish(newer)))
                    await asyncio.sleep(0)
                    release.set()
                    async with asyncio.timeout(5):
                        await first_done.wait()
                        await newer_prepared.wait()
                    receipt = {
                        'expanded': group.expanded,
                        'canonical_members': list(view.members),
                        'first_publication_rows': [row.target_name for row in group.member_container.children],
                        'newer_preparation_pending': not tasks[1].done(),
                    }
                    print(json.dumps(receipt), flush=True)
                    (artifacts / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
                    assert receipt['first_publication_rows'] == ['beta'], receipt
                    release_newer.set()
                    await asyncio.gather(*tasks)
                finally:
                    release.set()
                    release_newer.set()
                    await asyncio.gather(*tasks, return_exceptions=True)
            await pilot.pause()
            retained = tuple(group.member_container.children)
            assert [row.target_name for row in retained] == ['beta']
            await pilot.click(group.disclosure)
            await pilot.pause()
            assert not group.expanded and not group.member_container.children
            await pilot.click(group.disclosure)
            await pilot.pause()
            assert group.expanded and len(group.member_container.children) == 1
            # Poll metadata is not a new rendered row. Reuse its original
            # prepared frames without another worker hash/delivery roundtrip.
            reused = group.member_container.children[0]._thread_presentation
            requests = []

            async def count_rows(work):
                if isinstance(work, ThreadRowsWork):
                    requests.append(len(work.rows))
                return await submit(work)

            metadata_only = replace(sidebar.projection.snapshot, wire=replace(
                sidebar.projection.snapshot.wire, channels=tuple(
                    replace(view, last_activity=view.last_activity + 1)
                    for view in sidebar.projection.snapshot.wire.channels)))
            with patch.object(app.preparation, 'submit', count_rows):
                await sidebar.projection.publish(metadata_only)
            assert requests == [], requests
            assert group.member_container.children[0]._thread_presentation is reused
            # A changed tooltip is published, but it does not damage identical
            # native row text. Both sidebars inherit this same row consumer.
            retained_row = group.member_container.children[0]
            tooltip_source = replace(reused.source, model='tooltip-only-source-change')
            tooltip_row, = await submit(ThreadRowsWork((tooltip_source,)))
            with patch.object(retained_row, 'update', wraps=retained_row.update) as paints:
                retained_row.apply_thread_preparation(tooltip_row)
                assert retained_row.tooltip.plain == tooltip_row.tooltip.plain
                assert paints.call_count == 0
                retained_row.apply_thread_preparation(reused)
                assert paints.call_count == 0
            # Real disclosure clicks may change reader intent while preparation
            # is held. Publication must use the current disclosure, then reverse.
            preparing, deliver = asyncio.Event(), asyncio.Event()
            publications = []
            reconcile = group.reconcile_rows

            async def held_disclosure(work):
                result = await submit(work)
                if isinstance(work, ThreadRowsWork) and not preparing.is_set():
                    preparing.set()
                    await deliver.wait()
                return result

            async def record_publication(keys, *args, **kwargs):
                publications.append((group.expanded, tuple(keys)))
                return await reconcile(keys, *args, **kwargs)

            clicks = []
            with (patch.object(app.preparation, 'submit', held_disclosure),
                  patch.object(group, 'reconcile_rows', record_publication)):
                try:
                    # Source reconciliation runs independently of the widget's
                    # message pump; the real collapse click remains deliverable.
                    changed = replace(sidebar.projection.snapshot, wire=replace(
                        sidebar.projection.snapshot.wire,
                        unread={**sidebar.projection.snapshot.wire.unread, 'beta': 2},
                        thread_unread={**sidebar.projection.snapshot.wire.thread_unread, 'beta': 2},
                    ))
                    clicks.append(asyncio.create_task(sidebar.projection.publish(changed)))
                    async with asyncio.timeout(5):
                        await preparing.wait()
                    clicks.append(asyncio.create_task(pilot.click(group.disclosure)))
                    async with asyncio.timeout(5):
                        while group.expanded:
                            await asyncio.sleep(.01)
                    deliver.set()
                    await asyncio.gather(*clicks)
                finally:
                    deliver.set()
                    await asyncio.gather(*clicks, return_exceptions=True)
            assert publications and all(expanded or not keys for expanded, keys in publications), publications
            assert not group.expanded and not group.member_container.children
            await pilot.click(group.disclosure)
            await pilot.pause()
            assert group.expanded and len(group.member_container.children) == 1
            region = group.member_container.region
            paint = '\n'.join(strip.crop(region.x, region.right).text
                              for strip in app.screen._compositor.render_strips()[region.y:region.bottom])
            assert 'beta' in paint, paint
            # The other group family inherits the same member lifetime lock.
            # Read its original private canonical parent/child relationship.
            right = app.screen.query_one('#thread-sidebar', SessionThreadSidebar)
            right.reveal()
            await right.wait_content_ready()
            previous = right.query_one(ThreadCommsSidebar)
            container = previous.parent
            await previous.remove()
            tree = ThreadCommsSidebar('beta', wire_root=str(root / 'wire'),
                source=WireRelationshipSource(str(root / 'wire'), comms))
            await container.mount(tree)
            async with asyncio.timeout(5):
                while ('children' not in tree.groups
                       or not tree.groups['children'].member_container.children):
                    await pilot.pause(.02)
            children = tree.groups['children']
            retained = tuple(children.member_container.children)
            assert [row.target_name for row in retained] == ['child']
            model = next(model for model in comms.relationships.snapshot('beta').groups
                         if model.key == 'children')
            relationship_requests = []

            async def count_relationship_rows(work):
                if isinstance(work, ThreadRowsWork):
                    relationship_requests.append(len(work.rows))
                return await submit(work)

            with patch.object(app.preparation, 'submit', count_relationship_rows):
                captured = await ThreadRowsWork.capture(
                    app.preparation, tuple(ThreadRowInput(person) for person in children.thread_people()))
                await children.reconcile_groups((children,), captured, sources={children: model})
            assert relationship_requests == [], relationship_requests
            assert tuple(children.member_container.children) == retained
            children.toggle_members()
            await pilot.pause()
            assert not children.member_container.display
            children.toggle_members()
            await pilot.pause()
            assert children.member_container.display
            assert tuple(children.member_container.children) == retained
            receipt.update(channel_member_painted=True, collapse_expand_passed=True,
                           collapse_during_preparation=publications,
                           canonical_relationship_child='child', relationship_row_retained=True,
                           metadata_only_worker_rows=requests,
                           unchanged_relationship_worker_rows=relationship_requests)
            (artifacts / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
            print(json.dumps(receipt), flush=True)
        assert app._exception is None


if __name__ == '__main__':
    asyncio.run(main())
