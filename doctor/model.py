"""Shared types: findings, command results and the context every check receives."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ERROR, WARN, INFO = "error", "warn", "info"


@dataclass
class Finding:
    check: str
    code: str
    severity: str
    subject: str
    message: str
    fix: str = ""
    path: str = ""
    # What --fix would do to shell.json, or None when the finding needs a human.
    action: Optional[dict] = field(default=None, repr=False)

    @property
    def fixable(self) -> bool:
        return self.action is not None

    def to_json(self) -> dict:
        return {
            "check": self.check,
            "code": self.code,
            "severity": self.severity,
            "subject": self.subject,
            "message": self.message,
            "fix": self.fix,
            "path": self.path,
            "fixable": self.fixable,
        }


@dataclass
class Result:
    """Outcome of one check: what it found, plus one-line notes about its coverage."""

    findings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    skipped: bool = False


@dataclass
class Run:
    """Outcome of an external command. status is "ok" (it ran), "missing" or "timeout"."""

    status: str
    code: int = -1
    out: str = ""
    err: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.code == 0


def run_command(argv, timeout=5.0, env=None) -> Run:
    try:
        done = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except (FileNotFoundError, PermissionError, NotADirectoryError):
        return Run("missing")
    except subprocess.TimeoutExpired:
        return Run("timeout")
    except OSError as error:
        return Run("ok", 126, "", str(error))
    return Run("ok", done.returncode, done.stdout, done.stderr)


def shell_pids(omarchy_path: Path) -> list:
    """PIDs of the quickshell instance(s) running the Omarchy shell config."""
    config = str(omarchy_path / "shell")
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().decode("utf-8", "replace").split("\0")
        except OSError:
            continue
        if os.path.basename(argv[0]) not in ("quickshell", "qs"):
            continue
        if any(a in ("-p", "--path") and b.rstrip("/") == config for a, b in zip(argv, argv[1:])):
            pids.append(int(entry.name))
    return sorted(pids)


@dataclass
class Context:
    config_dir: Path  # ~/.config/omarchy
    hypr_dir: Path  # ~/.config/hypr
    omarchy_path: Path  # /usr/share/omarchy
    # False when pointed at a directory that is not the running session's, or
    # with --no-live: the shell, the journal and Hyprland are then left alone.
    live: bool = True
    path_env: str = field(default_factory=lambda: os.environ.get("PATH", os.defpath))
    run: Callable[..., Run] = run_command
    shell_pids: Callable[[Path], list] = shell_pids

    @property
    def plugins_dir(self) -> Path:
        return self.config_dir / "plugins"

    @property
    def shell_json(self) -> Path:
        return self.config_dir / "shell.json"

    def display(self, path) -> str:
        """A path the way a person would type it: ~ for home, $OMARCHY_PATH for stock files."""
        text = str(path)
        stock = str(self.omarchy_path)
        if text == stock or text.startswith(stock + "/"):
            return "$OMARCHY_PATH" + text[len(stock):]
        home = os.path.expanduser("~")
        if home not in ("", "/") and (text == home or text.startswith(home + "/")):
            return "~" + text[len(home):]
        return text
