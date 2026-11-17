"""The release version, shipped inside the package.

PyInstaller builds carry no pip metadata, so the window reads the version from
here. ``packaging/release_docs.py sync`` rewrites ``VERSION`` from
pyproject.toml, and ``check`` fails the build when the two differ.
"""
from __future__ import annotations

import re

VERSION = "0.3.0"

_PATTERN = re.compile(r"^(\d+\.\d+\.\d+)(?:(b|rc)(\d+))?$")
_STAGES = {"b": "Beta", "rc": "RC"}


def display_version(version: str = VERSION) -> str:
    """0.3.0b8 -> '0.3.0 Beta 8'; a final release stays '0.3.0'."""
    match = _PATTERN.fullmatch(version)
    if match is None:
        return version
    base, stage, number = match.groups()
    return f"{base} {_STAGES[stage]} {number}" if stage else base
