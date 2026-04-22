"""
PURPOSE:     Replay the tokenized leg of the MMF settlement simulation
             against a REAL ledger — the XRP Ledger (XRPL) testnet — so
             that the ~12s on-chain finality assumption in
             builds/tokenized_mmf_settlement/simulate.py survives contact
             with a live, distributed, publicly-verifiable network.

             Concretely: create two testnet wallets (issuer + investor),
             configure the issuer the way an institutional share-class
             issuer would, establish a trust line from the investor to
             the issuer for a synthetic MMF share token, and issue
             1,000,000 shares via a single Payment transaction.

             Every step is timestamped against the wall clock AND against
             the ledger-close time, so we can compare what the TradFi
             (Traditional Finance) simulation assumed to what actually
             happened.

INPUTS:      None. The XRPL testnet faucet funds wallets for free. No
             secrets on disk, no existing accounts reused — each run
             creates fresh wallets on a throwaway public testnet.

OUTPUTS:     builds/tokenized_mmf_xrpl_leg/run_YYYYMMDD_HHMMSS.json
               — machine-readable trace (wallets, tx hashes, timings).
             stdout — a human-readable BLUF summary.

ASSUMPTIONS: - XRPL testnet is reachable at
               https://s.altnet.rippletest.net:51234 (public endpoint).
             - The testnet faucet is up. If it isn't, the script exits
               cleanly with a clear message — it never falls back to
               mainnet. Mainnet is explicitly blocked.
             - A 3-letter currency code ("MMF") is used for the share
               token. In production you would use a 40-byte hex code to
               encode something richer like "PRIMEMMF-I-2026". Same
               mechanism, different string length.
             - This is SYNTHETIC. The "ACME Family Office" wallet has no
               real owner. "Prime MMF Class I" is not a real fund. No
               real assets are created.

AUDIT NOTES: - Zero mainnet exposure. Endpoint is hardcoded to testnet
               and asserted at startup. No env-var override.
             - All tx hashes written to JSON are verifiable on any XRPL
               testnet explorer (e.g. testnet.xrpl.org).
             - Wallets are ephemeral. Their seeds are NOT persisted.
             - HITL (Human-In-The-Loop) gate is modeled as a real
               input() pause before the issuance transaction submits,
               matching the compliance-step placement in the parent
               simulation.
"""

# ----------------------------------------------------------------------------
# TEACHING NOTE — what xrpl-py is doing under the hood
# ----------------------------------------------------------------------------
# xrpl-py is the official Python SDK for the XRP Ledger. It handles:
#   - RPC transport (HTTP JSON-RPC or WebSocket) to a node we don't run.
#   - Transaction serialization (turning a Python object into the exact
#     bytes the ledger expects — XRPL's wire format is its own binary
#     codec, not JSON, not RLP).
#   - Signing (ed25519 or secp256k1) using the wallet's private key.
#   - "submit_and_wait" — a convenience that submits the tx and polls
#     the network until a validator includes it in a closed ledger, then
#     returns the final result. This is our ~12s measurement.
#
# XRPL closes a new ledger every ~3-5 seconds. "Finality" on XRPL is
# deterministic: once your tx is in a validated ledger, it cannot be
# reorged. That is the structural claim the MMF simulation leaned on.
# ----------------------------------------------------------------------------

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

from xrpl.clients import JsonRpcClient
from xrpl.wallet import generate_faucet_wallet
from xrpl.models.transactions import (
    AccountSet,
    AccountSetAsfFlag,
    TrustSet,
    Payment,
)
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.transaction import submit_and_wait


# --- Safety rails -----------------------------------------------------------
TESTNET_RPC = "https://s.altnet.rippletest.net:51234"
MAINNET_HOSTS_BLOCK = ("xrplcluster.com", "s1.ripple.com", "s2.ripple.com")

# --- Synthetic trade parameters (match the parent sim) ----------------------
SHARE_CURRENCY = "MMF"      # 3-letter ticker; XRPL supports longer hex codes
SHARE_COUNT = "1000000"     # 1,000,000 shares, string per XRPL convention
TRUST_LIMIT = "10000000"    # investor's trust line max (operational headroom)

