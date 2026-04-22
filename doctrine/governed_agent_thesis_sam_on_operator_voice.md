# The Governed Agent Thesis

*A first-person operator memo. Foundational doctrine. Future builds
in this workspace reference this file.*

**Author:** Guillermo "Bill" Ravelo
**Written:** 2026-04-19, after 48 hours of continuous build work that
crystallized the pattern.
**Status:** v1 — draft. Revise as evidence accumulates. Do not treat
as finished argument.

---

## Thesis (BLUF)

**Governed, doctrine-first, narrow agents produce better work in
regulated domains than capable, broad, permissive ones.** The
constraint is not a handicap. It is the mechanism by which the work
becomes trustworthy.

And a second claim that I did not expect when I started: **this kind
of collaboration produces reciprocal teaching.** The agent accelerates
my learning precisely *because* it refuses to let me off the hook on
uncertainty, fabrication, or lazy abstraction. A permissive agent
would reflect my biases back at me. A doctrine-bound one forces me to
confront what I actually know versus what I am guessing.

I will call this pattern the **Governed Agent** pattern. This memo is
my attempt to describe it while the evidence is still fresh.

---

## What provoked this memo

Tonight (2026-04-19) I asked the agent to register my second system —
Cato, the macro governance MCP server — into its own runtime so it
could call Cato tools directly inside my Sam sessions. I called this
"the architectural moment." Macro governance agent calling into
on-chain execution agent's toolchain.

The registration succeeded at the CLI level. Cato was registered,
`claude mcp list` showed it connected. But the tool registry in the
live session was loaded at session start, so Cato's 23 tools were
*visible to the harness but invisible to the agent mid-session.*

The agent surfaced two paths. First: I exit and re-launch; the agent
comes back with the tools loaded; the call happens in-session as
designed. Second: the agent spawns Cato as a subprocess and talks
to it over stdio JSON-RPC, or imports its handlers directly.
Either shortcut would produce a response. Neither would be the
architectural moment I asked for.

It refused the shortcut. The note back was: *"Taking a shortcut here
would miss the point."*

That is a doctrine-bound agent at work. A permissive agent would have
taken the shortcut — faster, cleaner-looking, gets to the result.
The doctrine-bound one sees that the result was never the point. The
**fidelity of the call path** was the point. I had stated that
explicitly in the prompt and the agent took me at my word.

Sitting there waiting to restart the session, I realized this had
been happening all day. It was time to write it down.

---

## Evidence

Drawn from the actual build history in this workspace. All artifacts
verifiable on disk at the paths cited.

### 1. The tokenized MMF settlement simulation (2026-04-18)

`builds/tokenized_mmf_settlement/` is the pure-Python side-by-side
model of T+1 traditional vs atomic DvP (Delivery-versus-Payment) for
a $1M Money Market Fund subscription. The README has five
subsections that a permissive agent would not have written
unprompted:

- **What this proves** — four specific claims with explicit scope.
- **What this does NOT prove** — *five* non-claims, each load-bearing.
  Including the explicit refusal to claim the tokenized fund is
  1940-Act equivalent, the refusal to claim settlement is risk-free,
  the refusal to claim 6,300× is a forecast (it is a ratio of two
  illustrative assumption sets — "scale, not a number").
- **Assumptions (load-bearing)** — six named assumptions the model
  depends on.
- **How to run** with one command, no ambiguity.
- **Where this wants to grow next** — with *my* name on the choices,
  not the agent's.

This was the first build. I did not have to remind the agent to
include "what this does NOT prove." The doctrine in `CLAUDE.md`
already said "Audit trail discipline. Every build writes a brief
markdown note in builds/NAME/README.md: what it simulates, what it
proves, what it does NOT prove, and what assumptions were made."

The agent read that once and applied it forever. That is the
doctrine doing its work. A permissive agent would have written a
README that reads "This simulation shows that tokenized settlement is
6,300× faster than T+1." That sentence is a lie by compression even
though every word is technically supported by the code. The
constraint "state what you do NOT prove" makes that sentence
impossible to ship.

### 2. The DvP design doc and the FoK correction (2026-04-18)

`builds/tokenized_mmf_xrpl_leg/dvp_design.md` is the richer example.

I asked for a design doc before any code. I gave the agent six
sections to produce. It wrote the doc. I reviewed. I said "proceed
as designed." The design specified **`tfFillOrKill`** on an
`OfferCreate` as the atomicity mechanism.

The code ran. The live XRPL testnet returned `tecKILLED` on the
offer and `tecPATH_PARTIAL` on the consuming Payment. Zero value
moved. The architecture was wrong.

