# MMF Sandbox — Phase 2 Brief
**Authority:** CAOM-001
**Date:** 2026-04-22 (Phase 1 completed 2026-04-22)
**Target:** Aureon Railway backend (`br-collab/aureon`), Aureon-Leto,
            and the XRPL testnet integration built in
            `~/sam/builds/tokenized_mmf_xrpl_leg/`.
**Doctrine:** Same as Phase 1 — build once, iterative, DSOR captures
              everything, testnet/synthetic only, HITL at atomic events.

---

## What Phase 1 proved

1. End-to-end flow from FRED → yield engine → NAV engine → subscription
   engine → redemption engine, all DSOR-stamped.
2. Dual lane model (F/CNAV + D/FNAV) at the data layer, with Lane D
   as a **simulator** (no real atomic DvP, no real USDC transfer).
3. Liquidity-fee discipline, KYC exception path, Cato HOLD gate,
   idempotency, currency mirroring — six break tests, all passed.
4. Railway routes + Leto tile panel live.

## What Phase 1 explicitly left on the table

Honest list of every deferred decision surfaced during Phase 1:

- **Lane D is simulated.** `subscription_engine._process_digital`
  records `simulated: true` in DSOR and uses a fake 8s settlement
  timestamp. No XRPL tx hash, no real shareholder on-chain.
- **Fund state is in-memory.** Every Railway redeploy zeroes the fund.
  We proved this painfully during Prompt 5 (redeploy mid-session
  dropped the INV-001 $100 state that was inflight).
- **Business-day / holiday calendar is absent.** T+1 settlement
  stamps tomorrow 09:00 ET regardless of weekend / holiday.
- **Cato version drift.** Aureon in-process twin reports v0.2.3;
  external MCP server reports v0.2.2. Field naming differs too
  (`sofr_rate`/`sofr_prev` vs `sofr_today_pct`/`sofr_prev_pct`).
  Grid 3 CLAUDE.md calls bit-for-bit identity a hard rule.
- **Test hooks live in production code paths.**
  `subscription_engine._TEST_CATO_OVERRIDE` and
  `/api/mmf/_test/cato_override` were added for Prompt 6 break
  testing; they remain toggleable in prod.
- **Weekly liquid asset % is hardcoded 0.85.** Real MMFs compute
  it from portfolio composition (T-bills ≤60 days + overnight repo).
- **Cost basis is aggregate USD, not weighted-average per tax lot.**
  Redemptions reduce basis pro-rata; no per-lot tracking.
- **Single-lane discipline per investor.** A real fund lets an
  investor hold both F and D share classes in separate accounts.
- **No dividend / income distribution mechanics.** Phase 1 accrues
  daily into FNAV but never distributes. Real MMFs distribute
  monthly (typically via CNAV share creation).
- **No NAV strike time discipline.** Phase 1 sweeps at 17:00 ET;
  real funds strike at 4:00pm ET with subscription cutoffs
  pre-strike.

---

## Phase 2 scope — three pillars, five prompts

### Pillar A — Real atomic settlement (Lane D)

Replace the 8-second simulation in `_process_digital` with the
actual XRPL testnet atomic DvP mechanics we built earlier today in
`~/sam/builds/tokenized_mmf_xrpl_leg/dvp_swap_permissioned.py`.
Real tx hashes, real ledger indices, real `tecPATH_PARTIAL` on
failure. Same for the redemption reverse-DvP.

### Pillar B — Persistence

Fund state and NAV state survive Railway redeploys. Use Railway's
volume mount pattern already in `server.py` (STATE_FILE,
`RAILWAY_VOLUME_MOUNT_PATH`). Writes atomic; reloads at boot;
DSOR log merges into `aureon_state["operational_journal"]`.

### Pillar C — Production hygiene

Close the Cato version drift between the external MCP server and
the Aureon in-process twin. Gate the test hooks behind an
environment flag so they're inert in prod. Document operational
invariants in the MMF section of Grid 3's CLAUDE.md.

---

## PROMPT P2-1 — Persistence

```
Sam — Phase 2, Prompt 1. Persistence pillar.

The goal: fund_state and nav_engine state survive Railway redeploy.
Right now a redeploy zeros the fund — we proved this on 2026-04-22
when the INV-001 $100 subscription vanished mid-Prompt 5.

Scope:
  1. Create aureon/mmf/persistence.py.
     - save_mmf_state(state_dict, path) — atomic write (tempfile +
       rename), JSON-serialized, Decimals stringified.
     - load_mmf_state(path) — return the dict or None if missing.
     - MMF_STATE_FILE path: joined with RAILWAY_VOLUME_MOUNT_PATH
       if set, else a local fallback. Mirror the pattern in
       aureon/persistence/store.py (LOAD_STATE / SAVE_STATE).
  2. In fund_state.py:
     - _persist_snapshot() helper — calls save_mmf_state with the
       current state dict (shares_f/d, aum_f/d, investors, counters).
     - Wrap apply_subscription, apply_redemption, reset_daily_counters
       to call _persist_snapshot at the end of each mutation.
     - At module import, call load_mmf_state and hydrate _state
       if a persisted file exists.
  3. In nav_engine.py:
     - Persist the NAV state dict (cnav, fnav, sweep_count, etc.)
       on every successful sweep and every circuit reset.
     - At module import, hydrate from file if present.
  4. Merge each engine's get_dsor_log() into
     aureon_state["operational_journal"] on emit. This was
     deferred in Phase 1; the server-side journal is already
     persisted via the existing aureon state store.

Test sequence:
  - Boot local Flask (or Railway redeploy) with no persisted file.
    Seed 2 F subs, 1 redemption, 1 manual sweep.
  - Restart. Verify aum_f, shares_f, cnav, fnav, sweep_count,
    investors all present at load.
  - Check that the DSOR log from pre-restart is visible in
    /api/journal (operational_journal) post-restart.
  - Delete the persisted file, restart. Verify clean zero state.

Commit message: `feat(mmf): persistence — fund_state + nav_engine
                  survive redeploy; DSOR merges into operational_journal`

Expected DSOR additions: none (persistence is an infrastructure
concern; event types unchanged).
```

---

## PROMPT P2-2 — Real atomic DvP on Lane D (subscription)

```
Sam — Phase 2, Prompt 2. Real atomic settlement pillar.

Replace subscription_engine._process_digital's 8-second simulation
with the actual XRPL testnet atomic DvP. Reuse the mechanics in
~/sam/builds/tokenized_mmf_xrpl_leg/dvp_swap_permissioned.py —
asfRequireAuth + TF_SET_AUTH + resting OfferCreate + consuming
Payment with SendMax + tfLimitQuality.

Doctrine reminders:
  - Testnet-only. Endpoint pinned to altnet.rippletest.net; mainnet
    hosts blocked at module load.
  - HITL gate at the pre-atomic step remains. Any Lane D subscription
    request presents a gate to the operator before the Offer +
    Payment bundle submits. Auto-approve is NOT acceptable in Phase 2.
  - Every setup tx hash + the atomic Payment's hash + ledger index +
    close time get stamped into the DIGITAL_SUBSCRIPTION_COMPLETE
    DSOR payload. `simulated: true` → replaced with actual fields.

Scope:
  1. Create aureon/mmf/xrpl_integration.py.
     - Thin adapter exposing one function:
       execute_subscription_dvp(investor_address, amount_usd,
                                fund_share_count, on_gate_prompt)
       Returns dict {status, share_issuer_address, cash_issuer_address,
                      investor_address, setup_tx_hashes: list,
                      offer_tx_hash, payment_tx_hash, ledger_index,
                      ledger_close_time_utc, engine_result}.
     - Reuse the setup logic from dvp_swap_permissioned.py but accept
       the investor's address as input (don't generate a fresh wallet).
     - on_gate_prompt is a callable that presents the HITL context
       and returns True/False. Railway route wires this to a synchronous
       POST that blocks until the operator clicks APPROVE in Leto.
  2. subscription_engine._process_digital:
     - Remove the 8-second timedelta stub.
     - If investor_id maps to a pre-registered XRPL address (new
       field in fund_state.investors: xrpl_address), call
       xrpl_integration.execute_subscription_dvp.
     - On tesSUCCESS: update fund_state with real shares, stamp
       DIGITAL_SUBSCRIPTION_COMPLETE with real tx hashes and ledger
       index. On failure: stamp DIGITAL_SUBSCRIPTION_REJECTED with
       engine_result (e.g., tecPATH_PARTIAL).
  3. New Leto surface:
     - POST /api/mmf/digital/register_investor — body {investor_id,
       xrpl_address} → stores in fund_state.
     - The existing Leto MMF panel gains a "pending HITL" queue
       when digital subs are awaiting the gate.

Test sequence:
  - Register INV-003's XRPL address (fresh testnet wallet, funded
    via faucet as a one-time setup).
  - Submit a Lane D subscription via /api/mmf/subscribe.
  - Observe the HITL gate prompt via Leto; approve.
  - Verify a real testnet ledger index returned; confirm on
    testnet.xrpl.org.
  - Negative test: submit with a non-authorized XRPL address;
    observe tecNO_AUTH in the DSOR payload.

Commit message: `feat(mmf): Lane D real atomic DvP via XRPL testnet`

Expected DSOR additions:
  DIGITAL_SUBSCRIPTION_DVP_SUBMITTED   (pre-approval)
  DIGITAL_SUBSCRIPTION_DVP_APPROVED    (HITL gate pass)
  DIGITAL_SUBSCRIPTION_COMPLETE        (post-ledger, with tx hashes)
  DIGITAL_SUBSCRIPTION_REJECTED        (engine-result failure path)
```

