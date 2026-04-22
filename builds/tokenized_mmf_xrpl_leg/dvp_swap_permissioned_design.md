# dvp_swap_permissioned.py — Design Note

> **Status (2026-04-21):** design-first artifact. Code follows this doc.
> Extends, does not replace, `dvp_design.md`. Read that doc first for
> the architectural reasoning behind the atomic DvP mechanics; this one
> only names what changes when the permissioned posture lives in its own
> standalone script.

> **Relationship to prior work.** The permissioned posture already exists
> inside `dvp_swap.py` behind a `--permissioned` flag, with two verified
> testnet runs (ledger 16656361 happy path, `tecPATH_PARTIAL` negative;
> run artifacts `run_dvp_permissioned_20260419_003908.json` and
> `run_dvp_permissioned_negative_20260419_004035.json`). This design note
> governs the extraction of that code path into its own first-class file.

**Acronyms (short list; full glossary in `dvp_design.md`):**
DvP = Delivery-versus-Payment. MMF = Money Market Fund. HITL =
Human-In-The-Loop. KYC = Know-Your-Customer. IOU = I-Owe-You (issued
asset on XRPL). `asfRequireAuth` = AccountSet flag on an XRPL account
that requires the issuer to explicitly authorize every trust line
opened *to* that account's issued assets. `TF_SET_AUTH` = the TrustSet
flag an issuer submits to flip the `lsfAuth` bit on a counterparty's
trust line, admitting it to the allowlist. `tecNO_AUTH` / `tecPATH_PARTIAL`
= XRPL engine result codes (tec* = final, claimed fee, no state change
beyond fee).

---

## 1. Why a standalone file, not just the flag

The flag form worked. It produced four clean artifacts in one afternoon.
Operator decision (2026-04-21) to lift it to its own file is motivated by:

1. **Teaching clarity.** The open and permissioned postures are
   institutionally different — one is a tokenization demo, the other
   is the mainnet-realistic access-control surface. Two files make
   that distinction structural (visible in a directory listing, a
   commit diff, a README table) rather than runtime-conditional
   (hidden inside an `if permissioned:` branch a reader has to trace).
2. **Single-claim files.** Each file states one claim and verifies it
   end-to-end. `dvp_swap.py` → "XRPL supports atomic DvP as a native
   primitive." `dvp_swap_permissioned.py` → "the same atomic primitive
   survives the addition of issuer-side authorization — which is the
   posture any regulated tokenization would ship under."
3. **Closer to the mainnet mental model.** In a real deployment, the
   open posture would not exist; an institutional issuer does not ship
   unrestricted trust lines. Promoting the permissioned variant to its
   own file signals that this is the file an institutional reader should
   look at when asking "how would this actually run?"
4. **Independent evolution.** When the Batch amendment (XLS-56) activates
   on the target network, the permissioned path is the one that should
   migrate first (offer + payment collapse into one atomic bundle, closing
   the inter-ledger window on top of the access-control surface). Keeping
   the two files separate means that migration touches one file, not a
   cross-cutting branch in a shared one.

**What this does NOT change:** the atomic-DvP mechanics in steps 10-11
are identical to `dvp_swap.py`. The design rationale in `dvp_design.md`
Sections 1-5 applies verbatim. This is a packaging change that carries
two extra setup transactions, not a new architectural claim.

## 2. What is identical to `dvp_swap.py`

These elements are copied forward without revision. They are
load-bearing and verified by the existing runs; changing any of them in
the permissioned file would create drift that a future reader must
reconcile.

- **Endpoint pinning.** `TESTNET_RPC = "https://s.altnet.rippletest.net:51234"`.
  Mainnet hosts asserted-against at startup
  (`MAINNET_HOSTS_BLOCK = ("xrplcluster.com", "s1.ripple.com", "s2.ripple.com")`).
- **Actor triplet and labels.** `ShareIssuer` / `CashIssuer` / `Investor`,
  same SYNTHETIC labels.
