# `last` — Personal Maintenance History

## Idea

`last` is a small Unix-style CLI for answering a deceptively useful question:

> **When did I last do this?**

It records recurring real-world activities—changing filters, rotating tires, replacing consumables, servicing equipment, completing household chores, or any other action worth remembering—and makes that history easy to query.

The tool should be fast enough to use casually, simple enough to trust, and composable enough to become one part of a larger Unix-like personal operating system.

## Command Name

The project is named `last`, but its executable is `lastdone`. Unix systems already provide `last` for displaying login history; installing another command under that name would shadow an established administration tool. The project does not install a `last` alias or compatibility wrapper.

---

## Problem

Many recurring tasks are too infrequent to remember accurately but too mundane to justify a dedicated application.

Examples:

- When did I last change the furnace filter?
- How long has it been since I rotated the tires?
- When did I replace the toothbrush head?
- When did I clean the coffee maker?
- When did I last back up a particular device?
- How often have I actually performed a maintenance task?

Calendar reminders solve only part of the problem. They tell you what you *planned* to do, not necessarily what you *did*.

`last` treats completed actions as durable facts.

---

## Core Principle

Recording an event should require almost no ceremony.

```sh
lastdone add furnace-filter
```

Querying should be equally direct.

```sh
lastdone show furnace-filter
```

Example:

```text
furnace-filter
Last: 2026-08-21
Previous: 2026-05-14
Interval: 99 days
```

The system should preserve history rather than merely storing a single “last performed” timestamp.

---

## Design Goals

### 1. Unix-like

`last` should:

- do one thing well;
- work naturally in shell pipelines;
- produce human-readable output by default;
- support stable machine-readable output;
- avoid unnecessary dependencies;
- use meaningful exit codes;
- keep its data portable and inspectable.

### 2. Local-first

The authoritative data belongs to the user.

The first version should require no:

- cloud account;
- hosted service;
- browser UI;
- external API;
- network connection.

### 3. Append-oriented history

Every recorded action is an event.

Do not overwrite prior records merely because a newer event exists.

Historical data enables later questions that the initial implementation may not anticipate.

### 4. Low-friction capture

The tool succeeds only if recording an event is easier than deciding not to record it.

The normal case should be:

```sh
lastdone add <name>
```

### 5. Composable

`last` should eventually interoperate with other personal-OS commands such as:

```text
where       Where is something?
capture     Record a thought or loose input.
decision    What did I decide, and why?
now         What deserves attention now?
```

Shared conventions matter more than shared implementation.

---

## Non-Goals

The initial version is **not**:

- a task manager;
- a calendar;
- a reminder application;
- a home inventory database;
- a full maintenance-management system;
- a mobile app;
- an AI assistant.

Those systems may consume `last` data later.

`last` should remain useful independently.

---

## Proposed CLI

### Record an event

```sh
lastdone add furnace-filter
```

Record an event with an explicit date:

```sh
lastdone add furnace-filter --date 2026-08-20
```

Optional note:

```sh
lastdone add furnace-filter --note "MERV 11"
```

---

### Show history summary

```sh
lastdone show furnace-filter
```

Possible output:

```text
furnace-filter
Last: 2026-08-21
Previous: 2026-05-14
Interval: 99 days
Occurrences: 5
```

---

### Show full history

```sh
lastdone history furnace-filter
```

Example:

```text
2026-08-21  MERV 11
2026-05-14
2026-02-10
2025-11-08
```

---

### List known activities

```sh
lastdone list
```

Possible output:

```text
coffee-machine-clean
furnace-filter
oil-change
smoke-detector-battery
toothbrush-head
```

---

### Define an expected interval

```sh
lastdone set furnace-filter --every 90d
```

This does not create a scheduled task. It adds metadata describing how frequently the action is normally expected.

---

### Show items becoming due

```sh
lastdone due
```

Example:

```text
furnace-filter       99 / 90 days    OVERDUE
oil-change          142 / 180 days
smoke-detector       73 / 180 days
```

Possible filtering:

```sh
lastdone due --overdue
```

---

