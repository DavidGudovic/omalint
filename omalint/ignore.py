"""Findings the user has accepted: read the ignore rules and set matching findings aside."""

from __future__ import annotations

from .inventory import SECTIONS, shell_id

PLUGIN_ID = "io.github.davidgudovic.omalint"


def parse(value) -> list:
    """Rules from a comma-separated string or a list of strings; anything else holds none."""
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def from_config(config) -> list:
    """The rules set on OmaLint's own bar entry in shell.json (the dict the inventory parsed)."""
    bar = config.get("bar") if isinstance(config, dict) else None
    layout = bar.get("layout") if isinstance(bar, dict) else None
    if not isinstance(layout, dict):
        return []
    rules = []
    for section in SECTIONS:
        entries = layout.get(section)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, dict) and shell_id(entry.get("id")) == PLUGIN_ID:
                rules += parse(entry.get("ignore"))
    return rules


def apply(results: dict, rules) -> None:
    """Move the findings the rules match from each result's findings to its ignored list."""
    # A rule is CODE or CODE:SUBJECT; only the first colon separates them.
    wanted = [rule.partition(":") for rule in rules]

    def matches(finding) -> bool:
        return any(code == finding.code and (not colon or subject == finding.subject) for code, colon, subject in wanted)

    for result in results.values():
        kept = []
        for finding in result.findings:
            (result.ignored if matches(finding) else kept).append(finding)
        result.findings = kept
