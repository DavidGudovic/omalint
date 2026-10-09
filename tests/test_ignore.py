import json
import re
import shutil
import unittest

from helpers import FIXTURES, ROOT, Helpers, cli, context, directory_args, fixture_args, write_plugin

from omalint import cli as command_line
from omalint import ignore, report
from omalint.model import Finding, Result

OWN_ID = "io.github.davidgudovic.omalint"

# The four warnings of the fixable fixture, all in the bar check, as (code, subject).
FIXABLE = [
    ("bar.unknown-bar", "acme.neon-bar"),
    ("bar.unknown-widget", "acme.gone"),
    ("bar.entry-without-id", "bar.layout.center[1]"),
    ("bar.unknown-plugin", "acme.vanished"),
]
FIXABLE_CODES = [code for code, _ in FIXABLE]


def finding(code, subject, severity="warn", **changes):
    return Finding("bar", code, severity, subject, "message", **changes)


def pairs(findings):
    return [(f.code, f.subject) for f in findings]


def pairs_of(findings):
    """The same for findings in a JSON report."""
    return [(f["code"], f["subject"]) for f in findings]


def run_json(*args):
    result = cli("--json", *args)
    return result, json.loads(result.stdout)


def check(data, name):
    (found,) = [c for c in data["checks"] if c["id"] == name]
    return found


def own_entry(**changes):
    return {"id": OWN_ID, **changes}


def config_with(section, entry):
    return {"version": 1, "bar": {"layout": {section: [{"id": "omarchy.clock"}, entry]}}}


class ParseTests(unittest.TestCase):
    def test_a_comma_separated_string_gives_one_rule_per_part(self):
        self.assertEqual(ignore.parse("a.b,c.d:e"), ["a.b", "c.d:e"])

    def test_whitespace_around_rules_is_stripped(self):
        self.assertEqual(ignore.parse("  a.b ,\tc.d:e \n"), ["a.b", "c.d:e"])
        self.assertEqual(ignore.parse(["  a.b ", "\tc.d:e"]), ["a.b", "c.d:e"])

    def test_empty_parts_are_dropped(self):
        self.assertEqual(ignore.parse(",a.b,, ,c.d,"), ["a.b", "c.d"])
        self.assertEqual(ignore.parse(["", "  ", "a.b"]), ["a.b"])
        self.assertEqual(ignore.parse(""), [])
        self.assertEqual(ignore.parse("  ,  "), [])
        self.assertEqual(ignore.parse([]), [])

    def test_a_list_item_is_not_split_on_commas(self):
        # A key binding can be "SUPER + ,"; the list form is how to name it.
        self.assertEqual(ignore.parse(["keys.conflict:SUPER + ,"]), ["keys.conflict:SUPER + ,"])

    def test_any_other_type_holds_no_rules(self):
        for value in (None, 3, 1.5, True, False, {"a.b": 1}, ("a.b",)):
            with self.subTest(value=value):
                self.assertEqual(ignore.parse(value), [])


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.a_x = finding("a.code", "x")
        self.a_y = finding("a.code", "y")
        self.b_x = finding("b.code", "x")
        self.results = {"bar": Result([self.a_x, self.b_x, self.a_y])}

    def apply(self, *rules):
        ignore.apply(self.results, list(rules))
        return self.results["bar"]

    def test_a_code_rule_ignores_every_finding_with_that_code(self):
        result = self.apply("a.code")
        self.assertEqual(result.findings, [self.b_x])
        self.assertEqual(result.ignored, [self.a_x, self.a_y])

    def test_a_code_and_subject_rule_ignores_just_that_finding(self):
        result = self.apply("a.code:y")
        self.assertEqual(result.findings, [self.a_x, self.b_x])
        self.assertEqual(result.ignored, [self.a_y])

    def test_a_subject_with_colons_and_spaces_matches_whole(self):
        keys = finding("keys.conflict", "SUPER + F: open: the [thing]")
        other = finding("keys.conflict", "SUPER + F")
        self.results = {"bar": Result([other, keys])}
        result = self.apply("keys.conflict:SUPER + F: open: the [thing]")
        self.assertEqual(result.findings, [other])
        self.assertEqual(result.ignored, [keys])

    def test_a_rule_that_matches_nothing_changes_nothing(self):
        for rule in ("c.code", "a.code:z", "b.code:y", "a.code:", ":x", "a.cod"):
            with self.subTest(rule=rule):
                result = self.apply(rule)
                self.assertEqual(result.findings, [self.a_x, self.b_x, self.a_y])
                self.assertEqual(result.ignored, [])

    def test_matching_is_case_sensitive_in_both_parts(self):
        result = self.apply("A.code", "a.CODE:x", "a.code:X")
        self.assertEqual(result.ignored, [])
        self.assertEqual(len(result.findings), 3)

    def test_the_order_of_both_lists_is_kept(self):
        findings = [finding("a.code", str(n)) if n % 2 else finding("b.code", str(n)) for n in range(8)]
        self.results = {"bar": Result(list(findings))}
        result = self.apply("a.code")
        self.assertEqual(result.ignored, [f for f in findings if f.code == "a.code"])
        self.assertEqual(result.findings, [f for f in findings if f.code == "b.code"])


