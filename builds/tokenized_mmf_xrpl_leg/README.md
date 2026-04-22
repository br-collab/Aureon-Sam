# Tokenized MMF — XRPL Leg (Live Testnet Replay)

> **Data label:** SYNTHETIC. XRPL testnet only. No real fund, no real
> customer, no real money. The endpoint is hard-blocked to mainnet.
> Acronyms: MMF = Money Market Fund, XRPL = XRP Ledger, DvP = Delivery-
> versus-Payment, HITL = Human-In-The-Loop, KYC = Know-Your-Customer,
> TA = Transfer Agent, NAV = Net Asset Value.

## What this simulates
The **tokenized leg** of `builds/tokenized_mmf_settlement/` re-run
against a live public ledger instead of a time-table. We create two
fresh testnet wallets, configure the issuer the way an institutional
share-class issuer does, open a trust line from the investor to the
issuer, and issue 1,000,000 synthetic "MMF" share tokens via a single
Payment transaction. A HITL gate sits just before the issuance step,
matching the compliance-step placement in the parent simulation.

Every transaction hash in this README can be verified on any XRPL
testnet explorer (e.g. `https://testnet.xrpl.org/transactions/<hash>`).

## What this proves
- **The ~12s finality assumption from the parent sim holds.** On the
  2026-04-18 run, each individual transaction (AccountSet, TrustSet,
  Payment) reached a validated ledger in **5.1s – 8.6s** wall time.
  That brackets — and mostly beats — the conservative 12s the parent
  simulation used.
- **Per-transaction finality, not per-flow finality.** A real
  institutional subscription touches the ledger at least three times
  (issuer config once per lifetime, investor trust line once per
  investor, issuance per subscription). Aggregate on-chain time for a
  brand-new investor on a cold issuer account was **~20.5s** of ledger
  time — still four orders of magnitude below traditional T+1.
- **The issuance mechanic on XRPL is a Payment, not a separate mint
  opcode.** The issuer signs a Payment from its own account, with an
  `IssuedCurrencyAmount` whose issuer field equals the signer. The
  ledger interprets this as "create these units against the recipient's
  trust line."
- **DefaultRipple is load-bearing institutional setup.** Without it, an
  issuer's balances cannot route between trust lines. Any institutional
  XRPL issuer enables it on day one — the script does this explicitly
  and records the tx hash so the audit trail is complete.
- **HITL fits naturally at the pre-submission step.** Once the Payment
  submits, there is no "hold" — the ledger closes and the shares are
  on the investor's trust line. The compliance checkpoint therefore
  lives *before* the atomic event, not after.

## What this does NOT prove
- **This is not a 1940-Act MMF.** The "MMF" token is a three-letter
  currency code on a trust line. Legal wrapping, NAV discipline,
  redemption mechanics, and disclosure regimes are all off-chain
  problems that this script does not touch.
- **Testnet is not mainnet.** Validator diversity, fee pressure, and
  adversarial conditions on public mainnet can change close times,
  especially in congestion. Treat the numbers here as a floor for a
  healthy network, not a guarantee.
- **This is not DvP.** No cash leg exists in this build. We issued
  shares; we did not atomically exchange them for tokenized cash. That
  is a future extension (see "Where this wants to grow next").
- **Redemption and corporate-action mechanics are untested.** Burn on
  redemption, income distribution, freeze / clawback for compliance
  events — none of these are exercised here.
- **The HITL gate is a placeholder.** It is a terminal `input()` call,
  not a real reviewer workflow with identity, audit log, and dual
  control. Enough to prove the *placement* is right; not enough to
  ship.

## Assumptions (load-bearing)
- XRPL testnet endpoint `https://s.altnet.rippletest.net:51234` is
  reachable and the public faucet is funding wallets.
- The issuer account is fresh each run — no pre-existing trust lines,
  balances, or reserve obligations are inherited.
- Currency code `MMF` is used for readability. Production institutional
  issuance would use a 40-byte hex code carrying richer identity (e.g.,
  `"PRIMEMMF-I-2026"` encoded as hex).
- `submit_and_wait` polls until the tx is in a validated ledger. The
  reported wall time is end-to-end (submit + broadcast + include +
  validate), which is what the parent simulation's 12s assumption
  intended to cover.

## Verified run (2026-04-18, 22:16 UTC)

