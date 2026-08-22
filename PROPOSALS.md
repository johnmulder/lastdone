# Proposals for `last`

These proposals are ordered by when they are likely to pay off. The first group
should be settled before or during the MVP; the later proposals should wait for
usage evidence. They preserve the project's local-first, append-oriented, and
Unix-like goals without turning it into a task manager.

## Before the MVP

### 1. Resolve the executable-name collision

**Gap**

`last` is already a common Unix command for displaying login history. Installing
a new executable with the same name would shadow a system administration tool,
make documentation ambiguous, and weaken the project's claim to compose safely
with a normal shell environment.

**Approach**

Keep `last` as the project concept if desired, but ship an unambiguous executable
such as `lastdone` or `whenlast`. Check the intended macOS, Linux, and BSD targets
before choosing the final name. A `last` shell alias can remain an explicit user
choice rather than an installed default.

**Implementation considerations**

- The package, repository, and executable do not need the same name.
- Update every command example once, before users or scripts depend on it.
- Do not add a runtime dispatcher or wrapper solely to preserve the conflicted
  name.

### 2. Turn the proposed CLI into a behavioral contract

**Gap**

The document names commands and exit codes, but not several observable edge
cases: duplicate events, empty history, future dates, output ordering, broken
pipes, or whether diagnostics can appear on standard output. Those decisions
become compatibility constraints as soon as another command consumes `--jsonl`.

**Approach**

Write a compact command contract and encode it as end-to-end CLI tests. Define
arguments, standard output, standard error, exit status, sort order, and the
JSONL shape for each MVP command. Human output may evolve; JSONL fields and
semantics should be versioned deliberately.

**Implementation considerations**

- Send records only to stdout and diagnostics only to stderr.
- Emit exactly one complete JSON object per line in JSONL mode, including for
  single-record commands.
- Make ordering explicit: newest first for history and bytewise ascending by
  activity key for list output.
- Treat an empty list as successful and a missing named activity as exit code 1.
- Handle a closed downstream pipe without printing a traceback.

### 3. Distinguish an instant from a calendar date

**Gap**

The proposed model stores a timezone-aware timestamp, while `--date 2026-08-20`
supplies only a local calendar date. Turning that date into midnight invents a
time and can move the event to another date when viewed in another timezone.

**Approach**

Represent occurrence precision explicitly. A normal `add` records an RFC 3339
instant; `add --date` records a date-only value. Human summaries can display a
local date for both, while machine output preserves which kind was supplied.

**Implementation considerations**

- Use separate `occurred_at` and `occurred_on` columns with a database check that
  exactly one is set, or an equally explicit representation.
- Record instants in UTC and retain the original offset only if a demonstrated
  display need requires it.
- Define how mixed date-only and timestamp events sort on the same day.
- Calculate day-based intervals from calendar dates, not elapsed 24-hour blocks,
  so daylight-saving transitions do not create surprising results.

### 4. Add schema constraints and tiny, forward-only migrations

**Gap**

SQLite makes storage simple, but the suggested schema accepts malformed names,
invalid temporal values, and silent schema drift. A local database that opens
successfully can still contain data the CLI cannot interpret.

**Approach**

Let SQLite enforce the small invariants the application depends on, and use
`PRAGMA user_version` for numbered, forward-only migrations. Run each migration
inside a transaction before executing the requested command.

**Implementation considerations**

- Reject empty names, impossible occurrence representations, and invalid
  interval values at both the CLI boundary and database boundary.
- Create the database and parent directory with user-only permissions where the
  platform permits it.
- Generate event IDs with a standard-library UUID unless sortable IDs become a
  measured requirement.
- Back up before a destructive migration; avoid an ORM or migration dependency
  for a schema this small.

### 5. Keep the first implementation standard-library sized

**Gap**

The design calls for low complexity, but it does not constrain the implementation
shape. A command framework, ORM, repository layer, and plugin system could add
more surface area than the four-command MVP itself.

