from __future__ import annotations

from contextlib import closing, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import runpy
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "lastdone"
CONVENTION_FIXTURES = ROOT / "conventions" / "v1" / "fixtures"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
RUN = runpy.run_path(str(CLI), run_name="lastdone_test")["run"]


def remove_reading_columns(database: sqlite3.Connection) -> None:
    database.execute("ALTER TABLE events DROP COLUMN reading_unit")
    database.execute("ALTER TABLE events DROP COLUMN reading_value")


class CliContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_home = Path(self.temporary_directory.name)
        self.environment = os.environ.copy()
        self.environment["XDG_DATA_HOME"] = str(self.data_home)
        self.environment["TZ"] = "UTC"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_cli(
        self,
        *arguments: str,
        environment: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), *arguments],
            capture_output=True,
            text=True,
            input=input_text,
            env=environment or self.environment,
            check=False,
        )

    def add_json(self, name: str, *options: str) -> dict[str, object]:
        result = self.run_cli("add", name, *options, "--jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        self.assertEqual(1, result.stdout.count("\n"))
        return json.loads(result.stdout)

    def test_help_and_version(self) -> None:
        version = self.run_cli("--version")
        self.assertEqual(0, version.returncode)
        self.assertEqual("lastdone 0.10.0\n", version.stdout)
        self.assertEqual("", version.stderr)

        help_result = self.run_cli("--help")
        self.assertEqual(0, help_result.returncode)
        self.assertIn("usage: lastdone", help_result.stdout)
        self.assertIn("--db PATH", help_result.stdout)
        self.assertIn("export", help_result.stdout)
        self.assertIn("import", help_result.stdout)
        self.assertIn("batch", help_result.stdout)
        self.assertIn("doctor", help_result.stdout)
        self.assertIn("void", help_result.stdout)
        self.assertIn("replace", help_result.stdout)
        self.assertIn("set", help_result.stdout)
        self.assertIn("due", help_result.stdout)
        self.assertEqual("", help_result.stderr)

    def test_invalid_input_uses_exit_two_and_stderr(self) -> None:
        for arguments in (
            (),
            ("unknown",),
            ("add", ""),
            ("add", "line\nbreak"),
            ("add", "escape\x1bsequence"),
            ("add", "bad-date", "--date", "2026-02-29"),
            ("add", "compact-date", "--date", "20260821"),
            ("add", "future", "--date", "9999-12-31"),
            ("add", "reading", "--reading", ""),
            ("add", "reading", "--reading", "01mi"),
            ("add", "reading", "--reading", ".5mi"),
            ("add", "reading", "--reading", "1.mi"),
            ("add", "reading", "--reading", "-1mi"),
            ("add", "reading", "--reading", "+1mi"),
            ("add", "reading", "--reading", "1e3mi"),
            ("add", "reading", "--reading", "1MI"),
            ("add", "reading", "--reading", "1 mi"),
            ("add", "reading", "--reading", "1m_i"),
            ("add", "reading", "--reading", "1mi--trip"),
            ("add", "reading", "--allow-decrease"),
            ("--db", "", "list"),
            ("list", "--db", "somewhere.db"),
            ("export",),
            ("import",),
            ("batch",),
            ("void", ""),
            ("void", "event"),
            ("void", "event", "--reason", ""),
            ("replace", "event"),
            ("replace", "event", "--reason", "reason", "--allow-decrease"),
            ("replace", "event", "--reason", "reason", "--note", "line\nbreak"),
            ("set", "name"),
            ("set", "name", "--display-name", ""),
            ("set", "name", "--display-name", "line\nbreak"),
            ("set", "name", "--every", "0d"),
            ("set", "name", "--every", "01d"),
            ("set", "name", "--every", "+1d"),
            ("set", "name", "--every", "-1d"),
            ("set", "name", "--every", "1D"),
            ("set", "name", "--every", "1"),
            ("set", "name", "--every", "1mo"),
            ("set", "name", "--every", "١d"),
            ("set", "name", "--every", "9223372036854775808d"),
            ("due", "unexpected"),
            ("add", "Uppercase"),
            ("add", "éclair"),
            ("add", "-leading"),
            ("add", "trailing-"),
            ("add", "two--hyphens"),
            ("add", "under_score"),
            ("add", "white space"),
            ("show", "éclair"),
            ("history", "Uppercase"),
            ("set", "éclair", "--every", "1d"),
            (
                "replace",
                "event",
                "--reason",
                "reason",
                "--name",
                "Uppercase",
            ),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr.startswith("lastdone: error:"))
                self.assertNotIn("Traceback", result.stderr)

    def test_database_path_precedence(self) -> None:
        home = self.data_home / "home"
        environment_path = home / "environment" / "last.db"
        xdg_path = self.data_home / "last" / "last.db"
        environment = self.environment.copy()
        environment["HOME"] = str(home)
        environment["LASTDONE_DB"] = "~/environment/last.db"

        cli_result = self.run_cli(
            "--db", "~/cli/last.db", "add", "cli", environment=environment
        )
        self.assertEqual(0, cli_result.returncode, cli_result.stderr)
        self.assertTrue((home / "cli" / "last.db").is_file())
        self.assertFalse(environment_path.exists())
        self.assertFalse(xdg_path.exists())

        environment_result = self.run_cli(
            "add", "environment", environment=environment
        )
        self.assertEqual(
            0, environment_result.returncode, environment_result.stderr
        )
        self.assertTrue(environment_path.is_file())
        self.assertFalse(xdg_path.exists())

        environment["LASTDONE_DB"] = ""
        xdg_result = self.run_cli("add", "xdg", environment=environment)
        self.assertEqual(0, xdg_result.returncode, xdg_result.stderr)
        self.assertTrue(xdg_path.is_file())

        fallback_home = self.data_home / "fallback-home"
        environment.pop("LASTDONE_DB")
        environment.pop("XDG_DATA_HOME")
        environment["HOME"] = str(fallback_home)
        fallback_result = self.run_cli(
            "add", "fallback", environment=environment
        )
        self.assertEqual(0, fallback_result.returncode, fallback_result.stderr)
        self.assertTrue(
            (fallback_home / ".local" / "share" / "last" / "last.db").is_file()
        )

        if os.name == "posix":
            shared_directory = self.data_home / "shared"
            shared_directory.mkdir(mode=0o755)
            os.chmod(shared_directory, 0o755)
            shared_result = self.run_cli(
                "--db",
                str(shared_directory / "last.db"),
                "list",
                environment=environment,
            )
            self.assertEqual(0, shared_result.returncode, shared_result.stderr)
            self.assertEqual(
                0o755, stat.S_IMODE(shared_directory.stat().st_mode)
            )

    def test_empty_list_and_missing_activity(self) -> None:
        for arguments in (("list",), ("list", "--jsonl")):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(0, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual("", result.stderr)

        for command in ("show", "history"):
            with self.subTest(command=command):
                result = self.run_cli(command, "missing")
                self.assertEqual(1, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual(
                    "lastdone: activity not found: missing\n", result.stderr
                )

    def test_fresh_database_is_versioned_private_and_idempotent(self) -> None:
        first = self.run_cli("list")
        self.assertEqual(0, first.returncode, first.stderr)
        database_path = self.data_home / "last" / "last.db"
        self.assertTrue(database_path.is_file())
        self.assertFalse(database_path.with_name("last.db.v0.bak").exists())
        self.assertFalse(database_path.with_name("last.db.v3.bak").exists())
        if os.name == "posix":
            self.assertEqual(0o700, stat.S_IMODE(database_path.parent.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(database_path.stat().st_mode))

        with closing(sqlite3.connect(database_path)) as database:
            version = database.execute("PRAGMA user_version").fetchone()[0]
            table_sql = database.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'events'"
            ).fetchone()[0]
            correction_sql = database.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'corrections'"
            ).fetchone()[0]
            activity_sql = database.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'activities'"
            ).fetchone()[0]
        self.assertEqual(5, version)
        self.assertIn("events_occurred_at_valid", table_sql)
        self.assertIn("events_reading_valid", table_sql)
        self.assertIn("corrections_relationship_valid", correction_sql)
        self.assertIn("activities_interval_positive", activity_sql)
        self.assertIn("activities_display_name_nonempty", activity_sql)
        self.assertIn("activities_metadata_present", activity_sql)

        second = self.run_cli("list")
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertFalse(database_path.with_name("last.db.v0.bak").exists())
        self.assertFalse(database_path.with_name("last.db.v3.bak").exists())

    def test_add_is_silent_and_jsonl_add_is_an_event(self) -> None:
        silent = self.run_cli("add", "furnace-filter")
        self.assertEqual(0, silent.returncode)
        self.assertEqual("", silent.stdout)
        self.assertEqual("", silent.stderr)

        event = self.add_json("furnace-filter")
        self.assertEqual(
            {
                "schema_version": 2,
                "type": "event",
                "id": event["id"],
                "name": "furnace-filter",
                "occurred_at": event["occurred_at"],
                "occurred_on": None,
                "note": None,
                "reading_value": None,
                "reading_unit": None,
            },
            event,
        )
        UUID(str(event["id"]))
        self.assertRegex(str(event["occurred_at"]), TIMESTAMP)

    def test_readings_are_canonical_and_show_exact_unit_changes(self) -> None:
        older = self.add_json(
            "oil-change",
            "--date",
            "2026-01-01",
            "--reading",
            "80800.00mi",
        )
        latest = self.add_json(
            "oil-change",
            "--date",
            "2026-02-01",
            "--reading",
            "84221.500mi",
        )
        self.assertEqual(
            ("80800", "mi"),
            (older["reading_value"], older["reading_unit"]),
        )
        self.assertEqual(
            ("84221.5", "mi"),
            (latest["reading_value"], latest["reading_unit"]),
        )

        summary = json.loads(
            self.run_cli("show", "oil-change", "--jsonl").stdout
        )
        self.assertEqual("84221.5", summary["reading_value"])
        self.assertEqual("mi", summary["reading_unit"])
        self.assertEqual("3421.5", summary["reading_change"])
        self.assertIn(
            "Reading: 84221.5mi (+3421.5mi)\n",
            self.run_cli("show", "oil-change").stdout,
        )
        history = self.run_cli("history", "oil-change")
        self.assertIn(f"{latest['id']}  2026-02-01  84221.5mi\n", history.stdout)
        self.assertIn(f"{older['id']}  2026-01-01  80800mi\n", history.stdout)

        different_unit = self.add_json(
            "oil-change",
            "--date",
            "2026-03-01",
            "--reading",
            "10km",
        )
        self.assertEqual("km", different_unit["reading_unit"])
        summary = json.loads(
            self.run_cli("show", "oil-change", "--jsonl").stdout
        )
        self.assertEqual("10", summary["reading_value"])
        self.assertEqual("km", summary["reading_unit"])
        self.assertIsNone(summary["reading_change"])

        self.add_json(
            "precision",
            "--date",
            "2026-01-01",
            "--reading",
            "9999999999999999999999999999.99cycles",
        )
        self.add_json(
            "precision",
            "--date",
            "2026-02-01",
            "--reading",
            "10000000000000000000000000000.01cycles",
        )
        precise = json.loads(
            self.run_cli("show", "precision", "--jsonl").stdout
        )
        self.assertEqual("0.02", precise["reading_change"])

    def test_decreasing_and_out_of_order_readings_require_confirmation(
        self,
    ) -> None:
        self.add_json("meter", "--date", "2026-01-01", "--reading", "100mi")
        rejected = self.run_cli(
            "add", "meter", "--date", "2026-02-01", "--reading", "90mi"
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("use --allow-decrease", rejected.stderr)
        self.assertEqual(
            1,
            len(self.run_cli("history", "meter", "--jsonl").stdout.splitlines()),
        )

        reset = self.add_json(
            "meter",
            "--date",
            "2026-02-01",
            "--reading",
            "90mi",
            "--allow-decrease",
        )
        reset_summary = json.loads(
            self.run_cli("show", "meter", "--jsonl").stdout
        )
        self.assertEqual("-10", reset_summary["reading_change"])
        self.assertIn("Reading: 90mi (-10mi)\n", self.run_cli("show", "meter").stdout)

        self.add_json("meter", "--date", "2026-03-01", "--reading", "95mi")
        middle = self.add_json(
            "meter", "--date", "2026-02-15", "--reading", "92mi"
        )
        self.assertEqual("92", middle["reading_value"])
        for value in ("85mi", "99mi"):
            with self.subTest(value=value):
                result = self.run_cli(
                    "add",
                    "meter",
                    "--date",
                    "2026-02-15",
                    "--reading",
                    value,
                )
                self.assertEqual(2, result.returncode)
        records = self.run_cli("history", "meter", "--jsonl").stdout.splitlines()
        self.assertEqual(4, len(records))
        self.assertIn(reset["id"], [json.loads(record)["id"] for record in records])

        exported = self.run_cli("export", "--jsonl").stdout
        imported_path = self.data_home / "confirmed-reset" / "last.db"
        imported_arguments = ("--db", str(imported_path))
        imported = self.run_cli(
            *imported_arguments,
            "import",
            "--jsonl",
            input_text=exported,
        )
        self.assertEqual(0, imported.returncode, imported.stderr)
        self.assertEqual(
            exported,
            self.run_cli(*imported_arguments, "export", "--jsonl").stdout,
        )

    def test_replace_preserves_and_validates_readings(self) -> None:
        self.add_json("meter", "--date", "2026-01-01", "--reading", "100mi")
        target = self.add_json(
            "meter", "--date", "2026-02-01", "--reading", "110mi"
        )
        rejected = self.run_cli(
            "replace",
            str(target["id"]),
            "--reason",
            "meter reset",
            "--reading",
            "90mi",
            "--jsonl",
        )
        self.assertEqual(2, rejected.returncode)
        self.assertEqual("", rejected.stdout)

        accepted = self.run_cli(
            "replace",
            str(target["id"]),
            "--reason",
            "meter reset",
            "--reading",
            "90mi",
            "--allow-decrease",
            "--jsonl",
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        replacement_id = json.loads(accepted.stdout)["replacement_id"]
        replacement = json.loads(
            self.run_cli("history", "meter", "--jsonl").stdout.splitlines()[0]
        )
        self.assertEqual(replacement_id, replacement["id"])
        self.assertEqual(
            ("90", "mi"),
            (replacement["reading_value"], replacement["reading_unit"]),
        )
        summary = json.loads(self.run_cli("show", "meter", "--jsonl").stdout)
        self.assertEqual("-10", summary["reading_change"])

        preserved = self.run_cli(
            "replace",
            str(replacement_id),
            "--reason",
            "add note",
            "--note",
            "confirmed",
            "--allow-decrease",
            "--jsonl",
        )
        self.assertEqual(0, preserved.returncode, preserved.stderr)
        newest = json.loads(
            self.run_cli("history", "meter", "--jsonl").stdout.splitlines()[0]
        )
        self.assertEqual("confirmed", newest["note"])
        self.assertEqual(
            ("90", "mi"),
            (newest["reading_value"], newest["reading_unit"]),
        )

    def test_export_import_round_trip_is_lossless_and_idempotent(self) -> None:
        instant = self.add_json("instant")
        dated = self.add_json("dated", "--date", "2024-02-29")
        source_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(source_path)) as database:
            database.execute(
                "UPDATE events SET note = ? WHERE id = ?",
                ("line one · line two — café", dated["id"]),
            )
            database.commit()

        exported = self.run_cli("export", "--jsonl")
        self.assertEqual(0, exported.returncode, exported.stderr)
        self.assertEqual("", exported.stderr)
        records = [json.loads(line) for line in exported.stdout.splitlines()]
        self.assertEqual([instant["id"], dated["id"]], [r["id"] for r in records])
        self.assertTrue(all(record["record_version"] == 5 for record in records))
        self.assertTrue(all("schema_version" not in record for record in records))
        self.assertEqual("line one · line two — café", records[1]["note"])

        target_path = self.data_home / "round-trip" / "last.db"
        target_arguments = ("--db", str(target_path))
        imported = self.run_cli(
            *target_arguments,
            "import",
            "--jsonl",
            input_text=exported.stdout,
        )
        self.assertEqual(0, imported.returncode, imported.stderr)
        self.assertEqual("", imported.stdout)
        self.assertEqual("", imported.stderr)

        target_export = self.run_cli(*target_arguments, "export", "--jsonl")
        self.assertEqual(exported.stdout, target_export.stdout)
        repeated = self.run_cli(
            *target_arguments,
            "import",
            "--jsonl",
            input_text=exported.stdout,
        )
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual(
            exported.stdout,
            self.run_cli(*target_arguments, "export", "--jsonl").stdout,
        )

    def test_personal_os_convention_fixtures_match_cli(self) -> None:
        fixture_text: dict[str, str] = {}
        for name in (
            "events.jsonl",
            "invalid.stderr",
            "not-a-database.txt",
            "summary.jsonl",
            "not-found.stderr",
            "storage.stderr",
            "version.stdout",
        ):
            raw = (CONVENTION_FIXTURES / name).read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), name)
            self.assertNotIn(b"\r", raw, name)
            self.assertTrue(raw.endswith(b"\n"), name)
            fixture_text[name] = raw.decode("utf-8")

        for name in ("events.jsonl", "summary.jsonl"):
            for line in fixture_text[name].splitlines():
                record = json.loads(line)
                self.assertIsInstance(record, dict)
                self.assertEqual(
                    line,
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )

        database_path = self.data_home / "convention-fixtures" / "last.db"
        arguments = ("--db", str(database_path))
        imported = self.run_cli(
            *arguments,
            "import",
            "--jsonl",
            input_text=fixture_text["events.jsonl"],
        )
        self.assertEqual(0, imported.returncode, imported.stderr)
        self.assertEqual("", imported.stdout)
        self.assertEqual("", imported.stderr)
        exported = self.run_cli(*arguments, "export", "--jsonl")
        self.assertEqual(0, exported.returncode, exported.stderr)
        self.assertEqual("", exported.stderr)
        self.assertEqual(
            fixture_text["events.jsonl"],
            exported.stdout,
        )
        summary = self.run_cli(
            *arguments, "show", "furnace-filter", "--jsonl"
        )
        self.assertEqual(0, summary.returncode, summary.stderr)
        self.assertEqual("", summary.stderr)
        self.assertEqual(
            fixture_text["summary.jsonl"],
            summary.stdout,
        )

        missing = self.run_cli(*arguments, "show", "missing")
        self.assertEqual(1, missing.returncode)
        self.assertEqual("", missing.stdout)
        self.assertEqual(fixture_text["not-found.stderr"], missing.stderr)
        invalid = self.run_cli("add", "Uppercase")
        self.assertEqual(2, invalid.returncode)
        self.assertEqual("", invalid.stdout)
        self.assertEqual(fixture_text["invalid.stderr"], invalid.stderr)
        invalid_database = CONVENTION_FIXTURES / "not-a-database.txt"
        before = invalid_database.read_bytes()
        storage = self.run_cli("--db", str(invalid_database), "list")
        self.assertEqual(3, storage.returncode)
        self.assertEqual("", storage.stdout)
        self.assertEqual(fixture_text["storage.stderr"], storage.stderr)
        self.assertEqual(before, invalid_database.read_bytes())
        version = self.run_cli("--version")
        self.assertEqual(0, version.returncode)
        self.assertEqual(fixture_text["version.stdout"], version.stdout)
        self.assertEqual("", version.stderr)

    def test_export_import_preserves_correction_chains(self) -> None:
        original = self.add_json("original", "--date", "2024-01-01")
        replaced = self.run_cli(
            "replace",
            str(original["id"]),
            "--reason",
            "rename",
            "--name",
            "renamed",
            "--jsonl",
        )
        self.assertEqual(0, replaced.returncode, replaced.stderr)
        replacement = json.loads(replaced.stdout)
        voided = self.run_cli(
            "void",
            replacement["replacement_id"],
            "--reason",
            "did not happen",
            "--jsonl",
        )
        self.assertEqual(0, voided.returncode, voided.stderr)
        void_correction = json.loads(voided.stdout)
        configured = self.run_cli(
            "set",
            "renamed",
            "--every",
            "90d",
            "--display-name",
            "תחזוקה 🧰",
        )
        self.assertEqual(0, configured.returncode, configured.stderr)

        exported = self.run_cli("export", "--jsonl")
        self.assertEqual(0, exported.returncode, exported.stderr)
        records = [json.loads(line) for line in exported.stdout.splitlines()]
        self.assertEqual(
            ["event", "event", "correction", "correction", "activity"],
            [record["type"] for record in records],
        )
        self.assertTrue(all(record["record_version"] == 5 for record in records))
        self.assertEqual(
            [replacement["id"], void_correction["id"]],
            [record["id"] for record in records[2:4]],
        )
        self.assertEqual(90, records[4]["expected_interval_days"])
        self.assertEqual("תחזוקה 🧰", records[4]["display_name"])

        target_path = self.data_home / "correction-round-trip" / "last.db"
        target_arguments = ("--db", str(target_path))
        imported = self.run_cli(
            *target_arguments,
            "import",
            "--jsonl",
            input_text=exported.stdout,
        )
        self.assertEqual(0, imported.returncode, imported.stderr)
        self.assertEqual(
            exported.stdout,
            self.run_cli(*target_arguments, "export", "--jsonl").stdout,
        )
        repeated = self.run_cli(
            *target_arguments,
            "import",
            "--jsonl",
            input_text=exported.stdout,
        )
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual(
            "renamed  תחזוקה 🧰\n",
            self.run_cli(*target_arguments, "list").stdout,
        )
        audit = self.run_cli(
            *target_arguments,
            "history",
            "renamed",
            "--include-corrections",
            "--jsonl",
        )
        audit_records = [json.loads(line) for line in audit.stdout.splitlines()]
        self.assertEqual(2, sum(r["type"] == "event" for r in audit_records))
        self.assertEqual(
            2, sum(r["type"] == "correction" for r in audit_records)
        )
        doctor = json.loads(
            self.run_cli(*target_arguments, "doctor", "--jsonl").stdout
        )
        self.assertEqual(2, doctor["events"])
        self.assertEqual(2, doctor["corrections"])
        self.assertEqual(1, doctor["activities"])
        self.assertEqual("ok", doctor["conventions"])

    def test_batch_accepts_event_versions_and_idempotent_replay(self) -> None:
        old_event = {
            "record_version": 1,
            "type": "event",
            "id": "old-event",
            "name": "water-meter",
            "occurred_at": None,
            "occurred_on": "2024-01-01",
            "note": "initial reading",
        }
        current_event = {
            "record_version": 5,
            "type": "event",
            "id": "current-event",
            "name": "water-meter",
            "occurred_at": "2024-02-01T12:00:00.000000Z",
            "occurred_on": None,
            "note": "café meter",
            "reading_value": "42.5",
            "reading_unit": "gal",
        }
        stream = "".join(
            f"{json.dumps(record, ensure_ascii=False)}\n"
            for record in (old_event, current_event)
        )
        database_path = self.data_home / "batch" / "last.db"
        arguments = ("--db", str(database_path))

        empty = self.run_cli(*arguments, "batch", "--jsonl", input_text="")
        self.assertEqual(0, empty.returncode, empty.stderr)
        self.assertEqual("", empty.stdout)
        self.assertEqual("", empty.stderr)

        for _ in range(2):
            result = self.run_cli(
                *arguments, "batch", "--jsonl", input_text=stream
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertEqual("", result.stderr)

        exported = self.run_cli(*arguments, "export", "--jsonl")
        self.assertEqual(
            [
                {
                    **old_event,
                    "record_version": 5,
                    "reading_value": None,
                    "reading_unit": None,
                },
                current_event,
            ],
            [json.loads(line) for line in exported.stdout.splitlines()],
        )

    def test_batch_is_event_only_atomic_and_does_not_echo_input(self) -> None:
        valid_event = {
            "record_version": 5,
            "type": "event",
            "id": "rolled-back-event",
            "name": "private-log",
            "occurred_at": None,
            "occurred_on": "2024-01-01",
            "note": None,
            "reading_value": None,
            "reading_unit": None,
        }
        private_note = "secret-note-4831"
        non_event = {
            "record_version": 5,
            "type": "activity",
            "note": private_note,
        }
        stream = "".join(
            f"{json.dumps(record)}\n" for record in (valid_event, non_event)
        )
        database_path = self.data_home / "rejected-batch" / "last.db"
        arguments = ("--db", str(database_path))

        result = self.run_cli(
            *arguments, "batch", "--jsonl", input_text=stream
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual(
            "lastdone: batch error: line 2: expected event record\n",
            result.stderr,
        )
        self.assertNotIn(private_note, result.stderr)
        self.assertEqual("", self.run_cli(*arguments, "export", "--jsonl").stdout)

        invalid_json = self.run_cli(
            *arguments,
            "batch",
            "--jsonl",
            input_text=f"{json.dumps(valid_event)}\n{{{private_note}}}\n",
        )
        self.assertEqual(2, invalid_json.returncode)
        self.assertEqual(
            "lastdone: batch error: line 2: invalid JSON\n",
            invalid_json.stderr,
        )
        self.assertNotIn(private_note, invalid_json.stderr)
        self.assertEqual("", self.run_cli(*arguments, "export", "--jsonl").stdout)

    def test_decoder_failures_are_contained_and_atomic(self) -> None:
        private_note = "private-note-4831"
        valid_event = {
            "record_version": 5,
            "type": "event",
            "id": "rolled-back-event",
            "name": "private-log",
            "occurred_at": None,
            "occurred_on": "2024-01-01",
            "note": private_note,
            "reading_value": None,
            "reading_unit": None,
        }
        integer_limit = getattr(sys, "get_int_max_str_digits", lambda: 0)()
        malformed = (
            (
                "oversized-integer",
                "9" * max(10_000, integer_limit + 1),
                "invalid JSON" if integer_limit else "expected record object",
            ),
            ("deep-nesting", "[" * 10_000 + "]" * 10_000, "invalid JSON"),
        )
        for command in ("import", "batch"):
            for case, bad_line, detail in malformed:
                with self.subTest(command=command, case=case):
                    database_path = self.data_home / f"{command}-{case}" / "last.db"
                    arguments = ("--db", str(database_path))
                    stream = f"{json.dumps(valid_event)}\n{bad_line}\n"
                    result = self.run_cli(
                        *arguments,
                        command,
                        "--jsonl",
                        input_text=stream,
                    )
                    self.assertEqual(2, result.returncode)
                    self.assertEqual("", result.stdout)
                    self.assertEqual(
                        f"lastdone: {command} error: line 2: {detail}\n",
                        result.stderr,
                    )
                    self.assertLess(len(result.stderr), 200)
                    self.assertNotIn(private_note, result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    exported = self.run_cli(*arguments, "export", "--jsonl")
                    self.assertEqual(0, exported.returncode, exported.stderr)
                    self.assertEqual("", exported.stdout)

    def test_import_requires_events_before_valid_corrections(self) -> None:
        event = {
            "record_version": 2,
            "type": "event",
            "id": "target",
            "name": "name",
            "occurred_at": None,
            "occurred_on": "2024-01-01",
            "note": None,
        }
        correction = {
            "record_version": 2,
            "type": "correction",
            "id": "correction",
            "kind": "void",
            "target_id": "target",
            "replacement_id": None,
            "reason": "duplicate",
            "corrected_at": "2026-01-01T00:00:00.000000Z",
        }
        database_path = self.data_home / "ordered-import" / "last.db"
        arguments = ("--db", str(database_path))
        reversed_stream = f"{json.dumps(correction)}\n{json.dumps(event)}\n"
        rejected = self.run_cli(
            *arguments, "import", "--jsonl", input_text=reversed_stream
        )
        self.assertEqual(2, rejected.returncode)
        self.assertIn("line 1: correction references missing event", rejected.stderr)
        self.assertEqual("", self.run_cli(*arguments, "export", "--jsonl").stdout)

        valid_stream = f"{json.dumps(event)}\n{json.dumps(correction)}\n"
        accepted = self.run_cli(
            *arguments, "import", "--jsonl", input_text=valid_stream
        )
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        baseline = self.run_cli(*arguments, "export", "--jsonl").stdout
        conflicting_target = {
            **correction,
            "id": "second-correction",
            "reason": "another reason",
        }
        conflict = self.run_cli(
            *arguments,
            "import",
            "--jsonl",
            input_text=f"{json.dumps(conflicting_target)}\n",
        )
        self.assertEqual(2, conflict.returncode)
        self.assertIn("event already has a correction", conflict.stderr)
        self.assertEqual(
            baseline, self.run_cli(*arguments, "export", "--jsonl").stdout
        )

    def test_import_activity_is_idempotent_and_rejects_conflicts(self) -> None:
        activity = {
            "record_version": 3,
            "type": "activity",
            "name": "filter",
            "expected_interval_days": 90,
        }
        database_path = self.data_home / "activity-import" / "last.db"
        arguments = ("--db", str(database_path))
        stream = f"{json.dumps(activity)}\n"
        first = self.run_cli(
            *arguments, "import", "--jsonl", input_text=stream
        )
        self.assertEqual(0, first.returncode, first.stderr)
        baseline = self.run_cli(*arguments, "export", "--jsonl").stdout
        self.assertEqual(
            {
                **activity,
                "record_version": 5,
                "display_name": None,
            },
            json.loads(baseline),
        )
        repeated = self.run_cli(
            *arguments, "import", "--jsonl", input_text=stream
        )
        self.assertEqual(0, repeated.returncode, repeated.stderr)

        conflict = self.run_cli(
            *arguments,
            "import",
            "--jsonl",
            input_text=f"{json.dumps({**activity, 'expected_interval_days': 30})}\n",
        )
        self.assertEqual(2, conflict.returncode)
        self.assertIn("name conflicts with existing activity", conflict.stderr)
        self.assertEqual(
            baseline, self.run_cli(*arguments, "export", "--jsonl").stdout
        )

    def test_import_rolls_back_bad_lines_and_conflicting_ids(self) -> None:
        base = {
            "record_version": 1,
            "type": "event",
            "id": "original-id",
            "name": "original",
            "occurred_at": None,
            "occurred_on": "2024-02-29",
            "note": None,
        }
        database_path = self.data_home / "import" / "last.db"
        arguments = ("--db", str(database_path))
        initial_stream = json.dumps(base) + "\n"
        initial = self.run_cli(
            *arguments, "import", "--jsonl", input_text=initial_stream
        )
        self.assertEqual(0, initial.returncode, initial.stderr)
        baseline = self.run_cli(*arguments, "export", "--jsonl").stdout

        added = {**base, "id": "rolled-back-id", "name": "rolled-back"}
        conflict = {**base, "name": "different"}
        conflict_stream = "\n".join(
            (json.dumps(added), json.dumps(conflict), "")
        )
        conflict_result = self.run_cli(
            *arguments, "import", "--jsonl", input_text=conflict_stream
        )
        self.assertEqual(2, conflict_result.returncode)
        self.assertEqual("", conflict_result.stdout)
        self.assertIn("import error: line 2: ID conflicts", conflict_result.stderr)
        self.assertEqual(
            baseline, self.run_cli(*arguments, "export", "--jsonl").stdout
        )

        bad_json_stream = json.dumps(added) + "\n{not-json}\n"
        bad_json = self.run_cli(
            *arguments, "import", "--jsonl", input_text=bad_json_stream
        )
        self.assertEqual(2, bad_json.returncode)
        self.assertIn("import error: line 2: invalid JSON", bad_json.stderr)
        self.assertEqual(
            baseline, self.run_cli(*arguments, "export", "--jsonl").stdout
        )

    def test_import_rejects_invalid_record_shapes(self) -> None:
        base = {
            "record_version": 1,
            "type": "event",
            "id": "event-id",
            "name": "event",
            "occurred_at": None,
            "occurred_on": "2024-02-29",
            "note": None,
        }
        invalid_records = (
            "",
            "[" * 2_000 + "]" * 2_000,
            json.dumps({**base, "record_version": 5}),
            json.dumps({**base, "record_version": 6}),
            json.dumps(
                {
                    **base,
                    "record_version": 5,
                    "reading_value": "1",
                    "reading_unit": None,
                }
            ),
            json.dumps(
                {
                    **base,
                    "record_version": 5,
                    "reading_value": None,
                    "reading_unit": "mi",
                }
            ),
            json.dumps(
                {
                    **base,
                    "record_version": 5,
                    "reading_value": "1.0",
                    "reading_unit": "mi",
                }
            ),
            json.dumps(
                {
                    **base,
                    "record_version": 5,
                    "reading_value": 1,
                    "reading_unit": "mi",
                }
            ),
            json.dumps(
                {
                    **base,
                    "record_version": 5,
                    "reading_value": "1",
                    "reading_unit": "MI",
                }
            ),
            json.dumps({**base, "occurred_at": "2024-02-29T00:00:00.000000Z"}),
            json.dumps({**base, "occurred_on": "2026-02-29"}),
            json.dumps({**base, "name": "event\n"}),
            json.dumps({**base, "note": "\x00"}),
            json.dumps({key: value for key, value in base.items() if key != "note"}),
            json.dumps({**base, "extra": True}),
        )
        for index, record in enumerate(invalid_records):
            with self.subTest(index=index):
                database_path = self.data_home / f"invalid-{index}" / "last.db"
                result = self.run_cli(
                    "--db",
                    str(database_path),
                    "import",
                    "--jsonl",
                    input_text=f"{record}\n",
                )
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr.startswith("lastdone: import error:"))
                exported = self.run_cli(
                    "--db", str(database_path), "export", "--jsonl"
                )
                self.assertEqual("", exported.stdout)

        correction = {
            "record_version": 2,
            "type": "correction",
            "id": "correction-id",
            "kind": "void",
            "target_id": "event-id",
            "replacement_id": None,
            "reason": "duplicate",
            "corrected_at": "2026-01-01T00:00:00.000000Z",
        }
        invalid_corrections = (
            {**correction, "record_version": 1},
            {**correction, "kind": "edit"},
            {**correction, "reason": ""},
            {**correction, "reason": "reason\x1b"},
            {**correction, "corrected_at": "2026-01-01"},
            {**correction, "replacement_id": "replacement"},
            {
                **correction,
                "kind": "replace",
                "replacement_id": None,
            },
            {
                **correction,
                "kind": "replace",
                "replacement_id": "event-id",
            },
            {key: value for key, value in correction.items() if key != "reason"},
        )
        for index, record in enumerate(invalid_corrections):
            with self.subTest(correction=index):
                database_path = (
                    self.data_home / f"invalid-correction-{index}" / "last.db"
                )
                result = self.run_cli(
                    "--db",
                    str(database_path),
                    "import",
                    "--jsonl",
                    input_text=f"{json.dumps(record)}\n",
                )
                self.assertEqual(2, result.returncode)
                self.assertTrue(result.stderr.startswith("lastdone: import error:"))

        activity = {
            "record_version": 3,
            "type": "activity",
            "name": "filter",
            "expected_interval_days": 90,
        }
        invalid_activities = (
            {**activity, "record_version": 2},
            {**activity, "name": ""},
            {**activity, "expected_interval_days": True},
            {**activity, "expected_interval_days": 0},
            {**activity, "expected_interval_days": -1},
            {**activity, "expected_interval_days": 1.5},
            {**activity, "expected_interval_days": 9223372036854775808},
            {**activity, "extra": None},
            {
                key: value
                for key, value in activity.items()
                if key != "expected_interval_days"
            },
            {
                **activity,
                "record_version": 4,
                "display_name": "display\n",
            },
            {
                "record_version": 4,
                "type": "activity",
                "name": "filter",
                "expected_interval_days": None,
                "display_name": None,
            },
            {
                "record_version": 4,
                "type": "activity",
                "name": "filter",
                "expected_interval_days": None,
                "display_name": "",
            },
        )
        for index, record in enumerate(invalid_activities):
            with self.subTest(activity=index):
                database_path = (
                    self.data_home / f"invalid-activity-{index}" / "last.db"
                )
                result = self.run_cli(
                    "--db",
                    str(database_path),
                    "import",
                    "--jsonl",
                    input_text=f"{json.dumps(record)}\n",
                )
                self.assertEqual(2, result.returncode)
                self.assertTrue(result.stderr.startswith("lastdone: import error:"))

    def test_import_preserves_printable_deviations_for_doctor(self) -> None:
        name = "Cafe\u0301"
        event = {
            "record_version": 4,
            "type": "event",
            "id": "event-id",
            "name": name,
            "occurred_at": None,
            "occurred_on": "2024-02-29",
            "note": "note\u0301",
        }
        correction = {
            "record_version": 4,
            "type": "correction",
            "id": "correction-id",
            "kind": "void",
            "target_id": "event-id",
            "replacement_id": None,
            "reason": "reason\u0301",
            "corrected_at": "2026-01-01T00:00:00.000000Z",
        }
        activity = {
            "record_version": 4,
            "type": "activity",
            "name": name,
            "expected_interval_days": None,
            "display_name": "E\u0301lan 🧰",
        }
        stream = "".join(
            f"{json.dumps(record, ensure_ascii=False)}\n"
            for record in (event, correction, activity)
        )
        database_path = self.data_home / "deviations" / "last.db"
        arguments = ("--db", str(database_path))
        imported = self.run_cli(
            *arguments, "import", "--jsonl", input_text=stream
        )
        self.assertEqual(0, imported.returncode, imported.stderr)
        exported = self.run_cli(*arguments, "export", "--jsonl")
        self.assertEqual(
            [
                {
                    **event,
                    "record_version": 5,
                    "reading_value": None,
                    "reading_unit": None,
                },
                {**correction, "record_version": 5},
                {**activity, "record_version": 5},
            ],
            [json.loads(line) for line in exported.stdout.splitlines()],
        )
        before = database_path.read_bytes()

        doctor = self.run_cli(*arguments, "doctor", "--jsonl")
        self.assertEqual(3, doctor.returncode, doctor.stderr)
        report = json.loads(doctor.stdout)
        self.assertEqual("ok", report["parseability"])
        self.assertEqual("problems", report["conventions"])
        self.assertEqual("problems", report["status"])
        issues = "\n".join(report["convention_issues"])
        self.assertIn("invalid activity key", issues)
        self.assertIn("non-NFC activity key", issues)
        self.assertIn("non-NFC note", issues)
        self.assertIn("non-NFC display name", issues)
        self.assertIn("non-NFC correction reason", issues)
        self.assertEqual(before, database_path.read_bytes())

        rejected = self.run_cli(*arguments, "show", name)
        self.assertEqual(2, rejected.returncode)

    def test_doctor_reports_health_without_mutating_database(self) -> None:
        self.add_json("instant")
        self.add_json("dated", "--date", "2024-02-29")
        database_path = self.data_home / "last" / "last.db"
        before = database_path.read_bytes()

        human = self.run_cli("doctor")
        self.assertEqual(0, human.returncode, human.stderr)
        self.assertEqual("", human.stderr)
        self.assertIn(f"Database: {database_path.resolve()}\n", human.stdout)
        self.assertIn("Schema: ok\n", human.stdout)
        self.assertIn("Integrity: ok\n", human.stdout)
        self.assertIn("Parseability: ok\n", human.stdout)
        self.assertIn("Conventions: ok\n", human.stdout)
        self.assertIn(
            "Events: 2\nCorrections: 0\nActivities: 0\nStatus: ok\n",
            human.stdout,
        )

        machine = self.run_cli("doctor", "--jsonl")
        self.assertEqual(0, machine.returncode, machine.stderr)
        self.assertEqual("", machine.stderr)
        self.assertEqual(
            {
                "schema_version": 2,
                "type": "doctor",
                "database": str(database_path.resolve()),
                "database_schema_version": 5,
                "schema": "ok",
                "integrity": "ok",
                "permissions": "ok" if os.name == "posix" else "not-applicable",
                "parseability": "ok",
                "conventions": "ok",
                "convention_issues": [],
                "events": 2,
                "corrections": 0,
                "activities": 0,
                "status": "ok",
            },
            json.loads(machine.stdout),
        )
        self.assertEqual(before, database_path.read_bytes())
        self.assertFalse(database_path.with_name("last.db.v0.bak").exists())

    def test_doctor_reports_unhealthy_database_without_migrating(self) -> None:
        database_path = self.data_home / "legacy-doctor" / "last.db"
        database_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database_path)) as database:
            database.execute(
                """
                CREATE TABLE events (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    note TEXT
                )
                """
            )
            database.execute(
                """
                INSERT INTO events (id, name, occurred_at, note)
                VALUES ('legacy', 'legacy', '2026-01-01T00:00:00.000000Z', NULL)
                """
            )
            database.commit()
        if os.name == "posix":
            os.chmod(database_path, 0o644)
        before = database_path.read_bytes()

        result = self.run_cli(
            "--db", str(database_path), "doctor", "--jsonl"
        )
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(0, report["database_schema_version"])
        self.assertNotEqual("ok", report["schema"])
        self.assertEqual("ok", report["integrity"])
        if os.name == "posix":
            self.assertEqual("expected 0600, found 0644", report["permissions"])
        self.assertNotEqual("ok", report["parseability"])
        self.assertIsNone(report["events"])
        self.assertIsNone(report["corrections"])
        self.assertIsNone(report["activities"])
        self.assertEqual("problems", report["status"])
        self.assertEqual(before, database_path.read_bytes())
        self.assertFalse(database_path.with_name("last.db.v0.bak").exists())
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(0, database.execute("PRAGMA user_version").fetchone()[0])
            self.assertNotIn(
                "occurred_on",
                {row[1] for row in database.execute("PRAGMA table_info(events)")},
            )

    def test_doctor_does_not_create_missing_database(self) -> None:
        database_path = self.data_home / "missing" / "last.db"
        result = self.run_cli("--db", str(database_path), "doctor")
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertTrue(result.stderr.startswith("lastdone: storage error:"))
        self.assertFalse(database_path.exists())
        self.assertFalse(database_path.parent.exists())

    def test_run_boundary_accepts_fixed_time_and_database_path(self) -> None:
        now = datetime(
            2026,
            8,
            22,
            23,
            30,
            0,
            123456,
            tzinfo=timezone(-timedelta(hours=6)),
        )
        database_path = self.data_home / "injected" / "custom.db"
        error_output = io.StringIO()
        with redirect_stderr(error_output):
            with self.assertRaises(SystemExit) as error:
                RUN(
                    ("add", "future", "--date", "2026-08-23"),
                    now=now,
                    path=database_path,
                )
        self.assertEqual(2, error.exception.code)
        self.assertIn("DATE must not be in the future", error_output.getvalue())
        self.assertFalse(database_path.exists())

        output = io.StringIO()
        with redirect_stdout(output):
            status = RUN(
                ("add", "fixed", "--jsonl"), now=now, path=database_path
            )
        self.assertEqual(0, status)
        self.assertEqual(
            "2026-08-23T05:30:00.123456Z",
            json.loads(output.getvalue())["occurred_at"],
        )
        self.assertTrue(database_path.is_file())
        self.assertFalse((self.data_home / "last" / "last.db").exists())

    def test_duplicate_events_feed_show_and_newest_first_history(self) -> None:
        first = self.add_json("furnace-filter")
        second = self.add_json("furnace-filter")
        self.assertNotEqual(first["id"], second["id"])
        self.assertGreater(second["occurred_at"], first["occurred_at"])

        summary_result = self.run_cli("show", "furnace-filter", "--jsonl")
        self.assertEqual(0, summary_result.returncode, summary_result.stderr)
        summary = json.loads(summary_result.stdout)
        self.assertEqual(
            {
                "schema_version": 2,
                "type": "summary",
                "name": "furnace-filter",
                "display_name": None,
                "last": {
                    "occurred_at": second["occurred_at"],
                    "occurred_on": None,
                },
                "previous": {
                    "occurred_at": first["occurred_at"],
                    "occurred_on": None,
                },
                "interval_days": 0,
                "reading_value": None,
                "reading_unit": None,
                "reading_change": None,
                "occurrences": 2,
            },
            summary,
        )

        human_summary = self.run_cli("show", "furnace-filter")
        date = str(second["occurred_at"])[:10]
        self.assertEqual(
            "\n".join(
                (
                    "furnace-filter",
                    f"Last: {date}",
                    f"Previous: {date}",
                    "Interval: 0 days",
                    "Reading: -",
                    "Occurrences: 2",
                    "",
                )
            ),
            human_summary.stdout,
        )
        self.assertEqual("", human_summary.stderr)

        json_history = self.run_cli("history", "furnace-filter", "--jsonl")
        history = [json.loads(line) for line in json_history.stdout.splitlines()]
        self.assertEqual([second["id"], first["id"]], [item["id"] for item in history])
        self.assertTrue(all(item["type"] == "event" for item in history))

        human_history = self.run_cli("history", "furnace-filter")
        self.assertEqual(
            f"{second['id']}  {date}  -\n{first['id']}  {date}  -\n",
            human_history.stdout,
        )
        self.assertEqual("", human_history.stderr)

    def test_void_excludes_event_but_preserves_audit_history(self) -> None:
        older = self.add_json("filter", "--date", "2024-01-01")
        latest = self.add_json("filter", "--date", "2024-02-01")

        result = self.run_cli(
            "void", str(latest["id"]), "--reason", "duplicate", "--jsonl"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        correction = json.loads(result.stdout)
        self.assertEqual(2, correction["schema_version"])
        self.assertEqual("correction", correction["type"])
        self.assertEqual("void", correction["kind"])
        self.assertEqual(latest["id"], correction["target_id"])
        self.assertIsNone(correction["replacement_id"])
        self.assertEqual("duplicate", correction["reason"])
        UUID(correction["id"])
        self.assertRegex(correction["corrected_at"], TIMESTAMP)

        summary = json.loads(self.run_cli("show", "filter", "--jsonl").stdout)
        self.assertEqual(
            {"occurred_at": None, "occurred_on": "2024-01-01"},
            summary["last"],
        )
        self.assertEqual(1, summary["occurrences"])
        history = self.run_cli("history", "filter", "--jsonl")
        self.assertEqual([older["id"]], [json.loads(history.stdout)["id"]])
        self.assertEqual("filter\n", self.run_cli("list").stdout)

        audit = self.run_cli(
            "history", "filter", "--include-corrections", "--jsonl"
        )
        audit_records = [json.loads(line) for line in audit.stdout.splitlines()]
        self.assertEqual(
            [older["id"], latest["id"]],
            [record["id"] for record in audit_records[:2]],
        )
        self.assertEqual(correction, audit_records[2])
        human_audit = self.run_cli(
            "history", "filter", "--include-corrections"
        )
        self.assertIn(
            f"event {latest['id']} 2024-02-01 -\n", human_audit.stdout
        )
        self.assertIn(
            f"correction {correction['id']} void {latest['id']} - ",
            human_audit.stdout,
        )

        repeated = self.run_cli(
            "void", str(latest["id"]), "--reason", "again"
        )
        self.assertEqual(1, repeated.returncode)
        self.assertIn("event already corrected", repeated.stderr)
        missing = self.run_cli("void", "missing", "--reason", "unknown ID")
        self.assertEqual(1, missing.returncode)
        self.assertIn("event not found: missing", missing.stderr)

        void_last = self.run_cli(
            "void", str(older["id"]), "--reason", "never happened"
        )
        self.assertEqual(0, void_last.returncode, void_last.stderr)
        self.assertEqual("", self.run_cli("list").stdout)
        self.assertEqual(1, self.run_cli("show", "filter").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                2, database.execute("SELECT count(*) FROM events").fetchone()[0]
            )
            self.assertEqual(
                2, database.execute("SELECT count(*) FROM corrections").fetchone()[0]
            )

    def test_replace_preserves_fields_and_supports_correction_chains(self) -> None:
        target = self.add_json("old-name", "--date", "2024-02-29")
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute(
                "UPDATE events SET note = 'original note' WHERE id = ?",
                (target["id"],),
            )
            database.commit()

        incomplete = self.run_cli(
            "replace", str(target["id"]), "--reason", "no change"
        )
        self.assertEqual(2, incomplete.returncode)
        self.assertIn("requires at least one", incomplete.stderr)
        missing = self.run_cli(
            "replace", "missing", "--reason", "unknown", "--name", "new"
        )
        self.assertEqual(1, missing.returncode)
        self.assertIn("event not found: missing", missing.stderr)

        result = self.run_cli(
            "replace",
            str(target["id"]),
            "--reason",
            "rename activity",
            "--name",
            "new-name",
            "--jsonl",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        first_correction = json.loads(result.stdout)
        replacement_id = first_correction["replacement_id"]
        self.assertEqual("replace", first_correction["kind"])
        self.assertEqual(target["id"], first_correction["target_id"])
        UUID(replacement_id)

        old_history = self.run_cli("history", "old-name", "--jsonl")
        self.assertEqual(1, old_history.returncode)
        current = json.loads(
            self.run_cli("history", "new-name", "--jsonl").stdout
        )
        self.assertEqual(replacement_id, current["id"])
        self.assertEqual("2024-02-29", current["occurred_on"])
        self.assertEqual("original note", current["note"])

        old_audit = self.run_cli(
            "history", "old-name", "--include-corrections", "--jsonl"
        )
        old_records = [json.loads(line) for line in old_audit.stdout.splitlines()]
        self.assertEqual(
            [target["id"], replacement_id],
            [record["id"] for record in old_records[:2]],
        )
        self.assertEqual(first_correction, old_records[2])

        second = self.run_cli(
            "replace",
            replacement_id,
            "--reason",
            "correct date and clear note",
            "--date",
            "2024-03-01",
            "--note",
            "",
            "--jsonl",
        )
        self.assertEqual(0, second.returncode, second.stderr)
        second_correction = json.loads(second.stdout)
        self.assertEqual(replacement_id, second_correction["target_id"])
        final_event = json.loads(
            self.run_cli("history", "new-name", "--jsonl").stdout
        )
        self.assertEqual(second_correction["replacement_id"], final_event["id"])
        self.assertEqual("new-name", final_event["name"])
        self.assertEqual("2024-03-01", final_event["occurred_on"])
        self.assertEqual("", final_event["note"])

        audit = self.run_cli(
            "history", "new-name", "--include-corrections", "--jsonl"
        )
        records = [json.loads(line) for line in audit.stdout.splitlines()]
        self.assertEqual(3, sum(record["type"] == "event" for record in records))
        self.assertEqual(
            2, sum(record["type"] == "correction" for record in records)
        )

    def test_single_event_summary_uses_null_and_human_dashes(self) -> None:
        event = self.add_json("single")
        summary = self.run_cli("show", "single", "--jsonl")
        record = json.loads(summary.stdout)
        self.assertEqual(
            {"occurred_at": event["occurred_at"], "occurred_on": None},
            record["last"],
        )
        self.assertIsNone(record["previous"])
        self.assertIsNone(record["interval_days"])
        self.assertEqual(1, record["occurrences"])

        human = self.run_cli("show", "single")
        self.assertIn(
            "\nPrevious: -\nInterval: -\nReading: -\nOccurrences: 1\n",
            human.stdout,
        )

    def test_date_only_event_is_explicit_and_timezone_independent(self) -> None:
        event = self.add_json("leap-day", "--date", "2024-02-29")
        self.assertEqual(
            {
                "schema_version": 2,
                "type": "event",
                "id": event["id"],
                "name": "leap-day",
                "occurred_at": None,
                "occurred_on": "2024-02-29",
                "note": None,
                "reading_value": None,
                "reading_unit": None,
            },
            event,
        )
        machine_summary = self.run_cli("show", "leap-day", "--jsonl")
        self.assertEqual(
            {"occurred_at": None, "occurred_on": "2024-02-29"},
            json.loads(machine_summary.stdout)["last"],
        )

        for timezone_name in ("UTC", "Pacific/Honolulu", "Pacific/Kiritimati"):
            with self.subTest(timezone=timezone_name):
                environment = self.environment.copy()
                environment["TZ"] = timezone_name
                summary = self.run_cli(
                    "show", "leap-day", environment=environment
                )
                history = self.run_cli(
                    "history", "leap-day", environment=environment
                )
                self.assertEqual(
                    "leap-day\nLast: 2024-02-29\nPrevious: -\n"
                    "Interval: -\nReading: -\nOccurrences: 1\n",
                    summary.stdout,
                )
                self.assertEqual(
                    f"{event['id']}  2024-02-29  -\n", history.stdout
                )

    def test_mixed_precision_order_and_dst_interval_use_local_dates(self) -> None:
        date_event = self.add_json("mixed", "--date", "2026-03-08")
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.executemany(
                """
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    (
                        "mixed-instant",
                        "mixed",
                        "2026-03-09T01:00:00.000000Z",
                        None,
                        None,
                    ),
                    (
                        "dst-before",
                        "dst",
                        "2026-03-08T07:30:00.000000Z",
                        None,
                        None,
                    ),
                    (
                        "dst-after",
                        "dst",
                        "2026-03-09T06:30:00.000000Z",
                        None,
                        None,
                    ),
                ),
            )
            database.commit()

        denver = self.environment.copy()
        denver["TZ"] = "America/Denver"
        history = self.run_cli("history", "mixed", "--jsonl", environment=denver)
        records = [json.loads(line) for line in history.stdout.splitlines()]
        self.assertEqual(
            ["mixed-instant", date_event["id"]],
            [record["id"] for record in records],
        )

        summary = self.run_cli("show", "dst", "--jsonl", environment=denver)
        record = json.loads(summary.stdout)
        self.assertEqual(1, record["interval_days"])
        self.assertEqual(
            {
                "occurred_at": "2026-03-09T06:30:00.000000Z",
                "occurred_on": None,
            },
            record["last"],
        )
        human = self.run_cli("show", "dst", environment=denver)
        self.assertIn("\nLast: 2026-03-09\nPrevious: 2026-03-08\nInterval: 1 days\n", human.stdout)

    def test_schema_rejects_invalid_events(self) -> None:
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        valid_instant = "2026-01-01T00:00:00.000000Z"
        invalid_events = (
            (None, "name", valid_instant, None, None),
            ("", "name", valid_instant, None, None),
            ("empty-name", "", valid_instant, None, None),
            ("neither", "name", None, None, None),
            ("both", "name", valid_instant, "2026-01-01", None),
            ("short-time", "name", "2026-01-01T00:00:00Z", None, None),
            ("bad-time", "name", "2026-01-01T25:00:00.000000Z", None, None),
            ("bad-date", "name", None, "2026-02-29", None),
        )
        with closing(sqlite3.connect(database_path)) as database:
            for event in invalid_events:
                with self.subTest(event=event):
                    with self.assertRaises(sqlite3.IntegrityError):
                        database.execute(
                            """
                            INSERT INTO events
                                (id, name, occurred_at, occurred_on, note)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            event,
                        )
                    database.rollback()

            invalid_readings = (
                ("missing-unit", "1", None),
                ("missing-value", None, "mi"),
                ("empty-value", "", "mi"),
                ("leading-zero", "01", "mi"),
                ("leading-dot", ".1", "mi"),
                ("trailing-dot", "1.", "mi"),
                ("two-dots", "1.2.3", "mi"),
                ("trailing-zero", "1.0", "mi"),
                ("empty-unit", "1", ""),
                ("upper-unit", "1", "MI"),
                ("digit-unit", "1", "co2"),
                ("leading-hyphen", "1", "-mi"),
                ("trailing-hyphen", "1", "mi-"),
                ("double-hyphen", "1", "engine--h"),
            )
            for event_id, value, unit in invalid_readings:
                with self.subTest(reading=(value, unit)):
                    with self.assertRaises(sqlite3.IntegrityError):
                        database.execute(
                            """
                            INSERT INTO events
                                (id, name, occurred_at, occurred_on, note,
                                 reading_value, reading_unit)
                            VALUES (?, 'name', ?, NULL, NULL, ?, ?)
                            """,
                            (event_id, valid_instant, value, unit),
                        )
                    database.rollback()

            database.execute(
                """
                INSERT INTO events
                    (id, name, occurred_at, occurred_on, note,
                     reading_value, reading_unit)
                VALUES ('valid-reading', 'name', ?, NULL, NULL, '84221.5', 'mi')
                """,
                (valid_instant,),
            )
            database.execute(
                """
                INSERT INTO events
                    (id, name, occurred_at, occurred_on, note,
                     reading_value, reading_unit)
                VALUES ('coerced-reading', 'name', ?, NULL, NULL, 1, 'mi')
                """,
                (valid_instant,),
            )
            database.commit()
            self.assertEqual(
                ("1", "text"),
                database.execute(
                    """
                    SELECT reading_value, typeof(reading_value)
                    FROM events WHERE id = 'coerced-reading'
                    """
                ).fetchone(),
            )

    def test_schema_rejects_invalid_activities(self) -> None:
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        invalid_activities = (
            (None, 1, None),
            ("", 1, None),
            ("zero", 0, None),
            ("negative", -1, None),
            ("real", 1.5, None),
            ("text", "days", None),
            ("missing", None, None),
            ("empty-display", None, ""),
        )
        with closing(sqlite3.connect(database_path)) as database:
            for activity in invalid_activities:
                with self.subTest(activity=activity):
                    with self.assertRaises(sqlite3.IntegrityError):
                        database.execute(
                            """
                            INSERT INTO activities
                                (name, expected_interval_days, display_name)
                            VALUES (?, ?, ?)
                            """,
                            activity,
                        )
                    database.rollback()

    def test_schema_rejects_invalid_corrections(self) -> None:
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        timestamp = "2026-01-01T00:00:00.000000Z"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute("PRAGMA foreign_keys = ON")
            database.executemany(
                """
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES (?, 'name', ?, NULL, NULL)
                """,
                (
                    ("target", timestamp),
                    ("replacement", timestamp),
                    ("second-target", timestamp),
                ),
            )
            database.commit()
            invalid_corrections = (
                ("", "void", "target", None, "reason", timestamp),
                ("kind", "edit", "target", None, "reason", timestamp),
                ("void-link", "void", "target", "replacement", "reason", timestamp),
                ("replace-no-link", "replace", "target", None, "reason", timestamp),
                ("same", "replace", "target", "target", "reason", timestamp),
                ("empty-reason", "void", "target", None, "", timestamp),
                ("bad-time", "void", "target", None, "reason", "2026-01-01"),
                ("missing", "void", "missing", None, "reason", timestamp),
            )
            for correction in invalid_corrections:
                with self.subTest(correction=correction):
                    with self.assertRaises(sqlite3.IntegrityError):
                        database.execute(
                            """
                            INSERT INTO corrections
                                (id, kind, target_id, replacement_id, reason,
                                 corrected_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            correction,
                        )
                    database.rollback()

            database.execute(
                """
                INSERT INTO corrections
                    (id, kind, target_id, replacement_id, reason, corrected_at)
                VALUES ('valid', 'replace', 'target', 'replacement', 'reason', ?)
                """,
                (timestamp,),
            )
            database.commit()
            for correction in (
                ("same-target", "void", "target", None, "reason", timestamp),
                (
                    "same-replacement",
                    "replace",
                    "second-target",
                    "replacement",
                    "reason",
                    timestamp,
                ),
            ):
                with self.subTest(correction=correction):
                    with self.assertRaises(sqlite3.IntegrityError):
                        database.execute(
                            """
                            INSERT INTO corrections
                                (id, kind, target_id, replacement_id, reason,
                                 corrected_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            correction,
                        )
                    database.rollback()

    def test_version_one_database_adds_corrections_without_changing_events(
        self,
    ) -> None:
        event = self.add_json("preserved", "--date", "2024-02-29")
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            remove_reading_columns(database)
            database.execute("DROP TABLE activities")
            database.execute("DROP TABLE corrections")
            database.execute("PRAGMA user_version = 1")
            database.commit()

        result = self.run_cli("history", "preserved", "--jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(event, json.loads(result.stdout))
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                5, database.execute("PRAGMA user_version").fetchone()[0]
            )
            self.assertIsNotNone(
                database.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'corrections'"
                ).fetchone()
            )
            self.assertIsNotNone(
                database.execute(
                    "SELECT sql FROM sqlite_master WHERE name = 'activities'"
                ).fetchone()
            )

    def test_version_two_database_adds_activities_without_changing_history(
        self,
    ) -> None:
        event = self.add_json("preserved", "--date", "2024-02-29")
        correction = self.run_cli(
            "void", str(event["id"]), "--reason", "duplicate", "--jsonl"
        )
        self.assertEqual(0, correction.returncode, correction.stderr)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            remove_reading_columns(database)
            database.execute("DROP TABLE activities")
            database.execute("PRAGMA user_version = 2")
            database.commit()

        result = self.run_cli(
            "history", "preserved", "--include-corrections", "--jsonl"
        )
        self.assertEqual(0, result.returncode, result.stderr)
        records = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(event, records[0])
        self.assertEqual(json.loads(correction.stdout), records[1])
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                5, database.execute("PRAGMA user_version").fetchone()[0]
            )
            self.assertEqual(
                1, database.execute("SELECT count(*) FROM events").fetchone()[0]
            )
            self.assertEqual(
                1,
                database.execute("SELECT count(*) FROM corrections").fetchone()[0],
            )

    def test_version_three_activity_migration_preserves_interval_and_backup(
        self,
    ) -> None:
        self.assertEqual(
            0, self.run_cli("set", "preserved", "--every", "90d").returncode
        )
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            remove_reading_columns(database)
            database.executescript(
                """
                DROP TABLE activities;
                CREATE TABLE activities (
                    name TEXT NOT NULL PRIMARY KEY
                        CONSTRAINT activities_name_nonempty
                        CHECK (length(name) > 0),
                    expected_interval_days INTEGER NOT NULL
                        CONSTRAINT activities_interval_positive CHECK (
                            typeof(expected_interval_days) = 'integer'
                            AND expected_interval_days > 0
                        )
                );
                INSERT INTO activities (name, expected_interval_days)
                VALUES ('preserved', 90);
                PRAGMA user_version = 3;
                """
            )
            database.commit()

        result = self.run_cli("list")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("preserved\n", result.stdout)
        backup_path = database_path.with_name("last.db.v3.bak")
        self.assertTrue(backup_path.is_file())
        if os.name == "posix":
            self.assertEqual(0o600, stat.S_IMODE(backup_path.stat().st_mode))
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                5, database.execute("PRAGMA user_version").fetchone()[0]
            )
            self.assertEqual(
                ("preserved", 90, None),
                database.execute(
                    """
                    SELECT name, expected_interval_days, display_name
                    FROM activities
                    """
                ).fetchone(),
            )
        with closing(sqlite3.connect(backup_path)) as backup:
            self.assertEqual(
                3, backup.execute("PRAGMA user_version").fetchone()[0]
            )
            self.assertEqual(
                ("name", "expected_interval_days"),
                tuple(
                    row[1] for row in backup.execute("PRAGMA table_info(activities)")
                ),
            )
            self.assertEqual(
                ("preserved", 90),
                backup.execute("SELECT * FROM activities").fetchone(),
            )
        before = backup_path.read_bytes()
        self.assertEqual(0, self.run_cli("list").returncode)
        self.assertEqual(before, backup_path.read_bytes())

    def test_version_four_migration_adds_null_readings_without_backup(
        self,
    ) -> None:
        event = self.add_json("preserved", "--date", "2024-02-29")
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            remove_reading_columns(database)
            database.execute("PRAGMA user_version = 4")
            database.commit()

        result = self.run_cli("history", "preserved", "--jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(event, json.loads(result.stdout))
        self.assertFalse(database_path.with_name("last.db.v4.bak").exists())
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                5, database.execute("PRAGMA user_version").fetchone()[0]
            )
            self.assertEqual(
                (None, None),
                database.execute(
                    "SELECT reading_value, reading_unit FROM events"
                ).fetchone(),
            )

    def test_legacy_database_migrates_without_changing_instant(self) -> None:
        database_path = self.data_home / "last" / "last.db"
        database_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database_path)) as database:
            database.executescript(
                """
                CREATE TABLE events (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    note TEXT
                );
                CREATE INDEX idx_events_name_occurred_at
                ON events(name, occurred_at DESC);
                INSERT INTO events (id, name, occurred_at, note)
                VALUES ('legacy-id', 'legacy',
                        '2026-08-21T20:32:00.000000Z', 'preserved');
                """
            )
            database.commit()

        result = self.run_cli("history", "legacy", "--jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            {
                "schema_version": 2,
                "type": "event",
                "id": "legacy-id",
                "name": "legacy",
                "occurred_at": "2026-08-21T20:32:00.000000Z",
                "occurred_on": None,
                "note": "preserved",
                "reading_value": None,
                "reading_unit": None,
            },
            json.loads(result.stdout),
        )

        backup_path = database_path.with_name("last.db.v0.bak")
        self.assertTrue(backup_path.is_file())
        if os.name == "posix":
            self.assertEqual(0o600, stat.S_IMODE(backup_path.stat().st_mode))
        with closing(sqlite3.connect(backup_path)) as backup:
            backup_version = backup.execute("PRAGMA user_version").fetchone()[0]
            backup_columns = {
                row[1] for row in backup.execute("PRAGMA table_info(events)")
            }
            backup_row = backup.execute(
                "SELECT id, name, occurred_at, note FROM events"
            ).fetchone()
        self.assertEqual(0, backup_version)
        self.assertNotIn("occurred_on", backup_columns)
        self.assertEqual(
            (
                "legacy-id",
                "legacy",
                "2026-08-21T20:32:00.000000Z",
                "preserved",
            ),
            backup_row,
        )

        with closing(sqlite3.connect(database_path)) as database:
            version = database.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                row[1] for row in database.execute("PRAGMA table_info(events)")
            }
            indexes = {
                row[1] for row in database.execute("PRAGMA index_list(events)")
            }
            table_sql = database.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'events'"
            ).fetchone()[0]
        self.assertEqual(5, version)
        self.assertIn("occurred_on", columns)
        self.assertIn("idx_events_name", indexes)
        self.assertNotIn("idx_events_name_occurred_at", indexes)
        self.assertIn("events_occurred_on_valid", table_sql)

    def test_unversioned_precision_database_migrates_date_event(self) -> None:
        database_path = self.data_home / "last" / "last.db"
        database_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database_path)) as database:
            database.executescript(
                """
                CREATE TABLE events (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    occurred_at TEXT,
                    occurred_on TEXT,
                    note TEXT,
                    CHECK ((occurred_at IS NOT NULL) <>
                           (occurred_on IS NOT NULL))
                );
                CREATE INDEX idx_events_name ON events(name);
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES ('date-id', 'date-event', NULL, '2024-02-29', NULL);
                """
            )
            database.commit()

        result = self.run_cli("history", "date-event", "--jsonl")
        self.assertEqual(0, result.returncode, result.stderr)
        record = json.loads(result.stdout)
        self.assertIsNone(record["occurred_at"])
        self.assertEqual("2024-02-29", record["occurred_on"])
        self.assertTrue(database_path.with_name("last.db.v0.bak").is_file())
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                5, database.execute("PRAGMA user_version").fetchone()[0]
            )

    def test_invalid_legacy_data_rolls_back_and_keeps_backup(self) -> None:
        database_path = self.data_home / "last" / "last.db"
        database_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database_path)) as database:
            database.executescript(
                """
                CREATE TABLE events (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    occurred_at TEXT,
                    occurred_on TEXT,
                    note TEXT,
                    CHECK ((occurred_at IS NOT NULL) <>
                           (occurred_on IS NOT NULL))
                );
                CREATE INDEX idx_events_name ON events(name);
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES ('bad-date', 'invalid', NULL, '2026-02-29', NULL);
                """
            )
            database.commit()

        result = self.run_cli("list")
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertTrue(result.stderr.startswith("lastdone: storage error:"))
        self.assertNotIn("Traceback", result.stderr)
        self.assertTrue(database_path.with_name("last.db.v0.bak").is_file())

        with closing(sqlite3.connect(database_path)) as database:
            version = database.execute("PRAGMA user_version").fetchone()[0]
            columns = {
                row[1] for row in database.execute("PRAGMA table_info(events)")
            }
            names = {
                row[0]
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            stored_date = database.execute(
                "SELECT occurred_on FROM events WHERE id = 'bad-date'"
            ).fetchone()[0]
        self.assertEqual(0, version)
        self.assertIn("occurred_on", columns)
        self.assertNotIn("events_legacy", names)
        self.assertEqual("2026-02-29", stored_date)

    def test_unrecognized_unversioned_schema_is_preserved(self) -> None:
        database_path = self.data_home / "last" / "last.db"
        database_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database_path)) as database:
            database.execute(
                "CREATE TABLE events (id TEXT PRIMARY KEY, unexpected TEXT)"
            )
            database.execute(
                "INSERT INTO events (id, unexpected) VALUES ('kept', 'value')"
            )
            database.commit()

        result = self.run_cli("list")
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("unrecognized unversioned events schema", result.stderr)
        self.assertTrue(database_path.with_name("last.db.v0.bak").is_file())
        with closing(sqlite3.connect(database_path)) as database:
            row = database.execute("SELECT id, unexpected FROM events").fetchone()
            version = database.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(("kept", "value"), row)
        self.assertEqual(0, version)

    def test_newer_schema_version_is_rejected_without_downgrade(self) -> None:
        self.assertEqual(0, self.run_cli("add", "preserved").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute("PRAGMA user_version = 99")
            database.commit()

        result = self.run_cli("list")
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("newer than supported", result.stderr)
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                99, database.execute("PRAGMA user_version").fetchone()[0]
            )
            self.assertEqual(
                1, database.execute("SELECT count(*) FROM events").fetchone()[0]
            )

    def test_declared_schema_drift_is_rejected(self) -> None:
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute("DROP INDEX idx_events_name")
            database.commit()

        result = self.run_cli("list")
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("schema does not match its version", result.stderr)
        with closing(sqlite3.connect(database_path)) as database:
            indexes = {
                row[1] for row in database.execute("PRAGMA index_list(events)")
            }
        self.assertNotIn("idx_events_name", indexes)

    def test_integrity_check_rejects_bypassed_constraint(self) -> None:
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute("PRAGMA ignore_check_constraints = ON")
            database.execute(
                """
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES ('bypassed', 'invalid', NULL, '2026-02-29', NULL)
                """
            )
            database.commit()

        doctor = self.run_cli("doctor", "--jsonl")
        self.assertEqual(3, doctor.returncode)
        self.assertEqual("", doctor.stderr)
        report = json.loads(doctor.stdout)
        self.assertEqual("ok", report["schema"])
        self.assertIsInstance(report["integrity"], str)
        self.assertNotEqual("ok", report["parseability"])
        self.assertIsNone(report["events"])
        self.assertIsNone(report["corrections"])
        self.assertIsNone(report["activities"])
        self.assertEqual("problems", report["status"])

        result = self.run_cli("list")
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("integrity check failed", result.stderr)

    def test_foreign_key_check_rejects_broken_correction_link(self) -> None:
        event = self.add_json("linked")
        correction = self.run_cli(
            "void", str(event["id"]), "--reason", "duplicate", "--jsonl"
        )
        self.assertEqual(0, correction.returncode, correction.stderr)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute(
                "UPDATE corrections SET target_id = 'missing' WHERE id = ?",
                (json.loads(correction.stdout)["id"],),
            )
            database.commit()

        doctor = self.run_cli("doctor", "--jsonl")
        self.assertEqual(3, doctor.returncode)
        report = json.loads(doctor.stdout)
        self.assertEqual("ok", report["schema"])
        self.assertEqual("ok", report["integrity"])
        self.assertEqual("foreign key check failed", report["parseability"])
        self.assertIsNone(report["events"])
        self.assertIsNone(report["corrections"])
        self.assertIsNone(report["activities"])

        result = self.run_cli("list")
        self.assertEqual(3, result.returncode)
        self.assertIn("database foreign key check failed", result.stderr)

    def test_set_upserts_interval_and_lists_metadata_only_activity(self) -> None:
        silent = self.run_cli("set", "filter", "--every", "90d")
        self.assertEqual(0, silent.returncode, silent.stderr)
        self.assertEqual("", silent.stdout)
        self.assertEqual("", silent.stderr)
        self.assertEqual("filter\n", self.run_cli("list").stdout)
        listed = json.loads(self.run_cli("list", "--jsonl").stdout)
        self.assertEqual(
            {
                "schema_version": 2,
                "type": "activity",
                "name": "filter",
                "expected_interval_days": 90,
                "display_name": None,
            },
            listed,
        )

        updated = self.run_cli(
            "set", "filter", "--every", "30d", "--jsonl"
        )
        self.assertEqual(0, updated.returncode, updated.stderr)
        self.assertEqual(30, json.loads(updated.stdout)["expected_interval_days"])
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            self.assertEqual(
                [("filter", 30)],
                database.execute(
                    "SELECT name, expected_interval_days FROM activities"
                ).fetchall(),
            )

    def test_display_name_is_normalized_and_used_in_human_output(self) -> None:
        decomposed = "Cafe\u0301 🏠 תחזוקה"
        normalized = "Café 🏠 תחזוקה"
        configured = self.run_cli(
            "set",
            "coffee-clean",
            "--display-name",
            decomposed,
            "--jsonl",
        )
        self.assertEqual(0, configured.returncode, configured.stderr)
        record = json.loads(configured.stdout)
        self.assertIn(normalized, configured.stdout)
        self.assertEqual(normalized, record["display_name"])
        self.assertIsNone(record["expected_interval_days"])
        self.assertEqual(
            f"coffee-clean  {normalized}\n", self.run_cli("list").stdout
        )
        self.assertEqual(
            normalized,
            json.loads(self.run_cli("list", "--jsonl").stdout)["display_name"],
        )
        self.assertEqual("", self.run_cli("due", "--jsonl").stdout)

        event = self.run_cli("add", "coffee-clean", "--date", "2026-08-20")
        self.assertEqual(0, event.returncode, event.stderr)
        human = self.run_cli("show", "coffee-clean")
        self.assertTrue(human.stdout.startswith(f"{normalized} [coffee-clean]\n"))
        summary = json.loads(
            self.run_cli("show", "coffee-clean", "--jsonl").stdout
        )
        self.assertEqual(normalized, summary["display_name"])

        interval = self.run_cli(
            "set", "coffee-clean", "--every", "30d", "--jsonl"
        )
        self.assertEqual(0, interval.returncode, interval.stderr)
        updated = json.loads(interval.stdout)
        self.assertEqual(30, updated["expected_interval_days"])
        self.assertEqual(normalized, updated["display_name"])
        due = json.loads(self.run_cli("due", "--jsonl").stdout)
        self.assertEqual(normalized, due["display_name"])
        self.assertIn(
            f"coffee-clean  {normalized}  ", self.run_cli("due").stdout
        )

    def test_replacement_human_text_is_normalized_to_nfc(self) -> None:
        original = self.add_json("normalize", "--date", "2026-08-20")
        replaced = self.run_cli(
            "replace",
            str(original["id"]),
            "--reason",
            "re\u0301ason",
            "--note",
            "Cafe\u0301",
            "--jsonl",
        )
        self.assertEqual(0, replaced.returncode, replaced.stderr)
        correction = json.loads(replaced.stdout)
        self.assertEqual("réason", correction["reason"])
        history = json.loads(self.run_cli("history", "normalize", "--jsonl").stdout)
        self.assertEqual("Café", history["note"])

    def test_due_reports_all_states_and_filters_only_overdue(self) -> None:
        intervals = {
            "due-today": 2,
            "future": 2,
            "never": 7,
            "not-due": 3,
            "overdue": 2,
        }
        for name, interval in intervals.items():
            result = self.run_cli("set", name, "--every", f"{interval}d")
            self.assertEqual(0, result.returncode, result.stderr)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.executemany(
                """
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES (?, ?, NULL, ?, NULL)
                """,
                (
                    ("due-id", "due-today", "2026-08-20"),
                    ("future-id", "future", "2026-08-23"),
                    ("not-due-id", "not-due", "2026-08-20"),
                    ("overdue-id", "overdue", "2026-08-19"),
                ),
            )
            database.commit()

        now = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)
        output = io.StringIO()
        with redirect_stdout(output):
            status = RUN(("due", "--jsonl"), now=now, path=database_path)
        self.assertEqual(0, status)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(list(intervals), [record["name"] for record in records])
        self.assertEqual(
            {
                "due-today": "due-today",
                "future": "future-dated",
                "never": "never-recorded",
                "not-due": "not-due",
                "overdue": "overdue",
            },
            {record["name"]: record["state"] for record in records},
        )
        self.assertEqual(
            {
                "due-today": "2026-08-22",
                "future": "2026-08-25",
                "never": None,
                "not-due": "2026-08-23",
                "overdue": "2026-08-21",
            },
            {record["name"]: record["due_on"] for record in records},
        )
        self.assertIsNone(records[2]["last"])

        human = io.StringIO()
        with redirect_stdout(human):
            status = RUN(("due",), now=now, path=database_path)
        self.assertEqual(0, status)
        self.assertIn(
            "never  -  -  7d  -  NEVER-RECORDED\n", human.getvalue()
        )
        overdue = io.StringIO()
        with redirect_stdout(overdue):
            status = RUN(
                ("due", "--overdue", "--jsonl"),
                now=now,
                path=database_path,
            )
        self.assertEqual(0, status)
        filtered = [json.loads(line) for line in overdue.getvalue().splitlines()]
        self.assertEqual(["overdue"], [record["name"] for record in filtered])

    def test_due_uses_calendar_dates_timezone_and_effective_history(self) -> None:
        self.assertEqual(
            0, self.run_cli("set", "leap", "--every", "365d").returncode
        )
        self.assertEqual(
            0, self.run_cli("add", "leap", "--date", "2024-02-29").returncode
        )
        self.assertEqual(
            0, self.run_cli("set", "dst", "--every", "1d").returncode
        )
        original = self.add_json("corrected", "--date", "2026-01-01")
        self.assertEqual(
            0, self.run_cli("set", "corrected", "--every", "1d").returncode
        )
        replaced = self.run_cli(
            "replace",
            str(original["id"]),
            "--reason",
            "wrong date",
            "--date",
            "2026-03-08",
        )
        self.assertEqual(0, replaced.returncode, replaced.stderr)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute(
                """
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES ('dst-id', 'dst', '2026-03-08T07:30:00.000000Z',
                        NULL, NULL)
                """
            )
            database.commit()

        previous_timezone = os.environ.get("TZ")
        os.environ["TZ"] = "America/Denver"
        time.tzset()
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                status = RUN(
                    ("due", "--jsonl"),
                    now=datetime(
                        2026,
                        3,
                        9,
                        12,
                        tzinfo=timezone(-timedelta(hours=6)),
                    ),
                    path=database_path,
                )
        finally:
            if previous_timezone is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous_timezone
            time.tzset()
        self.assertEqual(0, status)
        records = {
            record["name"]: record
            for record in map(json.loads, output.getvalue().splitlines())
        }
        self.assertEqual("2025-02-28", records["leap"]["due_on"])
        self.assertEqual("2026-03-09", records["dst"]["due_on"])
        self.assertEqual("due-today", records["dst"]["state"])
        self.assertEqual("2026-03-09", records["corrected"]["due_on"])
        self.assertEqual("due-today", records["corrected"]["state"])

    def test_due_handles_interval_beyond_calendar_range(self) -> None:
        self.assertEqual(
            0, self.run_cli("set", "maximum", "--every", "1d").returncode
        )
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.execute(
                """
                INSERT INTO events (id, name, occurred_at, occurred_on, note)
                VALUES ('maximum-id', 'maximum', NULL, '9999-12-31', NULL)
                """
            )
            database.commit()
        output = io.StringIO()
        with redirect_stdout(output):
            status = RUN(
                ("due", "--jsonl"),
                now=datetime(9999, 12, 31, tzinfo=timezone.utc),
                path=database_path,
            )
        self.assertEqual(0, status)
        record = json.loads(output.getvalue())
        self.assertEqual("not-due", record["state"])
        self.assertIsNone(record["due_on"])

    def test_list_is_distinct_and_ordered_by_utf8_bytes(self) -> None:
        names = ["zeta", "alpha", "alpha-2", "eclair", "alpha"]
        for name in names:
            result = self.run_cli("add", name)
            self.assertEqual(0, result.returncode, result.stderr)

        expected = sorted(set(names), key=lambda name: name.encode("utf-8"))
        human = self.run_cli("list")
        self.assertEqual("".join(f"{name}\n" for name in expected), human.stdout)
        self.assertEqual("", human.stderr)

        jsonl = self.run_cli("list", "--jsonl")
        records = [json.loads(line) for line in jsonl.stdout.splitlines()]
        self.assertEqual(expected, [record["name"] for record in records])
        self.assertTrue(
            all(
                record["schema_version"] == 2 and record["type"] == "activity"
                and record["expected_interval_days"] is None
                and record["display_name"] is None
                for record in records
            )
        )

    def test_storage_failure_uses_exit_three_and_stderr(self) -> None:
        invalid_data_home = self.data_home / "not-a-directory"
        invalid_data_home.write_text("file", encoding="utf-8")
        environment = self.environment.copy()
        environment["XDG_DATA_HOME"] = str(invalid_data_home)

        result = self.run_cli("list", environment=environment)
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertTrue(result.stderr.startswith("lastdone: storage error:"))
        self.assertNotIn("Traceback", result.stderr)

    def test_concurrent_first_adds_wait_and_preserve_both_events(self) -> None:
        database_path = self.data_home / "last" / "last.db"
        database_path.parent.mkdir(parents=True)
        with closing(sqlite3.connect(database_path)) as locker:
            locker.execute("BEGIN IMMEDIATE")
            processes = [
                subprocess.Popen(
                    [str(CLI), "add", "concurrent", "--jsonl"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=self.environment,
                )
                for _ in range(2)
            ]
            time.sleep(0.2)
            blocked_states = [process.poll() for process in processes]
            locker.rollback()

        results = [process.communicate(timeout=10) for process in processes]
        self.assertEqual([None, None], blocked_states)
        for process, (stdout, stderr) in zip(processes, results):
            self.assertEqual(0, process.returncode, stderr)
            self.assertEqual("", stderr)
            self.assertEqual("concurrent", json.loads(stdout)["name"])

        history_result = self.run_cli("history", "concurrent", "--jsonl")
        self.assertEqual(0, history_result.returncode, history_result.stderr)
        history = [json.loads(line) for line in history_result.stdout.splitlines()]
        self.assertEqual(2, len(history))
        self.assertEqual(2, len({event["id"] for event in history}))

    def test_lock_timeout_is_actionable_storage_error(self) -> None:
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as locker:
            locker.execute("BEGIN IMMEDIATE")
            result = self.run_cli("add", "blocked")
            locker.rollback()

        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual(
            "lastdone: storage error: database is busy after 5 seconds; "
            "retry the command\n",
            result.stderr,
        )
        self.assertNotIn("Traceback", result.stderr)

    def test_closed_pipe_exits_cleanly(self) -> None:
        self.assertEqual(0, self.run_cli("add", "seed").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            database.executemany(
                "INSERT INTO events (id, name, occurred_at, note) VALUES (?, ?, ?, ?)",
                (
                    (
                        f"pipe-{index}",
                        f"activity-{index:05d}",
                        "2026-08-21T00:00:00.000000Z",
                        None,
                    )
                    for index in range(20_000)
                ),
            )
            database.commit()

        process = subprocess.Popen(
            [str(CLI), "list"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        self.assertTrue(process.stdout.readline())
        process.stdout.close()
        stderr = process.stderr.read()
        process.stderr.close()
        self.assertEqual(0, process.wait(timeout=10))
        self.assertEqual(b"", stderr)


if __name__ == "__main__":
    unittest.main()
