# MMF Sandbox — Mechanics Map v2
**Status:** PRE-BUILD. Review and sign off before any code is written.
**Date:** 2026-04-21 (updated from v1)
**Operator:** Guillermo Ravelo (CAOM-001)

**What changed from v1:**
- Redemption mechanics corrected — no HITL on size, fully automatic per regulation
- NAV jurisdiction matrix added — this is load-bearing for the build
- Live issuer practices (BUIDL, BENJI, Ondo) mapped to our architecture
- Q3/Q5 answers updated — FRED live, redemptions mirror subscriptions
- Liquidity fee mechanics added (SEC 2023 Final Rule, effective Oct 2023)

---

## 1. What This Is

A governed dual-lane sandbox fund absorbing both FIAT and digital asset
subscriptions into a single fund vehicle. Both lanes feed the same NAV
oracle, hit the same 17:00 ET sweep, and are governed by the same Aureon
doctrine. Full DSOR lineage on every event.

---

## 2. NAV Jurisdiction Matrix — LOAD BEARING

This is why there is no single NAV. The NAV type is dictated by where
the fund is domiciled and who the investors are. The sandbox models
the US institutional lane as primary, with EU/UCITS as a declared
second NAV class.

| Jurisdiction | Fund Type | NAV Type | NAV Precision | Redemption Basis |
|---|---|---|---|---|
| **US — Government MMF** | 1940 Act | CNAV (stable $1.00) | Rounded to $0.0001 | At stable $1.00 |
| **US — Institutional Prime MMF** | 1940 Act | **FNAV (floating)** | 4 decimal places | At floating market NAV |
| **US — Retail MMF** | 1940 Act | CNAV (stable $1.00) | Rounded to $0.0001 | At stable $1.00 |
| **EU — Public Debt CNAV** | UCITS/MMFR | CNAV | Rounded to nearest % | At constant price |
| **EU — LVNAV** | UCITS/MMFR | Stable within ±20bps | 4 decimal places | Stable unless >20bps deviation |
| **EU — VNAV (Short Term)** | UCITS/MMFR | **Floating** | 4 decimal places | At floating market NAV |
| **EU — VNAV (Standard)** | UCITS/MMFR | **Floating** | 4 decimal places | At floating market NAV |

**Sandbox NAV configuration:**
- **Class F (FIAT lane)** — US Government MMF profile: CNAV, stable $1.00
  per share. Simulates the most common institutional cash management vehicle.
- **Class D (Digital lane)** — US Institutional Prime MMF profile: FNAV
  (floating), 4 decimal places. This is the correct structure for a tokenized
  institutional fund — matches BUIDL, BENJI, and Ondo's operating model.
- **Class E (EU/UCITS, future)** — LVNAV, stable within ±20bps. Not in Phase 1.
  Declared here so the NAV engine is built to support it.

**Why this matters for the build:**
The NAV engine must be capable of producing both CNAV (rounded) and FNAV
(4 decimal places) from the same oracle inputs. The sweep logic differs:
CNAV rounds and holds; FNAV marks to market and floats. Two NAV methods,
one engine.

---

## 3. Fund Vehicle

| Parameter | Value |
|---|---|
| Name | Arcadia Liquidity Fund — Sandbox Series |
| AUM (paper) | $10M notional |
| Gross yield target | 5.0–5.2% (FRED-sourced T-bill/SOFR rate) |
| Class F NAV | CNAV — stable $1.00 |
| Class D NAV | FNAV — floating, 4 decimal places |
| NAV sweep time | 17:00 ET daily (Thifur-R scheduled, automatic) |
| Settlement currency | USD (Lane F) / USDC (Lane D) |
| Yield distribution | Daily accrual, end-of-month distribution (BUIDL model) |

---

## 4. Redemption Mechanics — CORRECTED

**Redemptions in MMFs are automatic and on-demand. No HITL on size.**

This is the key correction from v1. MMF regulation requires that investors
can redeem on demand. The SEC 2023 Final Rule (effective October 2023)
explicitly removed redemption gates for institutional prime MMFs and
replaced them with mandatory liquidity fees — which are automatic, not
human-gated.

### What actually governs redemption behavior:

**SEC 2023 Final Rule (US Institutional Prime MMFs):**
- Daily net redemptions >5% of net assets → **mandatory automatic liquidity fee**
  applied same day. Fee calculated from actual liquidity costs. No gate, no HITL.
