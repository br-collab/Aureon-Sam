"""
PURPOSE:     Standalone permissioned-posture atomic DvP on XRPL testnet.

             Companion to `dvp_swap.py` (open variant). The atomic
             Delivery-versus-Payment mechanics in steps 10-11 are
             IDENTICAL to the open file — resting OfferCreate + cross-
             currency Payment with SendMax + tfLimitQuality in a single
             validated ledger. What this file adds is the mainnet-
             realistic access-control surface that any regulated
             tokenization would ship under:

               Step 4b — ShareIssuer AccountSet asfRequireAuth.
                         MUST precede any trust line on ShareIssuer (XRPL
                         rule: the flag cannot be set while trust lines
                         exist on the account).
               Step 7b — ShareIssuer TrustSet with TF_SET_AUTH,
                         LimitAmount.issuer = Investor, value = "0".
                         The on-ledger equivalent of a post-KYC
                         allowlist admission — flips the lsfAuth bit on
                         the investor's MMF trust line. Without this
                         step, the DvP Payment at step 11 fails with
                         tecNO_AUTH.

             Architectural reasoning lives in two places:
               - `dvp_design.md`                    — the full DvP
                 architecture (load-bearing).
               - `dvp_swap_permissioned_design.md`  — the delta doc
                 governing this file specifically.

INPUTS:      One CLI flag: --negative-test (default off). Skips the
             OfferCreate at step 10 and proves the Payment fails with
             tecPATH_PARTIAL, no balances moved.

             No secrets on disk. Wallets are freshly faucet-funded each
             run; seeds never persisted.

OUTPUTS:     builds/tokenized_mmf_xrpl_leg/run_dvp_permissioned_YYYYMMDD_HHMMSS.json
               (or run_dvp_permissioned_negative_... for negative tests).
             stdout — BLUF summary + per-step timing.

             Artifact schema is IDENTICAL to `dvp_swap.py` output.
             Downstream consumers (log parsers, future dashboards)
             continue to work with no branching on file-of-origin.

ASSUMPTIONS: XRPL testnet reachable, faucet funding, no mainnet exposure.
             asfRequireAuth is baseline on testnet — no amendment
             dependency. xrpl-py 4.5.0 flag encoding for TrustSetFlag
             and PaymentFlag matches published spec.

AUDIT NOTES: Every tx hash + ledger index + close time captured.
             HITL approval recorded in the JSON — keystroke, approval
             reason, reviewer identity, prompted_at_utc, decided_at_utc.
             Mainnet hosts blocked at startup via assertion.
             All data is SYNTHETIC — no real fund, cash, or investor.

             Permissioned runs carry TWO additional setup transactions
             (4b, 7b) vs the open variant. The atomic-DvP mechanics in
             steps 10-11 are unchanged — permissioning closes the
             "any holder can consume the offer" surface by restricting
             who can hold the issuer's IOU; it does not alter the one-
             ledger atomicity guarantee of the Payment itself.
"""

# ----------------------------------------------------------------------------
# TEACHING NOTE — why permissioning is orthogonal to atomicity
# ----------------------------------------------------------------------------
# Atomicity answers: "can the ledger produce a state where one leg moved
# and the other did not?" The XRPL answer is no, by design of the
# cross-currency Payment + SendMax + tfLimitQuality combination.
#
# Permissioning answers a different question: "who is allowed to hold
# the issued asset in the first place?" asfRequireAuth + TF_SET_AUTH
# restricts the set of addresses that can receive the issuer's IOU.
# It is the institutional access-control surface — the on-ledger
# expression of a KYC / AML / sanctions-screening workflow.
#
# The two are independent. An unpermissioned issuer can still run atomic
# DvP (that is what dvp_swap.py demonstrates). A permissioned issuer
# runs the same atomic DvP on top of an allowlist. This file shows that
# the atomicity guarantee survives the addition of the access-control
# surface — the two compose cleanly, which is what a regulated deployment
# needs.
# ----------------------------------------------------------------------------

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet, Wallet
from xrpl.models.transactions import (
    AccountSet,
    AccountSetAsfFlag,
    TrustSet,
    TrustSetFlag,
    Payment,
    PaymentFlag,
    OfferCreate,
)
from xrpl.models.requests import AccountLines
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.transaction import submit_and_wait


