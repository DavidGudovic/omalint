"""Just enough Lua reading to find keybinding calls in Hyprland config files.

This is a scanner, not an interpreter: it finds `o.bind(...)`-style calls and
`require(...)` lines, and knows which block each one sits in. Bindings built at
run time (string concatenation, loops over tables) are invisible to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_LONG_OPEN = re.compile(r"\[(=*)\[")
_TOKEN = re.compile(
    r"\b(?P<block>function|if|do|repeat|end|until|else|elseif)\b"
    r"|\b(?P<call>o\.bind_toggle|o\.bind|hl\.bind|hl\.unbind)\s*\("
    r"|\b(?P<require>require_optional\.module|require)\b\s*\(?\s*(?P<quote>[\"'])"
)
_SHORT = re.compile(r"""^(["'])((?:\\.|(?!\1)[^\\\n])*)\1$""", re.S)
_LONG = re.compile(r"^\[(=*)\[(.*)\]\1\]$", re.S)
_ESCAPES = {"n": "\n", "t": "\t"}


@dataclass
class Call:
    name: str  # "o.bind", "o.bind_toggle", "hl.bind", "hl.unbind" or "require"
    args: list  # source text of each top-level argument
    line: int
    # Conditions of the enclosing `if` blocks ("" when unknown, e.g. an else branch).
    conditions: list = field(default_factory=list)
    # True inside a function body: the call runs later, if at all.
    deferred: bool = False
    masked: str = ""  # the argument list with string contents blanked


def mask(source: str) -> str:
    """Same-length copy with comments blanked and string contents replaced by 'x'."""
    out = list(source)
    size = len(source)

    def blank(start, end, fill):
        for index in range(start, min(end, size)):
            if out[index] != "\n":
                out[index] = fill

    def long_end(match):
        closing = "]" + match.group(1) + "]"
        found = source.find(closing, match.end())
        return (size, size) if found == -1 else (found, found + len(closing))

    i = 0
    while i < size:
        char = source[i]
        if source.startswith("--", i):
            match = _LONG_OPEN.match(source, i + 2)
            if match:
                end = long_end(match)[1]
            else:
                end = source.find("\n", i)
                end = size if end == -1 else end
            blank(i, end, " ")
            i = end
        elif char in "\"'":
            j = i + 1
            while j < size and source[j] != char and source[j] != "\n":
                j += 2 if source[j] == "\\" else 1
            blank(i + 1, j, "x")
            i = j + 1
        elif char == "[" and _LONG_OPEN.match(source, i):
            match = _LONG_OPEN.match(source, i)
            content_end, end = long_end(match)
            blank(match.end(), content_end, "x")
            i = end
        else:
            i += 1
    return "".join(out)


def string_value(arg: str):
    """The value of an argument that is exactly one string literal, else None."""
    match = _SHORT.match(arg)
    if match:
        return re.sub(r"\\(.)", lambda e: _ESCAPES.get(e.group(1), e.group(1)), match.group(2), flags=re.S)
    match = _LONG.match(arg)
    if match and "]" + match.group(1) + "]" not in match.group(2):
        return match.group(2)
    return None


def _closing(masked: str, opening: int) -> int:
    depth = 0
    for index in range(opening, len(masked)):
        char = masked[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _split(source: str, masked: str, start: int, end: int) -> list:
    args, depth, begin = [], 0, start
    for index in range(start, end):
        char = masked[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            args.append(source[begin:index].strip())
            begin = index + 1
    last = source[begin:end].strip()
    if last or args:
        args.append(last)
    return args


def scan(source: str) -> list:
    """Binding and require calls in source order, each with the blocks around it."""
    masked = mask(source)
    calls = []
    blocks = []  # [kind, condition] for every open function/if/do/repeat

    def context():
        return (
            [condition for kind, condition in blocks if kind == "if"],
            any(kind == "function" for kind, _ in blocks),
        )

    for match in _TOKEN.finditer(masked):
        line = source.count("\n", 0, match.start()) + 1
        word = match.group("block")
        if word:
            if word in ("end", "until"):
                if blocks:
                    blocks.pop()
            elif word in ("else", "elseif"):
                if blocks and blocks[-1][0] == "if":
                    blocks[-1][1] = ""
            elif word == "if":
                then = re.compile(r"\bthen\b").search(masked, match.end())
                blocks.append(["if", source[match.end():then.start()].strip() if then else ""])
            else:
                blocks.append([word, ""])
            continue

        conditions, deferred = context()
        if match.group("require"):
            opening = match.end() - 1
            closing = masked.find(match.group("quote"), opening + 1)
            if closing != -1:
                calls.append(Call("require", [source[opening + 1:closing]], line, conditions, deferred))
            continue

        # `function o.bind(...)` defines the helper; it is not a call to it.
        if masked[:match.start()].rstrip().endswith("function"):
            continue
        opening = match.end() - 1
        closing = _closing(masked, opening)
        if closing == -1:
            continue
        calls.append(Call(
            match.group("call"),
            _split(source, masked, opening + 1, closing),
            line,
            conditions,
            deferred,
            masked[opening + 1:closing],
        ))
    return calls
