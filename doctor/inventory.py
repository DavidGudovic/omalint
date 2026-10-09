"""Discover plugins and shell.json the way the shell's PluginRegistry does.

The rules here mirror $OMARCHY_PATH/shell/services/PluginRegistry.qml and
`omarchy plugin validate`, so "loadable" means what the running shell means.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .model import ERROR, WARN, Context

# kind -> the entryPoints key the shell loads for it
KINDS = {
    "bar": "bar",
    "bar-widget": "barWidget",
    "menu": "menu",
    "overlay": "overlay",
    "panel": "panel",
    "service": "service",
}
SECTIONS = ("left", "center", "right")
REQUIRED = ("id", "name", "version", "kinds", "entryPoints")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RESERVED = "omarchy."
MAX_WALK = 20000


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def load_json(path: Path):
    """Parse a file the way the shell does. Returns (value, error).

    The shell decodes leniently (a stray byte becomes U+FFFD) and then parses
    strictly with JSON.parse, so a file is only invalid here when it is there.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return None, f"it cannot be read: {error.strerror}"
    try:
        return json.loads(text, parse_constant=_reject_constant), ""
    except json.JSONDecodeError as error:
        return None, f"line {error.lineno}, column {error.colno}: {error.msg}"
    except (ValueError, RecursionError) as error:
        return None, str(error) or "it is nested too deeply"


@dataclass
class Plugin:
    dir: Path
    manifest: Optional[dict] = None
    first_party: bool = False
    # (code, severity, message, fix) for each manifest problem
    problems: list = field(default_factory=list)
    # True when the shell registers the plugin; False when it rejects the manifest.
    loadable: bool = False
    # True when a manifest.json exists but no id can be read from it.
    unidentified: bool = False

    @property
    def id(self) -> str:
        value = self.manifest.get("id") if self.manifest else None
        return value if isinstance(value, str) else ""

    @property
    def label(self) -> str:
        return self.id or self.dir.name

    @property
    def kinds(self) -> list:
        kinds = self.manifest.get("kinds") if self.manifest else None
        return [k for k in kinds if isinstance(k, str)] if isinstance(kinds, list) else []

    @property
    def allow_multiple(self) -> bool:
        widget = self.manifest.get("barWidget") if self.manifest else None
        return isinstance(widget, dict) and widget.get("allowMultiple") is True


def _first_symlink(root: Path) -> str:
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in dirnames + filenames:
            seen += 1
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                return os.path.relpath(full, root)
        if seen > MAX_WALK:
            break
    return ""


def _safe_entry_point(value) -> bool:
    return isinstance(value, str) and value != "" and not value.startswith("/") and ".." not in value