- **Trade parameters.** `SHARE_CURRENCY = "MMF"`, `CASH_CURRENCY = "USD"`,
  `TRADE_NOTIONAL = "1000000"`, `TRUST_LIMIT = "10000000"`.
- **HITL schema.** Four-field gate (`reviewer_identity`, `keystroke`,
  `approval_reason`, `decided_at_utc`) plus `prompted_at_utc`, `approved`,
  `context`. `REVIEWER_IDENTITY = "Guillermo Ravelo"` constant.
  `hitl_gate()` function logic unchanged. Gate fires *pre-atomic*, same
  placement as in `dvp_swap.py`.
- **Artifact shape.** `RunRecord`, `StepRecord`, `HITLRecord`,
  `BalanceSnapshot` dataclasses unchanged. JSON output schema identical —
  downstream consumers (log scripts, future dashboards) keep working with
  no branching on file-of-origin.
- **Freshly-faucet-funded ephemeral wallets.** No seed persistence.
- **Atomic DvP mechanics (steps 10-11).** Resting `OfferCreate` (no FoK,
  no IOC) + cross-currency `Payment` with `SendMax` and `tfLimitQuality`.
  The architectural correction logged in `dvp_design.md` Section 2.3
  (maker-vs-taker FoK mis-reading) stands.
- **Negative-test primitive.** `--negative-test` still skips the offer
  to prove `tecPATH_PARTIAL` / `tecPATH_DRY` on the consuming Payment.
- **SYNTHETIC banner on every artifact and every stdout print.**

## 3. What is different in `dvp_swap_permissioned.py`

### 3.1 Permissioned-by-construction
No `--permissioned` flag. The file is the permissioned variant; the
posture is the file's identity, not a runtime option. Simpler CLI,
fewer combinatorial modes to reason about.

### 3.2 Two additional setup transactions (load-bearing)

**Step 4b — `AccountSet asfRequireAuth` on `ShareIssuer`.**
Submitted *after* step 4 (`ShareIssuer AccountSet asfDefaultRipple`) and
*before* step 6 (the first trust line involving `ShareIssuer`). XRPL
enforces that `asfRequireAuth` can only be set while the account has no
trust lines — if any exist, the flag is rejected. Placement in the
sequence is a hard constraint, not a convention.

Effect: once set, any third party opening a trust line TO `ShareIssuer`'s
issued MMF asset creates an **unauthorized** line. The holder cannot
receive the MMF IOU until `ShareIssuer` submits an authorization.

**Step 7b — `TrustSet` with `TF_SET_AUTH` submitted by `ShareIssuer`.**
Placed between step 7 (investor opens the MMF trust line) and step 8
(investor opens the USD trust line). Exact field layout:

```
Account           = ShareIssuer      (the signer — the issuer
                                       authorizing, not the holder)
LimitAmount.currency = MMF
LimitAmount.issuer   = Investor      (the counterparty of the line
                                       from ShareIssuer's perspective)
LimitAmount.value    = "0"           (authorization-only, no reciprocal
                                       limit being opened)
Flags             = TF_SET_AUTH      (0x00010000)
```

Semantically: ShareIssuer is flipping the `lsfAuth` bit on the
investor's MMF trust line. This is the on-ledger equivalent of a
post-KYC allowlist admission. Without this step, step 11's atomic
Payment fails with `tecNO_AUTH` — the investor's line exists but is
not authorized to receive the issuer's IOU.

### 3.3 Artifact filename / `mode` string
Runs write to `run_dvp_permissioned_*.json` (and
`run_dvp_permissioned_negative_*.json` for negative tests). The
`RunRecord.permissioned` field is always `True` and
`RunRecord.mode` always contains the `permissioned` token. This
matches the pattern established by the existing permissioned runs.

### 3.4 HITL context string
The gate's context lines name `"permissioned (asfRequireAuth + explicit
issuer authorization of investor MMF line)"` verbatim. Removes the
ternary present in `dvp_swap.py` that flips wording based on a flag.
Reviewer sees the posture in the prompt every time — no risk of approving
under one mental model while the code runs the other.

