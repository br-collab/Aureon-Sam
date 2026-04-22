# DvP Cash Leg — Design Doc

> **Status note (2026-04-18):** the architecture below is already
> implemented as `dvp_swap.py`, with happy-path and negative-test runs
> verified against XRPL testnet (`run_dvp_20260418_230722.json`,
> `run_dvp_negative_20260418_231646.json`). This doc replaces the
> earlier lighter version of `dvp_design.md` with the rigorous 6-section
> framing the operator requested. It documents the decisions, the live
> ledger corrections, and what the build can and cannot claim.

> **Acronyms used throughout:** DvP = Delivery-versus-Payment. PvP =
> Payment-versus-Payment. FMI = Financial Market Infrastructure. CSD =
> Central Securities Depository. CCP = Central Counterparty. DTCC =
> Depository Trust & Clearing Corporation. NSCC = National Securities
> Clearing Corporation. MMF = Money Market Fund. NAV = Net Asset Value.
> HTLC = Hash Time Lock Contract. AMM = Automated Market Maker. IOU =
> I-Owe-You (an issued asset on XRPL). DEX = Decentralized Exchange.
> HITL = Human-In-The-Loop. KYC = Know-Your-Customer. FoK = Fill-or-Kill.
> IOC = Immediate-or-Cancel. XLS-nn = XRPL Standards (amendment specs).

---

## Section 1 — The DvP problem, stated precisely

### What institutional DvP means
Delivery-versus-Payment is the principle that a securities transfer and
its corresponding cash payment must be linked such that **one cannot
occur without the other**. BIS-CPMI defines three DvP models by how the
two legs are settled: gross/gross (Model 1), gross-securities /
net-cash (Model 2), and net/net (Model 3). All three exist to solve
the same problem: **principal risk at settlement** — the risk that one
party delivers and the counterparty fails to pay, or vice versa.

The canonical lesson is **Herstatt risk**, named after Bankhaus
Herstatt's collapse in June 1974. Its counterparties had already paid
Deutschmarks into Herstatt expecting same-day dollar delivery in New
York. Herstatt was closed by regulators in the intervening hours. The
dollars never arrived. The principal was unrecoverable. That single
event shaped every settlement system built since — CHIPS, CLS, DTCC,
TARGET2 — all of which exist in large part to close temporal windows
between legs.

### Why the gap between legs is the core settlement risk
Classical settlement is not atomic. A securities transfer and its cash
countermove are choreographed by:
- **Institutional intermediaries** holding both legs until matched
  (DTCC/NSCC for US equities; CSDs for European securities; CLS for FX).
- **Cutoffs and windows** (NAV strike at 4:00pm ET for MMFs; Fedwire
  close at 6:00pm ET; CHIPS/CLS cutoffs for FX).
- **Contractual obligations and legal recourse** if one leg fails.

The residual risk sits in the **gap** — the period between the
securities transfer and the cash transfer where one party has a claim
without the counter-asset. Even "same-day" settlement usually means
"same-day by convention, sequential in reality." The parent simulation
in `builds/tokenized_mmf_settlement/` models this gap explicitly: in
T+1 settlement the custodian/TA pair bridges roughly 26 hours of
exposure between trade capture and settled-share delivery.

### What "atomic" means on-chain vs TradFi
In TradFi, "DvP" means *institutionally choreographed simultaneity* —
two legs that occur within the same settlement batch, guaranteed by a
trusted FMI that holds both sides until matched. Atomicity is
*contractual and operational*, not *protocol-enforced*.

On a distributed ledger, "atomic" means a stronger thing: the two
asset transfers are **indivisible at the protocol level**. They are
wrapped inside a single ledger state transition. The ledger either
applies both or neither. There is no intermediate state where one leg
has moved and the other hasn't, because the transaction has not been
written until both movements are recorded in the same closed ledger.

This is a qualitative difference. It eliminates the gap, not by
shortening it, but by **refusing to produce a state in which one leg
has moved without the other**. The custodian's traditional role of
"holding both sides until matched" is absorbed into the protocol.

**What atomic does NOT mean on-chain:**
- It does not mean "fast." A slow atomic settlement is still atomic.
- It does not mean "cheap." Gas/fees exist. The claim is about
  indivisibility, not cost.
