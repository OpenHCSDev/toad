"""External decode is confined to the request; root never selects a presentation."""
import ast
from pathlib import Path


def test_deleted_dispatch():
    root=Path(__file__).parents[2]
    tree=ast.parse((root/'src/toad/widgets/conversation.py').read_text())
    body=next(node for node in ast.walk(tree) if isinstance(node,ast.AsyncFunctionDef)
              and node.name=='request_permissions')
    assert not any(isinstance(node,(ast.If,ast.For,ast.Match)) for node in ast.walk(body))
    assert not any(isinstance(node,ast.Attribute) and node.attr=='tool_call' for node in ast.walk(body))
    controller=ast.parse((root/'src/toad/acp/permission_controller.py').read_text())
    assert not any(isinstance(node,ast.Attribute) and node.attr=='_tool_call' for node in ast.walk(controller))


async def new_case():
    from toad.permission_presentation import PermissionPresentation
    class ProbePermissionPresentation(PermissionPresentation):
        priority=1
        @classmethod
        def admit(cls, kind, title, content):
            return cls(title) if kind=='probe' else None
        async def show(self, view, request):
            view.prompt.text=self.title
    selected=PermissionPresentation.from_acp({'kind':'probe','title':'Declaration-owned permission'})
    assert isinstance(selected,ProbePermissionPresentation)
    # All production callers share the inherited eligibility/lifetime contract.
    assert ProbePermissionPresentation.present is PermissionPresentation.present


if __name__=='__main__':
    import asyncio
    test_deleted_dispatch()
    asyncio.run(new_case())
    print('permission family declaration-only discovery and removed raw root/store guards pass')
