"""The external ACP catalogue shared by the picker peer and its UI assertions."""

from acp.schema import SessionConfigSelectOption

GLM = "openrouter/z-ai/glm-5.3-flash"
SONNET = "openrouter/anthropic/claude-sonnet-4.6"
GPT = "openrouter/openai/gpt-5.4"


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
