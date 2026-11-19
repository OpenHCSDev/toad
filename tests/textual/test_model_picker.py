"""Textual-facing: the model picker (an option list popup with a search input) takes keyboard focus, highlights under mouse and keys, stays on screen when resized, and keeps the prompt draft."""

import json
import subprocess
import sys
from contextlib import asynccontextmanager

from acp.schema import (
    SessionConfigOptionSelect,
    SessionConfigSelectOption,
    SetSessionConfigOptionResponse,
)
from support.agents import AppAgents, command
from textual import events
from textual.pilot import _get_mouse_message_arguments

from formbridge.key_declarations import TextEntryMode
from toad.acp.agent import Agent
from toad.acp.agent_configuration import (
    AdvertisedSetting,
    ModelConfigurationSetting,
    ServiceTierConfigurationSetting,
    ThinkingConfigurationSetting,
)
from toad.acp.status import EndTurnStopReason
from toad.command_catalog import CommandCatalog
from toad.client.db import DB
from toad.forms.editors import ChoicesEditor
from toad.widgets.model_selection import ClearModelSearchAction
from toad.widgets.model_switcher import (
    FinishSessionSettings,
    PopupSessionForm,
    SessionForm,
    SessionModelEditor,
)
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
                   for n in range(439)})
    return models


def advertised_settings(models, model=GLM, thinking_level="low", service_tier="standard"):
    """The test agent's actual ACP declaration; field order comes from this response."""
    return [
        SessionConfigOptionSelect(
            id="thinking_level", name="Thinking level", category="thought_level", type="select",
            current_value=thinking_level, options=[
                SessionConfigSelectOption(value="low", name="Low"),
                SessionConfigSelectOption(value="high", name="High"),
            ],
        ),
        SessionConfigOptionSelect(
            id="service_tier", name="Service tier", category="service_tier", type="select",
            current_value=service_tier, options=[
                SessionConfigSelectOption(value="standard", name="Standard"),
                SessionConfigSelectOption(value="priority", name="Priority"),
            ],
        ),
        SessionConfigOptionSelect(
            id="model", name="Model", category="model", type="select",
            current_value=model, options=list(models.values()),
        ),
    ]


class PickerRpc:
    """The ACP boundary used by ordinary advertised-setting edits."""

    def __init__(self, agent):
        self.agent = agent

    async def set_config_option(self, config_id, session_id, value):
        self.agent.config_calls.append((config_id, value))
        self.agent.values[config_id] = value
        return SetSessionConfigOptionResponse(
            config_options=advertised_settings(self.agent.models, **self.agent.values)
        )

    async def close(self):
        pass


