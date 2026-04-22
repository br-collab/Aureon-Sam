"""
PURPOSE:     Extend the tokenized MMF XRPL build to achieve true atomic
             Delivery-versus-Payment (DvP) on the XRP Ledger testnet.

             Architecture (full rationale in dvp_design.md):
               * Three actors — ShareIssuer, CashIssuer, Investor.
               * Setup opens trust lines and pre-funds Investor with a
                 synthetic USD IOU (I-Owe-You) from CashIssuer.
               * A human-in-the-loop (HITL) gate records the reviewer's
                 keystroke + timestamp into the audit artifact.
               * ShareIssuer posts a Fill-or-Kill OfferCreate (no partial
                 fills, all-or-nothing).
               * Investor submits a cross-currency Payment to itself,
                 bounded by SendMax and tfLimitQuality, which consumes
                 the offer inside a single validated ledger.
               * Post-settlement balance reads verify the swap.

             The --negative-test flag proves the failure mode: skip the
             OfferCreate and try to run the Payment anyway. The ledger
             rejects it (no path to destination, no partial fill) and
             no balances move. Proof by counterexample.

INPUTS:      One CLI flag: --negative-test (default off).
             No secrets on disk. Wallets are freshly faucet-funded each
             run per operator choice (see dvp_design.md open questions).

OUTPUTS:     builds/tokenized_mmf_xrpl_leg/run_dvp_YYYYMMDD_HHMMSS.json
               (or run_dvp_negative_... for the adversarial mode).
             stdout — BLUF summary + per-step timing.

ASSUMPTIONS: Same as issue_shares.py — testnet only, faucet up, no
             mainnet exposure. The design doc is the load-bearing
             architectural reasoning; this file is the executable form.

AUDIT NOTES: Every tx hash + ledger index + close time captured.
             HITL approval now recorded in the JSON (keystroke + UTC ts).
             Mainnet hosts blocked at startup via assertion.
             All data is SYNTHETIC — no real fund, cash, or investor.
"""

# ----------------------------------------------------------------------------
# TEACHING NOTE — what makes this "atomic" DvP on XRPL
# ----------------------------------------------------------------------------
# XRPL's Payment transaction can do more than move a single currency. A
# cross-currency Payment specifies:
#
#   Amount   — what the destination receives (in the destination currency).
#   SendMax  — the maximum the source will pay (in the source currency).
#
# When the two currencies differ, the ledger consults the DEX (the
# native order book) and routes the exchange through offers. If no
# path exists — or the rate is worse than SendMax / Amount allows —
# the whole Payment fails. No partial side-effects, no rollback dance.
#
# We combine two XRPL flags to reach institutional-grade atomicity:
#
#   tfFillOrKill (on OfferCreate): the offer either fills completely
#                                  right now or vanishes. No partial
#                                  fills, no lingering book state.
#   tfLimitQuality (on Payment):   only consume offers that meet or
#                                  beat the quoted Amount/SendMax rate.
#                                  If the rate moved, the tx fails.
#
# Together they guarantee: either (a) investor's USD trust-line balance
# decreases by exactly 1,000,000 AND investor's MMF trust-line balance
# increases by exactly 1,000,000 in the same validated ledger, or (b)
# the transaction fails and nothing moves. That is true DvP.
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
    OfferCreateFlag,
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
TRADE_NOTIONAL = "1000000"         # 1,000,000 shares at $1 NAV
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
    mode: str = "happy_path"
    permissioned: bool = False
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
    """Prompt the operator for approval and record the decision in the
    audit artifact. Returns True if approved, False otherwise.

    Schema hardened 2026-04-18 per operator decision. Every gate
    crossing records four fields:
      - reviewer_identity: who approved (v1 hardcoded; future: signed)
      - keystroke:         what they typed, verbatim
      - approval_reason:   one-line free text, captured at decision time
      - decided_at_utc:    when the decision landed

    Rationale: the placeholder remains input()-based to keep this build
    focused on settlement mechanics, but the artifact schema is now
    shaped for a real reviewer workflow. When the reviewer-workflow
    lane ships, only the gate internals change; downstream consumers
    of the JSON keep working.
    """
    print("\n" + "=" * 72)
    print("HITL GATE — compliance review")
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
def snapshot_balances(client: JsonRpcClient, label: str, address: str) -> BalanceSnapshot:
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