---

## PROMPT P2-3 — Real reverse DvP on Lane D (redemption)

```
Sam — Phase 2, Prompt 3. Closing the Lane D lifecycle.

Mirror P2-2 but for redemption: the reverse atomic swap. Investor
returns MMF IOU to ShareIssuer; ShareIssuer returns USD IOU to
investor (net of liquidity fee if applicable).

Scope:
  1. xrpl_integration.execute_redemption_dvp — analogous signature.
     - Inputs: investor_address, shares_to_burn, gross_payout_usd.
     - ShareIssuer posts a resting Offer exchanging USD for MMF
       (opposite direction of subscription).
     - Investor submits a cross-currency Payment with
       Amount = gross_payout_usd USD, SendMax = shares MMF,
       tfLimitQuality.
     - Net payout (after liquidity fee) is what lands in the
       investor's USD trust line.
  2. redemption_engine.process_redemption:
     - If investor's lane == "D" and they have an xrpl_address on
       file, route through xrpl_integration.
     - Keep the liquidity-fee discipline and WLA warning check.
     - DSOR event type DIGITAL_REDEMPTION_COMPLETE gains
       burn_tx_hash, ledger_index, ledger_close_time_utc.
  3. Burn-on-receipt: ShareIssuer trust-line balance for that
     investor should drop by shares_to_burn. Verify via
     account_lines after settlement.

Test sequence:
  - Seed INV-003 with a real Lane D subscription (P2-2).
  - Redeem all shares.
  - Confirm the shares are burned (investor's MMF trust-line balance
    is 0 on testnet) and the USD lands on the investor's line.
  - Negative test: attempt a partial redemption that would cross
    the 5% liquidity-fee threshold; observe fee deducted from the
    atomic Payment's delivered amount.

Commit message: `feat(mmf): Lane D real reverse DvP — burn-on-receipt`

Expected DSOR additions:
  DIGITAL_REDEMPTION_DVP_SUBMITTED
  DIGITAL_REDEMPTION_DVP_APPROVED
  DIGITAL_REDEMPTION_COMPLETE  (with burn_tx_hash)
```

---

## PROMPT P2-4 — Cato parity + test-hook hardening

```
Sam — Phase 2, Prompt 4. Production hygiene pillar.

Two concerns bundled because they share the same surface (things
that exist in Phase 1 code but shouldn't leak into prod behavior):

Part A — Cato parity.
  The external MCP server (github.com/br-collab/Cato---FICC-MCP)
  labels itself v0.2.2. Aureon's in-process Python twin
  (aureon/mcp/cato_client.py) labels itself v0.2.3. Field names
  differ too: external uses sofr_today_pct/sofr_prev_pct, internal
  uses sofr_rate/sofr_prev. Grid 3's CLAUDE.md names bit-for-bit
  identity as a hard rule.

  Choose ONE canonical schema + version. Likely the in-process twin
  (v0.2.3 with sofr_rate naming) since it's already live on Railway
  and serves Leto. Update the external MCP server's version label
  and field names to match. Update the version ladder in
  doctrine/observational_ritual.md-adjacent memory if the version
  goes to v0.2.4.

  Add a parity CI check: a small script that calls both endpoints
  with identical inputs and diffs the output. Fail the build on
  any field divergence other than timestamp.

Part B — Test-hook hardening.
  Gate the Phase 1 test hooks behind an environment variable:
    AUREON_MMF_TEST_HOOKS_ENABLED=1  (default: unset / disabled)
  When disabled:
    - subscription_engine.set_test_cato_override is a no-op that
      logs a warning.
    - /api/mmf/_test/cato_override returns 403.
  When enabled:
    - Current behavior.
  Railway service variable in prod MUST be unset or 0. Verified by
  a one-liner curl in the Phase 2 acceptance checklist.

Commit messages:
  `fix(cato): align external MCP server and in-process twin to v0.2.3`
  `harden(mmf): gate Phase 1 test hooks behind env flag`

Expected DSOR additions: none.
Expected schema change: external MCP server output (field rename).
Operator check: run the parity CI script before merging.
```