- It does not eliminate risk. It replaces settlement risk with
  smart-contract risk, oracle risk, key-management risk, chain-liveness
  risk, and stablecoin-issuer risk. A real institutional assessment
  trades one risk matrix for another, it does not zero the matrix out.

### Implication for this build
The tokenized MMF story is incomplete without the cash leg. A
tokenized share delivery with a T+1 wire on the cash side is not DvP
— it is *partial tokenization*, and still carries the Herstatt-style
gap. To close the loop, both legs must move in a single ledger state
transition. That is the claim this build exists to make.

---

## Section 2 — XRPL mechanisms available

Six primitives are reasonable candidates. Four are seriously
considered; two are dismissed with reasons.

### 2.1 Native Escrow (`EscrowCreate` / `EscrowFinish` / `EscrowCancel`)
**What it is.** XRPL's on-ledger escrow mechanism. An account locks
funds (XRP, and issued tokens via the TokenEscrow amendment XLS-40)
under conditions that release them when met or cancel them when not.

**How it works.** `EscrowCreate` takes a destination, an optional
`FinishAfter` time, an optional `CancelAfter` time, and an optional
`Condition` (a PREIMAGE-SHA-256 crypto-condition, RFC 3712/5). The
destination (or any account with the preimage) submits `EscrowFinish`
with the fulfillment to release. If the cancel time passes and no
finish has been submitted, anyone can submit `EscrowCancel` to return
funds to the source.

**Atomic-swap pattern (HTLC).** Classic cross-chain DvP: two escrows,
one per leg, both locked by `SHA-256(preimage)` with differing
timeouts. Alice's escrow (shares) sits longer; Bob's escrow (cash)
expires sooner. When Alice submits the preimage to claim Bob's cash,
the preimage is now visible on-chain. Bob uses it to claim Alice's
shares. Timeouts + refund paths defend the adversarial cases.

**Tradeoffs.**
- *Pro:* The right tool for **cross-chain** DvP (XRPL ↔ Ethereum,
  XRPL ↔ Bitcoin via Lightning). No single ledger can enforce
  atomicity across chains; hashlocks are the canonical workaround.
- *Pro:* Works without the DEX and without an order book.
- *Con:* Atomicity is **economic, not transactional**. Two ledger txs,
  one preimage reveal, a timeout window. There exists a narrow window
  where one party has claimed and the other hasn't yet. Safe under
  honest operation; defended but not eliminated under adversarial play.
- *Con:* Complexity. Crypto-condition encoding, preimage management,
  refund paths, clock skew assumptions.
- *Con:* XLS-40 (TokenEscrow) amendment activation must be verified on
  the specific network before issued-asset escrows work.

### 2.2 Cross-currency `Payment` with DEX pathfinding
**What it is.** XRPL's `Payment` transaction type generalizes beyond
"move currency X from A to B." When source currency and destination
currency differ, the ledger consults the on-ledger DEX order book and
routes the exchange through available offers, matching them as part
of the Payment's execution.

**How it works.** Fields that matter:
- `Amount`: what the destination receives (e.g., 1M MMF IOU).
- `SendMax`: the upper bound the source will pay (e.g., 1M USD IOU).
- `Paths` (optional): explicit path hints; if omitted, the server
  auto-discovers.
- Flags:
  - `tfLimitQuality`: only consume offers with exchange rate at or
    better than `Amount / SendMax`. If no such path exists, fail.
  - `tfPartialPayment`: allow partial execution. **Omitted** in DvP
    — we want all-or-nothing.

**Atomicity property.** The entire exchange — source debit,
intermediate offer consumption, destination credit — happens inside
*one transaction*, inside *one closed ledger*. Either every affected
trust-line balance moves, or none do. If the rate has moved, the path
is dry, or liquidity is insufficient, the tx fails with
`tecPATH_DRY` or `tecPATH_PARTIAL` and no balance changes.

**Tradeoffs.**
- *Pro:* True single-tx atomicity at the protocol level. No two-phase
  commit, no shared secret, no timeout math.
- *Pro:* Native primitive, no amendment dependency.
- *Pro:* Maps cleanly onto the institutional mental model of "a
  subscription is an exchange of cash for shares at NAV."
- *Con:* Requires liquidity on the DEX — either an existing offer or
  a rippling path. For primary issuance, someone has to have posted
  the issuer's offer first.
