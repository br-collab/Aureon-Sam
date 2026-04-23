# MMF Sandbox — Phase 1 Build Prompts
**Authority:** CAOM-001 — Operator Cleared Hot
**Date:** 2026-04-21
**Target:** Aureon Railway backend (`br-collab/aureon`, `server.py`)
**Doctrine:** Build once. Iterative. Bugs are expected. DSOR captures everything.

---

## PROMPT 1 — Module scaffold + FRED yield engine

```
Sam — Phase 1 MMF sandbox. Build once, iteratively.

Create the module scaffold and yield data layer:

1. Create `aureon/mmf/__init__.py` — empty, marks the package.

2. Create `aureon/mmf/yield_engine.py`:
   - Pull DGS1MO (1-month T-bill rate) and SOFR from FRED via the
     existing Cato/FRED connectivity already in the codebase.
     If Cato client isn't directly importable, call the Railway
     /api/cato/settlement-context endpoint internally — it already
     has SOFR. For DGS1MO use FRED API directly
     (https://api.stlouisfed.org/fred/series/observations) with
     FRED_API_KEY from environment.
   - Expose: `get_current_yield_inputs() -> dict` returning:
     {dgs1mo_pct, sofr_pct, source, fetched_at, stale: bool}
   - Stale = True if data is >4 hours old.
   - Cache result in module-level dict with TTL=3600s.
   - Expose: `compute_daily_accrual(nav_per_share, management_fee_bps) -> dict`
     returning: {gross_yield_daily, fee_daily, net_yield_daily, annual_rate_pct}
   - Use DGS1MO as primary rate. Fall back to SOFR if DGS1MO unavailable.
   - Log which rate was used and whether fallback was triggered.

3. Add `FRED_API_KEY` to `.env.example` with a comment.

Commit message: `feat(mmf): module scaffold + FRED yield engine`

Do not touch server.py yet. Yield engine first, standalone.
Test it: call `get_current_yield_inputs()` and log the output.
Tell me what FRED returned.
```

---

## PROMPT 2 — NAV engine (CNAV + FNAV, sweep logic, circuit breaker)

```
Sam — Phase 1 MMF, Prompt 2. Yield engine is done. Now the NAV engine.

Create `aureon/mmf/nav_engine.py`:

FUND CONFIGURATION (module-level constants):
  FUND_NAME = "Arcadia Liquidity Fund — Sandbox Series"
  CLASS_F_TYPE = "CNAV"        # stable $1.0000
  CLASS_D_TYPE = "FNAV"        # floating, 4 decimal places
  MANAGEMENT_FEE_BPS = 15      # 15bps/yr (sandbox — competitive vs BUIDL 20-50bps)
  SWEEP_HOUR_ET = 17           # 17:00 ET daily
  ORACLE_STALE_THRESHOLD_MIN = 15
  NAV_VARIANCE_HALT_PCT = 0.10  # halt if NAV moves >0.1% unexplained

NAV STATE (module-level, in-memory for Phase 1):
  - cnav: Decimal = Decimal("1.0000")   # Class F — stable, rounded
  - fnav: Decimal = Decimal("1.0000")   # Class D — floating, 4 decimal places
  - last_sweep_at: datetime | None
  - next_sweep_at: datetime             # next 17:00 ET
  - sweep_count: int = 0
  - last_fred_rate: dict | None
  - circuit_open: bool = False
  - circuit_reason: str = ""

FUNCTIONS:

`compute_nav() -> dict`
  - Call yield_engine.get_current_yield_inputs()
  - If stale or unavailable: set circuit_open=True, circuit_reason="oracle stale",
    return {status: "HALTED", reason: ...}
  - Compute FNAV: previous_fnav + net_yield_daily (from yield_engine)
  - CNAV stays $1.0000 — does not float (US Government MMF model)
  - Check variance: if abs(new_fnav - old_fnav) / old_fnav > ORACLE_STALE_THRESHOLD:
    set circuit_open=True, halt
  - Return {cnav, fnav, gross_yield_daily, net_yield_daily, fee_daily,
            annual_rate_pct, fred_rate_used, sweep_at, status: "OK"}

`run_sweep() -> dict`
  - Gate: if circuit_open, return {status: "HALTED", reason: circuit_reason}
  - Call compute_nav()
  - Update module state
  - Increment sweep_count
  - Emit DSOR event NAV_SWEEP_COMPLETE (or NAV_SWEEP_HALTED)
  - Return full sweep result

`get_nav_state() -> dict`
  - Return current NAV state snapshot for API consumption

`next_sweep_dt() -> datetime`
  - Return next 17:00 ET as UTC datetime

DSOR integration:
  - Import the existing DSOR stamping function from the codebase.
  - NAV_SWEEP_COMPLETE stamp must include:
    cnav, fnav, gross_yield, net_yield, fee_accrued,
    fred_rate_used, sofr_used, sweep_count, aum_class_f,
    aum_class_d, status
  - NAV_SWEEP_HALTED stamp must include: reason, circuit_reason,
    last_good_nav, halted_at

SCHEDULER:
  - Add a background thread in nav_engine.py that fires run_sweep()
    daily at 17:00 ET. Use threading + a sleep loop that checks
    time every 60s. Do NOT use APScheduler — stdlib only per Leto pattern.
  - Expose `start_nav_scheduler()` to be called at server boot.

Commit message: `feat(mmf): NAV engine — CNAV/FNAV, 17:00 sweep, circuit breaker`

Test: call run_sweep() manually once. Show me the DSOR output.
```

