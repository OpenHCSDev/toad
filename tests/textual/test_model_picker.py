"""Textual-facing: the model picker (an option list popup with a search input) takes keyboard focus, highlights under mouse and keys, stays on screen when resized, and keeps the prompt draft."""

from contextlib import asynccontextmanager
import json
import subprocess
import sys

from acp.schema import SessionConfigOptionSelect, SessionConfigSelectOption
from toad.acp.status import EndTurnStopReason
from support.agents import AppAgents, command
from toad.acp.agent import Agent
from toad.command_catalog import CommandCatalog
from toad.db import DB
from toad.widgets.prompt import AgentInfo

GLM = "openrouter/z-ai/glm-5.3-flash"
SONNET = "openrouter/anthropic/claude-sonnet-4.6"
GPT = "openrouter/openai/gpt-5.4"
SCOPE = "picker-test"


def catalogue():
    models = {model.value: model for model in (
        SessionConfigSelectOption(value=GLM, name="GLM 5.3 Flash", description="Fast coding model"),
        SessionConfigSelectOption(value=SONNET, name="Claude Sonnet 4.6", description="Balanced coding model"),
        SessionConfigSelectOption(value=GPT, name="GPT 5.4", description="OpenRouter"),
        SessionConfigSelectOption(value="openai/gpt-5.4", name="GPT 5.4 direct", description="OpenAI"),
        SessionConfigSelectOption(value="test/unavailable", name="Unavailable model"),
    )}
    models.update({f"test/model-{n:04}": SessionConfigSelectOption(value=f"test/model-{n:04}", name=f"Model {n:04}")
                   for n in range(1000)})
    return models