- Board may apply discretionary fee at any time if in fund's best interest.
- No redemption gates permitted for institutional prime MMFs (removed Oct 2023).
- Weekly liquid assets must be maintained at ≥30% (hard floor).

**EU MMFR (Public Debt CNAV + LVNAV):**
- Mandatory fees and gates when weekly liquid assets fall below 10%.
- These are board-level decisions, not individual-redemption gates.
- Applied to the entire fund class, not per investor.

**Tokenized MMF practice (BUIDL, BENJI, Ondo):**
- BUIDL holders can convert to USDC around the clock through a smart
  contract-enabled liquidity facility via Circle — 24/7 automatic.
- Ondo's OUSG offers instant 24/7 minting and redemptions in USDC or PYUSD,
  with the number of tokens multiplied by NAV determining what an investor receives.
- BUIDL smart contracts handle redemptions with no manual work — investors
  sell tokens back to the fund and receive the equivalent cash value automatically.
- For redemptions, the transfer agent removes ("burns") the token from the
  blockchain, the fund liquidates the necessary assets, and sends cash or
  stablecoins to the transfer agent's account for payout.

### Sandbox redemption model:

**Lane F (FIAT/CNAV):**
```
Investor submits redemption request
    → Thifur-R: validate shares owned, compute redemption value at CNAV ($1.00)
    → Check daily net redemption total against 5% NAV threshold
    → If threshold breached: calculate and apply mandatory liquidity fee (automatic)
    → Queue redemption for next sweep (17:00 ET) or same-day if before cutoff
    → Thifur-R: process payout, debit shares from TA register
    → DSOR: FIAT_REDEMPTION_COMPLETE (+ LIQUIDITY_FEE_APPLIED if triggered)
```

**Lane D (Digital/FNAV):**
```
Investor submits redemption (sends shares back to issuer wallet)
    → Thifur-J: verify sender is allowlisted, shares are valid
    → Thifur-R: compute redemption value at current FNAV (4 decimal places)
    → Check daily net redemption total against 5% NAV threshold
    → If threshold breached: apply mandatory liquidity fee (automatic)
    → Cato gate: confirm settlement rail is viable
    → Thifur-R: atomic reverse DvP — burn shares ↔ release USDC in one tx
    → XRPL finality ~6–8s
    → DSOR: DIGITAL_REDEMPTION_COMPLETE (+ LIQUIDITY_FEE_APPLIED if triggered)
```

**HITL on redemptions:** Only if Cato returns HOLD/ESCALATE (rail issue),
or if the fund-level weekly liquid asset buffer drops below 30% (systemic
condition, board-level decision). Neither is an individual redemption gate.

**"Redemptions are according to what goes in"** — confirmed. Lane F
subscribers redeem in USD. Lane D subscribers redeem in USDC. The
redemption currency mirrors the subscription currency.

---

## 5. Yield Mechanics — The Spread

Yield source: **FRED live** (SOFR, T-bill rates via Cato's existing FRED
connectivity). Not simulated. This is a meaningful upgrade from v1.

```
NAV engine pulls from FRED at each sweep:
    → DGS1MO (1-month T-bill rate) — primary yield reference
    → SOFR (Secured Overnight Financing Rate) — secondary / repo proxy
    → Compute gross yield per share per day = (rate / 365) * NAV
    → Apply management fee per day = (fee_bps / 10000 / 365) * NAV
    → Net yield per share = gross - fee
    → Accrue to all share positions
    → Distribute at month-end (BUIDL model)
```

Cost advantage table (unchanged from v1, now confirmed with live data):

| Cost Item | Lane F (FIAT) | Lane D (Digital) | Delta |
|---|---|---|---|
| TA (Transfer Agent) fee | ~3–5bps/yr | 0 — on-chain register | 3–5bps |
| Settlement cost/tx | ~$25–35 Fedwire | ~$0.00043 XRPL | structural |
| Cash drag T+1 float | 1 day per sub | 0 — atomic, instant | ~$1,370/day per $100M |
| NAV labor | fund accountant | Thifur-R automated | structural |

**The spread is the live running number in Leto.**

---

## 6. Live Issuer Comparison — Architecture Gaps We Fill

