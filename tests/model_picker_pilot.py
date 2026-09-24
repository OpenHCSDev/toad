"""Search, keyboard focus, confirmed recency, and persisted model history."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from textual.content import Content
from toad.acp.agent import Model
from toad.acp.messages import SetModels
from toad.agent import AgentBase
from toad.app import ToadApp
from toad.db import DB
from toad.widgets.prompt import AgentInfo


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.03)


class TestAgent(AgentBase):
    def __init__(self, project, target, models):
        super().__init__(project)
        self.target = target
        self.models = models
        self.calls = []

    def get_info(self):
        return Content("Picker test")

    async def send_prompt(self, prompt):
        return "end_turn"

    async def set_model(self, model_id):
        self.calls.append(model_id)
        if model_id == "test/unavailable":
            return "Model unavailable"
        self.target.post_message(SetModels(model_id, self.models))
        return None


async def main():
    with tempfile.TemporaryDirectory(prefix="toad-model-picker-") as directory:
        root = Path(directory)
        os.environ.update(
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_STATE_HOME=str(root / "state"),
            XDG_DATA_HOME=str(root / "data"),
            AGENT_COMMS_ROOT=str(root / "wire"),
        )
        glm = "openrouter/z-ai/glm-5.3-flash"
        sonnet = "openrouter/anthropic/claude-sonnet-4.6"
        gpt = "openrouter/openai/gpt-5.4"
        models = {
            model.id: model
            for model in (
                Model(glm, "GLM 5.3 Flash", "Fast coding model"),
                Model(sonnet, "Claude Sonnet 4.6", "Balanced coding model"),
                Model(gpt, "GPT 5.4", "OpenRouter"),
                Model("openai/gpt-5.4", "GPT 5.4 direct", "OpenAI"),
                Model("test/unavailable", "Unavailable model", None),
            )
        }
        models.update(
            {
                f"test/model-{n:04}": Model(f"test/model-{n:04}", f"Model {n:04}", None)
                for n in range(1000)
            }
        )
        app = ToadApp(project_dir=str(root))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            conversation = app.screen.conversation
            agent = TestAgent(root, conversation, models)
            # Install the fixture without restarting the already-mounted shell
            # view's lifecycle / filesystem watchers.
            conversation.set_reactive(type(conversation).agent, agent)
            conversation.model_history_scope = "picker-test"
            conversation.post_message(SetModels(glm, models))
            await until(lambda: conversation.current_model is not None)
            db = DB()
            await db.record_model_usage("picker-test", gpt)
            await db.record_model_usage("picker-test", sonnet)
            await db.record_model_usage("picker-test", "retired/model")
            await db.record_model_usage("other-agent", glm)
            before = await db.recent_models("picker-test")
            conversation.prompt.text = "Keep this unfinished draft"
            picker = conversation.prompt.model_switcher

            def ids():
                return [
                    picker.option_list.get_option_at_index(i).id
                    for i in range(picker.option_list.option_count)
                ]

            assert await pilot.click(conversation.prompt.query_one(AgentInfo))
            await until(lambda: picker.recent_ids == before)
            await pilot.pause()
            assert picker.search_input.has_focus
            assert ids()[:3] == [sonnet, gpt, glm]
            highlighted_style = list(picker.option_list.render_line(0))[0].style
            assert highlighted_style.color != highlighted_style.bgcolor
            assert (
                highlighted_style.bgcolor
                != list(picker.option_list.render_line(1))[0].style.bgcolor
            )
            assert "retired/model" not in ids()
            await pilot.hover(picker.option_list, offset=(2, 1))
            await pilot.pause()
            assert picker.option_list.highlighted == 1
            assert picker.search_input.has_focus
            await pilot.press("down")
            await pilot.pause()
            assert picker.option_list.highlighted == 2
            assert picker.option_list._mouse_hovering_over is None
            assert (
                list(picker.option_list.render_line(1))[0].style.bgcolor
                != list(picker.option_list.render_line(2))[0].style.bgcolor
            )
            await pilot.press(*"SONNET anthr")
            await pilot.pause()
            assert ids() == [sonnet]
            assert conversation.prompt.text == "Keep this unfinished draft"
            assert not conversation.prompt.prompt_text_area.suggestion
            await pilot.press("ctrl+u", *"cldsnt")
            await pilot.pause()
            assert ids() == [sonnet]
            await pilot.press("ctrl+u", *"zzzzzzzzz", "down", "up", "enter")
            await pilot.pause()
            assert not ids() and picker.is_open and not agent.calls
            await pilot.press("escape")
            await pilot.pause()
            assert not picker.is_open and conversation.prompt.prompt_text_area.has_focus
            assert await db.recent_models("picker-test") == before

            await conversation.slash_command("/model")
            await pilot.pause()
            await pilot.press(*"glm")
            await pilot.pause()
            assert await pilot.click(picker.option_list, offset=(2, 0))
            await until(lambda: agent.calls and agent.calls[-1] == glm)
            await pilot.pause()
            assert not picker.is_open

            await conversation.slash_command("/model")
            await pilot.pause()
            assert picker.search_input.has_focus and not picker.search_input.value
            await pilot.press(*"gpt 5.4")
            await pilot.pause()
            assert ids()[0] == gpt
            await pilot.press("enter")
            await until(lambda: conversation.current_model.id == gpt)
            for _ in range(50):
                if (await db.recent_models("picker-test"))[0] == gpt:
                    break
                await asyncio.sleep(0.03)
            assert (await db.recent_models("picker-test"))[0] == gpt
            assert conversation.prompt.text == "Keep this unfinished draft"

            await conversation.slash_command("/model")
            await pilot.pause()
            await until(lambda: picker.recent_ids[0] == gpt)
            assert ids()[0] == gpt
            for width, height in ((80, 24), (96, 18), (120, 40)):
                await pilot.resize_terminal(width, height)
                await pilot.pause()
                assert picker.region.x >= 0 and picker.region.right <= width
                assert picker.region.y >= 0 and picker.region.bottom <= height
                assert picker.search_input.region.y < picker.option_list.region.y
            await pilot.press(*"unavailable", "enter")
            await until(lambda: agent.calls[-1] == "test/unavailable")
            await pilot.pause()
            assert conversation.current_model.id == gpt
            assert "test/unavailable" not in await db.recent_models("picker-test")
            # Loading/receiving model state is not use. A completed turn is.
            conversation.post_message(SetModels(sonnet, models))
            await until(lambda: conversation.current_model.id == sonnet)
            assert (await db.recent_models("picker-test"))[0] == gpt
            await conversation.agent_turn_over("end_turn")
            assert (await db.recent_models("picker-test"))[0] == sonnet
            history = json.loads(
                subprocess.check_output(
                    [
                        sys.executable,
                        "-c",
                        "import asyncio,json; from toad.db import DB; print(json.dumps(asyncio.run(DB().recent_models('picker-test'))))",
                    ],
                    text=True,
                )
            )
            assert history[0] == sonnet
            assert history.count(gpt) == 1
    print(
        "model picker: fuzzy filtering, focus, recency persistence, failed selections and resizing passed"
    )


if __name__ == "__main__":
    asyncio.run(main())