- *Con:* The offer is publicly visible on the order book between
  creation and consumption. On mainnet, that's a front-running surface.
  On testnet with fresh wallets and no MEV bots, effectively zero.

### 2.3 `OfferCreate` (DEX limit orders) + consuming `Payment`
**What it is.** The maker half of the DEX flow. An account posts a
limit order to the on-ledger order book specifying `TakerPays` (what
the taker pays = what the maker receives) and `TakerGets` (what the
taker gets = what the maker gives up).

**How it works.** `OfferCreate` flags shape behavior:
- No flag (default): **resting offer**. Sits on the book until taken
  or explicitly cancelled.
- `tfPassive`: don't cross existing offers at the same or better rate.
- `tfImmediateOrCancel` (IOC): consume existing book liquidity
  immediately; kill the remainder if any.
- `tfFillOrKill` (FoK): consume existing book liquidity completely or
  kill the entire offer.
- `tfSell`: exchange the entire `TakerGets` amount even at a higher
  rate than requested (sell-side priority).

**Critical clarification learned from live ledger (2026-04-18):** FoK
and IOC are **taker** flags. They describe how the newly-created
offer consumes *existing* liquidity on the book. A maker posting
**new** liquidity with FoK in an empty book gets `tecKILLED` — there
is nothing to consume. For primary issuance (where the issuer *is*
the liquidity), the correct primitive is a **resting offer** (no FoK,
no IOC), consumed moments later by a counterparty's Payment or Offer.

**Atomicity property.** Lives on the *consuming* side, not the
maker's offer. The Payment that consumes the resting offer is the
atomic transaction; the offer itself is merely available book state.

**Tradeoffs.**
- *Pro:* Models institutional issuance naturally — "issuer posts
  subscription offer at NAV, investor takes it."
- *Pro:* Deterministic per-trade rate when combined with
  `tfLimitQuality` on the Payment.
- *Con:* Two-transaction window between offer post and consumption.
  On mainnet, a front-runner could theoretically take the offer
  before the intended investor. Mitigations: tight inter-tx window,
  `tfLimitQuality` rate guard, authorized-only trust lines, or move
  to Batch (XLS-56) when activated.

### 2.4 Batch (XLS-56)
**What it is.** An amendment that wraps multiple inner transactions
into a single atomic bundle. If any inner tx fails, the entire batch
reverts.

**Tradeoffs.**
- *Pro:* The ideal primitive for this use case. Offer+Payment
  collapse into one atomic event, closing the inter-tx window
  entirely. Eliminates the last residual timing concern in 2.3.
- *Con:* Amendment activation status is a prerequisite. At time of
  writing this doc (2026-04-18), Batch is not a baseline v1-toolchain
  dependency we should lean on.
- *Disposition:* defer until amendment is activated on the target
  network; revisit as a cleanup.

### 2.5 AMM (Automated Market Maker) — dismissed for this build
**What it is.** XRPL native AMMs. Liquidity providers deposit asset
pairs into a pool; traders swap against the pool at a curve-determined
price with slippage and (optionally) impermanent-loss exposure.

**Why not.** AMMs are designed for **secondary-market liquidity**
under continuous demand. Primary issuance of MMF shares at NAV does
not need a curve, has no slippage tolerance, and has no liquidity-
provision use case. Wrong tool for the job.

### 2.6 Payment Channels — dismissed for this build
**What it is.** Unidirectional streaming micropayments between two
parties, settled periodically on-chain.

**Why not.** Designed for high-frequency unidirectional payments
(content, APIs). Not a swap primitive. Cannot express DvP atomicity.

---

## Section 3 — Recommended architecture

### Selection: resting `OfferCreate` + cross-currency `Payment` with `SendMax` + `tfLimitQuality`

### Why this over alternatives

| Alternative                       | Why not for this build                                    |
|-----------------------------------|-----------------------------------------------------------|
| HTLC via TokenEscrow (2.1)        | Right tool for **cross-chain**; over-engineered on one ledger. 2 txs, preimage, timeouts, XLS-40 dependency. No benefit over native DEX atomicity for same-ledger DvP. |
| Batch (XLS-56, 2.4)               | Would be strictly better. Defer until amendment activated on target network. |
| AMM (2.5)                         | Wrong tool — secondary liquidity, not primary issuance.   |
| Payment Channels (2.6)            | Not a swap primitive. Cannot express DvP atomicity.       |
| `OfferCreate` with FoK            | FoK is a *taker* flag; a maker posting new liquidity with FoK in an empty book gets `tecKILLED`. Confirmed on live ledger. Not applicable. |

