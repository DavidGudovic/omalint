"""Stale plugins: local edits to git checkouts, and code that points at files that are gone."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..inventory import Inventory, Plugin
from ..model import ERROR, WARN, Context, Finding, Result

TITLE = "Stale or modified plugins"

# Folders the shell never loads code from.
_SKIP = {".git", "node_modules", "target", "tests", "test", "docs", "dev", "benchmarks", "examples", "build", "dist"}
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_ASSET = re.compile(r"\.(qml|m?js|png|svg|jpe?g|webp|gif|ttf|otf|json|wav|mp3|ogg|frag|vert|qsb)$", re.I)
_IMPORT = re.compile(r'^[ \t]*\.?import\s+"([^"\n]+)"', re.M)
_RESOLVED = re.compile(r'Qt\.resolvedUrl\(\s*"([^"\n]+)"\s*\)')
_SOURCE = re.compile(r'\bsource\s*:\s*"([^"\n]+)"')
MAX_FILES = 2000
MAX_SOURCE = 1024 * 1024


def strip_comments(text: str) -> str:
    """Blank // and /* */ comments in QML or JavaScript, keeping strings and line numbers."""
    out = list(text)
    size = len(text)
    i = 0
    while i < size:
        char = text[i]
        if char in "\"'`":
            j = i + 1
            while j < size and text[j] != char and (char == "`" or text[j] != "\n"):
                j += 2 if text[j] == "\\" else 1
            i = j + 1
        elif text.startswith("//", i) or text.startswith("/*", i):
            if text[i + 1] == "/":
                end = text.find("\n", i)
                end = size if end == -1 else end
            else:
                end = text.find("*/", i + 2)
                end = size if end == -1 else end + 2
            for index in range(i, end):
                if out[index] != "\n":
                    out[index] = " "
            i = end
        else:
            i += 1
    return "".join(out)


def references(text: str) -> list:
    """(kind, line, target) for each local file a QML/JS source refers to by a literal path."""
    text = strip_comments(text)
    found = []
    for kind, pattern in (("import", _IMPORT), ("resolvedUrl", _RESOLVED), ("source", _SOURCE)):
        for match in pattern.finditer(text):
            target = match.group(1)
            if _SCHEME.match(target) or target[0] in "/~$" or "${" in target or "%" in target:
                continue
            if kind != "import" and not _ASSET.search(target):
                continue
            found.append((kind, text.count("\n", 0, match.start(1)) + 1, target))
    return found


def _sources(root: Path):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP and not d.startswith("."))
        for name in sorted(filenames):
            if name.endswith((".qml", ".js")):
                count += 1
                if count > MAX_FILES:
                    return
                yield Path(dirpath) / name


def missing_files(plugin: Plugin) -> list:
    """(relative file, line, target, is_entry_point_import) for references that do not resolve."""
    entry_points = set()
    if plugin.manifest and isinstance(plugin.manifest.get("entryPoints"), dict):
        entry_points = {v for v in plugin.manifest["entryPoints"].values() if isinstance(v, str)}
    broken = []
    for path in _sources(plugin.dir):
        try:
            if path.stat().st_size > MAX_SOURCE:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        relative = str(path.relative_to(plugin.dir))
        for kind, line, target in references(text):
            if not (path.parent / target.split("?")[0].split("#")[0]).exists():
                broken.append((relative, line, target, kind == "import" and relative in entry_points))
    return broken


def git_changes(ctx: Context, directory: Path):
    """(modified, untracked) paths of a git checkout, or None when git cannot say."""
    # Inherited GIT_DIR and friends (set inside git hooks) would point git at another repo.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    run = ctx.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(directory), "status", "--porcelain"],
        timeout=15,
        env=env,
    )
    if not run.ok:
        return None
    modified, untracked = [], []
    for line in run.out.splitlines():
        if len(line) > 3:
            (untracked if line.startswith("??") else modified).append(line[3:].strip('"'))
    return modified, untracked


def _some(items, limit=3) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def check(ctx: Context, inv: Inventory) -> Result:
    result = Result()
    checkouts = unknown = 0
    for plugin in inv.third_party:
        where = ctx.display(plugin.dir)
        if (plugin.dir / ".git").exists():
            checkouts += 1
            changes = git_changes(ctx, plugin.dir)
            if changes is None:
                unknown += 1
            elif changes[0] or changes[1]:
                modified, untracked = changes
                parts = []
                if modified:
                    parts.append(f"{len(modified)} changed ({_some(modified)})")
                if untracked:
                    parts.append(f"{len(untracked)} untracked ({_some(untracked)})")
                # `omarchy plugin update` is a fast-forward merge: it only fails when the update
                # touches the same files, and a local commit would block every later update.
                if modified:
                    consequence = "`omarchy plugin update` stops when an update changes a file you have edited."
                    fix = (f"See your changes with `git -C {where} diff`. To drop them: `git -C {where} restore .`. "
                           f"To carry them across an update: `git -C {where} stash`, update, "
                           f"then `git -C {where} stash pop`.")
                else:
                    consequence = "`omarchy plugin update` stops if an update adds a file with one of those names."
                    fix = f"List them with `git -C {where} status`, and delete them if they are leftovers."
                result.findings.append(Finding(
                    "stale", "stale.local-changes", WARN, plugin.label,
                    f"{plugin.label} differs from the version its author published: {'; '.join(parts)}. "
                    + consequence,
                    fix,
                    where,
                ))

        broken = missing_files(plugin)
        if broken:
            fatal = any(entry for _, _, _, entry in broken)
            listed = "; ".join(f'{file}:{line} → "{target}"' for file, line, target, _ in broken[:3])
            more = f" and {len(broken) - 3} more" if len(broken) > 3 else ""
            result.findings.append(Finding(
                "stale", "stale.missing-file", ERROR if fatal else WARN, plugin.label,
                f"{plugin.label} refers to {len(broken)} file{'s' if len(broken) > 1 else ''} "
                f"that {'do' if len(broken) > 1 else 'does'} not exist: {listed}{more}."
                + (" Its entry point cannot load." if fatal else " The part that uses it will fail."),
                "Reinstall or update the plugin; if you edited it, restore the missing file.",
                where,
            ))

    compared = checkouts - unknown
    result.notes.append(
        f"{compared} git checkout{'s' if compared != 1 else ''} compared with their last commit (no network)."
    )
    if unknown:
        result.notes.append(
            f"Local edits were not checked for {unknown} checkout{'s' if unknown > 1 else ''}: "
            "git did not answer (is it installed?)."
        )
    return result
