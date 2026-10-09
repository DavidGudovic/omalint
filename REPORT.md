# OmaLint: final report

**Status: ready to publish, not published.** The repository is local only, as
instructed. Nothing has been pushed and no GitHub repository exists yet. The working
tree is clean, 249 tests pass, `omarchy plugin validate` accepts it, and the
marketplace's own static security baseline reports `passed`.

| | |
|---|---|
| Repository | `~/projects/omalint` (branch `main`), to become `DavidGudovic/omalint` |
| Plugin id | `io.github.davidgudovic.omalint` |
| Command | `omalint` |
| Version | 0.1.0 |

## What it is

A health check for Omarchy shell plugins and the bar setup. A stdlib-only Python command
(`bin/omalint`, package `omalint/`) runs six read-only checks and prints a grouped
OK / WARN / ERROR report with a plain-language fix for each finding. A small bar widget
(`Widget.qml`) runs the same checks in the background and shows the count.

| Check | What it reports |
|---|---|
| `manifests` | Plugin folders the shell cannot load: invalid JSON, wrong `schemaVersion`, missing fields, unusable or reserved `omarchy.*` ids, missing entry point files, id collisions, folder/id mismatch, symlinks |
| `bar` | `shell.json` entries pointing at widgets or plugins that are not installed, widgets placed twice that do not support it, unknown sections, entries without an id, missing custom modules, a `shell.json` the shell ignores |
| `keys` | Keys bound to more than one action (config files, Omarchy defaults, and bindings plugins register at run time), keys that open a missing or disabled plugin, README-suggested shortcuts that are already taken |
| `deps` | Commands a plugin's README or manifest lists as required that `command -v` cannot find |
| `stale` | Git-installed plugins with local edits, and plugin code referring to files that no longer exist |
| `health` | Whether the shell is running, whether it has picked up every plugin, and plugin errors in the shell log since it started |

Output: text report by default, `--json` for machines, exit status 0 / 1 (errors found) /
2 (could not run), `--strict` to fail on warnings too. `--fix` removes dead `shell.json`
entries after writing a `shell.json.bak.omalint.<timestamp>` backup and printing a diff;
`--fix --dry-run` shows the diff and writes nothing.

## Install and remove

Install (once published):

```bash
omarchy plugin add https://github.com/DavidGudovic/omalint.git
ln -s ~/.config/omarchy/plugins/io.github.davidgudovic.omalint/bin/omalint ~/.local/bin/omalint
omarchy plugin enable io.github.davidgudovic.omalint    # optional: the bar widget
```

Remove:

```bash
omarchy plugin remove io.github.davidgudovic.omalint
rm -f ~/.local/bin/omalint
rm -f ~/.config/omarchy/shell.json.bak.omalint.*    # only exist if --fix was run
```

Those are the only files it can create. It keeps no cache, state directory or log, and
does not write Python bytecode into the plugin folder.

Per the brief, the plugin was **not** installed into `~/.config/omarchy/plugins` and no
`omarchy plugin` install command was run.

## What was tested

**Unit and fixture tests: 249, all passing** (`bash tests/run.sh`, about 4 seconds,
standard library only). Fixtures under `tests/fixtures/`:

- `stock/`: a miniature Omarchy install (built-in plugins, default Hyprland bindings)
- `healthy/`: a setup with nothing wrong, which must produce no warnings
- `broken/`: one problem per plugin or config entry (invalid manifest, missing fields,
  reserved id, id collision, missing entry point, missing dependency, bad `shell.json`
  references, key conflicts, missing imports)
- `fixable/`: only the problems `--fix` repairs
- `journal.txt`: a captured shell log

Each finding is asserted by code, subject and severity. Git and symlink cases are built
at run time in temporary directories, so the repository itself contains no symlinks and
no nested `.git`. The tests added for the review fixes were also run against the pre-fix
code, where every one that covers a fixed defect fails.

**Real machine, read-only.** Run against the real `~/.config/omarchy` and
`~/.config/hypr` (13 plugins). Output below. A snapshot taken immediately before and
after three runs (text, `--json`, `--fix --dry-run`) was identical: the hash of
`shell.json`, the names, sizes and modification times of everything in both config
directories, the `.git/index` of all 11 plugin checkouts, and the absence of
`__pycache__`.