**Approach**

Build the MVP with Python's `argparse`, `sqlite3`, `json`, `datetime`, `pathlib`,
and `uuid` modules. Separate only the CLI parsing, database operations, and
formatting that genuinely need independent tests.

**Implementation considerations**

- Prefer a few small modules over a framework-shaped package hierarchy.
- Test through the executable against a temporary database; add focused unit
  tests only for time and interval logic with meaningful edge cases.
- Inject the clock and database path at the boundary so tests remain
  deterministic without a general dependency-injection system.
- Add a formatter and linter only if they remove recurring review work.

### 6. Specify data-location overrides and concurrency behavior

**Gap**

An XDG default is suggested, but scripts, tests, removable backups, and multiple
personal profiles need a predictable way to select a database. Concurrent shell
invocations also need a defined failure mode.

**Approach**

Use one documented precedence order: a `--db PATH` option, then a project-specific
environment variable, then the XDG data directory, then the platform fallback.
Use short SQLite transactions and a modest busy timeout for concurrent writers.

**Implementation considerations**

- Resolve and print the active path in a future `doctor` command, but never add it
  to normal machine output.
- Do not introduce a configuration file until there is a setting that cannot be
  expressed clearly as an option or environment variable.
- Surface lock timeouts as storage errors with actionable diagnostics.
- Test two near-simultaneous `add` operations to confirm neither event is lost.

## Immediately after the MVP

### 7. Provide lossless export, idempotent import, and basic diagnostics

**Gap**

SQLite is easy to copy, but portability and inspectability are only partial if
users must query implementation tables or replace a live database to move data.
The personal-OS integration goal also needs a supported interchange format.

**Approach**

Add `export --jsonl`, `import --jsonl`, and `doctor`. Export every durable field,
including event IDs and occurrence precision. Import should validate the entire
stream and treat an already-present identical ID as a no-op.

**Implementation considerations**

- Stream JSONL rather than loading a whole history into memory.
- Reject an existing ID with different content instead of overwriting it.
- Run an import transactionally so a bad line cannot leave a partial import.
- Keep export records independent of SQLite column names and include a small
  record-format version.
- Have `doctor` check schema version, integrity, permissions, and parseability;
  it should not mutate data unless explicitly asked to repair it.

### 8. Add explicit correction without erasing history

**Gap**

Low-friction capture guarantees occasional mistakes, yet the append-oriented
principle does not say how to correct a wrong date, name, or note. Direct SQL
edits would make history less trustworthy and would not compose with export.

**Approach**

Expose event IDs in history output and support explicit `void` and `replace`
operations. A replacement is a new event linked to the superseded event; a void
records that an event should no longer count. Default queries show the effective
history, with an option to include corrections.

**Implementation considerations**

- Require an event ID, not a fuzzy name-and-date match, for destructive-looking
  operations.
- Store the reason and correction timestamp.
- Keep corrected records in export and machine-readable history.
- Define whether correcting the newest event changes due calculations; the
  effective, non-void history should be the single source of truth.
- Do not build general event sourcing; two explicit relationships are enough.

### 9. Make interval semantics deliberately narrow

**Gap**

`90d` can mean 90 calendar days or 2,160 elapsed hours, and `3mo` cannot be
represented reliably as a fixed number of seconds. The proposed
`expected_interval_seconds` column hides that distinction. Due output is also
undefined for activities with no events or events dated in the future.

**Approach**

Start with whole calendar days only and store `expected_interval_days` as a
positive integer. Determine due status from the user's current local date. Add
calendar months only after a real use case justifies separate month arithmetic.

**Implementation considerations**

- Initially accept a single grammar such as `[1-9][0-9]*d`; reject rather than
  guess at other units.
- Define due as `last occurrence date + interval`, and say whether equality means
  due today or overdue.
- Represent `never recorded`, `future dated`, `due today`, and `overdue` as
  explicit machine-readable states.