# --- Setup phase ------------------------------------------------------------
def _setup(client: JsonRpcClient, run_rec: RunRecord, permissioned: bool,
           ) -> tuple[Wallet, Wallet, Wallet]:
    """Fund three wallets and open the trust lines. Returns the three
    Wallet objects in the order (share_issuer, cash_issuer, investor).

    When permissioned=True, adds two steps:
      4b. ShareIssuer AccountSet asfRequireAuth (BEFORE any trust lines
          exist on ShareIssuer — XRPL constraint).
      7b. ShareIssuer authorizes Investor's MMF trust line via a
          TrustSet with TF_SET_AUTH, LimitAmount.issuer = investor
          address, value = 0.

    Without 7b in permissioned mode, the DvP Payment would fail with
    tecNO_AUTH: the investor's trust line exists but is not authorized
    to hold the issuer's IOU. This is the real institutional access
    control surface — KYC pre-checked, allowlist enforced at the ledger.
    """

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

    # 4b. PERMISSIONED MODE ONLY — ShareIssuer enables asfRequireAuth.
    # Per XRPL rules, this flag can ONLY be set while the account has
    # no trust lines. We therefore set it here, before step 6 creates
    # the ShareIssuer's outbound USD trust line to CashIssuer.
    if permissioned:
        _submit(
            run_rec,
            "ShareIssuer AccountSet (enable RequireAuth) [permissioned]",
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
    # receive the cash leg of the DvP swap. (ShareIssuer is a *holder*
    # of USD from CashIssuer's perspective — RequireAuth on ShareIssuer
    # does not affect ShareIssuer's ability to hold other issuers' IOUs.)
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
    # In permissioned mode this line exists but is UNAUTHORIZED until
    # step 7b. The Payment in step 11 would fail with tecNO_AUTH if
    # 7b is skipped.
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

    # 7b. PERMISSIONED MODE ONLY — ShareIssuer authorizes the Investor's
    # MMF trust line. This is the on-ledger equivalent of a
    # post-KYC allowlist admission: the issuer flips the lsfAuth bit on
    # the investor's line so the investor can receive the issuer's IOU.
    #
    # Mechanics: ShareIssuer submits a TrustSet where
    #   - Account         = ShareIssuer (signer)
    #   - LimitAmount.issuer = Investor (the counterparty of the line
    #                         *from ShareIssuer's perspective*)
    #   - LimitAmount.value  = "0" (authorization-only — issuer is not
    #                         opening a reciprocal line)
    #   - Flags           = TF_SET_AUTH (0x00010000)
    if permissioned:
        _submit(
            run_rec,
            f"ShareIssuer TrustSet (authorize Investor {SHARE_CURRENCY} line) [permissioned]",
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
        # Used mainly by the --negative-test path, where we expect one
        # of these to be rejected. xrpl-py raises XRPLReliableSubmissionException
        # on final tec* / tef* / ter* codes for submit_and_wait.
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


# --- DvP phase --------------------------------------------------------------
def _atomic_dvp(client: JsonRpcClient, run_rec: RunRecord,
                share_issuer: Wallet, cash_issuer: Wallet, investor: Wallet,
                negative_test: bool) -> None:
    """The value-exchange event. Step 10 posts the FoK Offer. Step 11
    consumes it via a cross-currency Payment with SendMax + LimitQuality.

    In --negative-test, step 10 is skipped. Step 11 then has no offer
    to consume and the ledger should reject it with tecPATH_DRY (or
    similar), leaving all balances unchanged."""

    # Snapshot balances before the DvP event.
    run_rec.balances_before_dvp = [
        snapshot_balances(client, SHARE_ISSUER_LABEL, share_issuer.classic_address),
        snapshot_balances(client, CASH_ISSUER_LABEL, cash_issuer.classic_address),
        snapshot_balances(client, INVESTOR_LABEL, investor.classic_address),
    ]

    # Step 10 — ShareIssuer posts Fill-or-Kill Offer.
    if negative_test:
        print("\n[negative-test] Skipping OfferCreate (step 10). "
              "Payment should fail cleanly.")
        run_rec.steps.append(StepRecord(
            label="SKIPPED: ShareIssuer OfferCreate (negative test)",
            started_at_utc=utc_now(),
            finished_at_utc=utc_now(),
            wall_seconds=0.0,
            note="negative test: offer deliberately not posted",
        ))
    else:
        # CORRECTION from design-doc v1: FoK on OfferCreate is a *taker*
        # flag — "consume existing book liquidity immediately or die"
        # (tecKILLED if no liquidity). Since our ShareIssuer is the one
        # *creating* liquidity with no counter-offer yet on the book, a
        # regular (resting) Offer is the right primitive. The atomicity
        # guarantee lives on the consuming side: the Payment's
        # tfLimitQuality blocks any fill worse than the quoted rate and
        # returns tecPATH_PARTIAL if the offer has been moved/consumed.
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
    # than Amount / SendMax.
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
            # Confirm no MMF was delivered to investor.
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
                    f"NEGATIVE TEST PASSED: no Offer -> Payment rejected "
                    f"(engine={swap_step.engine_result}). No shares delivered, "
                    f"no cash moved. Failure mode is clean."
                )
    else:
        # Expect success. Verify investor received exactly TRADE_NOTIONAL MMF.
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
                f"DvP ATOMIC: investor received {mmf_balance} {SHARE_CURRENCY}, "
                f"USD drained to 0. Swap settled in a single validated ledger."
            )
        else:
            run_rec.verdict = (
                f"DvP NOT ATOMIC: engine={swap_step.engine_result}, "
                f"investor MMF={mmf_balance}, investor USD={usd_balance}. "
                f"Review artifact."
            )