**The `--fix` path** on a copy of the fixture: transcript below. The backup is
byte-identical to the original, the diff shows exactly the four removed entries, a
second run finds nothing to fix and makes no second backup, and `--dry-run` leaves the
file untouched.

**The widget** was loaded in a scratch Quickshell instance (offscreen, so nothing
appeared on screen) using the shell's real `Commons` and `Ui` components and the real
`PluginBarApi` facade that third-party widgets receive. It loaded without QML errors,
ran the real command and parsed the same 2 warnings the CLI reports, hides the count on
a vertical bar, and shows "could not run" rather than breaking when its script is
missing. The double shell-quoting of the click command was verified through both shell
evaluations with a path containing spaces and an apostrophe.

**Marketplace rules.** `omarchy plugin validate .` exits 0. One `manifest.json`, at the
root. README has install and removal sections; LICENSE is MIT. No symlinks. The
marketplace's `security-baseline-analysis.mjs`, run locally over the tracked files,
reports `outcome: passed`.

### Real output on this machine

```
OmaLint: 13 plugins in ~/.config/omarchy/plugins

  OK     Plugin manifests
         13 plugin folders checked.

  OK     Bar layout
         25 bar entries checked in ~/.config/omarchy/shell.json.

  OK     Keybindings
         • omamail's README suggests binding SUPER + SHIFT + G, but that key already runs "Signal"
           ($OMARCHY_PATH/default/hypr/bindings/applications.lua:17).
           → Pick a different key if you add the plugin's shortcut.
         • x99.dockarchy's README suggests binding SUPER + SHIFT + D, but that key already runs
           "Servers menu" (~/.config/hypr/bindings.lua:41).
           → Pick a different key if you add the plugin's shortcut.
         190 bindings read from 27 Lua files.

  OK     Dependencies
         32 declared commands checked with `command -v`.

  WARN   Stale or modified plugins
         ! zeru.portwatch differs from the version its author published: 1 changed
           (PortsPopup.qml). `omarchy plugin update` stops when an update changes a file you have
           edited.
           → See your changes with `git -C ~/.config/omarchy/plugins/zeru.portwatch diff`. To drop
             them: `git -C ~/.config/omarchy/plugins/zeru.portwatch restore .`. To carry them
             across an update: `git -C ~/.config/omarchy/plugins/zeru.portwatch stash`, update,
             then `git -C ~/.config/omarchy/plugins/zeru.portwatch stash pop`.
         11 git checkouts compared with their last commit (no network).

  WARN   Shell health
         ! x99.dockarchy logged 2 problems since the shell started (last at 11:12):
           Panel.qml[815:-1]: TypeError: Cannot call method 'unregisterRow' of null (×2)
           → Try `omarchy plugin update x99.dockarchy`; if it persists, report it to the plugin's
             author. Full log: journalctl --user -b -t omarchy-shell
         Shell is running (PID 1700); 196 log lines checked.

  2 warnings found. 2 notes (•) need no action.
```

Exit status 0. `--json` summary: `{"errors":0,"warnings":2,"notes":2,"fixable":0,"plugins":13}`.
Both warnings are real: `zeru.portwatch` has an uncommitted edit, and the shell journal
does contain that `TypeError` from `x99.dockarchy`. The static binding scan was compared
with the running Hyprland: every named key it found is bound there the same number of
times.

### `--fix` on a copy of the fixture