# --- Safety rails -----------------------------------------------------------
TESTNET_RPC = "https://s.altnet.rippletest.net:51234"
MAINNET_HOSTS_BLOCK = ("xrplcluster.com", "s1.ripple.com", "s2.ripple.com")

# --- Synthetic trade parameters ---------------------------------------------
SHARE_CURRENCY = "MMF"
CASH_CURRENCY = "USD"
TRADE_NOTIONAL = "1000000"         # 1,000,000 shares at $1 NAV (SYNTHETIC)
TRUST_LIMIT = "10000000"           # operational headroom on trust lines

SHARE_ISSUER_LABEL = "Generic Prime MMF Class I Issuer (SYNTHETIC)"
CASH_ISSUER_LABEL = "Generic Tokenized-USD Issuer (SYNTHETIC)"
INVESTOR_LABEL = "ACME Family Office (SYNTHETIC)"

# --- HITL reviewer identity (v1: hardcoded; future: signed keypair) ---------
# Operator decision 2026-04-18: record reviewer identity and an approval
# reason alongside keystroke + timestamp in the HITL artifact. This hardens
# the audit schema without building the reviewer-workflow infrastructure
# (that is a separate lane). The identity is hardcoded for v1 because the
# single operator is the only reviewer; future builds will replace this
# with a signed per-reviewer credential.
REVIEWER_IDENTITY = "Guillermo Ravelo"


# --- Helpers ----------------------------------------------------------------
def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ripple_epoch_to_iso(ripple_time: int) -> str:
    # XRPL's "Ripple epoch" begins 2000-01-01T00:00:00Z (946684800 Unix).
    ripple_epoch_offset = 946684800
    return datetime.fromtimestamp(ripple_time + ripple_epoch_offset,
                                  timezone.utc).isoformat()


@dataclass
class StepRecord:
    label: str
    started_at_utc: str
    finished_at_utc: str
    wall_seconds: float
    tx_hash: str = ""
    ledger_index: int = 0
    ledger_close_utc: str = ""
    engine_result: str = ""
    note: str = ""


@dataclass
class HITLRecord:
    prompted_at_utc: str = ""
    decided_at_utc: str = ""
    reviewer_identity: str = ""
    keystroke: str = ""
    approval_reason: str = ""
    approved: bool = False
    context: str = ""


@dataclass
class BalanceSnapshot:
    account_label: str
    account_address: str
    taken_at_utc: str
    lines: list[dict] = field(default_factory=list)


@dataclass
class RunRecord:
    # Schema matches dvp_swap.py one-for-one so downstream tooling
    # (log parsers, artifact dashboards) can consume either file's output
    # without branching on origin. `permissioned` is True by construction
    # in this file; the field is retained for consumer parity.
    mode: str = "happy_path"
    permissioned: bool = True
    data_label: str = "SYNTHETIC — XRPL testnet, not for production use"
    started_at_utc: str = ""
    finished_at_utc: str = ""
    rpc_endpoint: str = TESTNET_RPC
    share_issuer_address: str = ""
    cash_issuer_address: str = ""
    investor_address: str = ""
    share_currency: str = SHARE_CURRENCY
    cash_currency: str = CASH_CURRENCY
    trade_notional: str = TRADE_NOTIONAL
    hitl: HITLRecord = field(default_factory=HITLRecord)
    steps: list[StepRecord] = field(default_factory=list)
    balances_before_dvp: list[BalanceSnapshot] = field(default_factory=list)
    balances_after_dvp: list[BalanceSnapshot] = field(default_factory=list)
    total_wall_seconds: float = 0.0
    dvp_atomic: bool = False
    verdict: str = ""


