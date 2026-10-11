"""A declared permission presentation is selected for its request kind without a root dispatch."""

from acp.schema import ToolCallUpdate

from toad.permission_presentation import PermissionPresentation


class ProbePermissionPresentation(PermissionPresentation):
    priority = 1

    @classmethod
    def admit(cls, kind, title, content):
        return cls(title) if kind == "read" else None


def test_a_declared_presentation_is_selected_for_its_kind():
    selected = PermissionPresentation.from_acp(ToolCallUpdate(
        tool_call_id="permission-probe", kind="read", title="Declaration-owned permission"))
    assert isinstance(selected, ProbePermissionPresentation)
    assert selected.title == "Declaration-owned permission"
