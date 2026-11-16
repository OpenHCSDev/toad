"""The packages python-for-android builds from recipes, read from the APK's buildozer.spec.in.

assemble.py leaves them out of the app folder (the build ships its compiled copies) and
bundle_check.py supplies them from SITE_PACKAGES, so both read this one list.
"""
import configparser
import re
from pathlib import Path

SPEC = Path(__file__).resolve().parent / "buildozer.spec.in"
# shiboken6's recipe also installs these top-level support modules.
SHIBOKEN_SUPPORT = {"shibokensupport", "signature_bootstrap"}


def import_names() -> set[str]:
    spec = configparser.ConfigParser(interpolation=None)
    spec.read(SPEC)
    requirements = spec["app"]["requirements"].split(",")
    names = {re.split(r"[=<>]", requirement.strip())[0].replace("-", "_") for requirement in requirements}
    names.discard("python3")
    return names | (SHIBOKEN_SUPPORT if "shiboken6" in names else set())