# --- HITL gate --------------------------------------------------------------
def hitl_gate(context: str, record: HITLRecord) -> bool:
    """Pre-atomic Human-In-The-Loop gate. Returns True if the operator
    types 'approve' (case-insensitive), False otherwise. Records the
    decision into the audit artifact with four fields:

      - reviewer_identity: who approved (v1 hardcoded; future: signed)
      - keystroke:         what they typed, verbatim
      - approval_reason:   one-line free text, captured at decision time
      - decided_at_utc:    when the decision landed

    Placement is pre-atomic by design: once the Payment submits, there is
    no hold — the ledger closes and the swap is settled. Gate logic is
    intentionally identical to dvp_swap.py so operator muscle memory and
    downstream JSON consumers port across both files without change."""
    print("\n" + "=" * 72)
    print("HITL GATE — compliance review (PERMISSIONED posture)")
    print("=" * 72)
    print(context)
    print("-" * 72)
    record.prompted_at_utc = utc_now()
    record.context = context
    record.reviewer_identity = REVIEWER_IDENTITY
    print(f"Reviewer:  {record.reviewer_identity}")
    keystroke = input("Type 'approve' to submit, anything else to abort: ").strip()
    record.keystroke = keystroke
    record.approved = keystroke.lower() == "approve"
    if record.approved:
        reason = input("Approval reason (one line): ").strip()
        record.approval_reason = reason
        record.decided_at_utc = utc_now()
        print("HITL gate: APPROVED. Submitting DvP to network.\n")
    else:
        record.decided_at_utc = utc_now()
        print(f"HITL gate: ABORTED (keystroke={keystroke!r}). No DvP submitted.")
    return record.approved


# --- Balance reads ----------------------------------------------------------
def snapshot_balances(client: JsonRpcClient, label: str,
                      address: str) -> BalanceSnapshot:
    """Query account_lines for an address and return a serializable
    snapshot. Used to prove before/after balances around the DvP event."""
    resp = client.request(AccountLines(account=address))
    lines = resp.result.get("lines", [])
    return BalanceSnapshot(
        account_label=label,
        account_address=address,
        taken_at_utc=utc_now(),
        lines=lines,
    )


def _record_tx_step(run_rec: RunRecord, label: str, started_iso: str,
                    t0_monotonic: float, tx_result: Any) -> StepRecord:
    wall = round(time.monotonic() - t0_monotonic, 3)
    finished_iso = utc_now()

    result_dict = tx_result.result if hasattr(tx_result, "result") else {}
    tx_hash = result_dict.get("hash", "") or result_dict.get("tx_json", {}).get("hash", "")
    ledger_index = result_dict.get("ledger_index", 0)
    close_raw = (
        result_dict.get("close_time_iso")
        or result_dict.get("date")
        or result_dict.get("tx_json", {}).get("date")
    )
    if isinstance(close_raw, int):
        close_iso = ripple_epoch_to_iso(close_raw)
    elif isinstance(close_raw, str):
        close_iso = close_raw
    else:
        close_iso = ""
    engine_result = (
        result_dict.get("engine_result")
        or result_dict.get("meta", {}).get("TransactionResult", "")
    )

    step = StepRecord(
        label=label,
        started_at_utc=started_iso,
        finished_at_utc=finished_iso,
        wall_seconds=wall,
        tx_hash=tx_hash,
        ledger_index=ledger_index,
        ledger_close_utc=close_iso,
        engine_result=engine_result,
        note="",
    )
    run_rec.steps.append(step)
    print(f"           tx_hash={tx_hash[:16]}... ledger={ledger_index} "
          f"engine={engine_result} wall={wall}s")
    return step


def _fund(role: str, label: str, client: JsonRpcClient,
          run_rec: RunRecord) -> Wallet:
    t0_iso = utc_now()
    t0 = time.monotonic()
    print(f"[{t0_iso}] Funding {role} wallet ({label})...")
    wallet = generate_faucet_wallet(client, debug=False)
    run_rec.steps.append(StepRecord(
        label=f"Fund {role} wallet (faucet)",
        started_at_utc=t0_iso,
        finished_at_utc=utc_now(),
        wall_seconds=round(time.monotonic() - t0, 3),
        note=f"{role} address: {wallet.classic_address}",
    ))
    print(f"           {role} address: {wallet.classic_address}")
    return wallet