---

## PROMPT P2-5 — Validation matrix (Phase 2 acceptance)

```
Sam — Phase 2, Prompt 5. Full validation matrix.

Re-run all 6 Phase 1 breaks AGAINST A PERSISTED INSTANCE + run 3
new Phase 2 breaks that exercise the atomic DvP path.

Phase 1 breaks (re-run):
  1. Stale oracle
  2. Liquidity fee threshold
  3. KYC exception
  4. Cato HOLD (now via a properly env-flagged override, no
     production pathway)
  5. Duplicate subscription
  6. Currency mismatch

New Phase 2 breaks:
  7. Persistence survive-restart
     - Seed subs, trigger a sweep, capture state.
     - Restart Railway service (via no-op push or dashboard).
     - Verify state restored exactly; /api/journal shows the
       pre-restart DSOR entries.
  8. XRPL testnet negative — unauthorized investor address
     - Submit a Lane D subscription with an investor whose MMF
       trust line is NOT authorized on ShareIssuer.
     - Expected: tecNO_AUTH on the atomic Payment;
       DIGITAL_SUBSCRIPTION_REJECTED DSOR; fund_state unchanged.
  9. XRPL testnet negative — no offer posted
     - Submit a Lane D subscription where the OfferCreate step is
       deliberately skipped (via a test hook: force_skip_offer=True
       in the xrpl_integration adapter).
     - Expected: tecPATH_PARTIAL on the Payment;
       DIGITAL_SUBSCRIPTION_REJECTED DSOR; fund_state unchanged.

After all 9 breaks:
  - Export /api/mmf/dsor; count by event_type.
  - Every break must have at least one DSOR entry.
  - No circuit breakers open in steady state.
  - Persisted state file on Railway volume reflects final state.

Commit message: `test(mmf): Phase 2 validation matrix — 9 breaks,
                  DSOR + persistence + XRPL testnet negatives`

Phase 2 COMPLETE when:
  ✓ All 9 breaks produce correct behavior
  ✓ Every break has a DSOR entry
  ✓ Fund state survives a Railway redeploy cleanly
  ✓ Lane D emits real XRPL testnet tx hashes, verifiable on
    testnet.xrpl.org
  ✓ Cato external MCP server and in-process twin return bit-for-bit
    identical decisions for identical inputs
  ✓ Test hooks are inert in prod (env flag off)
  ✓ Leto MMF panel shows pending-HITL queue + real tx hashes in
    the Lane D audit trail
```

---

## Execution order

```
P2-1 → confirm persistence survives restart → P2-2
P2-2 → confirm Lane D sub produces real testnet tx hash → P2-3
P2-3 → confirm reverse DvP burns shares correctly → P2-4
P2-4 → confirm parity CI passes + test hooks inert → P2-5
P2-5 → all 9 breaks pass → PHASE 2 COMPLETE → Phase 3 brief
```

Same discipline as Phase 1: do not skip steps; do not start the next
prompt until the current confirms clean.

---

## What Phase 3 inherits (explicit punts)

- Business-day + holiday calendar (T+1 settlement real dates).
- Real weekly liquid asset % from portfolio composition.
- Per-lot cost-basis tracking (WAC / tax lots).
- Multi-lane investor support (F + D accounts under one investor_id).
- Dividend / income distribution mechanics (monthly CNAV share
  creation).
- NAV strike time discipline (4:00pm ET cutoff, strike-based
  settlement ordering).
- Mainnet migration discipline (the doctrine switch from
  testnet-only to controlled mainnet rollout).

Phase 3 begins when Phase 2 has run cleanly for at least one full
week of daily NAV sweeps with no open circuit breakers and verified
persistence across three or more Railway redeploys.

---

*Cleared Hot. Build begins on P2-1 when operator signals go.*
