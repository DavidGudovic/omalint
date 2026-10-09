"""The bar widget and its service, mounted the way the Omarchy shell mounts them.

The shell draws one bar per monitor, so a bar widget exists once per monitor, while
the plugin's service exists once. tests/harness/shell.qml does the same in an offscreen
Quickshell: one service, two widgets, and the shell's own Commons, Ui and
PluginShellApi copied from /usr/share/omarchy/shell. Everything runs in a temporary
home, from a temporary copy of the plugin, with no Wayland or Hyprland in reach.
"""

import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from helpers import FIXTURES, ROOT

SHELL = Path("/usr/share/omarchy/shell")
PLUGIN_ID = "io.github.davidgudovic.omalint"
QUICKSHELL = shutil.which("quickshell")
NEEDED = (SHELL / "Commons", SHELL / "Ui", SHELL / "services" / "PluginShellApi.qml")
AVAILABLE = bool(QUICKSHELL and all(path.exists() for path in NEEDED))

ANSI = re.compile(r"\x1b\[[0-9;]*m")
FIRST_RUN = re.compile(
    r"HARNESS first-run errors=(?P<errors>\d+) warnings=(?P<warnings>\d+) failure=(?P<failure>.*)"
    r" runs=(?P<runs>\d+) interval=(?P<interval>\d+)"
    r" widgetA=(?P<a>\d+,\d+,\d+\|[^|]*\|\w+) widgetB=(?P<b>\d+,\d+,\d+\|[^|]*\|\w+)$"
)
SECOND_RUN = re.compile(r"HARNESS second-run runs=2 afterMs=(?P<after>\d+)$")
# The service starts its own check 10 s after it is created; a second run sooner than that was asked for.
STARTUP_TIMER_MS = 10000
QML_ERRORS = ("typeerror", "referenceerror", "is not a type", "failed to load", "unable to assign")


def build_harness(base):
    """The shell directory the harness runs from, and a home holding the fixable fixture."""
    harness = base / "harness"
    plugin = harness / "plugin"
    (harness / "services").mkdir(parents=True)
    plugin.mkdir()
    shutil.copytree(SHELL / "Commons", harness / "Commons")
    shutil.copytree(SHELL / "Ui", harness / "Ui")
    shutil.copy(SHELL / "services" / "PluginShellApi.qml", harness / "services" / "PluginShellApi.qml")
    shutil.copy(ROOT / "tests" / "harness" / "shell.qml", harness / "shell.qml")
    for name in ("Widget.qml", "Service.qml", "manifest.json"):
        shutil.copy(ROOT / name, plugin / name)
    ignore = shutil.ignore_patterns("__pycache__")
    shutil.copytree(ROOT / "bin", plugin / "bin", ignore=ignore)
    shutil.copytree(ROOT / "omalint", plugin / "omalint", ignore=ignore)

    home = base / "home"
    (home / ".config").mkdir(parents=True)
    shutil.copytree(FIXTURES / "fixable" / "omarchy", home / ".config" / "omarchy")
    # Quickshell keeps a directory per instance here; a private one leaves none behind.
    (base / "run").mkdir(mode=0o700)
    return harness, home


def environment(home):
    # Built from nothing, so that nothing of the user's session leaks in: no Wayland or
    # Hyprland, and OMALINT_NO_LIVE keeps the check away from the running shell.
    return {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "QT_QPA_PLATFORM": "offscreen",
        "QS_NO_RELOAD_POPUP": "1",
        "OMARCHY_PATH": str(FIXTURES / "stock"),
        "OMALINT_NO_LIVE": "1",
        "XDG_RUNTIME_DIR": str(home.parent / "run"),
    }


@unittest.skipUnless(AVAILABLE, "needs quickshell and the Omarchy shell's Commons, Ui and PluginShellApi.qml")
class WidgetAndServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        harness, home = build_harness(Path(temp.name))
        env = environment(home)
        log = Path(temp.name) / "quickshell.log"
        cls.ipc = None
        with open(log, "wb") as stream:
            process = subprocess.Popen(
                [QUICKSHELL, "-p", str(harness)],
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, env=env,
                start_new_session=True,
            )
        try:
            cls.wait_for(process, log, "HARNESS ready", seconds=30)
            if "HARNESS ready" in cls.read(log):
                # Never `report`: it would open a terminal on the desktop.
                cls.ipc = subprocess.run(
                    [QUICKSHELL, "ipc", "-p", str(harness), "call", PLUGIN_ID, "refresh"],
                    capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, timeout=15,
                )
                cls.wait_for(process, log, "HARNESS second-run", seconds=30)
            cls.wait_for_exit(process)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        cls.output = cls.read(log)
        cls.lines = cls.output.splitlines()

    @staticmethod
    def read(log):
        return ANSI.sub("", log.read_text(encoding="utf-8", errors="replace"))

    @classmethod
    def wait_for(cls, process, log, marker, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end and process.poll() is None and marker not in cls.read(log):
            time.sleep(0.1)

    @staticmethod
    def wait_for_exit(process, seconds=30):
        try:
            process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            pass

    def line(self, pattern):
        for text in self.lines:
            match = pattern.search(text)
            if match:
                return match
        self.fail(f"no line matches {pattern.pattern!r} in the Quickshell output:\n{self.output}")

    def test_the_second_widget_does_not_register_the_ipc_target_again(self):
        duplicates = [text for text in self.lines if "Handler was registered but will not be used" in text]
        self.assertEqual(duplicates, [])

    def test_the_qml_loads_without_errors(self):
        errors = [text for text in self.lines if any(word in text.lower() for word in QML_ERRORS)]
        self.assertEqual(errors, [])

    def test_the_service_ran_the_check_once_and_took_its_settings_from_the_bar_entry(self):
        run = self.line(FIRST_RUN)
        self.assertEqual(
            (run["errors"], run["warnings"], run["failure"], run["runs"], run["interval"]),
            ("0", "4", "", "1", "120"),
        )

    def test_both_widgets_show_the_services_numbers(self):
        run = self.line(FIRST_RUN)
        self.assertEqual(run["a"], "0,4,4|OmaLint: 4 warnings|true")
        self.assertEqual(run["b"], run["a"])

    # Sent from outside, the way `omarchy-shell io.github.davidgudovic.omalint refresh` does.
    def test_an_ipc_refresh_reaches_the_service(self):
        self.assertIsNotNone(self.ipc, "the harness never became ready:\n" + self.output)
        self.assertEqual(self.ipc.returncode, 0, self.ipc.stderr)
        self.assertEqual(self.ipc.stdout.strip(), "", "the ipc call was refused: " + self.ipc.stdout)
        later = self.line(SECOND_RUN)
        self.assertLess(int(later["after"]), STARTUP_TIMER_MS - 1000, "the run came from the startup timer")


if __name__ == "__main__":
    unittest.main()
