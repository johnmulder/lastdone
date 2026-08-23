# `lastdone` CLI Contract

This document defines version 2 of the observable command-line interface for
the `last` project's `lastdone` executable. Human output may gain optional
detail later; the JSONL record meanings change only with a `schema_version`
change.

The copyable [personal-OS convention pack](conventions/v1/SPEC.md) extracts the
shared encoding, framing, time, stream, diagnostic, and exit-status rules from
this command-specific contract. Its version is independent of this CLI version.

## Invocation

```text
lastdone [--db PATH] add KEY [--date YYYY-MM-DD] [--reading VALUEUNIT]
         [--allow-decrease] [--jsonl]
lastdone [--db PATH] show KEY [--jsonl]
lastdone [--db PATH] history KEY [--include-corrections] [--jsonl]
lastdone [--db PATH] list [--jsonl]
lastdone [--db PATH] void EVENT_ID --reason TEXT [--jsonl]
lastdone [--db PATH] replace EVENT_ID --reason TEXT
         [--name KEY] [--date YYYY-MM-DD] [--note TEXT]
         [--reading VALUEUNIT] [--allow-decrease] [--jsonl]
lastdone [--db PATH] set KEY [--every Nd] [--display-name TEXT] [--jsonl]
lastdone [--db PATH] due [--overdue] [--jsonl]
lastdone [--db PATH] export --jsonl
lastdone [--db PATH] import --jsonl
lastdone [--db PATH] doctor [--jsonl]
lastdone --help
lastdone --version
```

`KEY` is one exact lowercase ASCII activity key matching
`[a-z0-9]+(?:-[a-z0-9]+)*`. Commands never lowercase, transliterate, or otherwise
rewrite it. Imported legacy keys outside this grammar are preserved and reported
by `doctor`, but cannot be supplied to interactive activity-key arguments.

`--date` accepts only a real ISO 8601 calendar date in `YYYY-MM-DD` form. Future
dates are invalid because `lastdone` records completed actions. `EVENT_ID`,
display names, and correction reasons are non-empty printable text. Replacement
notes are printable text and may be empty. CLI-supplied display names, reasons,
and notes are normalized to Unicode NFC before storage. NUL and all other
non-printable/control characters are invalid in every text field. The global
`--db` option must appear before the command.
`Nd` is an ASCII, non-zero decimal integer followed immediately by lowercase
`d`. It has no sign, whitespace, leading zero, or other unit and must fit
SQLite's signed integer range. Options not shown above are invalid; `add --note`
remains outside this contract.

`VALUEUNIT` joins one non-negative decimal and one exact unit with no separator.
The decimal matches `(0|[1-9][0-9]*)(\.[0-9]+)?`; the unit contains lowercase
ASCII letters with optional non-adjacent internal hyphens. Fractional trailing
zeroes are removed before storage. Signs, exponents, whitespace, leading zeroes,
uppercase units, and non-ASCII spellings are invalid. Units are compared exactly
and never converted.

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

The database schema uses `PRAGMA user_version`; the current schema version is 5.
Migrations run forward in numbered transactions before the requested command.
Before rebuilding an existing unversioned database, `lastdone` creates
`last.db.v0.bak`; before rebuilding schema 3 activity metadata, it creates
`last.db.v3.bak`. Both use mode 0600 and are never overwritten. Migration 5 only
adds nullable columns, so it does not need a recovery copy. A newer schema
version, an unrecognized schema, or schema drift is a storage error and returns
3 without mutating the database.

## JSONL records

Every record contains:

```json
{"schema_version":2,"type":"..."}
```

Version 2 has six record types.

### Event

Produced by `add --jsonl` and once per occurrence by `history --jsonl`:

```json
{"schema_version":2,"type":"event","id":"550e8400-e29b-41d4-a716-446655440000","name":"furnace-filter","occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null,"note":null,"reading_value":"84221.5","reading_unit":"mi"}
```

- `id` is a UUID string unique to the event.
- `name` is the stable activity key.
- Exactly one of `occurred_at` and `occurred_on` is non-null.
- `occurred_at` is an RFC 3339 UTC instant with six fractional digits and `Z`.
- `occurred_on` is an ISO 8601 calendar date with no implied time or timezone.
- `add` sets `note` to null; replacement and imported events may contain text.
- `reading_value` and `reading_unit` are both null or both present. Values are
  canonical decimal strings and units use the exact grammar above.

### Summary

Produced once by `show --jsonl`:

```json
{"schema_version":2,"type":"summary","name":"furnace-filter","display_name":"Filtre à air 🏠","last":{"occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null},"previous":{"occurred_at":null,"occurred_on":"2026-05-14"},"interval_days":99,"reading_value":"84221.5","reading_unit":"mi","reading_change":"3421.5","occurrences":5}
```

`previous` and `interval_days` are null when only one event exists. Each
occurrence object has the same exactly-one rule as an event. The interval is the
difference between the two displayed calendar dates, not elapsed 24-hour blocks.
`display_name` is NFC-normalized configured human text or null.
The three reading fields are null when the latest event has no reading.
Otherwise value and unit describe that event; `reading_change` is the exact
decimal difference from the nearest older effective event with the same unit,
or null when no compatible older reading exists.