---

## PROMPT 3 — Fund state + subscription engine (both lanes, simulated)

```
Sam — Phase 1 MMF, Prompt 3. NAV engine done. Now fund state and subscriptions.

Create `aureon/mmf/fund_state.py`:

FUND STATE (module-level, in-memory):
  - shares_f: Decimal = 0          # Class F shares outstanding
  - shares_d: Decimal = 0          # Class D shares outstanding
  - aum_f: Decimal = 0             # Class F AUM in USD
  - aum_d: Decimal = 0             # Class D AUM in USD
  - daily_redemptions_f: Decimal = 0   # reset at each sweep
  - daily_redemptions_d: Decimal = 0   # reset at each sweep
  - total_subscriptions: int = 0
  - total_redemptions: int = 0
  - investors: dict[str, dict]     # investor_id -> {lane, shares, cost_basis}

  Expose:
    get_state() -> dict
    reset_daily_counters()         # called by NAV sweep
    weekly_liquid_asset_pct() -> Decimal  # simulated: always returns 85% in Phase 1

Create `aureon/mmf/subscription_engine.py`:

FUNCTION: `process_subscription(investor_id, lane, amount_usd) -> dict`

Lane F (FIAT — simulated):
  - Validate: amount_usd > 0, investor_id not empty
  - KYC check: simple allowlist dict in module (seed 3 approved investors).
    If not on list: return {status: "KYC_EXCEPTION", hitl_required: True}
  - Simulate T+1 timing: record subscription_intent_at = now(),
    settlement_at = next_business_day 09:00 ET (simulated, not real wait)
  - Compute shares = amount_usd / cnav (from nav_engine)
  - Update fund_state: shares_f += shares, aum_f += amount_usd
  - DSOR: FIAT_SUBSCRIPTION_COMPLETE
  - Return {status: "COMPLETE", shares, nav_used, lane: "F",
            settlement_simulated_at, dsor_id}

Lane D (Digital — simulated for Phase 1, XRPL in Phase 2):
  - Same KYC check
  - Cato gate check: call /api/cato/gate internally.
    If HOLD or ESCALATE: return {status: "CATO_HOLD", hitl_required: True,
    cato_decision: ..., cato_chain: ...}
  - Simulate atomic DvP: no real XRPL call yet.
    settlement_at = now() + 8 seconds (simulated finality)
  - Compute shares = amount_usd / fnav (from nav_engine) — 4 decimal places
  - Update fund_state: shares_d += shares, aum_d += amount_usd
  - DSOR: DIGITAL_SUBSCRIPTION_COMPLETE (mark as SIMULATED in Phase 1)
  - Return {status: "COMPLETE", shares, nav_used, lane: "D",
            settlement_simulated_at, simulated: True, dsor_id}

Idempotency: hash (investor_id + lane + amount + minute_bucket) ->
  reject duplicate within same 60s window.

Commit message: `feat(mmf): fund state + subscription engine — dual lane, simulated`

Test: run 2 Lane F subs + 2 Lane D subs. Show me fund_state and the 4 DSOR entries.
```

---

## PROMPT 4 — Redemption engine (automatic, liquidity fee, currency mirroring)

