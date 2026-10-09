# OmaLint: final report

**Status: ready to publish, not published.** `DavidGudovic/omalint` does not exist on
GitHub and this repository has no remote, so everything is committed locally only. The
working tree is clean, 321 tests pass, `omarchy plugin validate` accepts it, and the
marketplace's own static security baseline reports `passed`.

| | |
|---|---|
| Repository | `~/projects/omalint` (branch `main`), to become `DavidGudovic/omalint` |
| Plugin id | `io.github.davidgudovic.omalint` |
| Command | `omalint` |
| Version | 0.3.0 |

## Round 3: inspection

I used OmaLint the way a new user would: in a temporary HOME with nothing configured,
with a stock `shell.json`, with the sample setup, and with the plugin installed into that
temporary setup. I read what it says at each step.

**Findings**

1. There was no way to accept a finding. A warning the user has decided to live with,
   such as a plugin edited on purpose, kept the bar icon on for good. On the owner's own
   machine the two warnings from round 1 would have made the icon permanent.
2. The bar count could be up to 30 minutes old after a fix, because the service only
   checked on a timer.
3. Between the shell starting and the first check finishing, the tooltip said "no
   problems found" although nothing had been checked yet.
4. The README did not say that seeing nothing on the bar after enabling is the healthy
   state, or that the report can be opened without the `~/.local/bin` link.