### 3.5 Header block
The opening docstring spells out PURPOSE / INPUTS / OUTPUTS / ASSUMPTIONS
/ AUDIT NOTES specific to the permissioned file. Names the two extra
setup transactions as the file's distinguishing feature. Links back to
`dvp_design.md` for architectural reasoning.

## 4. Transaction sequence (eleven steps)

| #   | Signer        | Tx type       | Purpose                                                                                              |
|-----|---------------|---------------|------------------------------------------------------------------------------------------------------|
| 1   | —             | Faucet        | Fund `ShareIssuer`                                                                                   |
| 2   | —             | Faucet        | Fund `CashIssuer`                                                                                    |
| 3   | —             | Faucet        | Fund `Investor`                                                                                      |
| 4   | `ShareIssuer` | `AccountSet`  | Enable `asfDefaultRipple`                                                                            |
| **4b** | **`ShareIssuer`** | **`AccountSet`** | **Enable `asfRequireAuth` (must precede any trust line on this account)** |
| 5   | `CashIssuer`  | `AccountSet`  | Enable `asfDefaultRipple`                                                                            |
| 6   | `ShareIssuer` | `TrustSet`    | Open USD trust line to `CashIssuer`                                                                  |
| 7   | `Investor`    | `TrustSet`    | Open MMF trust line to `ShareIssuer` (unauthorized at this point)                                    |
| **7b** | **`ShareIssuer`** | **`TrustSet`** | **`TF_SET_AUTH` on investor MMF line — flips `lsfAuth` bit (KYC-admission analogue)** |
| 8   | `Investor`    | `TrustSet`    | Open USD trust line to `CashIssuer`                                                                  |
| 9   | `CashIssuer`  | `Payment`     | Pre-fund `Investor` with 1M USD                                                                      |
| —   | HITL          | (no tx)       | Pre-atomic approval gate — reviewer identity / keystroke / reason / UTC                              |
| 10  | `ShareIssuer` | `OfferCreate` | Resting offer: `TakerPays = 1M USD(CashIssuer)`, `TakerGets = 1M MMF(ShareIssuer)`                   |
| 11  | `Investor`    | `Payment`     | Cross-currency self-Payment. `Amount = 1M MMF`, `SendMax = 1M USD`, `tfLimitQuality`. **ATOMIC.**    |
| 12-14 | —           | `account_lines` | Post-settlement balance reads for audit                                                            |

## 5. What this build will prove (and what it will not)

### Will prove
1. **Atomic DvP survives the access-control surface.** Adding
   `asfRequireAuth` + explicit line authorization does not break the
   one-ledger atomic guarantee in step 11. The institutional posture
   is ledger-native, not bolted on.
2. **The compliance choke point is the authorization step.** Whoever
   signs step 7b is the gatekeeper. In production, that signer sits
   behind a KYC / AML / sanctions-screening workflow. In v1 the signer
   is the issuer wallet directly; the architectural claim is that the
   signing capability is the right hand-off point for a real workflow.
3. **Negative-test `tecPATH_PARTIAL` behaviour holds under permissioned
   setup.** Already evidenced by `run_dvp_permissioned_negative_*.json`;
   the standalone file reproduces it.

### Will NOT prove
1. **That v1's hardcoded reviewer identity is a real KYC workflow.**
   It is a placeholder that shapes the artifact schema for a real
   reviewer-workflow lane later.
2. **That step 7b's signer is cryptographically bound to a compliance
   officer.** In v1, the `ShareIssuer` wallet signs. Real deployment
   needs multisig / signer-list / signed-credential integration before
   step 7b is a defensible control.
3. **Freeze, clawback, or revocation.** This build authorizes; it does
   not revoke. Lifecycle events are out of scope.
4. **Mainnet liquidity, MEV, or front-running.** Permissioning closes
   the "any holder can consume the offer" surface (only an authorized
   line can receive MMF). It does not close the "offer is visible
   between ledgers" surface — Batch (XLS-56) is the answer there when
   it activates.
5. **Any claim the open variant already failed to prove.**
   `dvp_design.md` Section 5 non-claims apply to this file too.