| Issuer | AUM | Yield (7D) | What they do | What they don't publish |
|---|---|---|---|---|
| BlackRock BUIDL | $2B+ | ~3.43% | Smart contract yield accrual, USDC 24/7 redemption via Circle | Operating model governance between payment dates |
| Franklin BENJI | $894M | ~3.54% | On-chain shareholder registry (BENJI = 1 share), 10 chains | Governance layer, continuous compliance surveillance |
| Ondo OUSG | $1.4B+ | ~4.8% | Instant 24/7 mint/redeem in USDC/PYUSD | Audit chain, HITL gate framework |
| JPMorgan MONY | $100M | — | USDC sub/redemption, qualified investors, Ethereum | Governance model not public |

**The gap we fill:** None of the above has published a complete agentic
operating model with continuous compliance surveillance, HITL gate
framework for exceptions, and an immutable audit chain designed for
regulatory submission. That is what this sandbox demonstrates.

---

## 7. Agent Assignments — CORRECTED

| Function | Agent | Mode | Automatic/HITL? |
|---|---|---|---|
| KYC/onboarding | Thifur-J | Bounded autonomy | **Automatic** on pass; HITL on exception only |
| Rail selection | Cato / Verana L0 | Automated | Automatic PROCEED; HITL only on HOLD/ESCALATE |
| NAV sweep | Thifur-R | Deterministic | **Fully automatic. Never HITL.** |
| Yield accrual | Thifur-R | Deterministic | Automatic |
| Liquidity fee calculation | Thifur-R | Deterministic | Automatic (triggered by threshold, not human) |
| Subscription — Lane F | Thifur-R | Deterministic | Automatic |
| Subscription — Lane D | Thifur-J → Thifur-R | Bounded → Deterministic | Automatic |
| Redemption — Lane F | Thifur-R | Deterministic | **Automatic** |
| Redemption — Lane D | Thifur-J → Thifur-R | Bounded → Deterministic | **Automatic** |
| Compliance surveillance | Thifur-J | Continuous | Automatic; HITL on anomaly score threshold |
| Audit / DSOR | DSOR engine | Always-on | Automatic |
| Operator console | Leto | Display | Operator-initiated only |

---

## 8. DSOR Event Types

```
# Subscription
FIAT_SUBSCRIPTION_INTENT
FIAT_SUBSCRIPTION_COMPLETE
FIAT_SUBSCRIPTION_REJECTED

DIGITAL_SUBSCRIPTION_INTENT
DIGITAL_SUBSCRIPTION_COMPLETE
DIGITAL_SUBSCRIPTION_REJECTED

# Redemption
FIAT_REDEMPTION_INTENT
FIAT_REDEMPTION_COMPLETE
DIGITAL_REDEMPTION_INTENT
DIGITAL_REDEMPTION_COMPLETE

# Liquidity fee (automatic, threshold-triggered)
LIQUIDITY_FEE_APPLIED          # includes: lane, fee_bps, redemption_pct_of_nav
LIQUIDITY_FEE_WAIVED           # de minimis exemption

# NAV
NAV_SWEEP_TRIGGERED
NAV_SWEEP_COMPLETE             # includes: cnav, fnav, gross_yield, net_yield, fee_accrued,
                               #           fred_rate_used, sofr_used, aum_by_lane
NAV_SWEEP_HALTED               # oracle stale or variance >0.1%

# Yield
YIELD_ACCRUAL_POSTED           # daily
YIELD_DISTRIBUTION_EXECUTED    # monthly

# Compliance / HITL (exception paths)
KYC_EXCEPTION_HITL_GATE_OPEN
KYC_EXCEPTION_HITL_GATE_RESOLVED
CATO_HOLD_OPERATOR_DECISION
COMPLIANCE_ANOMALY_FLAGGED
LIQUIDITY_BUFFER_WARNING       # weekly liquid assets <30%
```

---

## 9. Known Breaks to Test

| Break Scenario | Lane | Expected Behavior |
|---|---|---|
| FRED feed unavailable at sweep | Both | Thifur-R halts, NAV_SWEEP_HALTED, uses last known rate + flags stale |
| Oracle feed stale >15min | Both | Thifur-R halts sweep, NAV_SWEEP_HALTED, C2 escalation |
| Daily redemptions hit 5% NAV | Both | LIQUIDITY_FEE_APPLIED automatically, no gate |
| Weekly liquid assets <30% | Both | LIQUIDITY_BUFFER_WARNING, board-level escalation logged |
| KYC miss on Digital sub | D | Thifur-J blocks, KYC_EXCEPTION_HITL_GATE_OPEN |
| Cato returns HOLD | D | DvP paused, CATO_HOLD_OPERATOR_DECISION, operator resolves |
| XRPL finality timeout >30s | D | DIGITAL_SUBSCRIPTION_REJECTED, clean DSOR record |
| FNAV deviates >20bps from CNAV | D | Logged as variance event; relevant for future EU LVNAV class |
| Duplicate subscription attempt | Both | Idempotency check, second attempt rejected cleanly |
| Redemption in wrong currency | Both | Rejected at intake — Lane F redeems USD, Lane D redeems USDC |

