# Proposals for `last`

This backlog records deferred decisions for the mature `lastdone` CLI and
possible future personal-OS tools. No implementation proposal is currently active.

## Active proposals

None. The composability contracts were ratified on October 25, 2026. Their
maintained requirements are in the [convention pack](conventions/v1/SPEC.md),
with verification in the [audit record](conventions/v1/AUDIT.md).

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
