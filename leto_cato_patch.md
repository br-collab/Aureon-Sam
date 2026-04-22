# Leto — Cato Gate Tile: server.py Patch

Two insertion points. No existing lines change. No new deps.

---

## Insertion 1 — Cache + health dep (after line 164, inside the HEALTH dict block)

Add `"cato_gate"` to the `HEALTH` dict:

```python
# existing lines 159-165:
HEALTH: dict[str, DepStatus] = {
    "railway":     DepStatus(name="Railway Prod",   tier=1),
    "kraken_rest": DepStatus(name="Kraken REST",    tier=1),
    "kraken_auth": DepStatus(name="Kraken Auth",    tier=1),
    "github":      DepStatus(name="GitHub",         tier=2),
    "dsor_volume": DepStatus(name="DSOR Archive",   tier=3),
    # ADD THIS LINE:
    "cato_gate":   DepStatus(name="Cato Gate",      tier=3),
}
```

---

## Insertion 2 — Cache + check function + route (insert after line 288, before the CHECKS list)

```python
# ── Cato gate — 60s cache, Tier-3 health dep ──────────────────────

_cato_gate_cache: dict = {"ts": 0.0, "payload": None}
_CATO_GATE_TTL = 60.0  # seconds


def _check_cato_gate() -> None:
    """Poll Railway /api/cato/gate. Tier-3: informational, never blocks trading."""
    s = HEALTH["cato_gate"]
    s.last_checked = _now_iso()
    now = time.time()
    # Only re-hit Railway if cache is stale; otherwise classify from cached payload.
    if _cato_gate_cache["payload"] is None or (now - _cato_gate_cache["ts"]) >= _CATO_GATE_TTL:
        t0 = time.time()
        code, payload = _railway_request("GET", "/api/cato/gate", timeout=6.0)
        s.latency_ms = int((time.time() - t0) * 1000)
        if code == 200 and isinstance(payload, dict) and "gate_decision" in payload:
            _cato_gate_cache["payload"] = payload
            _cato_gate_cache["ts"] = now
            s.status = "UP"
            s.last_ok = _now_iso()
            s.detail = payload.get("gate_decision", "UNKNOWN")
        else:
            s.status = "DOWN"
            s.detail = f"HTTP {code}" if code != 200 else "unexpected payload shape"
    else:
        # Cache still fresh — status is whatever last check set.
        pass
```

---

## Insertion 3 — Update CHECKS list (line 291-297)

```python
CHECKS = [
    _check_railway,
    _check_kraken_rest,
    _check_kraken_auth,
    _check_github,
    _check_dsor_volume,
    _check_cato_gate,       # ADD THIS LINE
]
```

---

## Insertion 4 — Route (insert after /api/dsor/archive/<n> route, before Sam command surface block ~line 581)

```python
# ── Cato gate proxy ────────────────────────────────────────────────

@app.route("/api/cato/gate")
def api_cato_gate():
    """
    Proxy to Railway /api/cato/gate with 60s local cache.
    Returns cached payload with stale flag if Railway is DOWN.
    Never blocks — Tier-3 informational only.
    """
    now = time.time()
    cache_age = now - _cato_gate_cache["ts"] if _cato_gate_cache["ts"] else None
    if _cato_gate_cache["payload"] is None or (cache_age is not None and cache_age >= _CATO_GATE_TTL):
        code, payload = _railway_request("GET", "/api/cato/gate", timeout=6.0)
        if code == 200 and isinstance(payload, dict) and "gate_decision" in payload:
            _cato_gate_cache["payload"] = payload
            _cato_gate_cache["ts"] = now
            cache_age = 0.0
        else:
            if _cato_gate_cache["payload"] is None:
                return jsonify({"error": f"Cato gate unavailable (HTTP {code})", "stale": True}), 502
            # Fall through to serve stale cache below.

    payload = _cato_gate_cache["payload"]
    return jsonify({
        **payload,
        "stale": (cache_age is not None and cache_age > 90),
        "cache_age_s": int(cache_age) if cache_age is not None else None,
        "leto_ts": _now_iso(),
    })


@app.route("/api/cato/settlement-context")
def api_cato_settlement_context():
    code, payload = _railway_request("GET", "/api/cato/settlement-context", timeout=6.0)
    return jsonify(payload), code


@app.route("/api/cato/compare-rails")
def api_cato_compare_rails():
    code, payload = _railway_request("GET", "/api/cato/compare-rails", timeout=6.0)
    return jsonify(payload), code


@app.route("/api/cato/multichain-gas")
def api_cato_multichain_gas():
    code, payload = _railway_request("GET", "/api/cato/multichain-gas", timeout=6.0)
    return jsonify(payload), code


@app.route("/api/cato/prices")
def api_cato_prices():
    code, payload = _railway_request("GET", "/api/cato/prices", timeout=6.0)
    return jsonify(payload), code
```

> Note: Only `/api/cato/gate` gets the cache + stale logic. The other four are
> pass-through — Railway already caches them internally. Add caching to those
> only if you see latency problems in practice.

---

## index.html — Cato Gate tile

Add this tile inside the System Health panel, alongside the existing 5 dep tiles.
Exact placement: after the `dsor_volume` dep card, before the closing `</div>` of the health grid.

