"""--fix: drop dead references from shell.json, behind a backup and a diff.

The only file ever written is the user's shell.json. Every fix removes an
entry the shell already ignores, so the bar looks the same before and after.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from .model import Context


class FixError(Exception):
    pass


def plan(config: dict, findings) -> tuple:
    """Apply every fixable finding to a copy of the config. Returns (new config, fixed findings)."""
    new = copy.deepcopy(config)
    spots, rows, fixed = set(), set(), []
    drop_bar_id = False
    for finding in findings:
        action = finding.action
        if not action:
            continue
        fixed.append(finding)
        if action["op"] == "remove-layout":
            spots.update((section, index) for section, index in action["spots"])
        elif action["op"] == "remove-plugin":
            rows.add(action["index"])
        elif action["op"] == "remove-bar-id":
            drop_bar_id = True
    # Highest index first, so earlier removals do not shift later ones.
    for section, index in sorted(spots, key=lambda spot: spot[1], reverse=True):
        del new["bar"]["layout"][section][index]
    for index in sorted(rows, reverse=True):
        del new["plugins"][index]
    if drop_bar_id:
        del new["bar"]["id"]
    return new, fixed


def render(config: dict) -> str:
    """Serialize the way the shell does (JSON.stringify(config, null, 2) plus a newline)."""
    return json.dumps(config, indent=2, ensure_ascii=False) + "\n"


def diff(old: str, new: str, name: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=name, tofile=name + " (fixed)"
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def apply(ctx: Context, target: Path, old: str, new: str) -> Path:
    """Back up target, then replace its content. Returns the backup path."""
    real = Path(os.path.realpath(target))
    for stock in {os.path.realpath(ctx.omarchy_path), "/usr/share/omarchy"}:
        if str(real) == stock or str(real).startswith(stock + os.sep):
            raise FixError(f"{real} belongs to Omarchy itself; refusing to edit it.")
    if real.read_text(encoding="utf-8") != old:
        raise FixError(f"{target} changed while it was being checked. Nothing was written; run the command again.")

    # Named after the tool, so its backups can be told from anyone else's and removed with it.
    stamp = f"{real.name}.bak.omadoctor.{int(time.time())}"
    backup = real.with_name(stamp)
    suffix = 1
    while backup.exists():
        backup = real.with_name(f"{stamp}.{suffix}")
        suffix += 1
    shutil.copy2(real, backup)

    handle, temporary = tempfile.mkstemp(prefix=".omadoctor-", dir=real.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(new)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copymode(real, temporary)
        os.replace(temporary, real)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup
