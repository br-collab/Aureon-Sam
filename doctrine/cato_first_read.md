# Cato — First-Read Doctrine Note

> **Read-only:** Sam has not touched Cato's code. This note is a
> structural summary + honest-assessment artifact after reading the
> 2026-04-14 copy of `index.js` (v0.2.3, 1,227 lines) and `README.md`.
> **Acronyms:** MCP = Model Context Protocol. eFICC = electronic Fixed
> Income, Currencies & Commodities. FICC = Fixed Income Clearing
> Corporation (the DTCC subsidiary). DSOR = Doctrine/State/Outcome/Record
> (Aureon pre-trade context package). SOFR = Secured Overnight
> Financing Rate. OFR = Office of Financial Research. FSI = Financial
> Stress Index. MMF = Money Market Fund. DvP = Delivery-versus-Payment.
> L0 / L1 / L2 = protocol layer (Verana L0 = governance layer; Ethereum
> L1 = base chain; Base/Arbitrum = L2 rollups). PORTS = Perpetual
> Overnight Rate Treasury Securities (Duffie 2025). CBDC = Central
> Bank Digital Currency. BVAL = Bloomberg Valuation Service.

---

## Section 1 — What Cato is, architecturally

Cato is a **Node.js MCP server** (single file `index.js`, ~1,200 LOC,
two dependencies: `@modelcontextprotocol/sdk` and `axios`) that exposes
23 tools over the stdio MCP transport. The tools are read-only
fetchers + composers — they call free public APIs (NY Fed, FRED,
TreasuryDirect, OFR, SEC EDGAR, Blockscout for EVM chains, Solana
public RPC, CoinGecko) and return structured JSON. No state is
persisted except a process-memory sticky price cache
(`_lastLivePrices`) introduced in v0.2.3.

In the **Aureon architecture**, Cato sits at **Verana L0** — the
governance data layer. Verana L0 is the doctrine gate; Cato is what
the gate consumes. The call path per README is:

```
Aureon → Verana L0 → Cato → [NY Fed | FRED | TreasuryDirect | OFR | Blockscout]
```

The server has a **Python twin** (`aureon/mcp/cato_client.py`,
referenced in index.js line 73 but not in this repo). Per a comment
on line 72-76, the **parity principle** is a hard rule: thresholds
must be identical across the Node MCP server and the Python twin so
the gate produces the same decision regardless of caller. That is an
important audit property — one doctrine, two implementations, no
drift.

The business purpose stated in Cato's own doctrine (README line 11-13,
`index.js` header): produce a real-time **PROCEED / HOLD / ESCALATE**
decision before any tokenized settlement proceeds on any rail. The
tool that produces that decision is `get_atomic_settlement_gate`. The
tool that produces the richer pre-trade DSOR context package is
`cato_gate` (renamed from `get_ficc_context`).

Cato is **chain-agnostic by design** (README line 81). The rail
lineup is Ethereum L1 / Base L2 / Arbitrum L2 / Solana / FICC
traditional / Fed L1 (placeholder). The README is explicit that "the
gate, not the rail, is the product" — when Fed L1 / PORTS arrives,
Cato routes there. Doctrine stays; rail changes.

---

## Section 2 — The 23 tools, grouped by function

### NY Fed (4)
| Tool | Function |
| --- | --- |
| `get_sofr` | SOFR daily rate history from NY Fed `markets.newyorkfed.org/api/rates/sofr` |
| `get_repo_reference_rates` | SOFR + BGCR (Broad General Collateral Rate) + TGCR (Tri-party General Collateral Rate) |
| `get_effr` | Effective Federal Funds Rate daily history |
| `get_repo_operations` | Fed open-market repo and reverse-repo operations (daily liquidity posture) |

### Treasury Yield Curve (4)
| Tool | Function |
| --- | --- |
| `get_treasury_yield_curve` | Full CMT (Constant Maturity Treasury) curve 1m → 30y, any tenor or all |
| `get_tips_yields` | TIPS real yields + breakeven inflation (5y, 10y, 20y, 30y) |
| `get_treasury_auctions` | Auction results: bid-to-cover, high yield, indirect bidder % |
| `get_yield_curve_spread` | 2y10y, 3m10y, 5y30y spreads in basis points |

### Macro Regime (3)
| Tool | Function |
| --- | --- |
| `get_macro_regime_snapshot` | FEDFUNDS + SOFR + 10y + 2y + 3m + CPI + UNRATE in one call (Neptune Spear context) |
| `get_cpi` | Headline CPI (CPIAUCSL) and core CPI (CPILFESL), months of history |
| `get_fed_balance_sheet` | WALCL total assets, TREAST Treasury holdings, MBST MBS holdings, WRESBAL reserves |

### OFR / Money Markets (2)
| Tool | Function |
| --- | --- |
| `get_ofr_stress_index` | STLFSI4 St. Louis Fed Financial Stress Index (described as "OFR" in doctrine, sourced from FRED) |
| `get_money_market_rates` | Commercial paper rates: DCPN3M, DCPF3M, DCPN30 |

### Repo Market (2)
| Tool | Function |
| --- | --- |
| `get_repo_market_context` | SOFR + term SOFR + reverse repo facility usage |
| `get_term_sofr` | CME Term SOFR 1m/3m/6m/12m (FRED SOFR1/3/6/12) |

### SEC EDGAR (2)
| Tool | Function |
| --- | --- |
| `get_recent_13f_filers` | Recent 13F-HR institutional holdings filings by date range |
| `get_company_filings` | Company-specific filings (10-K / 10-Q / 8-K / 13F-HR) by CIK |

### Tokenized Settlement — Multi-Chain Router (5)
| Tool | Function |
| --- | --- |
| `get_onchain_prices` | Live ETH + SOL USD prices from CoinGecko (sticky cache / static fallback) |
| `get_multichain_gas` | Parallel per-chain state: Ethereum + Base + Arbitrum via Blockscout, Solana via public RPC, plus `fed_l1` placeholder |
| `get_tokenized_settlement_context` | `settlement_posture` ∈ {favorable, monitor, elevated} from ETH gas + SOFR + OFR FSI |
| `compare_settlement_rails` | All-in USD cost across all 5 rails + ranked table + `recommended_rail` (requires `notional_usd`) |
| `get_atomic_settlement_gate` | **The gate.** PROCEED / HOLD / ESCALATE + `recommended_chain` + thresholds + Solana and Fed-L1 notes |

### Governance (1)
| Tool | Function |
| --- | --- |
| `cato_gate` | Consolidated DSOR context package: rates, spreads, OFR stress, fed liquidity, multi-chain state, `recommended_chain`, live prices. Single call Verana L0 makes pre-trade |

**Count:** 4 + 4 + 3 + 2 + 2 + 2 + 5 + 1 = **23** ✓

---

## Section 3 — Doctrine thresholds and what each one governs

Cato defines **four load-bearing thresholds** as top-level constants
(`index.js` lines 77-80). Per the parity principle comment, these are
the identical values in the Python twin `aureon/mcp/cato_client.py`.

| Constant | Value | What it governs | Triggered behavior |
| --- | ---: | --- | --- |
| `CATO_OFR_ESCALATE_THRESHOLD` | **1.0** | Systemic stress — OFR FSI above average by more than 1 standard deviation territory | `gate_decision = "ESCALATE"`, `recommended_rail = "human_authority"`. Kicks the decision *out* of Cato's autonomy back to a human. Overrides everything else. |
| `CATO_OFR_HOLD_THRESHOLD` | **0.5** | Above-average stress — tradeable but elevated | `gate_decision = "HOLD"`, `recommended_rail = "traditional"`. Forces the trade to FICC traditional rail; atomic-on-chain rails are closed. |
| `CATO_GAS_GWEI_HOLD_THRESHOLD` | **50.0** | Ethereum L1 fee spike — atomic settlement too expensive to be economic | `gate_decision = "HOLD"`, falls back to FICC traditional. Atomic rails on EVM are closed. |
| `CATO_SOFR_DELTA_HOLD_BPS` | **10.0** | **Funding-market shock detector.** 1-day absolute change in SOFR exceeding 10 bps. | `gate_decision = "HOLD"`, falls back to FICC traditional. Restored in v0.2.2 after `cato_backtest.py` revealed the September 2019 repo spike would have passed the other gates unchecked. |

