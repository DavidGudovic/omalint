"""Keybindings: keys bound twice, keys that open missing plugins, and plugin suggestions that clash."""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .. import lua
from ..inventory import Inventory
from ..model import INFO, WARN, Context, Finding, Result

TITLE = "Keybindings"

MOD_BITS = {"SHIFT": 1, "CAPS": 2, "CTRL": 4, "ALT": 8, "MOD2": 16, "MOD3": 32, "SUPER": 64, "MOD5": 128}
MOD_ORDER = ("SUPER", "CTRL", "ALT", "SHIFT", "CAPS", "MOD2", "MOD3", "MOD5")
MOD_ALIASES = {"CONTROL": "CTRL", "WIN": "SUPER", "LOGO": "SUPER", "MOD4": "SUPER", "META": "SUPER", "MOD1": "ALT"}
MAX_SOURCE = 1024 * 1024

# `omarchy-shell shell toggle <id>` names a plugin outright. The other form,
# `omarchy-shell <target> <method>`, names an IPC target that need not be a plugin id.
_SHELL_CALL = re.compile(
    r"\bomarchy(?:-|\s+)shell\s+(?:-q\s+)?shell\s+(?:toggle|summon|hide|call)\s+[\"']?([A-Za-z0-9][A-Za-z0-9._-]*)"
)
_EXEC = re.compile(r"hl\.dsp\.exec_cmd\(\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')\s*\)")
_FLAG = re.compile(r"^[ \t]*(?:_G\.)?(omarchy_\w+)[ \t]*=[ \t]*(true|false)\b", re.M)
_README_LUA = re.compile(r"\b(?:o\.bind_toggle|o\.bind|hl\.bind)\(\s*\"([^\"\n]+)\"")
_README_CONF = re.compile(r"^\s*bind[a-z]*\s*=\s*([^,\n]*),\s*([^,\s][^,\n]*?)\s*,", re.M)
_CONF_MODS = re.compile(r"SUPER|WIN|LOGO|MOD4|META|CONTROL|CTRL|ALT|SHIFT")


def normalize(combo: str) -> str:
    """Canonical spelling of a key combination: modifiers in a fixed order, key upper-cased."""
    mods, keys = set(), []
    for part in combo.split("+"):
        part = part.strip().upper()
        if not part:
            continue
        part = MOD_ALIASES.get(part, part)
        if part in MOD_BITS:
            mods.add(part)
        else:
            keys.append(part)
    return " + ".join([m for m in MOD_ORDER if m in mods] + keys)


def _split(combo: str):
    parts = combo.split(" + ")
    mask = sum(MOD_BITS[p] for p in parts if p in MOD_BITS)
    return mask, " + ".join(p for p in parts if p not in MOD_BITS)


@dataclass
class Bind:
    combo: str
    release: bool
    label: str
    command: str  # the shell command it runs, "" when it is not a plain command
    file: Path
    line: int
    stock: bool  # comes from Omarchy's defaults rather than the user's config
    description: str = ""  # as given in the config; Hyprland reports the same text
    arms: tuple = ()  # (file, if statement, arm) for each `if` around the call

    def where(self, ctx: Context) -> str:
        return f"{ctx.display(self.file)}:{self.line}"

    def excludes(self, other: "Bind") -> bool:
        """True when the two sit in different arms of one `if`, so at most one of them runs."""
        mine = {arm[:2]: arm[2] for arm in self.arms}
        return any(arm[:2] in mine and mine[arm[:2]] != arm[2] for arm in other.arms)


def plugin_reference(command: str) -> str:
    """The plugin id a command summons through the shell, or ""."""
    match = _SHELL_CALL.search(command)
    return match.group(1) if match else ""


def _shorten(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class _Loader:
    """Follows hyprland.lua the way Hyprland does and keeps the bindings left standing."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.binds = []
        self.files = []
        self.flags = {}
        self._seen = set()

    def _module(self, name: str):
        for prefix, base in (("default.hypr.", self.ctx.omarchy_path / "default" / "hypr"), ("hypr.", self.ctx.hypr_dir)):
            if name.startswith(prefix):
                return base / (name[len(prefix):].replace(".", "/") + ".lua"), prefix != "hypr."
        return None, False

    def _holds(self, condition: str) -> bool:
        """False only for a condition known to be false; unknown conditions count as true."""
        text = condition.strip()
        negated = text.startswith("not ")
        if negated:
            text = text[4:].strip()
        match = re.fullmatch(r"o\.cmd_(present|missing)\(\s*[\"']([^\"']+)[\"']\s*\)", text)
        if match:
            value = (shutil.which(match.group(2), path=self.ctx.path_env) is not None) == (match.group(1) == "present")
        elif text == "o.preinstalled_bindings_enabled()":
            value = self.flags.get("omarchy_preinstalled_bindings")
            if value is None:
                marker = Path(os.path.expanduser("~/.local/state/omarchy/preinstalls-removed"))
                value = not (self.ctx.live and marker.exists())
        else:
            match = re.fullmatch(r"(?:_G\.)?(omarchy_\w+)\s*~=\s*false", text)
            if not match:
                return True
            value = self.flags.get(match.group(1)) is not False
        return value != negated

    def load(self, path: Path, stock: bool) -> None:
        key = os.path.realpath(path)
        if key in self._seen or not path.is_file():
            return
        self._seen.add(key)
        try:
            if path.stat().st_size > MAX_SOURCE:
                return
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        self.files.append(path)
        if not stock:
            for name, value in _FLAG.findall(lua.mask(source)):
                self.flags[name] = value == "true"

        for call in lua.scan(source):
            if call.deferred or not all(self._holds(c) for c in call.conditions):
                continue
            if call.name == "require":
                target, target_stock = self._module(call.args[0])
                if target:
                    self.load(target, target_stock)
                continue
            keys = lua.string_value(call.args[0]) if call.args else None
            if keys is None:
                continue
            combo = normalize(keys)
            if call.name == "hl.unbind":
                self.binds = [b for b in self.binds if b.combo != combo]
            elif combo:
                self.binds.append(self._bind(call, combo, path, stock))

    def _bind(self, call: lua.Call, combo: str, path: Path, stock: bool) -> Bind:
        args = call.args + ["", "", ""]
        description, command = None, ""
        if call.name == "hl.bind":
            action = args[1]
            found = re.search(r"\bdescription\s*=\s*(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')", ", ".join(args[2:]))
            description = lua.string_value(found.group(1)) if found else None
        else:
            description, action = lua.string_value(args[1]), args[2]
        literal = lua.string_value(action)
        executed = _EXEC.search(action)
        if literal is not None:
            command = "omarchy-toggle-" + literal if call.name == "o.bind_toggle" else literal
        elif executed:
            command = lua.string_value(executed.group(1)) or ""
        release = bool(re.search(r"\brelease\s*=\s*true\b", call.masked))
        return Bind(
            combo, release, description or _shorten(command or action), command, path, call.line, stock,
            description or "", tuple((str(path), number, arm) for number, arm in call.arms),
        )


def collect(ctx: Context):
    """Effective bindings from the Hyprland Lua config, plus the files that were read."""
    loader = _Loader(ctx)
    root = ctx.hypr_dir / "hyprland.lua"
    if root.is_file():
        loader.load(root, False)
    else:
        # No main config to follow: assume the stock order, defaults then the user's bindings.
        loader.load(ctx.omarchy_path / "default" / "hypr" / "omarchy.lua", True)
        loader.load(ctx.hypr_dir / "bindings.lua", False)
    return loader.binds, loader.files


def live_binds(ctx: Context):
    """{(modmask, KEY, release): [descriptions]} from the running Hyprland, or None when unknown.

    Keys bound by keycode come back from hyprctl without a name and are left out.
    """
    if not ctx.live:
        return None
    run = ctx.run(["hyprctl", "-j", "binds"], timeout=3)
    if not run.ok:
        return None
    try:
        binds = json.loads(run.out)
    except ValueError:
        return None
    if not isinstance(binds, list):
        return None
    table = defaultdict(list)
    for bind in binds:
        if not isinstance(bind, dict):
            continue
        # Mouse, submap, long-press and catch-all bindings fire under other conditions
        # than a plain press, so they do not collide with one.
        if bind.get("mouse") or bind.get("submap") or bind.get("longPress") or bind.get("catch_all"):
            continue
        key = str(bind.get("key") or "").upper()
        if key and isinstance(bind.get("modmask"), int):
            table[(bind["modmask"], key, bool(bind.get("release")))].append(str(bind.get("description") or ""))
    return table


def conflicts(ctx: Context, binds: list, live) -> tuple:
    """Keys that run more than one action. Returns (findings, ignored static candidates).

    The config files say where a binding comes from; the running Hyprland says
    what is really bound, including bindings plugins register at run time.
    """
    groups = defaultdict(list)
    for bind in binds:
        group = groups[(bind.combo, bind.release)]
        # Bindings in different arms of one `if` are alternatives, not a double binding.
        if not any(bind.excludes(other) for other in group):
            group.append(bind)
    running = {}
    for (mask, key, release), descriptions in (live or {}).items():
        combo = " + ".join([m for m in MOD_ORDER if mask & MOD_BITS[m]] + [key])
        running[(combo, release)] = descriptions

    findings, ignored = [], 0
    for combo, release in sorted(set(groups) | set(running)):
        group = groups.get((combo, release), [])
        descriptions = running.get((combo, release))
        entries, runtime = [], False
        if descriptions:
            if len(descriptions) < 2:
                # The scanner saw two bindings, but one of them is switched off in a way it cannot see.
                if len(group) > 1 and not all(b.stock for b in group):
                    ignored += 1
                continue
            if len(descriptions) == len(group) and all(b.stock for b in group):
                continue
            unmatched, unexplained = list(group), []
            for description in descriptions:
                match = next((b for b in unmatched if b.description == description), None)
                if match:
                    unmatched.remove(match)
                    entries.append(f'"{match.label}" ({match.where(ctx)})')
                else:
                    unexplained.append(description)
            for description in unexplained:
                if unmatched:
                    # A config binding nobody has claimed explains it better than an unseen plugin.
                    match = unmatched.pop(0)
                    entries.append(f'"{match.label}" ({match.where(ctx)})')
                else:
                    runtime = True
                    entries.append(f'"{description or "no description"}" (added while Hyprland was running)')
        elif len(group) > 1 and not all(b.stock for b in group):
            entries = [f'"{b.label}" ({b.where(ctx)})' for b in group]
        else:
            continue

        mine = next((b for b in group if not b.stock), None)
        if runtime:
            fix = ("A plugin or script registered one of these at run time. Change that shortcut in the "
                   "plugin's settings, or move the other binding to another key.")
        elif any(b.stock for b in group):
            fix = f'Put hl.unbind("{combo}") above your binding to replace Omarchy\'s default, or choose another key.'
        else:
            fix = "Delete one of the bindings, or move one to another key."
        findings.append(Finding(
            "keys", "keys.conflict", WARN, combo + (" (release)" if release else ""),
            f"{combo} is bound {len(entries)} times: {' and '.join(entries)}. Hyprland runs every binding "
            "for a key, so one press triggers all of them.",
            fix, mine.where(ctx) if mine else "",
        ))
    return findings, ignored


def readme_suggestions(directory: Path) -> list:
    """Key combinations a plugin's README offers as copy-paste bindings."""
    combos = []
    for name in ("README.md", "readme.md", "README"):
        path = directory / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:MAX_SOURCE]
        except OSError:
            continue
        combos += [normalize(keys) for keys in _README_LUA.findall(text)]
        for mods, key in _README_CONF.findall(text):
            mods = re.sub(r"\$(mainMod|mod)\b", "SUPER", mods, flags=re.I).upper()
            if "$" not in mods:
                combos.append(normalize(" + ".join(_CONF_MODS.findall(mods) + [key])))
        break
    return sorted({c for c in combos if c})


