#!/usr/bin/env bash
# Regenerates docs/report.png, docs/widget.png and preview.png from the real code:
# the CLI's own output on docs/sample, and the real Service.qml + Widget.qml
# mounted in an offscreen Quickshell. Nothing is drawn by hand and nothing touches
# your own configuration: everything runs with a temporary HOME.
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
omarchy=${OMARCHY_PATH:-/usr/share/omarchy}
python=/usr/bin/python3

die() {
  echo "screenshots.sh: $*" >&2
  exit 1
}

command -v quickshell >/dev/null || die "quickshell is not installed"
command -v script >/dev/null || die "script (util-linux) is not installed"
command -v timeout >/dev/null || die "timeout (coreutils) is not installed"
[[ -x $python ]] || die "$python is missing"
[[ -d $omarchy/shell/Commons && -d $omarchy/shell/Ui && -f $omarchy/shell/services/PluginShellApi.qml ]] ||
  die "no Omarchy shell found in $omarchy/shell (needs Commons, Ui and services/PluginShellApi.qml; set OMARCHY_PATH)"
[[ -f $omarchy/themes/tokyo-night/colors.toml ]] || die "the theme $omarchy/themes/tokyo-night/colors.toml is missing"

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# A home with only the sample setup and Omarchy's default theme.
home=$work/home
mkdir -p "$home/.config" "$home/.local/state/omarchy/current/theme" "$work/out"
cp -r "$repo/docs/sample/omarchy" "$home/.config/omarchy"
cp -r "$repo/docs/sample/hypr" "$home/.config/hypr"
cp "$omarchy/themes/tokyo-night/colors.toml" "$home/.local/state/omarchy/current/theme/colors.toml"

# The report as a terminal shows it: run on a pty, so the CLI colors its output.
# It exits 1 when it finds errors, which this sample does on purpose.
status=0
env -i HOME="$home" PATH=/usr/bin:/bin OMARCHY_PATH="$omarchy" LANG=C.UTF-8 TERM=xterm-256color COLUMNS=98 \
  OMALINT_BIN="$repo/bin/omalint" \
  script -qfec "$python -B \"\$OMALINT_BIN\" --no-live" /dev/null >"$work/report.ansi" || status=$?
((status <= 1)) || die "omalint itself failed (exit status $status)"
"$python" -B "$repo/docs/render/segments.py" <"$work/report.ansi" >"$work/report.json" ||
  die "could not read the closing line of omalint's report"

# What the shell would load: its own libraries and the plugin, copied.
qs=$work/qs
mkdir -p "$qs/services" "$qs/plugin"
cp -RL "$omarchy/shell/Commons" "$omarchy/shell/Ui" "$qs/"
cp "$omarchy/shell/services/PluginShellApi.qml" "$qs/services/"
cp "$repo/docs/render/shell.qml" "$qs/shell.qml"
cp "$work/report.json" "$qs/report.json"
cp -RL "$repo/Widget.qml" "$repo/Service.qml" "$repo/manifest.json" "$repo/bin" "$repo/omalint" "$qs/plugin/"

# Offscreen, with no access to the running session: no display, no Hyprland, no live checks,
# and a runtime directory of its own, so Quickshell leaves nothing in yours.
mkdir -m 700 "$work/run"
status=0
env -i HOME="$home" PATH=/usr/bin:/bin LANG=C.UTF-8 XDG_RUNTIME_DIR="$work/run" \
  QT_QPA_PLATFORM=offscreen QS_NO_RELOAD_POPUP=1 OMARCHY_PATH="$omarchy" OMALINT_NO_LIVE=1 RENDER_OUT="$work/out" \
  timeout 60 quickshell --path "$qs" >"$work/quickshell.log" 2>&1 || status=$?
grep -a -o 'RENDER.*' "$work/quickshell.log" || true
if ((status != 0)); then
  tail -n 30 "$work/quickshell.log" >&2
  die "quickshell exited with status $status"
fi

for name in report widget preview; do
  [[ -s $work/out/$name.png ]] || die "$name.png was not produced"
done
cp "$work/out/report.png" "$repo/docs/report.png"
cp "$work/out/widget.png" "$repo/docs/widget.png"
cp "$work/out/preview.png" "$repo/preview.png"

size() {
  "$python" -B -c 'import struct, sys; print("%dx%d" % struct.unpack(">II", open(sys.argv[1], "rb").read(24)[16:24]))' "$1"
}
echo "docs/report.png  $(size "$repo/docs/report.png")"
echo "docs/widget.png  $(size "$repo/docs/widget.png")"
echo "preview.png      $(size "$repo/preview.png")"
echo "The widget shows what the service reported: $(grep -a -o 'errors=.*' "$work/quickshell.log" | head -n 1)"