```
Sam — Phase 1 MMF, Prompt 4. Subscriptions done. Now redemptions.

Create `aureon/mmf/redemption_engine.py`:

CONSTANTS:
  LIQUIDITY_FEE_THRESHOLD_PCT = Decimal("0.05")  # 5% daily net redemptions
  LIQUIDITY_FEE_BPS = Decimal("10")              # 10bps fee when threshold breached
                                                  # (de minimis exemption below 1bp)
  WEEKLY_LIQUID_ASSET_FLOOR_PCT = Decimal("0.30") # 30% floor — warning threshold

FUNCTION: `process_redemption(investor_id, shares_to_redeem) -> dict`

  - Validate: investor exists in fund_state.investors, shares_to_redeem > 0,
    shares_to_redeem <= investor's current shares
  - Determine lane from investor record — redemption currency mirrors subscription:
    Lane F → USD payout / Lane D → USDC payout
  - Get current NAV: Lane F uses cnav ($1.0000), Lane D uses fnav (4dp)
  - Compute gross_payout = shares_to_redeem * nav
  - Check liquidity fee:
    - Compute: (daily_redemptions_lane + gross_payout) / aum_lane
    - If > LIQUIDITY_FEE_THRESHOLD_PCT:
        fee_amount = gross_payout * (LIQUIDITY_FEE_BPS / 10000)
        if fee_amount < gross_payout * Decimal("0.0001"):
            fee_amount = 0  # de minimis exemption
        net_payout = gross_payout - fee_amount
        DSOR: LIQUIDITY_FEE_APPLIED
    - Else: net_payout = gross_payout, fee_amount = 0
  - Update fund_state:
    - Remove shares from investor record
    - Reduce shares_outstanding and aum for the lane
    - Increment daily_redemptions_lane
  - Check weekly liquid asset floor (simulated 85% always clears in Phase 1,
    but the check must run and log):
    - If weekly_liquid_asset_pct() < 0.30: DSOR LIQUIDITY_BUFFER_WARNING
  - DSOR: FIAT_REDEMPTION_COMPLETE or DIGITAL_REDEMPTION_COMPLETE
    (mark DIGITAL as SIMULATED in Phase 1 — no real USDC transfer yet)
  - Return {status: "COMPLETE", shares_redeemed, gross_payout, fee_amount,
            net_payout, currency: "USD"|"USDC", lane, nav_used,
            liquidity_fee_applied: bool, dsor_id}

Commit message: `feat(mmf): redemption engine — automatic, liquidity fee, currency mirror`

Test: subscribe 2 investors Lane F, redeem both. Then force the 5%
threshold by redeeming a large amount and confirm LIQUIDITY_FEE_APPLIED
fires in DSOR. Show me all DSOR entries.
```

---

## PROMPT 5 — Railway routes + Leto MMF panel

```
Sam — Phase 1 MMF, Prompt 5. Engines done. Wire to Railway and Leto.

PART A — Railway server.py routes:

Add to server.py (find the right section near other api routes):

  POST /api/mmf/subscribe
    Body: {investor_id, lane ("F"|"D"), amount_usd}
    Calls: subscription_engine.process_subscription()
    Returns: subscription result + updated fund state snapshot

  POST /api/mmf/redeem
    Body: {investor_id, shares_to_redeem}
    Calls: redemption_engine.process_redemption()
    Returns: redemption result

  GET /api/mmf/nav
    Calls: nav_engine.get_nav_state()
    Returns: {cnav, fnav, last_sweep_at, next_sweep_at, sweep_count,
              circuit_open, circuit_reason, annual_rate_pct, fred_rate_used}

  GET /api/mmf/status
    Calls: fund_state.get_state() + nav_engine.get_nav_state()
    Returns: unified fund overview:
      {aum_f, aum_d, aum_total, shares_f, shares_d,
       cnav, fnav, annual_rate_pct, yield_spread_bps,
       total_subscriptions, total_redemptions, circuit_open}

  GET /api/mmf/dsor
    Returns: all DSOR entries where event_type starts with
    "FIAT_", "DIGITAL_", "NAV_", "LIQUIDITY_", "YIELD_"
    (filter from existing DSOR store)

  POST /api/mmf/sweep/trigger
    Operator-only manual sweep override for testing.
    Calls: nav_engine.run_sweep()
    Returns: sweep result

  POST /api/mmf/hitl/resolve
    Body: {event_id, decision ("approve"|"reject"), reason}
    For KYC exceptions and Cato HOLD resolutions.
    DSOR: KYC_EXCEPTION_HITL_GATE_RESOLVED or CATO_HOLD_OPERATOR_DECISION

Also: call nav_engine.start_nav_scheduler() at server boot
(near where the health thread starts).

PART B — Leto index.html MMF panel:

Add a new panel to the Leto dashboard: "MMF · FUND CONSOLE"

Tiles (polls /api/mmf/status via Railway proxy every 30s):
  - AUM: Class F | Class D | Total (USD)
  - NAV: CNAV ($1.0000 stable) | FNAV (4dp floating)
  - Yield: annual rate % | daily accrual | source (FRED DGS1MO or SOFR fallback)
  - Cost Spread: "Lane D saves Xbps vs Lane F" — computed from fee delta
  - Next Sweep: countdown timer to 17:00 ET
  - Circuit: GREEN "NAV ENGINE OK" or RED "HALTED — {reason}"
  - Session counters: total subs | total redemptions | liquidity fees triggered

Add to Leto server.py:
  GET /api/mmf/status — proxy to Railway /api/mmf/status (30s cache)
  POST /api/mmf/sweep/trigger — proxy to Railway (no cache)

Add to Leto README endpoint table: all 7 MMF routes.

Commit message: `feat(mmf): Railway routes + Leto MMF panel — Phase 1 complete`

After deploying: trigger a manual sweep via /api/mmf/sweep/trigger.
Show me the Leto panel screenshot path and the DSOR output.
```

---

## PROMPT 6 — Break testing (Phase 1 validation)

```
Sam — Phase 1 MMF, Prompt 6. All engines wired. Now break it.

Run the following break scenarios in sequence. For each:
  - Document what happened
  - Show the DSOR entry (or confirm it's missing if that's the bug)
  - Note whether behavior matched the mechanics map

BREAK 1 — Stale oracle
  Temporarily set yield_engine cache TTL to 0 and mock a stale response.
  Call /api/mmf/sweep/trigger.
  Expected: NAV_SWEEP_HALTED in DSOR, circuit_open=True in /api/mmf/nav.

BREAK 2 — Liquidity fee threshold
  Subscribe investor A to Lane F: $9,500 (95% of a $10,000 test fund).
  Subscribe investor B to Lane F: $500.
  Have investor A redeem all $9,500.
  Expected: daily redemptions hit >5% of AUM,
  LIQUIDITY_FEE_APPLIED in DSOR, fee deducted from payout.

BREAK 3 — KYC exception
  Submit a subscription with investor_id not on the allowlist.
  Expected: {status: "KYC_EXCEPTION", hitl_required: True},
  KYC_EXCEPTION_HITL_GATE_OPEN in DSOR.
  Then call /api/mmf/hitl/resolve with decision "reject".
  Expected: KYC_EXCEPTION_HITL_GATE_RESOLVED in DSOR.

BREAK 4 — Cato HOLD simulation
  Temporarily mock the Cato gate response to return HOLD for Lane D.
  Submit a Lane D subscription.
  Expected: {status: "CATO_HOLD", hitl_required: True},
  CATO_HOLD_OPERATOR_DECISION in DSOR.

BREAK 5 — Duplicate subscription (idempotency)
  Submit the exact same subscription twice within 60 seconds.
  Expected: second attempt rejected cleanly, no duplicate DSOR entry.

BREAK 6 — Redemption currency mismatch attempt
  Subscribe investor to Lane F (USD).
  Attempt to retrieve USDC (simulate by passing currency="USDC" if route accepts it).
  Expected: rejected — Lane F always redeems USD. DSOR records rejection.

After all 6 breaks:
  Export /api/mmf/dsor and count entries.
  Every break must have a DSOR entry. If any break has no DSOR record,
  that is a bug — flag it explicitly before marking Phase 1 complete.

Commit message: `test(mmf): Phase 1 break testing — 6 scenarios, full DSOR validation`

Phase 1 is complete when:
  ✓ All 6 breaks produce correct behavior
  ✓ Every break has a DSOR entry
  ✓ NAV sweep fires on schedule (or manual trigger)
  ✓ FRED rate is live (not hardcoded)
  ✓ Leto MMF panel shows live data
  ✓ No open circuit breakers in steady state
```

---

## Execution Order

```
Prompt 1 → confirm FRED returns live data → Prompt 2
Prompt 2 → confirm sweep fires + DSOR output → Prompt 3
Prompt 3 → confirm 4 DSOR entries → Prompt 4
Prompt 4 → confirm liquidity fee fires → Prompt 5
Prompt 5 → confirm Leto panel live → Prompt 6
Prompt 6 → all 6 breaks pass → Phase 1 COMPLETE → Phase 2 brief
```

**Do not skip steps. Do not start the next prompt until the current
one confirms clean. Bugs are expected — document them in the nightly
log, fix them, re-validate.**

---

*Cleared Hot. Build begins on Prompt 1.*
