# Proposals for `last`

These proposals are ordered by when they are likely to pay off. Later proposals
should wait for usage evidence. They preserve the project's local-first,
append-oriented, and Unix-like goals without turning it into a task manager.

## Usage-driven extensions

### 1. Add batch capture through standard input

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