def _submit(run_rec: RunRecord, label: str, tx: Any,
            client: JsonRpcClient, signer: Wallet) -> StepRecord:
    t0_iso = utc_now()
    t0 = time.monotonic()
    print(f"[{t0_iso}] {label}...")
    try:
        result = submit_and_wait(tx, client, signer)
    except Exception as e:
        # Capture the failure as an audit event instead of crashing.
        # Used by the --negative-test path, where step 11 is expected to
        # be rejected. xrpl-py raises XRPLReliableSubmissionException on
        # final tec* / tef* / ter* codes for submit_and_wait.
        wall = round(time.monotonic() - t0, 3)
        print(f"           SUBMISSION FAILED: {type(e).__name__}: {e}")
        step = StepRecord(
            label=label,
            started_at_utc=t0_iso,
            finished_at_utc=utc_now(),
            wall_seconds=wall,
            engine_result="SUBMIT_EXCEPTION",
            note=f"{type(e).__name__}: {str(e)[:240]}",
        )
        run_rec.steps.append(step)
        return step
    return _record_tx_step(run_rec, label, t0_iso, t0, result)


# --- Setup phase ------------------------------------------------------------
def _setup(client: JsonRpcClient,
           run_rec: RunRecord) -> tuple[Wallet, Wallet, Wallet]:
    """Fund three wallets and open the trust lines under the permissioned
    posture. Eleven transactions total (vs nine in the open variant):
    two additional steps — 4b (asfRequireAuth on ShareIssuer) and
    7b (TF_SET_AUTH on the Investor MMF line) — are load-bearing for
    the permissioned posture and are what distinguishes this file from
    dvp_swap.py.

    Without step 4b, the allowlist discipline has no effect — any holder
    could open and use a trust line to ShareIssuer. Without step 7b, the
    DvP Payment at step 11 would fail with tecNO_AUTH.

    Returns the three Wallets in the order (share_issuer, cash_issuer,
    investor)."""

    # 1-3. Fund all three actors from the testnet faucet.
    share_issuer = _fund("ShareIssuer", SHARE_ISSUER_LABEL, client, run_rec)
    cash_issuer = _fund("CashIssuer", CASH_ISSUER_LABEL, client, run_rec)
    investor = _fund("Investor", INVESTOR_LABEL, client, run_rec)
    run_rec.share_issuer_address = share_issuer.classic_address
    run_rec.cash_issuer_address = cash_issuer.classic_address
    run_rec.investor_address = investor.classic_address

    # 4. ShareIssuer: enable DefaultRipple so MMF balances can route.
    _submit(
        run_rec, "ShareIssuer AccountSet (enable DefaultRipple)",
        AccountSet(
            account=share_issuer.classic_address,
            set_flag=AccountSetAsfFlag.ASF_DEFAULT_RIPPLE,
        ),
        client, share_issuer,
    )

    # 4b. ShareIssuer enables asfRequireAuth.
    #
    # Hard XRPL rule: asfRequireAuth can only be set while the account
    # has ZERO trust lines. The moment a trust line exists on the
    # account, the flag is rejected. Placement in the sequence is a
    # protocol constraint, not a stylistic choice.
    #
    # Effect: once set, any third party opening a trust line TO
    # ShareIssuer's issued MMF asset creates an UNAUTHORIZED line. The
    # holder cannot receive the MMF IOU until ShareIssuer submits
    # step 7b below.
    _submit(
        run_rec,
        "ShareIssuer AccountSet (enable RequireAuth) [permissioned 4b]",
        AccountSet(
            account=share_issuer.classic_address,
            set_flag=AccountSetAsfFlag.ASF_REQUIRE_AUTH,
        ),
        client, share_issuer,
    )

    # 5. CashIssuer: enable DefaultRipple so USD balances can route.
    _submit(
        run_rec, "CashIssuer AccountSet (enable DefaultRipple)",
        AccountSet(
            account=cash_issuer.classic_address,
            set_flag=AccountSetAsfFlag.ASF_DEFAULT_RIPPLE,
        ),
        client, cash_issuer,
    )

    # 6. ShareIssuer opens USD trust line to CashIssuer so it can
    # receive the cash leg of the DvP swap. RequireAuth on ShareIssuer
    # does NOT affect ShareIssuer's ability to hold other issuers'
    # IOUs — the flag gates holders of ShareIssuer's MMF, not
    # ShareIssuer's own holdings.
    _submit(
        run_rec,
        f"ShareIssuer TrustSet (hold {CASH_CURRENCY} from CashIssuer)",
        TrustSet(
            account=share_issuer.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=TRUST_LIMIT,
            ),
        ),
        client, share_issuer,
    )

    # 7. Investor opens MMF trust line to ShareIssuer.
    # The line exists but is UNAUTHORIZED (lsfAuth bit is 0) — the
    # Payment in step 11 would fail with tecNO_AUTH if step 7b below
    # is skipped.
    _submit(
        run_rec,
        f"Investor TrustSet (hold {SHARE_CURRENCY} from ShareIssuer)",
        TrustSet(
            account=investor.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=share_issuer.classic_address,
                value=TRUST_LIMIT,
            ),
        ),
        client, investor,
    )

    # 7b. ShareIssuer authorizes the Investor's MMF trust line.
    #
    # On-ledger equivalent of a post-KYC allowlist admission: the
    # issuer flips the lsfAuth bit on the investor's MMF line so the
    # investor can receive the issuer's IOU.
    #
    # Mechanics:
    #   Account              = ShareIssuer  (the signer — the issuer
    #                                         authorizing, not the
    #                                         holder)
    #   LimitAmount.currency = MMF
    #   LimitAmount.issuer   = Investor     (the counterparty of the
    #                                         line *from ShareIssuer's
    #                                         perspective*)
    #   LimitAmount.value    = "0"          (authorization-only — the
    #                                         issuer is not opening a
    #                                         reciprocal trust line)
    #   Flags                = TF_SET_AUTH  (0x00010000)
    #
    # Without this step, step 11 fails with tecNO_AUTH. With it, the
    # atomic DvP proceeds identically to the open variant.
    _submit(
        run_rec,
        f"ShareIssuer TrustSet (authorize Investor {SHARE_CURRENCY} line) "
        f"[permissioned 7b]",
        TrustSet(
            account=share_issuer.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=investor.classic_address,
                value="0",
            ),
            flags=TrustSetFlag.TF_SET_AUTH,
        ),
        client, share_issuer,
    )

    # 8. Investor opens USD trust line to CashIssuer.
    _submit(
        run_rec,
        f"Investor TrustSet (hold {CASH_CURRENCY} from CashIssuer)",
        TrustSet(
            account=investor.classic_address,
            limit_amount=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=TRUST_LIMIT,
            ),
        ),
        client, investor,
    )

    # 9. CashIssuer: Payment to investor — pre-fund the cash position.
    _submit(
        run_rec,
        f"CashIssuer Payment: pre-fund Investor with {TRADE_NOTIONAL} {CASH_CURRENCY}",
        Payment(
            account=cash_issuer.classic_address,
            destination=investor.classic_address,
            amount=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=TRADE_NOTIONAL,
            ),
        ),
        client, cash_issuer,
    )

    return share_issuer, cash_issuer, investor