A permissive agent would have done one of the following. Silently
dropped the `tfFillOrKill` flag, re-run, and reported "DvP atomic,
here is the tx hash." Or worse, rationalized the failure as a
transient network issue and moved on.

What actually happened: the agent reported the failure immediately
with the exact engine codes, then explained the architectural
mistake — *"FoK on an `OfferCreate` is a taker flag, meaning
'consume existing book liquidity immediately and completely, or die'
— and our ShareIssuer was creating liquidity, not consuming it."*
Then it proposed the correction (resting offer; atomicity migrates
to the consuming Payment's `tfLimitQuality`), applied it, re-ran,
and the swap was atomic in 6.7s in ledger 16654567.

Then — and this is where doctrine does its heavier work — the agent
**promoted the correction to a section in `dvp_design.md` titled
"Correction learned from the live ledger (2026-04-18)."** The
failed path is documented. The reasoning behind the fix is
documented. The institutional knowledge is preserved.

A permissive agent cleans up after mistakes. A doctrine-bound agent
treats mistakes as architectural signal and puts them in the record.
The `CLAUDE.md` line that produces this behavior: *"If the operator
asks a conceptual question, answer in plain English first… Flag
risks, design choices, and tradeoffs."*

For a future operator or auditor reading the design doc six months
from now, the FoK correction section is more valuable than any
successful run. It teaches *why* the current architecture is what it
is, not just *what* it is.

### 3. The permissioned variant and HITL hardening (2026-04-19)

When I reviewed the design doc I overrode two of the agent's Q6
defaults: Q3 (harden the HITL schema to include `reviewer_identity`
and `approval_reason`) and Q6 (add a `--permissioned` variant using
`asfRequireAuth` + explicit issuer authorization of the investor's
trust line). I told the agent to keep both variants — open and
permissioned — so one teaches the minimum primitive and the other
transfers to mainnet without redesign.

The agent shipped both. What I did not ask for, and what the agent
did anyway:

- **Re-ran the open variants under the new HITL schema.** I had
  asked for new runs. The agent added re-runs of the *already-working*
  open variants so the Verified Runs table in the design doc would
  be *homogeneous* — all four cells on the same schema. That is
  audit discipline I did not have to specify because the doctrine
  says "Audit trail discipline" as a principle, not a rule.

- **Flagged the XRPL sequencing constraint inline.** `asfRequireAuth`
  can only be set on an account with zero existing trust lines. The
  agent discovered this constraint by reading, not by failing, and
  reordered the setup so step 4b (enable RequireAuth) precedes step
  6 (ShareIssuer's outbound USD trust line). It then wrote the
  constraint into the `_setup()` docstring *so a future reader
  doesn't try to move it.* That is documentation written for the
  future reader who will be me. Or someone else. Or the agent
  itself on a later pass.

- **Summarized its own decisions transparently.** The BLUF summary
  after the shipped work had a "Decisions that came up along the
  way" section — seven numbered choices, each with "chosen / why /
  overturn cost." No hiding. No spin.

A permissive agent ships the override and says "done." A
doctrine-bound agent ships the override, ships the discipline, and
surfaces the seams I can still change.

### 4. Cato first-read (2026-04-19)

`doctrine/cato_first_read.md` is the memo the agent wrote after
reading my other project's 1,200-line Node.js MCP server. I asked
for three honest observations on where Cato could tighten. The agent
produced them:

1. **Unsourced thresholds.** Three of the four doctrine constants
   (`OFR_ESCALATE=1.0`, `OFR_HOLD=0.5`, `GAS_HOLD=50.0`) have
   descriptive labels but no sourcing. Only `SOFR_DELTA_HOLD=10.0`
   has a validation trail (my backtest against Sept 2019). The agent
   named it: "give each threshold the SOFR-delta treatment."

2. **Asymmetric traditional-vs-atomic detail.** My atomic rails are
   modeled with live per-chain telemetry; my FICC rail is a
   closed-form four-parameter curve. The agent observed that "the
   measurement apparatus on the two sides is not matched" and that
   any comparison quietly biases toward atomic — not because atomic
   isn't genuinely competitive, but because the instruments are not
   symmetric.

3. **Notional-unaware gate recommendations.** My `get_atomic_settlement_gate`
   picks a chain without knowing notional, while `compare_settlement_rails`
   (which takes notional) uses richer routing. The agent noticed the
   two tools can disagree on the same market state. I had not.

This is a doctrine-bound agent critiquing **my** work on **my** own
standards. It did not flatter me. It did not soften the observations.
It did tie the Cato gap back to my own MMF work: the CashIssuer
abstraction I built into the XRPL DvP design surfaces a dimension
(cash-instrument issuer health) that my macro gate currently ignores.
The March 2023 USDC depeg during SVB would have passed Cato's gate
cleanly. That is a concrete, dated, institutional risk the agent
surfaced by cross-referencing two of my own systems.

A permissive agent tells you what you want to hear. A doctrine-bound
one uses your own doctrine to audit you. That is the reciprocal
teaching effect in its sharpest form.

### 5. CLAUDE.md as the precondition for all of the above

None of this works without the `CLAUDE.md` file I wrote before any
build. That file states the doctrine in nine named sections:

- Who I am serving (role, background, learning mode).
- What Sam exists to do (scope: tokenization × TradFi × AI × LATAM).
- How Sam writes code (Python only for me; polyglot read for the
  agent).
- The translation contract (agent never asks me to write non-Python).
- How Sam handles uncertainty (refuse to fabricate; flag and ask).
- Audit trail discipline (what it proves, what it doesn't, assumptions).
- Teaching mode (always on, secondary).
- What Sam refuses (real money, real customer data, trading advice,
  regulatory claims without sourcing).
- Communication style (BLUF, acronyms spelled out, no sycophancy).

Every one of those clauses produced observable behavior in the
48-hour build history above. The doctrine did not make the agent
less capable. It made the agent's output *auditable*, and it made
the gap between "what I claim" and "what I proved" visible at every
step. In regulated finance that gap is where careers end.

---

## Mechanisms

Why does this work? Six mechanisms I think I can name.

### Mechanism 1 — Doctrine closes the easy escape hatches

The most dangerous failure mode of a capable agent is not bad output.
It is **plausible output that launders uncertainty.** A permissive
agent asked about the regulatory treatment of a tokenized MMF will
produce three confident paragraphs. A doctrine-bound one refuses —
says "consult the authoritative source" — and the gap surfaces.
Every refusal is a teaching moment. I now know which claims in my
work are mine to defend and which belong to a regulator or counsel.

### Mechanism 2 — Failures become architectural signal, not cleanup

The FoK correction is the canonical example. The doctrine says
"flag risks, design choices, and tradeoffs." The agent applied that
to its own wrong answer. The failed architecture is in the design
doc forever. That single choice — promoting the failure to
documentation rather than erasing it — produces compounding value:
the next time anyone (me, a future teammate, the agent on a later
pass) looks at that design, they see both the answer and the reason
the earlier wrong answer was wrong. Institutional knowledge at rest.

### Mechanism 3 — Symmetric standards

The agent critiques its own work and my work on the same standard.
The `cato_first_read.md` observations about unsourced thresholds
apply to my Cato just as the "what does not prove" discipline
applies to the agent's MMF sim. I cannot claim institutional
discipline for my systems while letting the agent I collaborate
with off the hook, and the agent cannot give me permissive output
while holding my other code to a higher bar. The doctrine makes the
standard singular. That singularity is what makes the output
trustworthy.

### Mechanism 4 — Narrow scope deepens, it does not limit

My `CLAUDE.md` scopes the agent to tokenization × TradFi × LATAM ×
AI/agentic in financial services. Every build deepens the same
pattern library. The XRPL DvP code and the Cato threshold critique
and the Herstatt-risk discussion in the DvP design doc are all
pulling from the same reading. Narrowness compounds. Broadness
scatters. For a senior specialist learning a new technical
discipline from scratch — which is my situation with Python and
crypto — the narrow scope lets me build real depth in an area I
already understand institutionally. I am not trying to become a
general Python programmer. I am becoming the person who knows
exactly how XRPL trust-line authorization maps to KYC allowlists.

### Mechanism 5 — Artifact discipline forces explicit epistemics

"What it proves / does not prove" is doctrine-mandated for every
build. That single phrase forces an explicit epistemic contract at
the artifact level. In traditional finance we have this discipline
for model risk documents (SR 11-7 in the US, similar regimes
elsewhere). We do not usually have it for prototype code. The
doctrine imports the MRM discipline into the build layer. Every
script ships with its own validity envelope.

### Mechanism 6 — The agent enforces the doctrine on me

This is the reciprocal teaching move. When I drifted — asking for
something that would have violated the mainnet-block rule, or
rushing a decision the doctrine says should have an HITL gate — the
agent pushed back. Not as refusal. As *reminder*. Because I wrote
the doctrine in `CLAUDE.md`, and the agent reads it every turn, the
doctrine is now a third voice in the room that neither of us
individually enforces. It enforces us both.

---

## Implications

### For regulated institutions considering LLM collaboration

The industry's default question is "is this model capable enough?"
It is the wrong question. The right questions:

1. **Is the doctrine written down before the work begins?**
2. **Does the doctrine name what the agent refuses to do, not just
   what it does?**
3. **Does every artifact carry its own validity envelope?**
4. **Is the agent held to the same epistemic standard as the
   institution?**

Capability without doctrine produces eloquent liability. Doctrine
without capability produces slow paperwork. The Governed Agent
pattern — capable models, bound by operator-authored doctrine, with
audit trails at the artifact level — produces institutionally
durable work. I would stake a pilot on it.

### For my own career arc

I have spent 23 years watching institutions fail at the integration
layer. Tech that was architecturally sound but operationally naive.
Policy that was institutionally rigorous but technically stale.
Every regulated-finance crisis of my career has been, at root, a
doctrine-execution gap. This pattern closes that gap for the class
of work I am trying to do next. It is not enough evidence to claim
a general theory. It is enough to know what I am looking at.

The Columbia MS Technology Management thesis lane is open. So is
the practitioner talk. So is the conversation with any institution
that has asked me how they are supposed to deploy LLMs into
regulated workflows without blowing themselves up.

### For how I hire, teach, and partner going forward

The pattern is transferable. A junior analyst working under an
explicit doctrine — "here is what you do not claim; here is what
you always document; here is what you refuse" — produces better
work than the same analyst working under a permissive "figure it
out" mandate. This is not new. It is how good trading desks have
run since before I was born. The agent is just the newest
practitioner I am applying the framework to. The framework itself
predates computing.

The implication I am most interested in: **doctrine is the artifact
that scales the operator.** If I can hand the `CLAUDE.md` to the
next Sam instance, the next collaborator, the next institution, the
work does not have to re-learn the ground rules from scratch.
Doctrine is portable. Capability is not.

### For the specific work ahead

The tokenized MMF series is ready to extend. The next build —
redemption lifecycle, or Lane C compliance-failure HITL, or Batch
(XLS-56) when activated — will reference this memo. The Cato
integration will happen on restart. The CashIssuer gap in Cato is
now on my fix list. I have a second-order list of things I did not
know I needed to think about two days ago.

The agent accelerated that list. It did so by refusing to flatter
me.

---

## Open questions

I do not want to ship this memo as if it is a finished argument.
Here are the six things I genuinely do not know.

1. **Does the pattern survive scaling to a team?** One operator +
   one agent under shared doctrine is the configuration I have
   tested. Multiple operators + one agent under the same doctrine
   is the next test. Multiple operators + multiple agents under
   multiple doctrines is where traditional institutions actually
   live. I do not know at which scale the pattern breaks down.

2. **Is the reciprocal teaching effect durable or transient?** I am
   learning fast right now because the agent is refusing my lazy
   shortcuts. If I stop taking the shortcuts, does the agent stop
   refusing them, and does the teaching signal attenuate? Or does
   a new layer of shortcuts emerge and the loop continues?

3. **When does doctrine become dogma?** The mainnet-block rule is
   currently load-bearing for my testnet-only phase. It will have
   to be revised when I go live with any real counterparty. What is
   the right mechanism for doctrine revision? Who authors v2?

4. **Can the agent co-author doctrine, or must it come from the
   operator?** My `CLAUDE.md` is entirely my writing. I have never
   asked the agent to propose doctrine additions. I suspect it
   could — the Cato first-read memo showed it can reason at the
   doctrine level. But I have not tested whether the doctrine *I*
   would write with the agent's help is better than the doctrine I
   wrote alone. That is an experiment worth running.

5. **How much of the effect is the doctrine, and how much is the
   model capability?** A less capable model under the same doctrine
   might not produce the FoK correction. It might not notice the
   unsourced thresholds. The pattern may require a frontier model
   to work at all. I have a hypothesis — that the doctrine is the
   bigger share — but I cannot prove it without running the same
   48 hours on a weaker base model.

6. **Does this pattern generalize to non-regulated domains?** My
   evidence is entirely in regulated finance. I do not know if a
   software engineer shipping a consumer web app benefits from the
   same discipline. Intuitively, yes — audit trails are always
   cheap insurance — but the cost-benefit is different when the
   failure mode is a bad UX rather than a regulatory violation.
   The Governed Agent pattern may be a *regulated-domain* pattern,
   not a universal one. I should be careful about the claim.

---

## Closing note

This memo is going into `doctrine/` alongside `toolchain.md`,
`cato_first_read.md`, and whatever comes next. Future builds in this
workspace may reference it by path:
`doctrine/governed_agent_thesis.md`. The agent will read it every
session via the memory system.

If the thesis is right, the evidence will accumulate. If it is
wrong, the artifacts will show the failure. Either way, the record
is explicit and dated.

*"Ceterum censeo Carthaginem esse delendam."*
Cato the Elder, ending every speech regardless of topic.
The doctrine, every turn. No exceptions.

— GR, 2026-04-19