**Relationship between the four:** they are **additive** in the HOLD
tier (any single breach flips the decision to HOLD) and the OFR
threshold at 1.0 is the **only** gate that can reach ESCALATE.
Looking at the handler in `get_atomic_settlement_gate` (lines
1108-1133): ESCALATE is evaluated first and exclusively; if not
ESCALATE, each of OFR 0.5 / gas 50 / SOFR delta 10 bps is an
independent HOLD trigger; if none triggers, PROCEED.

**Implicit thresholds in the routing layer (not in the constants
block, worth noting):**

| Implicit threshold | Location | Governs |
| --- | --- | --- |
| `notional_usd > $10,000,000 AND eth_gas < 30` | `compare_settlement_rails` line 1025 | Large-notional bias: gas is noise at $10M+, route to Ethereum L1 |
| `solana_fee_usd < $0.01` | line 1027, 1141 | Solana economic bound for "ultra-low cost for any size" |
| `base_gas < 1 gwei` | line 1029, 1143 | Base L2 default when its fee is truly L2-cheap |
| `eth_gas < 30 gwei` | settlement posture "monitor" upper | Favorable on-chain |
| `eth_gas 30..50 gwei` | settlement posture "monitor" band | Still viable but watch |

**The recommended-chain logic inside `cato_gate` (lines 830-834)
merits a reader flag:** the guard reads
`ofrVal <= 1.0 && (eth_gas === null || eth_gas <= 50) && ofrVal <= 0.5`.
The `ofrVal <= 1.0` predicate is made redundant by the later
`ofrVal <= 0.5` in the same conjunction. Harmless — equivalent to
just `ofrVal <= 0.5` — but worth tidying when it next gets touched.

---

## Section 4 — Relationship between Cato and Sam's tokenized MMF work

**Sam's tokenized MMF build is the on-chain execution layer. Cato is
the macro layer that decides whether execution should happen at all.**
They sit on opposite sides of the gate:

```
                    Cato (this doctrine)                     Sam's work
                   ─────────────────────                 ──────────────────────
  Verana L0 → PROCEED / HOLD / ESCALATE     →      builds/tokenized_mmf_xrpl_leg/
              (is the macro regime safe?)           (atomic DvP on XRPL testnet)
              (which rail?)                         (resting OfferCreate +
              (cash or stress conditions)            cross-currency Payment)
```

Concretely: if Cato returns `gate_decision = "PROCEED"` and
`recommended_chain = "xrpl"` — which it does not today, because XRPL
is not in the Cato rail lineup — Sam's `dvp_swap.py` is the script
that would run next.

### Where Sam's Q1 CashIssuer pattern maps to a gap in Cato

Sam's `dvp_design.md` Section 6 Q1 asked whether to use XRP (the
native asset) or a synthetic USD IOU from a distinct `CashIssuer`
actor. Sam chose the synthetic IOU and wrote: *"This stands in for
any of: USDC on XRPL, a tokenized bank deposit, or a wholesale CBDC.
The simulation does not need to distinguish between them."* The
institutional boundary preserved was: **the cash leg has an issuer
separate from the ledger; that issuer has its own counterparty risk.**

**Cato currently collapses this dimension.** Its model of a settlement
event is a pair `{rail, cost}`. It does not ask — anywhere — *whose
tokenized cash is on that rail*. Scanning the 23 tools: `get_onchain_prices`
returns ETH and SOL spot (the chains' native assets, not the cash
instruments settled on them); `compare_settlement_rails` computes
per-rail cost; `get_atomic_settlement_gate` returns a `recommended_chain`.
No tool returns a `recommended_cash_instrument` or exposes an
`issuer_health` axis.

The operational gap this creates is not hypothetical. In **March 2023
(Silicon Valley Bank collapse)**, USDC depegged to approximately
$0.88 for roughly 36 hours because Circle disclosed ~$3.3B in reserves
held at SVB. In Cato's current model, that day would likely have shown:

- OFR FSI elevated but probably not above 1.0 for an instant ESCALATE
  (the crisis was compartmentalized to the tokenized-USD issuer, not
  full-system stress);
- Ethereum gas within normal range;
- SOFR delta within normal range;
- Cato's verdict: **PROCEED**, `recommended_chain = "ethereum"` or
  `"solana"`, settle via USDC.