### Mechanism in one sentence
A third-party `CashIssuer` issues a synthetic USD IOU to the
investor. `ShareIssuer` posts a resting `OfferCreate` exchanging 1M
MMF shares for 1M of the `CashIssuer`'s USD. The investor submits a
self-directed cross-currency `Payment` with `Amount = 1M MMF`,
`SendMax = 1M USD(CashIssuer)`, and `tfLimitQuality`. The ledger
validates the consuming Payment in one closed ledger: cash leaves the
investor and shares arrive, or the Payment fails and nothing moves.

### Actors and asset structure
```
+------------------+        USD IOU         +------------------+
|   CashIssuer     | ---------------------> |    Investor      |
| (tokenized cash) |   (setup: pre-fund)    | (ACME Family Off)|
+------------------+                        +------------------+
         ^                                         |
         |                                         | submits
         | USD (via DvP swap                       | cross-currency
         |  consuming Offer)                       | Payment with
         |                                         | SendMax +
         |                                         | tfLimitQuality
         |                                         v
+------------------+                        +------------------+
|   ShareIssuer    |        MMF IOU         |     XRPL DEX     |
| (Prime MMF Cls I)| <--------------------- | (matches Offer   |
|                  |  (DvP swap, atomic)    |  in one ledger)  |
+------------------+                        +------------------+
         |                                         ^
         |  posts resting OfferCreate:             |
         +-----------------------------------------+
            TakerPays = 1M USD(CashIssuer)
            TakerGets = 1M MMF(ShareIssuer)
```

### Cash-leg asset choice
**Synthetic USD IOU issued by a distinct `CashIssuer` account.** This
stands in for any of: USDC on XRPL, a tokenized bank deposit, or a
wholesale CBDC (central bank digital currency). The simulation does
not need to distinguish between them. The critical property is that
the cash leg is a fungible, ledger-native issued asset held on a
trust line — which is what all three of those real-world instruments
are or would be on XRPL.

**Why not XRP as a placeholder:** XRP would technically work, but it
hides the critical institutional boundary. Real tokenized-cash
instruments are issued by someone (Circle, a bank, a central bank);
using XRP conflates that issuer accountability with the ledger's
native asset. Keep `CashIssuer` as a distinct actor for fidelity.

### Exact XRPL transaction sequence

**Setup (once per actor-pair in production; fresh each run in v1):**

| #  | Signer        | Tx type       | Purpose                                                          |
|----|---------------|---------------|------------------------------------------------------------------|
| 1  | —             | Faucet        | Fund `ShareIssuer`                                               |
| 2  | —             | Faucet        | Fund `CashIssuer`                                                |
| 3  | —             | Faucet        | Fund `Investor`                                                  |
| 4  | `ShareIssuer` | `AccountSet`  | Enable `asfDefaultRipple` so MMF balances can route              |
| 5  | `CashIssuer`  | `AccountSet`  | Enable `asfDefaultRipple` so USD balances can route              |
| 6  | `ShareIssuer` | `TrustSet`    | Open USD trust line to `CashIssuer` (receive cash leg)           |
| 7  | `Investor`    | `TrustSet`    | Open MMF trust line to `ShareIssuer`                             |
| 8  | `Investor`    | `TrustSet`    | Open USD trust line to `CashIssuer`                              |
| 9  | `CashIssuer`  | `Payment`     | Issue 1M USD to `Investor` (pre-fund the cash position)          |

**HITL gate:** operator approves. Keystroke + UTC timestamp recorded
to artifact. Anything other than `approve` aborts without submitting
the atomic event.

**Atomic DvP:**

| #  | Signer        | Tx type       | Purpose                                                                                 |
|----|---------------|---------------|-----------------------------------------------------------------------------------------|
| 10 | `ShareIssuer` | `OfferCreate` | **Resting offer** (no FoK, no IOC). `TakerPays = 1M USD(CashIssuer)`, `TakerGets = 1M MMF(ShareIssuer)` |
| 11 | `Investor`    | `Payment`     | Self-Payment. `Amount = 1M MMF(ShareIssuer)`, `SendMax = 1M USD(CashIssuer)`, `tfLimitQuality`. Consumes offer #10 in a single validated ledger |

