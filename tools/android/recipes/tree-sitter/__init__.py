"""py-tree-sitter: a C extension with its runtime bundled; built for the APK like any pyproject."""
from pythonforandroid.recipe import PyProjectRecipe


class TreeSitterRecipe(PyProjectRecipe):
    version = "0.26.0"
    url = "https://files.pythonhosted.org/packages/source/t/tree-sitter/tree_sitter-{version}.tar.gz"
    site_packages_name = "tree_sitter"
    depends = ["setuptools"]


recipe = TreeSitterRecipe()
