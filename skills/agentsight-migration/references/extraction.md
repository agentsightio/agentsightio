# Getting the data out

*How* you produce the file is your judgment. The source is the user's system,
you have just read its shape in step 2, and no rule written here would survive
contact with the fourth database you meet. This file is short on purpose: it
names the shapes you will actually find, and the properties the output has to
have whatever you write.

## The four shapes

**One row per message, with a conversation key.** The common relational case.
Group by the key, sort each group by timestamp, and take `started_at` from the
conversation table if there is one — `min(timestamp)` only if there is not
(a Wave 3 question, because a conversation opened before its first message
gives a different duration on the dashboard).

**One row per conversation with the transcript in a blob.** A JSON or text
column holding the whole exchange. The parsing is the work, and the trap is
that the blob's own speaker labels are usually a third vocabulary — neither
yours nor AgentSight's. Map them explicitly; do not pattern-match on `"role"`
and hope.

**A vendor export.** A CSV or JSON dump from a previous platform. Its columns
are a product's internal names, its timestamps are frequently already strings
in some unstated zone, and it usually contains rows that are not messages at
all — system events, typing indicators, delivery receipts. Filter first, then
map.

**A log file, JSONL or plain.** Reconstructing conversation boundaries from a
stream is the hardest of the four and the answer is never "a time gap". Find
whatever the application used as a correlation id; if there genuinely is not
one, say so and stop rather than inventing thread boundaries that put two
customers in one transcript.

## What the output has to be

- **Deterministic.** Running the exporter twice on an unchanged source
  produces the same file. Anything involving `now()`, a dict iteration order,
  or an unsorted `SELECT` breaks this and makes the reconciliation in step 9
  unrepeatable.
- **Streaming, not accumulating.** A history worth migrating does not fit in
  memory twice. Write conversations out as you build them.
- **Split on conversation boundaries.** Never mid-conversation: a part file is
  one upload, and half a transcript is a whole conversation with half its
  messages.
- **Written with `allow_nan=False`**, `ensure_ascii=False`, and UTF-8. The
  first is a correctness rule; the other two keep the file readable and
  smaller.
- **Ordered by timestamp within each conversation**, explicitly sorted, not
  inherited from row order.
- **Outside the repo, or gitignored in the same edit.** These are full
  customer transcripts.

## Read-only, and slowly

The source is very likely still in production. `SELECT` only. Prefer a keyset
walk (`WHERE id > ?  ORDER BY id LIMIT n`) over `OFFSET`, which re-scans; take
the export from a replica if the user mentions one has one. If the table is
large enough that a full scan is a real cost, say so and let the user pick the
window rather than deciding for them.

Make the read-only-ness structural. Ask for a read-only role or a replica DSN
before accepting a read-write one; when the read-write one is all there is,
pin the session so a mistake fails instead of landing:

```sql
SET default_transaction_read_only = on;   -- Postgres, for the session
SET SESSION TRANSACTION READ ONLY;        -- MySQL / MariaDB
```

```python
sqlite3.connect("file:app.db?mode=ro", uri=True)   # SQLite
```

Reading through the source application's own ORM is fine — sometimes it is
the fastest way to see the shape. Letting it change anything is not. A
Django `manage.py` that warns of unapplied migrations, an Alembic head that
is behind, a Prisma schema that has drifted: each is describing the source,
not asking you to update it, and none of them is the migration this skill's
name refers to. The exporter leaves the source exactly as it found it: no
schema change, no status column, no "exported" flag written back.

## A consequence, not a rule

Ten conversations can be assembled by hand. A full history cannot.

Nothing here forbids hand-writing the pilot, and there are sources where
poking at ten rows in a REPL genuinely is the fastest way to see the shape.
But step 9 asks for conversation counts, message counts and a min/max
timestamp reconciled against the same three queries on the source, and that
arithmetic cannot be satisfied at scale by anything but a repeatable
extraction. If you hand-build the pilot, you are writing the exporter
afterwards regardless — usually with less information than you had at step 5.
