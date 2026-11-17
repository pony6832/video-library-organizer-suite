"""Keep the version in the shipped documents equal to pyproject.toml.

``sync``   rewrite the version strings in place (run after bumping the version)
``check``  fail when a document still names another version (build and CI)
``notes``  write the testers' note for a built installer, with its SHA-256
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys
import tomllib

PROJECT = Path(__file__).resolve().parents[1]
REPOSITORY_URL = "https://github.com/pony6832/video-library-organizer-suite"
_VERSION = re.compile(r"^(\d+\.\d+\.\d+)(?:(b|rc)(\d+))?$")
_STAGE_LABELS = {"b": "Beta", "rc": "RC"}
_STAGE_TAGS = {"b": "beta", "rc": "rc"}
_LABEL = r"\d+\.\d+\.\d+(?: (?:Beta|RC) \d+)?"
_TAG = r"\d+\.\d+\.\d+(?:-(?:beta|rc)\.\d+)?"


def project_version() -> str:
    with open(PROJECT / "pyproject.toml", "rb") as source:
        return tomllib.load(source)["project"]["version"]


def version_label(version: str) -> str:
    """0.3.0b7 -> '0.3.0 Beta 7' (the wording used in the documents)."""
    base, stage, number = _parse(version)
    return f"{base} {_STAGE_LABELS[stage]} {number}" if stage else base


def version_tag(version: str) -> str:
    """0.3.0b7 -> '0.3.0-beta.7' (release tags and installer file names)."""
    base, stage, number = _parse(version)
    return f"{base}-{_STAGE_TAGS[stage]}.{number}" if stage else base


def _parse(version: str) -> tuple[str, str | None, str | None]:
    match = _VERSION.fullmatch(version)
    if match is None:
        raise ValueError(f"Unsupported version format: {version}")
    return match.group(1), match.group(2), match.group(3)


def _rules(version: str) -> dict[Path, list[tuple[str, str]]]:
    label, tag = version_label(version), version_tag(version)
    return {
        PROJECT / "packaging" / "README-zh-TW.md": [
            (rf"(Windows 桌面版 ){_LABEL}", rf"\g<1>{label}"),
            (rf"VideoLibraryOrganizer-{_TAG}-Setup\.exe", f"VideoLibraryOrganizer-{tag}-Setup.exe"),
        ],
        PROJECT / "src" / "media_catalog" / "_version.py": [
            (r'(VERSION = ")[^"]+(")', rf"\g<1>{version}\g<2>"),
        ],
        PROJECT / "README.md": [
            (rf"(目前版本：\*\*){_LABEL}(\*\*)", rf"\g<1>{label}\g<2>"),
        ],
    }


def synced_text(path: Path, rules: list[tuple[str, str]]) -> tuple[str, str]:
    original = path.read_bytes().decode("utf-8")
    updated = original
    for pattern, replacement in rules:
        updated, count = re.subn(pattern, replacement, updated)
        if count == 0:
            raise ValueError(f"{path.name}: nothing matches {pattern!r}")
    return original, updated


def stale_documents(version: str | None = None) -> list[Path]:
    version = version or project_version()
    stale = []
    for path, rules in _rules(version).items():
        original, updated = synced_text(path, rules)
        if original != updated:
            stale.append(path)
    return stale


def sync(version: str | None = None) -> list[Path]:
    version = version or project_version()
    changed = []
    for path, rules in _rules(version).items():
        original, updated = synced_text(path, rules)
        if original != updated:
            path.write_bytes(updated.encode("utf-8"))
            changed.append(path)
    return changed


def tester_notes(setup: Path, version: str | None = None) -> str:
    version = version or project_version()
    digest = hashlib.sha256(setup.read_bytes()).hexdigest().upper()
    template = (PROJECT / "packaging" / "tester-notes.template.txt").read_bytes().decode("utf-8")
    return (
        template.replace("{{VERSION_LABEL}}", version_label(version))
        .replace("{{VERSION_TAG}}", version_tag(version))
        .replace("{{SETUP_NAME}}", setup.name)
        .replace("{{SHA256}}", digest)
        .replace("{{REPOSITORY_URL}}", REPOSITORY_URL)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("sync")
    commands.add_parser("check")
    commands.add_parser("tag")
    notes = commands.add_parser("notes")
    notes.add_argument("setup", type=Path)
    notes.add_argument("output", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "sync":
        for path in sync():
            print(f"updated {path.relative_to(PROJECT)}")
        return 0
    if arguments.command == "check":
        stale = stale_documents()
        for path in stale:
            print(f"version out of date: {path.relative_to(PROJECT)}", file=sys.stderr)
        if stale:
            print("run: python packaging/release_docs.py sync", file=sys.stderr)
        return 1 if stale else 0
    if arguments.command == "tag":
        print(version_tag(project_version()))
        return 0
    arguments.output.write_bytes(tester_notes(arguments.setup).encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
