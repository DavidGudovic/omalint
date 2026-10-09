"""Turn check results into the terminal report or the --json document."""

from __future__ import annotations

import textwrap

from .checks import CHECKS
from .model import ERROR, INFO, WARN

_STYLE = {"red": "31", "green": "32", "yellow": "33", "dim": "2", "bold": "1"}
_BADGE = {"error": ("ERROR", "red"), "warn": ("WARN", "yellow"), "ok": ("OK", "green"), "skipped": ("SKIP", "dim")}
_MARK = {ERROR: ("✗", "red"), WARN: ("!", "yellow"), INFO: ("•", "dim")}
INDENT = " " * 9


def status(result) -> str:
    severities = {finding.severity for finding in result.findings}
    if ERROR in severities:
        return "error"
    if WARN in severities:
        return "warn"
    return "skipped" if result.skipped else "ok"


def summary(results: dict) -> dict:
    findings = [finding for result in results.values() for finding in result.findings]
    return {
        "errors": sum(f.severity == ERROR for f in findings),
        "warnings": sum(f.severity == WARN for f in findings),
        "notes": sum(f.severity == INFO for f in findings),
        "fixable": sum(f.fixable for f in findings),
    }


def as_json(results: dict, version: str, plugins: int) -> dict:
    totals = summary(results)
    return {
        "tool": "omadoctor",
        "version": version,
        "ok": totals["errors"] == 0,
        "summary": dict(totals, plugins=plugins),
        "checks": [
            {
                "id": name,
                "title": CHECKS[name].TITLE,
                "status": status(result),
                "findings": [finding.to_json() for finding in result.findings],
                "notes": result.notes,
            }
            for name, result in results.items()
        ],
    }


def _count(number: int, word: str) -> str:
    return f"{number} {word}{'' if number == 1 else 's'}"


def headline(totals: dict) -> str:
    if not (totals["errors"] or totals["warnings"]):
        return "No problems found."
    parts = [_count(totals[key], word) for key, word in (("errors", "error"), ("warnings", "warning")) if totals[key]]
    return " and ".join(parts) + " found."


def as_text(results: dict, color: bool, width: int = 100, title: str = "") -> str:
    def paint(text, style):
        return f"\x1b[{_STYLE[style]}m{text}\x1b[0m" if color else text

    def wrap(text, first, rest):
        lines = textwrap.wrap(
            text, max(40, width), initial_indent=first, subsequent_indent=rest,
            break_long_words=False, break_on_hyphens=False,
        )
        return lines or [first]

    lines = [paint(title, "bold"), ""] if title else []
    for name, result in results.items():
        label, style = _BADGE[status(result)]
        lines.append(f"  {paint(label.ljust(6), style)} {paint(CHECKS[name].TITLE, 'bold')}")
        for finding in result.findings:
            mark, mark_style = _MARK[finding.severity]
            text = finding.message
            if finding.subject and finding.subject not in text:
                text = f"{finding.subject}: {text}"
            body = wrap(text, INDENT + "  ", INDENT + "  ")
            body[0] = INDENT + paint(mark, mark_style) + body[0][len(INDENT) + 1:]
            lines += body
            if finding.fix:
                fix = finding.fix + (" (`omadoctor --fix` does this.)" if finding.fixable else "")
                lines += [paint(line, "dim") for line in wrap(fix, INDENT + "  → ", INDENT + "    ")]
        lines += [paint(line, "dim") for note in result.notes for line in wrap(note, INDENT, INDENT)]
        lines.append("")

    totals = summary(results)
    closing = headline(totals)
    if totals["notes"]:
        closing += f" {_count(totals['notes'], 'note')} (•) need{'s' if totals['notes'] == 1 else ''} no action."
    if totals["fixable"]:
        closing += f" {_count(totals['fixable'], 'problem')} can be fixed automatically: omadoctor --fix"
    lines += wrap(closing, "  ", "  ")
    return "\n".join(lines) + "\n"
