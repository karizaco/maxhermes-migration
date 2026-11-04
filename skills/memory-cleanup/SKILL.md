---
name: memory-cleanup
description: Use when running a memory cleanup / rebalancing pass over the agent's MEMORY.md and memory topic files — e.g. the scheduled "Memory cleanup <date>" session, or any time MEMORY.md has grown past its budget. Covers the size targets, the classification rules, the byte-exact edit mechanics (heading-anchor deletion, the 10-topic and 30 KB caps, immutable topic descriptions), the concurrent-writer hazard, and the final summary index. Read BEFORE editing memory.
---

# Memory cleanup — the hot layer and the topic files

A cleanup is a **rebalancing**, not a rewrite: the hot layer keeps the rules, the topic files keep
the depth. The failure mode is not "the file is too big" — it is "the file is big because
detail leaked into it, and it grew again the next day".

## Targets

| Layer | Budget | Note |
|---|---|---|
| `MEMORY.md` | target ≤ 10 KB, hard ceiling 15 KB | one-line rules; everything else is a pointer |
| `memory/<topic>.md` | ≤ 30 KB each | thick knowledge, per domain |
| topic count | 10 max | `memory_topic_create` fails at 11 |
| `memory/.summary.md` | ≤ 4 KB, ≤ 15 entries | the retrieval index; server-enforced |

A starting file over 20 KB needs ≥ 50 % removed in one run. Over 15 KB, ≥ 40 %.

## Order of work

1. **Read `MEMORY.md` and EVERY topic first** (`memory_read`, `memory_topic_read`). Do not start
   editing from the hot layer alone — the whole point is to find what belongs *downstairs*.
2. **Baseline the size of every topic.** They are all near the 30 KB cap; an append that fails
   costs a trim-then-retry loop.
3. **Check for concurrent writers.** Other sessions append to `MEMORY.md` during the day. Re-read
   the size at the end and assume it grew under you.
4. **Compress before deleting** (see the moves below), then dedup, then classify.
5. **Apply** with `memory_edit` / `memory_append`; **verify** with the `new_size_bytes` each call
   returns. If it is still over target, another pass on the largest section.
6. **Regenerate `memory/.summary.md` LAST**, after every other edit, with line numbers re-derived
   from the final file.

## Classification

- **HOT** (`MEMORY.md`) — a rule that applies to every future session; a trap you keep re-learning;
  live state with an owner. One line each, with a pointer to the topic that holds the depth.
- **TOPIC** (`memory/<topic>.md`) — thick knowledge, a per-domain procedure, a measured data path.
  Needs a `description` written like a skill description: it is auto-injected as the retrieval
  index.
- **DELETE** — recoverable from code, git, AGENTS.md/CLAUDE.md, a skill, or a daily digest.
- **UPDATE** — references a stale artifact, a renamed file, or a rule that has since changed.

### The moves, in the order they pay off

1. **MERGE** similar bullets into one denser line.
2. **DOWNSHIFT** the detail to a topic file; leave a one-line pointer in HOT.
3. **STRIP** examples and rationales from HOT — they belong in the topic.
4. **DEDUP** against AGENTS.md / CLAUDE.md / skills / topic descriptions.
5. **DELETE** what the repo already says.

**A rule of thumb:** if the repo has a document for it, point at the repo instead of copying the
prose into memory. Memory is the short index of what the repo cannot tell you.

## Editing mechanics — the byte-exact part

`memory_edit` requires an **exact** `old_string`. The traps, all of which cost real time:

- It **trims whitespace-only parameters**. Never pass one; never `replace_all` a bare space (one
  such call stripped every space out of the file); never let an `old_string` END in whitespace —
  the transport eats the following heading.
- A **literal `\n` sequence inside `old_string` is decoded as a real newline**, so it can never
  match stored text that holds a backslash-n. `new_string` is stored verbatim, so the same bytes
  behave differently on the two sides. **Match around the sequence, never through it.**
- `memory_read` can re-wrap a long line and drops backticks nested inside bold. When a match
  fails, re-derive the true line with `memory_search` (it prints the stored line and its number).
- The rendered text and the stored bytes can differ in quote style (`'` vs `’`) and in bold
  markers. **Diff first, then copy the exact bytes** — a single dropped `**` is a failed edit.

### The heading-anchor deletion trick

To delete a section, do not try to match its body exactly. Replace **the section and the heading
that follows it** with just that following heading:

```
old = "<section heading>\n\n<body>\n\n### Next section heading"
new = "### Next section heading"
```

One edit, no body transcription, no risk of a half-matched body. Do the same when a section is at
the end of the file by folding its content into the previous section.

### The caps

- **`memory_topic_create` fails at 10 topics.** "Insufficient resources, please try again later"
  from a create IS the cap, not a transient outage — do not retry. To split a topic you must first
  free a slot: delete one, or delete-and-recreate a topic (which is also the only way to fix a
  stale `description`).
- **`_append` / `_edit` fail once a body passes 30 KB**, checked on the RESULT — a 29.7 KB file
  rejects a 30.8 KB append. Trim first. `_edit` can **replace** a stale section with a shorter one
  to free bytes; that is cheaper than deleting anything.
- **A topic's `description` lives in metadata, not the body** — only a newly created topic can
  change it. Descriptions are auto-injected, so write them for retrieval: when to READ this.

### Never append a dated section

`memory_append` creates a `### Untitled (YYYY-MM-DD)` heading. A run of those is the main reason
the hot layer outgrows its budget: each is a new heading nothing ever merges or retires.

- To add a rule to an existing section, **insert a bullet** with `memory_edit` under that heading.
- A genuinely new domain becomes a **topic file** (its description does the retrieval), not a HOT
  section.

## The summary index

`memory/.summary.md` is a compressed index of the final `MEMORY.md`: one entry per `###`
section, one line of conclusion each, plus the source line range.

- **Regenerate it LAST** — line numbers shift with every edit, and a stale index points at
  sections that no longer exist.
- Get the line ranges from `memory_search` on `"### "` **after** the last edit.
- Write it with `memory_summary_write`: **two calls** — the first returns a `confirm_token`, the
  second commits with the same content plus that token. The server caps it at 4 KB and rejects a
  mismatch between the two calls.

## Finish

Report what moved and where: sections merged or deleted, detail downshifted into which topic, new
topics created or merged, and the final size. Say plainly what you left alone and why — a topic
that is at its cap and whose content is unique is a legitimate "keep", not a failure.
