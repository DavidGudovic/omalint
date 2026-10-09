import json
import unittest

from helpers import FIXTURES, FakeRun, Helpers, context, find, run_check

from omalint import inventory
from omalint.checks import health
from omalint.model import Run

PLUGINS_DIR = "/home/user/.config/omarchy/plugins"
PLUGIN_IDS = ["acme.good", "acme.dup", "omarchy.hijack"]


class ParseJournalTests(unittest.TestCase):
    def setUp(self):
        text = (FIXTURES / "journal.txt").read_text(encoding="utf-8")
        self.problems = health.parse_journal(text, PLUGINS_DIR, PLUGIN_IDS)

    def messages(self, owner):
        return list(self.problems[owner])

    def test_only_plugins_with_real_problems_are_listed(self):
        self.assertEqual(set(self.problems), {"acme.good", "acme.dup", "acme.dup-two", "omarchy.hijack"})

    def test_repeated_error_is_one_message_counted_twice(self):
        (message,) = self.messages("acme.good")
        self.assertIn("TypeError", message)
        self.assertEqual(self.problems["acme.good"][message][0], 2)

    def test_plugin_folder_prefix_is_stripped(self):
        (message,) = self.messages("acme.good")
        self.assertTrue(message.startswith("Widget.qml["), message)

    def test_percent_encoded_file_names_are_decoded(self):
        (message,) = self.messages("acme.dup-two")
        self.assertIn("Gauge Dial.qml", message)

    def test_failure_naming_a_plugin_id_is_attributed_to_it(self):
        (message,) = self.messages("acme.dup")
        self.assertIn("Gauge unavailable", message)

    def test_unrelated_system_messages_are_not_attributed(self):
        text = " ".join(list(self.problems) + [m for owner in self.problems for m in self.problems[owner]])
        self.assertNotIn("StatusNotifierItem", text)
        self.assertNotIn("pam", text)


def ping_ok():
    return (("omarchy-shell", "shell", "ping"), Run("ok", 0, "ok\n"))


def listing(ids):
    # listPlugins prints a JSON list of objects that carry an "id".
    return (("omarchy-shell", "shell", "listPlugins"), Run("ok", 0, json.dumps([{"id": i} for i in ids])))


def live_context(*rules):
    fake = FakeRun(*rules)
    return context("broken", live=True, run=fake, shell_pids=lambda path: [1700]), fake


def loadable_ids():
    return sorted(inventory.build(context("broken")).loaded)


def journal_line(folder, message):
    plugins_dir = context("broken").plugins_dir
    return f"2026-10-09T09:12:01+02:00 omarchy omarchy-shell[1700]: WARN scene: file://{plugins_dir}/{folder}/{message}\n"


class CheckTests(Helpers, unittest.TestCase):
    def test_missing_omarchy_shell_is_one_warning(self):
        ctx, _ = live_context()
        self.assertFindings(run_check("health", ctx), {("health.no-omarchy-shell", "omarchy-shell"): "warn"})

    def test_shell_that_is_not_running_is_an_error(self):
        ctx, _ = live_context((("omarchy-shell", "shell", "ping"), Run("ok", 1, "", "omarchy-shell is not running")))
        self.assertFindings(run_check("health", ctx), {("health.shell-not-running", "omarchy-shell"): "error"})

    def test_shell_that_is_still_starting_is_not_an_error(self):
        ctx, _ = live_context((("omarchy-shell", "shell", "ping"), Run("ok", 1, "", "omarchy-shell is not ready")))
        result = run_check("health", ctx)
        self.assertFindings(result, {})
        self.assertTrue(result.skipped)

    def test_shell_that_times_out_is_an_error(self):
        ctx, _ = live_context((("omarchy-shell", "shell", "ping"), Run("timeout")))
        self.assertFindings(run_check("health", ctx), {("health.shell-unresponsive", "omarchy-shell"): "error"})

    def test_plugin_the_shell_has_not_picked_up_is_reported(self):
        ids = [i for i in loadable_ids() if i != "acme.keys"]
        ctx, _ = live_context(ping_ok(), listing(ids), (("journalctl",), Run("ok", 0, "")))
        self.assertFindings(run_check("health", ctx), {("health.not-discovered", "acme.keys"): "warn"})

    def test_plugin_that_logs_errors_is_reported(self):
        log = journal_line("acme.good", "Widget.qml[815:-1]: TypeError: boom")
        ctx, _ = live_context(ping_ok(), listing(loadable_ids()), (("journalctl",), Run("ok", 0, log)))
        result = run_check("health", ctx)
        self.assertFindings(result, {("health.log-errors", "acme.good"): "warn"})
        self.assertIn("TypeError", find(result, "health.log-errors", "acme.good").message)

    def test_journal_is_read_for_this_user_tag_and_process_only(self):
        ctx, fake = live_context(ping_ok(), listing(loadable_ids()), (("journalctl",), Run("ok", 0, "")))
        run_check("health", ctx)
        (argv,) = fake.calls_to("journalctl")
        self.assertIn("--user", argv)
        self.assertEqual(argv[argv.index("-t") + 1], "omarchy-shell")
        self.assertIn("_PID=1700", argv)

    def test_unreadable_journal_is_a_note_not_a_finding(self):
        ctx, _ = live_context(ping_ok(), listing(loadable_ids()), (("journalctl",), Run("missing")))
        result = run_check("health", ctx)
        self.assertFindings(result, {})
        self.assertTrue(any("journal" in note for note in result.notes))

    def test_not_live_run_checks_nothing_and_runs_nothing(self):
        fake = FakeRun(ping_ok())
        result = run_check("health", context("broken", live=False, run=fake))
        self.assertFindings(result, {})
        self.assertTrue(result.skipped)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
