# MMF Sandbox — Phase 3 Brief
**Authority:** CAOM-001
**Date drafted:** 2026-04-22 (Phase 2 completed same day)
**Phase 3 kickoff gate:** one week of clean daily NAV sweeps + ≥3
successful Railway redeploys with verified state continuity, per
the Phase 2 brief's time-bound. Drafted now (while fresh) so the
build plan exists when the gate opens.
**Target:** same surfaces as Phase 2 — `br-collab/aureon`,
`br-collab/Cato---FICC-MCP`, Aureon-Leto.
**Doctrine:** unchanged — build once, iterative, DSOR captures
everything, testnet/synthetic only, HITL at atomic events.

---

## What Phase 2 closed

1. **Persistence** (P2-1): fund_state + nav_engine snapshots persist
   to the Railway volume; MMF DSOR merges into
   `aureon_state["operational_journal"]`.
2. **Real atomic DvP on Lane D** (P2-2): `xrpl_integration.
   execute_subscription_dvp` replaces the 8-second simulation with
   real testnet tx hashes. Sandbox custody model.
3. **Real reverse DvP (burn-on-receipt)** (P2-3): Lane D redemptions
   now burn MMF shares and deliver USD IOU atomically on testnet.
4. **Cato parity + test-hook hardening** (P2-4): external MCP +
   in-process twin both at v0.2.3 with `sofr_rate`/`sofr_prev`.
   `/api/mmf/_test/cato_override` gated behind
   `AUREON_MMF_TEST_HOOKS_ENABLED`; inert in prod.
5. **Validation matrix** (P2-5): all 9 breaks pass (6 Phase 1 +
   persistence + tecPATH_DRY + tecPATH_PARTIAL). Every break has a
   DSOR entry.

Residual observations carried forward to Phase 3 below.

## What Phase 2 explicitly left on the table

**Scope-deferred (my Phase 2 brief's "Phase 3 inherits" list):**

- **Business-day + holiday calendar.** T+1 settlement stamps
  tomorrow 09:00 ET regardless of weekend / Fed holiday.
- **Real weekly liquid asset %.** Hardcoded 0.85 in Phase 1;
  real MMFs compute from portfolio composition.
- **Per-lot cost-basis tracking.** Current impl uses aggregate
  pro-rata; real tax-lot accounting (WAC or FIFO) deferred.
- **Multi-lane investor support.** Single-lane discipline per
  investor_id enforced in Phase 1; real funds let one investor
  hold both F and D classes in separate accounts.
- **Dividend / income distribution mechanics.** Phase 1+2 accrues
  daily into FNAV but never distributes. Real MMFs distribute
  monthly (typically via CNAV share creation).
- **NAV strike time discipline.** Phase 2 sweeps at 17:00 ET; real
  funds strike at 4:00pm ET with subscription cutoffs pre-strike
  and ordered post-strike settlement.

**Surfaced during Phase 2 execution but not originally in the
brief:**

- **Async HITL flow for Lane D.** Phase 2 left the Lane D path
  synchronous — request blocks ~20s for DvP. No separate
  `DIGITAL_SUBSCRIPTION_DVP_APPROVED` event. The brief assumed
  async via `on_gate_prompt` callback; implementation took the
  sync shortcut and flagged it.
- **Leto UI for Lane D.** MMF panel shows the same tiles as Phase 1
  (AUM, NAV, yield, circuit, counters). No pending-HITL queue, no
  tx-hash display for Lane D subscriptions/redemptions, no
  investor-registration flow surface. Operator currently interacts
  with Lane D via curl.
- **Sandbox custody model is a Phase-2 shortcut.** The fund
  auto-generates investor XRPL wallets via faucet and holds their
  seeds in the volume (`aureon_mmf_xrpl_wallets.json`). This does
  not match how real tokenization works — investors hold their
  own keys. The switch to wallet-connect / signed-tx submission
  is what flips this build from sandbox to real-investor-facing.
- **Full end-to-end parity harness for Cato.** P2-4 shipped a
  static schema-alignment check
  (`scripts/cato_parity_check.py`); a real harness invokes the
  external MCP server's stdio JSON-RPC and diffs against the
  in-process twin for a matrix of scalar inputs. Deferred.
- **Response-shape polish for Lane D redemption.** The `/api/mmf/
  redeem` response doesn't echo the XRPL tx hashes (they land in
  the DSOR payload). Operator-UX inconsistency vs Lane D
  subscribe which DOES echo them.