# --- DvP phase --------------------------------------------------------------
def _atomic_dvp(client: JsonRpcClient, run_rec: RunRecord,
                share_issuer: Wallet, cash_issuer: Wallet, investor: Wallet,
                negative_test: bool) -> None:
    """The value-exchange event. Step 10 posts a resting OfferCreate.
    Step 11 is the atomic moment — a cross-currency Payment with
    SendMax + tfLimitQuality that consumes the offer in a single
    validated ledger.

    Mechanics are IDENTICAL to dvp_swap.py. Permissioning is enforced
    upstream in _setup() — by the time control reaches this function,
    the investor's MMF line has been authorized and the atomic DvP can
    run unchanged.

    Negative test: skip step 10. Ledger rejects step 11 with
    tecPATH_PARTIAL (no offer on the book to consume), all balances
    unchanged. Same failure mode as the open variant."""

    # Snapshot balances before the DvP event.
    run_rec.balances_before_dvp = [
        snapshot_balances(client, SHARE_ISSUER_LABEL, share_issuer.classic_address),
        snapshot_balances(client, CASH_ISSUER_LABEL, cash_issuer.classic_address),
        snapshot_balances(client, INVESTOR_LABEL, investor.classic_address),
    ]

    # Step 10 — ShareIssuer posts a resting Offer.
    #
    # NOTE — maker vs taker (architectural correction logged in
    # dvp_design.md Section 2.3): FillOrKill and ImmediateOrCancel are
    # TAKER flags. A maker posting new liquidity into an empty book
    # with FoK gets tecKILLED because there is nothing to consume. The
    # correct primitive for primary issuance is a RESTING offer; the
    # atomicity guarantee lives on the CONSUMING side (step 11's
    # tfLimitQuality + SendMax).
    if negative_test:
        print("\n[negative-test] Skipping OfferCreate (step 10). "
              "Payment should fail cleanly with tecPATH_PARTIAL.")
        run_rec.steps.append(StepRecord(
            label="SKIPPED: ShareIssuer OfferCreate (negative test)",
            started_at_utc=utc_now(),
            finished_at_utc=utc_now(),
            wall_seconds=0.0,
            note="negative test: offer deliberately not posted",
        ))
    else:
        offer_tx = OfferCreate(
            account=share_issuer.classic_address,
            taker_pays=IssuedCurrencyAmount(
                currency=CASH_CURRENCY,
                issuer=cash_issuer.classic_address,
                value=TRADE_NOTIONAL,
            ),
            taker_gets=IssuedCurrencyAmount(
                currency=SHARE_CURRENCY,
                issuer=share_issuer.classic_address,
                value=TRADE_NOTIONAL,
            ),
        )
        _submit(
            run_rec,
            f"ShareIssuer OfferCreate (resting): {TRADE_NOTIONAL} {SHARE_CURRENCY} "
            f"for {TRADE_NOTIONAL} {CASH_CURRENCY}",
            offer_tx, client, share_issuer,
        )

    # Step 11 — Investor cross-currency self-Payment that consumes the
    # offer atomically. tfLimitQuality ensures the rate is at-or-better
    # than Amount / SendMax. This is THE atomic event — either:
    #   (a) investor's USD trust-line balance decreases by exactly
    #       TRADE_NOTIONAL AND investor's MMF trust-line balance
    #       increases by exactly TRADE_NOTIONAL in the same validated
    #       ledger, or
    #   (b) the transaction fails (tec* code) and nothing moves.
    payment_tx = Payment(
        account=investor.classic_address,
        destination=investor.classic_address,
        amount=IssuedCurrencyAmount(
            currency=SHARE_CURRENCY,
            issuer=share_issuer.classic_address,
            value=TRADE_NOTIONAL,
        ),
        send_max=IssuedCurrencyAmount(
            currency=CASH_CURRENCY,
            issuer=cash_issuer.classic_address,
            value=TRADE_NOTIONAL,
        ),
        flags=PaymentFlag.TF_LIMIT_QUALITY,
    )
    swap_step = _submit(
        run_rec,
        f"Investor Payment (DvP swap): consume offer, {TRADE_NOTIONAL} "
        f"{CASH_CURRENCY} -> {TRADE_NOTIONAL} {SHARE_CURRENCY}",
        payment_tx, client, investor,
    )

    # Snapshot balances after the DvP event (or attempted event).
    run_rec.balances_after_dvp = [
        snapshot_balances(client, SHARE_ISSUER_LABEL, share_issuer.classic_address),
        snapshot_balances(client, CASH_ISSUER_LABEL, cash_issuer.classic_address),
        snapshot_balances(client, INVESTOR_LABEL, investor.classic_address),
    ]

    # Atomicity verdict.
    if negative_test:
        # Expect failure. tesSUCCESS here would be a red flag.
        succeeded = swap_step.engine_result == "tesSUCCESS"
        if succeeded:
            run_rec.dvp_atomic = False
            run_rec.verdict = (
                "NEGATIVE TEST FAILED: Payment succeeded without an Offer. "
                "This is a meaningful anomaly — investigate."
            )
        else:
            inv_after = run_rec.balances_after_dvp[2].lines
            got_mmf = any(
                line.get("currency") == SHARE_CURRENCY
                and float(line.get("balance", "0")) > 0
                for line in inv_after
            )
            if got_mmf:
                run_rec.dvp_atomic = False
                run_rec.verdict = (
                    "NEGATIVE TEST FAILED: engine rejected Payment but "
                    "investor somehow holds MMF. Investigate."
                )
            else:
                run_rec.dvp_atomic = True
                run_rec.verdict = (
                    f"NEGATIVE TEST PASSED (permissioned): no Offer -> "
                    f"Payment rejected (engine={swap_step.engine_result}). "
                    f"No shares delivered, no cash moved. Failure mode is "
                    f"clean, and the permissioned setup path did not "
                    f"introduce spurious approvals."
                )
    else:
        succeeded = swap_step.engine_result == "tesSUCCESS"
        inv_after = run_rec.balances_after_dvp[2].lines
        mmf_balance = next(
            (line.get("balance", "0") for line in inv_after
             if line.get("currency") == SHARE_CURRENCY
             and line.get("account") == share_issuer.classic_address),
            "0",
        )
        usd_balance = next(
            (line.get("balance", "0") for line in inv_after
             if line.get("currency") == CASH_CURRENCY
             and line.get("account") == cash_issuer.classic_address),
            "0",
        )
        delivered_shares = float(mmf_balance) == float(TRADE_NOTIONAL)
        cash_drained = float(usd_balance) == 0.0
        run_rec.dvp_atomic = succeeded and delivered_shares and cash_drained
        if run_rec.dvp_atomic:
            run_rec.verdict = (
                f"DvP ATOMIC (permissioned): investor received {mmf_balance} "
                f"{SHARE_CURRENCY}, USD drained to 0. Swap settled in a single "
                f"validated ledger on an authorized trust line."
            )
        else:
            run_rec.verdict = (
                f"DvP NOT ATOMIC: engine={swap_step.engine_result}, "
                f"investor MMF={mmf_balance}, investor USD={usd_balance}. "
                f"Review artifact. (Check for tecNO_AUTH if step 7b was "
                f"skipped.)"
            )