```html
<!-- Cato Gate tile — polls /api/cato/gate every 60s -->
<div class="dep-card" id="dep-cato_gate">
  <div class="dep-header">
    <span class="dep-name">Cato Gate</span>
    <span class="dep-badge tier3">T3</span>
  </div>
  <div class="dep-status">
    <span id="cato-decision-badge" class="gate-badge unknown">—</span>
    <span id="cato-chain" class="dep-detail">loading…</span>
  </div>
  <div class="dep-sub">
    OFR stress: <span id="cato-ofr">—</span>
    &nbsp;|&nbsp;
    SOFR Δ: <span id="cato-sofr">—</span>
  </div>
  <div class="dep-sub" id="cato-stale-row" style="display:none; color: var(--warn);">
    ⚠ stale
  </div>
  <div class="dep-ts">checked <span id="cato-ts">—</span></div>
</div>
```

CSS additions (in `<style>` block):

```css
.gate-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 3px;
  font-weight: 700;
  font-size: 0.8rem;
  letter-spacing: 0.05em;
}
.gate-badge.proceed  { background: var(--green);  color: #000; }
.gate-badge.hold     { background: var(--amber);  color: #000; }
.gate-badge.escalate { background: var(--red);    color: #fff; }
.gate-badge.unknown  { background: var(--muted);  color: #fff; }
```

JS additions — add `fetchCatoGate()` call and the function itself:

```javascript
// In your polling init block, add:
fetchCatoGate();
setInterval(fetchCatoGate, 60000);   // 60s — matches server cache TTL

function fetchCatoGate() {
  fetch('/api/cato/gate')
    .then(r => r.json())
    .then(d => {
      const decision = (d.gate_decision || 'UNKNOWN').toUpperCase();
      const badge = document.getElementById('cato-decision-badge');
      badge.textContent = decision;
      badge.className = 'gate-badge ' + {
        'PROCEED': 'proceed',
        'HOLD': 'hold',
        'ESCALATE': 'escalate'
      }[decision] || 'unknown';

      document.getElementById('cato-chain').textContent =
        d.recommended_chain ? '→ ' + d.recommended_chain : '';

      const inputs = d.inputs || {};
      document.getElementById('cato-ofr').textContent =
        inputs.ofr_stress != null ? inputs.ofr_stress : '—';

      const sofr = inputs.sofr_delta_bps;
      document.getElementById('cato-sofr').textContent =
        sofr != null ? sofr + ' bps' : '— (null)';   // honest: shows null, not zero

      const staleRow = document.getElementById('cato-stale-row');
      staleRow.style.display = d.stale ? 'block' : 'none';

      document.getElementById('cato-ts').textContent =
        d.leto_ts ? new Date(d.leto_ts).toLocaleTimeString() : '—';
    })
    .catch(err => {
      document.getElementById('cato-decision-badge').className = 'gate-badge unknown';
      document.getElementById('cato-decision-badge').textContent = 'ERR';
      document.getElementById('cato-chain').textContent = err.message || 'fetch failed';
    });
}
```

---

## README.md addition — Endpoint table

Add these rows to the endpoint reference table:

| `/api/cato/gate`             | GET | Cato Verana L0 gate — 60s cached proxy (PROCEED/HOLD/ESCALATE) |
| `/api/cato/settlement-context` | GET | Pass-through: settlement posture summary |
| `/api/cato/compare-rails`    | GET | Pass-through: rail comparison |
| `/api/cato/multichain-gas`   | GET | Pass-through: gas across chains |
| `/api/cato/prices`           | GET | Pass-through: CoinGecko price snapshot |

And add `Cato Gate` row to the Health Monitor tier table:

| 3 | Cato Gate | `/api/cato/gate` < 6s | Informational; doesn't block trading |

---

## Dispatch context — optional addition

If you want Sam's situational awareness to include the Cato gate state,
add this block to `_gather_dispatch_context()` in server.py (after the DSOR block):

```python
try:
    if _cato_gate_cache["payload"]:
        ctx["cato_gate"] = {
            "decision": _cato_gate_cache["payload"].get("gate_decision"),
            "recommended_chain": _cato_gate_cache["payload"].get("recommended_chain"),
            "settlement_posture": (_cato_gate_cache["payload"].get("inputs") or {}).get("settlement_posture"),
            "cache_age_s": int(time.time() - _cato_gate_cache["ts"]) if _cato_gate_cache["ts"] else None,
        }
except Exception:
    pass
```

This is a 5-line addition. Worth doing — Sam answering "is now a good time to
open a session?" should know the Cato posture without a separate fetch.

---

## Commit message

```
feat(leto): add Cato gate tile — Verana L0 macro read in dashboard

- HEALTH["cato_gate"] dep added (Tier-3, informational)
- _check_cato_gate() joins health loop; 60s Railway proxy cache
- /api/cato/gate route: cached proxy with stale flag at 90s
- /api/cato/{settlement-context,compare-rails,multichain-gas,prices}: pass-throughs
- index.html: PROCEED/HOLD/ESCALATE badge tile in System Health panel
- SOFR delta shown as "— (null)" when null — honest per first_cato_gate_call.md
- Sam dispatch context gains cato_gate block
- README: endpoint table + health tier table updated
```