| Step                                    | Wall  | Ledger    | Tx hash (prefix)      |
| --------------------------------------- | ----- | --------- | --------------------- |
| Fund issuer wallet (faucet)             |  8.2s | —         | (off-ledger)          |
| Fund investor wallet (faucet)           |  6.1s | —         | (off-ledger)          |
| Issuer AccountSet (DefaultRipple)       |  8.6s | 16653572  | `D88A50B7…`           |
| Investor TrustSet (limit 10M MMF)       |  6.8s | 16653574  | `08F4D9CF…`           |
| Issuer Payment: issue 1M MMF            |  5.1s | 16653576  | `8BA7670D…`           |
| **On-chain subtotal**                   | **20.5s** |       |                       |
| **Full run incl. faucet + HITL**        | **34.9s** |       |                       |

- Issuer:   `rHEaRgnBbV6yhQE737wgANbaR8htHXMRL5`
- Investor: `rBeYo1y4H9VhVMqLbaK8CsAKZt2ps4ksEx`
- Full JSON trace: `run_20260418_221644.json`
- Verdict: the parent sim's ~12s assumption survives contact with a
  live ledger. Multi-tx setup (~20s) still beats T+1 by ~4,500x.

## How to re-run

```bash
# From the repo root, with the project venv active:
echo "approve" | .venv/bin/python builds/tokenized_mmf_xrpl_leg/issue_shares.py

# Or run interactively and type "approve" at the HITL prompt:
.venv/bin/python builds/tokenized_mmf_xrpl_leg/issue_shares.py
```

Each run writes a new `run_YYYYMMDD_HHMMSS.json` beside the script.
Runs accumulate so you can compare numbers across network conditions.

---

# DvP Atomic Swap — Cash Leg (Shipped 2026-04-18)

Architectural rationale lives in `dvp_design.md`. The executable form is
`dvp_swap.py`. Run modes:

```bash
# Happy path — posts offer, consumes it via cross-currency Payment.
echo "approve" | .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap.py

# Negative test — skips OfferCreate; proves the Payment fails cleanly
# with no value moved. Proof by counterexample.
echo "approve" | .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap.py --negative-test
```

## What the DvP extension proves
- **Atomic DvP on XRPL is a native primitive, not a pattern.** A
  single cross-currency `Payment` with `SendMax` + `tfLimitQuality`
  either swaps both legs in one validated ledger or fails with no
  value moved. No HTLC (Hash Time Lock Contract), no two-phase commit,
  no shared-secret preimage management.
- **The custodian role claim from the parent sim survives.** The
  custodian still runs keys + compliance (HITL gate at pre-submission);
  cash-movement ops are absorbed into the ledger.
- **Failure mode is clean.** The negative run proves that removing
  book liquidity (no OfferCreate) produces a deterministic rejection
  (`tecPATH_PARTIAL`) and leaves all balances exactly as they were.
  "DvP or nothing" is not marketing — it is the protocol's behavior.

## Architectural correction the live ledger forced
The design doc originally prescribed `tfFillOrKill` on the
`OfferCreate`. The first live run rejected that offer with
`tecKILLED`: **FoK is a taker flag**, meaning "consume existing book
liquidity immediately and completely or die" — and our `ShareIssuer`
was creating liquidity, not consuming it. The structural fix is that
atomicity must live on the consuming side. The `OfferCreate` is a
plain resting offer; the Investor's `Payment` provides the
`tfLimitQuality` guarantee. Parent design doc updated with the
correction section. This is exactly the kind of "failure as
architectural signal" the operator's doctrine celebrates.

## Verified run — happy path (2026-04-18, 23:07 UTC)