### Machine-readable output

Commands that return structured information should support:

```sh
lastdone show furnace-filter --json
```

or, preferably for the wider personal-OS convention:

```sh
lastdone show furnace-filter --jsonl
```

Example:

```json
{"name":"furnace-filter","last":"2026-08-21","previous":"2026-05-14","interval_days":99,"occurrences":5}
```

---

## Data Model

The conceptual model should remain small.

### Event

An event records that something happened.

```text
id
name
occurred_at or occurred_on
note
```

Example:

```json
{
  "id": "01K...",
  "name": "furnace-filter",
  "occurred_at": "2026-08-21T20:32:00Z",
  "occurred_on": null,
  "note": "MERV 11"
}
```

### Activity metadata

Optional metadata describes an activity.

```text
name
expected_interval
description
tags
```

Example:

```json
{
  "name": "furnace-filter",
  "expected_interval": "90d",
  "description": "Replace main HVAC return filter",
  "tags": ["house", "maintenance"]
}
```

Events remain valid even if no metadata exists for the activity.

---

## Storage

### Recommended first implementation: SQLite

SQLite offers:

- atomic writes;
- simple querying;
- excellent Python standard-library support;
- easy backup;
- low operational complexity;
- room for future indexing and metadata.

The schema should use `PRAGMA user_version` for numbered, forward-only
migrations. Each migration and version update should share one transaction.
Before a migration rebuilds a table, preserve a user-only recovery copy of the
database.

Suggested default location:

```text
~/.local/share/last/last.db
```

Configuration could follow XDG conventions where available.

The database should remain an implementation detail. The CLI is the stable interface.

---

## Suggested Schema

```sql
CREATE TABLE events (
    id TEXT NOT NULL PRIMARY KEY
        CONSTRAINT events_id_nonempty CHECK (length(id) > 0),
    name TEXT NOT NULL
        CONSTRAINT events_name_nonempty CHECK (length(name) > 0),
    occurred_at TEXT,
    occurred_on TEXT,
    note TEXT,
    CONSTRAINT events_occurrence_exactly_one CHECK (
        (occurred_at IS NOT NULL) <> (occurred_on IS NOT NULL)
    ),
    CONSTRAINT events_occurred_at_valid CHECK (
        occurred_at IS NULL OR (
            length(occurred_at) = 27
            AND occurred_at GLOB (
                '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T' ||
                '[0-9][0-9]:[0-9][0-9]:[0-9][0-9].' ||
                '[0-9][0-9][0-9][0-9][0-9][0-9]Z'
            )
            AND coalesce(
                datetime(substr(occurred_at, 1, 19), '+0 seconds') =
                    replace(substr(occurred_at, 1, 19), 'T', ' '),
                0
            )
        )
    ),
    CONSTRAINT events_occurred_on_valid CHECK (
        occurred_on IS NULL OR (
            length(occurred_on) = 10
            AND occurred_on GLOB
                '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
            AND coalesce(
                date(occurred_on, '+0 days') = occurred_on,
                0
            )
        )
    )
);

CREATE INDEX idx_events_name
ON events(name);

CREATE TABLE activities (
    name TEXT PRIMARY KEY,
    expected_interval_seconds INTEGER
        CONSTRAINT activities_interval_positive CHECK (
            expected_interval_seconds IS NULL OR expected_interval_seconds > 0
        ),
    description TEXT
);
```

Tags can be postponed until there is a demonstrated use case.

---

## Naming

Activity names should behave like lightweight Unix identifiers:

```text
furnace-filter
jeep-oil-change
coffee-machine-clean
xander-nail-trim
```

Recommended normalization:

- lowercase;
- hyphen-separated;
- ASCII by default;
- exact names stored and queried consistently.

Avoid forcing a taxonomy prematurely.

---

## Time Semantics

Events should preserve the precision the user supplied. A normal add records a
timezone-aware UTC instant, while `--date` records only a calendar date.

Human-oriented commands may usually display local dates when exact time is unimportant.

For example:

```sh
lastdone add furnace-filter
```

records the full current timestamp, while:

