# `lastdone` MVP CLI Contract

This document defines version 2 of the observable command-line interface for
the `last` project's `lastdone` executable. It covers the MVP only. Human output
may gain optional detail later; the JSONL record meanings change only with a
`schema_version` change.

## Invocation

```text
lastdone add NAME [--date YYYY-MM-DD] [--jsonl]
lastdone show NAME [--jsonl]
lastdone history NAME [--jsonl]
lastdone list [--jsonl]
lastdone --help
lastdone --version
```

`NAME` is one non-empty, printable command argument. Version 2 does not otherwise
normalize or restrict names. The activity-key proposal will define a stricter
grammar.

`--date` accepts only a real ISO 8601 calendar date in `YYYY-MM-DD` form. Future
dates are invalid because `lastdone` records completed actions. Options not shown
above are invalid; `--note`, `set`, and `due` remain outside this contract.

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
{"schema_version":2,"type":"..."}
```

Version 2 has three record types.

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

Adding a field is backward-compatible. Removing a field, renaming a field, or
changing a field's meaning requires a new `schema_version`.

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

### `--help` and `--version`

Help returns 0, writes usage text to stdout, and writes nothing to stderr.
Version returns 0 and writes exactly:

```text
lastdone 0.2.0
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