def _validate(plugin: Plugin) -> None:
    """Fill plugin.problems and plugin.loadable from its manifest.json."""
    rejected = False

    def problem(code, severity, message, fix, rejects=False):
        nonlocal rejected
        plugin.problems.append((code, severity, message, fix))
        rejected = rejected or rejects

    path = plugin.dir / "manifest.json"
    if not path.is_file():
        problem(
            "manifest.missing", WARN,
            "This folder has no manifest.json, so the shell does not treat it as a plugin.",
            "Restore its manifest.json, or delete the folder if it is a leftover.",
        )
        return

    plugin.unidentified = True
    manifest, error = load_json(path)
    if error:
        problem(
            "manifest.invalid-json", ERROR,
            f"manifest.json is not valid JSON ({error}), so the shell cannot load this plugin.",
            "Fix manifest.json, or reinstall the plugin from its repository.",
        )
        return
    if not isinstance(manifest, dict):
        problem(
            "manifest.not-object", ERROR,
            "manifest.json must contain a JSON object, so the shell cannot load this plugin.",
            "Reinstall the plugin from its repository.",
        )
        return
    plugin.manifest = manifest
    plugin.unidentified = not plugin.id

    version = manifest.get("schemaVersion")
    if isinstance(version, bool) or not isinstance(version, (int, float)) or version != 1:
        problem(
            "manifest.schema-version", ERROR,
            f"schemaVersion is {json.dumps(version)}; the shell only loads manifests with schemaVersion 1.",
            'Set "schemaVersion": 1 (a number, not a string), or update the plugin.',
            rejects=True,
        )

    missing = [name for name in REQUIRED if name not in manifest]
    if missing:
        problem(
            "manifest.missing-field", ERROR,
            f"Required field{'s' if len(missing) > 1 else ''} missing: {', '.join(missing)}. "
            "The shell rejects the whole manifest.",
            f"Add {'them' if len(missing) > 1 else 'it'} to manifest.json, or update the plugin.",
            rejects=True,
        )

    if "id" in manifest:
        raw = manifest["id"]
        if not isinstance(raw, str) or raw == "" or "/" in raw or ".." in raw:
            problem(
                "manifest.invalid-id", ERROR,
                f"The plugin id {json.dumps(raw)} is not usable: it must be a non-empty name "
                "without '/' or '..'. The shell rejects the manifest.",
                'Use an id such as "yourname.plugin-name".',
                rejects=True,
            )
        elif raw.startswith(RESERVED):
            problem(
                "manifest.reserved-id", ERROR,
                f'The id "{raw}" is in the omarchy.* namespace, which is reserved for built-in '
                "plugins. The shell refuses to load it.",
                "Change the id to your own namespace. To customize a built-in plugin, use "
                "`omarchy plugin clone <id>` instead.",
                rejects=True,
            )
        else:
            if not ID_PATTERN.match(raw):
                problem(
                    "manifest.invalid-id", WARN,
                    f'The plugin id "{raw}" contains unusual characters. The shell loads it, '
                    "but `omarchy plugin` commands refuse ids outside letters, digits, '.', '_' and '-'.",
                    "Ask the plugin author to rename it.",
                )
            if raw != plugin.dir.name:
                problem(
                    "manifest.folder-mismatch", WARN,
                    f'The folder is named "{plugin.dir.name}" but the manifest id is "{raw}". '
                    "`omarchy plugin update` and `omarchy plugin remove` look for a folder named "
                    "after the id and will not find this one.",
                    f'Rename the folder to "{raw}".',
                )

    kinds = manifest.get("kinds")
    if "kinds" in manifest and (not isinstance(kinds, list) or not kinds):
        problem(
            "manifest.invalid-kinds", ERROR,
            '"kinds" must be a non-empty list such as ["bar-widget"]. The shell rejects the manifest.',
            "Fix manifest.json, or update the plugin.",
            rejects=True,
        )
        kinds = []
    unknown = [k for k in kinds or [] if not isinstance(k, str) or k not in KINDS]
    if unknown:
        problem(
            "manifest.unknown-kind", WARN,
            f"Unknown kind{'s' if len(unknown) > 1 else ''} {', '.join(json.dumps(k) for k in unknown)}. "
            f"The shell knows: {', '.join(sorted(KINDS))}.",
            "Check for a typo in manifest.json, or update Omarchy if the plugin needs a newer shell.",
        )

    entry_points = manifest.get("entryPoints")
    if "entryPoints" in manifest and not isinstance(entry_points, dict):
        problem(
            "manifest.invalid-entry-points", ERROR,
            '"entryPoints" must be an object such as {"barWidget": "Widget.qml"}. '
            "The shell rejects the manifest.",
            "Fix manifest.json, or update the plugin.",
            rejects=True,
        )
    if isinstance(entry_points, dict):
        for key, value in entry_points.items():
            if not _safe_entry_point(value):
                problem(
                    "manifest.unsafe-entry-point", ERROR,
                    f"entryPoints.{key} is {json.dumps(value)}; entry points must be relative "
                    "paths inside the plugin folder. The shell rejects the manifest.",
                    "Do not enable this plugin until its author fixes the path.",
                    rejects=True,
                )
            elif not (plugin.dir / value).is_file():
                problem(
                    "manifest.entry-point-missing", ERROR,
                    f'entryPoints.{key} points to "{value}", which does not exist, '
                    "so that part of the plugin cannot load.",
                    "Restore the file, or reinstall the plugin from its repository.",
                )
        for kind in plugin.kinds:
            if kind in KINDS and KINDS[kind] not in entry_points:
                problem(
                    "manifest.kind-without-entry-point", WARN,
                    f'The plugin declares kind "{kind}" but has no entryPoints.{KINDS[kind]}, '
                    "so enabling it does nothing.",
                    "Report it to the plugin author.",
                )

    widget = manifest.get("barWidget")
    if isinstance(widget, dict) and "defaultSection" in widget:
        if str(widget["defaultSection"]) not in SECTIONS:
            problem(
                "manifest.invalid-default-section", ERROR,
                f"barWidget.defaultSection is {json.dumps(widget['defaultSection'])}; it must be "
                "left, center or right. The shell rejects the manifest.",
                "Fix manifest.json, or update the plugin.",
                rejects=True,
            )

    link = _first_symlink(plugin.dir)
    if link:
        problem(
            "manifest.symlink", WARN,
            f'The plugin folder contains a symlink ("{link}"). `omarchy plugin validate` refuses '
            "plugins with symlinks because they can point at files outside the plugin.",
            "Check where the link points before trusting the plugin.",
        )

    plugin.loadable = not rejected