5. Two empty states read like counters ("0 declared commands checked", "0 git checkouts
   compared").

The rest held up: the empty and first-run reports, usage errors, `--help`, and the plugin
linting a setup it is itself installed in.

**Changed**

- **Ignore rules.** Every finding has a rule (`code:subject`), and `omalint --rules` shows
  it. A rule listed in the widget's `ignore` setting, or passed with `--ignore`, takes the
  finding out of the counts, the exit status and `--fix`. It stays visible on an
  `Ignored:` line and in the JSON. Version 0.3.0.
- The service checks again one second after `shell.json` changes. It compares content, so
  the host sending the same configuration again does nothing.
- Until the first check has finished, the tooltip says "first check pending" and the icon
  is dimmed.
- The two empty states are sentences now.
- README: a first-run note under Install, and an "Ignoring a finding" section.
- The images were regenerated, because one line of the sample report changed. I opened
  the new `docs/report.png` and `preview.png`.

**Left out on purpose**

- Dropping log errors from before the last plugin reload, so that an updated plugin
  clears without a shell restart. It would also hide errors that only happen now and
  then, and ignore rules cover the real need.
- A popup panel on the bar that lists the findings. It is the natural next step, but it
  is a new UI surface and not a low-risk change.
- Desktop notifications when a new problem appears. They turn into noise easily.
- Putting the command on PATH automatically. Omarchy runs no install hooks, so it stays
  one `ln -s` in the README.
- Tooltip hints for the click actions. Stock widgets do not carry them.

**Tests: 321, all passing.** New: ignore rules (46 tests), the pending state and the
re-check in the offscreen harness (the widget test now has 10 tests, and fails when
either behaviour is removed), and the two empty states. `omarchy plugin validate` passes
and the marketplace baseline still reports `passed`.

**Not verified:** 0.3.0 has not run inside the real bar. The re-check was exercised by
assigning a new configuration in the harness, not by a real `shell.json` write through
the shell. Two Sonnet subagents wrote the code, and Haiku subagents the text and a test
clean-up; I reviewed all of it. As in round 2, everything ran in a temporary HOME.

## Round 2: what changed

**The duplicate IPC handler warning is fixed.** For the installed 0.1.0 the shell logged:

```
Handler was registered but will not be used because another handler is registered for target io.github.davidgudovic.omalint
```

Cause: the Omarchy bar is created once per monitor (`Variants { model: Quickshell.screens }`
in the shell's `Bar.qml`), so every bar widget exists once per monitor, and 0.1.0
registered its IPC target inside the widget. This machine has two monitors, so the second
copy's registration was refused. It was not an id clash with the plugin loader: the
journal shows the same line for most stock and third-party widgets here, for the same
reason.

Fix: the plugin is now a service plus a widget, which is the layout the shell provides
for this. `Service.qml` is mounted once per shell and owns the check, its timers and the
single IPC handler. `Widget.qml` is a view that reads the service through
`bar.shell.serviceFor(...)`. As a side effect the check now runs once per shell instead of
once per monitor.

Evidence, from an offscreen Quickshell that mounts the plugin the way the shell does (one
service, two widgets, and the shell's own `Commons`, `Ui` and `PluginShellApi`):

- The 0.1.0 widget, two copies, logs
  `WARN scene: QML IpcHandler at @plugin/Widget.qml[57:3]: Handler was registered but will not be used because another handler is registered for target io.github.davidgudovic.omalint`,
  the same line at the same `[57:3]` as in the real journal.
- 0.2.0, two copies: no such line. `quickshell ipc show` lists the target once, with
  `report()` and `refresh()`, and `quickshell ipc call io.github.davidgudovic.omalint refresh`
  reaches the service (its run counter goes from 1 to 2).

This is now a regression test (`tests/test_widget.py`, 5 tests), and it was confirmed to
fail when the handler is put back into the widget.

**Not verified:** 0.2.0 has not run inside the real bar on the real monitors. The copy
installed in `~/.config/omarchy/plugins/` is still 0.1.0 and was not touched, so the
running shell keeps logging the warning until that copy is updated
(`omarchy plugin update io.github.davidgudovic.omalint`; its origin is this local
repository). After the update, `journalctl --user -b -t omarchy-shell | grep omalint`
should show no new "Handler was registered" line.

**README.** A "What you get" section explains the report and the bar icon in plain
language, with two images.

**Screenshots come from real output.** `docs/screenshots.sh` regenerates
`docs/report.png`, `docs/widget.png` and `preview.png` in a temporary HOME. The report is
the command's own colored output on the made-up setup in `docs/sample`, and the icon is
the real widget showing the count its own service computed (1 error and 4 warnings). The
earlier preview used simulated shell answers and a mock clock; both are gone. The report
image is a rendering of the captured text in Omarchy's default theme, not a photograph of
a terminal window. I opened all three images and checked them for clipping and
legibility.

**Also new.** `OMALINT_NO_LIVE=1` does the same as `--no-live`, so the widget's test and
the screenshot script never contact the running session. Both run with a temporary HOME
and a private runtime directory. Nothing in round 2 was run against the real
`~/.config/omarchy`; I only read the journal, `shell.json` and the installed copy's git
log to diagnose the warning. One early trial of mine, in a temporary HOME before this
switch existed, did ask the running shell for `ping` and `listPlugins` (both read-only).
That is how I found the switch was needed.

## What it is

A health check for Omarchy shell plugins and the bar setup. A stdlib-only Python command
(`bin/omalint`, package `omalint/`) runs six read-only checks and prints a grouped
OK / WARN / ERROR report with a plain-language fix for each finding. A background
service (`Service.qml`) runs the same checks once per shell, and a small bar widget
(`Widget.qml`) shows the count.

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

**Tests: 321, all passing** (`bash tests/run.sh`, about 8 seconds,
standard library only). Fixtures under `tests/fixtures/`:

- `stock/`: a miniature Omarchy install (built-in plugins, default Hyprland bindings)
- `healthy/`: a setup with nothing wrong, which must produce no warnings
- `broken/`: one problem per plugin or config entry (invalid manifest, missing fields,
  reserved id, id collision, missing entry point, missing dependency, bad `shell.json`
  references, key conflicts, missing imports)
- `fixable/`: only the problems `--fix` repairs
- `journal.txt`: a captured shell log
- `docs/sample/`: the made-up setup the screenshots show, with a test that it still
  produces exactly the problems in the pictures
- an offscreen Quickshell harness (`tests/harness/`) for the widget and its service,
  skipped where Quickshell or the Omarchy shell's files are missing

Each finding is asserted by code, subject and severity. Git and symlink cases are built
at run time in temporary directories, so the repository itself contains no symlinks and
no nested `.git`. The tests added for the review fixes were also run against the pre-fix
code, where every one that covers a fixed defect fails.

**Real machine, read-only (round 1, version 0.1.0).** Run against the real
`~/.config/omarchy` and `~/.config/hypr` (13 plugins). Output below. A snapshot taken
immediately before and after three runs (text, `--json`, `--fix --dry-run`) was
identical: the hash of `shell.json`, the names, sizes and modification times of
everything in both config directories, the `.git/index` of all 11 plugin checkouts, and
the absence of `__pycache__`. Round 2 did not repeat this run: by instruction, everything
in it used a temporary HOME.

**The `--fix` path** on a copy of the fixture: transcript below. The backup is
byte-identical to the original, the diff shows exactly the four removed entries, a
second run finds nothing to fix and makes no second backup, and `--dry-run` leaves the
file untouched.

**The widget and its service** are mounted by `tests/test_widget.py` in an offscreen
Quickshell (nothing appears on screen) using the shell's real `Commons` and `Ui`
components and the real `PluginShellApi` and `PluginBarApi` facades that third-party
plugins receive. With one service and two widgets it checks that the IPC target is
registered once, that the QML loads without errors, that the service ran the real command
and both widgets show its numbers, and that an IPC `refresh` sent from outside reaches the
service. The command that opens the report in a terminal is never run by a test; its
quoting was checked separately through a stand-in launcher with a path containing spaces
and an apostrophe.

**Marketplace rules.** `omarchy plugin validate .` exits 0. One `manifest.json`, at the
root, now declaring a service and a bar widget; its fields were checked by hand against
the marketplace's `validateManifest`, which I could not import to run. README has install
and removal sections; LICENSE is MIT. No symlinks. The
marketplace's `security-baseline-analysis.mjs`, run locally over the tracked files,
reports `outcome: passed`.

### Real output on this machine (round 1, version 0.1.0)

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

Left alone in round 1: the reviewer noted that with several monitors each bar's copy of
the widget ran its own check. Round 2's service removes that.

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

Checked again in round 2: `gh repo view DavidGudovic/omalint` still fails and no remote is
configured, so nothing was pushed.

To publish:

```bash
cd ~/projects/omalint
gh repo create DavidGudovic/omalint --public --source . --remote origin --push
gh repo view DavidGudovic/omalint --json visibility,url
```

## Known limitations

- **0.3.0 has never run inside the real bar.** The service and widget were verified in a
  separate offscreen Quickshell with the shell's real components, not in the running
  Omarchy shell. The owner's installed copy is 0.1.0.
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
- **The images are renders, not window screenshots.** They are produced offscreen from
  real output (see round 2) in the stock Tokyo Night theme. The line numbers and binding
  counts in them depend on the installed Omarchy version.

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
