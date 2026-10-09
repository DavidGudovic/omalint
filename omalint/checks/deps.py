"""Dependencies: commands a plugin says it needs that are not installed.

Plugin manifests have no dependency field, so the README's requirements
section is the declaration. Reading prose is a heuristic: only `backticked`
names in that section's lists and tables count, and anything worded as
optional is reported as a note rather than a warning.
"""

from __future__ import annotations

import os
import re
import shutil

from ..inventory import Inventory, Plugin
from ..model import INFO, WARN, Context, Finding, Result

TITLE = "Dependencies"

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_SECTION = re.compile(r"requirement|dependenc|prerequisite|requires", re.I)
_OPTIONAL = re.compile(
    r"\b(optional(ly)?|only (for|to|if|when|needed|used|required)|recommended|if you (want|use|have))\b", re.I
)
_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_TOKEN = re.compile(r"`([^`\n]+)`")
_COMMAND = re.compile(r"^[a-z0-9][a-z0-9+_-]{1,39}$")
_BINARY_PATH = re.compile(r"^/(?:usr/(?:local/)?)?s?bin/[A-Za-z0-9+._-]+$")
_NOT_COMMANDS = {"true", "false", "null", "left", "right", "center", "top", "bottom"}
# Backticks also mark things that are not programs: "the `requests` and `psutil` modules",
# "your user in the `i2c` group", "set `enabled` to `true`".
_NOUNS = (r"modules?|librar(?:y|ies)|groups?|scopes?|options?|settings?|keys?|fields?|propert(?:y|ies)|flags?"
          r"|variables?|extensions?|plugins?|fonts?|themes?|services?|permissions?|drivers?|protocols?")
_RUN = r"`[^`\n]+`(?:(?:\s*,\s*(?:and\s+|or\s+)?|\s+and\s+|\s+or\s+)`[^`\n]+`)*"
_DESCRIBED = re.compile(rf"{_RUN}(?=\s+(?:python\s+|kernel\s+)?(?:{_NOUNS})\b)", re.I)
_INTRODUCED = re.compile(rf"\b(?:set|{_NOUNS})\s+{_RUN}", re.I)
_CHECK = 'for c in "$@"; do command -v "$c" >/dev/null 2>&1 || printf "%s\\n" "$c"; done'
MAX_README = 1024 * 1024


def _blocks(text: str) -> list:
    """(text, optional) for each list item, table row or paragraph in a requirements section."""
    blocks, current = [], []
    state = {"kind": "", "in": False, "level": 0, "optional": False}

    def flush():
        if current:
            blocks.append((state["kind"], " ".join(current), state["optional"]))
            current.clear()

    fenced = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
            flush()
            continue
        if fenced:
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            depth, title = len(heading.group(1)), heading.group(2)
            if not (state["in"] and depth > state["level"]):
                state["in"], state["level"] = bool(_SECTION.search(title)), depth
            state["optional"] = "optional" in title.lower()
            continue
        if not state["in"]:
            continue
        if not stripped:
            flush()
        elif _ITEM.match(line):
            flush()
            state["kind"] = "item"
            current.append(stripped)
        elif stripped.startswith("|"):
            flush()
            blocks.append(("item", stripped, state["optional"]))
        elif current:
            current.append(stripped)
        else:
            state["kind"] = "paragraph"
            current.append(stripped)
    flush()

    items = [(body, optional) for kind, body, optional in blocks if kind == "item"]
    if items:
        return items
    # A section written as prose: its opening paragraph is the requirement list.
    return [(body, optional) for _, body, optional in blocks[:1]]


def readme_requirements(text: str) -> dict:
    """{name: optional} for every command or binary path a README's requirements name."""
    found = {}
    for body, optional in _blocks(text):
        optional = optional or bool(_OPTIONAL.search(body))
        body = _INTRODUCED.sub(" ", _DESCRIBED.sub(" ", body))
        for token in _TOKEN.findall(body):
            words = token.split()
            name = words[0] if words else ""
            if not (_BINARY_PATH.match(name) or (_COMMAND.match(name) and name not in _NOT_COMMANDS)):
                continue
            if name.isdigit():
                continue
            # Required wins when a name is listed both ways.
            found[name] = found.get(name, True) and optional
    return found


def manifest_requirements(manifest) -> list:
    names = []
    for key in ("dependencies", "requires"):
        value = manifest.get(key) if isinstance(manifest, dict) else None
        if isinstance(value, dict):
            value = list(value)
        if isinstance(value, list):
            names += [v for v in value if isinstance(v, str) and (_COMMAND.match(v) or _BINARY_PATH.match(v))]
    return names


def _readme(plugin: Plugin) -> str:
    for name in ("README.md", "readme.md", "README"):
        path = plugin.dir / name
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8", errors="replace")[:MAX_README]
            except OSError:
                return ""
    return ""


def missing(ctx: Context, names) -> set:
    """The names that are neither a command on PATH nor an installed package."""
    paths = {n for n in names if n.startswith("/")}
    commands = sorted(set(names) - paths)
    absent = {p for p in paths if not os.path.exists(p)}
    if not commands:
        return absent
    run = ctx.run(["sh", "-c", _CHECK, "sh"] + commands, env=dict(os.environ, PATH=ctx.path_env))
    if run.status == "ok":
        gone = set(run.out.split()) & set(commands)
    else:
        gone = {c for c in commands if shutil.which(c, path=ctx.path_env) is None}
    if gone:
        # Requirement lists often name the package instead of its command (pciutils for lspci).
        packages = ctx.run(["pacman", "-Qq"] + sorted(gone))
        if packages.status == "ok":
            gone -= set(packages.out.split())
    return absent | gone


def _names(items) -> str:
    items = [f"`{item}`" for item in sorted(items)]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def check(ctx: Context, inv: Inventory) -> Result:
    result = Result()
    declared = {}
    for plugin in inv.third_party:
        required = {name: "manifest.json" for name in manifest_requirements(plugin.manifest)}
        optional = set()
        for name, is_optional in readme_requirements(_readme(plugin)).items():
            if is_optional:
                optional.add(name)
            else:
                required.setdefault(name, "README")
        declared[plugin.label] = (plugin, required, optional - set(required))

    everything = set()
    for _, required, optional in declared.values():
        everything |= set(required) | optional
    gone = missing(ctx, everything)

    for label, (plugin, required, optional) in sorted(declared.items()):
        absent = sorted(set(required) & gone)
        if absent:
            sources = sorted({required[name] for name in absent})
            result.findings.append(Finding(
                "deps", "deps.missing", WARN, label,
                f"{label} needs {_names(absent)} according to its {' and '.join(sources)}, "
                f"but {'it is' if len(absent) == 1 else 'they are'} not installed.",
                # No install command here: omalint reports, it does not manage packages.
                f"Install the package that provides {'it' if len(absent) == 1 else 'each one'}; "
                "the plugin's README says what it is used for.",
                ctx.display(plugin.dir),
            ))
        absent = sorted(optional & gone)
        if absent:
            result.findings.append(Finding(
                "deps", "deps.optional-missing", INFO, label,
                f"{label} can use {_names(absent)}, which {'is' if len(absent) == 1 else 'are'} not installed; "
                "its README marks that as optional.",
                "Install it only if you want the feature it enables.",
                ctx.display(plugin.dir),
            ))

    result.notes.append(
        f"{len(everything)} declared command{'s' if len(everything) != 1 else ''} checked with `command -v`."
    )
    return result
