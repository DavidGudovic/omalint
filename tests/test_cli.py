import json
import os
import shutil
import subprocess
import sys
import unittest

from helpers import (
    CLI, FIXTURES, ROOT, Helpers, cli, context, directory_args, fixture_args, good_manifest, snapshot, write_plugin,
)

from omalint import cli as command_line
from omalint.checks import bar

try:
    import pty
except ImportError:  # pragma: no cover
    pty = None

CHECK_IDS = ["manifests", "bar", "keys", "deps", "stale", "health"]
FINDING_KEYS = {"check", "code", "severity", "subject", "message", "fix", "path", "fixable"}


def report(*args):
    result = cli("--json", *args)
    return result, json.loads(result.stdout)


def on_a_tty(*args):
    """Run the CLI with its stdout attached to a terminal and return what it printed."""
    master, slave = pty.openpty()
    env = {k: v for k, v in os.environ.items() if k != "NO_COLOR"}
    process = subprocess.Popen(
        [sys.executable, "-B", str(CLI), *map(str, args)],
        stdin=subprocess.DEVNULL, stdout=slave, stderr=subprocess.DEVNULL, env=env,
    )
    os.close(slave)
    chunks = []
    while True:
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    os.close(master)
    process.wait(timeout=60)
    return b"".join(chunks).decode("utf-8", "replace")