**Verification:**

| #  | Request         | Purpose                                                     |
|----|-----------------|-------------------------------------------------------------|
| 12 | `account_lines` | Confirm `Investor` holds 1M MMF and 0 USD                   |
| 13 | `account_lines` | Confirm `ShareIssuer` holds 1M USD                          |
| 14 | `account_lines` | Confirm `CashIssuer`-side reflects the drained investor line |

### The atomic moment
Step #11 is the DvP event. That single `Payment` transaction is where
atomicity lives. The ledger validates it as an indivisible unit: cash
debit from investor, offer consumption, offer's TakerPays routed to
ShareIssuer, offer's TakerGets credited to investor — all or nothing.

The negative-test mode skips step #10 (no offer on the book) and
submits step #11 anyway. The ledger returns `tecPATH_PARTIAL` and no
balances move. That is the institutional claim this build exists to
make verifiable.

---

## Section 4 — What we keep from Lane B

The DvP build is an **extension** of `issue_shares.py`, not a
replacement. Concretely:

**Preserved file:** `builds/tokenized_mmf_xrpl_leg/issue_shares.py`
stays in place as the simpler teaching artifact — single issuer,
single leg, the minimum reproducible tokenized-issuance example. New
readers encounter it first; DvP is the graduation exercise.

**Preserved doctrine:**
- **Python-only for the operator's hands.** The polyglot primitives
  (Solidity, Rust, Move, etc.) remain read-and-explain-only. All
  executable code in this build is Python, using `xrpl-py`.
- **Testnet-only.** Endpoint hardcoded to
  `https://s.altnet.rippletest.net:51234`.
- **Mainnet hard-blocked at startup.** `MAINNET_HOSTS_BLOCK` tuple
  (`xrplcluster.com`, `s1.ripple.com`, `s2.ripple.com`) asserted
  against the endpoint string before any client construction. Same
  pattern ported verbatim from `issue_shares.py`.
- **Faucet-funded ephemeral wallets.** Every run creates fresh
  wallets; seeds are never persisted. Same pattern as Lane B.
- **HITL gate at the pre-atomic step.** Same placement, same
  `input("approve")` primitive. New in the DvP build: the keystroke
  + UTC timestamp are persisted to the artifact, matching the
  operator's directive to record human decisions.
- **Audit-trail JSON.** Every tx hash, ledger index, and ledger
  close time recorded. Filenames are UTC-timestamped and append-only
  (no run overwrites a prior run). Verifiable on `testnet.xrpl.org`.
- **SYNTHETIC banner.** Every artifact and every print starts by
  labeling the data as synthetic, non-production, not a regulated
  financial product.
- **Dependency surface.** Only `xrpl-py` (already pinned in the
  project `.venv` at 4.5.0) plus Python stdlib. No new system
  dependencies introduced.

**Lane B's one-leg claim is also preserved.** Lane B proved the
~12-second finality assumption from the parent simulation survives
contact with a live ledger. The DvP build extends that proof: the
same finality also holds for multi-tx atomic settlement at
approximately one ledger close per transaction.

---

## Section 5 — What this build will prove and what it won't

### What it will prove
1. **Atomic DvP is a native XRPL primitive**, not a pattern
   synthesized on top of simpler primitives. A single `Payment`
   transaction with `SendMax` + `tfLimitQuality` is the atomic
   unit. No smart-contract glue, no HTLC machinery, no two-phase
   commit logic the institution must write or audit.
2. **Real tx hashes on a public ledger.** Every step produces a
   verifiable transaction hash. Any third party with a browser can
   visit `testnet.xrpl.org` and confirm the ledger index, close
   timestamp, and state effects.
3. **Single-ledger settlement is achievable inside finality budgets
   the parent simulation assumed.** Each on-chain transaction closes
   in ~5–9 seconds on XRPL testnet. The full DvP path (setup +
   atomic event) is multi-ledger for operational reasons, but the
   *atomic value-exchange* is one tx in one ledger.
4. **The custodian role transformation claim holds at the cash-leg
   level too.** Cash movement becomes a ledger operation, not a
   Fedwire operation. Custodian shifts to key-management + compliance,
   consistent with the parent simulation's thesis.
