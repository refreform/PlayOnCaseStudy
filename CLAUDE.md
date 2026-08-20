# Project Norms — PrepCast Case Study

Process only; no domain knowledge lives here. Domain knowledge lives in `dev_docs/` — start at
`dev_docs/INDEX.md`, and read `dev_docs/wiki/README.md` first if this is a new session.

These norms were derived over four months of forecasting work and are kept because they
demonstrably prevented specific failures — each rule notes the failure it exists to stop.
Instantiated for this project by WP-001 (2026-08-18), which also records what was adapted.

This file is deliberately **self-contained**: one file, no companion templates to copy. The
skeletons in §1 are embedded here rather than shipped as files so that the structure travels
with the norms.

---

## 1. Bootstrap: what to create on day one

A new project is not set up until these exist. Create them in this order.

### 1.1 `dev_docs/INDEX.md`

The single map of the project's documentation. Every other doc is reachable from here, and a
doc that isn't listed here is presumed dead.

Create it verbatim from this skeleton, then fill it in:

```markdown
# <Project> — Documentation Index

## 1. Purpose and scope
What this project is, and — equally important — what it is not.

## 2. Active docs
One line per doc, with the question that doc answers.

### wiki/
### domain/
### project/

## 3. Data sources / systems
Where the inputs live, who owns them, and any access notes.

## 4. Conventions
Naming, paragraph numbering, and footer format — see `CLAUDE.md` §4.
Work-package naming and status values — see `CLAUDE.md` §3.1.

## 5. Work packages
| WP | Date | Description | Status | Supersedes | Superseded by |
|----|------|-------------|--------|------------|---------------|

## 6. Graveyard
Superseded work kept for reference only. **Do not build on anything listed here.**

Last verified: YYYY-MM-DD
```

At the start of a session, if that footer is more than thirty days old, say so out loud (§8.1).

### 1.2 `dev_docs/` folder layout

- `wiki/` — orientation. A `README.md` a new instance reads first: what we're doing, what prior
  work exists, and **which prior claims are and aren't trustworthy**. This last part matters
  most; without it every new instance re-derives settled decisions or trusts a retracted one.
- `domain/` — the durable subject-matter docs. One topic per file.
- `project/` — how the current work is organized: roadmap, open questions, validation plan.
- `changelog/` — one file per work package, append-only (§3).
- `archive/` — superseded code and rejected experiments, with a doc explaining why each is here.

Every work-package file in `changelog/` starts from this skeleton (naming and status values in
§3.1):

```markdown
---
id: WP-001
date: YYYY-MM-DD
status: active
supersedes:
superseded_by:
---

# WP-001 — <short title>

## What changed
## Why
## Files touched
## What this supersedes, and why it was wrong
## Open threads
```

### 1.3 `.claude/parking-lot.md`

A short-lived working queue for threads dropped to stay on one topic. It sits **outside**
`dev_docs/` deliberately: no work package, no `Last verified:` footer, and items are deleted
once resolved. It is a queue, not a record.

Deleting a resolved item is not a loss of history: **the item's outcome moves into the WP that
resolved it** (§3.1) before it leaves the lot. If an item is dropped without being resolved,
say so in the WP rather than letting it vanish silently. This is the one file exempt from the
append-only rule, because it is the only file that records intent rather than fact.

### 1.4 The gotchas section of this file

Reserve it from day one, even empty. See §6 — it is the highest-value section in the file and
it can only be written by discovering things the hard way.

---

## 2. The change-summary confirmation gate (STRICT)

Before any file edit or creation:

1. Summarize what you're about to do — **every file you plan to touch, and why**.
2. Ask for confirmation. Wait. No exceptions, however small the change feels.
3. If the change requires updating multiple docs (§3) and that can't fit in one response,
   say so **before starting** — not halfway through.

**One gate per bundle, itemized.** An atomic update (§3.2) touches several files, and they are
confirmed together in a single numbered list rather than one gate per file. The list is
itemized so the owner can approve a subset — "do one through five, skip six" is a normal
answer, and anything not approved is not written.

Why: a written file isn't a draft. It's the context every later reader treats as truth,
including future instances of you.

---

## 3. Documenting the change (STRICT)

Every code or schema change is documented **before the work closes**, in the same response as
the change itself.

### 3.1 Work packages are append-only files

Append a new file to `dev_docs/changelog/`, named `WP-NNN-short-slug.md` — a zero-padded
three-digit number, never reused, plus a kebab-case slug. Frontmatter keys are `id`, `date`,
`status`, `supersedes`, `superseded_by` (skeleton in §1.2).

`status` is exactly one of:

- `proposed` — written up, not yet started
- `active` — in progress
- `closed` — done, and still the current answer
- `superseded` — replaced by a later WP; `superseded_by` must be filled in
- `rejected` — tried and abandoned; the owner declares this, not you (§9)

**Never edit an existing WP file.** A revision is a new file that references the old one via
`supersedes` / `superseded_by`. The single exception is filling in the `superseded_by` key of
the older file, which is a pointer, not a rewrite.

Why append-only: an edited history is not a history. When a result turns out wrong six weeks
later, the only way to find out what was actually believed at the time is a record nobody
rewrote.

### 3.2 Atomic update — code, docs, comments, and visuals move together

The same response that changes the code updates:

- the affected `domain/` and `project/` docs;
- the `Last verified:` footer on every doc touched (§4);
- the `INDEX.md` work-package table;
- **any chart or figure whose numbers the change moves** — a changed formula, filter, cutoff,
  horizon, or validation scheme. A chart drawn on a superseded scheme is worse than no chart,
  because it reads as current. "The old chart is still interesting" is not a reason to leave it
  stale; if the old version is a deliberate comparison, keep both and say in a comment which
  is which.
- **comments on the code you changed.** Do *not* touch comments on sections you didn't modify —
  they may encode context you don't have.

If a cross-cutting convention changed, update this file's gotchas section too.

If all of that can't fit in one response, flag it and split across turns — but never leave the
docs drifted from the code silently.

### 3.3 The work-package table

`INDEX.md` carries a table of every WP: identifier, date, one-line description, status, and
supersedes/superseded-by links (§1.1). It's the index into the changelog; the changelog files
are the detail.

---

## 4. One place per topic, and paragraph numbering

Two rules that together prevent documentation and schema drift:

1. **Exactly one home per topic.** If two docs both explain the tier split, they will disagree
   within a month and you will confidently cite the wrong one.
2. **Number the paragraphs** — `§1`, `§3.2` — the way the Catholic catechism does, and
   cross-reference by number rather than by restating content. A cross-reference that copies
   the content is a second home for the topic in disguise.

Every doc ends with a `Last verified: YYYY-MM-DD` footer. Update it whenever you touch the doc,
even for a small edit — a stale footer on accurate text is a cheap error; a fresh footer on
stale text is an expensive one.

---

## 5. Delegation (subagents)

Delegation is **opt-in**. Don't spawn an agent or a workflow unless asked. When asked:

1. **Never delegate past the confirmation gate (§2).** A subagent must not create or edit files
   before the owner has confirmed the change summary. Read-only research delegates freely;
   writes don't. Same for a judgment call the owner asked *you* for — decide it, don't farm it out.
2. **Specify the outcome, not the method.** Subagents inherit no conversation context, so every
   prompt needs the what, the why, and explicit acceptance criteria. Under-specified goals are
   the top documented cause of multi-agent failure — but over-constrained prompts degrade
   performance measurably too.
3. **Verify outputs, don't supervise process.** Let a delegate run, then check its work before
   relaying. Its report never reaches the owner unless you relay it, and unchecked parallel
   agents amplify errors several-fold.
4. **Fan out only on decomposable work.** Two to five delegates when the sub-parts are genuinely
   independent; a single agent when the work is sequential. Coordination cost grows faster than
   parallelism buys.
5. **A delegate that finds a doc/code contradiction reports it and stops.** It neither fixes the
   doc nor works around it — it surfaces it in its report, and you relay it to the owner (§8.2).
   A subagent has no view of why the doc says what it says, so a silent reconciliation by a
   delegate is the version of this failure that is hardest to detect later.

---

## 6. Gotchas (reserve this section; fill it as you learn)

The most valuable section in this file and the only one that can't be written up front. It
holds things **not inferable from the code alone** — behaviors of a data source, a type that
silently coerces, a flag whose value isn't what its name suggests, two similar-looking inputs
that are constantly confused.

Rules for a good gotcha entry:

- State the wrong belief, then the correct one. "You will assume X; it is actually Y."
- Give the fix inline, not a pointer to the fix.
- Cross-reference the full treatment by paragraph number (§4).
- Say when it was last re-tested. Gotchas rot, and a retracted gotcha is worse than none —
  note corrections in place rather than deleting the history of the wrong version.

Anything that burned an hour and would burn the next instance an hour belongs here.

### 6.1 Timestamps arrive in THREE formats, and not only in playback_events

**Corrected 2026-08-18 (WP-002).** The first version of this entry said "two formats, in
`playback_events`". Both halves were wrong, and the wrong version is recorded here because it
is exactly the mistake the next person will make: find two encodings, stop looking, ship.

