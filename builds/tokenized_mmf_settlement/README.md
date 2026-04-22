# Tokenized MMF Settlement — Side-by-Side Simulation

> **Data label:** SYNTHETIC. No real fund, no real customer, no real money.
> Acronyms: MMF = Money Market Fund, NAV = Net Asset Value, TA = Transfer
> Agent, DvP = Delivery-versus-Payment, HITL = Human-In-The-Loop,
> KYC = Know-Your-Customer, MPC = Multi-Party Computation.

## What this simulates
A single $1,000,000 subscription into a generic prime MMF, modeled twice on
the same fictional business day (2026-04-20):

1. **Traditional path (T+1):** broker captures order → Transfer Agent routes →
   wait for 4:00pm ET NAV cutoff → fund accountant strikes NAV → TA confirms
   and instructs custodian → next-morning Fedwire of cash → custodian + TA
   reconcile and post shares to the investor's account.
2. **Tokenized path (atomic DvP):** allowlisted investor wallet submits intent
   → compliance engine (with HITL option) clears the order → smart contract
   escrows tokenized cash → issuer multisig + contract atomically mint shares
   against cash release → block finality and custodian reconciliation.

Outputs:
- `simulate.py` — the model.
- `timeline.html` — interactive Plotly Gantt of both flows on one timeline.
- `summary.json` — machine-readable trace of every step.

## What this proves
- **The settlement-time gap is real and large.** Under our (clearly stated)
  assumptions the traditional path takes ~26h while the tokenized path
  finishes in ~15s. Even with conservative on-chain timings this is multiple
  orders of magnitude.
- **The custodian role transforms; it does not disappear.** Inline notes in
  `simulate.py` mark the exact steps where the role pivots:
  - Traditional: custodian is the **operational settlement counterparty** —
    receives cash via Fedwire, books shares against the TA register, runs
    end-of-day recon files.
  - Tokenized: custodian becomes a **key + compliance gatekeeper** — operates
    the wallet via MPC/multisig, enforces allowlist/KYC pre-trade, and
    handles asset-servicing (distributions, corporate actions). The
    transfer-agent ledger function moves onto the chain itself.
- **HITL is naturally inserted at the compliance step**, not at the cash leg
  — because in DvP the cash leg is atomic and there is nothing to "hold."
- **Cutoffs and waits are the dominant cost** in the traditional flow, not
  any single processing step. That is a structural observation, not an
  efficiency complaint about any one party.

## What this does NOT prove
- That a tokenized MMF is **legally equivalent** to a 1940-Act registered
  open-end fund. Tokenization wrappers, issuance vehicles, and applicable
  regulations vary by jurisdiction and product (e.g., 40-Act fund vs.
  tokenized share class vs. tokenized note referencing the fund). Consult
  authoritative sources for the specific structure.
- That on-chain settlement is **risk-free**. It moves risk: smart-contract
  risk, oracle risk, key-management risk, stablecoin/tokenized-cash issuer
  risk, and chain-liveness risk all become first-order.
- That **all** MMFs settle T+1 — some institutional share classes settle
  same-day (T+0) under specific cutoffs. The traditional flow here is a
  reasonable but not universal baseline.
- That **6,300x** is a forecast. It is the ratio of two illustrative
  assumption sets. Treat it as scale, not as a number.
- Anything about **liquidity, NAV stability, or investor outcomes**. This is
  a settlement-mechanics simulation only.

## Assumptions (load-bearing)
- Single US business day; no holiday/weekend math; no Fedwire cutoff
  edge cases; one NAV strike at 4:00pm ET.
- Tokenized leg runs on a **permissioned chain** with issuer-controlled
  mint/burn, an allowlist, and a single atomic DvP transaction. ~12s from
  intent to finality (one conservative block).
- Tokenized cash leg is an institutional-grade tokenized cash instrument
  (USDC, tokenized deposit, or a wholesale CBDC stand-in). The simulation
  does not distinguish between them.
- Custodian-role narrative reflects the **typical** institutional
  arrangement; specific bank/custodian operating models may collapse or
  separate these steps differently.
- All actor names, roles, and timestamps are illustrative.

## How to run
From the repo root, with the project venv active:

```bash
.venv/bin/python builds/tokenized_mmf_settlement/simulate.py
```

Then open `builds/tokenized_mmf_settlement/timeline.html` in a browser.

## Where this build wants to grow next (operator's choice)
- Add a third lane: **partial tokenization** — tokenized shares but
  off-chain cash (T+1 USD wire), to model the "halfway" state most
  pilots actually run today.
- Wire in `xrpl-py` to actually issue a synthetic share token on XRPL
  testnet and replay the tokenized leg against a real (test) ledger.
- Layer a **compliance failure** scenario (allowlist miss, sanctions
  hit) and show what the HITL gate looks like when it fires.