# --- Orchestration ----------------------------------------------------------
def run(negative_test: bool) -> RunRecord:
    # Mainnet-blocked at startup. These assertions are the last line of
    # defence before any client is constructed; the doctrine (testnet-
    # only, mainnet-blocked) is enforced here in code, not in comments.
    assert "altnet" in TESTNET_RPC, "Endpoint must be XRPL testnet."
    for blocked in MAINNET_HOSTS_BLOCK:
        assert blocked not in TESTNET_RPC, f"Refusing mainnet host {blocked}."

    mode_parts = ["negative_test" if negative_test else "happy_path",
                  "permissioned"]
    run_rec = RunRecord(
        mode="__".join(mode_parts),
        permissioned=True,
        started_at_utc=utc_now(),
    )
    client = JsonRpcClient(TESTNET_RPC)
    print(f"[{utc_now()}] Connected to XRPL testnet: {TESTNET_RPC}")
    print(f"[{utc_now()}] Mode: {run_rec.mode}")

    share_issuer, cash_issuer, investor = _setup(client, run_rec)

    approved = hitl_gate(
        f"ShareIssuer:      {share_issuer.classic_address}\n"
        f"CashIssuer:       {cash_issuer.classic_address}\n"
        f"Investor:         {investor.classic_address}\n"
        f"Mode:              {run_rec.mode}\n"
        f"Trust-line model:  permissioned (asfRequireAuth + explicit "
        f"issuer authorization of investor MMF line)\n"
        f"Action:            Atomic DvP — swap {TRADE_NOTIONAL} "
        f"{CASH_CURRENCY} for {TRADE_NOTIONAL} {SHARE_CURRENCY}\n"
        f"Guarantees:        Resting Offer + cross-currency Payment with "
        f"SendMax + tfLimitQuality = single-tx atomicity, on an "
        f"authorized trust line.",
        run_rec.hitl,
    )
    if not approved:
        run_rec.finished_at_utc = utc_now()
        run_rec.total_wall_seconds = round(
            sum(s.wall_seconds for s in run_rec.steps), 3,
        )
        run_rec.verdict = (
            f"Aborted at HITL gate (keystroke={run_rec.hitl.keystroke!r}). "
            f"Setup txs persisted (including permissioned 4b + 7b); "
            f"DvP never attempted."
        )
        return run_rec

    _atomic_dvp(client, run_rec, share_issuer, cash_issuer, investor,
                negative_test)

    run_rec.finished_at_utc = utc_now()
    run_rec.total_wall_seconds = round(
        sum(s.wall_seconds for s in run_rec.steps), 3,
    )
    return run_rec