```
Fixing 4 problems in fixable/omarchy/shell.json:
  - bar.id selects "acme.neon-bar", which is neither an installed plugin nor built in. The shell falls back to the built-in bar.
  - bar.layout.left[1] references acme.gone, which is neither an installed plugin nor built in. The bar leaves an empty slot.
  - bar.layout.center[1] has no id, so the bar shows nothing for it.
  - plugins[0] enables acme.vanished, which is neither an installed plugin nor built in.

--- fixable/omarchy/shell.json
+++ fixable/omarchy/shell.json (fixed)
@@ -5,26 +5,18 @@
     "lock": 300
   },
   "bar": {
-    "id": "acme.neon-bar",
     "position": "top",
     "centerAnchor": "omarchy.clock",
     "layout": {
       "left": [
         {
           "id": "omarchy.workspaces"
-        },
-        {
-          "id": "acme.gone",
-          "color": "red"
         }
       ],
       "center": [
         {
           "id": "omarchy.clock",
           "verticalFormat": "HH\n—\nmm"
-        },
-        {
-          "size": 4
         }
       ],
       "right": [
@@ -44,10 +36,6 @@
   },
   "plugins": [
     {
-      "id": "acme.vanished",
-      "interval": 5
-    },
-    {
       "id": "omarchy.emojis"
     }
   ]

Backup saved: fixable/omarchy/shell.json.bak.omalint.1791539101
To undo: cp fixable/omarchy/shell.json.bak.omalint.1791539101 fixable/omarchy/shell.json

OmaLint: 1 plugin in fixable/omarchy/plugins

  OK     Bar layout
         5 bar entries checked in
         fixable/omarchy/shell.json.

  No problems found.
```

`cmp` confirms the backup equals the original file. A second `--fix` prints "Nothing
here can be fixed automatically." and leaves one backup. (Paths shortened: the copy
lived in a scratch directory.)

## The review and what changed

A fresh Opus subagent reviewed the merged code against Omarchy's own sources, the 13
real plugins and the marketplace scripts. It found no blockers, 3 major and 11 minor
problems, and 2 nits. I checked each before acting; all but one were real and are fixed.

| # | Finding | What was done |
|---|---|---|
| 1 | Major. A bar entry whose `id` is an array (`{"id": ["acme.good"]}`) works in the shell, but was reported as having no id and removed by `--fix` | Ids are now read exactly as the shell reads them (`String(id)`), in the layout, `plugins`, `bar.id` and manifests |
| 2 | Major. The local-edits warning said updates always fail and advised committing, which would block every later update | Reproduced with git, then reworded: an update stops only when it touches an edited file; the advice is `stash`, not commit |
| 3 | Major. A config binding without a description was blamed on "a plugin or script" | Running bindings are matched to config lines by description, and an unclaimed config line is preferred over an unseen plugin |
| 4 | `if`/`else` arms binding the same key were reported as a conflict when Hyprland is not queried | Arms of one `if` are treated as alternatives |
| 5 | `--fix` could write invalid JSON (`1e400` became `Infinity`) | Refused with exit 2; nothing written |
| 6 | README referenced a `preview.png` that did not exist | Added |
| 7 | Backticked words that are not programs (`requests` modules, `i2c` group) counted as required commands | Such words are filtered by context. This stays a heuristic; see limitations |
| 8 | A manifest with a byte-order mark, or a non-string id, was reported as rejected though the shell loads it | Both now follow the shell. I confirmed in Quickshell that a BOM never reaches its JSON parser |
| 9 | `--help` named the wrong backup file | Fixed |
| 10 | README said a new plugin is left disabled; `omarchy plugin add` asks | Fixed |
| 11 | With `shell.json` symlinked into a dotfiles folder, the backup landed there and the removal instructions missed it | The backup now goes beside the path the user knows |
| 12 | Without `git`, the report still claimed checkouts were compared; a missing `omarchy-shell` was a warning, not a skip | Notes are accurate; the health check is skipped and says so |
| 13 | Two odd `shell.json` inputs ended `--fix` in a traceback | Clean refusal, exit 2; unexpected errors also exit 2 rather than 1 |
| 14 | The marketplace baseline would report `review-required` because a hint named `omarchy pkg add` | Hint reworded; the baseline now reports `passed` |
| 15 | Nit. A crashed check was only a warning, so a CI gate would pass | It is an error now |
| 16 | Nit. Widget: guessed width for the count, README silent about vertical bars, stethoscope left over from the old name | Width is measured, README says so, icon is a checklist |

Not changed: the reviewer noted that with several monitors each bar's copy of the widget
runs its own check. That is a half-second of work per monitor every 30 minutes, so I
left it (listed below).

Before that review, my own pass led to three stricter `--fix` rules, also in the code:
a widget placed twice is reported but never removed (the bar draws both copies);
nothing in the `omarchy.*` namespace is ever removed; and `--fix` refuses a `shell.json`
that changed since it was checked.