- **_submit engine_result parsing.** Addressed as a fix in P2-5
  (commit 9e7c900) — tec*/tef*/tel*/tem*/ter* codes now parse out
  of xrpl-py exception messages. This was a P2 polish, not a P3
  concern; noting so it doesn't re-surface.
- **Non-finding on nav_state persistence.** I flagged "sweep_count
  reset" as a possible P2-1 bug in my P2-2 report. P2-5 diagnostic
  (sweep → induce redeploy → verify) proved nav_state persistence
  works correctly. The sweep_count=0 observations were genuine
  zero-sweep states on fresh instances, not lost writes.
  Closed — no Phase 3 action needed.

---

## Phase 3 scope — four pillars, six prompts

### Pillar 1 — Production realism

Bring the money math and calendar to where a Compliance officer
could read the code without flinching.

### Pillar 2 — Lifecycle completeness

Match how a real fund actually operates day-over-day: cutoff
times, distribution events, multiple share classes per investor.

### Pillar 3 — Custody + HITL

Replace the sandbox custody shortcut (fund holds investor seeds)
with an investor-signed-tx protocol. Add async HITL for Lane D so
the request path doesn't block 20s, and expose the pending queue
in Leto.

### Pillar 4 — Mainnet migration readiness (design, not deployment)

Write the doctrine for when/how to flip testnet-only to mainnet.
This is an artifact phase — the brief + checklist + a risk
register. Actual mainnet migration is a separate authorization
beyond Phase 3.

---

## PROMPT P3-1 — Business-day calendar + per-lot cost basis

```
Sam — Phase 3, Prompt 1. Production-realism pillar.

TWO related changes that share the same reviewer context (money
math + calendar discipline).

Scope A — Business-day calendar:
  1. Create aureon/mmf/business_calendar.py.
     - next_business_day(dt: date) -> date
     - n_business_days_after(dt: date, n: int) -> date
     - is_fed_holiday(d: date) -> bool
     - US Fed holiday list (hardcoded; roll forward quarterly):
       MLK, Presidents, Memorial, Juneteenth, Independence, Labor,
       Columbus, Veterans, Thanksgiving, Christmas, New Year.
       Observed-when-weekend rules applied.
     - Weekends skipped.
  2. Update subscription_engine._next_business_day_0900_et to use
     the new calendar. T+1 settlement never lands on a weekend or
     Fed holiday.
  3. New DSOR field settlement_model_detail: "T+1 (next business
     day 09:00 ET: 2026-04-23)" so the specific target date is in
     the record, not just the abstract model.

Scope B — Per-lot cost-basis tracking:
  1. fund_state.apply_subscription extended: investor record now
     contains lots: list[{shares, cost_per_share, acquired_at}].
     Existing cost_basis field becomes a derived sum.
  2. fund_state.apply_redemption reduces lots FIFO (tax-favorable
     for redemptions in an accruing fund — oldest lots first).
     Partial lot reductions split the lot.
  3. New DSOR stamp LOT_CLOSED or LOT_OPENED on each redemption/
     subscription with the lot identifiers touched.
  4. Persistence: lot records survive redeploy (schema bump on
     the fund_state snapshot — migrate older snapshots on load).

Test sequence:
  - next_business_day(2026-12-24) → 2026-12-26 (Christmas Dec 25
    is Thursday; 26 is Friday business day).
  - next_business_day(2026-07-03) → 2026-07-06 (July 4 is Saturday
    observed Friday; 6 is Monday).
  - Sub 100 shares @ $1.00, wait, sub 100 shares @ $1.001 (after
    an intervening NAV bump), redeem 50 shares → FIFO consumes
    oldest lot (50 of the first 100). cost_basis_out = 50 × $1.00.
  - Redeem another 100 → consumes the 50 remaining of first lot
    + 50 of second lot.

Commit messages:
  `feat(mmf): business-day calendar with Fed holiday table`
  `feat(mmf): per-lot cost-basis tracking with FIFO redemption`

Expected DSOR additions:
  LOT_OPENED, LOT_CLOSED. Settlement timestamps in FIAT_
  SUBSCRIPTION_COMPLETE payloads become precise dates.
```

