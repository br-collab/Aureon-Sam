"""
================================================================================
PURPOSE
    Side-by-side simulation comparing the settlement of a Money Market Fund
    (MMF) share purchase under two operating models:
      (1) Traditional MMF on T+1 (US conventional path: broker -> Transfer Agent
          -> custodian -> investor of record).
      (2) Tokenized MMF settled atomically on a permissioned blockchain using
          Delivery-versus-Payment (DvP) against tokenized cash (e.g., USDC or
          a tokenized deposit).

INPUTS
    None. All trade parameters are SYNTHETIC and hard-coded below for clarity.
    See the SYNTHETIC_TRADE constant. NO real market, customer, or NAV data
    is used.

OUTPUTS
    1. Console: ordered, step-by-step trace of both settlement flows with
       per-step elapsed time and the role responsible.
    2. timeline.html: an interactive Plotly Gantt-style timeline with two
       swimlanes (Traditional, Tokenized) saved next to this script.
    3. summary.json: machine-readable summary of both flows (used by README
       reviewers and downstream prototypes).

ASSUMPTIONS
    - US-centric T+1 cycle for the traditional MMF, single business day, no
      holidays, no Fedwire cutoff edge cases. Real-world MMFs have multiple
      same-day NAV strikes; we model one strike for clarity.
    - Tokenized leg assumes a permissioned chain where the issuer controls
      mint/burn, an allowlist gates wallet eligibility, and a single atomic
      smart-contract call swaps tokenized cash for shares (true DvP).
    - "Atomic" on-chain settlement is modeled as ~12 seconds (one block on a
      conservative permissioned chain). Faster chains exist; 12s is a safe
      illustration.
    - All timestamps are wall-clock on a single fictional business day
      (2026-04-20) for visual comparison only. They are NOT a forecast.

AUDIT NOTES
    - All synthetic data is labeled SYNTHETIC.
    - No live API calls, no real wallet, no real fund. This is a teaching
      simulation only.
    - Custodian role transformation is annotated inline at the steps where it
      changes between the two flows.

ACRONYMS (spelled out on first use)
    MMF  = Money Market Fund
    NAV  = Net Asset Value (per-share price struck once or several times daily)
    TA   = Transfer Agent (keeps the official register of fund shareholders)
    DvP  = Delivery-versus-Payment (cash and asset move atomically or not at all)
    HITL = Human-In-The-Loop (a human gate inside an automated workflow)
    KYC  = Know-Your-Customer (identity + sanctions + suitability checks)
    MPC  = Multi-Party Computation (key custody without a single private key)
================================================================================
"""

from __future__ import annotations

# --- WHY THESE IMPORTS -------------------------------------------------------
# dataclasses: lightweight, typed records for domain objects (Event, Flow).
# enum:        explicit, grep-able state names instead of raw strings.
# datetime:    wall-clock timestamps; timedelta does the math for elapsed time.
# json:        machine-readable summary so other prototypes can consume it.
# pathlib:     OS-independent file paths; safer than string concatenation.
# pandas:      plotly.express.timeline reads tidy DataFrames natively.
# plotly:      Gantt-style timeline is the native visual for parallel flows.
# -----------------------------------------------------------------------------
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
import json
from pathlib import Path

import pandas as pd
import plotly.express as px


# =============================================================================
# SYNTHETIC TRADE PARAMETERS  (clearly labeled — not real)
# =============================================================================
SYNTHETIC_TRADE = {
    "label": "SYNTHETIC",
    "investor": "ACME Family Office (SYNTHETIC)",
    "fund": "Generic Prime MMF Class I (SYNTHETIC)",
    "shares": 1_000_000,
    "nav_per_share_usd": 1.0000,   # MMFs target a stable $1.00 NAV
    "notional_usd": 1_000_000.00,
    "trade_date": datetime(2026, 4, 20, 9, 0, 0),  # fictional business day
}


