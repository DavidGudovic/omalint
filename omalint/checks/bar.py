"""Bar layout: does shell.json only reference widgets and plugins that exist?"""

from __future__ import annotations

import os
from collections import defaultdict

from ..inventory import RESERVED, SECTIONS, Inventory, entry_id
from ..model import ERROR, WARN, Context, Finding, Result

TITLE = "Bar layout"
NOT_FOUND = "is neither an installed plugin nor built in"


def custom_type(entry) -> str:
    """Mirrors BarModel.customModuleType: these keys turn an entry into a user module."""
    if not isinstance(entry, dict):
        return ""
    if entry.get("type"):
        return str(entry["type"])
    if entry.get("exec"):
        return "command"
    if entry.get("source"):
        return "qml"
    return ""


def _custom_qml_path(ctx: Context, entry: dict, name: str) -> str:
    source = entry.get("source")
    if source:
        source = str(source)
        home = os.path.expanduser("~")
        if source.startswith("~/"):
            return home + source[1:]
        if source.startswith("$HOME/"):
            return home + source[5:]
        return source
    if name and ".." not in name and not name.startswith("/"):
        return str(ctx.config_dir / "bar" / "modules" / f"{name}.qml")
    return ""


def check(ctx: Context, inv: Inventory) -> Result:
    result = Result()
    where = ctx.display(ctx.shell_json)

    def add(code, severity, subject, message, fix, action=None):
        result.findings.append(Finding("bar", code, severity, subject, message, fix, where, action))

    if inv.shell_state == "missing":
        result.notes.append(f"No {where}; the shell uses its stock layout.")
        return result
    if inv.shell_state == "invalid":
        add(
            "bar.shell-json-invalid", ERROR, "shell.json",
            f"shell.json is not valid JSON ({inv.shell_error}). The shell ignores the whole file "
            "and shows its stock bar, so none of your layout or plugin settings apply.",
            "Fix the syntax error, restore a shell.json.bak.* backup, or reset with `omarchy refresh shell`.",
        )
        return result
    if inv.shell_state == "version":
        add(
            "bar.shell-json-version", ERROR, "shell.json",
            'shell.json has no "version": 1 at the top level. The shell ignores the whole file '
            "and shows its stock bar.",
            'Add "version": 1 as a top-level key.',
        )
        return result

    config = inv.shell_config
    # Without the stock manifests, built-in ids cannot be told from typos.
    verify_builtins = bool(inv.first_party)
    if not verify_builtins:
        result.notes.append(
            f"Built-in plugins not found under {ctx.display(ctx.omarchy_path)}; omarchy.* ids were not verified."
        )

    def describe_missing(plugin_id: str):
        """(reason, fix, removable) for an id that names no loadable plugin."""
        broken = inv.broken(plugin_id)
        if broken:
            return (f"is installed in {broken.dir.name}, but its manifest does not load",
                    "Fix or reinstall the plugin (see Plugin manifests).", False)
        if plugin_id.startswith(RESERVED):
            # Never removed automatically: a built-in this version of OmaLint cannot find
            # (moved by an Omarchy update, say) must not cost the user a working widget.
            return ("is not a built-in of this Omarchy version",
                    "Check the id against `omarchy plugin list`, and remove the entry by hand if it is a leftover.",
                    False)
        if inv.unidentified:
            # One of those folders might be this plugin, so removing the entry is not safe.
            return (NOT_FOUND, "Reinstall the plugin, or remove the entry by hand. (Not fixed "
                    f"automatically while {inv.unidentified[0]} has an unreadable manifest.)", False)
        return NOT_FOUND, "Reinstall the plugin, or remove the entry.", True

    bar = config.get("bar") if isinstance(config.get("bar"), dict) else {}

    bar_id = bar.get("id")
    if isinstance(bar_id, str) and bar_id not in ("", "omarchy.bar"):
        plugin = inv.plugin(bar_id)
        if plugin and "bar" in plugin.kinds:
            pass
        elif plugin:
            add(
                "bar.unknown-bar", WARN, bar_id,
                f'bar.id selects "{bar_id}", which is not a bar plugin. The shell falls back to the built-in bar.',
                'Remove "id" from the bar section, or pick a bar with `omarchy bar use <id>`.',
            )
        elif verify_builtins or not bar_id.startswith("omarchy."):
            reason, fix, removable = describe_missing(bar_id)
            add(
                "bar.unknown-bar", WARN, bar_id,
                f'bar.id selects "{bar_id}", which {reason}. The shell falls back to the built-in bar.',
                fix,
                {"op": "remove-bar-id"} if removable else None,
            )

    layout = bar.get("layout") if isinstance(bar.get("layout"), dict) else {}
    for name in layout:
        if name in SECTIONS:
            continue
        entries = layout[name] if isinstance(layout[name], list) else []
        ids = [entry_id(e) or "?" for e in entries]
        add(
            "bar.unknown-section", WARN, f"bar.layout.{name}",
            f'bar.layout has a section "{name}", but the bar only draws left, center and right. '
            + (f"Its widgets are never shown: {', '.join(ids)}." if ids else "It is ignored."),
            "Move its entries into left, center or right, then delete the section.",
        )

    placements = defaultdict(list)
    for section in SECTIONS:
        if section not in layout:
            continue
        entries = layout[section]
        if not isinstance(entries, list):
            add(
                "bar.section-not-list", WARN, f"bar.layout.{section}",
                f"bar.layout.{section} must be a list of widgets; the shell treats it as empty.",
                f'Write it as a list, e.g. "{section}": [{{"id": "omarchy.clock"}}].',
            )
            continue
        for index, entry in enumerate(entries):
            spot = f"bar.layout.{section}[{index}]"
            remove = {"op": "remove-layout", "spots": [[section, index]]}
            name = entry_id(entry)
            kind = custom_type(entry)
            # A command module draws whatever its id is, so only a plain entry is dead without one.
            if not name and not kind:
                add(
                    "bar.entry-without-id", WARN, spot,
                    f"{spot} has no id, so the bar shows nothing for it.",
                    "Delete the entry, or give it the id of a widget.",
                    remove,
                )
                continue

            if kind == "qml":
                path = _custom_qml_path(ctx, entry, name)
                if not path or not os.path.isfile(path):
                    add(
                        "bar.custom-module-missing", WARN, name or spot,
                        f'{spot} is a custom QML module, but its file {ctx.display(path) if path else "(none)"} '
                        "does not exist, so the slot stays empty.",
                        "Create the file, fix its \"source\" path, or delete the entry.",
                    )
                continue
            if kind == "command":
                continue
            if kind:
                add(
                    "bar.unknown-module-type", WARN, name,
                    f'{spot} has "type": "{kind}". A "type" key makes the bar treat the entry as a '
                    'custom module, and only "command" and "qml" exist, so the slot stays empty.',
                    'Remove the "type" key, or use "command" or "qml".',
                )
                continue

            plugin = inv.plugin(name)
            if plugin and "bar-widget" in plugin.kinds:
                placements[name].append((section, index))
            elif plugin:
                add(
                    "bar.not-a-widget", WARN, name,
                    f"{spot} places {name} on the bar, but it is a {'/'.join(plugin.kinds)} plugin "
                    "without a bar widget, so the slot stays empty.",
                    f'Move {{"id": "{name}"}} from the bar layout to the top-level "plugins" list.',
                )
            elif verify_builtins or not name.startswith("omarchy."):
                reason, fix, removable = describe_missing(name)
                add(
                    "bar.unknown-widget", WARN, name,
                    f"{spot} references {name}, which {reason}. The bar leaves an empty slot.",
                    fix,
                    remove if removable else None,
                )

    for name, spots in sorted(placements.items()):
        if len(spots) < 2 or inv.plugin(name).allow_multiple:
            continue
        listed = ", ".join(f"{section}[{index}]" for section, index in spots)
        add(
            "bar.duplicate-widget", WARN, name,
            f"{name} is placed {len(spots)} times ({listed}) but does not support multiple instances. "
            "The copies fight over one IPC target and one settings entry, and `omarchy bar` commands "
            "only reach the first.",
            # Not fixed automatically: the bar draws every copy, so which one goes is the user's call.
            f"Decide which one to keep and delete the other {name} entries from shell.json.",
        )

    plugins = config.get("plugins")
    if isinstance(plugins, list):
        for index, entry in enumerate(plugins):
            spot = f"plugins[{index}]"
            name = entry.get("id") if isinstance(entry, dict) else None
            if not isinstance(name, str) or not name:
                add(
                    "bar.plugin-entry-invalid", WARN, spot,
                    f'{spot} is not an object with an "id", so it enables nothing.',
                    'Write entries as {"id": "<plugin id>"}, or delete it.',
                )
            elif not inv.plugin(name) and (verify_builtins or not name.startswith("omarchy.")):
                reason, fix, removable = describe_missing(name)
                add(
                    "bar.unknown-plugin", WARN, name,
                    f"{spot} enables {name}, which {reason}.",
                    fix,
                    {"op": "remove-plugin", "index": index} if removable else None,
                )

    widgets = sum(len(layout[s]) for s in SECTIONS if isinstance(layout.get(s), list))
    result.notes.append(f"{widgets} bar entries checked in {where}.")
    return result