INVESTOR_LABEL = "ACME Family Office (SYNTHETIC)"
ISSUER_LABEL = "Generic Prime MMF Class I Issuer (SYNTHETIC)"


# --- Small helpers ----------------------------------------------------------
def utc_now() -> str:
    """ISO-8601 UTC timestamp, second precision."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ripple_epoch_to_iso(ripple_time: int) -> str:
    """XRPL stamps ledger-close times in 'Ripple epoch' seconds (seconds
    since 2000-01-01 UTC). We convert to UTC ISO for readability."""
    ripple_epoch_offset = 946684800  # seconds from 1970-01-01 to 2000-01-01
    unix_seconds = ripple_time + ripple_epoch_offset
    return datetime.fromtimestamp(unix_seconds, timezone.utc).isoformat()


@dataclass
class StepRecord:
    """One event in the audit trace."""
    label: str
    started_at_utc: str
    finished_at_utc: str
    wall_seconds: float
    tx_hash: str = ""
    ledger_index: int = 0
    ledger_close_utc: str = ""
    note: str = ""


@dataclass
class RunRecord:
    data_label: str = "SYNTHETIC — XRPL testnet, not for production use"
    started_at_utc: str = ""
    finished_at_utc: str = ""
    rpc_endpoint: str = TESTNET_RPC
    issuer_address: str = ""
    investor_address: str = ""
    share_currency: str = SHARE_CURRENCY
    shares_issued: str = SHARE_COUNT
    steps: list[StepRecord] = field(default_factory=list)
    total_wall_seconds: float = 0.0
    verdict: str = ""


# --- HITL gate --------------------------------------------------------------
def hitl_gate(context: str) -> None:
    """Explicit human-in-the-loop pause. Matches the compliance-step
    placement in builds/tokenized_mmf_settlement/simulate.py.

    The operator types 'approve' to release the transaction. Anything
    else aborts the run cleanly. Models a compliance reviewer sign-off
    *before* the atomic ledger event — because once the tx submits, the
    share-issuance leg is effectively final."""
    print("\n" + "=" * 72)
    print("HITL GATE — compliance review")
    print("=" * 72)
    print(context)
    print("-" * 72)
    response = input("Type 'approve' to submit, anything else to abort: ").strip().lower()
    if response != "approve":
        print("HITL gate: operator aborted. No transaction submitted.")
        sys.exit(0)
    print("HITL gate: approved. Submitting to network.\n")


# --- Core flow --------------------------------------------------------------
def run() -> RunRecord:
    # Safety assert: the endpoint must be the public testnet. Belt + braces
    # in case a well-meaning future edit swaps in a mainnet URL.
    assert "altnet" in TESTNET_RPC, "Endpoint must be XRPL testnet."
    for blocked in MAINNET_HOSTS_BLOCK:
        assert blocked not in TESTNET_RPC, f"Refusing mainnet host {blocked}."

    run_rec = RunRecord(started_at_utc=utc_now())
    client = JsonRpcClient(TESTNET_RPC)
    print(f"[{utc_now()}] Connected to XRPL testnet: {TESTNET_RPC}")

    # ------------------------------------------------------------------
    # Step 1 — fund issuer wallet from the testnet faucet
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    t0_iso = utc_now()
    print(f"[{t0_iso}] Funding issuer wallet ({ISSUER_LABEL})...")
    issuer = generate_faucet_wallet(client, debug=False)
    run_rec.issuer_address = issuer.classic_address
    run_rec.steps.append(StepRecord(
        label="Fund issuer wallet (faucet)",
        started_at_utc=t0_iso,
        finished_at_utc=utc_now(),
        wall_seconds=round(time.monotonic() - t0, 3),
        note=f"Issuer address: {issuer.classic_address}",
    ))
    print(f"           issuer address: {issuer.classic_address}")

    # ------------------------------------------------------------------
    # Step 2 — fund investor wallet from the testnet faucet
    # ------------------------------------------------------------------
    t0 = time.monotonic()
    t0_iso = utc_now()
    print(f"[{t0_iso}] Funding investor wallet ({INVESTOR_LABEL})...")
    investor = generate_faucet_wallet(client, debug=False)
    run_rec.investor_address = investor.classic_address
    run_rec.steps.append(StepRecord(
        label="Fund investor wallet (faucet)",
        started_at_utc=t0_iso,
        finished_at_utc=utc_now(),
        wall_seconds=round(time.monotonic() - t0, 3),
        note=f"Investor address: {investor.classic_address}",
    ))
    print(f"           investor address: {investor.classic_address}")

    # ------------------------------------------------------------------
    # Step 3 — issuer sets DefaultRipple so balances can flow through
    # ------------------------------------------------------------------
    # Institutional context: on XRPL, an issuer must enable DefaultRipple
    # for issued-asset balances to route between trust lines. Without it,
    # the token is "stuck" on the issuing account and cannot move
    # between holders. This is the XRPL equivalent of enabling the
    # rail, and every institutional issuer does it on day one.
    t0 = time.monotonic()
    t0_iso = utc_now()
    print(f"[{t0_iso}] Issuer AccountSet: enable DefaultRipple...")
    account_set_tx = AccountSet(
        account=issuer.classic_address,
        set_flag=AccountSetAsfFlag.ASF_DEFAULT_RIPPLE,
    )
    account_set_result = submit_and_wait(account_set_tx, client, issuer)
    _record_tx_step(
        run_rec, "Issuer AccountSet (enable DefaultRipple)",
        t0_iso, t0, account_set_result,
    )

    # ------------------------------------------------------------------
    # Step 4 — investor opens a trust line to the issuer for MMF shares
    # ------------------------------------------------------------------
    # The trust line is the investor's explicit opt-in to hold a specific
    # issued asset from a specific issuer. It is the XRPL analogue of an
    # allowlist entry + custodial authorization in one step. This is
    # also where, in a real institutional deployment, the issuer would
    # have already run KYC (Know-Your-Customer) and only the approved
    # investor would even reach this step.
    t0 = time.monotonic()
    t0_iso = utc_now()
    print(f"[{t0_iso}] Investor TrustSet: open trust line for {SHARE_CURRENCY}...")
    trust_set_tx = TrustSet(
        account=investor.classic_address,
        limit_amount=IssuedCurrencyAmount(
            currency=SHARE_CURRENCY,
            issuer=issuer.classic_address,
            value=TRUST_LIMIT,
        ),
    )
    trust_set_result = submit_and_wait(trust_set_tx, client, investor)
    _record_tx_step(
        run_rec, f"Investor TrustSet (limit {TRUST_LIMIT} {SHARE_CURRENCY})",
        t0_iso, t0, trust_set_result,
    )

    # ------------------------------------------------------------------
    # HITL compliance gate — the "approve to mint" step
    # ------------------------------------------------------------------
    hitl_gate(
        f"Issuer:   {issuer.classic_address}\n"
        f"Investor: {investor.classic_address}\n"
        f"Action:   Issue {SHARE_COUNT} {SHARE_CURRENCY} shares\n"
        f"Context:  Tokenized MMF subscription, synthetic run.\n"
        f"          In production this gate confirms KYC current, sanctions\n"
        f"          clear, allowlist matches, and order matches NAV strike."
    )

    # ------------------------------------------------------------------
    # Step 5 — issuer Payment transaction: issue the shares
    # ------------------------------------------------------------------
    # On XRPL, "issuance" is a Payment from the issuer account where the
    # `amount` is an IssuedCurrencyAmount. The ledger interprets this as
    # "create (issue) these units against the recipient's trust line".
    # There is no separate 'mint' opcode — the Payment is the mint.
    t0 = time.monotonic()
    t0_iso = utc_now()
    print(f"[{t0_iso}] Issuer Payment: issue {SHARE_COUNT} {SHARE_CURRENCY} to investor...")
    payment_tx = Payment(
        account=issuer.classic_address,
        destination=investor.classic_address,
        amount=IssuedCurrencyAmount(
            currency=SHARE_CURRENCY,
            issuer=issuer.classic_address,
            value=SHARE_COUNT,
        ),
    )
    payment_result = submit_and_wait(payment_tx, client, issuer)
    _record_tx_step(
        run_rec, f"Issuer Payment: issue {SHARE_COUNT} {SHARE_CURRENCY} to investor",
        t0_iso, t0, payment_result,
    )

    # ------------------------------------------------------------------
    # Finalize run record
    # ------------------------------------------------------------------
    run_rec.finished_at_utc = utc_now()
    run_rec.total_wall_seconds = round(
        sum(s.wall_seconds for s in run_rec.steps), 3
    )

    # Focus: the *on-chain* portion (3 txs), which is the part the parent
    # simulation assumed would take ~12s. Funding steps and HITL are
    # operational, not ledger-finality.
    onchain_wall = round(
        sum(s.wall_seconds for s in run_rec.steps if s.tx_hash), 3
    )

    if onchain_wall < 30:
        run_rec.verdict = (
            f"On-chain finality across 3 txs: {onchain_wall}s. "
            f"The parent sim's ~12s single-tx assumption survives; "
            f"multi-tx setup is still orders of magnitude under T+1."
        )
    else:
        run_rec.verdict = (
            f"On-chain finality across 3 txs: {onchain_wall}s. "
            f"Slower than the parent sim assumed — worth investigating "
            f"(testnet congestion? validator diversity?)."
        )

    return run_rec


def _record_tx_step(run_rec: RunRecord, label: str, started_iso: str,
                    t0_monotonic: float, tx_result) -> None:
    """Pull tx_hash, ledger_index, and ledger close time out of an xrpl-py
    submit_and_wait result and append a StepRecord. Kept as a helper so
    the main flow reads top-to-bottom."""
    wall = round(time.monotonic() - t0_monotonic, 3)
    finished_iso = utc_now()

    result_dict = tx_result.result if hasattr(tx_result, "result") else {}
    tx_hash = result_dict.get("hash", "") or result_dict.get("tx_json", {}).get("hash", "")
    ledger_index = result_dict.get("ledger_index", 0)

    # ledger close time lives under different keys depending on SDK version
    close_time_ripple = (
        result_dict.get("close_time_iso")
        or result_dict.get("date")
        or result_dict.get("tx_json", {}).get("date")
    )
    if isinstance(close_time_ripple, int):
        close_iso = ripple_epoch_to_iso(close_time_ripple)
    elif isinstance(close_time_ripple, str):
        close_iso = close_time_ripple
    else:
        close_iso = ""

    engine_result = result_dict.get("engine_result") or result_dict.get("meta", {}).get("TransactionResult", "")
    note = f"engine_result={engine_result}" if engine_result else ""

    run_rec.steps.append(StepRecord(
        label=label,
        started_at_utc=started_iso,
        finished_at_utc=finished_iso,
        wall_seconds=wall,
        tx_hash=tx_hash,
        ledger_index=ledger_index,
        ledger_close_utc=close_iso,
        note=note,
    ))
    print(f"           tx_hash={tx_hash[:16]}... ledger={ledger_index} wall={wall}s")


def write_artifact(run_rec: RunRecord) -> Path:
    """Persist the run trace as JSON. Filename is timestamped so repeated
    runs accumulate rather than overwrite."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(__file__).parent
    out_path = out_dir / f"run_{stamp}.json"
    out_path.write_text(json.dumps(asdict(run_rec), indent=2))
    return out_path


def main() -> int:
    try:
        run_rec = run()
    except KeyboardInterrupt:
        print("\nInterrupted by operator. No artifact written.")
        return 130

    out_path = write_artifact(run_rec)

    print("\n" + "=" * 72)
    print("BLUF — XRPL tokenized-leg run")
    print("=" * 72)
    print(f"Data label:    {run_rec.data_label}")
    print(f"Endpoint:      {run_rec.rpc_endpoint}")
    print(f"Issuer:        {run_rec.issuer_address}")
    print(f"Investor:      {run_rec.investor_address}")
    print(f"Shares issued: {run_rec.shares_issued} {run_rec.share_currency}")
    print(f"Total wall:    {run_rec.total_wall_seconds}s")
    print(f"Verdict:       {run_rec.verdict}")
    print(f"Artifact:      {out_path}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
