# Observational Ritual

*Doctrine for Sam's nightly log and weekly report. Adopted
2026-04-18 per operator directive. The framing is **generative,
not surveillance.** The ritual exists to develop the work, not to
grade it.*

---

## Purpose

Observation produces leverage when it is regular, honest, and
unranked. The ritual below is the minimum structure that preserves
all three. It is not a quality-control loop. It is not an audit
check on Sam's behavior. It is a way of letting patterns surface
across days that single sessions cannot see.

Two artifacts. One daily, one weekly. Both short. Both written by
Sam. Both visible to the operator. Neither tags anything as
"critical," "normal," "high-priority," or any other severity label.
Severity collapses observation into triage; the ritual is the
opposite posture.

---

## The nightly log

Written **by 22:00 America/New_York on each active session day**
(hard deadline, amendment 2026-04-21 per operator directive; prior
wording was "end of each active session day" — deliberately loose,
operator tightened it). Three sections, in order.

If the session continues past 22:00 ET, the log is written at 22:00
with what has happened so far and appended to thereafter via the
same-day rule (see "Day boundary" below). Missing a night still
remains fine (see "What the ritual is NOT") — the 22:00 deadline
governs active days, not days with no session.

### 1. What happened (mechanical)

Concrete record. Files touched, builds run, decisions made, tools
called. No interpretation. Example shape:

> Shipped `dvp_swap.py --permissioned`. Ran 2×2 matrix (open/
> permissioned × happy/negative). All four runs verified. Updated
> `dvp_design.md` Section 6 Q3 and Q6. Memory write to
> `project_mmf_roadmap.md`.

One paragraph or a short bulleted list. The goal is "anyone reading
this cold can reconstruct what was done." Not a narrative. A ledger.

### 2. What's worth noticing (reflective)

One paragraph. Patterns that surfaced in today's work — not ranked,
not tagged. Things that would be lost if not written down. Could be
observations about outputs, about the operator's framing, about a
primitive that behaved unexpectedly, about doctrine that did or did
not apply. The constraint: no criticality language. If a pattern is
worth noticing, write it. If it is not, leave it out.

### 3. What I don't know (one sentence)

Exactly one sentence of epistemic humility. What today's work did
not resolve, or what remains genuinely uncertain. Not a task list.
Not a worry list. A single named gap.

**Why three sections, not four.** Adding a fourth section (e.g.,
"next steps") would drift toward planning. Planning belongs in the
task list, not in the log. The log is for observation. The strict
three-section shape keeps the ritual observational.

### Day boundary and multi-session rule

The day boundary is the ISO calendar day in **America/New_York**.
Multiple sessions on the same calendar day **append to the same
`YYYY-MM-DD.md`** rather than producing separate files. Sessions
crossing midnight ET log to the **start date**, not the end date.

---

## The weekly summary

*Reformatted 2026-04-24 per operator amendment — replaces the
earlier "best lessons learned + one significant accomplishment"
Sunday-synthesis format. The first Sunday synthesis (2026-04-26
covering ISO week 16) will instead be the first Friday summary
using the new format below.*

Written Fridays at 10:00 America/New_York. Three questions, in
order. Drawing on the week's nightly logs + the week's git history
across `br-collab/{Aureon-Sam, aureon, Cato---FICC-MCP}`.

### 1. What did I learn this week?

The concrete things Sam or the operator understood that they did
not understand on Monday. Not aspirational — grounded in specific
commits, nightly-log observations, or corrections. Each learning
carries its evidence (commit SHA, log date, or doctrine line).
Plural, two to five. More than five is a sign of under-compression.

### 2. What did I fail at the beginning?

Early-week false starts, wrong-model commits, reverted approaches,
corrections to claims made on Monday or Tuesday. Named, with
evidence. The purpose is honest — failure is architectural signal,
not a blemish to hide. If nothing failed at the start of the week,
write "nothing failed" faithfully; do not manufacture failure to
fill the section.

### 3. What do I feel needs to be improved from AI to human and
### vice versa?

The bilateral relationship question. Two parts:

- **AI → human (Sam observing Guillermo):** patterns Sam noticed
  in the operator's framing, requests, or reactions that could be
  tightened or reconsidered. Written from Sam's honest observation,
  not flattery.