5. **Failure mode is deterministic and clean.** The negative-test
   scenario (no offer on the book) produces `tecPATH_PARTIAL` and
   zero state change. The protocol refuses to leave a half-settled
   position. This is the property that matters most to institutional
   audiences — "DvP or nothing" is a ledger guarantee, not a policy.
6. **HITL placement is structurally correct.** The gate lives
   pre-atomic because once the Payment submits, there is no hold —
   the ledger closes and the swap is settled.

### What it will NOT prove
1. **That a synthetic USD IOU from `CashIssuer` is legally equivalent
   to a regulated payment instrument.** Legal wrapping of the cash
   leg — whether it is a tokenized deposit, a stablecoin, or a
   wholesale CBDC — is entirely off-ledger. Real deployment requires
   specific legal structure, licensing, and supervision not modeled
   here.
2. **That the "MMF" share IOU is a 1940-Act registered fund.**
   Tokenization wrappers, issuance vehicles, and applicable
   regulations vary by jurisdiction and product. This build models
   settlement mechanics only.
3. **Mainnet conditions.** Testnet has no meaningful validator
   adversarial activity, no MEV (Maximal Extractable Value) bots, no
   fee pressure, no congestion. Mainnet numbers will differ.
4. **Liquidity claims.** The "1M MMF for 1M USD" trade happens
   against an uncontested book we ourselves populate. This is not
   evidence of real mainnet liquidity.
5. **Redemption, corporate actions, or lifecycle events.** Burns on
   redemption, income distributions, freeze/clawback compliance
   events — none are exercised.
6. **HITL workflow security.** The gate is a `input("approve")`
   placeholder. It is enough to prove the gate *placement* is
   architecturally correct. It is not a real reviewer workflow with
   identity, dual control, or cryptographic signing.
7. **Resilience against adversarial network conditions.** No
   validator partitions, no forks, no amendment-activation edge
   cases modeled.

### Load-bearing assumptions
- XRPL testnet endpoint is reachable and the faucet is funding
  wallets. Script exits cleanly with a clear message if not; never
  falls back to mainnet.
- `asfDefaultRipple` is enabled on both issuers (steps 4 and 5) —
  load-bearing for issued-asset routing between trust lines.
- `ShareIssuer` has a trust line to `CashIssuer`'s USD (step 6) —
  load-bearing for receiving the cash leg in step #11.
- `tfLimitQuality` semantics match the published spec across the
  version of `xrpl-py` in the `.venv` (currently 4.5.0). If the SDK
  changes flag-encoding behavior, re-verify.
- Fresh wallets per run. No persisted-account state across runs
  (simpler audit; each run is independent).
- Three-letter currency codes (`MMF`, `USD`) are fine for v1
  readability. Production would use 40-byte hex codes carrying
  richer identity such as `PRIMEMMF-I-2026`.