# =============================================================================
# DOMAIN MODEL
# =============================================================================
class Flow(str, Enum):
    """Which settlement track an event belongs to."""
    TRADITIONAL = "Traditional MMF (T+1)"
    TOKENIZED = "Tokenized MMF (atomic DvP)"


@dataclass
class Event:
    """
    One step in a settlement workflow.

    Why a dataclass: each event is a small bag of typed fields. A dataclass
    gives us __init__, __repr__, and equality for free. Compare to a dict,
    where every read is a string lookup with no type guarantees.
    """
    flow: Flow
    start: datetime
    duration: timedelta
    actor: str               # who performs this step (broker, TA, custodian...)
    action: str              # what they do
    custodian_role_note: str = ""  # populated only where the role meaningfully shifts

    @property
    def end(self) -> datetime:
        return self.start + self.duration


# =============================================================================
# FLOW 1 — TRADITIONAL MMF, T+1 SETTLEMENT
# =============================================================================
def build_traditional_flow(trade: dict) -> list[Event]:
    """
    Models the conventional US MMF subscription path. Sequence reflects how
    a broker-introduced order to an open-end MMF generally settles T+1:
    order capture -> NAV strike at cutoff -> next-day cash wire -> custodian
    books shares to the investor's account on the TA's register.
    """
    t0 = trade["trade_date"]                   # 09:00 on T+0
    cutoff = t0.replace(hour=16, minute=0)     # 4:00pm ET NAV cutoff
    next_day_open = (t0 + timedelta(days=1)).replace(hour=9, minute=0)

    return [
        Event(
            flow=Flow.TRADITIONAL,
            start=t0,
            duration=timedelta(minutes=1),
            actor="Broker / Order Mgmt System",
            action="Capture investor subscription order",
        ),
        Event(
            flow=Flow.TRADITIONAL,
            start=t0 + timedelta(minutes=1),
            duration=timedelta(minutes=4),
            actor="Broker -> Transfer Agent (TA)",
            action="Route order to TA via NSCC/Fund-SERV message",
        ),
        Event(
            flow=Flow.TRADITIONAL,
            start=t0 + timedelta(minutes=5),
            duration=cutoff - (t0 + timedelta(minutes=5)),
            actor="Investor / Broker",
            action="WAIT for 4:00pm ET NAV cutoff (order accrues during day)",
        ),
        Event(
            flow=Flow.TRADITIONAL,
            start=cutoff,
            duration=timedelta(minutes=90),
            actor="Fund Accountant",
            action="Strike NAV; compute shares = notional / NAV",
        ),
        Event(
            flow=Flow.TRADITIONAL,
            start=cutoff + timedelta(minutes=90),
            duration=timedelta(minutes=30),
            actor="Transfer Agent",
            action="Confirm allotment to broker; instruct custodian",
            custodian_role_note=(
                "TRADITIONAL CUSTODIAN ROLE: receives instruction to expect "
                "cash and to credit shares to the investor's segregated "
                "sub-account once cash lands. Custodian is the operational "
                "settlement counterparty, not just a record-keeper."
            ),
        ),
        Event(
            flow=Flow.TRADITIONAL,
            start=next_day_open,
            duration=timedelta(hours=2),
            actor="Investor's Bank -> Fund Custodian",
            action="Fedwire cash settlement (T+1 morning)",
        ),
        Event(
            flow=Flow.TRADITIONAL,
            start=next_day_open + timedelta(hours=2),
            duration=timedelta(minutes=15),
            actor="Custodian + TA",
            action="Cash matched; shares posted to investor account",
            custodian_role_note=(
                "Custodian and TA reconcile via end-of-day file. Investor's "
                "beneficial ownership exists as an entry on the TA register; "
                "custodian holds cash leg and provides the audit trail."
            ),
        ),
    ]


