"""Command line: run the checks, print the report, optionally fix shell.json."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import fixes, inventory, report
from .checks import CHECKS
from .model import WARN, Context, Finding, Result

VERSION = "0.1.0"

DESCRIPTION = """\
Find problems in your Omarchy shell plugins and bar setup.

Checks (choose with --only / --skip):
  manifests  every plugin folder has a manifest the shell can load
  bar        shell.json only places widgets and plugins that exist
  keys       no key is bound twice, no key opens a missing plugin
  deps       commands a plugin's README lists as required are installed
  stale      git-installed plugins are unmodified; code refers to files that exist
  health     the shell is running and plugins are not logging errors

Nothing is changed unless you pass --fix, and --fix only edits
~/.config/omarchy/shell.json after saving a shell.json.bak.<timestamp> copy.

Exit status: 0 no errors, 1 errors found (with --strict: or warnings), 2 could not run.
"""


def _names(value: str) -> list:
    names = [name.strip() for name in value.split(",") if name.strip()]
    unknown = [name for name in names if name not in CHECKS]
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown check {', '.join(unknown)} (choose from {', '.join(CHECKS)})")
    return names


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(
        prog="omadoctor", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="print the report as JSON")
    mode.add_argument("--fix", action="store_true", help="remove dead entries from shell.json (backup + diff)")
    cli.add_argument("--dry-run", action="store_true", help="with --fix: show the diff, write nothing")
    cli.add_argument("--only", type=_names, metavar="CHECKS", help="run only these checks (comma-separated)")
    cli.add_argument("--skip", type=_names, metavar="CHECKS", default=[], help="skip these checks")
    cli.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    cli.add_argument("--no-live", action="store_true", help="do not query the running shell, journal or Hyprland")
    cli.add_argument("--no-color", action="store_true", help="plain text output")
    cli.add_argument("--config-dir", type=Path, metavar="DIR", help="Omarchy config directory (default: ~/.config/omarchy)")
    cli.add_argument("--hypr-dir", type=Path, metavar="DIR", help="Hyprland config directory (default: ~/.config/hypr)")
    cli.add_argument("--omarchy-path", type=Path, metavar="DIR", help="Omarchy install (default: $OMARCHY_PATH)")
    cli.add_argument("--version", action="version", version=f"omadoctor {VERSION}")
    return cli


def context(args) -> Context:
    home = Path(os.path.expanduser("~"))
    # The running session belongs to the default directories; point elsewhere and
    # the shell, journal and Hyprland would describe a different setup.
    elsewhere = any(value is not None for value in (args.config_dir, args.hypr_dir, args.omarchy_path))
    return Context(
        config_dir=(args.config_dir or home / ".config" / "omarchy").absolute(),
        hypr_dir=(args.hypr_dir or home / ".config" / "hypr").absolute(),
        omarchy_path=(args.omarchy_path or Path(os.environ.get("OMARCHY_PATH") or "/usr/share/omarchy")).absolute(),
        live=not (args.no_live or elsewhere),
    )


def run_checks(ctx: Context, names) -> tuple:
    inv = inventory.build(ctx)
    results = {}
    for name in names:
        try:
            results[name] = CHECKS[name].check(ctx, inv)
        except Exception as error:  # one broken check must not hide the others
            results[name] = Result([Finding(
                "doctor", "doctor.check-crashed", WARN, name,
                f"The {name} check stopped unexpectedly ({type(error).__name__}: {error}).",
                "This is a bug in omadoctor; please report it.",
            )])
    return inv, results


def _fix(ctx: Context, inv, results, dry_run: bool, color: bool) -> bool:
    """Returns True when shell.json was rewritten."""
    fixable = [finding for result in results.values() for finding in result.findings if finding.fixable]
    if not fixable:
        print("Nothing here can be fixed automatically.\n")
        return False

    name = ctx.display(ctx.shell_json)
    old = ctx.shell_json.read_text(encoding="utf-8")
    new_config, fixed = fixes.plan(inv.shell_config, fixable)
    new = fixes.render(new_config)

    print(f"Fixing {len(fixed)} problem{'s' if len(fixed) != 1 else ''} in {name}:")
    for finding in fixed:
        print(f"  - {finding.message}")
    print()
    if fixes.render(inv.shell_config) != old:
        print("Note: the file was not in the shell's own formatting, so the diff also shows re-indentation.\n")
    for line in fixes.diff(old, new, name).splitlines():
        tint = {"+": "32", "-": "31", "@": "36"}.get(line[:1]) if color and not line.startswith(("+++", "---")) else None
        print(f"\x1b[{tint}m{line}\x1b[0m" if tint else line)
    print()
    if dry_run:
        print("Dry run: nothing was written.\n")
        return False
    backup = fixes.apply(ctx, ctx.shell_json, old, new)
    print(f"Backup saved: {ctx.display(backup)}")
    print(f"To undo: cp {ctx.display(backup)} {name}\n")
    return True


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.dry_run and not args.fix:
        print("omadoctor: --dry-run only makes sense with --fix", file=sys.stderr)
        return 2
    names = [name for name in (args.only or CHECKS) if name not in args.skip]
    color = not args.no_color and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    results = {}
    try:
        ctx = context(args)
        inv, results = run_checks(ctx, names)
        if args.fix:
            # Fixes come from the bar check, whichever checks were asked for.
            source = results if "bar" in results else run_checks(ctx, ["bar"])[1]
            if _fix(ctx, inv, source, args.dry_run, color):
                inv, results = run_checks(ctx, names)
        if args.json:
            json.dump(report.as_json(results, VERSION, len(inv.third_party)), sys.stdout, indent=2, ensure_ascii=False)
            print()
        else:
            width = min(shutil.get_terminal_size((100, 24)).columns, 110) - 2
            count = len(inv.third_party)
            title = f"OmaDoctor: {count} plugin{'' if count == 1 else 's'} in {ctx.display(ctx.plugins_dir)}"
            sys.stdout.write(report.as_text(results, color, width, title))
        sys.stdout.flush()
    except fixes.FixError as error:
        print(f"omadoctor: {error}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        # The reader went away (`omadoctor | head`). Point stdout somewhere harmless so
        # Python does not complain while exiting; the exit status still reports the findings.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except OSError as error:
        print(f"omadoctor: {error}", file=sys.stderr)
        return 2
    totals = report.summary(results)
    return 1 if totals["errors"] or (args.strict and totals["warnings"]) else 0
