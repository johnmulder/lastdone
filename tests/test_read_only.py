from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


CLI = Path(__file__).resolve().parents[1] / "lastdone"


def snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    result = {}
    for path in (root, *sorted(root.rglob("*"))):
        info = path.lstat()
        result[str(path.relative_to(root))] = (
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
            info.st_dev,
            info.st_ino,
            info.st_nlink,
            path.read_bytes() if stat.S_ISREG(info.st_mode) else None,
        )
    return result


class ReadOnlyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.database = self.source / "last.db"
        self.environment = dict(
            os.environ,
            TZ="UTC",
            HOME=str(self.root / "unused-home"),
            LASTDONE_DB=str(self.root / "unused-environment.db"),
            XDG_DATA_HOME=str(self.root / "unused-xdg"),
        )
        self.cli("add", "fixture", "--date", "2020-01-01")
        self.cli(
            "set", "fixture", "--every", "14d", "--display-name", "Fixture"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def cli(
        self,
        *args: str,
        read_only: bool = False,
        database: Path | None = None,
        input_text: str | None = None,
    ):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(CLI),
                *(["--read-only"] if read_only else []),
                "--db",
                str(database or self.database),
                *args,
            ],
            capture_output=True,
            text=True,
            input=input_text,
            env=self.environment,
            check=False,
            timeout=10,
        )
        return result

    def test_read_only_queries_preserve_bytes_permissions_and_metadata(self):
        queries = (
            ("list", "--jsonl"),
            ("show", "fixture", "--jsonl"),
            ("history", "fixture", "--jsonl"),
            ("history", "fixture", "--include-corrections", "--jsonl"),
            ("due", "--jsonl"),
            ("export", "--jsonl"),
        )
        for query in queries:
            with self.subTest(query=query):
                ordinary = self.cli(*query)
                self.assertEqual(0, ordinary.returncode, ordinary.stderr)
                self.database.chmod(0o644)
                before = snapshot(self.source)
                observed = self.cli(*query, read_only=True)
                self.assertEqual(0, observed.returncode, observed.stderr)
                self.assertEqual(ordinary.stdout, observed.stdout)
                self.assertEqual("", observed.stderr)
                self.assertEqual(before, snapshot(self.source))
        self.assertFalse((self.root / "unused-home").exists())
        self.assertFalse((self.root / "unused-environment.db").exists())
        self.assertFalse((self.root / "unused-xdg").exists())

    def test_read_only_missing_store_never_initializes(self):
        missing = self.root / "missing" / "last.db"
        for query in (
            ("list", "--jsonl"),
            ("export", "--jsonl"),
            ("doctor", "--jsonl"),
        ):
            with self.subTest(query=query):
                result = self.cli(*query, read_only=True, database=missing)
                self.assertEqual(3, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertFalse(missing.parent.exists())

    def test_read_only_empty_current_store_is_successful_empty_evidence(self):
        empty = self.source / "empty.db"
        self.assertEqual(0, self.cli("list", database=empty).returncode)
        before = snapshot(self.source)
        for query in (("list", "--jsonl"), ("export", "--jsonl")):
            result = self.cli(*query, read_only=True, database=empty)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
        self.assertEqual(before, snapshot(self.source))

    def test_read_only_mutations_rejected_before_open_or_stdin(self):
        missing = self.root / "must-not-exist" / "last.db"
        for query in (
            ("add", "fixture"),
            ("batch", "--jsonl"),
            ("import", "--jsonl"),
            ("void", "event", "--reason", "x"),
            ("replace", "event", "--reason", "x", "--date", "2020-01-01"),
            ("set", "fixture", "--every", "1d"),
        ):
            with self.subTest(query=query):
                result = self.cli(*query, read_only=True, database=missing)
                self.assertEqual(2, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertFalse(missing.parent.exists())

    def test_read_only_requires_exact_current_schema_without_migration(self):
        for version in (0, 1, 4, 6):
            with self.subTest(version=version):
                altered = self.source / f"schema-{version}.db"
                shutil.copyfile(self.database, altered)
                with sqlite3.connect(altered) as connection:
                    connection.execute(f"PRAGMA user_version={version}")
                before = snapshot(self.source)
                result = self.cli(
                    "export", "--jsonl", read_only=True, database=altered
                )
                self.assertEqual(3, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual(before, snapshot(self.source))

    def test_read_only_malformed_store_unchanged(self):
        malformed = self.source / "malformed.db"
        malformed.write_bytes(b"not SQLite")
        before = snapshot(self.source)
        result = self.cli(
            "list", "--jsonl", read_only=True, database=malformed
        )
        self.assertEqual(3, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertEqual(before, snapshot(self.source))

    @unittest.skipUnless(os.name == "posix", "requires POSIX file semantics")
    def test_read_only_rejects_symlink_components_hardlinks_and_fifo(self):
        direct = self.root / "alias.db"
        direct.symlink_to(self.database)
        directory = self.root / "alias-directory"
        directory.symlink_to(self.source, target_is_directory=True)
        hardlink = self.root / "hardlink.db"
        os.link(self.database, hardlink)
        fifo = self.root / "pipe.db"
        os.mkfifo(fifo)
        before = snapshot(self.source)
        for path in (
            direct,
            directory / "last.db",
            hardlink,
            self.database,
            fifo,
        ):
            with self.subTest(path=str(path)):
                result = self.cli(
                    "list", "--jsonl", read_only=True, database=path
                )
                self.assertEqual(3, result.returncode)
                self.assertEqual("", result.stdout)
        self.assertEqual(before, snapshot(self.source))

    def test_read_only_rejects_every_sidecar_without_cleanup(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                sidecar = Path(str(self.database) + suffix)
                sidecar.write_bytes(b"untrusted sidecar")
                before = snapshot(self.source)
                result = self.cli("list", "--jsonl", read_only=True)
                self.assertEqual(3, result.returncode)
                self.assertEqual("", result.stdout)
                self.assertEqual(before, snapshot(self.source))
                sidecar.unlink()

    def test_read_only_changed_source_discards_buffered_output(self):
        namespace = runpy.run_path(
            str(CLI), run_name="lastdone_read_only_test"
        )
        run = namespace["run"]
        original = namespace["list_activities"]

        def changed(database, args):
            result = original(database, args)
            self.database.chmod(0o644)
            return result

        output = io.StringIO()
        with patch.dict(run.__globals__, list_activities=changed):
            with redirect_stdout(output):
                with self.assertRaises((OSError, sqlite3.Error)):
                    run(["--read-only", "list", "--jsonl"], path=self.database)
        self.assertEqual("", output.getvalue())

    def test_read_only_replaced_source_discards_buffered_output(self):
        namespace = runpy.run_path(
            str(CLI), run_name="lastdone_read_only_test"
        )
        run = namespace["run"]
        original = namespace["list_activities"]

        def replaced(database, args):
            result = original(database, args)
            replacement = self.source / "replacement.db"
            shutil.copyfile(self.database, replacement)
            replacement.replace(self.database)
            return result

        output = io.StringIO()
        with patch.dict(run.__globals__, list_activities=replaced):
            with redirect_stdout(output):
                with self.assertRaises((OSError, sqlite3.Error)):
                    run(["--read-only", "list", "--jsonl"], path=self.database)
        self.assertEqual("", output.getvalue())

    def test_read_only_export_preserves_version_and_opaque_ids(self):
        imported = {
            "record_version": 5,
            "type": "event",
            "id": "legacy opaque:café",
            "name": "Imported café name",
            "occurred_at": None,
            "occurred_on": "2020-01-02",
            "note": "Untrusted $(touch PWNED)",
            "reading_value": None,
            "reading_unit": None,
        }
        self.assertEqual(
            0,
            self.cli(
                "import", "--jsonl", input_text=json.dumps(imported) + "\n"
            ).returncode,
        )
        added = self.cli("add", "fixture", "--jsonl")
        event_id = json.loads(added.stdout)["id"]
        self.assertEqual(
            0,
            self.cli(
                "void", event_id, "--reason", "fixture correction"
            ).returncode,
        )
        result = self.cli("export", "--jsonl", read_only=True)
        self.assertEqual(0, result.returncode, result.stderr)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertTrue(all(row["record_version"] == 5 for row in rows))
        self.assertEqual(
            {"event", "correction", "activity"}, {row["type"] for row in rows}
        )
        correction = next(row for row in rows if row["type"] == "correction")
        self.assertEqual(event_id, correction["target_id"])
        self.assertIn(imported, rows)
        self.assertFalse((self.source / "PWNED").exists())

    def test_read_only_doctor_uses_guarded_snapshot(self):
        before = snapshot(self.source)
        result = self.cli("doctor", "--jsonl", read_only=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ok", json.loads(result.stdout)["status"])
        self.assertEqual(before, snapshot(self.source))

    def test_read_only_overflow_discards_all_output(self):
        namespace = runpy.run_path(
            str(CLI), run_name="lastdone_read_only_test"
        )
        run = namespace["run"]
        output = io.StringIO()
        before = snapshot(self.source)
        with patch.dict(run.__globals__, READ_ONLY_OUTPUT_BYTES=1):
            with redirect_stdout(output):
                with self.assertRaisesRegex(sqlite3.Error, "output exceeds"):
                    run(
                        ["--read-only", "export", "--jsonl"],
                        path=self.database,
                    )
        self.assertEqual("", output.getvalue())
        self.assertEqual(before, snapshot(self.source))

    def test_read_only_late_sidecar_discards_all_output(self):
        namespace = runpy.run_path(
            str(CLI), run_name="lastdone_read_only_test"
        )
        run = namespace["run"]
        original = namespace["list_activities"]

        def new_wal(database, args):
            result = original(database, args)
            Path(str(self.database) + "-wal").touch()
            return result

        output = io.StringIO()
        with patch.dict(run.__globals__, list_activities=new_wal):
            with redirect_stdout(output):
                with self.assertRaisesRegex(OSError, "sidecars"):
                    run(["--read-only", "list", "--jsonl"], path=self.database)
        self.assertEqual("", output.getvalue())


if __name__ == "__main__":
    unittest.main()