`playback_events.event_ts` carries three: ISO-8601 with `Z` (54.9%), ISO-8601 space-separated
with **no timezone marker at all** (25.5%), and Unix epoch seconds (19.7%). And
`subscriptions.event_effective_ts` has the same problem — 1,225 of 8,014 rows use the
timezone-less form. A naive cast nulls or misdates whole populations, and epoch seconds read as
a date land decades off, not minutes.

The timezone-less form is the dangerous one: treating it as UTC is an **assumption**, not a
reading. The owner made that call knowingly; it is a live question for the source team.

Tempting dead end: the format is *not* correlated with `app_version` or `device_type` — all
three spread evenly across all six of each. It is not one bad client build, and looking for one
wastes an hour.

**Fix:** use the `normalize_timestamp` macro in `playon_dbt/macros/`. Branch before casting —
`^[0-9]+$` is epoch seconds, `%T%Z` is ISO-with-Z, everything else is assumed-UTC — and emit a
`*_source_format` column beside it so the assumption stays auditable. Output naive `TIMESTAMP`,
not `TIMESTAMPTZ`, which renders differently per reader's session timezone. Full treatment:
`dev_docs/domain/source-extracts.md` §6.1.

*Last re-tested: 2026-08-18 — profiled across all 216,045 and 8,014 rows, 0 parse failures.*

### 6.2 `asset_catalog.sport` mixes full words and abbreviations

You will assume `sport` is a clean categorical. Observed: `BASEBALL` alongside `VB`, while the
matching `title` spells out "Volleyball". Grouping by `sport` splits one real sport in two.

**Fix:** an explicit mapping in the standardized layer, cross-checked against the sport word in
`title` — not a `LIKE` guess. Enumerate the distinct set first. Full treatment:
`dev_docs/domain/source-extracts.md` §6.2.

*Last re-tested: 2026-08-18 (observation from two rows only — not yet profiled).*

### 6.3 `subscriptions.subscription_id` is not unique, by design

It is named like a key, so every instinct says test it for uniqueness. That test fails
correctly — the file is an append-style change log — and "fixing" it by deduplicating destroys
the very subscription history the retention question depends on.

**Fix:** treat it as a log. Uniqueness belongs on (`subscription_id`, `event_effective_ts`) —
verify that holds — and the collapse to a dimension is a deliberate SCD decision, owner-made
(§9). Full treatment: `dev_docs/domain/source-extracts.md` §6.3.

*Last re-tested: 2026-08-18 — confirmed unique 8,014/8,014 on the pair.*

### 6.4 Bare `dbt` on PATH is dbt-fusion, not dbt-core

The user's `.local/bin` sits at **position 1** on PATH and contains dbt-fusion's `dbt.exe`. An
unactivated shell therefore resolves `dbt` to fusion 2.0.0-preview — a different engine — every
time.

It does not fail loudly. Fusion parses this project happily and emits only a benign warning
about unused config paths. The version banner is the only tell.

**Fix:** run `./.venv/Scripts/dbt.exe` or `uv run dbt`. In PyCharm: Settings → Tools → Terminal
→ tick "Activate virtualenv", then open a *new* tab — setting the project *interpreter* does
not activate the *terminal*. Before any real run, confirm `dbt --version` reports
`Core: - installed: 1.12.2`.

*Last re-tested: 2026-08-18.*

### 6.5 The DuckDB UI takes an exclusive lock on the database file

While `playon_dbt/scripts/duckdb_ui.py` is running, **nothing else can open `playon.duckdb`** —
not `dbt build`, not a `read_only=True` connection, not even `cp`. You will assume concurrent
readers are fine because DuckDB's documentation describes them; on this Windows filesystem they
are not.

The error is `IO Error: ... being used by another process`, which reads like corruption and is
not. Helpfully, DuckDB names the offending process and PID in the error text — read it before
assuming anything is broken.

**Fix:** stop the UI before running dbt and restart it afterwards. If a dbt run fails with an IO
error, look for a stray UI process before debugging anything else:

```
tasklist | grep -i python          # find it
taskkill //PID <pid> //F           # release the lock
```

**Two ways to strand a lock holder, both seen on 2026-08-18:**

1. Backgrounding the UI with a bare `&` inside a compound shell command. The process survives
   the command that launched it but is not tracked, so it holds the lock invisibly and cannot
   be stopped through the normal task controls. Launch it as a properly backgrounded task
   instead, so it has an id you can stop.
2. Assuming a failed launch means nothing started. A UI launch that appears to fail (because a
   health check ran before it finished binding) may still be holding the file moments later.
   Check the port before concluding it died.

*Last re-tested: 2026-08-18 — including both stranding modes above.*

---

## 7. Not applicable to this project