def check(ctx: Context, inv: Inventory) -> Result:
    result = Result()
    if not (ctx.hypr_dir / "hyprland.lua").is_file() and not (ctx.hypr_dir / "bindings.lua").is_file():
        legacy = (ctx.hypr_dir / "hyprland.conf").is_file()
        result.skipped = True
        result.notes.append(
            f"No Lua config in {ctx.display(ctx.hypr_dir)}"
            + ("; hyprland.conf bindings are not checked." if legacy else "; nothing to check.")
        )
        return result

    binds, files = collect(ctx)
    live = live_binds(ctx)
    found, unconfirmed = conflicts(ctx, binds, live)
    result.findings += found

    verify_builtins = bool(inv.first_party)
    for bind in binds:
        target = plugin_reference(bind.command)
        if not target or bind.stock or inv.first_party.get(target):
            continue
        if target.startswith("omarchy.") and not verify_builtins:
            continue
        plugin = inv.loaded.get(target)
        if plugin is None:
            broken = inv.broken(target)
            reason = "is installed but its manifest does not load" if broken else "is not installed"
            result.findings.append(Finding(
                "keys", "keys.missing-plugin", WARN, bind.combo,
                f'{bind.combo} ("{bind.label}") opens the plugin {target}, which {reason}, so the key does nothing.',
                f"Reinstall the plugin, or delete the binding at {bind.where(ctx)}.",
                bind.where(ctx),
            ))
        elif inv.enabled(target) is False:
            result.findings.append(Finding(
                "keys", "keys.disabled-plugin", WARN, bind.combo,
                f'{bind.combo} ("{bind.label}") opens the plugin {target}, which is installed but not enabled, '
                "so the key does nothing.",
                f"Enable it with `omarchy plugin enable {target}`, or delete the binding at {bind.where(ctx)}.",
                bind.where(ctx),
            ))

    pressed = defaultdict(list)
    for bind in binds:
        if not bind.release:
            pressed[bind.combo].append(bind)
    suggested = defaultdict(list)
    for plugin in inv.third_party:
        for combo in readme_suggestions(plugin.dir):
            suggested[combo].append(plugin.label)
            taken = pressed.get(combo, [])
            # A binding that already drives this plugin is the suggestion, adopted.
            if taken and not any(plugin.label in b.command for b in taken):
                result.findings.append(Finding(
                    "keys", "keys.suggestion-taken", INFO, combo,
                    f"{plugin.label}'s README suggests binding {combo}, but that key already runs "
                    f'"{taken[0].label}" ({taken[0].where(ctx)}).',
                    "Pick a different key if you add the plugin's shortcut.",
                    ctx.display(plugin.dir),
                ))
    for combo, owners in sorted(suggested.items()):
        if len(owners) > 1:
            result.findings.append(Finding(
                "keys", "keys.suggestion-overlap", INFO, combo,
                f"{' and '.join(owners)} both suggest binding {combo} in their READMEs.",
                "Give each plugin its own key if you add their shortcuts.",
            ))

    result.notes.append(f"{len(binds)} bindings read from {len(files)} Lua files.")
    if live is None and ctx.live:
        result.notes.append("Hyprland did not answer `hyprctl binds`; conflicts come from the config files alone.")
    if unconfirmed:
        result.notes.append(
            f"{unconfirmed} apparent double binding{'s' if unconfirmed > 1 else ''} ignored: "
            "the running Hyprland has the key bound once."
        )
    return result