class PickerAgent(Agent):
    """An agent object that advertises the catalogue and answers model changes without a process."""

    def __init__(self, *args, models, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = []
        self.config_calls = []
        self.models = models
        self.values = {
            "model": next(iter(models)),
            "thinking_level": "low",
            "service_tier": "standard",
        }
        self.process.connection = PickerRpc(self)
        self.configuration.receive(advertised_settings(models, **self.values))

    async def set_model(self, model_id):
        self.calls.append(model_id)
        if model_id == "test/unavailable":
            return "Model unavailable"
        self.values["model"] = model_id
        self.configuration.receive(advertised_settings(self.models, **self.values))
        return None


class Picker:
    def __init__(self, ui, agent, db):
        self.ui, self.agent, self.db = ui, agent, db
        self.conversation = ui.conversation
        self.prompt = self.conversation.prompt
        self.widget = self.prompt.model_switcher
        _app, self.pilot = ui.textual

    @property
    def selection(self):
        return self.widget.query_one(SessionModelEditor)

    def ids(self):
        options = self.selection.option_list
        return [options.get_option_at_index(i).id for i in range(options.option_count)]

    async def open_with_command(self):
        await CommandCatalog.execute("/model", self.conversation)
        await self.ui.until(lambda: self.widget.is_open, why="the picker to open")
        await self.ui.step()

    async def recents(self):
        return await self.db.recent_models(SCOPE)

    def setting_editor(self, kind):
        return next(
            row.editor
            for row in self.widget.form.values.values()
            if isinstance(row.field.metadata(AdvertisedSetting).setting, kind)
        )

    async def focus_with_tab(self, target):
        visited = []
        for _ in range(12):
            if target.has_focus_within:
                return
            await self.ui.press("tab")
            focused = self.ui.app.focused
            visited.append(None if focused is None else type(focused).__name__)
        raise AssertionError(
            f"Tab never reached {type(target).__name__}; focus sequence={visited}"
        )

    async def wheel_down(self, target):
        arguments = _get_mouse_message_arguments(
            target, (target.size.width - 1, min(2, target.size.height - 1))
        )
        await self.ui.app._post_message_and_wait(events.MouseScrollDown(**arguments))
        await self.ui.step()


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
    assert picker.selection.search_input.has_focus and not picker.selection.search_input.value
    await picker.ui.press(*"gpt 5.4")
    assert picker.ids()[0] == GPT
    await picker.ui.press("enter")
    await picker.ui.until(lambda: picker.agent.configuration.model.current == GPT, why="the model change")
    assert picker.widget.is_open, "The live settings stay open for related choices"
    async def first():
        return (await picker.recents())[0] == GPT
    await picker.ui.until(first, why="the chosen model first in recent models")
    assert await picker.pilot.click(picker.widget.query_one(FinishSessionSettings))
    await picker.ui.until(lambda: not picker.widget.is_open, why="Done to close the settings")


async def open_by_clicking_the_model(picker):
    before = await picker.recents()
    assert await picker.pilot.click(picker.prompt.query_one(AgentInfo))
    await picker.ui.until(lambda: picker.selection.recent_ids == before, why="recent models in the picker")
    await picker.ui.step()
    return before


def row_style(options, y: int):
    """The first cell's style on row y, as the option list paints it."""
    return list(options.render_line(y, options._paint_state))[0].style


async def test_opening_the_picker_focuses_search_and_lists_recent_models_first(workspace):
    async with picker_session(workspace) as picker:
        widget = picker.widget
        await open_by_clicking_the_model(picker)
        assert picker.selection.search_input.has_focus
        assert picker.ids()[:3] == [SONNET, GPT, GLM]
        highlighted_style = row_style(picker.selection.option_list, 0)
        assert highlighted_style.color != highlighted_style.bgcolor
        assert highlighted_style.bgcolor != row_style(picker.selection.option_list, 1).bgcolor
        assert "retired/model" not in picker.ids()


async def test_hover_and_arrow_keys_move_the_highlight_without_taking_focus_from_search(workspace):
    async with picker_session(workspace) as picker:
        widget, ui = picker.widget, picker.ui
        await open_by_clicking_the_model(picker)
        await picker.pilot.hover(picker.selection.option_list, offset=(2, 1))
        await ui.step()
        assert picker.selection.option_list.highlighted == 1
        assert picker.selection.search_input.has_focus
        await ui.press("down")
        assert picker.selection.option_list.highlighted == 2
        assert picker.selection.option_list._mouse_hovering_over is None
        assert row_style(picker.selection.option_list, 1).bgcolor != row_style(picker.selection.option_list, 2).bgcolor


async def test_typing_filters_models_fuzzily_and_escape_closes_without_a_change(workspace):
    async with picker_session(workspace) as picker:
        widget, ui = picker.widget, picker.ui
        ui.textual[0].set_keymap({ClearModelSearchAction.binding_id(TextEntryMode): "f9"})
        before = await open_by_clicking_the_model(picker)
        await ui.press(*"SONNET anthr")
        assert picker.ids() == [SONNET]
        assert picker.prompt.text == "Keep this unfinished draft"
        assert not picker.prompt.prompt_text_area.suggestion
        await ui.press("f9", *"cldsnt")
        assert picker.ids() == [SONNET]
        await ui.press("f9", *"zzzzzzzzz", "down", "up", "enter")
        assert not picker.ids() and widget.is_open and not picker.agent.calls
        await ui.press("escape")
        assert not widget.is_open and picker.prompt.prompt_text_area.has_focus
        assert await picker.recents() == before


async def test_choosing_the_current_model_does_not_reapply_it(workspace):
    async with picker_session(workspace) as picker:
        await picker.open_with_command()
        await picker.ui.press(*"glm")
        assert await picker.pilot.click(picker.selection.option_list, offset=(2, 0))
        await picker.ui.step()
        assert picker.widget.is_open
        await picker.ui.press("escape")
        assert not picker.agent.calls, "Opening the current model must not reapply it"


async def test_choosing_another_model_applies_it_and_makes_it_the_most_recent(workspace):
    async with picker_session(workspace) as picker:
        await choose_gpt(picker)
        assert picker.prompt.text == "Keep this unfinished draft"
        await picker.open_with_command()
        await picker.ui.until(lambda: picker.selection.recent_ids[0] == GPT, why="the chosen model first in the picker")
        assert picker.ids()[0] == GPT


async def test_model_settings_remain_reachable_after_scrolling_the_catalogue(workspace):
    async with picker_session(workspace) as picker:
        await picker.ui.resize(80, 18)
        await picker.open_with_command()
        assert len(picker.ids()) == 444
        configuration = picker.agent.configuration
        assert SessionForm.settings(configuration) == PopupSessionForm.settings(configuration)
        assert [
            type(row.field.metadata(AdvertisedSetting).setting)
            for row in picker.widget.form.values.values()
        ] == [
            ModelConfigurationSetting,
            ThinkingConfigurationSetting,
            ServiceTierConfigurationSetting,
        ]
        assert picker.selection.current == configuration.model.current

        options = picker.selection.option_list
        before = options.scroll_y
        await picker.wheel_down(options)
        assert options.scroll_y > before, "The pointer must scroll the bounded catalogue"

        picker.selection.search_input.clear()
        await picker.ui.press(*"gpt 5.4", "enter")
        await picker.ui.until(
            lambda: picker.agent.configuration.model.current == GPT,
            why="the model selection",
        )
        await picker.ui.until(
            lambda: picker.widget.form.represents(picker.agent.configuration),
            why="the dependent settings rebuild",
        )

        await picker.ui.until(
            lambda: bool(picker.selection.recent_ids),
            why="the rebuilt model editor's recent choices",
        )
        thinking = picker.setting_editor(ThinkingConfigurationSetting)
        service = picker.setting_editor(ServiceTierConfigurationSetting)
        done = picker.widget.query_one(FinishSessionSettings)
        assert isinstance(thinking, ChoicesEditor) and isinstance(service, ChoicesEditor)
        await picker.ui.until(
            lambda: thinking.is_mounted and service.is_mounted and done.is_mounted,
            why="every advertised setting and Done to mount",
        )
        await picker.ui.step()

        await picker.focus_with_tab(thinking)
        await picker.ui.press("enter")
        await picker.ui.until(lambda: thinking.expanded, why="the keyboard-opened thinking choices")
        await picker.ui.press("down", "enter")
        await picker.ui.until(
            lambda: ("thinking_level", "high") in picker.agent.config_calls,
            why="the thinking setting request",
        )
        await picker.ui.until(
            lambda: picker.agent.configuration.thinking.current == "high",
            why="the keyboard-selected thinking level",
        )
        await picker.ui.until(
            lambda: picker.widget.form.represents(picker.agent.configuration),
            why="the form after the thinking selection",
        )

        service = picker.setting_editor(ServiceTierConfigurationSetting)
        assert isinstance(service, ChoicesEditor)
        await picker.ui.until(lambda: service.is_mounted, why="the Service tier field to mount")
        form = picker.widget.query_one(PopupSessionForm)
        scrollbar = form.vertical_scrollbar
        await picker.ui.until_clickable(
            scrollbar,
            (0, scrollbar.size.height - 2),
            why="the settings-form scrollbar",
        )
        for _ in range(8):
            assert await picker.pilot.click(
                scrollbar, offset=(0, scrollbar.size.height - 2)
            )
        await picker.pilot.click(service, offset=(service.size.width - 2, 1))
        await picker.ui.until(lambda: service.expanded, why="the pointer-opened service choices")
        await picker.ui.click("Priority")
        await picker.ui.until(
            lambda: picker.agent.configuration.setting(ServiceTierConfigurationSetting).current
                    == "priority",
            why="the pointer-selected service tier",
        )
        await picker.ui.until(
            lambda: picker.widget.form.represents(picker.agent.configuration),
            why="the form after the service-tier selection",
        )

        done = picker.widget.query_one(FinishSessionSettings)
        await picker.focus_with_tab(done)
        await picker.ui.press("enter")
        await picker.ui.until(lambda: not picker.widget.is_open, why="keyboard Done")

        await picker.open_with_command()
        done = picker.widget.query_one(FinishSessionSettings)
        assert await picker.pilot.click(done)
        await picker.ui.until(lambda: not picker.widget.is_open, why="pointer Done")
        assert picker.agent.values == {
            "model": GPT,
            "thinking_level": "high",
            "service_tier": "priority",
        }


async def test_the_picker_stays_inside_the_screen_when_it_is_resized(workspace):
    async with picker_session(workspace) as picker:
        await picker.open_with_command()
        for width, height in ((80, 24), (96, 18), (120, 40)):
            await picker.ui.resize(width, height)
            widget = picker.widget
            assert widget.region.x >= 0 and widget.region.right <= width
            assert widget.region.y >= 0 and widget.region.bottom <= height
            assert picker.selection.search_input.region.y < picker.selection.option_list.region.y
            done = widget.query_one(FinishSessionSettings)
            assert done.region.y >= widget.region.y and done.region.bottom <= widget.region.bottom
        options = picker.selection.option_list
        assert options.max_scroll_y > 0, "The long catalogue must scroll inside its own list"
        assert options.scrollbar_gutter.width > 0, "The scrollable catalogue must reserve a visible gutter"


async def test_a_model_the_agent_refuses_is_not_applied_or_recorded(workspace):
    async with picker_session(workspace) as picker:
        await choose_gpt(picker)
        await picker.open_with_command()
        async with picker.ui.reporting_error():
            await picker.ui.press(*"unavailable", "enter")
        await picker.ui.until(lambda: picker.agent.calls[-1] == "test/unavailable", why="the refused request")
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
            f"import asyncio,json; from toad.client.db import DB; print(json.dumps(asyncio.run(DB().recent_models({SCOPE!r}))))",
        ], text=True))
        assert history[0] == SONNET
        assert history.count(GPT) == 1
