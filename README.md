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

## Documentation

- [CLI contract](CLI.md) — commands, output formats, validation, and exit codes
- [Project idea](IDEA.md) — goals, motivation, and non-goals
- [Personal-OS conventions](conventions/v1/SPEC.md) — shared stream conventions

## Tests

```sh
python3 -m unittest discover -s tests -v
```
