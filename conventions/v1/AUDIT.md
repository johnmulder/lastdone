# Personal-OS convention ratification

Reviewed October 25, 2026. The existing v1 convention pack is ratified as the
copyable CLI boundary for future independent tools. Their record schemas,
identifier grammars, storage, and domain behavior remain their own contracts.
No shared runtime, runner, database, or framework was introduced.

## Findings and resolutions

The implementation, CLI contract, README examples, and byte fixtures agree on
the boundaries below, with two corrections from this audit:

- **Standard-stream encoding:** forcing Python's I/O encoding to ASCII caused a
  valid UTF-8 fixture import to fail and a Unicode export to print a traceback.
  The executable now configures its standard text streams for UTF-8 and LF
  before parsing commands. A black-box regression imports/exports the original
  Unicode fixture byte-for-byte under ASCII configuration and verifies invalid
  input still returns 2 without echoing its bytes or printing a traceback.
- **Extension policy:** the shared text previously said every consumer ignores
  unknown fields, while the documented lossless importer deliberately requires
  exact fields for each supported record version. The docs now distinguish
  tolerant command-result readers from portable importers that reject fields
  they cannot preserve. Existing strict import behavior and durable data are
  unchanged; closed import shapes evolve through `record_version` changes.
  The shared exit rules now also state the existing successful closed-pipe
  behavior explicitly.

## Contract and evidence

| Boundary | Implementation and retained checks |
| --- | --- |
| UTF-8/LF, compact JSONL, literal Unicode, type discriminators, silent success, statuses 0–3 | `emit_json`; `test_personal_os_convention_fixtures_match_cli`; `test_utf8_streams_are_independent_of_python_io_encoding` |
| Help/version, diagnostics, no traceback, successful consumer-closed pipe | `parse_args`, `main`, `silence_broken_pipe`; `test_help_and_version`, `test_invalid_input_uses_exit_two_and_stderr`, `test_closed_pipe_exits_cleanly` |
| Separate command-result, portable-record, executable, and SQLite versions | Result record constructors use `schema_version: 2`; interchange constructors use `record_version: 5`; executable 0.10.0; SQLite schema 5. Fixture and round-trip tests assert the separate fields. |
| Stdin transaction boundaries and private rejection diagnostics | `import_records`; batch/import atomicity, malformed decoder, record/link validation, and no-input-echo tests |
| Lossless coherent export and idempotent replay | `export_events` uses one read transaction; round-trip, correction-chain, repeated-import, and concurrent-replacement tests use portable JSONL |
| Exact UTC instants and date-only precision | `current_timestamp`, `valid_import_timestamp`; six-digit fixture timestamps, date-only, mixed-precision, DST, and import-shape tests |
| Exact lowercase ASCII activity keys and separate NFC human text | `activity_key`, `display_name`, `replacement_note`, `correction_reason`; invalid-key, display-name, replacement-text, and legacy-preservation tests |
| Explicit path, nonempty command environment, XDG, then home fallback | `database_file`, `database_path`; `test_database_path_precedence` checks overrides, tilde expansion, empty command environment, fallback, and existing-directory permissions |

The fixture test reads UTF-8 bytes, rejects BOM/CR framing, compares import/export
and summary output byte-for-byte, and checks expected diagnostics and version
output. Interchange tests exercise the public streams; a sibling command does
not need to read SQLite tables. Existing tests also preserve legacy printable
keys/text and report their convention deviations without silently rewriting
history.

## Verification

Baseline: `rtk proxy python3 -B -m unittest discover -s tests -v` passed all 59 tests.
The new encoding regression failed on valid fixture import before the fix and
passed after it. The same full acceptance command then passed all **60 tests**
in 48.794 seconds on macOS, Python 3.15.0, SQLite 3.54.1. The existing fixture,
closed-pipe, concurrent-export, import/batch rollback, version, and path tests
all passed. `rtk proxy git diff --check` also passed. Other platform/Python CI
jobs were not rerun for this local audit.

Migration backup semantics and command namespace remain deferred under their
existing proposal triggers. This audit does not activate either workstream.