### Load-bearing assumptions (in addition to `dvp_design.md` Section 5)
- `asfRequireAuth` activation is baseline on XRPL testnet. No amendment
  dependency needed.
- `TF_SET_AUTH` with `LimitAmount.value = "0"` is the authorization-only
  form — the issuer is not opening a reciprocal line, only flipping the
  `lsfAuth` bit.
- Step-ordering constraint (`asfRequireAuth` before any trust line on the
  account) is enforced by xrpl-py and the ledger; the script's sequence
  respects it.

## 6. Optional future negative test (not shipped in v1)

Two natural failure modes exist, only one of which is currently exercised:

| Mode                      | What is dropped           | Expected engine result   | Ships in v1? |
|---------------------------|---------------------------|--------------------------|--------------|
| Offer missing             | Step 10 skipped           | `tecPATH_PARTIAL`        | Yes (`--negative-test`) |
| Investor line unauthorized| Step 7b skipped           | `tecNO_AUTH`             | **Deferred.** A second flag (e.g. `--no-auth-test`) is worth adding once operator wants the richer failure-mode panel. For v1 we stay consistent with `dvp_swap.py`'s single negative-test scope. |

## 7. Verification pattern

Reproducibility commands, once the file exists:

```bash
# Happy path
printf "approve\n<approval reason>\n" | \
  .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap_permissioned.py

# Negative test (no offer posted)
printf "approve\n<approval reason>\n" | \
  .venv/bin/python builds/tokenized_mmf_xrpl_leg/dvp_swap_permissioned.py --negative-test
```

Expected artifacts:
- Happy path: `run_dvp_permissioned_YYYYMMDD_HHMMSS.json`,
  `engine_result = "tesSUCCESS"` on the DvP Payment,
  investor MMF balance = 1,000,000, investor USD balance = 0.
- Negative test: `run_dvp_permissioned_negative_YYYYMMDD_HHMMSS.json`,
  `engine_result = "tecPATH_PARTIAL"` on the DvP Payment, all balances
  unchanged.

## 8. Relationship to the existing `--permissioned` flag

**Cut-over plan (operator decision):** keep or drop the flag in
`dvp_swap.py`?

- *Option A — drop.* `dvp_swap.py` reverts to open-only. Two files,
  one posture each. Cleanest separation.
- *Option B — keep.* Flag stays as-is; `dvp_swap_permissioned.py`
  exists as the canonical permissioned entry point, and the flag
  becomes a convenience shortcut to the same mechanics.

**Recommendation:** *Option A.* One file per claim avoids the
maintenance hazard of two codepaths producing the same artifact. If
the flag stays, the next reader has to ask "which do I trust, the
file or the flag?" — a question that has no good answer. The verified
flag-based runs from 2026-04-18 are preserved on disk either way;
dropping the flag does not destroy evidence.

Defer the cut-over execution until the standalone file is built and
verified against testnet. That ordering keeps the flag as a
known-good fallback while the new file is being brought online.

## 9. Doctrine checklist

- [x] **Testnet-only.** Endpoint pinned, mainnet hosts asserted-against.
- [x] **Mainnet-blocked.** Hard assertion at `run()` entry, same as
      `dvp_swap.py`.
- [x] **HITL gate preserved.** Pre-atomic placement, four-field schema,
      hardcoded reviewer identity for v1.
- [x] **Audit artifact identical schema.** `RunRecord` / `StepRecord` /
      `HITLRecord` / `BalanceSnapshot` unchanged — downstream consumers
      keep working.
- [x] **Python-only for operator hands.** `xrpl-py` + stdlib only. No
      new dependencies.
- [x] **Synthetic banner on every artifact and every stdout print.**
- [x] **Architectural reasoning referenced, not duplicated.**
      `dvp_design.md` is load-bearing; this file governs packaging.
- [x] **Failure-mode proof.** `--negative-test` reproduces the
      `tecPATH_PARTIAL` path already evidenced by
      `run_dvp_permissioned_negative_20260419_004035.json`.
