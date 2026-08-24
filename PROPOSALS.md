# Proposals for `last`

These proposals are ordered by when they are likely to pay off. They treat
`lastdone` as both a small, mature Unix-style CLI and a likely reference for
future personal-OS tools. The active work is about correctness and composable
contracts, not new end-user features.

## Active proposals

### P1 / Do soon: Make partial activity metadata updates atomic

**Gap**

`set` reads the existing activity row to preserve omitted fields, then upserts a
complete row. No transaction encloses that read-modify-write sequence. Concurrent
`set --every` and `set --display-name` commands can therefore read the same stale
row and silently overwrite each other's independent change.

**Why it matters**

This is a lost-update correctness bug, not a throughput optimization. A command
that promises to preserve an omitted field must do so even when another writer
updates that field concurrently. The reference CLI should establish that partial
metadata updates do not silently discard committed data.

**Approach**

Begin one `BEGIN IMMEDIATE` SQLite transaction before reading the activity row,
then merge, upsert, and commit inside that transaction. This matches the existing
write paths and is the smallest fix.

**Implementation considerations**

- Reuse SQLite's existing transaction support, five-second busy timeout, and
  actionable storage diagnostic. Do not add retries or a transaction framework.
- Roll back on failure and emit JSONL only after the commit succeeds.
- Preserve the current idempotent upsert, omitted-field semantics, and record
  shape.
- This requires no ORM, schema migration, repository layer, or new abstraction.

**Tests / acceptance criteria**

- A deterministic two-writer regression updates the interval and display name
  independently under contention and verifies that the final row contains both
  committed values.
- Existing single-command behavior, including silent human success and JSONL
  output after commit, remains unchanged.
- A lock timeout still returns the documented storage error without a traceback
  or partial update.

### P1 / Do soon: Give export and doctor one coherent read snapshot

**Gap**

`export` reads events, corrections, and activities with separate queries and no
explicit read transaction. A concurrent replacement between phases can produce
a correction whose replacement event is absent, making a successful export
impossible to import. `doctor` similarly performs structure, integrity,
parseability, convention, and count queries without fixing one database state.

**Why it matters**

A successful export must represent one coherent database state and be accepted
by `import`. That is a backup and portability guarantee, not merely prettier
reporting. A completed doctor report should likewise describe one state rather
than combine checks and counts from different moments.

**Approach**

Open one ordinary SQLite read transaction before the first database read and
hold it through the final export query or doctor check. Continue streaming rows;
there is no need to load the database into memory. Commit the read transaction
on success and roll it back or close it on failure.

**Implementation considerations**

- A deferred read transaction is sufficient. Do not acquire a write lock,
  change journal mode, or introduce a snapshot abstraction.
- Keep `doctor` read-only, non-creating, non-migrating, and non-repairing.
- Preserve export ordering, import compatibility, the existing busy timeout,
  and successful closed-pipe behavior.
- Prefer a few local transaction statements in the two handlers over a generic
  transaction helper.

**Tests / acceptance criteria**

- Every successful export can be imported into a fresh database and exported
  again byte-for-byte, including events, corrections, and activity metadata.
- If the existing test harness can interleave a replacement without production
  hooks, add one deterministic regression at the query boundary and verify that
  the export is wholly before or wholly after the replacement, never mixed.
  Do not build barriers, a fault-injection framework, or elaborate concurrency
  infrastructure solely for this race.
- Doctor retains its documented output and exit behavior while its checks and
  counts come from one snapshot.

### P2 / Establish the personal-OS composability contracts

**Gap**

The CLI contract, the versioned `conventions/v1` pack, implementation, and
fixtures already encode most of the right Unix boundaries. Before `lastdone`
becomes precedent for `where`, `capture`, `decision`, `now`, and other tools,
those existing choices should be reviewed together and ratified as a small,
explicit contract. Otherwise sibling commands may copy incidental behavior or
couple directly to `lastdone`'s SQLite schema.

**Why it matters**

Shared edge conventions let small independent commands compose without a shared
database, runtime, plugin system, or framework. Stabilizing these conventions
while there is one mature implementation is cheaper than reconciling several
incompatible tools later.

**Approach**

Audit the implementation against `CLI.md`, `README.md`, and
`conventions/v1/SPEC.md`; resolve only demonstrated drift. Ratify the following
conventions as the precedent future tools may copy:

1. **Streams and diagnostics:** UTF-8 and LF; results on stdout; diagnostics on
   stderr; success is silent on stderr; failure is silent on stdout except for a
   completed diagnostic report such as unhealthy `doctor`; no terminal-control
   sequences or tracebacks.