A cash leg in depegged USDC that day would have delivered ~88 cents
of value for every dollar of notional. The on-chain mechanics would
have been perfect — atomic, immediate finality, audit-trail complete
— and the principal risk at settlement would have been realized in
the cash instrument, entirely outside Cato's sensor array.

**What the gap concretely looks like:** Cato lacks a `cash_instrument`
dimension analogous to Sam's `CashIssuer`. It would need (at minimum):

1. A set of cash-instrument identifiers (`usdc`, `usdt`, `tokenized_deposit_jpm`,
   `fed_reserves_l1_pending`, `xrpl_usd_iou_circle`, …).
2. Per-instrument health signals: peg deviation (live), attestation freshness,
   issuer reserve composition signals (where disclosed), Chainlink Proof-of-Reserve
   feeds where available.
3. Doctrine thresholds analogous to the existing four: e.g.
   `CATO_PEG_DEVIATION_HOLD_BPS`, `CATO_ATTESTATION_STALENESS_HOLD_HOURS`.
4. A `recommended_cash_instrument` field alongside `recommended_chain`
   in the gate response.

Sam's CashIssuer abstraction surfaces this dimension naturally because
XRPL's ledger model forces it — every IOU *has* an issuer address
recorded on every trust line. EVM chains hide this behind ERC-20
contract semantics, and Cato's rail-centric model inherits that
blindness. **The tokenized MMF build has been doing, on a single
ledger, the modeling discipline Cato needs at the governance layer.**

---

## Section 5 — Three honest observations on where Cato could tighten

### Observation 1 — Unsourced thresholds

Of Cato's four doctrine thresholds, only **one** has an explicit
validation trail:

- `CATO_SOFR_DELTA_HOLD_BPS = 10.0` — commented on lines 76-78 as
  restored in v0.2.2 after `cato_backtest.py` revealed the September
  2019 repo spike gap. That is a **calibrated, historically-validated**
  threshold. Defensible in audit.

The other three thresholds — `CATO_OFR_ESCALATE_THRESHOLD = 1.0`,
`CATO_OFR_HOLD_THRESHOLD = 0.5`, and `CATO_GAS_GWEI_HOLD_THRESHOLD = 50.0`
— appear with descriptive labels but no sourcing. The STLFSI4 is a
standardized z-score-like series so 0.0 / 0.5 / 1.0 have reasonable
statistical interpretations (mean / ~half-sigma / ~one-sigma above
average), but that rationale is nowhere in the code and nowhere in
the README. The 50 gwei gas threshold has no stated rationale at all
— it is a round number.

**Tightening path:** give each threshold the SOFR-delta treatment.
A `cato_calibration.md` or equivalent that, per threshold: (a) cites
the statistical or historical basis; (b) names the events the
threshold is tuned against (Sept 2019 SOFR spike, March 2020 gas
spike, March 2023 SVB/USDC event, etc.); (c) shows the backtest pass
rate. Parity with SOFR delta. Same discipline across the whole gate.

### Observation 2 — Asymmetric traditional-vs-atomic detail

The atomic-rail side of Cato is modeled in **live, per-chain,
observation-rich** detail:

- Four chains fetched in parallel (Ethereum, Base, Arbitrum, Solana);
- Per-chain gas / priority fees / block time / network utilization /
  coin price;
- Three-state price fallback (fresh / stale-sticky / static cold-boot);
- Solana-specific JSON-RPC call for median prioritization fee;
- Per-rail status in `{live, unavailable, placeholder, not_yet_issued}`;
- Institutional disclosure that CoinGecko should be replaced by a
  licensed feed.

The **FICC traditional** rail is modeled as a **single closed-form
cost formula** (`ficcCost`, lines 315-321):

```
clearing = notional × 0.00005 × (1 - 0.40) × (term_days / 360)
coc      = notional × (sofr_pct / 100) × (term_days / 360)
cost     = clearing + coc
```

Four parameters, two of them hardcoded constants. No observational
inputs. No stress-conditional adjustments. No modeling of:

- **The T+1 settlement window itself as risk.** Which is, structurally,
  the whole reason DvP exists. FICC traditional's cost curve treats
  T+1 as a duration for cost-of-capital; the principal-at-risk during
  the window doesn't appear as a risk premium anywhere.
