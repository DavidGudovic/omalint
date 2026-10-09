import copy
import json
import os
import re
import shutil
import stat
import unittest

from helpers import FIXTURES, Helpers, cli, directory_args, snapshot, temp_context

from omalint import cli as command_line
from omalint import fixes
from omalint.model import Finding

BACKUP = re.compile(r"^shell\.json\.bak\.omalint\.\d+$")


def removal(**action):
    return Finding("bar", "bar.test", "warn", "x", "message", action=action or None)


class PlanTests(unittest.TestCase):
    def config(self):
        return {
            "bar": {"id": "acme.bar", "layout": {"right": [{"id": f"w{i}"} for i in range(6)]}},
            "plugins": [{"id": f"p{i}"} for i in range(3)],
        }

    def test_several_indices_are_removed_from_one_list(self):
        action = {"op": "remove-layout", "spots": [["right", 0], ["right", 2], ["right", 4]]}
        new, _ = fixes.plan(self.config(), [removal(**action)])
        self.assertEqual([e["id"] for e in new["bar"]["layout"]["right"]], ["w1", "w3", "w5"])

    def test_spots_from_separate_findings_are_combined(self):
        findings = [
            removal(op="remove-layout", spots=[["right", 1]]),
            removal(op="remove-layout", spots=[["right", 3]]),
        ]
        new, fixed = fixes.plan(self.config(), findings)
        self.assertEqual([e["id"] for e in new["bar"]["layout"]["right"]], ["w0", "w2", "w4", "w5"])
        self.assertEqual(len(fixed), 2)

    def test_input_config_is_not_modified(self):
        config = self.config()
        before = copy.deepcopy(config)
        fixes.plan(config, [removal(op="remove-layout", spots=[["right", 0]]), removal(op="remove-bar-id")])
        self.assertEqual(config, before)

    def test_plugin_rows_are_removed_by_index(self):
        findings = [removal(op="remove-plugin", index=0), removal(op="remove-plugin", index=2)]
        new, _ = fixes.plan(self.config(), findings)
        self.assertEqual(new["plugins"], [{"id": "p1"}])

    def test_bar_id_is_removed(self):
        new, _ = fixes.plan(self.config(), [removal(op="remove-bar-id")])
        self.assertNotIn("id", new["bar"])

    def test_findings_without_an_action_are_skipped(self):
        new, fixed = fixes.plan(self.config(), [removal()])
        self.assertEqual(new, self.config())
        self.assertEqual(fixed, [])


class RenderTests(unittest.TestCase):
    def test_indents_by_two_spaces(self):
        self.assertEqual(fixes.render({"a": {"b": 1}}), '{\n  "a": {\n    "b": 1\n  }\n}\n')

    def test_ends_with_exactly_one_newline(self):
        text = fixes.render({"a": 1})
        self.assertTrue(text.endswith("}\n"))
        self.assertFalse(text.endswith("\n\n"))

    def test_non_ascii_characters_stay_literal(self):
        text = fixes.render({"format": "HH\n—\nmm"})
        self.assertIn("—", text)
        self.assertNotIn("\\u2014", text)