### Activity

Produced once per distinct name by `list --jsonl`:

```json
{"schema_version":2,"type":"activity","name":"furnace-filter","expected_interval_days":90,"display_name":"Filtre à air 🏠"}
```

`expected_interval_days` is a positive integer when configured and null when no
interval is set. `display_name` is configured human text or null. A name known
only from effective events has both null. `set --jsonl` emits the stored activity
record.

### Due

Produced once per configured activity by `due --jsonl`, subject to filtering:

```json
{"schema_version":2,"type":"due","name":"furnace-filter","expected_interval_days":90,"display_name":"Filtre à air 🏠","last":{"occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null},"due_on":"2026-11-19","state":"not-due"}
```

`last` preserves the effective latest event's occurrence precision and is null
for an activity with no effective events. `due_on` is the displayed local
calendar date of `last` plus `expected_interval_days`; it is null when there is
no effective event or the result is beyond year 9999. `state` is exactly one of
`never-recorded`, `future-dated`, `not-due`, `due-today`, or `overdue`.

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
{"schema_version":2,"type":"doctor","database":"/home/me/.local/share/last/last.db","database_schema_version":5,"schema":"ok","integrity":"ok","permissions":"ok","parseability":"ok","conventions":"ok","convention_issues":[],"events":5,"corrections":1,"activities":2,"status":"ok"}
```

`status` is `ok` only when every applicable check passes. On non-POSIX systems,
`permissions` is `not-applicable`. `database_schema_version`, `events`,
`corrections`, or `activities` is null when that value cannot be read safely.
`conventions` is `problems` when `convention_issues` reports invalid stored keys,
control characters, or non-NFC human text; these checks never rewrite data.

Adding a field is backward-compatible. Removing a field, renaming a field, or
changing a field's meaning requires a new `schema_version`.

## Interchange records

`export --jsonl` emits lossless record version 5:

```json
{"record_version":5,"type":"event","id":"550e8400-e29b-41d4-a716-446655440000","name":"furnace-filter","occurred_at":"2026-08-21T20:32:00.000000Z","occurred_on":null,"note":null,"reading_value":"84221.5","reading_unit":"mi"}
{"record_version":5,"type":"correction","id":"c8f8c768-7b2d-4985-a080-b58a94d3933c","kind":"replace","target_id":"550e8400-e29b-41d4-a716-446655440000","replacement_id":"ee481866-5e5f-4fc2-b6d1-a2f0e4d60cec","reason":"wrong date","corrected_at":"2026-08-22T18:00:00.000000Z"}
{"record_version":5,"type":"activity","name":"furnace-filter","expected_interval_days":90,"display_name":"Filtre à air 🏠"}
```

Version 5 event records require exactly the nine fields shown. The reading fields
are both null or contain canonical strings matching the CLI grammar. Versions 1
through 4 use the former seven fields and map to null readings. `id` and `name`
are non-empty strings; `note` is a string or null. Exactly one occurrence field
is populated. An exact timestamp has six fractional digits and `Z`; a calendar
date is real `YYYY-MM-DD`.

Version 5 correction records require exactly the eight fields shown, unchanged
from versions 2 through 4. IDs and reasons are non-empty strings, timestamps use
the exact event timestamp form, and kind/link combinations follow the
command-result correction rules. Events must precede corrections that reference
them. Version 5 activity records are unchanged from version 4 and require
exactly the five fields shown. The name is non-empty; the interval is null or a
positive integer; the display name is null or non-empty printable text; and at
least one metadata value is present. Version 3 activities map to a null display
name. Import continues to accept versions 1-4 events, versions 2-4 corrections,
and versions 3-4 activities. Printable non-ASCII keys and non-NFC human text are
preserved for compatibility and reported by `doctor`, while control characters
are rejected. Interchange versions are independent of command-result
`schema_version` values and SQLite schema versions.

## Commands

### `add`

`add KEY` records a new event at the current UTC instant. `add KEY --date DATE`
records only that calendar date; it never invents midnight or a timezone.
`--reading VALUEUNIT` attaches one canonical cumulative reading.
Repeating either command records another event, because duplicates are valid
history and receive different IDs.

For the same activity and exact unit, a reading must fit between its nearest
older and newer effective chronological neighbors. A decrease or backdated
value that would make a later reading decrease returns 2 without writing.
`--allow-decrease` confirms a reset or rollover and is invalid without a
reading.

Human mode is silent on success. JSONL mode emits the new event record.

### `show`

Human output is:

```text
Filtre à air 🏠 [furnace-filter]
Last: 2026-08-21
Previous: 2026-05-14
Interval: 99 days
Reading: 84221.5mi (+3421.5mi)
Occurrences: 5
```

For one event, the `Previous` and `Interval` values are `-`. Exact instants are
rendered in the process's local timezone; date-only events render their stored
date unchanged. JSONL mode emits one summary record that preserves both kinds.
Corrected targets never contribute to the summary; their effective replacements
do. The first human line is `DISPLAY_NAME [KEY]` when configured and otherwise
just `KEY`.
`Reading` is `-` when the latest event has none, omits the parenthesized change
when no older exact-unit reading exists, and uses a signed change otherwise.

A missing activity returns 1 and writes this diagnostic:

```text
lastdone: activity not found: furnace-filter
```

### `history`

By default, human mode emits `EVENT_ID  DATE  READING|-` per effective event and
JSONL mode emits one effective event record per line. Both order by displayed
calendar date, newest first. Exact instants precede date-only events on the same
date; otherwise-equal events use most recent insertion first.

`--include-corrections` emits all events stored under `KEY`, including corrected
targets, plus events directly linked to them by corrections. Events use insertion
order, followed by the directly related corrections in correction order. Human
audit lines begin with `event` or `correction`; JSONL uses the event and
correction records above.

A missing activity has the same behavior as missing `show` output.

### `list`

Human mode emits `KEY` or `KEY  DISPLAY_NAME` per line. JSONL mode emits one
activity record per line. Keys are ordered by their UTF-8 byte values. Duplicate
events never duplicate a list entry.

Effective events and configured activity metadata contribute names. Replacing
an event with a new name removes the old event-derived name when no other
effective event or metadata row uses it. JSONL activity records expose the
configured interval or null.

An empty database is successful and emits no output in either mode.

### `void`

`void EVENT_ID --reason TEXT` appends a correction that removes one effective
event from normal queries without deleting it. Human mode is silent; JSONL emits
the correction record. A missing event or an event already corrected returns 1.

### `replace`

`replace EVENT_ID --reason TEXT` appends a new event and a correction linking the
target to it in one transaction. At least one of `--name`, `--date`, `--note`, or
`--reading` is required; unspecified values preserve the target. `--date`
changes the occurrence to date-only precision. Human mode is silent; JSONL
emits the correction record. A missing or already-corrected target returns 1.

The resulting event follows the same exact-unit chronology check as `add` after
any name or date change. `--allow-decrease` explicitly accepts a reset and is
invalid when the resulting event has no reading.

A replacement is itself an ordinary effective event and can later be corrected
using its own ID. Corrections cannot be changed or deleted.

### `set`

`set KEY [--every Nd] [--display-name TEXT]` stores one or both metadata values;
at least one option is required. It is an idempotent upsert, preserves an omitted
existing value, and can configure a key with no events. Display names are stored
in NFC. It does not clear metadata, rename a key, schedule a task, migrate
metadata after `replace --name`, or accept calendar months. Human mode is silent;
JSONL emits the stored activity record.

### `due`

`due` emits one record or human line per configured activity, ordered by name's
UTF-8 bytes. Calculations use only effective events and the current local date.
If the latest displayed event date is in the future, the state is
`future-dated`. Otherwise `due_on` before today is `overdue`, equality is
`due-today`, and a later date is `not-due`. No effective event is
`never-recorded`. A representable `due_on` is still reported for future-dated
activities; a date beyond year 9999 is null and `not-due`.

Human lines use:

```text
KEY  DISPLAY_NAME|-  LAST_DATE|-  Nd  DUE_ON|-  STATE
```

The human state is the uppercase machine-state spelling. `--overdue` emits only
the `overdue` state; an empty result is successful. Ordinary states never change
the exit code.

### `export`

`export --jsonl` writes every interchange version 5 event oldest-insertion first,
then every correction in correction order, then activity metadata by name. It
streams directly from SQLite and includes every durable field. An empty database
emits no output successfully.

### `import`

`import --jsonl` reads interchange records from standard input and is
silent on success. It validates and applies the stream in one transaction
without loading it into memory. An existing identical ID is a no-op. An ID with
different content, malformed JSON, blank line, unsupported record version, or
invalid field or link rolls back the entire import and returns 2 with a diagnostic
that begins `lastdone: import error: line N:`. Corrections must follow their
target and replacement events. Older supported streams remain valid. Activity
metadata is idempotent by key; different stored metadata for an existing key is
a conflict that rolls back the stream. Printable legacy keys and non-NFC text
are preserved verbatim, while control characters are rejected.

### `doctor`

`doctor` opens the selected database read-only and never creates, migrates, or
repairs it. It reports the absolute database path, schema version and structure,
SQLite integrity, database-file permissions, event and correction parseability,
activity metadata parseability, key/text convention deviations, all three
counts, and overall status. Invalid stored keys and non-NFC text are reported
without mutation. Human output uses labeled lines; `--jsonl` emits the doctor
record above.

A healthy report returns 0. A completed report with problems returns 3. A
missing or inaccessible database is a storage error, returns 3, emits no report,
and leaves the path absent.

### `--help` and `--version`

Help returns 0, writes usage text to stdout, and writes nothing to stderr.
Version returns 0 and writes exactly:

```text
lastdone 0.9.0
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