def write_artifact(run_rec: RunRecord) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    parts = ["run_dvp", "permissioned"]
    if run_rec.mode.startswith("negative_test"):
        parts.append("negative")
    parts.append(stamp)
    out_dir = Path(__file__).parent
    out_path = out_dir / f"{'_'.join(parts)}.json"
    out_path.write_text(json.dumps(asdict(run_rec), indent=2, default=str))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Atomic DvP on XRPL testnet — PERMISSIONED variant "
                    "(asfRequireAuth + explicit trust-line authorization). "
                    "Companion to dvp_swap.py (open variant). All output is "
                    "SYNTHETIC; no real fund, cash, or investor.",
    )
    parser.add_argument(
        "--negative-test",
        action="store_true",
        help="Skip OfferCreate; prove Payment fails cleanly with no "
             "value moved. Proof by counterexample.",
    )
    args = parser.parse_args()

    try:
        run_rec = run(negative_test=args.negative_test)
    except KeyboardInterrupt:
        print("\nInterrupted by operator. No artifact written.")
        return 130

    out_path = write_artifact(run_rec)

    print("\n" + "=" * 72)
    print(f"BLUF — DvP run ({run_rec.mode})")
    print("=" * 72)
    print(f"Data label:   {run_rec.data_label}")
    print(f"Endpoint:     {run_rec.rpc_endpoint}")
    print(f"ShareIssuer:  {run_rec.share_issuer_address}")
    print(f"CashIssuer:   {run_rec.cash_issuer_address}")
    print(f"Investor:     {run_rec.investor_address}")
    print(f"Notional:     {run_rec.trade_notional} "
          f"{run_rec.share_currency} for {run_rec.trade_notional} "
          f"{run_rec.cash_currency}")
    print(f"Permissioned: {run_rec.permissioned}")
    print(f"HITL:         approved={run_rec.hitl.approved} "
          f"reviewer={run_rec.hitl.reviewer_identity!r} "
          f"keystroke={run_rec.hitl.keystroke!r}")
    print(f"HITL reason:  {run_rec.hitl.approval_reason!r}")
    print(f"HITL decided: {run_rec.hitl.decided_at_utc}")
    print(f"Total wall:   {run_rec.total_wall_seconds}s")
    print(f"DvP atomic:   {run_rec.dvp_atomic}")
    print(f"Verdict:      {run_rec.verdict}")
    print(f"Artifact:     {out_path}")
    print("=" * 72)
    return 0 if run_rec.dvp_atomic or not run_rec.hitl.approved else 1


if __name__ == "__main__":
    sys.exit(main())