2. **Exit status:** 0 for success, 1 for a requested resource or state not found,
   2 for invalid arguments or input, and 3 for storage, configuration, or
   integrity failure. Ordinary domain states belong in structured output. A
   consumer-closed stdout pipe is a successful early exit.
3. **JSONL and versions:** machine output is one compact object per line with a
   `type` discriminator. Command results use `schema_version`; portable
   interchange uses a separately evolving `record_version`; both are independent
   of executable and SQLite schema versions. Consumers ignore added fields;
   removal, rename, or changed meaning requires a version change.
4. **Pipelines and interchange:** commands that accept streams read JSONL from
   stdin and apply their documented transaction boundary; producers stream JSONL
   to stdout. Export is lossless, coherent, re-importable, and idempotent on
   replay. Rejected input is not echoed. SQLite is private storage, not an
   integration API.
5. **Time and identity:** exact instants are UTC RFC 3339 timestamps with six
   fractional digits and `Z`; date-only facts remain `YYYY-MM-DD` and never gain
   an invented timezone. `name` is a stable machine identifier with an explicit
   command-owned grammar. `lastdone` uses exact lowercase ASCII activity keys and
   never silently rewrites them; optional human text is separate and NFC
   normalized.
6. **Configuration and discovery:** explicit path option, then non-empty
   command-specific environment variable, then `$XDG_DATA_HOME`, then
   `~/.local/share`. Each tool owns its leaf directory and database. `--help`
   succeeds on stdout, and `--version` emits exactly `PROGRAM MAJOR.MINOR.PATCH`
   plus one LF.

Future tools should reuse these boundaries while owning their domain records,
identifier grammar, storage, and behavior. They should not require knowledge of
`lastdone` tables or import its code.

**Implementation considerations**

- Treat the existing convention pack and byte fixtures as the starting point;
  do not extract a library, shared runner, base command, or generalized framework.
- Keep the public boundary at CLI streams and documented records. Downstream
  tools must be able to consume `lastdone` without opening its SQLite database.
- Change a convention only for a demonstrated inconsistency or ambiguity, not to
  anticipate hypothetical sibling features.
- This proposal adds no user-facing command, option, record type, or database
  field.

**Tests / acceptance criteria**

- The implementation, CLI contract, convention pack, README examples, and
  byte-for-byte fixtures agree on the conventions above.
- Retain a black-box fixture test covering compact JSONL, Unicode, timestamp
  precision, stdout/stderr separation, version output, and exit statuses 0-3.
  Add only small cases for actual gaps found by the audit.
- Export/import tests exercise the documented interchange rather than requiring
  a downstream consumer to understand the SQLite schema.
- The convention pack remains copyable documentation and fixtures, not a runtime
  dependency shared by future tools.

## Deferred / backlog

### Review migration backup failure semantics before the next schema migration

**Status:** Deferred until another schema migration needs a recovery copy.

Current migrations mutate the authoritative database inside SQLite transactions,
so a failed migration rolls back the primary database. There is no demonstrated
current path by which backup publication corrupts that authoritative database.
The remaining concern is narrower: an interrupted or permission-failed backup
creation may leave an unreliable recovery artifact that a later run mistakes for
a completed one.

Before the next migration that requires a backup, review whether migration must
stop when the backup cannot be proven complete and private. Prefer SQLite's
existing backup and transaction guarantees plus a small local check. Do not build
a transactional backup-publication subsystem, fault-injection framework, or
multi-migrator coordination machinery without evidence of risk to the primary
database.

## Architectural question, not current implementation work

### Command namespace and naming

The project is conceptually named `last`, while the executable is `lastdone`
because Unix already provides a `last` command. Do not rename the executable or
add a `last` alias now.

Before many sibling tools exist, decide whether the personal OS should use
independent bare executables such as `lastdone`, `where`, `capture`, `decision`,
and `now`, or one shared namespace with subcommands. That decision affects name
collisions, discovery, global options, and installation, but it does not require
implementation work in this project today.

## Continue not to build

Reminders or scheduling, cloud sync, accounts, web or mobile UI, AI features,
tags or taxonomy not required by current code, aliases, fuzzy matching, shared
databases between personal-OS tools, plugin systems, and generalized framework
extraction remain out of scope. Each adds a second problem before the core CLI
contracts require it.

## Ordered implementation sequence

1. Enclose `set`'s metadata read-modify-write in one immediate transaction and
   add the smallest useful lost-update regression.
2. Enclose `export` and `doctor` reads in coherent SQLite snapshots; keep the
   concurrency test simple and preserve export round-trip coverage.
3. Audit and ratify the existing personal-OS convention pack and fixtures,
   changing only demonstrated contract drift.

Do no migration-backup work until the next relevant schema migration, and make
no command-namespace change in `lastdone` now.
