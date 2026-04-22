"""
PURPOSE
    Reconcile overnight Kraken state for Thifur-H after the 2026-04-19 live
    test. Railway restarted overnight; session_state is null; 2 of 6 stops
    fired per DSOR. We need ground truth from Kraken: XBT balance, open
    orders, trades since the test opened.

INPUTS
    aureon-leto/.env  -> KRAKEN_API_KEY, KRAKEN_API_SECRET
    window_start_utc: 2026-04-20 01:51:00 UTC (first ORDER_PLACED minus 1m)

OUTPUTS
    stdout: balance summary, open-orders count, trade ledger with side/qty/
    price/fee/txid, net residual XBT, implied USD exposure at current ticker.

ASSUMPTIONS
    Kraken nonce = int(time.time() * 1000) is fine for this account.
    Trade rows include 'type' ('buy'/'sell'), 'pair', 'vol', 'price',
    'fee', 'cost', 'time' (unix float), 'ordertxid'.
    BUY = entry. SELL = close (auto-stop or auto-sell). Residual XBT = sum
    of BUY vol minus sum of SELL vol over the window.

AUDIT NOTES
    Read-only. No order placement. No cancellation. Safe to run any time.
    Hits private endpoints Balance, OpenOrders, TradesHistory.
"""

import base64
import hashlib
import hmac
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path


ENV_PATH = Path(
    "/Users/guillermoravelo/Desktop/Programming for Fun + Other local Projects"
    "/Project Aureon/Programing/The Grid 3/aureon-leto/.env"
)
WINDOW_START_UNIX = 1776016260  # 2026-04-20 01:51:00 UTC (covers all entries)


def load_env(path: Path) -> dict:
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class KrakenDirect:
    BASE_URL = "https://api.kraken.com"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _sign(self, uri_path: str, data: dict) -> str:
        encoded = urllib.parse.urlencode(data).encode()
        sha = hashlib.sha256(data["nonce"].encode() + encoded).digest()
        secret = base64.b64decode(self.api_secret)
        mac = hmac.new(secret, uri_path.encode() + sha, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode()

    def _post(self, uri_path: str, data: dict | None = None, timeout: float = 10.0) -> dict:
        data = dict(data or {})
        data["nonce"] = str(int(time.time() * 1000))
        sig = self._sign(uri_path, data)
        req = urllib.request.Request(
            self.BASE_URL + uri_path,
            data=urllib.parse.urlencode(data).encode(),
            headers={
                "API-Key": self.api_key,
                "API-Sign": sig,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": [f"{type(e).__name__}: {e}"], "result": {}}

    def get_public(self, uri_path: str, timeout: float = 5.0) -> dict:
        try:
            with urllib.request.urlopen(self.BASE_URL + uri_path, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            return {"error": [f"{type(e).__name__}: {e}"], "result": {}}


def main():
    env = load_env(ENV_PATH)
    k = KrakenDirect(env["KRAKEN_API_KEY"], env["KRAKEN_API_SECRET"])

    print("=== RECONCILE KRAKEN STATE — 2026-04-20 ET ===\n")

    bal = k._post("/0/private/Balance")
    if bal.get("error"):
        print(f"BALANCE ERROR: {bal['error']}")
        return
    result = bal.get("result", {})
    print("BALANCES (non-zero):")
    for asset, qty in sorted(result.items()):
        q = float(qty)
        if q > 0:
            print(f"  {asset:12s} {q:.8f}")
    print()

    xbt_qty = float(result.get("XXBT", 0) or result.get("XBT", 0) or 0)
    zusd_qty = float(result.get("ZUSD", 0) or result.get("USD", 0) or 0)

    oo = k._post("/0/private/OpenOrders")
    open_orders = oo.get("result", {}).get("open", {}) or {}
    print(f"OPEN ORDERS: {len(open_orders)}")
    for txid, o in open_orders.items():
        d = o.get("descr", {})
        print(f"  {txid}  {d.get('type')} {o.get('vol')} {d.get('pair')} @ {d.get('price')}  status={o.get('status')}")
    print()

    th = k._post("/0/private/TradesHistory", {"start": str(WINDOW_START_UNIX)})
    trades = th.get("result", {}).get("trades", {}) or {}
    print(f"TRADES SINCE {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(WINDOW_START_UNIX))}: {len(trades)}\n")

    buys_vol = 0.0
    sells_vol = 0.0
    buys_cost = 0.0
    sells_cost = 0.0
    total_fee = 0.0
    rows = []
    for txid, t in trades.items():
        side = t.get("type")
        vol = float(t.get("vol", 0))
        price = float(t.get("price", 0))
        cost = float(t.get("cost", 0))
        fee = float(t.get("fee", 0))
        ts = float(t.get("time", 0))
        pair = t.get("pair", "")
        ordertxid = t.get("ordertxid", "")
        rows.append((ts, side, vol, price, cost, fee, pair, ordertxid, txid))
        if side == "buy":
            buys_vol += vol
            buys_cost += cost
        else:
            sells_vol += vol
            sells_cost += cost
        total_fee += fee

    rows.sort()
    print(f"{'TIME (ET)':20s} {'SIDE':4s} {'VOL':>12s} {'PRICE':>10s} {'COST':>10s} {'FEE':>8s}  ORDERTXID")
    for ts, side, vol, price, cost, fee, pair, ordertxid, txid in rows:
        et = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        print(f"{et:20s} {side:4s} {vol:12.8f} {price:10.1f} {cost:10.4f} {fee:8.4f}  {ordertxid}")
    print()

    residual_xbt = buys_vol - sells_vol
    ticker = k.get_public("/0/public/Ticker?pair=XBTUSD")
    last_price = None
    tres = ticker.get("result", {})
    if tres:
        first = next(iter(tres.values()))
        last_price = float(first.get("c", [0])[0])

    print("=== SUMMARY ===")
    print(f"Trades in window:    {len(trades)} ({int(buys_vol/max(1e-12,buys_vol/max(1,sum(1 for r in rows if r[1]=='buy'))))*0 + sum(1 for r in rows if r[1]=='buy')} buys, {sum(1 for r in rows if r[1]=='sell')} sells)")
    print(f"Total bought (XBT):  {buys_vol:.8f}   cost_usd={buys_cost:.4f}")
    print(f"Total sold   (XBT):  {sells_vol:.8f}   proceeds_usd={sells_cost:.4f}")
    print(f"Total fees (USD):    {total_fee:.4f}")
    print(f"Residual XBT:        {residual_xbt:.8f}")
    if last_price:
        print(f"XBT last:            ${last_price:,.2f}")
        print(f"Residual USD expo:   ${residual_xbt * last_price:,.4f}")
        realized = sells_cost - (buys_cost * (sells_vol / buys_vol)) if buys_vol > 0 else 0
        print(f"Implied realized:    ${realized:.4f} (pre-fee proportional)")
    print(f"\nSnapshot balances:   XBT={xbt_qty:.8f}  ZUSD=${zusd_qty:.4f}")


if __name__ == "__main__":
    main()