- Allow a clock/timezone override in tests to cover leap days and DST boundaries.

### 10. Separate stable ASCII keys from human display names

**Gap**

ASCII-only activity names are shell-friendly but exclude natural names in many
languages. Conversely, silently normalizing unrestricted Unicode keys can merge
distinct names or admit visually confusable identifiers. Notes already need to
handle Unicode safely even if keys remain ASCII.

**Approach**

Keep an immutable, lowercase ASCII activity key for commands and integration,
and add an optional Unicode `display_name` for human output. Preserve notes and
display names as UTF-8 after Unicode NFC normalization; never transliterate or
rewrite a key implicitly.

**Implementation considerations**

- Define the key grammar explicitly, for example lowercase letters, digits, and
  internal hyphens with no leading or trailing hyphen.
- Reject NUL and terminal control characters in all text fields.
- Let JSON serialization emit valid Unicode and test composed versus decomposed
  input, combining marks, emoji, and right-to-left text.
- Make `doctor` report keys imported outside the ASCII contract and Unicode
  normalization deviations without silently changing them.
- Use a display-width-aware library only if alignment defects become a real
  problem; correctness does not require column-perfect output.

### 11. Publish personal-OS conventions as fixtures, not a shared library

**Gap**

The idea identifies shared conventions for dates, JSONL, errors, and exit codes,
but prose alone will drift as sibling commands are implemented. A shared runtime
library, however, would tightly couple otherwise independent tools too early.

**Approach**

Create a small interoperability specification with representative input/output
fixtures. Each command can implement the conventions independently and run the
same fixture checks in its own test suite.

**Implementation considerations**

- Specify UTF-8, RFC 3339 timestamps, JSONL framing, error destination, and common
  field names such as `name` and `occurred_at`.
- Version the interchange contract independently from the executable version.
- Prefer copied or published fixtures over a mandatory shared package.
- Add a shared library only when multiple tools contain the same non-trivial code
  and changes repeatedly need coordinated fixes.

## Usage-driven extensions

### 12. Support one structured reading per event

**Gap**

Some maintenance is better understood by usage than elapsed time. The example
oil-change note (`84,221 miles`) is human-readable but cannot answer how many
miles passed between services. Equipment hours, charge cycles, and page counts
have the same limitation.

**Approach**

After real demand appears, allow an event to carry one optional decimal reading
and unit, for example `--reading 84221mi`. Show the change from the previous
compatible reading. Keep time-based due calculations independent at first.

**Implementation considerations**

- Store the numeric value as canonical decimal text, not binary floating point.
- Maintain a short allowlist of unit spellings or require exact unit equality;
  do not build a general unit-conversion system.
- Reject decreasing cumulative readings unless explicitly confirmed, because
  they often indicate a typo or meter replacement.
- Do not add arbitrary key/value metadata as a substitute for one proven query.
- Usage-based due predictions need a trustworthy current reading source and
  should remain a later, separate proposal.

### 13. Add batch capture through standard input

**Gap**

The single-event command is ideal interactively, but migration from notes or use
inside pipelines would otherwise require one process and one database connection
per event.

**Approach**

Add a batch mode that reads the same versioned JSONL event shape used by import,
validates it, and writes all accepted events in one transaction. Reuse the
single-event validation and insertion path.

**Implementation considerations**

- Prefer one documented JSONL input over a custom delimiter format or CSV dialect.
- Keep `add NAME` as the shortest and best interactive path.
- Make all-or-nothing behavior the default; partial success is difficult for
  scripts to recover from safely.
- Report the failing line number on stderr without echoing sensitive notes.

## Proposals to defer

Notifications, synchronization, tags, aliases, fuzzy matching, a web UI, and a
shared database should remain deferred. None is needed to answer "when did I last
do this?", and each adds a second problem—scheduling, conflict resolution,
taxonomy, ambiguity, hosting, or cross-tool coupling—before the core recording
habit has been proven.
