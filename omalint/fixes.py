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
    """Serialize the way the shell does (JSON.stringify(config, null, 2) plus a newline).

    Raises ValueError for a number JSON cannot hold (1e400 parses to infinity).
    """
    return json.dumps(config, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def diff(old: str, new: str, name: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=name, tofile=name + " (fixed)"
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def read(path: Path) -> str:
    """The file's exact text, line endings included. Refuses what could not be written back faithfully."""
    try:
        with open(path, encoding="utf-8", newline="") as stream:
            return stream.read()
    except UnicodeDecodeError:
        raise FixError(f"{path} is not valid UTF-8 text, so it is left alone. Fix its encoding by hand first.")


def _save_backup(target: Path, text: str) -> Path:
    """Write text to a new backup file beside target and return its path."""
    # Named after the tool, so its backups can be told from anyone else's and removed with it.
    # It goes beside the path the user knows, even when that is a symlink into a dotfiles folder.
    stamp = f"{target.name}.bak.omalint.{int(time.time())}"
    backup = target.with_name(stamp)
    suffix = 1
    while True:
        try:
            # Owner-only from the moment it exists, whatever the umask: a file that is created first and
            # restricted afterwards can be read by others in between. O_EXCL takes the name only if it is
            # free, and does not follow a symlink left there.
            handle = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            backup = target.with_name(f"{stamp}.{suffix}")
            suffix += 1
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        os.unlink(backup)
        raise
    return backup


def _replace(real: Path, text: str) -> None:
    """Swap in a new file with this text, so a reader never sees half of it."""
    handle, temporary = tempfile.mkstemp(prefix=".omalint-", dir=real.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        # mkstemp made the file owner-only; it takes the original's mode only now that the content is in.
        shutil.copymode(real, temporary)
        os.replace(temporary, real)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(ctx: Context, target: Path, old: str, new: str) -> Path:
    """Back up target, then replace its content. Returns the backup path."""
    real = Path(os.path.realpath(target))
    for stock in {os.path.realpath(ctx.omarchy_path), "/usr/share/omarchy"}:
        if str(real) == stock or str(real).startswith(stock + os.sep):
            raise FixError(f"{real} belongs to Omarchy itself; refusing to edit it.")
    if read(real) != old:
        raise FixError(f"{target} changed while it was being checked. Nothing was written; run the command again.")

    backup = _save_backup(target, old)
    try:
        _replace(real, new)
    except OSError:
        # Nothing was replaced, so there is nothing to undo and no reason to leave a copy behind.
        os.unlink(backup)
        raise
    return backup
