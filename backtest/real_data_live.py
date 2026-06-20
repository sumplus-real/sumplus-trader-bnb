"""Real-data backtest driving the ACTUAL live pipeline (agent/core.tick) on recent weeks.

real_data.py uses the champion *reference* impl (glm's), which micro-rebalances every 12h and so
over-trades vs the real agent. This script drives the EXACT live brain instead: agent.core.tick ->
survival.decide + PolicyEngine + the frozen config/strategy.json. Receipt/abstention writes are
redirected to a temp dir so the committed demo data is never touched. Same real Binance hourly
data, same three recent weeks. This is the faithful answer to "does what we commit survive on the
actual market, and how much does it really trade?".

Usage: python backtest/real_data_live.py [YYYY-MM-DD end-date, default today]
"""
from __future__ import annotations

import asyncio
import os
import sys
import json
import tempfile
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from real_data import _fetch_hourly, BINANCE, WARMUP_H, WEEK_H, GATE_DD_PCT
import real_data
import champion
from challenger import DEFAULT_CFG as CHALLENGER_CFG

from agent import core
from agent.simulate import _views_at
from agent.policy.canonical import load_config
from agent.policy.receipt import ReceiptChain as _RC
from agent.abstention.ledger import AbstentionLedger as _AL

INITIAL_NAV = 500.0


def _redirect_side_effects(tmpdir: str):
    """Point core.tick's receipt + abstention writes at a throwaway dir."""
    core.ReceiptChain = lambda: _RC(os.path.join(tmpdir, "receipts.jsonl"))
    core.AbstentionLedger = lambda: _AL(os.path.join(tmpdir, "abstentions.jsonl"))


def _run_week_live(series: dict, lo: int, hi: int, cfg: dict, base_ts: float) -> dict:
    state = {"nav": INITIAL_NAV, "stable_usd": INITIAL_NAV, "high_water_mark": INITIAL_NAV,
             "positions": {}, "trades_this_week": 0, "last_trade_ts": 0, "trades_last_hour": 0}
    max_dd = 0.0
    breach_hour = None
    for h in range(lo, hi):
        now_ts = base_ts + h * 3600
        market = _views_at(series, h, now_ts, cfg)
        price = {v.symbol.upper(): v.price for v in market[0]}
        _result, state = asyncio.run(core.tick(state=state, executor=None, cfg=cfg,
                                               now_ts=now_ts, market=market))
        nav = core.mark_nav(state, price)
        hwm = state["high_water_mark"]
        dd = (hwm - nav) / hwm * 100 if hwm > 0 else 0.0
        max_dd = max(max_dd, dd)
        if breach_hour is None and dd >= GATE_DD_PCT:
            breach_hour = h - lo
    final_nav = core.mark_nav(state, price)
    return {"return_pct": round((final_nav / INITIAL_NAV - 1) * 100, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "breached_gate": breach_hour is not None, "breach_hour": breach_hour,
            "trades": int(state.get("trades_this_week", 0))}


def main() -> dict:
    if len(sys.argv) > 1:
        end = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    import calendar
    fetch_start = end - timedelta(hours=WARMUP_H + 3 * WEEK_H)
    start_ms = calendar.timegm(fetch_start.timetuple()) * 1000
    end_ms = calendar.timegm(end.timetuple()) * 1000
    base_ts = float(calendar.timegm(fetch_start.timetuple()))

    # fetch + align
    raw = {}
    n = None
    for sym, bsym in BINANCE.items():
        s = _fetch_hourly(bsym, start_ms, end_ms)
        raw[sym] = s
        n = len(s) if n is None else min(n, len(s))
    # series format expected by _views_at: {sym: [(ts, price), ...]}
    series = {sym: [(base_ts + i * 3600, raw[sym][i]) for i in range(n)] for sym in raw}
    prices_per_asset = {sym: [p for _, p in series[sym]] for sym in series}  # for challenger harness

    cfg = load_config()  # the frozen committed policy

    weeks = []
    for i in range(3):
        lo = WARMUP_H + i * WEEK_H
        hi = min(lo + WEEK_H, n)
        lbl = (f"{(fetch_start + timedelta(hours=lo)).strftime('%m-%d')}->"
               f"{(fetch_start + timedelta(hours=hi)).strftime('%m-%d')}")
        weeks.append((lbl, lo, hi))

    print("\n" + "=" * 74)
    print(" REAL-DATA BACKTEST (LIVE PIPELINE): frozen policy, 3 recent weeks".center(74))
    print(f" agent.core.tick + survival.decide + config/strategy.json | {n} hourly bars".center(74))
    print(" data: Binance hourly closes | WBNB<-BNB BTCB<-BTC ETH CAKE".center(74))
    print("=" * 74)
    sep = "+" + "-" * 15 + "+" + "-" * 9 + "+" + "-" * 9 + "+" + "-" * 11 + "+" + "-" * 8 + "+"
    print(sep)
    print(f"| {'week':<13} | {'ret%':>7} | {'maxDD%':>7} | {'gate':>9} | {'trades':>6} |")
    print(sep.replace("-", "="))

    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for label, lo, hi in weeks:
            wk_dir = os.path.join(tmp, label.replace("->", "_"))
            os.makedirs(wk_dir, exist_ok=True)
            _redirect_side_effects(wk_dir)
            r = _run_week_live(series, lo, hi, cfg, base_ts)
            r["week"] = label
            status = f"BREACH@{r['breach_hour']}" if r["breached_gate"] else "SURVIVE"
            print(f"| {label:<13} | {r['return_pct']:>7.2f} | {r['max_drawdown_pct']:>7.2f} | "
                  f"{status:>9} | {r['trades']:>6} |")
            out.append(r)
    print(sep)

    # naive DCA challenger on the most recent week, for contrast (champion-harness execution)
    label, lo, hi = weeks[-1]
    chal_pf = real_data._run_week(__import__("challenger").decide, prices_per_asset, lo, hi, CHALLENGER_CFG)
    from metrics import all_metrics, first_breach_hour
    cm = all_metrics(chal_pf, chal_pf.nav_history, hi - lo)
    cb = first_breach_hour(chal_pf.drawdown_history, GATE_DD_PCT)
    print(f"\n  contrast, most recent week ({label}), naive DCA challenger:")
    print(f"    return {cm['total_return_pct']:+.2f}%  maxDD {cm['max_drawdown_pct']:.2f}%  "
          f"{'BREACH@'+str(cb) if cb is not None else 'survive'}  trades {cm['trade_count']}")

    survived = sum(1 for w in out if not w["breached_gate"])
    worst = max(w["max_drawdown_pct"] for w in out)
    print(f"\n  VERDICT: live policy survived {survived}/3 weeks inside the {GATE_DD_PCT}% gate. "
          f"worst-week maxDD = {worst:.2f}%.")
    print("  (these are the EXACT rules whose hash we commit on-chain.)\n")

    result = {"source": "binance hourly, live pipeline", "gate_pct": GATE_DD_PCT,
              "initial_nav": INITIAL_NAV, "weeks": out}
    with open(os.path.join(_HERE, "results_real_live.json"), "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    return result


if __name__ == "__main__":
    main()
