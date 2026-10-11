"""A link in chat text decodes to the project file it names, a search by file name, an external address or a missing file."""

import pytest

from toad.project_link import (
    AmbiguousProjectFile, DirectProjectFileLink, ExternalProjectLink, MissingProjectFileLink,
    ProjectLink, ProjectLinkProblem, SearchProjectFileLink,
)


@pytest.fixture
def project(tmp_path):
    root = (tmp_path / "project").resolve()
    plan = root / "plans" / "tag-channel-view-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Previewed plan\n")
    return root, plan


def decode(root, href):
    return ProjectLink.from_href(lambda: root, href)


def test_absolute_and_relative_spellings_name_the_same_existing_file(project):
    root, plan = project
    assert decode(root, str(plan)) == DirectProjectFileLink(plan)
    assert decode(root, "plans/tag-channel-view-plan.md") == DirectProjectFileLink(plan)
    assert decode(root, plan.as_uri()) == DirectProjectFileLink(plan)


def test_web_addresses_stay_external(project):
    root, _ = project
    assert decode(root, "https://example.com/preview.py") == ExternalProjectLink("https://example.com/preview.py")
    assert decode(root, "https://example.com/plans/tag-channel-view-plan.md").href.startswith("https://")


def test_a_bare_file_name_that_is_not_at_the_root_is_searched_for(project):
    root, _ = project
    assert decode(root, "missing.py") == SearchProjectFileLink("missing.py")
    assert decode(root, "plans/missing.md") == MissingProjectFileLink("plans/missing.md")


async def test_a_unique_file_name_resolves_to_its_nested_path(project):
    root, _ = project
    nested = root / "src" / "agent_comms" / "declarations.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("# NESTED-DECLARATIONS-MARKER\n")
    link = decode(root, "declarations.py")
    assert link == SearchProjectFileLink("declarations.py")
    assert await link.resolve(root) == nested
    assert decode(root, f"{nested}") == DirectProjectFileLink(nested)


async def test_a_file_name_found_twice_is_ambiguous_and_a_file_name_found_nowhere_is_missing(project):
    root, _ = project
    for place in ("src/agent_comms", "other"):
        (root / place).mkdir(parents=True, exist_ok=True)
        (root / place / "declarations.py").write_text("# declaration\n")
    with pytest.raises(AmbiguousProjectFile) as ambiguous:
        await SearchProjectFileLink("declarations.py").resolve(root)
    assert "Several files named declarations.py" in ambiguous.value.notice
    with pytest.raises(ProjectLinkProblem):
        await SearchProjectFileLink("absent.py").resolve(root)