---

## PROMPT P3-2 — Multi-lane investor + dividend distribution

```
Sam — Phase 3, Prompt 2. Lifecycle-completeness pillar.

TWO related changes: multi-lane investor support and the monthly
dividend distribution event.

Scope A — Multi-lane investor support:
  1. fund_state.investors key change: investor_id -> {
       "F": {"shares", "cost_basis", "lots"},
       "D": {"shares", "cost_basis", "lots", "xrpl_address"},
     }  # either or both lanes present
  2. apply_subscription / apply_redemption address the specific
     lane's record. No more single-lane exception on mixed usage.
  3. Persistence schema migration: load-time upgrade from Phase 2
     investor records (single lane) to Phase 3 (lane-keyed).
  4. subscription_engine allows the same investor_id to subscribe
     across both lanes. Redemption mirrors.

Scope B — Dividend distribution (monthly):
  1. Constants:
       DISTRIBUTION_DAY_OF_MONTH = 28 (last business day ≤ 28)
       DISTRIBUTION_HOUR_ET = 16 (post-NAV-strike)
  2. New event: DIVIDEND_DISTRIBUTION_COMPLETE (fund-level, not
     per-investor — covers all investors).
  3. Class F (CNAV model): accumulated per-share net yield is
     distributed as NEW CNAV shares ("stable-at-a-dollar, grow by
     share count"). aum_f increases by the accumulated_yield × NAV
     automatically.
  4. Class D (FNAV model): no share creation — accumulated yield
     is already embedded in the floating FNAV. Nothing additional
     to distribute. Still stamp a DIVIDEND_DISTRIBUTION_SKIPPED_D
     DSOR for completeness ("class D accrues in NAV; no
     distribution event").
  5. Scheduler: nav_engine scheduler already fires 17:00 ET daily.
     Extend to also check for month-boundary crossing and invoke
     the distribution event.

Test sequence:
  - Two investors in Lane F for one simulated month. Daily NAV
    sweep (force-stale each day). Run the scheduler-dispatched
    distribution event. Verify F shareholders' share counts
    increased by accumulated_net_yield / CNAV.
  - One investor in Lane D for same period. Verify their share
    count unchanged but FNAV has grown (yield embedded).
  - An investor with BOTH F and D positions: verify both records
    independently.

Commit messages:
  `feat(mmf): multi-lane investor accounts (F + D under one ID)`
  `feat(mmf): monthly dividend distribution — CNAV share creation`

Expected DSOR additions:
  DIVIDEND_DISTRIBUTION_COMPLETE with per-lane breakdown,
  DIVIDEND_DISTRIBUTION_SKIPPED_D for the FNAV-is-cumulative
  acknowledgement.
```

---

## PROMPT P3-3 — NAV strike discipline (4:00pm ET cutoff)