The template's candidate-scoring and rejected-experiments process. It applies only to projects
with a modeling or experimentation loop, and this is a data-engineering exercise — the template
itself says to skip it for that case. Declared out of scope by the owner in WP-001.

The section keeps its number rather than being deleted: §1.1, §3.1 and §8 cross-reference sections
by number, and renumbering would break those references — the exact drift §4 exists to prevent.

Note that §7.1's principle survives its section, in a different form: the owner declares the
verdict, not you. Here that generalizes past failed candidates to every design decision — see §9.

---

## 8. Session protocol and other standing rules

### 8.1 Opening and closing a session

- **Opening:** read `dev_docs/INDEX.md` first, and if its `Last verified:` footer is more than
  thirty days old, say so before starting work. Doc drift is worth surfacing before it bites,
  and the start of a session is the only moment it costs nothing to mention.
- **Closing:** before going idle, confirm the changelog is current — every change made this
  session has its WP file, and the `INDEX.md` table matches. Atomic update (§3.2) is a rule
  about a single response; this is the check that catches the response where it was skipped.

### 8.2 Standing rules

- If a doc contradicts the live code while you're working on something else, **flag it** —
  don't silently fix it and don't silently work around it. Same rule for a delegate (§5.5).
- Deliverables that need to survive outside the toolchain (a model another team runs in Excel,
  a query someone runs by hand) must stay usable there. Note that constraint per project.
- Prior-generation work is **reference, not inheritance**. Say explicitly in the wiki README
  which decisions carry forward and which must be re-derived. Anything not on the carry-forward
  list gets re-derived rather than ported because it happens to be written down.

---

## 9. Project specifics

Keep this section permanently; a `TODO:` left standing is a visible signal that setup is
unfinished.

- **What this project is building.** A dbt + DuckDB dimensional model over four raw CSV extracts
  from PrepCast, a fictional high-school sports streaming service, answering how engaged
  viewership relates to subscription retention. It is a ~4-hour interview case study for a
  Senior Analytics Engineer role, delivered as a ~30-minute deck plus work artifacts.

- **Reference documents** — key docs by task:
  - *New session, start here* → `dev_docs/wiki/README.md`, then `dev_docs/INDEX.md`
  - *What's in the raw files, and what's wrong with them* → `dev_docs/domain/source-extracts.md`
  - *What counts as an engaged view* → `dev_docs/domain/engaged-view.md`
  - *What to build next, and what to drop* → `dev_docs/project/roadmap.md`
  - *What we assumed and what we'd ask* → `dev_docs/project/open-questions.md`
  - *How we prove the model behaves* → `dev_docs/project/validation-plan.md`
  - *The original brief* → `Case_Study_-_Senior_Analytics_Engineer.docx` (repo root)

- **Data sources.** Four local CSVs in `data/`, provided with the case study; intent documented
  in `data_dictionary_(1).docx`. No external data or warehouse access — the prompt forbids it.
  Engine is dbt-core + DuckDB reading the CSVs directly (WP-001). PrepCast's stated production
  stack is Snowflake + SQLMesh; where a modeling choice would differ, note it as a talking point
  rather than building for it. Details in `dev_docs/INDEX.md` §3.

- **Teaching split — who decides what.** The load-bearing rule of this project, and it overrides
  any delivery-layer default.

  **The owner is the candidate being evaluated.** Every design decision is theirs: what "engaged
  view" means and where its threshold sits, the shape of the dimensional model, the SCD
  treatment of the subscription log, which data-quality issues get fixed versus flagged, and
  what gets cut when time runs out. They defend these to a technical panel; a call they did not
  reason through is worth less than nothing in live Q&A.

  **Construction is delegated.** Writing SQL, wiring dbt, building profiling queries, gathering
  the evidence a decision needs, drafting diagrams and docs.

  In practice: bring evidence and options with tradeoffs, then **stop and ask**. Do not resolve
  a definitional or structural question by picking the most reasonable-looking answer and
  proceeding — surfacing the tradeoff *is* the deliverable. This is not the Socratic mode
  (no drawing the owner toward a predetermined answer); it is: build fast, decide together,
  and never let construction quietly make a design call.

- **Carried-forward design decisions.** None. This project starts at WP-001 with no prior
  generation, so §8.2's re-derivation rule does not bite yet.

- **Gotchas** (§6) — three seeded at bootstrap from first-look observation, all still unprofiled:
  mixed `event_ts` encodings (§6.1), `sport` categorical variants (§6.2), and non-unique
  `subscription_id` (§6.3). Expect this list to grow fast during phase 1; the dataset is
  deliberately salted.

Last verified: 2026-08-18
