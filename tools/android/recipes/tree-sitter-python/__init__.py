"""The Python grammar for tree-sitter, from the GitHub release: the 0.25.0 PyPI sdist leaves out src/scanner.c."""
from pythonforandroid.recipe import PyProjectRecipe


class TreeSitterPythonRecipe(PyProjectRecipe):
    version = "0.25.0"
    url = "https://github.com/tree-sitter/tree-sitter-python/archive/refs/tags/v{version}.tar.gz"
    site_packages_name = "tree_sitter_python"
    depends = ["setuptools"]


recipe = TreeSitterPythonRecipe()