```
Sam — Phase 3, Prompt 3. Lifecycle-completeness pillar.

Replace the 17:00 ET daily sweep with the institutional-standard
4:00pm ET NAV strike pattern.

Scope:
  1. Two cutoffs — pre-strike and post-strike:
       SUBSCRIPTION_CUTOFF_ET = 16:00  (requests before this time
                                        settle at today's strike)
       STRIKE_TIME_ET         = 16:00  (NAV computed here)
       SETTLEMENT_WINDOW_ET   = 16:00-17:00 (ordered settlement)
  2. Before 16:00 ET: subscriptions queue against today's strike.
     After 16:00 ET: subscriptions queue against tomorrow's strike
     (T+0 if business day, else next business day).
  3. nav_engine.run_sweep() fires at 16:00 ET. After the sweep,
     queued subscriptions and redemptions settle in FIFO order
     between 16:00 and 17:00 ET using the just-struck NAV.
  4. New DSOR events:
       SUBSCRIPTION_QUEUED (pre-strike)
       SUBSCRIPTION_STRIKE_SETTLED (post-strike, at the struck NAV)
       REDEMPTION_QUEUED / REDEMPTION_STRIKE_SETTLED (same)
  5. NAV_SWEEP_COMPLETE already fires; additionally emit STRIKE_
     POSTED event.

Test sequence:
  - At 15:30 ET (simulated): submit a Lane F subscription. Should
    return {status: "QUEUED", strike_date: "2026-04-22"}.
  - At 16:00 ET (simulated): sweep fires. Queued sub settles at
    the new CNAV.
  - At 16:30 ET (simulated): submit another sub. Should queue for
    NEXT day's strike.
  - Edge: submit at 16:00:00.500 ET — falls on which side of cutoff?
    Explicit doctrine: > (strictly after) cutoff queues for next
    strike. Exactly-at cutoff settles today.

Commit message: `feat(mmf): 4:00pm ET NAV strike + ordered post-strike settlement`

Expected DSOR additions:
  SUBSCRIPTION_QUEUED, SUBSCRIPTION_STRIKE_SETTLED, REDEMPTION_
  QUEUED, REDEMPTION_STRIKE_SETTLED, STRIKE_POSTED.
```

---

## PROMPT P3-4 — Async HITL for Lane D + Leto pending-HITL queue

```
Sam — Phase 3, Prompt 4. Custody + HITL pillar.

Replace the Lane D sync-blocking DvP flow (request takes ~20s
while XRPL commits) with an async approval queue. Expose the
queue in Leto.

Scope A — Async DvP flow:
  1. /api/mmf/subscribe Lane D handler:
     - validates + Cato gate + stamps DIGITAL_SUBSCRIPTION_DVP_
       SUBMITTED as before
     - registers a pending job in a module-level dict keyed by
       event_id. Shape: {investor_id, amount, shares, xrpl_address,
       cato_decision, submitted_at, status: "AWAITING_APPROVAL"}
     - returns {status: "PENDING_APPROVAL", event_id, ...} and
       does NOT block
  2. /api/mmf/hitl/resolve extended:
     - gate_type="DVP" accepted. decision="approve" triggers the
       background execution: spawn a daemon thread that calls
       xrpl_integration.execute_subscription_dvp, stamps
       DIGITAL_SUBSCRIPTION_DVP_APPROVED at thread start,
       DIGITAL_SUBSCRIPTION_COMPLETE on tesSUCCESS,
       DIGITAL_SUBSCRIPTION_REJECTED on fail.
     - decision="reject" stamps DIGITAL_SUBSCRIPTION_REJECTED with
       reason="operator rejected at HITL" and clears the pending
       slot.
  3. New endpoint: GET /api/mmf/pending — returns the full pending
     queue for Leto polling.

Scope B — Leto pending-HITL queue UI:
  1. New Leto panel section in index.html: "MMF · Pending HITL"
     inside the MMF · Fund Console. Tiles list pending events
     (event_id, investor, lane, amount, submitted_at, status).
  2. Each pending tile has APPROVE and REJECT buttons.
  3. Leto server.py proxies: GET /api/mmf/pending (5s cache
     matching the UI poll), POST /api/mmf/hitl/resolve (uncached).
  4. Lane D tx hashes appear in the DSOR audit trail panel with
     testnet.xrpl.org links.

Scope C — Gunicorn timeout restored:
  - Once Lane D is async, gunicorn worker timeout can drop back to
    30s default. Sync path wasn't supposed to block that long in
    the first place.

Test sequence:
  - Submit Lane D sub via /api/mmf/subscribe → should return
    PENDING within ~1s.
  - GET /api/mmf/pending → shows the queued event.
  - Operator clicks APPROVE in Leto → background thread runs DvP.
  - /api/mmf/pending empties, /api/mmf/dsor shows DVP_APPROVED +
    COMPLETE entries with tx hashes.
  - Parallel test: submit, reject via Leto → REJECTED DSOR, no
    XRPL call.

Commit message: `feat(mmf): async HITL for Lane D + Leto pending queue`

Expected DSOR additions:
  DIGITAL_SUBSCRIPTION_DVP_APPROVED finally emits (was planned in
  Phase 2 but sync flow skipped it).
```

