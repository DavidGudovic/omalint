"""Split the CLI's ANSI-colored report (stdin) into styled text segments (stdout, JSON).

{"lines": [[[style, text], ...], ...], "errors": N, "warnings": M}

The CLI only emits SGR codes 31, 32, 33, 2, 1 and 0 (see _STYLE in omalint/report.py). The counts
are read from the report's closing line, so they are what the report itself says.
"""

import json
import re
import sys

STYLE = {"31": "red", "32": "green", "33": "yellow", "2": "dim", "1": "bold", "0": ""}
ESCAPE = re.compile(r"(\x1b\[[0-9;]*m)")
CLOSING = re.compile(r"(?:No problems found\.|(?:(\d+) errors?)?(?: and )?(?:(\d+) warnings?)? ?found\.)")


def split(raw):
    segments, style = [], ""
    for part in ESCAPE.split(raw):
        if ESCAPE.fullmatch(part):
            code = part[2:-1]
            if code not in STYLE:
                sys.exit(f"segments.py: unexpected escape code {code!r}")
            style = STYLE[code]
        elif part:
            segments.append([style, part])
    return segments


def main():
    text = sys.stdin.buffer.read().decode("utf-8").replace("\r", "").rstrip("\n")
    lines = [split(raw) for raw in text.split("\n")]

    # The closing line is the last paragraph; it wraps when the terminal is narrow.
    plain = ESCAPE.sub("", text)
    closing = " ".join(plain.split("\n\n")[-1].split())
    match = CLOSING.match(closing)
    if not match:
        sys.exit("segments.py: the report has no closing line")

    json.dump({"lines": lines, "errors": int(match.group(1) or 0), "warnings": int(match.group(2) or 0)}, sys.stdout)


main()