# =============================================================================
# FLOW 2 — TOKENIZED MMF, ATOMIC DvP ON A PERMISSIONED CHAIN
# =============================================================================
def build_tokenized_flow(trade: dict) -> list[Event]:
    """
    Models a tokenized MMF subscription where the share token and a tokenized
    cash leg (e.g., USDC or a tokenized deposit) settle atomically inside one
    on-chain transaction. The TA function is largely absorbed by the smart
    contract + issuer multisig; the custodian role pivots from settlement
    operator to key/compliance gatekeeper.
    """
    t0 = trade["trade_date"]   # 09:00 on T+0

    return [
        Event(
            flow=Flow.TOKENIZED,
            start=t0,
            duration=timedelta(seconds=2),
            actor="Investor (allowlisted wallet)",
            action="Submit buy intent via portfolio dashboard",
        ),
        Event(
            flow=Flow.TOKENIZED,
            start=t0 + timedelta(seconds=2),
            duration=timedelta(seconds=3),
            actor="Compliance Engine (HITL gate available)",
            action="Verify allowlist, KYC token, jurisdiction, sanctions",
            custodian_role_note=(
                "TOKENIZED CUSTODIAN ROLE STARTS HERE: the qualified custodian "
                "operates / co-signs the wallet via MPC or multisig and is the "
                "compliance enforcement point. No cash movement yet."
            ),
        ),
        Event(
            flow=Flow.TOKENIZED,
            start=t0 + timedelta(seconds=5),
            duration=timedelta(seconds=2),
            actor="Smart Contract",
            action="Escrow tokenized cash (USDC / tokenized deposit)",
        ),
        Event(
            flow=Flow.TOKENIZED,
            start=t0 + timedelta(seconds=7),
            duration=timedelta(seconds=5),
            actor="Issuer Multisig + Smart Contract",
            action="Atomic DvP: mint MMF shares <-> release cash in one tx",
            custodian_role_note=(
                "The transfer-agent function is now the smart contract: the "
                "share register is on-chain. Custodian no longer settles cash "
                "operationally; its role is key custody + compliance + "
                "asset-servicing (corporate actions, distributions)."
            ),
        ),
        Event(
            flow=Flow.TOKENIZED,
            start=t0 + timedelta(seconds=12),
            duration=timedelta(seconds=3),
            actor="Chain Finality + Custodian Recon",
            action="Block finality; custodian reconciles wallet snapshot",
        ),
    ]


# =============================================================================
# REPORTING
# =============================================================================
def print_trace(events: list[Event]) -> None:
    """Console trace, grouped by flow, with elapsed time per step."""
    by_flow: dict[Flow, list[Event]] = {}
    for ev in events:
        by_flow.setdefault(ev.flow, []).append(ev)

    for flow, flow_events in by_flow.items():
        print("\n" + "=" * 78)
        print(f" {flow.value}")
        print("=" * 78)
        flow_start = flow_events[0].start
        flow_end = flow_events[-1].end
        for i, ev in enumerate(flow_events, start=1):
            print(
                f"  [{i:>2}] {ev.start:%Y-%m-%d %H:%M:%S} "
                f"(+{_fmt_delta(ev.duration)})  "
                f"{ev.actor}\n"
                f"        -> {ev.action}"
            )
            if ev.custodian_role_note:
                print(f"        ** CUSTODIAN: {ev.custodian_role_note}")
        total = flow_end - flow_start
        print(f"\n  TOTAL ELAPSED: {_fmt_delta(total)}")