---

## PROMPT P3-5 — Wallet-connect / signed-tx submission protocol

```
Sam — Phase 3, Prompt 5. Custody pillar.

Replace the sandbox custody model (fund holds investor XRPL
seeds in the volume) with a signed-tx submission protocol.
Investors hold their own keys. Fund signs only what it has
authority over (ShareIssuer txs, CashIssuer Payment to
investor at subscription pre-fund).

Scope:
  1. New endpoint: POST /api/mmf/digital/build_investor_setup_tx
     Body: {investor_id, investor_xrpl_address}
     Returns: unsigned-tx JSON blobs (TrustSet MMF + TrustSet USD)
     for the INVESTOR to sign and submit via their own wallet
     software (Xumm, Bifrost, etc.). No server-side key material.
  2. New endpoint: POST /api/mmf/digital/register_authorized_address
     Body: {investor_id, investor_xrpl_address}
     Server performs the ShareIssuer-side TF_SET_AUTH step (this
     is fund authority, server signs). Assumes investor has
     already submitted their trust-line txs (server can verify via
     account_lines).
  3. New endpoint: POST /api/mmf/digital/build_subscription_tx
     Body: {investor_id, amount_usd, share_count}
     Returns: unsigned Payment blob for the investor to sign. The
     CashIssuer pre-fund + ShareIssuer Offer fire server-side
     (fund authority). Investor submits the signed Payment.
  4. Deprecate register_investor (sandbox custody). Keep it
     available behind AUREON_MMF_TEST_HOOKS_ENABLED for
     continued sandbox testing; production callers use the new
     build_*_tx endpoints.
  5. Aureon-Leto panel gets a "copy unsigned tx to clipboard"
     button — operator can paste into Xumm to sign.

Test sequence:
  - Create a fresh XRPL testnet wallet locally (not via the fund).
  - Use build_investor_setup_tx → get unsigned blobs. Sign locally
    using xrpl-py; submit via faucet client. Verify trust lines
    exist on testnet.
  - Use register_authorized_address → server flips TF_SET_AUTH.
  - Use build_subscription_tx → get unsigned Payment. Sign + submit.
    Verify tesSUCCESS + fund_state updated.

Commit message: `feat(mmf): signed-tx submission — investors hold own keys`

Expected DSOR additions:
  DIGITAL_TX_BUILT (server emits an unsigned tx for investor),
  DIGITAL_INVESTOR_SIGNED_TX_OBSERVED (when the fund detects a
  known investor's Payment settling via account_lines poll).
```

---

## PROMPT P3-6 — Mainnet migration readiness (DOCTRINE, not deploy)

