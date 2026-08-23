# Personal-OS Interoperability Conventions, Version 1

This directory is a copyable contract for small personal-OS commands. It
standardizes their edges, not their implementations or domain schemas.

## Versioning

The `v1` directory names this convention version. It is independent of:

- an executable's release version;
- a command-result `schema_version`;
- a portable interchange `record_version`;
- a storage schema version.

Structured command results contain a positive integer `schema_version` and a
string `type`. Portable interchange records use their owning command's positive
integer `record_version`. Adding a field is compatible. Removing or renaming a
field, or changing its meaning, requires the owning schema or record version to
change. Create `v2` only for an incompatible change to these shared conventions.

## Text and streams

- Text is UTF-8 without a byte-order mark and uses LF line endings.
- Results go to stdout; diagnostics go to stderr.
- Success writes nothing to stderr. Failure writes nothing to stdout unless a
  diagnostic command intentionally returns a complete machine-readable report.
- Human output and diagnostics contain no terminal-control sequences.
- A version request writes `PROGRAM MAJOR.MINOR.PATCH` and one LF to stdout.

JSONL output is compact UTF-8 JSON: one complete object per non-empty line, no
array wrapper, and one final LF per object. Literal Unicode is valid and
preferred over ASCII escapes when the encoder supports it. Producers must not
split an object across lines. Consumers ignore fields they do not understand.

## Common fields and time

- `type` is the record discriminator.
- `name` is a non-empty, stable machine identifier whose exact grammar belongs
  to the command.
- `display_name` is optional human-facing Unicode text and never replaces
  `name` as the integration key.
- `occurred_at` is either null or an RFC 3339 UTC instant in the exact form
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
- `occurred_on` is either null or a real Gregorian date in exact `YYYY-MM-DD`
  form.

Occurrence records include both occurrence fields and populate exactly one.
Commands do not invent midnight or a timezone for a date-only occurrence.

## Diagnostics and exit status

Diagnostics are single LF-terminated lines in this form:

```text
PROGRAM: CATEGORY: DETAIL
```

The category may be omitted when the detail is already a stable condition such
as `resource not found`. Diagnostics must not echo sensitive record content.

```text
0  success
1  requested resource not found
2  invalid arguments or input
3  storage, configuration, or integrity error
```

Ordinary domain states belong in structured output, not exit codes.

## Data locations

An explicit command-line path wins over a non-empty command-specific environment
variable, which wins over `$XDG_DATA_HOME`. When XDG data home is empty or
unset, use `~/.local/share`. Commands keep separate leaf directories and do not
share a database merely to share these conventions.

## Reference fixtures

`fixtures/events.jsonl` is portable `lastdone` input and expected byte-for-byte
export output. `fixtures/summary.jsonl`, `fixtures/not-found.stderr`, and
`fixtures/version.stdout` are expected command outputs. They demonstrate exact
timestamps, date-only occurrences, common fields, compact framing, Unicode, a
diagnostic, and independent executable/result/interchange versions.

Projects should copy or publish these files and write a small native test against
their own command. They should not depend on a shared runtime package or runner.