class ExitStatusTests(unittest.TestCase):
    def test_healthy_setup_exits_zero_and_says_so(self):
        result = cli("--no-color", *fixture_args("healthy"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No problems found", result.stdout)

    def test_broken_setup_exits_one_and_points_at_fix(self):
        result = cli("--no-color", *fixture_args("broken"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR", result.stdout)
        self.assertIn("omalint --fix", result.stdout)

    def test_warnings_alone_exit_zero(self):
        self.assertEqual(cli("--no-color", *fixture_args("fixable")).returncode, 0)

    def test_strict_turns_warnings_into_exit_one(self):
        self.assertEqual(cli("--no-color", "--strict", *fixture_args("fixable")).returncode, 1)


class JsonReportTests(unittest.TestCase):
    def setUp(self):
        self.result, self.report = report(*fixture_args("broken"))

    def test_exits_one(self):
        self.assertEqual(self.result.returncode, 1)

    def test_top_level_fields(self):
        self.assertEqual(self.report["tool"], "omalint")
        self.assertTrue(self.report["version"])
        self.assertIs(self.report["ok"], False)

    def test_summary_counts(self):
        self.assertEqual(
            self.report["summary"],
            {"errors": 7, "warnings": 21, "notes": 2, "fixable": 1, "plugins": 13},
        )

    def test_checks_come_in_the_documented_order(self):
        self.assertEqual([c["id"] for c in self.report["checks"]], CHECK_IDS)

    def test_every_check_has_title_status_findings_and_notes(self):
        for check in self.report["checks"]:
            with self.subTest(check=check["id"]):
                self.assertTrue(check["title"])
                self.assertIn(check["status"], {"ok", "warn", "error", "skipped"})
                self.assertIsInstance(check["findings"], list)
                self.assertIsInstance(check["notes"], list)

    def test_health_is_skipped_for_a_fixture_run(self):
        health = self.report["checks"][-1]
        self.assertEqual((health["id"], health["status"]), ("health", "skipped"))

    def test_every_finding_has_the_documented_fields(self):
        findings = [f for check in self.report["checks"] for f in check["findings"]]
        self.assertEqual(len(findings), 30)
        for finding in findings:
            with self.subTest(finding=(finding["code"], finding["subject"])):
                self.assertEqual(set(finding), FINDING_KEYS)

    def test_healthy_setup_is_ok(self):
        result, healthy = report(*fixture_args("healthy"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(healthy["ok"], True)


class SelectingChecksTests(unittest.TestCase):
    def ids(self, *args):
        result, data = report(*args, *fixture_args("broken"))
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return [c["id"] for c in data["checks"]]

    def test_only_runs_just_that_check(self):
        self.assertEqual(self.ids("--only", "bar"), ["bar"])

    def test_skip_omits_the_listed_checks(self):
        self.assertEqual(self.ids("--skip", "keys,deps"), ["manifests", "bar", "stale", "health"])

    def test_unknown_check_name_is_a_usage_error_naming_the_valid_ones(self):
        result = cli("--only", "nonsense", *fixture_args("broken"))
        self.assertEqual(result.returncode, 2)
        for name in CHECK_IDS:
            with self.subTest(name=name):
                self.assertIn(name, result.stderr)


class HelpTests(unittest.TestCase):
    def test_version_prints_the_name_and_a_version(self):
        result = cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"omalint \d+\.\d+")

    def test_help_mentions_every_check(self):
        result = cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in CHECK_IDS:
            with self.subTest(name=name):
                self.assertIn(name, result.stdout)


    def test_help_names_the_backup_file_fix_really_writes(self):
        self.assertIn("shell.json.bak.omalint.<timestamp>", cli("--help").stdout)


class RobustnessTests(Helpers, unittest.TestCase):
    def test_crashed_check_is_an_error_and_the_others_still_run(self):
        original = bar.check
        self.addCleanup(setattr, bar, "check", original)
        bar.check = lambda ctx, inv: 1 / 0
        _, results = command_line.run_checks(context("healthy"), ["bar", "manifests"])
        self.assertFindings(results["bar"], {("omalint.check-crashed", "bar"): "error"})
        self.assertFindings(results["manifests"], {})

    def test_text_the_terminal_cannot_encode_is_printed_escaped(self):
        root = self.tempdir()
        escape = chr(92) + "ud800"
        manifest = json.dumps(good_manifest("PLACEHOLDER")).replace("PLACEHOLDER", "acme" + escape + "x")
        write_plugin(root / "omarchy", "acme.x", manifest)
        for mode in ("--no-color", "--json"):
            with self.subTest(mode=mode):
                result = cli(mode, *directory_args(root / "omarchy", root / "hypr"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn(escape, result.stdout)


class ColorTests(unittest.TestCase):
    def test_piped_output_has_no_escape_codes(self):
        self.assertNotIn("\x1b", cli(*fixture_args("broken")).stdout)

    def test_no_color_flag_output_has_no_escape_codes(self):
        self.assertNotIn("\x1b", cli("--no-color", *fixture_args("broken")).stdout)

    @unittest.skipIf(pty is None, "no pseudo-terminals on this platform")
    def test_terminal_output_is_colored(self):
        self.assertIn("\x1b[", on_a_tty(*fixture_args("broken")))

    @unittest.skipIf(pty is None, "no pseudo-terminals on this platform")
    def test_no_color_flag_wins_on_a_terminal(self):
        self.assertNotIn("\x1b", on_a_tty("--no-color", *fixture_args("broken")))


class BrokenPipeTests(unittest.TestCase):
    def test_reader_that_goes_away_gets_no_traceback_and_the_real_exit_status(self):
        process = subprocess.Popen(
            [sys.executable, "-B", str(CLI), "--no-color", *fixture_args("broken")],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        process.stdout.close()
        errors = process.stderr.read().decode("utf-8", "replace")
        process.stderr.close()
        self.assertEqual(process.wait(timeout=60), 1)
        self.assertEqual(errors, "")


class ReadOnlyTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.root = self.tempdir()
        shutil.copytree(FIXTURES / "broken", self.root / "broken")
        shutil.copytree(FIXTURES / "stock", self.root / "stock")
        self.args = directory_args(self.root / "broken" / "omarchy", self.root / "broken" / "hypr", self.root / "stock")
        self.before = snapshot(self.root)

    def test_text_report_changes_nothing(self):
        cli("--no-color", *self.args)
        self.assertEqual(snapshot(self.root), self.before)

    def test_json_report_changes_nothing(self):
        cli("--json", *self.args)
        self.assertEqual(snapshot(self.root), self.before)


class WithoutTheSessionTests(Helpers, unittest.TestCase):
    """Both ways to keep a default-directory run away from the running session."""

    def health_status(self, *args, **env):
        home = self.tempdir()
        shutil.copytree(FIXTURES / "fixable" / "omarchy", home / ".config" / "omarchy")
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "OMARCHY_PATH": str(FIXTURES / "stock"), **env}
        result = subprocess.run(
            [sys.executable, "-B", str(CLI), "--json", *args],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return {check["id"]: check["status"] for check in json.loads(result.stdout)["checks"]}["health"]

    def test_the_environment_variable_skips_the_live_checks(self):
        self.assertEqual(self.health_status(OMALINT_NO_LIVE="1"), "skipped")

    def test_the_flag_skips_the_live_checks(self):
        self.assertEqual(self.health_status("--no-live"), "skipped")


class EntryScriptTests(Helpers, unittest.TestCase):
    def test_running_without_dash_b_leaves_no_bytecode(self):
        root = self.tempdir()
        ignore = shutil.ignore_patterns("__pycache__")
        shutil.copytree(ROOT / "bin", root / "bin", ignore=ignore)
        shutil.copytree(ROOT / "omalint", root / "omalint", ignore=ignore)
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        result = subprocess.run(
            [sys.executable, str(root / "bin" / "omalint"), "--no-color", *fixture_args("healthy")],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        leftovers = [dirpath for dirpath, dirnames, _ in os.walk(root) if "__pycache__" in dirnames]
        self.assertEqual(leftovers, [])

    def test_works_through_a_symlink(self):
        link = self.tempdir() / "omalint"
        os.symlink(CLI, link)
        result = subprocess.run(
            [sys.executable, "-B", str(link), "--version"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("omalint", result.stdout)


if __name__ == "__main__":
    unittest.main()