```
Sam — Phase 3, Prompt 6. Mainnet-readiness pillar.

WRITE the doctrine and checklist for when/how to migrate the MMF
sandbox from XRPL testnet to XRPL mainnet. This is an ARTIFACT
prompt — no deploy, no mainnet config flip. The output is a
document the operator can read, edit, and use as the
authorization template when the actual migration is proposed.

Scope:
  1. aureon/doctrine/mmf_mainnet_readiness.md (new). Sections:
     - Risk Register: every Phase 1/2/3 assumption that becomes
       DANGEROUS on mainnet. Each with a severity, mitigation,
       and gate-out criterion.
       Examples: XRPL testnet validator behavior vs mainnet MEV;
       faucet-funded wallets vs real-cost wallet setup; sandbox
       custody vs real-investor keys; KYC allowlist being a
       hardcoded dict vs a compliance workflow; Cato testnet
       SOFR feed vs institutional price feed; Fund wallet seed
       rotation policy; Volume backup and recovery; Regulatory
       registration (is this a 40-Act fund? 3(c)(7)? Reg-D?
       jurisdictional Reg-S?).
     - Flip Checklist: ordered list of operator-acknowledged
       gates that MUST ALL be green before any mainnet commit
       touches production. Includes external audit, mainnet-
       block-assertion removal review, legal sign-off, cap
       limits, insurance/indemnity disclosure, operator identity
       signing upgrade (CAOM-001 → multi-sig or enterprise KMS).
     - Doctrine Assertions: the non-negotiables carried from
       sandbox → mainnet. Small set: HITL at every atomic event;
       DSOR append-only; no autonomous execution; operator can
       halt at any moment.
     - Reversal Protocol: the mainnet-to-sandbox rollback path
       if something goes wrong in the first N days post-flip.
  2. Update Grid 3 CLAUDE.md with a pointer to the new doctrine
     file and a one-line statement: "MMF is testnet-only until
     mmf_mainnet_readiness.md checklist is fully green and
     explicitly acknowledged by the operator."
  3. Commit both files in one commit tagged as a doctrine
     artifact (not a feature).

Test: none — this is a documentation prompt. Success is the
operator reading the doc and either (a) accepting it as the
template, (b) editing in place to reflect their own constraints,
or (c) flagging gaps for a P3-6b follow-up.

Commit message: `doctrine: MMF mainnet-readiness risk register + flip checklist`

Expected DSOR additions: none — this is a doctrine artifact, not
a runtime event.
```

---

## Execution order

```
P3-1 → confirm business-day + FIFO lots → P3-2
P3-2 → confirm multi-lane + monthly distribution → P3-3
P3-3 → confirm 4:00pm ET strike + post-strike ordering → P3-4
P3-4 → confirm async HITL + Leto queue + tx-hash display → P3-5
P3-5 → confirm investor-signed-tx flow works end-to-end → P3-6
P3-6 → operator reads doctrine, accepts/edits → PHASE 3 COMPLETE
```

Same discipline as Phase 1/2: do not skip steps; do not start
the next prompt until the current confirms clean.

---

## Phase 3 kickoff gate (reiterated)

Per the Phase 2 brief: "Phase 3 begins when Phase 2 has run
cleanly for at least one full week of daily NAV sweeps with no
open circuit breakers and verified persistence across three or
more Railway redeploys."

2026-04-22 state toward the gate:
  - ≥3 Railway redeploys with verified state continuity: ✓
    (5+ redeploys since P2-1 baseline, fund_state + nav_state
    both survived)
  - One full week of daily NAV sweeps: pending (today is day 1)

Natural gate-open date: 2026-04-29 (Wednesday).

Nothing stops the operator from overriding the time gate. The
gate exists to let the real-time scheduler accumulate evidence
that nav_engine.start_nav_scheduler() fires daily at 17:00 ET
without operator intervention. That evidence takes a week to
gather; override accepts the unobserved risk.

---

## What Phase 4 inherits (if Phase 3 ships cleanly)

Non-exhaustive — flag as these surface during Phase 3 execution:

- **Actual mainnet migration.** Phase 3's P3-6 is the doctrine;
  Phase 4 is the flip itself, gated on every P3-6 checklist item
  going green.
- **Multi-fund support.** Current impl assumes one fund
  (Arcadia Liquidity Fund). Phase 4+ supports multiple funds
  under one Aureon instance, each with its own ShareIssuer /
  CashIssuer pair.
- **Institutional price-feed integration.** CoinGecko + FRED are
  baseline sandbox feeds; institutional deployment needs
  Bloomberg BVAL / Refinitiv / Chainlink Price Feeds.
- **Regulatory reporting hooks.** Form PF, Form N-CEN, DA-1594
  equivalents — outputs the operational_journal can feed, but
  the format + filing cadence is Phase 4 scope.
- **Secondary-market support.** Lane D could eventually list on
  an AMM (not XRPL AMM — the wrong primitive for MMF shares) or
  a regulated secondary venue. That's a very-late-phase concern.

---

*Drafted 2026-04-22 while Phase 2 is still fresh. Execution
gated on time + operator authorization per doctrine.*