class PickerAgent(Agent):
    """An agent object that advertises the catalogue and answers model changes without a process."""

    def __init__(self, *args, models, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []
        self.configuration.receive([SessionConfigOptionSelect(
            id='model', name='Model', category='model', type='select',
            current_value=next(iter(models)), options=list(models.values()))])

    async def set_model(self, model_id):
        self.calls.append(model_id)
        if model_id == "test/unavailable":
            return "Model unavailable"
        self.configuration.receive([self.configuration.model.option.model_copy(
            update={'current_value': model_id})])
        return None


class Picker:
    def __init__(self, ui, agent, db):
        self.ui, self.agent, self.db = ui, agent, db
        self.conversation = ui.conversation
        self.prompt = self.conversation.prompt
        self.widget = self.prompt.model_switcher
        _app, self.pilot = ui.textual

    def ids(self):
        options = self.widget.option_list
        return [options.get_option_at_index(i).id for i in range(options.option_count)]

    async def open_with_command(self):
        await CommandCatalog.execute("/model", self.conversation)
        await self.ui.until(lambda: self.widget.is_open, why="the picker to open")
        await self.ui.step()

    async def recents(self):
        return await self.db.recent_models(SCOPE)


@asynccontextmanager
async def picker_session(workspace):
    async with workspace.app(size=(120, 40)) as ui:
        app, _pilot = ui.textual
        agent = AppAgents(app).agent(PickerAgent, command("false", name="Picker test", identity="picker-test"),
                                     "picker", models=catalogue())
        ui.attach_agent(agent)
        ui.conversation.model_history_scope = SCOPE
        agent.configuration.publish()
        await ui.until(lambda: agent.configuration.model.selected is not None, why="the advertised model")
        db = DB()
        await db.record_model_usage(SCOPE, GPT)
        await db.record_model_usage(SCOPE, SONNET)
        await db.record_model_usage(SCOPE, "retired/model")
        await db.record_model_usage("other-agent", GLM)
        picker = Picker(ui, agent, db)
        picker.prompt.text = "Keep this unfinished draft"
        yield picker


async def choose_gpt(picker):
    await picker.open_with_command()
    assert picker.widget.search_input.has_focus and not picker.widget.search_input.value
    await picker.ui.press(*"gpt 5.4")
    assert picker.ids()[0] == GPT
    await picker.ui.press("enter")
    await picker.ui.until(lambda: picker.agent.configuration.model.current == GPT, why="the model change")
    async def first():
        return (await picker.recents())[0] == GPT
    await picker.ui.until(first, why="the chosen model first in recent models")


async def open_by_clicking_the_model(picker):
    before = await picker.recents()
    assert await picker.pilot.click(picker.prompt.query_one(AgentInfo))
    await picker.ui.until(lambda: picker.widget.recent_ids == before, why="recent models in the picker")
    await picker.ui.step()
    return before


async def test_opening_the_picker_focuses_search_and_lists_recent_models_first(workspace):
    async with picker_session(workspace) as picker:
        widget = picker.widget
        await open_by_clicking_the_model(picker)
        assert widget.search_input.has_focus
        assert picker.ids()[:3] == [SONNET, GPT, GLM]
        highlighted_style = list(widget.option_list.render_line(0))[0].style
        assert highlighted_style.color != highlighted_style.bgcolor
        assert highlighted_style.bgcolor != list(widget.option_list.render_line(1))[0].style.bgcolor
        assert "retired/model" not in picker.ids()


async def test_hover_and_arrow_keys_move_the_highlight_without_taking_focus_from_search(workspace):
    async with picker_session(workspace) as picker:
        widget, ui = picker.widget, picker.ui
        await open_by_clicking_the_model(picker)
        await picker.pilot.hover(widget.option_list, offset=(2, 1))
        await ui.step()
        assert widget.option_list.highlighted == 1
        assert widget.search_input.has_focus
        await ui.press("down")
        assert widget.option_list.highlighted == 2
        assert widget.option_list._mouse_hovering_over is None
        assert (list(widget.option_list.render_line(1))[0].style.bgcolor
                != list(widget.option_list.render_line(2))[0].style.bgcolor)


async def test_typing_filters_models_fuzzily_and_escape_closes_without_a_change(workspace):
    async with picker_session(workspace) as picker:
        widget, ui = picker.widget, picker.ui
        before = await open_by_clicking_the_model(picker)
        await ui.press(*"SONNET anthr")
        assert picker.ids() == [SONNET]
        assert picker.prompt.text == "Keep this unfinished draft"
        assert not picker.prompt.prompt_text_area.suggestion
        await ui.press("ctrl+u", *"cldsnt")
        assert picker.ids() == [SONNET]
        await ui.press("ctrl+u", *"zzzzzzzzz", "down", "up", "enter")
        assert not picker.ids() and widget.is_open and not picker.agent.calls
        await ui.press("escape")
        assert not widget.is_open and picker.prompt.prompt_text_area.has_focus
        assert await picker.recents() == before


async def test_choosing_the_current_model_does_not_reapply_it(workspace):
    async with picker_session(workspace) as picker:
        await picker.open_with_command()
        await picker.ui.press(*"glm")
        assert await picker.pilot.click(picker.widget.option_list, offset=(2, 0))
        await picker.ui.until(lambda: not picker.widget.is_open, why="the picker to close")
        assert not picker.agent.calls, "Opening the current model must not reapply it"


async def test_choosing_another_model_applies_it_and_makes_it_the_most_recent(workspace):
    async with picker_session(workspace) as picker:
        await choose_gpt(picker)
        assert picker.prompt.text == "Keep this unfinished draft"
        await picker.open_with_command()
        await picker.ui.until(lambda: picker.widget.recent_ids[0] == GPT, why="the chosen model first in the picker")
        assert picker.ids()[0] == GPT


async def test_the_picker_stays_inside_the_screen_when_it_is_resized(workspace):
    async with picker_session(workspace) as picker:
        await picker.open_with_command()
        for width, height in ((80, 24), (96, 18), (120, 40)):
            await picker.ui.resize(width, height)
            widget = picker.widget
            assert widget.region.x >= 0 and widget.region.right <= width
            assert widget.region.y >= 0 and widget.region.bottom <= height
            assert widget.search_input.region.y < widget.option_list.region.y


async def test_a_model_the_agent_refuses_is_not_applied_or_recorded(workspace):
    async with picker_session(workspace) as picker:
        await choose_gpt(picker)
        await picker.open_with_command()
        await picker.ui.press(*"unavailable", "enter")
        await picker.ui.until(lambda: picker.agent.calls[-1] == "test/unavailable", why="the refused request")
        await picker.ui.step()
        assert picker.agent.configuration.model.current == GPT
        assert "test/unavailable" not in await picker.recents()


async def test_a_model_counts_as_used_when_a_turn_completes_not_when_it_is_received(workspace):
    async with picker_session(workspace) as picker:
        await choose_gpt(picker)
        agent = picker.agent
        agent.configuration.receive([agent.configuration.model.option.model_copy(update={'current_value': SONNET})])
        await picker.ui.until(lambda: agent.configuration.model.current == SONNET, why="the received model")
        assert (await picker.recents())[0] == GPT
        await picker.conversation.agent_turn_over(EndTurnStopReason)
        async def sonnet_first():
            return (await picker.recents())[0] == SONNET
        await picker.ui.until(sonnet_first, why="the completed turn to record its model")
        history = json.loads(subprocess.check_output([
            sys.executable, "-c",
            f"import asyncio,json; from toad.db import DB; print(json.dumps(asyncio.run(DB().recent_models({SCOPE!r}))))",
        ], text=True))
        assert history[0] == SONNET
        assert history.count(GPT) == 1
