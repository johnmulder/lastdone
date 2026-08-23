# `lastdone` MVP CLI Contract

This document defines version 2 of the observable command-line interface for
the `last` project's `lastdone` executable. It covers the MVP only. Human output
may gain optional detail later; the JSONL record meanings change only with a
`schema_version` change.

## Invocation

```text
lastdone [--db PATH] add NAME [--date YYYY-MM-DD] [--jsonl]
lastdone [--db PATH] show NAME [--jsonl]
lastdone [--db PATH] history NAME [--include-corrections] [--jsonl]
lastdone [--db PATH] list [--jsonl]
lastdone [--db PATH] void EVENT_ID --reason TEXT [--jsonl]
lastdone [--db PATH] replace EVENT_ID --reason TEXT
         [--name NAME] [--date YYYY-MM-DD] [--note TEXT] [--jsonl]
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
dates are invalid because `lastdone` records completed actions. `EVENT_ID` and
correction reasons are non-empty printable text. Replacement notes are printable
text and may be empty. The global `--db` option must appear before the command.
Options not shown above are invalid; `add --note`, `set`, and `due` remain outside
this contract.

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

The database schema uses `PRAGMA user_version`; the current schema version is 2.
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

Version 2 has five record types.

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

### Correction

Produced by `void --jsonl`, `replace --jsonl`, and correction-inclusive machine
history:

```json
{"schema_version":2,"type":"correction","id":"c8f8c768-7b2d-4985-a080-b58a94d3933c","kind":"replace","target_id":"550e8400-e29b-41d4-a716-446655440000","replacement_id":"ee481866-5e5f-4fc2-b6d1-a2f0e4d60cec","reason":"wrong date","corrected_at":"2026-08-22T18:00:00.000000Z"}
```

`kind` is `void` or `replace`. A void has a null `replacement_id`; a replacement
references its newly appended event. Reasons are non-empty and `corrected_at` is
an RFC 3339 UTC instant with six fractional digits.

### Doctor

Produced once by `doctor --jsonl`:

```json
{"schema_version":2,"type":"doctor","database":"/home/me/.local/share/last/last.db","database_schema_version":2,"schema":"ok","integrity":"ok","permissions":"ok","parseability":"ok","events":5,"corrections":1,"status":"ok"}
```

`status` is `ok` only when every applicable check passes. On non-POSIX systems,
`permissions` is `not-applicable`. `database_schema_version`, `events`, or
`corrections` is null when that value cannot be read safely.

Adding a field is backward-compatible. Removing a field, renaming a field, or
changing a field's meaning requires a new `schema_version`.

## Interchange records

`export --jsonl` emits lossless record version 2:

```json
{"record_version":2,"type":"event","id":"550e8400-e29b-41d4-a716-446655440000","name":"furnace-filter","occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null,"note":null}
{"record_version":2,"type":"correction","id":"c8f8c768-7b2d-4985-a080-b58a94d3933c","kind":"replace","target_id":"550e8400-e29b-41d4-a716-446655440000","replacement_id":"ee481866-5e5f-4fc2-b6d1-a2f0e4d60cec","reason":"wrong date","corrected_at":"2026-08-22T18:00:00.000000Z"}
```

Version 2 event records require the same seven fields as version 1 event records;
only `record_version` changes. `id` and `name` are non-empty strings; `note` is a
string or null. Exactly one occurrence field is populated. An exact timestamp
has six fractional digits and `Z`; a calendar date is real `YYYY-MM-DD`.

Version 2 correction records require exactly the eight fields shown. IDs and
reasons are non-empty strings, timestamps use the exact event timestamp form,
and kind/link combinations follow the command-result correction rules. Events
must precede corrections that reference them. Import continues to accept version
1 event records. Interchange versions are independent of command-result
`schema_version` values and SQLite schema versions.

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
Corrected targets never contribute to the summary; their effective replacements
do.

A missing activity returns 1 and writes this diagnostic:

```text
lastdone: activity not found: furnace-filter
```

### `history`

By default, human mode emits `EVENT_ID  DATE` per effective event and JSONL mode
emits one effective event record per line. Both order by displayed calendar date,
newest first. Exact instants precede date-only events on the same date;
otherwise-equal events use most recent insertion first.

`--include-corrections` emits all events stored under `NAME`, including corrected
targets, plus events directly linked to them by corrections. Events use insertion
order, followed by the directly related corrections in correction order. Human
audit lines begin with `event` or `correction`; JSONL uses the event and
correction records above.

A missing activity has the same behavior as missing `show` output.

### `list`

Human mode emits one distinct activity name per line. JSONL mode emits one
activity record per line. Names are ordered by their UTF-8 byte values. Duplicate
events never duplicate a list entry.

Only effective events contribute names. Replacing an activity with a new name
removes the old name when no other effective event uses it.

An empty database is successful and emits no output in either mode.

### `void`

`void EVENT_ID --reason TEXT` appends a correction that removes one effective
event from normal queries without deleting it. Human mode is silent; JSONL emits
the correction record. A missing event or an event already corrected returns 1.

### `replace`

`replace EVENT_ID --reason TEXT` appends a new event and a correction linking the
target to it in one transaction. At least one of `--name`, `--date`, or `--note`
is required; unspecified values preserve the target. `--date` changes the
occurrence to date-only precision. Human mode is silent; JSONL emits the
correction record. A missing or already-corrected target returns 1.

A replacement is itself an ordinary effective event and can later be corrected
using its own ID. Corrections cannot be changed or deleted.

### `export`

`export --jsonl` writes every interchange version 2 event oldest-insertion first,
then every correction in correction order. It streams directly from SQLite and
includes every durable field. An empty database emits no output successfully.

### `import`

`import --jsonl` reads interchange event records from standard input and is
silent on success. It validates and applies the stream in one transaction
without loading it into memory. An existing identical ID is a no-op. An ID with
different content, malformed JSON, blank line, unsupported record version, or
invalid field or link rolls back the entire import and returns 2 with a diagnostic
that begins `lastdone: import error: line N:`. Corrections must follow their
target and replacement events. Version 1 event-only streams remain valid.

### `doctor`

`doctor` opens the selected database read-only and never creates, migrates, or
repairs it. It reports the absolute database path, schema version and structure,
SQLite integrity, database-file permissions, event and correction parseability,
event and correction counts, and overall status. Human output uses one labeled
line per value; `--jsonl` emits the doctor record above.

A healthy report returns 0. A completed report with problems returns 3. A
missing or inaccessible database is a storage error, returns 3, emits no report,
and leaves the path absent.

### `--help` and `--version`

Help returns 0, writes usage text to stdout, and writes nothing to stderr.
Version returns 0 and writes exactly:

```text
lastdone 0.6.0
```

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success, including an empty list or closed output pipe |
| 1 | Named activity/event not found, or event already corrected |
| 2 | Invalid command, option, value, argument count, or import stream |
| 3 | Storage or configuration failure |

Exit codes do not encode ordinary data states.

## Error stability

Missing-activity, missing-event, and already-corrected diagnostics begin with
`lastdone:`. Other invalid-argument and storage wording is not a machine
interface, but every diagnostic has that prefix and no Python traceback.
Programs should branch on exit codes, not parse those messages.
