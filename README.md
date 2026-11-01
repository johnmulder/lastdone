# last

`last` is a small, local-first CLI for answering: **When did I last do this?**
It records recurring real-world activities in SQLite and preserves their history.
The executable is named `lastdone` so it does not shadow the standard Unix
`last` command.

```sh
./lastdone add furnace-filter
./lastdone show furnace-filter
./lastdone history furnace-filter
```

`add` is silent on success. Use `--jsonl` when a command needs to feed another
program.

## Install

`lastdone` requires Python 3.10 or newer and has no third-party dependencies.

```sh
install -m 755 lastdone "$HOME/.local/bin/lastdone"
```

Ensure `$HOME/.local/bin` is on your `PATH`, then run `lastdone --help`.

## Examples

Record an earlier date or a cumulative reading:

```sh
lastdone add furnace-filter --date 2026-08-20
lastdone add oil-change --reading 84221.5mi
```

Configure an expected interval and see what is due:

```sh
lastdone set furnace-filter --every 90d
lastdone due
```

Export and restore the complete history as JSONL:

```sh
lastdone export --jsonl > lastdone-backup.jsonl
lastdone import --jsonl < lastdone-backup.jsonl
```

By default, data is stored at `~/.local/share/last/last.db`. Override this with
`--db PATH` or the `LASTDONE_DB` environment variable.

## Read-only snapshots

Use the opt-in global `--read-only` flag to query an existing quiescent,
current-schema database without initialization, migrations or permission changes:

```sh
lastdone --read-only --db /absolute/canonical/last.db list --jsonl
lastdone --read-only --db /absolute/canonical/last.db export --jsonl
```

It permits `list`, `show`, `history`, `due`, `export` and `doctor`; write commands
are rejected before the store opens. The guarded snapshot requires POSIX file
access, rejects symlinks, hardlinks and WAL/SHM/journal sidecars, and verifies source
identity/content before releasing results. Do not delete sidecars to bypass this
check. Missing, outdated, changed or unsafe snapshots fail without repair.
Read-only output is bounded to 8 MiB and buffered until verification completes.
The existing JSONL formats and command-specific time semantics are unchanged.
See the [read-only contract](CLI.md#read-only-snapshots) for details.

## Documentation

- [CLI contract](CLI.md) — commands, output formats, validation, and exit codes
- [Project idea](IDEA.md) — goals, motivation, and non-goals
- [Personal-OS conventions](conventions/v1/SPEC.md) — shared stream conventions
- [Convention ratification](conventions/v1/AUDIT.md) — audit evidence and the
  boundary between extensible command results and lossless portable imports

## Tests

```sh
python3 -m unittest discover -s tests -v
```
