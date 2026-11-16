"""pydantic-core, matching the pydantic Toad runs; its source now ships on PyPI, not as a tag."""
from pythonforandroid.recipe import RustCompiledComponentsRecipe


class PydanticcoreRecipe(RustCompiledComponentsRecipe):
    version = "2.46.5"
    url = "https://files.pythonhosted.org/packages/source/p/pydantic-core/pydantic_core-{version}.tar.gz"
    site_packages_name = "pydantic_core"


recipe = PydanticcoreRecipe()
