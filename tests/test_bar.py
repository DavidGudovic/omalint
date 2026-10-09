import unittest

from helpers import Helpers, context, find, pairs, run_check, temp_context, write_shell_json

BROKEN = {
    ("bar.unknown-bar", "acme.neon-bar"): "warn",
    ("bar.unknown-section", "bar.layout.middle"): "warn",
    ("bar.unknown-widget", "acme.gone"): "warn",
    ("bar.entry-without-id", "bar.layout.center[2]"): "warn",
    ("bar.not-a-widget", "acme.service"): "warn",
    ("bar.unknown-widget", "acme.badjson"): "warn",
    ("bar.custom-module-missing", "gpu"): "warn",
    ("bar.unknown-module-type", "acme.good"): "warn",
    ("bar.duplicate-widget", "omarchy.tray"): "warn",
    ("bar.unknown-plugin", "acme.vanished"): "warn",
    ("bar.plugin-entry-invalid", "plugins[1]"): "warn",
}

FIXABLE = {
    ("bar.unknown-bar", "acme.neon-bar"): "warn",
    ("bar.unknown-widget", "acme.gone"): "warn",
    ("bar.entry-without-id", "bar.layout.center[1]"): "warn",
    ("bar.unknown-plugin", "acme.vanished"): "warn",
}


class BrokenFixtureTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.result = run_check("bar", context("broken"))

    def test_reports_exactly_the_expected_findings(self):
        self.assertFindings(self.result, BROKEN)

    def test_only_the_entry_without_an_id_is_fixable(self):
        fixable = {(f.code, f.subject) for f in self.result.findings if f.fixable}
        self.assertEqual(fixable, {("bar.entry-without-id", "bar.layout.center[2]")})

    def test_unknown_widget_is_not_fixable_while_a_manifest_is_unreadable(self):
        finding = find(self.result, "bar.unknown-widget", "acme.gone")
        self.assertFalse(finding.fixable)
        self.assertIn("acme.badjson", finding.fix)

    def test_duplicate_tray_is_reported_but_left_for_the_user_to_resolve(self):
        finding = find(self.result, "bar.duplicate-widget", "omarchy.tray")
        self.assertFalse(finding.fixable)
        self.assertIn("center[1], right[0]", finding.message)

    def test_widgets_that_allow_multiple_instances_are_not_duplicates(self):
        subjects = {f.subject for f in self.result.findings if f.code == "bar.duplicate-widget"}
        self.assertNotIn("omarchy.spacer", subjects)
        self.assertNotIn("omarchy.clock", subjects)


class FixableFixtureTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.result = run_check("bar", context("fixable"))

    def test_reports_exactly_the_expected_findings(self):
        self.assertFindings(self.result, FIXABLE)

    def test_every_finding_is_fixable(self):
        self.assertTrue(all(f.fixable for f in self.result.findings))


class HealthyFixtureTests(Helpers, unittest.TestCase):
    def test_no_findings(self):
        self.assertFindings(run_check("bar", context("healthy")), {})


class TempConfigTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.ctx = temp_context(self.tempdir())

    def test_syntax_error_in_shell_json_is_one_error(self):
        write_shell_json(self.ctx.config_dir, '{"version": 1,')
        self.assertFindings(run_check("bar", self.ctx), {("bar.shell-json-invalid", "shell.json"): "error"})

    def test_shell_json_without_version_one_is_an_error(self):
        write_shell_json(self.ctx.config_dir, {"bar": {"layout": {}}})
        self.assertFindings(run_check("bar", self.ctx), {("bar.shell-json-version", "shell.json"): "error"})

    def test_no_shell_json_gives_no_findings(self):
        self.assertFindings(run_check("bar", self.ctx), {})

    def test_clock_and_spacer_may_be_placed_several_times(self):
        layout = {"left": [{"id": "omarchy.clock"}, {"id": "omarchy.clock"}],
                  "right": [{"id": "omarchy.spacer"}, {"id": "omarchy.spacer"}, {"id": "omarchy.spacer"}]}
        write_shell_json(self.ctx.config_dir, {"version": 1, "bar": {"layout": layout}})
        self.assertFindings(run_check("bar", self.ctx), {})

    def layout(self, **sections):
        write_shell_json(self.ctx.config_dir, {"version": 1, "bar": {"layout": sections}})
        return run_check("bar", self.ctx)

    def test_plain_entries_without_an_id_are_fixable(self):
        result = self.layout(left=[None, 7, [], {"id": ""}, {"size": 4}])
        self.assertEqual([f.code for f in result.findings], ["bar.entry-without-id"] * 5)
        self.assertTrue(all(f.fixable for f in result.findings))

    def test_command_module_without_an_id_still_draws_and_is_left_alone(self):
        result = self.layout(left=[{"type": "command", "exec": "date"}, {"exec": "date"}])
        self.assertFindings(result, {})

    def test_unknown_id_in_the_reserved_namespace_is_never_fixable(self):
        write_shell_json(self.ctx.config_dir, {
            "version": 1,
            "bar": {"id": "omarchy.future-bar", "layout": {"left": [{"id": "omarchy.future-widget"}]}},
            "plugins": [{"id": "omarchy.future-service"}],
        })
        result = run_check("bar", self.ctx)
        self.assertEqual(pairs(result), {
            ("bar.unknown-bar", "omarchy.future-bar"),
            ("bar.unknown-widget", "omarchy.future-widget"),
            ("bar.unknown-plugin", "omarchy.future-service"),
        })
        self.assertFalse(any(f.fixable for f in result.findings))

    def test_numeric_id_is_read_the_way_the_shell_reads_it(self):
        result = self.layout(left=[{"id": 5}])
        self.assertEqual(pairs(result), {("bar.unknown-widget", "5")})

    def test_section_that_is_not_a_list_is_reported(self):
        result = self.layout(left="omarchy.clock")
        self.assertEqual(pairs(result), {("bar.section-not-list", "bar.layout.left")})

    def test_bar_that_is_not_an_object_does_not_crash(self):
        write_shell_json(self.ctx.config_dir, {"version": 1, "bar": [1, 2], "plugins": {"a": 1}})
        self.assertFindings(run_check("bar", self.ctx), {})


class WithoutBuiltinPluginsTests(Helpers, unittest.TestCase):
    def setUp(self):
        root = self.tempdir()
        self.empty_install = root / "install"
        self.empty_install.mkdir()
        self.ctx = temp_context(root, omarchy_path=self.empty_install)
        layout = {"left": [{"id": "omarchy.clock"}, {"id": "acme.unknown"}]}
        write_shell_json(self.ctx.config_dir, {"version": 1, "bar": {"layout": layout}})
        self.result = run_check("bar", self.ctx)

    def test_unverifiable_builtin_ids_are_not_reported(self):
        self.assertNotIn("omarchy.clock", {f.subject for f in self.result.findings})

    def test_other_unknown_ids_are_still_reported(self):
        self.assertEqual(pairs(self.result), {("bar.unknown-widget", "acme.unknown")})

    def test_a_note_says_builtins_were_not_verified(self):
        self.assertTrue(any("Built-in plugins not found" in note for note in self.result.notes))


if __name__ == "__main__":
    unittest.main()
