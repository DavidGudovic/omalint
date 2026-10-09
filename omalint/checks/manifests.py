"""Plugin manifests: is every installed plugin something the shell can load?"""

from __future__ import annotations

from collections import defaultdict

from ..inventory import Inventory
from ..model import ERROR, Context, Finding, Result

TITLE = "Plugin manifests"


def check(ctx: Context, inv: Inventory) -> Result:
    result = Result()
    for plugin in inv.third_party:
        for code, severity, message, fix in plugin.problems:
            result.findings.append(
                Finding("manifests", code, severity, plugin.dir.name, message, fix, ctx.display(plugin.dir))
            )

    folders = defaultdict(list)
    for plugin in inv.third_party:
        if plugin.id:
            folders[plugin.id].append(plugin.dir.name)
    for plugin_id, names in sorted(folders.items()):
        if len(names) > 1:
            result.findings.append(Finding(
                "manifests", "manifest.id-collision", ERROR, plugin_id,
                f'{len(names)} folders declare the plugin id "{plugin_id}": {", ".join(names)}. '
                "The shell keeps one and silently ignores the rest.",
                "Remove the copy you do not want, so only one folder has this id.",
                ctx.display(ctx.plugins_dir),
            ))

    if not inv.third_party:
        result.notes.append(f"No plugins installed in {ctx.display(ctx.plugins_dir)}.")
    else:
        total = len(inv.third_party)
        rejected = sum(1 for p in inv.third_party if not p.loadable)
        result.notes.append(
            f"{total} plugin folder{'' if total == 1 else 's'} checked"
            + (f"; the shell does not load {rejected} of them." if rejected else ".")
        )
    return result
