# OmaDoctor

A health check for your [Omarchy](https://omarchy.org) shell plugins and bar setup.

Install enough marketplace plugins and something eventually goes quietly wrong: a widget
leaves an empty slot on the bar, a key does two things at once, a plugin stops loading
after an update. The shell says so only in its log. OmaDoctor reads the same files the
shell reads, tells you in plain language what is wrong, and suggests the fix.

![OmaDoctor report and bar widget](preview.png)

It is read-only. The one thing it will ever change is your `shell.json`, only when you
run `omadoctor --fix`, and only after saving a backup and showing you the diff.

## What it checks

| Check | Finds |
|---|---|
| `manifests` | Plugin folders the shell cannot load: invalid JSON, wrong `schemaVersion`, missing fields, unusable or reserved `omarchy.*` ids, missing entry point files, two folders with the same id, a folder named differently from its id, symlinks |
| `bar` | `shell.json` entries that point nowhere: widgets and plugins that are not installed, widgets placed twice that do not support it, widgets in a section other than left/center/right, entries without an id, custom modules whose file is gone, a `shell.json` the shell ignores entirely |
| `keys` | Keys bound to two actions (in your Hyprland Lua config, against Omarchy's defaults, or by a plugin at run time), keys that open a plugin which is not installed or not enabled, and shortcuts a plugin's README suggests that are already taken |
| `deps` | Commands a plugin's README lists under Requirements that are not installed |
| `stale` | Git-installed plugins with local edits (which block `omarchy plugin update`), and plugin code that imports or loads files that no longer exist |
| `health` | Whether the shell is running, whether it has picked up every installed plugin, and which plugins have logged errors since it started |

Each finding is an **ERROR** (something is broken), a **WARN** (something is wrong but
the shell copes), or a note (worth knowing, nothing to do).

## Requirements

- Omarchy 4 (the Quickshell-based shell)
- `python3`, which Omarchy ships. OmaDoctor uses only the standard library and runs `/usr/bin/python3`.

It also uses these when they are present, and skips the related check when they are not;
all of them are part of an Omarchy install:

- `git`, optional, only for the local-edits check
- `journalctl` and `omarchy-shell`, optional, only for the shell health check
- `hyprctl`, optional, only to see keybindings registered at run time
- `pacman`, optional, only to recognise a requirement that names a package instead of a command

No pip packages, no daemon, no network access, no elevated privileges.

## Install

```bash
omarchy plugin add https://github.com/DavidGudovic/omadoctor.git
```

Omarchy clones the repository into `~/.config/omarchy/plugins/io.github.davidgudovic.omadoctor/`
and leaves it disabled so you can read the code first.

To use the command from anywhere, link it into `~/.local/bin` (already on `PATH` in Omarchy):

```bash
ln -s ~/.config/omarchy/plugins/io.github.davidgudovic.omadoctor/bin/omadoctor ~/.local/bin/omadoctor
```

To put the widget on the bar (optional):

```bash
omarchy plugin enable io.github.davidgudovic.omadoctor
```

## Usage

```bash
omadoctor                    # the full report
omadoctor --only bar,keys    # just these checks
omadoctor --skip health      # everything but this one
omadoctor --json             # the same report, for scripts
omadoctor --fix --dry-run    # show what --fix would change
omadoctor --fix              # remove dead shell.json entries (backup + diff)
omadoctor --strict           # also exit 1 when there are warnings
```

Exit status is `0` when there are no errors, `1` when there are (so it can gate a hook
or a CI job), and `2` when OmaDoctor itself could not run.

`--config-dir`, `--hypr-dir` and `--omarchy-path` point it at another setup, such as a
dotfiles checkout in CI. Pointed away from your own session, or run with `--no-live`, it
does not query the running shell, the journal or Hyprland.

For example, to be told after every `omarchy update` if something broke, save this as a
file named `omadoctor-after-update`:

```bash
#!/bin/bash
omadoctor --skip health >/dev/null ||
  omarchy-notification-send "OmaDoctor found plugin errors" "Run omadoctor for the report"
```

and install it with `omarchy hook install post-update omadoctor-after-update`. Omarchy
copies it into `~/.config/omarchy/hooks/post-update.d/`; delete it there to undo.

## What `--fix` does

`--fix` repairs one kind of problem: entries in `~/.config/omarchy/shell.json` that the
shell already ignores. It removes

- bar entries for widgets that are not installed and not built in,
- extra placements of a widget that does not support several,
- bar entries without an id,
- `plugins` entries for plugins that are not installed,
- a `bar.id` naming a bar that is not installed.

The bar looks the same before and after. Before writing, it copies the file to
`shell.json.bak.omadoctor.<timestamp>` next to it and prints a unified diff; the output
ends with the `cp` command that undoes the change. It leaves an entry alone whenever the
plugin might merely be broken rather than gone, and says so.

Everything else in the report comes with a suggestion but is yours to fix: OmaDoctor
never edits plugin code, your Hyprland config, or anything under `/usr/share/omarchy`.

## The bar widget

The widget runs the same checks in the background (ten seconds after the shell starts,
then every 30 minutes) and shows a stethoscope with the number of errors and warnings.
With errors it takes the theme's urgent color. With nothing to report it stays off the
bar, like Omarchy's own update indicator.

- Left click opens the report in a floating terminal.
- Right click checks again now.

Settings, in the widget's `shell.json` entry or with `omarchy bar set`:

| Key | Default | Meaning |
|---|---|---|
| `alwaysShow` | `false` | Keep the icon on the bar when no problems are found |
| `refreshIntervalSec` | `1800` | Seconds between background checks (minimum 60) |

```bash
omarchy bar set io.github.davidgudovic.omadoctor alwaysShow true
omarchy bar set io.github.davidgudovic.omadoctor refreshIntervalSec 600 --json
omarchy-shell io.github.davidgudovic.omadoctor refresh    # re-check now
omarchy-shell io.github.davidgudovic.omadoctor report     # open the report
```

## What it reads, runs and writes

OmaDoctor reads `~/.config/omarchy/shell.json`, the folders in `~/.config/omarchy/plugins/`,
the Lua files your `~/.config/hypr/hyprland.lua` loads, and Omarchy's own defaults under
`$OMARCHY_PATH`.

It runs these local, read-only commands: `sh -c 'command -v …'`, `pacman -Qq`,
`git --no-optional-locks status` in each plugin checkout, `omarchy-shell shell ping`,
`omarchy-shell shell listPlugins`, `hyprctl -j binds` and `journalctl --user -t omarchy-shell`.
It never fetches, never contacts a network, and sends nothing anywhere.

It writes nothing, with one exception: `omadoctor --fix` rewrites `shell.json` and leaves
a `shell.json.bak.omadoctor.<timestamp>` backup beside it. There is no cache, no state
directory and no log file.

## Remove

```bash
omarchy plugin remove io.github.davidgudovic.omadoctor
rm -f ~/.local/bin/omadoctor
rm -f ~/.config/omarchy/shell.json.bak.omadoctor.*    # backups from --fix, if you ran it
```

`omarchy plugin remove` takes the widget off the bar and deletes the plugin folder. The
two `rm` lines cover the only other files OmaDoctor can have created.

## How sure is it

The `manifests` and `bar` checks apply the same rules as the shell's plugin registry and
`omarchy plugin validate`, so they are exact. The others read things that were not
written for a machine, and say less when they are less sure:

- **Keybindings** are found by scanning Lua for `o.bind`, `hl.bind` and `hl.unbind` calls
  with literal keys, following `require` in load order. Bindings built in loops or from
  variables are not seen. When Hyprland is running, its own binding table has the last
  word, which also catches shortcuts plugins register at run time. Keys bound by keycode
  (`code:38`) are compared with each other but not with their named equivalents.
- **Dependencies** come from the README, since manifests have no dependency field. Only
  `backticked` names in the lists and tables of a Requirements, Dependencies or
  Prerequisites section count, and anything described as optional becomes a note.
- **Missing files** are literal paths in `import "…"`, `Qt.resolvedUrl("…")` and
  `source: "…"`. Paths assembled at run time are not checked.
- **Log errors** are warnings and errors the shell logged about a plugin since the shell
  process started. Restart the shell (`omarchy restart shell`) to clear old ones.

## Development

```bash
bash tests/run.sh
```

The tests use only the standard library and the fixtures in `tests/fixtures/`: a small
stand-in Omarchy install, a healthy setup, a broken one with one problem per plugin, and
one with only the problems `--fix` repairs.

## License

MIT. See [LICENSE](LICENSE).
