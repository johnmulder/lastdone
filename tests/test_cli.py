from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import unittest
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "lastdone"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


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
        self.assertEqual("lastdone 0.2.0\n", version.stdout)
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

    def test_schema_requires_exactly_one_occurrence_value(self) -> None:
        self.assertEqual(0, self.run_cli("list").returncode)
        database_path = self.data_home / "last" / "last.db"
        with closing(sqlite3.connect(database_path)) as database:
            with self.assertRaises(sqlite3.IntegrityError):
                database.execute(
                    """
                    INSERT INTO events (id, name, occurred_at, occurred_on, note)
                    VALUES ('neither', 'invalid', NULL, NULL, NULL)
                    """
                )
            database.rollback()
            with self.assertRaises(sqlite3.IntegrityError):
                database.execute(
                    """
                    INSERT INTO events (id, name, occurred_at, occurred_on, note)
                    VALUES ('both', 'invalid', '2026-01-01T00:00:00.000000Z',
                            '2026-01-01', NULL)
                    """
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
            },
            json.loads(result.stdout),
        )

        with closing(sqlite3.connect(database_path)) as database:
            columns = {
                row[1] for row in database.execute("PRAGMA table_info(events)")
            }
            indexes = {
                row[1] for row in database.execute("PRAGMA index_list(events)")
            }
            table_sql = database.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'events'"
            ).fetchone()[0]
        self.assertIn("occurred_on", columns)
        self.assertIn("idx_events_name", indexes)
        self.assertNotIn("idx_events_name_occurred_at", indexes)
        self.assertIn("CHECK", table_sql)

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