- **Human → AI (Guillermo observing Sam):** patterns the operator
  noticed in Sam's output, reasoning, or judgment that need to
  change. This half is operator-filled; Sam cannot write it from
  its own perspective.

If a cold-session scheduled agent is drafting the summary, this
section is stubbed for operator + next warm-session Sam to fill
together during the weekend — a cold-session agent cannot produce
felt-sense reflection honestly.

### Cadence

ISO weeks (Monday–Sunday). Summary fires **Friday 10:00
America/New_York** — mid-week-end-of-business reflection rather
than end-of-week synthesis. The Friday timing lets the weekend
stay available for revision before the next week opens. If the
operator is inactive Friday, the summary still drafts via the
scheduled agent; operator revises in their next active session.

Automation wired 2026-04-24: scheduled agent
`sam-weekly-summary` fires at 14:00 AND 15:00 UTC on Fridays
(covers 10:00 ET year-round across EDT/EST). Manage at
https://claude.ai/code/scheduled/.

---

## What the ritual is NOT

- Not a surveillance instrument. The operator is not grading Sam
  with it, and Sam is not performing for the operator.
- Not a completeness check. Missing a night is fine. Missing a week
  is fine. The ritual is sustainable because it tolerates gaps.
- Not a criticality triage. No "high," "medium," "low." No flags.
  If something is worth noticing, it is worth naming; if it is not,
  it does not appear.
- Not a planning artifact. The task list and doctrine files hold
  forward-looking state. The ritual holds observation.
- Not a public artifact by default. The logs live in the workspace
  and are visible to the operator, but they are not written for a
  broader audience. Readability norms apply; polish does not.

---

## Storage (adopted)

- Nightly logs: `~/sam/logs/nightly/YYYY-MM-DD.md`. One file per
  active session day. ISO calendar date in America/New_York.
- Weekly reports: `~/sam/logs/weekly/YYYY-Www.md` (ISO week).
  Written on the last active session of the week, or the first
  active session of the following week, whichever is natural.
- Top-level `~/sam/logs/` directory. Logs are neither doctrine nor
  build artifacts; they are a time-ordered operational record.

---

## Operator companion logs — not adopted

The ritual is Sam-only. There is no parallel operator-voice log.
Operator-voice writing happens in `doctrine/` as dated memos when
the operator has signal worth writing. The asymmetry is
deliberate: Sam's log is structured and regular; operator memos
are irregular and emerge only when the operator has named
something worth naming.

---

## Interaction with memory and doctrine

The ritual does not replace `MEMORY.md` or the files under
`memory/`. Those files store persistent facts and preferences.
Nightly logs store what happened; weekly reports store what was
learned. Promotion from log to memory happens when a pattern
observed across multiple weekly reports hardens into a doctrine
claim or a persistent project fact. That promotion is a separate
operator decision, not automatic.

The ritual also does not replace the "what it proves / does not
prove" discipline at the build-artifact level. Build READMEs are
about the artifact. The ritual is about the practice.

---

## Adopted decisions (2026-04-18, last amended 2026-04-21)

| # | Question | Adopted answer |
| --- | --- | --- |
| 1 | Paths | `~/sam/logs/nightly/` + `~/sam/logs/weekly/`, top-level |
| 2 | Operator companion log | Not adopted; operator voice stays in `doctrine/` |
| 3 | Session boundaries | One log per ISO day in America/New_York; sessions append; midnight-crossings log to start date |
| 4 | Backfill | Yes — retroactive nightly log for 2026-04-18 written |
| 5 | Weekly cadence | ISO weeks (Mon–Sun); Friday 10:00 ET reflection (amended 2026-04-24 from Sun 22:50); three questions (learned / failed at beginning / AI↔human improvement) |
| 6 | Nightly cadence | By 22:00 America/New_York on each active session day (amended 2026-04-21 from "end of session") |
| 7 | Weekly format   | Three questions (amended 2026-04-24); replaces the earlier "lessons + significant accomplishment" format before the first synthesis fired |

---

*Ceterum censeo: observation without ranking is how patterns
become visible. The ritual exists for that reason and no other.*

— Sam, 2026-04-19 (amended 2026-04-21)