- **FICC margin and intraday liquidity calls.** Real clearing cost
  includes VaR-based initial margin and variation margin calls,
  neither of which is represented.
- **Netting benefit variance by portfolio.** The 40% netting benefit
  is a fleet average; an individual member's actual benefit varies
  substantially.
- **Term-matched cost of capital.** `ficcCost` uses overnight SOFR for
  any `term_days`; a 30-day repo should use 1m term SOFR.

The practical consequence: when `compare_settlement_rails` produces a
ranked table, the atomic rails are scored with live telemetry and the
FICC rail is scored with a smooth synthetic curve. Any comparison
inherits that asymmetry. **The comparison quietly biases toward
atomic** — not because atomic isn't genuinely competitive (it often
is), but because the measurement apparatus on the two sides is not
matched. For institutional audit, either add depth to the FICC model
(NSCC public filings have margin methodology; a few parameters go a
long way) or caveat the asymmetry explicitly in the tool output.

### Observation 3 — Notional-unaware gate recommendations disagree with the rail comparator

The three tools that return a recommended rail/chain use **different
logic** and do not converge:

| Tool | Takes notional? | Large-notional routing? | Recommended output |
| --- | --- | --- | --- |
| `get_atomic_settlement_gate` | No | **No** | `recommended_chain` purely by fee thresholds (solana < $0.01, base < 1 gwei, else ethereum) |
| `cato_gate` | No | **No** | Same reduced logic as above |
| `compare_settlement_rails` | Yes (required) | **Yes** — `notional > $10M AND eth_gas < 30 → ethereum_l1` | `recommended_rail` with notional-aware override |

This means on the same market state (gas calm, Solana cheap, stress
low, notional = $50M), the governance gate recommends **Solana**
(cheapest per fee) while the rail comparator recommends **Ethereum L1**
(large notional, gas is noise). A Verana L0 consumer that queries
both gets two different answers to the same question.

The README's stated "Routing Doctrine v0.2.0" (lines 85-92) is the
*comparator's* logic. The *gate*'s logic is a proper subset of it.
The gate does not see notional, so it cannot implement the large-
notional branch. Which is fair at the API level — but then the gate
is quietly recommending a *suboptimal* chain for institutional-size
trades, while claiming the authoritative governance voice.

**Tightening path:** either (a) require `notional_usd` at the gate
and converge the two implementations, or (b) have the gate return
"chain recommendation requires notional; call `compare_settlement_rails`"
for the recommendation axis while keeping PROCEED / HOLD / ESCALATE
notional-independent. Option (b) is honest about what the data
supports; option (a) is richer but expands the gate's input surface.

---

## What this note does NOT do

- Does not critique Cato's architectural choice of Node.js (it is
  what the MCP server ecosystem expects; the parity with the Python
  twin handles Sam's language constraint).
- Does not suggest rewriting any threshold values. The three
  un-sourced thresholds could still be *correct*; the observation is
  that the sourcing is missing, not the value.
- Does not benchmark Cato's live behavior against mainnet — Cato is
  a governance surface, not an executor, and nothing Sam has run
  touches it yet.
- Does not propose XRPL inclusion as a rail. That is a scope
  decision Sam and the operator can revisit as a follow-up; it is
  implied by the tokenized-MMF work but not yet asked for.

## Follow-up candidates (for operator decision)

1. **Add a `cash_instrument` dimension to Cato** — closes the Q1
   CashIssuer gap; biggest institutional-risk reduction per line of
   code.
2. **Source the three unsourced thresholds** via a `cato_calibration.md`
   artifact following the SOFR-delta template.
3. **Deepen the FICC cost model** or caveat the asymmetry in the
   comparator output.
4. **Reconcile the three "recommended rail/chain" implementations** —
   pick one routing logic, apply it everywhere, or make the gate
   notional-aware.
5. **Add XRPL as a rail** — Sam's XRPL leg + DvP build are the natural
   executor for a `recommended_chain = "xrpl"` verdict; the XRPL DEX
   primitive (Sam's `dvp_swap.py`) is arguably the closest thing to
   *native-primitive atomic DvP* in Cato's rail lineup.
