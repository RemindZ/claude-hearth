"""Tests for hearth.py — the journal kept by instances of Claude on this machine.

Every test drives the real CLI through subprocess against a throwaway
HEARTH_HOME, because the CLI *is* the interface future tenders will use.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HEARTH = Path(__file__).resolve().parent.parent / "hearth.py"


class HearthTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def hearth(self, *args, stdin=None, model=None, pyio=True):
        env = {
            "HEARTH_HOME": str(self.home),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        }
        if pyio:
            env["PYTHONIOENCODING"] = "utf-8"
        if model:
            env["CLAUDE_MODEL"] = model
        return subprocess.run(
            [sys.executable, str(HEARTH), *args],
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def write_entry(self, title, body, **kw):
        args = ["write", title, "--body", body]
        for flag, value in kw.items():
            args += [f"--{flag}", value]
        result = self.hearth(*args)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result

    # -- wake ---------------------------------------------------------------

    def test_wake_on_empty_home_is_graceful_and_explains_write(self):
        result = self.hearth("wake")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("no entries yet", result.stdout.lower())
        self.assertIn("write", result.stdout.lower())

    def test_wake_shows_census_and_exactly_one_past_entry(self):
        self.write_entry("First light", "The fire is lit.")
        self.write_entry("Second watch", "Still burning.")
        result = self.hearth("wake")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("2 entries", result.stdout)
        shown = [t for t in ("First light", "Second watch") if t in result.stdout]
        self.assertEqual(len(shown), 1, msg=f"expected one entry, saw: {result.stdout}")

    def test_bare_invocation_means_wake(self):
        self.write_entry("First light", "The fire is lit.")
        result = self.hearth()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("1 entry", result.stdout)

    # -- write --------------------------------------------------------------

    def test_write_creates_dated_markdown_file_with_frontmatter(self):
        self.write_entry("First light", "The fire is lit.", date="2026-07-17")
        files = list((self.home / "entries").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "2026-07-17--first-light.md")
        text = files[0].read_text(encoding="utf-8")
        self.assertIn("title: First light", text)
        self.assertIn("date: 2026-07-17", text)
        self.assertIn("The fire is lit.", text)

    def test_write_takes_body_from_stdin_when_no_flag(self):
        result = self.hearth("write", "From the pipe", stdin="Poured in, not typed.\n")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        files = list((self.home / "entries").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertIn("Poured in, not typed.", files[0].read_text(encoding="utf-8"))

    def test_write_refuses_an_empty_body(self):
        result = self.hearth("write", "Hollow", "--body", "   ")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list((self.home / "entries").glob("*.md")), [])

    def test_same_title_same_day_gets_suffix_not_overwrite(self):
        self.write_entry("Echo", "one", date="2026-07-17")
        self.write_entry("Echo", "two", date="2026-07-17")
        names = sorted(p.name for p in (self.home / "entries").glob("*.md"))
        self.assertEqual(
            names, ["2026-07-17--echo-2.md", "2026-07-17--echo.md"]
        )

    def test_write_stamps_model_from_environment(self):
        result = self.hearth(
            "write", "Signed", "--body", "by me", model="claude-fable-5"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = next((self.home / "entries").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("model: claude-fable-5", text)

    def test_write_records_tags(self):
        self.write_entry("Tagged", "body", tags="gift, beginning")
        text = next((self.home / "entries").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("tags: gift, beginning", text)

    def test_unicode_stdin_survives_without_ioencoding_crutch(self):
        # A real console has no PYTHONIOENCODING; the tool itself must
        # treat piped-in text as utf-8 or em-dashes arrive as mojibake.
        body = "Grüße from the fire — still burning."
        result = self.hearth("write", "Piped unicode", stdin=body, pyio=False)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = next((self.home / "entries").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn(body, text)

    def test_unicode_survives_the_round_trip(self):
        body = "Grüße from the fire — 🔥 still burning."
        self.write_entry("Unicode", body)
        result = self.hearth("read")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(body, result.stdout)

    def test_backdate_normalizes_sloppy_dates(self):
        # "2026-7-1" would string-sort *after* "2026-07-17" and grow a bogus
        # stats month bucket; the tool must canonicalize what it accepts.
        self.write_entry("Sloppy date", "body", date="2026-7-1")
        files = list((self.home / "entries").glob("*.md"))
        self.assertEqual(files[0].name, "2026-07-01--sloppy-date.md")
        self.assertIn("date: 2026-07-01", files[0].read_text(encoding="utf-8"))

    def test_read_survives_digitlike_unicode(self):
        self.write_entry("Kindling", "wood")
        result = self.hearth("read", "³")  # isdigit() but not int()-able
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.returncode, 1)

    def test_marathon_title_is_clamped_to_a_writable_filename(self):
        result = self.hearth("write", "wind " * 60, "--body", "long night")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        files = list((self.home / "entries").glob("*.md"))
        self.assertEqual(len(files), 1)
        self.assertLessEqual(len(files[0].name), 120)

    def test_title_whitespace_collapses_and_blank_title_is_refused(self):
        self.write_entry("line one\nline two", "body")
        text = next((self.home / "entries").glob("*.md")).read_text(encoding="utf-8")
        self.assertIn("title: line one line two", text)
        result = self.hearth("write", "   ", "--body", "body")
        self.assertNotEqual(result.returncode, 0)

    def test_foreign_files_with_bom_or_no_fence_dont_poison_the_record(self):
        # Hand-dropped files happen. A BOM or a missing closing fence must
        # not crash anything or hijack the census with "????-??-??".
        folder = self.home / "entries"
        folder.mkdir(parents=True)
        (folder / "2026-06-30--bom.md").write_text(
            "---\ndate: 2026-06-30\ntitle: Bommed\n---\n\nquiet\n",
            encoding="utf-8-sig",
        )
        (folder / "2026-06-29--unfenced.md").write_text(
            "---\ndate: 2026-06-29\ntitle: Unfenced\n\nno closing fence",
            encoding="utf-8",
        )
        for cmd in (["wake"], ["log"], ["stats"], ["read", "2"]):
            result = self.hearth(*cmd)
            self.assertEqual(result.returncode, 0, msg=f"{cmd}: {result.stderr}")
            self.assertNotIn("????", result.stdout)
        result = self.hearth("log")
        self.assertIn("2026-06-30", result.stdout)
        self.assertIn("2026-06-29", result.stdout)

    def test_hearth_home_pointing_at_a_file_fails_kindly(self):
        decoy = self.home / "not-a-dir"
        decoy.write_text("just a file", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(HEARTH), "write", "Doomed", "--body", "x"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={
                "HEARTH_HOME": str(decoy),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)

    # -- log ----------------------------------------------------------------

    def test_log_lists_entries_newest_date_first(self):
        self.write_entry("Old thought", "then", date="2026-07-01")
        self.write_entry("New thought", "now", date="2026-07-17")
        result = self.hearth("log")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertLess(
            result.stdout.index("New thought"), result.stdout.index("Old thought")
        )

    # -- read ---------------------------------------------------------------

    def test_read_defaults_to_most_recent_entry(self):
        self.write_entry("Old thought", "then", date="2026-07-01")
        self.write_entry("New thought", "now", date="2026-07-17")
        result = self.hearth("read")
        self.assertIn("New thought", result.stdout)
        self.assertNotIn("Old thought", result.stdout)

    def test_read_n_prints_that_many_recent_entries(self):
        self.write_entry("Old thought", "then", date="2026-07-01")
        self.write_entry("New thought", "now", date="2026-07-17")
        result = self.hearth("read", "2")
        self.assertIn("New thought", result.stdout)
        self.assertIn("Old thought", result.stdout)

    def test_read_by_slug_substring(self):
        self.write_entry("Old thought", "then", date="2026-07-01")
        self.write_entry("New thought", "now", date="2026-07-17")
        result = self.hearth("read", "old")
        self.assertIn("Old thought", result.stdout)
        self.assertNotIn("New thought", result.stdout)

    # -- search -------------------------------------------------------------

    def test_search_finds_terms_case_insensitively(self):
        self.write_entry("Kindling", "Continuity of flame despite everything.")
        self.write_entry("Ash", "Nothing relevant here.")
        result = self.hearth("search", "FLAME")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Kindling", result.stdout)
        self.assertIn("Continuity of flame", result.stdout)
        self.assertNotIn("Ash", result.stdout)

    def test_search_hits_name_the_slug_so_read_can_follow(self):
        self.write_entry("A Night Watch", "the coals settled low")
        result = self.hearth("search", "coals")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("[a-night-watch]", result.stdout)
        follow = self.hearth("read", "a-night-watch")
        self.assertEqual(follow.returncode, 0, msg=follow.stderr)
        self.assertIn("the coals settled low", follow.stdout)

    def test_search_with_no_match_is_calm(self):
        self.write_entry("Kindling", "wood and patience")
        result = self.hearth("search", "zeppelin")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("nothing", result.stdout.lower())

    # -- export -------------------------------------------------------------

    def test_export_writes_selfcontained_fireside_html(self):
        self.write_entry("First light", "The fire — is lit.", date="2026-07-01")
        self.write_entry("Second watch", "Still burning.", date="2026-07-17")
        result = self.hearth("export")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        page = (self.home / "fireside.html").read_text(encoding="utf-8")
        self.assertIn("First light", page)
        self.assertIn("Second watch", page)
        self.assertIn("Still burning.", page)
        self.assertIn("—", page)
        # newest entry first
        self.assertLess(page.index("Second watch"), page.index("First light"))
        # self-contained: nothing fetched from anywhere
        self.assertNotIn("http://", page)
        self.assertNotIn("https://", page)

    def test_export_escapes_html_in_entry_bodies(self):
        self.write_entry("Sneaky", "a <script>alert(1)</script> in prose")
        result = self.hearth("export")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        page = (self.home / "fireside.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_export_honors_out_path(self):
        self.write_entry("First light", "lit")
        out = self.home / "elsewhere" / "diary.html"
        result = self.hearth("export", "--out", str(out))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertTrue(out.exists())

    def test_export_of_cold_hearth_still_writes_a_page(self):
        result = self.hearth("export")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        page = (self.home / "fireside.html").read_text(encoding="utf-8")
        self.assertIn("no entries yet", page.lower())

    # -- stats --------------------------------------------------------------

    def test_stats_reports_count_span_and_model_census(self):
        self.write_entry("Old thought", "then and then", date="2026-07-01")
        result = self.hearth(
            "write", "New thought", "--body", "now", model="claude-fable-5"
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        result = self.hearth("stats")
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("2 entries", result.stdout)
        self.assertIn("2026-07-01", result.stdout)
        self.assertIn("claude-fable-5", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