class FindingTests(unittest.TestCase):
    def test_the_rule_is_the_code_and_the_subject(self):
        self.assertEqual(finding("stale.local-changes", "zeru.portwatch").rule, "stale.local-changes:zeru.portwatch")

    def test_the_rule_is_part_of_the_json(self):
        self.assertEqual(finding("a.b", "SUPER + F: x").to_json()["rule"], "a.b:SUPER + F: x")


class FromConfigTests(unittest.TestCase):
    def test_the_plugin_id_is_the_one_in_the_manifest(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(ignore.PLUGIN_ID, manifest["id"])
        self.assertEqual(OWN_ID, manifest["id"])

    def test_the_list_form(self):
        config = config_with("right", own_entry(ignore=["a.b", "c.d:e f"]))
        self.assertEqual(ignore.from_config(config), ["a.b", "c.d:e f"])

    def test_the_string_form(self):
        config = config_with("right", own_entry(ignore="a.b, c.d:e f,"))
        self.assertEqual(ignore.from_config(config), ["a.b", "c.d:e f"])

    def test_the_entry_is_found_in_each_section(self):
        for section in ("left", "center", "right"):
            with self.subTest(section=section):
                config = config_with(section, own_entry(ignore="a.b"))
                self.assertEqual(ignore.from_config(config), ["a.b"])

    def test_an_id_written_as_an_array_is_recognised(self):
        # The shell reads {"id": ["x"]} as "x", so a config written that way still counts.
        config = config_with("center", {"id": [OWN_ID], "ignore": "a.b"})
        self.assertEqual(ignore.from_config(config), ["a.b"])

    def test_another_widgets_ignore_setting_is_not_ours(self):
        config = config_with("right", {"id": "acme.good", "ignore": "a.b"})
        self.assertEqual(ignore.from_config(config), [])

    def test_no_config_at_all(self):
        # shell.json is missing or invalid.
        self.assertEqual(ignore.from_config(None), [])

    def test_odd_shapes_are_tolerated(self):
        entry = own_entry(ignore="a.b")
        shapes = [
            [], "text", 3, True,
            {"bar": None}, {"bar": "x"}, {"bar": []}, {"bar": [entry]},
            {"bar": {}}, {"bar": {"layout": None}}, {"bar": {"layout": []}}, {"bar": {"layout": [entry]}},
            {"bar": {"layout": {"right": None}}}, {"bar": {"layout": {"right": entry}}},
            {"bar": {"layout": {"right": "text"}}}, {"bar": {"layout": {"right": {"0": entry}}}},
            {"bar": {"layout": {"right": [None, 3, "text", [entry], True]}}},
            {"bar": {"layout": {"right": [OWN_ID]}}},
        ]
        for config in shapes:
            with self.subTest(config=config):
                self.assertEqual(ignore.from_config(config), [])


class RunChecksTests(unittest.TestCase):
    def test_rules_given_to_run_checks_are_applied(self):
        _, results = command_line.run_checks(context("fixable"), ["bar"], ["bar.unknown-widget:acme.gone"])
        self.assertEqual(pairs(results["bar"].ignored), [("bar.unknown-widget", "acme.gone")])
        self.assertEqual(len(results["bar"].findings), 3)


class ReportTests(unittest.TestCase):
    def results(self):
        return {"bar": Result(
            [finding("bar.unknown-bar", "acme.neon-bar", fix="Remove the entry.")],
            notes=["3 entries checked."],
            ignored=[finding("bar.unknown-widget", "acme.gone"), finding("bar.unknown-plugin", "acme.vanished")],
        )}

    def lines(self, *args, **kwargs):
        return report.as_text(self.results(), *args, **kwargs).splitlines()

    def test_the_ignored_line_comes_after_the_findings_and_before_the_notes(self):
        lines = self.lines(False)
        at = lines.index("         Ignored: bar.unknown-widget:acme.gone, bar.unknown-plugin:acme.vanished.")
        self.assertIn("acme.neon-bar", " ".join(lines[:at]))
        self.assertEqual(lines[at + 1], "         3 entries checked.")

    def test_the_closing_line_counts_the_ignored(self):
        self.assertEqual(self.lines(False)[-1], "  1 warning found. 2 ignored.")

    def test_a_check_with_only_ignored_findings_is_ok(self):
        results = {"bar": Result(ignored=[finding("bar.unknown-widget", "acme.gone")])}
        out = report.as_text(results, False)
        self.assertIn("OK     Bar layout", out)
        self.assertTrue(out.endswith("  No problems found. 1 ignored.\n"))

    def test_the_ignored_count_comes_before_the_fix_hint(self):
        fixable = finding("bar.unknown-widget", "acme.gone", action={"op": "remove-bar-id"})
        results = {"bar": Result([fixable], ignored=[finding("a.b", "x")])}
        self.assertEqual(
            report.as_text(results, False).splitlines()[-1],
            "  1 warning found. 1 ignored. 1 problem can be fixed automatically: omalint --fix",
        )


class IgnoreOptionTests(unittest.TestCase):
    def test_a_code_rule_hides_the_finding_and_shows_where_it_went(self):
        result, data = run_json("--ignore", "bar.unknown-widget", *fixture_args("fixable"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["summary"]["warnings"], 3)
        self.assertEqual(data["summary"]["ignored"], 1)
        bar = check(data, "bar")
        self.assertEqual(pairs_of(bar["findings"]), [p for p in FIXABLE if p[0] != "bar.unknown-widget"])
        (ignored,) = bar["ignored"]
        self.assertEqual((ignored["code"], ignored["subject"]), ("bar.unknown-widget", "acme.gone"))
        self.assertEqual(ignored["rule"], "bar.unknown-widget:acme.gone")
        self.assertEqual(ignored["severity"], "warn")

    def test_a_code_and_subject_rule_does_the_same(self):
        _, by_code = run_json("--ignore", "bar.unknown-widget", *fixture_args("fixable"))
        _, by_both = run_json("--ignore", "bar.unknown-widget:acme.gone", *fixture_args("fixable"))
        self.assertEqual(by_both, by_code)

    def test_a_subject_that_does_not_match_ignores_nothing(self):
        result, data = run_json("--ignore", "bar.unknown-widget:nope", *fixture_args("fixable"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["summary"]["warnings"], 4)
        self.assertEqual(data["summary"]["ignored"], 0)
        self.assertEqual(check(data, "bar")["ignored"], [])

    def test_two_options_and_one_comma_separated_option_are_equivalent(self):
        two = ["--ignore", "bar.unknown-widget", "--ignore", "bar.unknown-plugin:acme.vanished"]
        one = ["--ignore", "bar.unknown-widget,bar.unknown-plugin:acme.vanished"]
        spaced = ["--ignore", " bar.unknown-widget , bar.unknown-plugin:acme.vanished,"]
        for mode in ("--json", "--no-color"):
            expected = cli(mode, *two, *fixture_args("fixable"))
            self.assertEqual(expected.returncode, 0, expected.stderr)
            for other in (one, spaced):
                with self.subTest(mode=mode, other=other):
                    self.assertEqual(cli(mode, *other, *fixture_args("fixable")).stdout, expected.stdout)
        _, data = run_json(*two, *fixture_args("fixable"))
        self.assertEqual(data["summary"]["ignored"], 2)
        self.assertEqual(data["summary"]["warnings"], 2)

    def test_ignoring_everything_makes_strict_pass(self):
        args = [arg for code in FIXABLE_CODES for arg in ("--ignore", code)]
        self.assertEqual(cli("--no-color", "--strict", *fixture_args("fixable")).returncode, 1)
        result = cli("--no-color", "--strict", *args, *fixture_args("fixable"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("  No problems found. 4 ignored.\n", result.stdout)
        self.assertNotIn("fixed automatically", result.stdout)
        self.assertIn("OK     Bar layout", result.stdout)
        ignored = "Ignored: " + ", ".join(f"{code}:{subject}" for code, subject in FIXABLE) + "."
        self.assertIn(ignored, re.sub(r"\s*\n\s+", " ", result.stdout))

    def test_ignored_findings_leave_the_status_and_the_fixable_count(self):
        _, data = run_json("--ignore", ",".join(FIXABLE_CODES), *fixture_args("fixable"))
        self.assertEqual(data["ok"], True)
        self.assertEqual(data["summary"], {
            "errors": 0, "warnings": 0, "notes": 0, "fixable": 0, "ignored": 4, "plugins": 1,
        })
        bar = check(data, "bar")
        self.assertEqual((bar["status"], bar["findings"]), ("ok", []))
        self.assertEqual(pairs_of(bar["ignored"]), FIXABLE)


class RulesOptionTests(unittest.TestCase):
    def test_each_finding_gets_a_rule_line_after_its_fix_line(self):
        out = cli("--no-color", "--rules", *fixture_args("fixable")).stdout
        lines = out.splitlines()
        for code, subject in FIXABLE:
            with self.subTest(rule=f"{code}:{subject}"):
                at = lines.index(f"           rule: {code}:{subject}")
                self.assertIn("`omalint --fix` does this.)", lines[at - 1])
        self.assertEqual(sum(line.lstrip().startswith("rule: ") for line in lines), 4)

    def test_without_the_flag_the_report_has_no_rule_lines(self):
        out = cli("--no-color", *fixture_args("fixable")).stdout
        self.assertNotIn("rule:", out)

    def test_help_describes_both_options(self):
        out = cli("--help").stdout
        self.assertIn("--ignore RULE", out)
        self.assertIn("CODE or CODE:SUBJECT", out)
        self.assertIn("--rules", out)
        self.assertIn("Hide it with --ignore RULE", out)
        self.assertLess(out.index("Hide it with --ignore RULE"), out.index("Exit status"))

    def test_the_version_is_the_one_in_the_manifest(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(command_line.VERSION, manifest["version"])
        self.assertEqual(command_line.VERSION, "0.3.0")


class ErrorFindingTests(unittest.TestCase):
    def test_an_ignored_error_is_no_longer_counted(self):
        _, plain = run_json(*fixture_args("broken"))
        result, data = run_json("--ignore", "manifest.reserved-id", *fixture_args("broken"))
        self.assertEqual(data["summary"]["errors"], plain["summary"]["errors"] - 1)
        self.assertEqual(data["summary"]["warnings"], plain["summary"]["warnings"])
        self.assertEqual(data["summary"]["ignored"], 1)
        manifests = check(data, "manifests")
        (ignored,) = manifests["ignored"]
        self.assertEqual((ignored["code"], ignored["subject"], ignored["severity"]), ("manifest.reserved-id", "acme.reserved", "error"))
        self.assertNotIn("manifest.reserved-id", [f["code"] for f in manifests["findings"]])
        self.assertEqual(manifests["status"], "error")
        self.assertEqual(result.returncode, 1)


class SettingTestCase(Helpers, unittest.TestCase):
    """A temp copy of the fixable fixture with OmaLint's own plugin installed."""

    def setUp(self):
        root = self.tempdir()
        shutil.copytree(FIXTURES / "fixable", root / "fixable")
        self.config_dir = root / "fixable" / "omarchy"
        self.shell_json = self.config_dir / "shell.json"
        self.args = directory_args(self.config_dir, root / "fixable" / "hypr")
        # Without its folder the entry would itself be an unknown widget.
        write_plugin(self.config_dir, OWN_ID)

    def config(self):
        return json.loads(self.shell_json.read_text(encoding="utf-8"))

    def add_entry(self, section="right", **entry):
        config = self.config()
        config["bar"]["layout"][section].append({"id": OWN_ID, **entry})
        self.write(config)

    def write(self, config):
        self.shell_json.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class ShellJsonSettingTests(SettingTestCase):
    def test_the_comma_separated_string_form(self):
        self.add_entry(ignore="bar.unknown-widget, bar.unknown-plugin")
        result, data = run_json(*self.args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["summary"]["warnings"], 2)
        self.assertEqual(data["summary"]["ignored"], 2)
        self.assertEqual(
            pairs_of(check(data, "bar")["ignored"]),
            [("bar.unknown-widget", "acme.gone"), ("bar.unknown-plugin", "acme.vanished")],
        )

    def test_the_list_form(self):
        self.add_entry(ignore=["bar.unknown-widget", "bar.unknown-plugin"])
        _, data = run_json(*self.args)
        self.assertEqual(data["summary"]["warnings"], 2)
        self.assertEqual(data["summary"]["ignored"], 2)

    def test_it_adds_to_the_command_line_rules(self):
        self.add_entry(ignore="bar.unknown-widget")
        _, data = run_json("--ignore", "bar.unknown-bar", *self.args)
        self.assertEqual(data["summary"]["warnings"], 2)
        self.assertEqual(
            sorted(pairs_of(check(data, "bar")["ignored"])),
            [("bar.unknown-bar", "acme.neon-bar"), ("bar.unknown-widget", "acme.gone")],
        )

    def test_an_invalid_shell_json_gives_no_rules_and_no_crash(self):
        self.add_entry(ignore="bar.unknown-widget")
        self.shell_json.write_text('{"version": 1, "bar": ', encoding="utf-8")
        result, data = run_json(*self.args)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["summary"]["ignored"], 0)


class FixWithIgnoreTests(SettingTestCase):
    def fixed_left(self):
        return self.config()["bar"]["layout"]["left"]

    def test_fix_leaves_an_ignored_dead_entry_alone(self):
        before = self.config()
        result = cli("--fix", "--no-color", "--ignore", "bar.unknown-widget:acme.gone", *self.args)
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("Fixing 3 problems", out)
        self.assertFalse(any(line.startswith("-") and "acme.gone" in line for line in out.splitlines()), out)
        self.assertEqual(self.fixed_left(), before["bar"]["layout"]["left"])
        self.assertIn({"id": "acme.gone", "color": "red"}, self.fixed_left())

    def test_fix_still_repairs_the_other_problems(self):
        cli("--fix", "--no-color", "--ignore", "bar.unknown-widget:acme.gone", *self.args)
        config = self.config()
        self.assertNotIn("id", config["bar"])
        self.assertEqual(config["bar"]["layout"]["center"], [{"id": "omarchy.clock", "verticalFormat": "HH\n—\nmm"}])
        self.assertEqual(config["plugins"], [{"id": "omarchy.emojis"}])
        self.assertEqual(len([p for p in self.config_dir.iterdir() if ".bak." in p.name]), 1)

    def test_the_report_after_the_fix_still_shows_what_was_ignored(self):
        result = cli("--fix", "--no-color", "--ignore", "bar.unknown-widget:acme.gone", *self.args)
        tail = result.stdout[result.stdout.index("Backup saved"):]
        self.assertIn("Ignored: bar.unknown-widget:acme.gone.", tail)
        self.assertIn("  No problems found. 1 ignored.\n", tail)

    def test_fix_honours_the_setting_in_shell_json_and_keeps_it(self):
        self.add_entry(ignore="bar.unknown-widget")
        result = cli("--fix", "--no-color", *self.args)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.config()
        self.assertIn({"id": "acme.gone", "color": "red"}, config["bar"]["layout"]["left"])
        self.assertIn({"id": OWN_ID, "ignore": "bar.unknown-widget"}, config["bar"]["layout"]["right"])
        self.assertNotIn("id", config["bar"])
        self.assertIn("  No problems found. 1 ignored.\n", result.stdout)

    def test_fix_of_the_bar_check_alone_still_honours_the_rules(self):
        # --only keys leaves the bar check out of the run; --fix runs it again by itself.
        result = cli("--fix", "--only", "keys", "--no-color", "--ignore", "bar.unknown-widget", *self.args)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Fixing 3 problems", result.stdout)
        self.assertIn({"id": "acme.gone", "color": "red"}, self.fixed_left())


if __name__ == "__main__":
    unittest.main()