- Inter-ledger window between offer post (step #10) and consumption
  (step #11) is ≤1 ledger close (~3–5s) on testnet. Good enough for
  v1; mainnet would need Batch (XLS-56) or an authorized-only trust
  line pattern to close the window entirely.

---

## Section 6 — Open questions for the operator

The build is implemented, so these are **choices made that remain
revisable**. Each has a recommended default and a rationale. Overturn
any of them and the code adapts with small edits.

1. **Cash-leg asset — synthetic USD IOU, or XRP as placeholder?**
   Chosen: synthetic USD IOU from a distinct `CashIssuer` actor.
   *Rationale:* preserves the institutional boundary between the
   ledger's native asset and the tokenized-cash instrument being
   modeled. XRP would work mechanically but would collapse an
   important real-world distinction.
   *Revisit if:* you want a build that exercises XRP-native DvP
   specifically (which has different mechanics — no trust lines,
   different flags).

2. **Fresh wallets every run, or persisted `ShareIssuer`?**
   Chosen: fresh wallets every run.
   *Rationale:* simpler audit surface, no residual state carrying
   between runs, no seed persistence on disk. Burns small amounts
   of testnet faucet XRP per run, which is free.
   *Revisit if:* you want to model a long-lived issuer with
   accumulated history across subscriptions.

3. **HITL gate — `input()` placeholder, or something richer?**
   **OPERATOR OVERRIDE 2026-04-18 — Q3 hardened.** Kept the `input()`
   mechanism, but hardened the artifact schema to capture four fields
   per gate crossing:
   - `reviewer_identity` — hardcoded to `"Guillermo Ravelo"` for v1
     (constant at top of `dvp_swap.py`).
   - `keystroke` — verbatim operator response.
   - `approval_reason` — a one-line free-text prompt presented
     *after* the approval keystroke, captured at decision time.
   - `decided_at_utc` — ISO-8601 timestamp when approval landed.
   Also persisted: `prompted_at_utc`, `approved` (bool), and the
   full `context` string the reviewer saw.
   *Rationale:* proves the gate *placement* is correct and shapes the
   artifact for a real reviewer workflow without building it yet.
   When the reviewer-workflow lane ships, only the gate internals
   change; downstream consumers of the JSON keep working.
   *Revisit if:* you want this build to double as the
   reviewer-workflow proof — at that point replace the `input()` calls
   with signed-keypair approval and record the signature beside the
   other fields.

4. **Negative-test scope — just "no offer posted," or richer
   adversarial scenarios?** Chosen: single negative test (no
   `OfferCreate`, Payment attempted and rejected with
   `tecPATH_PARTIAL`). *Rationale:* proves the headline claim —
   "no offer, no swap, no movement" — cleanly and minimally.
   *Revisit if:* you want to add partial-liquidity (offer smaller
   than Payment), rate-drift (offer posted at worse rate than
   SendMax allows), or offer-cancellation-race scenarios.

5. **Redemption / reverse DvP — include in this build, or separate?**
   Chosen: **separate**, pending operator direction. This build
   exercises subscription (cash → shares) only.
   *Rationale:* keeps each artifact focused on one claim. Redemption
   exercises burn-on-receipt and a symmetric DvP in the opposite
   direction — sufficiently different to warrant its own README
   section and artifact.
   *Revisit if:* you want the lifecycle proven end-to-end in one
   build.

6. **Offer visibility on testnet — accept front-running risk
   disclosure, or address now?**
   **OPERATOR OVERRIDE 2026-04-18 — Q6: both variants now exist.**
   **OPERATOR DECISION 2026-04-21 — Option A cut-over executed.**
   The two postures now live in separate files — one file per claim,
   posture visible in a directory listing rather than a runtime flag:

   - **Open variant — `dvp_swap.py`.** Any holder may open a trust line
     to `ShareIssuer` without issuer approval. Teaches the minimum path
     to atomic DvP on XRPL. Not the mainnet-realistic posture.
   - **Permissioned variant — `dvp_swap_permissioned.py`.** Adds two
     setup transactions that together enforce pre-trade access control:
     1. `AccountSet` with `asfRequireAuth` on `ShareIssuer`, set
        *before* any trust lines exist on that account (XRPL rule).
     2. `TrustSet` with `TF_SET_AUTH` submitted by `ShareIssuer`
        with `LimitAmount.issuer` = the investor's address and
        `value = "0"` — the on-ledger equivalent of a
        post-KYC allowlist admission flipping the `lsfAuth` bit on
        the investor's MMF trust line. Without this step, the DvP
        `Payment` would fail with `tecNO_AUTH`.

   *Delta doc:* `dvp_swap_permissioned_design.md` governs the
   extraction and names what is identical / what differs.

   *Rationale for Option A (one file per posture):*
   - Single-claim files. Each file states one claim and verifies it
     end-to-end. No hidden `if permissioned:` branches a reader must
     trace.
   - Institutional reader path. When asking "how would this actually
     run on mainnet," a reader opens `dvp_swap_permissioned.py`
     directly — no CLI-flag archaeology.
   - Clean migration target. When Batch (XLS-56) activates, the
     permissioned file is where the Offer+Payment bundle goes. Edits
     touch one file, not a cross-cutting branch.
   - Maintenance hygiene. Two codepaths producing the same artifact
     (the flag form) created a "which do I trust" question with no good
     answer.

   *Architectural claim unchanged:* the atomic-DvP mechanics in
   steps 10-11 are byte-identical across both files. Permissioning
   composes cleanly with atomicity — it does not alter the one-ledger
   guarantee, only gates who is authorized to hold the issued asset.
   *Additional mainnet hardening still deferred:* Batch (XLS-56) to
   collapse the inter-ledger window between Offer post and Payment
   consumption entirely, when the amendment activates. Authorization
   closes the "any holder can consume the offer" surface; Batch would
   close the "offer exists between ledgers" surface on top of that.

7. **Artifact retention — one JSON per run (current), or an
   append-only log?** Chosen: one JSON per run, UTC-timestamped
   filename.
   *Rationale:* simpler to diff across runs, simpler to archive,
   each run is self-contained.
   *Revisit if:* you want a single long-lived ledger-of-runs for
   trend analysis across many executions.

---

## Verified runs (reference)

All runs below use the **hardened HITL schema** (Q3 override —
`reviewer_identity` and `approval_reason` captured alongside keystroke
and timestamp). Earlier pre-override artifacts
(`run_dvp_20260418_230722.json`, `run_dvp_negative_20260418_231646.json`)
are retained in-tree but not listed here; they predate the schema.

### Round 1 — 2026-04-18/19 (flag-form, pre-Option A)
Produced by `dvp_swap.py` with and without `--permissioned`.
Retained in-tree for historical completeness.

| Variant       | Mode          | Setup txs | Swap tx result                  | DvP atomic | Artifact                                                  |
|---------------|---------------|----------:|----------------------------------|-----------:|-----------------------------------------------------------|
| Open          | Happy path    | 9         | `tesSUCCESS` (ledger 16656414)   | ✓ True     | `run_dvp_20260419_004152.json`                            |
| Open          | Negative test | 9         | `tecPATH_PARTIAL` (no offer)    | ✓ True     | `run_dvp_negative_20260419_004703.json`                   |
| Permissioned  | Happy path    | 11        | `tesSUCCESS` (ledger 16656361)   | ✓ True     | `run_dvp_permissioned_20260419_003908.json`               |
| Permissioned  | Negative test | 11        | `tecPATH_PARTIAL` (no offer)    | ✓ True     | `run_dvp_permissioned_negative_20260419_004035.json`      |

### Round 2 — 2026-04-21 (split-file form, post-Option A)
Produced by the two separated files after the `--permissioned` flag
was removed from `dvp_swap.py`. Each file now carries one posture and
one claim.

| Variant       | Mode          | File                        | Setup txs | Swap tx result                  | DvP atomic | Artifact                                                 |
|---------------|---------------|-----------------------------|----------:|----------------------------------|-----------:|----------------------------------------------------------|
| Permissioned  | Happy path    | `dvp_swap_permissioned.py`  | 11        | `tesSUCCESS` (ledger 16724494)   | ✓ True     | `run_dvp_permissioned_20260421_114001.json`              |
| Permissioned  | Negative test | `dvp_swap_permissioned.py`  | 11        | `tecPATH_PARTIAL` (no offer)    | ✓ True     | `run_dvp_permissioned_negative_20260421_114129.json`     |
| Open          | Happy path    | `dvp_swap.py`               | 9         | `tesSUCCESS` (ledger 16724793)   | ✓ True     | `run_dvp_20260421_115524.json`                           |
| Open          | Negative test | `dvp_swap.py`               | 9         | `tecPATH_PARTIAL` (no offer)    | ✓ True     | `run_dvp_negative_20260421_115827.json`                  |

Permissioned runs carry two additional setup transactions:
`AccountSet asfRequireAuth` on `ShareIssuer` and the issuer-side
`TrustSet` with `TF_SET_AUTH` authorizing the investor's MMF line.
The atomic DvP mechanics in steps 10-11 are identical across variants.

All four current runs are reproducible via:

```bash
# Open variant — happy path
printf "approve\n<approval reason>\n" | \
  .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap.py

# Open variant — negative test
printf "approve\n<approval reason>\n" | \
  .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap.py --negative-test

# Permissioned variant — happy path
printf "approve\n<approval reason>\n" | \
  .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap_permissioned.py

# Permissioned variant — negative test
printf "approve\n<approval reason>\n" | \
  .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap_permissioned.py --negative-test
```

## Doctrine summary (checklist)

- [x] Testnet-only endpoint, mainnet hosts asserted-against at startup.
- [x] HITL gate before the atomic event; keystroke + UTC timestamp in artifact.
- [x] SYNTHETIC banner on every artifact and every print.
- [x] Full audit trail — tx hashes, ledger indices, close timestamps.
- [x] Python-only for operator hands; polyglot remains read-and-explain.
- [x] No new system dependencies; `xrpl-py` already in `.venv`.
- [x] Failure-mode proof (negative test) included.
- [x] Architectural correction from live ledger documented in Section 2.3.