class ApplyTests(Helpers, unittest.TestCase):
    def setUp(self):
        root = self.tempdir()
        self.install = root / "install"
        self.install.mkdir()
        self.ctx = temp_context(root, omarchy_path=self.install)
        self.ctx.config_dir.mkdir()
        self.target = self.ctx.config_dir / "shell.json"
        self.target.write_text("old\n", encoding="utf-8")

    def names(self):
        return sorted(os.listdir(self.ctx.config_dir))

    def test_replaces_the_content_and_returns_a_backup_of_the_old_file(self):
        backup = fixes.apply(self.ctx, self.target, "old\n", "new\n")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(backup.read_text(encoding="utf-8"), "old\n")
        self.assertRegex(backup.name, BACKUP)

    def test_refuses_a_file_inside_the_omarchy_install(self):
        stock = self.install / "shell.json"
        stock.write_text("old\n", encoding="utf-8")
        with self.assertRaises(fixes.FixError):
            fixes.apply(self.ctx, stock, "old\n", "new\n")
        self.assertEqual(stock.read_text(encoding="utf-8"), "old\n")
        self.assertEqual(os.listdir(self.install), ["shell.json"])

    def test_refuses_when_the_file_changed_since_it_was_read(self):
        with self.assertRaises(fixes.FixError):
            fixes.apply(self.ctx, self.target, "something else\n", "new\n")
        self.assertEqual(self.target.read_text(encoding="utf-8"), "old\n")

    def test_creates_no_backup_when_it_refuses(self):
        with self.assertRaises(fixes.FixError):
            fixes.apply(self.ctx, self.target, "something else\n", "new\n")
        self.assertEqual(self.names(), ["shell.json"])

    def test_preserves_a_private_file_mode(self):
        self.target.chmod(0o600)
        fixes.apply(self.ctx, self.target, "old\n", "new\n")
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)

    def test_preserves_a_group_readable_file_mode(self):
        self.target.chmod(0o640)
        fixes.apply(self.ctx, self.target, "old\n", "new\n")
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)

    def test_leaves_only_the_file_and_its_backup(self):
        backup = fixes.apply(self.ctx, self.target, "old\n", "new\n")
        self.assertEqual(self.names(), sorted(["shell.json", backup.name]))

    def test_writes_through_a_symlink_and_keeps_the_link(self):
        real = self.ctx.config_dir / "dotfiles-shell.json"
        self.target.rename(real)
        os.symlink(real, self.target)
        backup = fixes.apply(self.ctx, self.target, "old\n", "new\n")
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(real.read_text(encoding="utf-8"), "new\n")
        self.assertEqual(backup.parent, real.parent)

    def test_refuses_a_file_that_is_not_utf8(self):
        self.target.write_bytes(b'{"a": "\xff"}\n')
        with self.assertRaises(fixes.FixError):
            fixes.read(self.target)

    def test_read_keeps_windows_line_endings_as_they_are(self):
        self.target.write_bytes(b"a\r\nb\r\n")
        self.assertEqual(fixes.read(self.target), "a\r\nb\r\n")