The reviewer did not audit the test suite itself, the text renderer, or the widget at
run time. I covered the last one in the harness described above.

## Naming and publication

The project was renamed twice during the build and is now OmaLint throughout, including
the Python package. No remote was ever configured and no repository was ever created
under an earlier name, so there is nothing to rename on GitHub.

Name check, done on 2026-10-09:

- `DavidGudovic/omalint` does not exist.
- No repository named `omalint` exists under any owner on GitHub.
- The marketplace registry (fetched the same day) lists no plugin whose id, name or
  repository contains `omalint`, and `io.github.davidgudovic.omalint` is unused.

One correction to the finish notice: it says the marketplace already lists
`Davedes83/OmaLint`. That repository does not exist. What exists and is listed is
`Davedes83/OmaDoctor`, which was the conflict with the previous name. The rename removes
it, so I see no open naming question, but the decision to publish is the owner's.

To publish:

```bash
cd ~/projects/omalint
gh repo create DavidGudovic/omalint --public --source . --remote origin --push
gh repo view DavidGudovic/omalint --json visibility,url
```

## Known limitations

- **Never run inside the real bar.** The widget was verified in a separate offscreen
  Quickshell instance with the shell's real components, not in the running Omarchy
  shell, because installing was out of bounds. The first real install is the first time
  it runs there.
- **Keybindings** are found by scanning Lua for literal `o.bind` / `hl.bind` /
  `hl.unbind` calls. Bindings built in loops or from variables are invisible unless
  Hyprland is running, when its own table decides. Keys bound by keycode (`code:38`) are
  not matched with their named equivalents, and Hyprland reports them without a name.
  Legacy `hyprland.conf` bindings are not checked.
- **Dependencies** come from README prose. Only backticked names in the lists and tables
  of a Requirements-style section count, and optional ones become notes, but a
  backticked word that is not a program can still be mistaken for one.
- **Missing files** covers literal paths in `import`, `Qt.resolvedUrl` and `source:`
  only.
- **Log errors** are those since the current shell process started; they persist until
  the shell restarts, even after the cause is fixed.
- **`--fix`** only removes dead `shell.json` entries. Everything else is a suggestion.
  A number such as `1.0` is rewritten by Python as `1.0` where the shell would write
  `1`; the diff shows it.
- **The stale check runs `git status`** inside each plugin checkout, with optional
  locks and fsmonitor disabled. Like any git command there, it trusts the checkout's
  own git configuration.
- **Multiple monitors:** each bar's copy of the widget runs its own check.
- **`preview.png` is a render, not a screenshot.** It is the real `Widget.qml` and real
  report output, drawn offscreen in the stock Tokyo Night theme over a small made-up
  setup, with the shell, journal and Hyprland answers simulated. The bar strip and
  clock text around the widget are a mock.

## Things that happened during the build

- **A stray desktop notification.** At about 10:50 a patch command of mine went through
  a shell heredoc whose text contained an `EOF` line, so the shell ran part of a README
  snippet. The effect was one low-urgency notification reading "OmaDoctor found plugin
  errors / Run omadoctor for the report". It was false: nothing had been checked. I
  verified nothing else happened: no hook was installed, no update ran, no file changed.
  I did not dismiss it because the notification service can only dismiss "the last" or
  "all", and either could have removed one of yours. I stopped editing files through
  heredocs after that.
- **`shell.json` changed during the build, not by this tool.** At 11:17:57 the
  `jrmmhm.pocket` entry's `"pinned"` setting went from `"MPG271QX OLED"` to `""`. That
  is the Pocket widget saving its own state. OmaLint's write path always leaves a backup
  first and none exists; the before/after snapshot above was taken after noticing this.
- **Subagents.** A Sonnet subagent wrote the first 204 tests from an exact spec; I read
  all of them, extended them, and stopped it when it moved on to unrequested mutation
  testing, so it never sent a written report. The first Opus review was lost when that
  run ended; the review described above is the second, run to completion.

## Repository URL

Not created yet. Once published: https://github.com/DavidGudovic/omalint
