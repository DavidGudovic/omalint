import json
import shutil
import unittest

from helpers import FIXTURES, FakeRun, Helpers, context, find, pairs, run_check, temp_context

from omalint import lua
from omalint.checks import keys
from omalint.model import Run


class NormalizeTests(unittest.TestCase):
    def test_case_and_spacing_do_not_matter(self):
        self.assertEqual(keys.normalize("super+shift+a"), "SUPER + SHIFT + A")
        self.assertEqual(keys.normalize("super+shift+a"), keys.normalize("SUPER + SHIFT + A"))

    def test_modifier_order_is_canonical(self):
        self.assertEqual(keys.normalize("SHIFT + SUPER + A"), keys.normalize("SUPER + SHIFT + A"))

    def test_control_is_ctrl(self):
        self.assertEqual(keys.normalize("CONTROL + A"), "CTRL + A")

    def test_win_is_super(self):
        self.assertEqual(keys.normalize("WIN + A"), "SUPER + A")

    def test_keycode_is_kept_as_the_key(self):
        self.assertEqual(keys.normalize("SUPER + code:38"), "SUPER + CODE:38")


class PluginReferenceTests(unittest.TestCase):
    def test_toggle_names_the_plugin(self):
        self.assertEqual(keys.plugin_reference("omarchy-shell shell toggle acme.x"), "acme.x")

    def test_quiet_flag_and_quoted_json_argument(self):
        self.assertEqual(keys.plugin_reference("omarchy-shell -q shell summon acme.x '{}'"), "acme.x")

    def test_spaced_form_of_the_command(self):
        self.assertEqual(keys.plugin_reference("omarchy shell shell toggle acme.x"), "acme.x")

    def test_other_ipc_target_is_not_a_plugin(self):
        self.assertEqual(keys.plugin_reference("omarchy-shell notifications dismissOne"), "")

    def test_unrelated_command_is_not_a_plugin(self):
        self.assertEqual(keys.plugin_reference("firefox"), "")


class ReadmeSuggestionTests(unittest.TestCase):
    def test_lua_and_conf_examples_are_both_read(self):
        folder = FIXTURES / "broken" / "omarchy" / "plugins" / "acme.keys"
        self.assertEqual(keys.readme_suggestions(folder), ["SUPER + F", "SUPER + SHIFT + K"])


class LuaScanTests(unittest.TestCase):
    def test_a_plain_call_is_found(self):
        (call,) = lua.scan('o.bind("A", "x", "y")')
        self.assertEqual((call.name, call.args, call.line), ("o.bind", ['"A"', '"x"', '"y"'], 1))

    def test_line_comment_hides_a_call(self):
        calls = lua.scan('-- o.bind("A", "x", "y")\no.bind("B", "x", "y")')
        self.assertEqual([c.line for c in calls], [2])

    def test_block_comment_hides_a_call(self):
        calls = lua.scan('--[[ o.bind("A", "x", "y")\n]]\no.bind("B", "x", "y")')
        self.assertEqual([c.line for c in calls], [3])

    def test_string_literal_hides_a_call(self):
        calls = lua.scan('local s = "o.bind(\'A\', \'x\', \'y\')"\no.bind("B", "x", "y")')
        self.assertEqual([c.line for c in calls], [2])

    def test_function_definition_is_not_a_call(self):
        self.assertEqual(lua.scan("function o.bind(keys, description) end"), [])

    def test_call_inside_an_event_handler_is_deferred(self):
        calls = lua.scan('o.bind("A", "x", "y")\nhl.on("x", function()\n  o.bind("B", "x", "y")\nend)')
        self.assertEqual([c.deferred for c in calls], [False, True])

    def test_if_branch_carries_its_condition(self):
        calls = lua.scan('if cond then\n  o.bind("A", "x", "y")\nend')
        self.assertEqual(calls[0].conditions, ["cond"])

    def test_else_branch_has_an_empty_condition(self):
        calls = lua.scan('if cond then\n  o.bind("A", "x", "y")\nelse\n  o.bind("B", "x", "y")\nend\no.bind("C", "x", "y")')
        self.assertEqual([c.conditions for c in calls], [["cond"], [""], []])

    def test_require_is_a_call_with_the_module_name(self):
        (call,) = lua.scan('require("a.b")')
        self.assertEqual((call.name, call.args), ("require", ["a.b"]))

    def test_require_optional_module_is_a_require_call(self):
        (call,) = lua.scan('require_optional.module("a.b")')
        self.assertEqual((call.name, call.args), ("require", ["a.b"]))


class StringValueTests(unittest.TestCase):
    def test_quoted_strings_have_a_value(self):
        self.assertEqual(lua.string_value('"abc"'), "abc")
        self.assertEqual(lua.string_value("'abc'"), "abc")

    def test_concatenation_has_no_value(self):
        self.assertIsNone(lua.string_value('"a" .. b'))

    def test_nil_has_no_value(self):
        self.assertIsNone(lua.string_value("nil"))


