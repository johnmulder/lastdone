# `lastdone` MVP CLI Contract

This document defines version 2 of the observable command-line interface for
the `last` project's `lastdone` executable. It covers the MVP only. Human output
may gain optional detail later; the JSONL record meanings change only with a
`schema_version` change.

## Invocation

```text
lastdone [--db PATH] add NAME [--date YYYY-MM-DD] [--jsonl]
lastdone [--db PATH] show NAME [--jsonl]
lastdone [--db PATH] history NAME [--jsonl]
lastdone [--db PATH] list [--jsonl]
lastdone [--db PATH] export --jsonl
lastdone [--db PATH] import --jsonl
lastdone [--db PATH] doctor [--jsonl]
lastdone --help
lastdone --version
```

`NAME` is one non-empty, printable command argument. Version 2 does not otherwise
normalize or restrict names. The activity-key proposal will define a stricter
grammar.

`--date` accepts only a real ISO 8601 calendar date in `YYYY-MM-DD` form. Future
dates are invalid because `lastdone` records completed actions. The global
`--db` option must appear before the command. Options not shown above are
invalid; `--note`, `set`, and `due` remain outside this contract.

## Common behavior

- Text is UTF-8 and lines end with LF.
- Results go to stdout. Diagnostics go to stderr.
- Successful commands write nothing to stderr.
- Failed commands write nothing to stdout.
- Human output contains no color or terminal-control sequences.
- `--jsonl` emits one complete compact JSON object per result line. It never
  wraps the results in an array.
- A closed stdout pipe is a successful early consumer exit: return 0 and do not
  print a traceback or diagnostic.

An unhealthy `doctor` report is the sole exception to failed commands producing
no stdout: it emits the completed report and returns 3.

The database path is selected in this order:

1. `--db PATH`;
2. a non-empty `LASTDONE_DB` environment variable;
3. `$XDG_DATA_HOME/last/last.db` when `XDG_DATA_HOME` is non-empty;
4. `~/.local/share/last/last.db`.

Tildes are expanded. Relative paths are resolved by SQLite from the process's
working directory. The selected path is never added to ordinary command output;
`doctor` reports it explicitly. Missing parent directories and the database are
created on first use.
On POSIX systems a newly created leaf directory is mode 0700 and the database is
mode 0600; an existing custom directory keeps its permissions.

SQLite connections wait up to five seconds for a competing writer. Insert
transactions are committed immediately, and migration selection occurs while
holding the write lock so concurrent first runs cannot apply the same migration.
If the timeout expires, the command returns 3 with a storage diagnostic that
identifies the busy database and advises retrying.

The database schema uses `PRAGMA user_version`; the current schema version is 1.
Migrations run forward in numbered transactions before the requested command.
Before rebuilding an existing unversioned database, `lastdone` creates
`last.db.v0.bak` with mode 0600 and never overwrites it. A newer schema version,
an unrecognized schema, or schema drift is a storage error and returns 3 without
mutating the database.

## JSONL records

Every record contains:

```json
{"schema_version":2,"type":"..."}
```

Version 2 has four record types.

### Event

Produced by `add --jsonl` and once per occurrence by `history --jsonl`:

```json
{"schema_version":2,"type":"event","id":"550e8400-e29b-41d4-a716-446655440000","name":"furnace-filter","occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null,"note":null}
```

- `id` is a UUID string unique to the event.
- Exactly one of `occurred_at` and `occurred_on` is non-null.
- `occurred_at` is an RFC 3339 UTC instant with six fractional digits and `Z`.
- `occurred_on` is an ISO 8601 calendar date with no implied time or timezone.
- `note` is always null in version 2 because notes are not yet accepted.

### Summary

Produced once by `show --jsonl`:

```json
{"schema_version":2,"type":"summary","name":"furnace-filter","last":{"occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null},"previous":{"occurred_at":null,"occurred_on":"2026-05-14"},"interval_days":99,"occurrences":5}
```

`previous` and `interval_days` are null when only one event exists. Each
occurrence object has the same exactly-one rule as an event. The interval is the
difference between the two displayed calendar dates, not elapsed 24-hour blocks.

### Activity