def _third_party(plugins_dir: Path) -> list:
    if not plugins_dir.is_dir():
        return []
    plugins = []
    # Hidden entries are the shell's own staging and backup folders, not plugins.
    for entry in sorted(plugins_dir.iterdir(), key=lambda p: p.name):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        plugin = Plugin(entry)
        _validate(plugin)
        plugins.append(plugin)
    return plugins


def _first_party(omarchy_path: Path) -> dict:
    """Built-in plugins: manifest.json or *.manifest.json two or three levels down."""
    base = omarchy_path / "shell" / "plugins"
    found = {}
    if not base.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(base):
        depth = len(Path(dirpath).relative_to(base).parts)
        if depth >= 2:
            dirnames[:] = []
        if depth == 0:
            continue
        for name in sorted(filenames):
            if name != "manifest.json" and not name.endswith(".manifest.json"):
                continue
            manifest, _ = load_json(Path(dirpath) / name)
            if isinstance(manifest, dict) and isinstance(manifest.get("id"), str):
                found[manifest["id"]] = Plugin(Path(dirpath), manifest, first_party=True, loadable=True)
    return found


def entry_id(entry) -> str:
    """Id of a bar.layout entry as the shell reads it (String(entry.id)), or "" when it has none."""
    if isinstance(entry, str):
        return entry
    value = entry.get("id") if isinstance(entry, dict) else None
    if isinstance(value, str):
        return value
    if value is True:
        return "true"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value:
        return str(int(value)) if float(value).is_integer() else repr(value)
    return ""


@dataclass
class Inventory:
    third_party: list
    first_party: dict
    # "ok", "missing" (the shell uses its defaults), "invalid" or "version"
    shell_state: str = "missing"
    shell_error: str = ""
    shell_config: Optional[dict] = None

    @property
    def loaded(self) -> dict:
        """Third-party plugins the shell registers; on an id collision the last folder wins."""
        return {p.id: p for p in self.third_party if p.loadable}

    def plugin(self, plugin_id: str) -> Optional[Plugin]:
        return self.first_party.get(plugin_id) or self.loaded.get(plugin_id)

    def broken(self, plugin_id: str) -> Optional[Plugin]:
        """An installed folder that is meant to provide this id but does not load."""
        for plugin in self.third_party:
            if not plugin.loadable and plugin_id in (plugin.id, plugin.dir.name):
                return plugin
        return None

    @property
    def unidentified(self) -> list:
        """Folders whose id cannot be read; while any exist, "not installed" is not certain."""
        return [p.dir.name for p in self.third_party if p.unidentified]

    def enabled(self, plugin_id: str) -> Optional[bool]:
        """Whether shell.json references a third-party plugin; None when that is unknowable."""
        config = self.shell_config
        if self.shell_state == "missing":
            return False
        if config is None:
            return None
        bar = config.get("bar") if isinstance(config.get("bar"), dict) else {}
        if bar.get("id") == plugin_id:
            return True
        layout = bar.get("layout") if isinstance(bar.get("layout"), dict) else {}
        for section in SECTIONS:
            entries = layout.get(section)
            if isinstance(entries, list) and any(entry_id(e) == plugin_id for e in entries):
                return True
        plugins = config.get("plugins")
        if isinstance(plugins, list):
            return any(isinstance(e, dict) and e.get("id") == plugin_id for e in plugins)
        return False


def build(ctx: Context) -> Inventory:
    inventory = Inventory(_third_party(ctx.plugins_dir), _first_party(ctx.omarchy_path))
    if ctx.shell_json.is_file():
        config, error = load_json(ctx.shell_json)
        if error:
            inventory.shell_state, inventory.shell_error = "invalid", error
        elif not isinstance(config, dict):
            inventory.shell_state, inventory.shell_error = "invalid", "it is not a JSON object"
        elif isinstance(config.get("version"), bool) or config.get("version") != 1:
            inventory.shell_state = "version"
        else:
            inventory.shell_state, inventory.shell_config = "ok", config
    return inventory