```sh
lastdone add furnace-filter --date 2026-08-20
```

records `2026-08-20` without inventing midnight or a timezone. Meanwhile:

```sh
lastdone show furnace-filter
```

may display:

```text
Last: 2026-08-21
```

Machine-readable output should expose both occurrence fields with exactly one
populated. Human output renders instants in local time and date-only events
unchanged. Mixed history sorts by displayed calendar date; exact instants precede
date-only events on the same date. Intervals compare calendar dates rather than
elapsed 24-hour blocks.

---

## Exit Codes

A simple convention:

```text
0   success
1   requested activity not found
2   invalid arguments or input
3   storage/configuration error
```

Avoid using exit codes to encode ordinary states such as “overdue.”

Structured output should represent those states explicitly.

---

## First Useful Version

The MVP should be intentionally narrow.

### Implementation shape

The first implementation is one executable built entirely from Python's
standard library. CLI parsing, SQLite operations, and output formatting remain
plain functions; they should become separate modules only when independent use
or testing makes that simpler than the single file.

Contract tests invoke the executable against temporary databases. The `run()`
boundary also accepts the current time and database path directly so focused
time tests can be deterministic without a dependency-injection framework. A
formatter, linter, command framework, ORM, repository layer, and plugin system
remain deferred until recurring maintenance work demonstrates a need.

### Required

```text
lastdone add NAME
lastdone show NAME
lastdone history NAME
lastdone list
```

Plus:

```text
--jsonl
--help
--version
```

### Nice immediately after MVP

```text
lastdone set NAME --every INTERVAL
lastdone due
lastdone add NAME --date DATE
lastdone add NAME --note TEXT
```

### Explicitly defer

- recurring notifications;
- shell completion;
- fuzzy matching;
- aliases;
- tags;
- categories;
- web UI;
- mobile interface;
- synchronization;
- AI-generated recommendations;
- NFC/QR integration.

These should be added only when actual usage demonstrates the need.

---

## Examples

### Household maintenance

```sh
lastdone add furnace-filter
lastdone add coffee-machine-clean
lastdone add smoke-detector-test
```

### Vehicle maintenance

```sh
lastdone add jeep-oil-change --note "84,221 miles"
lastdone add jeep-tire-rotation
```

### Consumables

```sh
lastdone add toothbrush-head
lastdone add water-filter
```

### Pet care

```sh
lastdone add xander-nail-trim
lastdone add xander-bath
```

The tool should remain agnostic about the domain.

---

## Integration with the Personal OS

`last` should eventually be useful as both a human-facing command and a data source for other commands.

Example:

```sh
now
```

could consume:

```sh
lastdone due --jsonl
```

and incorporate overdue maintenance into a broader daily summary.

Likewise:

```sh
where show furnace-filter
```

might answer where replacement filters are stored, while:

```sh
lastdone show furnace-filter
```

answers when one was last installed.

The commands remain independent but become more useful together.

---

## Architectural Principle for the Larger System

The personal OS should prefer:

> **small commands over one large application, shared conventions over shared complexity, and durable local data over proprietary state.**

A command should expose enough structured output that another command—or an LLM—can use it without needing privileged internal access.

That implies common conventions across tools for:

- dates and timestamps;
- JSONL output;
- configuration paths;
- identifiers;
- exit codes;
- version reporting;
- error formatting.

`last` can serve as the reference implementation for those conventions.

---

## Open Questions

Questions worth answering through use rather than up-front design:

- Should activity names support aliases?
- Is JSONL preferable to conventional JSON for single-record queries?
- Should expected intervals allow calendar units such as `3mo`, or only durations?
- Should notes remain free text or support arbitrary key/value metadata?
- Should events ever be editable, or only corrected through explicit replacement/tombstone events?
- Should all personal-OS tools eventually share one database, or merely interoperable formats?

The default answer should be: **do not generalize until usage requires it.**

---

## Success Criterion

`last` succeeds if, after several months of use, questions such as:

> “When did I last do that?”

become trivial to answer—and recording the answer at the time felt easier than trying to remember it later.
