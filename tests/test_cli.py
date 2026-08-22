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
import tempfile
import unittest
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "lastdone"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
RUN = runpy.run_path(str(CLI), run_name="lastdone_test")["run"]


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
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CLI), *arguments],
            capture_output=True,
            text=True,
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
        self.assertEqual("lastdone 0.3.0\n", version.stdout)
        self.assertEqual("", version.stderr)

        help_result = self.run_cli("--help")
        self.assertEqual(0, help_result.returncode)
        self.assertIn("usage: lastdone", help_result.stdout)
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
        ):
            with self.subTest(arguments=arguments):
                result = self.run_cli(*arguments)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertTrue(result.stderr.startswith("lastdone: error:"))
                self.assertNotIn("Traceback", result.stderr)

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
        if os.name == "posix":
            self.assertEqual(0o700, stat.S_IMODE(database_path.parent.stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE(database_path.stat().st_mode))

        with closing(sqlite3.connect(database_path)) as database:
            version = database.execute("PRAGMA user_version").fetchone()[0]
            table_sql = database.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'events'"
            ).fetchone()[0]
        self.assertEqual(1, version)
        self.assertIn("events_occurred_at_valid", table_sql)

        second = self.run_cli("list")
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertFalse(database_path.with_name("last.db.v0.bak").exists())

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
            },
            event,
        )
        UUID(str(event["id"]))
        self.assertRegex(str(event["occurred_at"]), TIMESTAMP)

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
                "last": {
                    "occurred_at": second["occurred_at"],
                    "occurred_on": None,
                },
                "previous": {
                    "occurred_at": first["occurred_at"],
                    "occurred_on": None,
                },
                "interval_days": 0,
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
        self.assertEqual(f"{date}\n{date}\n", human_history.stdout)
        self.assertEqual("", human_history.stderr)

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
        self.assertIn("\nPrevious: -\nInterval: -\nOccurrences: 1\n", human.stdout)

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
                    "Interval: -\nOccurrences: 1\n",
                    summary.stdout,
                )
                self.assertEqual("2024-02-29\n", history.stdout)

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
        self.assertEqual(1, version)
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
                1, database.execute("PRAGMA user_version").fetchone()[0]
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

        result = self.run_cli("list")
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("integrity check failed", result.stderr)

    def test_list_is_distinct_and_ordered_by_utf8_bytes(self) -> None:
        names = ["zeta", "alpha", "Alpha", "éclair", "alpha"]
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
