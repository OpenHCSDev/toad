from toad.client.prompt_composer import PromptComposer


def test_editor_growth_is_bounded_by_the_shared_viewport_limit():
    assert PromptComposer.maximum_editor_viewport_percent == 50
    assert PromptComposer.visible_editor_lines(5, 800, 20, 20) == 5
    assert PromptComposer.visible_editor_lines(50, 800, 20, 20) == 19
    assert PromptComposer.visible_editor_lines(50, 20, 20, 20) == 1