class StaleFindingsTests(Helpers, unittest.TestCase):
    def test_fix_refuses_when_the_file_no_longer_matches_what_was_checked(self):
        root = self.tempdir()
        shutil.copytree(FIXTURES / "fixable", root / "fixable")
        ctx = temp_context(root / "fixable")
        inv, results = command_line.run_checks(ctx, ["bar"])
        changed = json.loads(ctx.shell_json.read_bytes())
        changed["bar"]["position"] = "bottom"
        ctx.shell_json.write_text(json.dumps(changed, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(fixes.FixError):
            command_line._fix(ctx, inv, results, dry_run=False, color=False)
        self.assertEqual(json.loads(ctx.shell_json.read_text(encoding="utf-8")), changed)
        self.assertEqual([p.name for p in ctx.config_dir.iterdir() if ".bak." in p.name], [])


ORIGINAL = (FIXTURES / "fixable" / "omarchy" / "shell.json").read_bytes()


class CliFixTestCase(Helpers, unittest.TestCase):
    def setUp(self):
        root = self.tempdir()
        shutil.copytree(FIXTURES / "fixable", root / "fixable")
        self.config_dir = root / "fixable" / "omarchy"
        self.shell_json = self.config_dir / "shell.json"
        self.args = directory_args(self.config_dir, root / "fixable" / "hypr")

    def backups(self):
        return sorted(p.name for p in self.config_dir.iterdir() if p.name.startswith("shell.json.bak"))

    def config(self):
        return json.loads(self.shell_json.read_text(encoding="utf-8"))


class DryRunTests(CliFixTestCase):
    def setUp(self):
        super().setUp()
        self.before = snapshot(self.config_dir)
        self.result = cli("--fix", "--dry-run", "--no-color", *self.args)

    def test_exits_zero(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_prints_a_diff_removing_the_dead_widget(self):
        lines = self.result.stdout.splitlines()
        self.assertTrue(any(line.startswith("-") and '"acme.gone"' in line for line in lines))

    def test_says_it_was_a_dry_run(self):
        self.assertIn("Dry run", self.result.stdout)

    def test_writes_nothing(self):
        self.assertEqual(self.shell_json.read_bytes(), ORIGINAL)
        self.assertEqual(self.backups(), [])
        self.assertEqual(snapshot(self.config_dir), self.before)


class FixTests(CliFixTestCase):
    def setUp(self):
        super().setUp()
        self.result = cli("--fix", "--no-color", *self.args)

    def test_exits_zero(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)

    def test_keeps_exactly_one_byte_identical_backup(self):
        (name,) = self.backups()
        self.assertRegex(name, BACKUP)
        self.assertEqual((self.config_dir / name).read_bytes(), ORIGINAL)

    def test_prints_the_diff_the_backup_and_how_to_undo(self):
        out = self.result.stdout
        self.assertIn("@@", out)
        self.assertTrue(any(line.startswith("-") and '"acme.gone"' in line for line in out.splitlines()))
        self.assertIn("Backup saved", out)
        self.assertIn("To undo", out)

    def test_bar_loses_its_unknown_bar_id(self):
        self.assertNotIn("id", self.config()["bar"])

    def test_left_loses_the_unknown_widget(self):
        self.assertEqual(self.config()["bar"]["layout"]["left"], [{"id": "omarchy.workspaces"}])

    def test_center_loses_the_entry_without_an_id(self):
        center = self.config()["bar"]["layout"]["center"]
        self.assertEqual(center, [{"id": "omarchy.clock", "verticalFormat": "HH\n—\nmm"}])

    def test_right_has_nothing_dead_and_is_untouched(self):
        right = self.config()["bar"]["layout"]["right"]
        self.assertEqual(right, [
            {"id": "omarchy.tray", "pinned": [], "hidden": []},
            {"id": "acme.good"},
            {"id": "omarchy.audio"},
        ])

    def test_nothing_is_left_to_report(self):
        self.assertIn("No problems found", self.result.stdout)

    def test_plugins_lose_the_vanished_one(self):
        self.assertEqual(self.config()["plugins"], [{"id": "omarchy.emojis"}])

    def test_unrelated_settings_are_untouched(self):
        original = json.loads(ORIGINAL.decode("utf-8"))
        self.assertEqual(self.config()["idle"], original["idle"])

    def test_non_ascii_text_is_written_literally(self):
        text = self.shell_json.read_text(encoding="utf-8")
        self.assertIn("—", text)
        self.assertNotIn("\\u2014", text)


class SecondFixTests(CliFixTestCase):
    def setUp(self):
        super().setUp()
        cli("--fix", "--no-color", *self.args)
        self.fixed = self.shell_json.read_bytes()
        self.result = cli("--fix", "--no-color", *self.args)

    def test_says_there_is_nothing_left_to_fix(self):
        self.assertEqual(self.result.returncode, 0, self.result.stderr)
        self.assertIn("Nothing here can be fixed automatically", self.result.stdout)

    def test_makes_no_second_backup(self):
        self.assertEqual(len(self.backups()), 1)

    def test_leaves_shell_json_unchanged(self):
        self.assertEqual(self.shell_json.read_bytes(), self.fixed)


class UsageTests(CliFixTestCase):
    def test_fix_and_json_together_are_a_usage_error(self):
        result = cli("--fix", "--json", *self.args)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.shell_json.read_bytes(), ORIGINAL)
        self.assertEqual(self.backups(), [])

    def test_dry_run_without_fix_is_a_usage_error(self):
        result = cli("--dry-run", *self.args)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--fix", result.stderr)
        self.assertEqual(self.backups(), [])


class FixOnBrokenFixtureTests(Helpers, unittest.TestCase):
    def setUp(self):
        root = self.tempdir()
        shutil.copytree(FIXTURES / "broken", root / "broken")
        shutil.copytree(FIXTURES / "stock", root / "stock")
        self.shell_json = root / "broken" / "omarchy" / "shell.json"
        self.original = json.loads(self.shell_json.read_text(encoding="utf-8"))
        args = directory_args(root / "broken" / "omarchy", root / "broken" / "hypr", root / "stock")
        self.result = cli("--fix", "--no-color", *args)

    def fixed(self):
        return json.loads(self.shell_json.read_text(encoding="utf-8"))

    def test_reports_one_fix(self):
        self.assertIn("Fixing 1 problem ", self.result.stdout)

    def test_removes_only_the_entry_without_an_id(self):
        expected = copy.deepcopy(self.original)
        del expected["bar"]["layout"]["center"][2]
        self.assertEqual(self.fixed(), expected)

    def test_leaves_the_unfixable_widget_in_the_file(self):
        self.assertIn({"id": "acme.gone"}, self.fixed()["bar"]["layout"]["left"])

    def test_leaves_both_copies_of_the_duplicated_tray(self):
        layout = self.fixed()["bar"]["layout"]
        self.assertIn({"id": "omarchy.tray"}, layout["center"])
        self.assertIn({"id": "omarchy.tray", "pinned": []}, layout["right"])

    def test_still_exits_one_because_errors_remain(self):
        self.assertEqual(self.result.returncode, 1)


if __name__ == "__main__":
    unittest.main()