---

## 10. Confirmed Answers to v1 Open Questions

| # | Question | Answer |
|---|---|---|
| 1 | Sandbox AUM scale | **$10M confirmed** |
| 2 | Lane D Phase 1 chain | **Fully simulated** — validate NAV engine first, XRPL in Phase 2 |
| 3 | Yield source | **FRED live** via Cato's existing connectivity (DGS1MO + SOFR) |
| 4 | Lane D cash instrument | **USDC** |
| 5 | Redemption threshold | **No threshold** — redemptions automatic per regulation. Liquidity fee at 5% daily net redemptions, automatic. |
| 6 | On-demand sweep trigger | **Confirmed** — `/api/mmf/sweep/trigger` for test overrides |

---

## 11. Module Structure

```
aureon/
  mmf/
    __init__.py
    nav_engine.py          # CNAV + FNAV calculation; FRED pull; 17:00 sweep; circuit breaker
    subscription_engine.py # Lane F + Lane D intake, routing, idempotency, DSOR stamps
    redemption_engine.py   # Automatic processing; liquidity fee calculation; USDC/USD routing
    surveillance_engine.py # Compliance anomaly monitoring; liquidity buffer watch
    onboarding.py          # KYC/AML intake; allowlist write; HITL exception path
    yield_engine.py        # Daily accrual; month-end distribution; FRED rate pull
    audit_mmf.py           # MMF-specific DSOR event extensions
```

Routes (Railway server.py additions):
```
/api/mmf/status              GET   Fund overview — AUM, NAV (CNAV+FNAV), yield by lane
/api/mmf/subscribe           POST  Submit subscription — {lane: "F"|"D", amount, investor_id}
/api/mmf/redeem              POST  Submit redemption — mirrors subscription lane automatically
/api/mmf/nav                 GET   Current NAV — both CNAV and FNAV, last sweep, next sweep ETA
/api/mmf/yield               GET   Accrual state — daily rate, YTD, by lane
/api/mmf/dsor                GET   MMF-specific DSOR events
/api/mmf/hitl/resolve        POST  Operator resolves KYC or Cato HOLD exception
/api/mmf/sweep/trigger       POST  Manual sweep override (test only, gated)
```

---

## 12. Build Sequence — Crawl-Walk-Run (unchanged)

**Phase 1 — Crawl: NAV engine + both lanes simulated**
- `nav_engine.py` — CNAV + FNAV, FRED-sourced rate, 17:00 sweep
- `yield_engine.py` — daily accrual, month-end distribution
- `subscription_engine.py` — Lane F + Lane D (fully simulated, no XRPL yet)
- `redemption_engine.py` — automatic, liquidity fee logic, currency mirroring
- DSOR events for all lifecycle events
- Leto MMF panel — AUM by lane, NAV (both), yield spread, cost spread
- **Validate:** NAV sweep fires, DSOR complete, yield accrues, fee triggers correctly

**Phase 2 — Walk: Lane D wired to XRPL testnet**
- Wire `subscription_engine.py` Lane D to existing XRPL DvP code
- Cato gate in series before DvP submission
- Atomic DvP + reverse DvP (redemption burn) on XRPL testnet
- Real tx hashes in DSOR
- **Validate:** yield spread visible in Leto, XRPL finality within doctrine bounds

**Phase 3 — Run: Break testing**
- Trigger all 10 break scenarios from §9 deliberately
- Verify DSOR captures every break with complete lineage
- Verify automatic liquidity fee fires at exactly 5% threshold
- Verify NAV circuit breaker halts on stale oracle
- Document in evidence package

**Do not start Phase 2 until Phase 1 validates clean.
Do not start Phase 3 until Phase 2 validates clean.**

---

*Map v2 complete. Sign off → Phase 1 build begins.*