Produced once per distinct name by `list --jsonl`:

```json
{"schema_version":2,"type":"activity","name":"furnace-filter"}
```

### Doctor

Produced once by `doctor --jsonl`:

```json
{"schema_version":2,"type":"doctor","database":"/home/me/.local/share/last/last.db","database_schema_version":1,"schema":"ok","integrity":"ok","permissions":"ok","parseability":"ok","events":5,"status":"ok"}
```

`status` is `ok` only when every applicable check passes. On non-POSIX systems,
`permissions` is `not-applicable`. `database_schema_version` or `events` is null
when that value cannot be read safely.

Adding a field is backward-compatible. Removing a field, renaming a field, or
changing a field's meaning requires a new `schema_version`.

## Interchange records

`export --jsonl` and `import --jsonl` use a separate, lossless record format:

```json
{"record_version":1,"type":"event","id":"550e8400-e29b-41d4-a716-446655440000","name":"furnace-filter","occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null,"note":null}
```

Version 1 requires exactly those seven fields. `id` and `name` are non-empty
strings; `note` is a string or null. Exactly one occurrence field is populated.
An exact timestamp has six fractional digits and `Z`; a calendar date is a real
date in `YYYY-MM-DD` form. Interchange versions are independent of command-result
`schema_version` values and SQLite column or schema versions.

## Commands

### `add`

`add NAME` records a new event at the current UTC instant. `add NAME --date DATE`
records only that calendar date; it never invents midnight or a timezone.
Repeating either command records another event, because duplicates are valid
history and receive different IDs.

Human mode is silent on success. JSONL mode emits the new event record.

### `show`

Human output is:

```text
furnace-filter
Last: 2026-08-21
Previous: 2026-05-14
Interval: 99 days
Occurrences: 5
```

For one event, the `Previous` and `Interval` values are `-`. Exact instants are
rendered in the process's local timezone; date-only events render their stored
date unchanged. JSONL mode emits one summary record that preserves both kinds.

A missing activity returns 1 and writes this diagnostic:

```text
lastdone: activity not found: furnace-filter
```

### `history`

Human mode emits one occurrence date per line. JSONL mode emits one event record
per line. Both modes order by displayed calendar date, newest first. Exact
instants precede date-only events on the same date; otherwise-equal events use
most recent insertion first.

A missing activity has the same behavior as missing `show` output.

### `list`

Human mode emits one distinct activity name per line. JSONL mode emits one
activity record per line. Names are ordered by their UTF-8 byte values. Duplicate
events never duplicate a list entry.

An empty database is successful and emits no output in either mode.

### `export`

`export --jsonl` writes one interchange event record per line, oldest insertion
first. It streams directly from SQLite and includes every durable event field.
An empty database emits no output successfully.

### `import`

`import --jsonl` reads interchange event records from standard input and is
silent on success. It validates and applies the stream in one transaction
without loading it into memory. An existing identical ID is a no-op. An ID with
different content, malformed JSON, blank line, unsupported record version, or
invalid field rolls back the entire import and returns 2 with a diagnostic that
begins `lastdone: import error: line N:`.

### `doctor`

`doctor` opens the selected database read-only and never creates, migrates, or
repairs it. It reports the absolute database path, schema version and structure,
SQLite integrity, database-file permissions, event parseability, event count,
and overall status. Human output uses one labeled line per value; `--jsonl`
emits the doctor record above.

A healthy report returns 0. A completed report with problems returns 3. A
missing or inaccessible database is a storage error, returns 3, emits no report,
and leaves the path absent.

### `--help` and `--version`

Help returns 0, writes usage text to stdout, and writes nothing to stderr.
Version returns 0 and writes exactly:

```text
lastdone 0.5.0
```

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success, including an empty list or closed output pipe |
| 1 | Named activity not found |
| 2 | Invalid command, option, name, argument count, or import stream |
| 3 | Storage or configuration failure |

Exit codes do not encode ordinary data states.

## Error stability

The missing-activity diagnostic above is stable. Invalid-argument and storage
diagnostic wording is not a machine interface, but each diagnostic begins with
`lastdone:` and contains no Python traceback. Programs should branch on exit
codes, not parse those messages.
