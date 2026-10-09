"""Shell health: is the Omarchy shell up, does it see every plugin, and what did plugins log?

Omarchy starts the shell through `systemd-cat -t omarchy-shell`, so its log is
the user journal. (Quickshell's own log file is a binary in a tmpfs runtime
directory and holds the same lines.)
"""

from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from urllib.parse import unquote

from ..inventory import Inventory
from ..model import ERROR, WARN, Context, Finding, Result

TITLE = "Shell health"

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_ENTRY = re.compile(r"^(\S+)\s+\S+\s+[^\[\s]+\[\d+\]:\s?(.*)$")
_LEVEL = re.compile(r"^\s*(DEBUG|INFO|WARN|WARNING|ERROR|CRITICAL|FATAL)\b\s*([^:]*):\s?(.*)$")
_QUIET = ("DEBUG", "INFO")
# One bar is drawn per monitor and each copy of a widget registers the same IPC
# target; the shell says so for stock widgets too. It is not a plugin fault.
_BENIGN = ("Handler was registered but will not be used because another handler is registered",)
_FAILURE = re.compile(r"\b(failed|threw|rejected|error|unavailable|is not a type)\b", re.I)
MAX_LINES = 50000


def parse_journal(text: str, plugins_dir: str, plugin_ids) -> "OrderedDict":
    """{plugin folder or id: {message: [count, last timestamp]}} for problem lines in the shell log."""
    prefix = plugins_dir.rstrip("/") + "/"
    ids = sorted(plugin_ids, key=len, reverse=True)
    problems = OrderedDict()
    for raw in text.splitlines():
        entry = _ENTRY.match(_ANSI.sub("", raw))
        if not entry:
            continue
        stamp, message = entry.group(1), unquote(entry.group(2))
        level = _LEVEL.match(message)
        if level:
            if level.group(1) in _QUIET:
                continue
            message = level.group(3)
        if any(marker in message for marker in _BENIGN):
            continue

        owner = ""
        at = message.find(prefix)
        if at != -1:
            owner = message[at + len(prefix):].split("/", 1)[0]
            message = message.replace("file://" + prefix + owner + "/", "").replace(prefix + owner + "/", "")
        elif _FAILURE.search(message):
            owner = next((i for i in ids if re.search(r"(?<![\w.-])" + re.escape(i) + r"(?![\w-])", message)), "")
        if not owner:
            continue
        record = problems.setdefault(owner, OrderedDict()).setdefault(message.strip(), [0, stamp])
        record[0] += 1
        record[1] = stamp
    return problems


def _clock(stamp: str) -> str:
    match = re.search(r"T(\d\d:\d\d)", stamp)
    return match.group(1) if match else stamp


def check(ctx: Context, inv: Inventory) -> Result:
    result = Result()
    if not ctx.live:
        result.skipped = True
        result.notes.append("Not checked: this run is not looking at the running session.")
        return result

    env = dict(os.environ)
    env.setdefault("OMARCHY_PATH", str(ctx.omarchy_path))

    ping = ctx.run(["omarchy-shell", "shell", "ping"], timeout=8, env=env)
    if ping.status == "missing":
        result.skipped = True
        result.notes.append("Not checked: the `omarchy-shell` command is not on PATH, so the shell cannot be asked.")
        return result
    if "not ready" in ping.err:
        # A shell that is still loading answers like this for a moment; that is not a fault.
        result.skipped = True
        result.notes.append("The shell is still starting up; run the check again in a few seconds.")
        return result
    if not (ping.ok and ping.out.strip() == "ok"):
        stuck = ping.status == "timeout" or "not responding" in ping.err
        result.findings.append(Finding(
            "health", "health.shell-unresponsive" if stuck else "health.shell-not-running", ERROR, "omarchy-shell",
            "The Omarchy shell is running but does not answer." if stuck
            else "The Omarchy shell is not running: there is no bar and no notifications.",
            "Restart it with `omarchy restart shell`.",
        ))
        return result

    listed = ctx.run(["omarchy-shell", "shell", "listPlugins"], timeout=8, env=env)
    try:
        seen = {p.get("id") for p in json.loads(listed.out) if isinstance(p, dict)} if listed.ok else None
    except (ValueError, TypeError):
        seen = None
    if seen is not None:
        for plugin_id, plugin in sorted(inv.loaded.items()):
            if plugin_id not in seen:
                result.findings.append(Finding(
                    "health", "health.not-discovered", WARN, plugin_id,
                    f"{plugin_id} is installed, but the running shell has not picked it up.",
                    "Run `omarchy-shell shell rescanPlugins`, or `omarchy restart shell`.",
                    ctx.display(plugin.dir),
                ))

    pids = ctx.shell_pids(ctx.omarchy_path)
    command = ["journalctl", "--user", "-b", "-t", "omarchy-shell", "-o", "short-iso", "--all", "--no-pager",
               "-n", str(MAX_LINES)]
    # Only this shell process: errors from a shell that has since been restarted are history.
    journal = ctx.run(command + [f"_PID={pid}" for pid in pids], timeout=15)
    if not journal.ok:
        result.notes.append("Shell is running. The journal could not be read, so plugin log errors were not checked.")
        return result

    by_folder = {p.dir.name: p.label for p in inv.third_party}
    problems = parse_journal(journal.out, str(ctx.plugins_dir), [p.id for p in inv.third_party if p.id])
    for owner, messages in problems.items():
        label = by_folder.get(owner, owner)
        total = sum(count for count, _ in messages.values())
        last = max(stamp for _, stamp in messages.values())
        shown = "; ".join(
            f"{text}" + (f" (×{count})" if count > 1 else "") for text, (count, _) in list(messages.items())[:3]
        )
        more = f"; and {len(messages) - 3} more" if len(messages) > 3 else ""
        result.findings.append(Finding(
            "health", "health.log-errors", WARN, label,
            f"{label} logged {total} problem{'s' if total != 1 else ''} since the shell started "
            f"(last at {_clock(last)}): {shown}{more}",
            f"Try `omarchy plugin update {label}`; if it persists, report it to the plugin's author. "
            "Full log: journalctl --user -b -t omarchy-shell",
        ))

    lines = len(journal.out.splitlines())
    result.notes.append(
        "Shell is running"
        + (f" (PID {', '.join(map(str, pids))})" if pids else "")
        + f"; {lines} log line{'s' if lines != 1 else ''} checked."
    )
    return result