| #  | Step                                          | Wall | Ledger    | Engine       | Tx hash (prefix) |
|----|-----------------------------------------------|-----:|-----------|--------------|------------------|
| 1  | Fund ShareIssuer (faucet)                     |  7.4s| —         | —            | (off-ledger)     |
| 2  | Fund CashIssuer (faucet)                      |  6.4s| —         | —            | (off-ledger)     |
| 3  | Fund Investor (faucet)                        |  6.6s| —         | —            | (off-ledger)     |
| 4  | ShareIssuer AccountSet (DefaultRipple)        |  6.8s| 16654553  | tesSUCCESS   | `161D7CCD…`      |
| 5  | CashIssuer AccountSet (DefaultRipple)         |  6.7s| 16654555  | tesSUCCESS   | `2B99AEDE…`      |
| 6  | ShareIssuer TrustSet (hold USD from CashIssuer)|  6.7s| 16654557  | tesSUCCESS   | `2AE24127…`      |
| 7  | Investor TrustSet (hold MMF from ShareIssuer) |  5.0s| 16654559  | tesSUCCESS   | `AE945606…`      |
| 8  | Investor TrustSet (hold USD from CashIssuer)  |  6.7s| 16654561  | tesSUCCESS   | `059F715D…`      |
| 9  | CashIssuer Payment: pre-fund 1M USD           |  5.0s| 16654563  | tesSUCCESS   | `76BB67F2…`      |
| 10 | **ShareIssuer OfferCreate (resting)**         |  6.7s| 16654565  | **tesSUCCESS** | `572ED0BD…`    |
| 11 | **Investor Payment (atomic DvP swap)**        |  6.7s| 16654567  | **tesSUCCESS** | `535680F2…`    |
|    | **On-chain subtotal (setup + DvP)**           | **63.7s** |     |              |                  |
|    | **Atomic DvP tx alone (step 11)**             | **6.7s** |      |              |                  |

- ShareIssuer: `rp1JwNuqodJk936AufVoi9QFCvfqPKUPKT`
- CashIssuer:  `rJLgZduXVvEDgwAYEg9nLexUdqzxRswEyK`
- Investor:    `rUMCx3y2qBe4hWYzA6FXsRBnoymUaXdfEb`
- Artifact:    `run_dvp_20260418_230722.json`
- Final balances (verified via `account_lines`):
  - Investor: 1,000,000 MMF / 0 USD ✓
  - ShareIssuer: 1,000,000 USD ✓
  - CashIssuer: investor's USD line drained ✓
- HITL record: `approved=True keystroke='approve' decided_at=2026-04-18T23:07:06+00:00`
- **Verdict:** DvP atomic. Cash leaves investor, shares arrive, in
  the same validated ledger window. Swap tx alone settled in 6.7s.

## Verified run — negative test (2026-04-18, 23:16 UTC)

Identical setup (steps 1–9 all `tesSUCCESS`). Step 10 (`OfferCreate`)
deliberately skipped. Step 11 (the consuming Payment) submitted into an
empty order book.

| #  | Step                                          | Wall | Ledger | Engine           |
|----|-----------------------------------------------|-----:|--------|------------------|
| 10 | SKIPPED: ShareIssuer OfferCreate              | 0.0s | —      | —                |
| 11 | Investor Payment (attempted DvP)              |  8.6s| —      | **tecPATH_PARTIAL** |

- Artifact: `run_dvp_negative_20260418_231646.json`
- Final balances: **unchanged from pre-DvP snapshot**
  - Investor: 0 MMF / 1,000,000 USD (pre-funded; DvP never happened)
  - ShareIssuer: 0 USD
  - CashIssuer: investor's USD still at 1M
- **Verdict:** negative test passed. No offer, no swap, no movement.
  The protocol refuses the half-leg rather than leaving a dangling
  position. This is the proof the institutional audience actually
  cares about.

## HITL gate — now part of the audit artifact
Per operator decision (2026-04-18), the HITL reviewer's keystroke
and UTC decision timestamp are now recorded in every run's JSON under
the `hitl` key. A typo or declined approval leaves a distinct,
diffable record. The placeholder `input()` is still not a real
reviewer workflow (one keypair, no dual control) — but the artifact
schema is now shaped for the real thing.

## Where this wants to grow next (operator's choice)
- **Model a redemption** — investor sends shares back to issuer,
  issuer burns on receipt, cash goes the other way. Completes the
  subscription/redemption lifecycle and exercises the reverse DvP.
- **Wire in the compliance-failure lane (Lane C)** — add an allowlist
  check, block the TrustSet before it submits, and record the
  compliance-reviewer decision trail. The HITL artifact schema is
  already in place.
- **Harden the HITL gate** — move from terminal input to a signed
  reviewer approval (second keypair) and record the signature
  alongside the tx artifact. Most relevant to an institutional pitch.
- **Revisit with Batch (XLS-56)** when the amendment is activated —
  the Offer + Payment pair collapses into one atomic bundle, closing
  the inter-ledger window entirely.
- **Partial tokenization (Lane A)** — leave the cash leg off-chain as
  a T+1 wire and model the "halfway" pilot state. Contrast directly
  against the full-DvP numbers above.