def _fmt_delta(td: timedelta) -> str:
    """Human-friendly timedelta. Why a helper: timedelta.__str__ is ugly."""
    secs = int(td.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    if secs < 86400:
        return f"{secs // 3600}h {(secs % 3600) // 60}m"
    days, rem = divmod(secs, 86400)
    return f"{days}d {rem // 3600}h {(rem % 3600) // 60}m"


def render_timeline(events: list[Event], out_path: Path) -> None:
    """
    Plotly Gantt-style timeline. plotly.express.timeline expects a tidy
    DataFrame with at minimum: start, end, and a categorical y-axis. We use
    Flow as the y-axis swimlane and the actor as the hover detail.
    """
    df = pd.DataFrame(
        [
            {
                "Flow": ev.flow.value,
                "Start": ev.start,
                "End": ev.end,
                "Actor": ev.actor,
                "Action": ev.action,
            }
            for ev in events
        ]
    )

    fig = px.timeline(
        df,
        x_start="Start",
        x_end="End",
        y="Flow",
        color="Actor",
        hover_data=["Action"],
        title=(
            "MMF Settlement: Traditional T+1 vs. Tokenized Atomic DvP "
            "— SYNTHETIC DATA"
        ),
    )
    # Default ordering puts the first row at the bottom; flip it so the
    # Traditional flow reads top-down like a process diagram.
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        xaxis_title="Wall-clock time (single fictional business day)",
        yaxis_title="",
        legend_title="Actor / Role",
        height=520,
    )
    fig.write_html(out_path)


def write_summary(events: list[Event], trade: dict, out_path: Path) -> None:
    """Machine-readable artifact for downstream prototypes / reviewers."""
    by_flow: dict[str, list[Event]] = {}
    for ev in events:
        by_flow.setdefault(ev.flow.value, []).append(ev)

    summary = {
        "data_label": "SYNTHETIC — not for production use",
        "trade": {**trade, "trade_date": trade["trade_date"].isoformat()},
        "flows": {
            name: {
                "start": evs[0].start.isoformat(),
                "end": evs[-1].end.isoformat(),
                "elapsed_seconds": int(
                    (evs[-1].end - evs[0].start).total_seconds()
                ),
                "step_count": len(evs),
                "steps": [
                    {
                        **{k: v for k, v in asdict(e).items()
                           if k not in ("flow", "start", "duration")},
                        "start": e.start.isoformat(),
                        "duration_seconds": int(e.duration.total_seconds()),
                    }
                    for e in evs
                ],
            }
            for name, evs in by_flow.items()
        },
    }
    out_path.write_text(json.dumps(summary, indent=2, default=str))


# =============================================================================
# ENTRY POINT
# =============================================================================
def main() -> None:
    here = Path(__file__).parent
    trad = build_traditional_flow(SYNTHETIC_TRADE)
    tok = build_tokenized_flow(SYNTHETIC_TRADE)
    all_events = trad + tok

    print("\n>>> SYNTHETIC SIMULATION — no real fund, no real money <<<")
    print(f"Investor : {SYNTHETIC_TRADE['investor']}")
    print(f"Fund     : {SYNTHETIC_TRADE['fund']}")
    print(f"Shares   : {SYNTHETIC_TRADE['shares']:,}")
    print(f"Notional : ${SYNTHETIC_TRADE['notional_usd']:,.2f}")

    print_trace(all_events)

    trad_elapsed = trad[-1].end - trad[0].start
    tok_elapsed = tok[-1].end - tok[0].start
    speedup = trad_elapsed.total_seconds() / max(tok_elapsed.total_seconds(), 1)

    print("\n" + "=" * 78)
    print(" HEADLINE COMPARISON")
    print("=" * 78)
    print(f"  Traditional elapsed : {_fmt_delta(trad_elapsed)}")
    print(f"  Tokenized   elapsed : {_fmt_delta(tok_elapsed)}")
    print(f"  Speedup factor      : ~{speedup:,.0f}x faster")
    print("  (Speedup is illustrative only — assumptions in module docstring.)")

    timeline_path = here / "timeline.html"
    summary_path = here / "summary.json"
    render_timeline(all_events, timeline_path)
    write_summary(all_events, SYNTHETIC_TRADE, summary_path)

    print(f"\nWrote: {timeline_path}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
