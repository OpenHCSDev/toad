"""Declaration-only control discovery and deleted root goal dispatch."""
import ast
from pathlib import Path


def test_deleted_root():
    tree=ast.parse((Path(__file__).parents[2]/'src/toad/widgets/conversation.py').read_text())
    retired={'_goal_modal','_poll_goal','change_goal'}
    assert not [n for n in ast.walk(tree)
                if isinstance(n,ast.Attribute) and n.attr in retired
                or isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in retired]
    handler=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=='on_goal_control')
    assert not any(isinstance(n,ast.Compare) for n in ast.walk(handler))


async def declared_case():
    import os
    from tempfile import TemporaryDirectory
    from agent_comms.goals import Goal
    from agent_comms.goal_actions import PausedGoalAction
    from toad.app import ToadApp
    from toad.goal_display import GoalDisplay
    from toad.goal_interaction import GoalInteraction, GoalSession
    from toad.widgets.goal_bar import GoalBar, GoalControl

    class ProbeInteraction(GoalInteraction):
        label="Probe"

        @classmethod
        async def apply(cls, session):
            session.view.prompt.text="Declared control exercised"

    with TemporaryDirectory(dir='.artifacts') as directory:
        root=Path(directory).resolve()
        os.environ.update(XDG_CONFIG_HOME=str(root/'config'),XDG_STATE_HOME=str(root/'state'),
                          XDG_DATA_HOME=str(root/'data'),AGENT_COMMS_ROOT=str(root/'wire'))
        app=ToadApp(project_dir=str(root))
        async with app.run_test(size=(140,44)) as pilot:
            await app.selected_session.wait_content_ready()
            view=app.selected_session.conversation
            view.goal_display=GoalDisplay.current(Goal("Visible goal for control discovery","new-control"))
            await pilot.pause()
            bar=view.query_one(GoalBar)
            assert {c.id for c in bar.query(GoalControl)}=={c.control_id() for c in GoalInteraction.members_with(GoalInteraction)}
            await pilot.click("#"+ProbeInteraction.control_id())
            assert view.prompt.text=="Declared control exercised"
            await pilot.click("#goal-collapse")
            assert bar.collapsed
            frame='\n'.join(strip.text for strip in app.screen._compositor.render_strips())
            assert "Expand" in frame and "Probe" in frame
            old=view.goal_controls
            view.goal_controls=GoalSession(view)
            try:
                await old.change(PausedGoalAction)
            except ValueError as error:
                assert "presentation changed" in str(error)
            else:
                raise AssertionError("A retired binding may not control the replacement source")
            old.close()
            assert old.view is None and old.modal is None
            assert app._exception is None
    print("installed declaration-only new control discovered, activated and painted; collapse behavior and stale binding fence passed")


def test_new_case():
    import asyncio
    asyncio.run(declared_case())


if __name__=='__main__':
    test_deleted_root()
    test_new_case()