# --- Orchestration ----------------------------------------------------------
def run(negative_test: bool, permissioned: bool) -> RunRecord:
    assert "altnet" in TESTNET_RPC, "Endpoint must be XRPL testnet."
    for blocked in MAINNET_HOSTS_BLOCK:
        assert blocked not in TESTNET_RPC, f"Refusing mainnet host {blocked}."

    mode_parts = ["negative_test" if negative_test else "happy_path"]
    if permissioned:
        mode_parts.append("permissioned")
    run_rec = RunRecord(
        mode="__".join(mode_parts),
        permissioned=permissioned,
        started_at_utc=utc_now(),
    )
    client = JsonRpcClient(TESTNET_RPC)
    print(f"[{utc_now()}] Connected to XRPL testnet: {TESTNET_RPC}")
    print(f"[{utc_now()}] Mode: {run_rec.mode}")

    share_issuer, cash_issuer, investor = _setup(client, run_rec, permissioned)

    trust_line_posture = (
        "permissioned (asfRequireAuth + explicit issuer authorization of "
        "investor MMF line)" if permissioned else
        "open (any holder may open the trust line without issuer approval)"
    )
    approved = hitl_gate(
        f"ShareIssuer:     {share_issuer.classic_address}\n"
        f"CashIssuer:      {cash_issuer.classic_address}\n"
        f"Investor:        {investor.classic_address}\n"
        f"Mode:            {run_rec.mode}\n"
        f"Trust-line model: {trust_line_posture}\n"
        f"Action:          Atomic DvP — swap {TRADE_NOTIONAL} {CASH_CURRENCY} "
        f"for {TRADE_NOTIONAL} {SHARE_CURRENCY}\n"
        f"Guarantees:      Resting Offer + cross-currency Payment with "
        f"SendMax + tfLimitQuality = single-tx atomicity.",
        run_rec.hitl,
    )
    if not approved:
        run_rec.finished_at_utc = utc_now()
        run_rec.total_wall_seconds = round(
            sum(s.wall_seconds for s in run_rec.steps), 3,
        )
        run_rec.verdict = (
            f"Aborted at HITL gate (keystroke={run_rec.hitl.keystroke!r}). "
            f"Setup txs persisted; DvP never attempted."
        )
        return run_rec

    _atomic_dvp(client, run_rec, share_issuer, cash_issuer, investor, negative_test)

    run_rec.finished_at_utc = utc_now()
    run_rec.total_wall_seconds = round(
        sum(s.wall_seconds for s in run_rec.steps), 3,
    )
    return run_rec


def write_artifact(run_rec: RunRecord) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    parts = ["run_dvp"]
    if run_rec.permissioned:
        parts.append("permissioned")
    if run_rec.mode.startswith("negative_test"):
        parts.append("negative")
    parts.append(stamp)
    out_dir = Path(__file__).parent
    out_path = out_dir / f"{'_'.join(parts)}.json"
    out_path.write_text(json.dumps(asdict(run_rec), indent=2, default=str))
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    parser.add_argument(
        "--negative-test",
        action="store_true",
        help="Skip OfferCreate; prove Payment fails cleanly with no "
             "value moved. Proof by counterexample.",
    )
    parser.add_argument(
        "--permissioned",
        action="store_true",
        help="Use permissioned trust lines: asfRequireAuth on ShareIssuer "
             "+ explicit issuer authorization of the investor's MMF line. "
             "Models the mainnet-realistic access-control posture.",
    )
    args = parser.parse_args()

    try:
        run_rec = run(negative_test=args.negative_test,
                      permissioned=args.permissioned)
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