class BrokenFixtureTests(Helpers, unittest.TestCase):
    def setUp(self):
        self.ctx = context("broken")
        self.result = run_check("keys", self.ctx)

    def test_reports_exactly_the_expected_findings(self):
        self.assertFindings(self.result, {
            ("keys.conflict", "SUPER + F"): "warn",
            ("keys.conflict", "SUPER + G"): "warn",
            ("keys.missing-plugin", "SUPER + Z"): "warn",
            ("keys.disabled-plugin", "SUPER + Y"): "warn",
            ("keys.suggestion-taken", "SUPER + F"): "info",
        })

    def test_default_binding_conflict_names_both_actions_and_suggests_unbind(self):
        finding = find(self.result, "keys.conflict", "SUPER + F")
        self.assertIn("Full screen", finding.message)
        self.assertIn("File manager", finding.message)
        self.assertIn("hl.unbind", finding.fix)

    def test_missing_plugin_message_names_the_plugin(self):
        self.assertIn("acme.gone", find(self.result, "keys.missing-plugin", "SUPER + Z").message)

    def test_disabled_plugin_message_names_the_plugin(self):
        self.assertIn("acme.disabled", find(self.result, "keys.disabled-plugin", "SUPER + Y").message)

    def test_keys_that_are_fine_are_not_reported(self):
        reported = {f.subject for f in self.result.findings}
        for combo in ("SUPER + X", "SUPER + H", "ALT + TAB", "F9", "SUPER + U", "RETURN", "SUPER + V"):
            with self.subTest(combo=combo):
                self.assertNotIn(combo, reported)


class EffectiveBindingTests(unittest.TestCase):
    def setUp(self):
        self.binds, self.files = keys.collect(context("broken"))

    def labels(self, combo):
        return [b.label for b in self.binds if b.combo == combo]

    def test_unbound_then_rebound_key_has_only_the_new_binding(self):
        self.assertEqual(self.labels("SUPER + X"), ["Terminal"])

    def test_press_and_release_are_separate_bindings(self):
        self.assertEqual({b.release for b in self.binds if b.combo == "SUPER + H"}, {False, True})

    def test_stock_double_binding_is_read_from_the_default_config(self):
        stock = [b for b in self.binds if b.combo == "ALT + TAB"]
        self.assertEqual(len(stock), 2)
        self.assertTrue(all(b.stock for b in stock))

    def test_binding_inside_an_event_handler_is_not_read(self):
        self.assertEqual(self.labels("RETURN"), [])

    def test_binding_under_a_false_condition_is_not_read(self):
        self.assertEqual(self.labels("SUPER + V"), [])


class HealthyFixtureTests(Helpers, unittest.TestCase):
    def test_no_findings(self):
        self.assertFindings(run_check("keys", context("healthy")), {})


class TempConfigTests(Helpers, unittest.TestCase):
    def test_turning_off_default_bindings_removes_the_conflict(self):
        root = self.tempdir()
        shutil.copytree(FIXTURES / "broken" / "hypr", root / "hypr")
        main = root / "hypr" / "hyprland.lua"
        main.write_text("omarchy_default_bindings = false\n" + main.read_text(encoding="utf-8"), encoding="utf-8")
        result = run_check("keys", context("broken", hypr_dir=root / "hypr"))
        self.assertNotIn(("keys.conflict", "SUPER + F"), pairs(result))
        self.assertIn(("keys.conflict", "SUPER + G"), pairs(result))

    def test_hypr_dir_without_lua_files_is_skipped(self):
        root = self.tempdir()
        (root / "hypr").mkdir()
        result = run_check("keys", temp_context(root))
        self.assertFindings(result, {})
        self.assertTrue(result.skipped)


def live_bind(modmask, key, description="", release=False):
    return {"modmask": modmask, "key": key, "release": release, "mouse": False, "submap": "", "description": description}


def live_context(binds=None):
    """A live context whose hyprctl answers with the given binds, or is missing when binds is None."""
    if binds is None:
        fake = FakeRun()
    else:
        fake = FakeRun((("hyprctl", "-j", "binds"), Run("ok", 0, json.dumps(binds))))
    return context("broken", live=True, run=fake)


class LiveTableTests(Helpers, unittest.TestCase):
    def test_key_bound_once_in_hyprland_is_not_a_conflict(self):
        result = run_check("keys", live_context([live_bind(64, "F", "Full screen")]))
        self.assertNotIn(("keys.conflict", "SUPER + F"), pairs(result))

    def test_ignored_double_binding_is_mentioned_in_a_note(self):
        result = run_check("keys", live_context([live_bind(64, "F", "Full screen")]))
        self.assertTrue(any("ignored" in note for note in result.notes))

    def test_other_static_conflicts_survive_a_live_table(self):
        result = run_check("keys", live_context([live_bind(64, "F", "Full screen")]))
        self.assertIn(("keys.conflict", "SUPER + G"), pairs(result))

    def test_runtime_binding_clash_is_reported(self):
        table = [live_bind(72, "B", "OmaJuke: previous track"), live_bind(72, "B", "Other thing")]
        result = run_check("keys", live_context(table))
        finding = find(result, "keys.conflict", "SUPER + ALT + B")
        self.assertIn("added while Hyprland was running", finding.message)

    def test_long_press_binding_does_not_collide_with_a_press(self):
        held = dict(live_bind(72, "B", "Hold"), longPress=True)
        result = run_check("keys", live_context([live_bind(72, "B", "Tap"), held]))
        self.assertNotIn(("keys.conflict", "SUPER + ALT + B"), pairs(result))

    def test_stock_alt_tab_pair_is_not_a_conflict(self):
        table = [live_bind(8, "TAB", "Focus on next window"), live_bind(8, "TAB", "Reveal active window on top")]
        result = run_check("keys", live_context(table))
        self.assertNotIn(("keys.conflict", "ALT + TAB"), pairs(result))

    def test_missing_hyprctl_falls_back_to_the_static_findings(self):
        static = run_check("keys", context("broken"))
        result = run_check("keys", live_context(None))
        self.assertEqual(pairs(result), pairs(static))

    def test_missing_hyprctl_is_mentioned_in_a_note(self):
        result = run_check("keys", live_context(None))
        self.assertTrue(any("hyprctl" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
