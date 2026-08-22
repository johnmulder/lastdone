# `lastdone` MVP CLI Contract

This document defines version 1 of the observable command-line interface for
the `last` project's `lastdone` executable. It covers the MVP only. Human output
may gain optional detail later; the JSONL record meanings change only with a
`schema_version` change.

## Invocation

```text
lastdone add NAME [--jsonl]
lastdone show NAME [--jsonl]
lastdone history NAME [--jsonl]
lastdone list [--jsonl]
lastdone --help
lastdone --version
```

`NAME` is one non-empty, printable command argument. Version 1 does not otherwise
normalize or restrict names. The activity-key proposal will define a stricter
grammar.

Options not shown above are invalid. In particular, version 1 has no supported
way to supply an occurrence time, future or otherwise. `--date`, `--note`,
`set`, and `due` remain outside the MVP contract.

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

The default database is `$XDG_DATA_HOME/last/last.db`. When `XDG_DATA_HOME` is
unset or empty, it is `~/.local/share/last/last.db`. The parent directory and
database are created on first use.

## JSONL records

Every record contains:

```json
{"schema_version":1,"type":"..."}
```

Version 1 has three record types.

### Event

Produced by `add --jsonl` and once per occurrence by `history --jsonl`:

```json
{"schema_version":1,"type":"event","id":"550e8400-e29b-41d4-a716-446655440000","name":"furnace-filter","occurred_at":"2026-08-21T20:32:00.000000Z","note":null}
```

- `id` is a UUID string unique to the event.
- `occurred_at` is an RFC 3339 UTC instant with six fractional digits and `Z`.
- `note` is always null in version 1 because notes are not accepted by the MVP.

### Summary

Produced once by `show --jsonl`:

```json
{"schema_version":1,"type":"summary","name":"furnace-filter","last":"2026-08-21T20:32:00.000000Z","previous":"2026-05-14T15:10:00.000000Z","interval_days":99,"occurrences":5}
```

`previous` and `interval_days` are null when only one event exists. The interval
is the difference between the two most recent occurrence dates in the process's
local timezone.

### Activity

Produced once per distinct name by `list --jsonl`:

```json
{"schema_version":1,"type":"activity","name":"furnace-filter"}
```

Adding a field is backward-compatible. Removing a field, renaming a field, or
changing a field's meaning requires a new `schema_version`.

## Commands

### `add`

`add NAME` records a new event at the current instant. Repeating the same command
records another event; duplicates are valid history and receive different IDs.

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

For one event, the `Previous` and `Interval` values are `-`. Dates are rendered
in the process's local timezone. JSONL mode emits one summary record with full
timestamps.

A missing activity returns 1 and writes this diagnostic:

```text
lastdone: activity not found: furnace-filter
```

### `history`

Human mode emits one local occurrence date per line. JSONL mode emits one event
record per line. Both modes order events newest first; events with identical
timestamps are ordered by most recent insertion first.

A missing activity has the same behavior as missing `show` output.

### `list`

Human mode emits one distinct activity name per line. JSONL mode emits one
activity record per line. Names are ordered by their UTF-8 byte values. Duplicate
events never duplicate a list entry.

An empty database is successful and emits no output in either mode.

### `--help` and `--version`

Help returns 0, writes usage text to stdout, and writes nothing to stderr.
Version returns 0 and writes exactly:

```text
lastdone 0.1.0
```

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success, including an empty list or closed output pipe |
| 1 | Named activity not found |
| 2 | Invalid command, option, name, or argument count |
| 3 | Storage or configuration failure |

Exit codes do not encode ordinary data states.

## Error stability

The missing-activity diagnostic above is stable. Invalid-argument and storage
diagnostic wording is not a machine interface, but each diagnostic begins with
`lastdone:` and contains no Python traceback. Programs should branch on exit
codes, not parse those messages.
