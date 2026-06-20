"""Real-data backtest: run the LIVE committed policy over three recent calendar weeks.

Unlike run.py (synthetic regimes, for the head-to-head narrative), this pulls REAL hourly
prices for the four-asset universe from Binance's public market-data endpoint
(data-api.binance.vision, no key, no geo-block) and runs the champion strategy with the
*live committed parameters* (config/strategy.json: 12% exposure cap, 1/2/3% drawdown ladder,
3% internal kill, 2% stops, 1-2.5% sizing). It answers a blunt question: on the actual recent
market, does the strategy we are about to commit on-chain stay inside the 6% elimination gate?

WBNB<-BNBUSDT, BTCB<-BTCUSDT, ETH<-ETHUSDT, CAKE<-CAKEUSDT (the BSC tokens track these majors).

Usage: python backtest/real_data.py [YYYY-MM-DD end-date, default today]
"""
from __future__ import annotations

import calendar
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import httpx

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import champion
import challenger
from challenger import DEFAULT_CFG as CHALLENGER_CFG
from portfolio import Portfolio, DEFAULT_FEE_BPS, DEFAULT_SLIPPAGE_BPS, new_portfolio
from metrics import all_metrics, first_breach_hour

# Live committed parameters, mirrored from config/strategy.json (the hash we commit on-chain).
LIVE_CFG = {
    "universe": ["WBNB", "BTCB", "ETH", "CAKE"],
    "signal": {
        "momentum_lookbacks_h": [1, 4],
        "require_momentum_agreement": True,
        "vol_enter_max_pct": 4.0,
        "vol_window_h": 24,
    },
    "risk": {
        "max_single_trade_pct": 0.025,
        "min_single_trade_pct": 0.01,
        "max_risky_exposure_pct": 0.12,
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,
        "max_hold_hours": 48,
        "max_trades_per_hour": 4,
    },
    "drawdown_ladder": [
        {"at_pct": 1.0, "action": "halve_size"},
        {"at_pct": 2.0, "action": "no_new_risk"},
        {"at_pct": 3.0, "action": "stablecoin_mode"},
    ],
    "min_trades": {
        "micro_rebalance_usd": 12.0,
        "target_risky_ratio": 0.10,
        "rebalance_band": 0.04,
        "cadence_h": 12,
    },
}

BINANCE = {"WBNB": "BNBUSDT", "BTCB": "BTCUSDT", "ETH": "ETHUSDT", "CAKE": "CAKEUSDT"}
GATE_DD_PCT = 6.0
INITIAL_NAV = 500.0
FEE_BPS = DEFAULT_FEE_BPS
SLIP_BPS = DEFAULT_SLIPPAGE_BPS
MAX_TRADES_PER_HOUR = 4
WARMUP_H = 24          # extra hours fetched before the oldest week for momentum/vol lookback
WEEK_H = 168           # 7 * 24


def _fetch_hourly(symbol: str, start_ms: int, end_ms: int) -> List[float]:
    """Return hourly close prices for [start_ms, end_ms) from Binance public data."""
    url = "https://data-api.binance.vision/api/v3/klines"
    out: List[float] = []
    cur = start_ms
    with httpx.Client(timeout=30) as c:
        while cur < end_ms:
            r = c.get(url, params={"symbol": symbol, "interval": "1h",
                                   "startTime": cur, "endTime": end_ms, "limit": 1000})
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            for row in rows:
                out.append(float(row[4]))  # close
            cur = rows[-1][0] + 3_600_000   # next hour after last openTime
            if len(rows) < 1000:
                break
    return out


def _run_week(decide_fn, prices_per_asset: Dict[str, List[float]], lo: int, hi: int,
              cfg: dict) -> Portfolio:
    """Fresh portfolio; trade hours [lo, hi); history has full prior lookback."""
    pf = new_portfolio(INITIAL_NAV)
    for h in range(lo, hi):
        prices = {a: prices_per_asset[a][h] for a in prices_per_asset}
        history = {a: prices_per_asset[a][: h + 1] for a in prices_per_asset}
        market_state = {"t": h, "prices": prices, "history": history}
        for _ in range(MAX_TRADES_PER_HOUR):
            intent = decide_fn(market_state, pf, cfg)
            if intent.action == "hold":
                break
            ok = False
            if intent.action == "buy":
                ok = pf.buy(intent.asset, intent.size, prices[intent.asset], h, FEE_BPS, SLIP_BPS) > 0
            elif intent.action == "sell":
                ok = pf.sell(intent.asset, intent.size, prices[intent.asset], FEE_BPS, SLIP_BPS) > 0
            elif intent.action == "flatten":
                ok = pf.flatten(prices, FEE_BPS, SLIP_BPS) > 0
            if not ok:
                break
        pf.mark(prices, h)
    return pf


def main() -> dict:
    # End date defaults to today (UTC midnight). Three prior calendar weeks before it.
    if len(sys.argv) > 1:
        end = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        now = datetime.now(timezone.utc)
        end = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    fetch_start = end - timedelta(hours=WARMUP_H + 3 * WEEK_H)
    start_ms = calendar.timegm(fetch_start.timetuple()) * 1000
    end_ms = calendar.timegm(end.timetuple()) * 1000

    prices_per_asset: Dict[str, List[float]] = {}
    n = None
    for sym, bsym in BINANCE.items():
        series = _fetch_hourly(bsym, start_ms, end_ms)
        prices_per_asset[sym] = series
        n = len(series) if n is None else min(n, len(series))
    # align lengths (exchanges can return an off-by-one)
    for sym in prices_per_asset:
        prices_per_asset[sym] = prices_per_asset[sym][:n]

    # week boundaries inside the aligned array; oldest first
    weeks = []
    for i in range(3):
        lo = WARMUP_H + i * WEEK_H
        hi = lo + WEEK_H
        if hi > n:
            hi = n
        lbl_lo = (fetch_start + timedelta(hours=lo)).strftime("%m-%d")
        lbl_hi = (fetch_start + timedelta(hours=hi)).strftime("%m-%d")
        weeks.append((f"{lbl_lo}->{lbl_hi}", lo, hi))

    print("\n" + "=" * 74)
    print(" REAL-DATA BACKTEST: live committed policy on 3 recent weeks".center(74))
    print(f" source: Binance hourly closes | {n} bars | gate {GATE_DD_PCT}% | "
          f"start NAV ${INITIAL_NAV:.0f}".center(74))
    print("=" * 74)
    hdr = f"| {'week':<13} | {'ret%':>7} | {'maxDD%':>7} | {'gate':>9} | {'trades':>6} | {'Sharpe':>7} |"
    sep = "+" + "-" * 15 + "+" + "-" * 9 + "+" + "-" * 9 + "+" + "-" * 11 + "+" + "-" * 8 + "+" + "-" * 9 + "+"
    print(sep); print(hdr); print(sep.replace("-", "="))

    out_weeks = []
    for label, lo, hi in weeks:
        champ = _run_week(champion.decide, prices_per_asset, lo, hi, LIVE_CFG)
        m = all_metrics(champ, champ.nav_history, hi - lo)
        breach = first_breach_hour(champ.drawdown_history, GATE_DD_PCT)
        status = f"BREACH@{breach}" if breach is not None else "SURVIVE"
        print(f"| {label:<13} | {m['total_return_pct']:>7.2f} | {m['max_drawdown_pct']:>7.2f} | "
              f"{status:>9} | {m['trade_count']:>6} | {m['sharpe']:>7.2f} |")
        out_weeks.append({"week": label, "return_pct": m["total_return_pct"],
                          "max_drawdown_pct": m["max_drawdown_pct"],
                          "breached_gate": breach is not None, "breach_hour": breach,
                          "trades": m["trade_count"], "sharpe": m["sharpe"]})
    print(sep)

    # challenger (naive DCA) on the most recent week for contrast
    label, lo, hi = weeks[-1]
    chal = _run_week(challenger.decide, prices_per_asset, lo, hi, CHALLENGER_CFG)
    cm = all_metrics(chal, chal.nav_history, hi - lo)
    cbreach = first_breach_hour(chal.drawdown_history, GATE_DD_PCT)
    print(f"\n  contrast, most recent week ({label}), naive DCA challenger:")
    print(f"    return {cm['total_return_pct']:+.2f}%  maxDD {cm['max_drawdown_pct']:.2f}%  "
          f"{'BREACH@'+str(cbreach) if cbreach is not None else 'survive'}  trades {cm['trade_count']}")

    survived = sum(1 for w in out_weeks if not w["breached_gate"])
    print(f"\n  VERDICT: champion survived {survived}/3 weeks inside the {GATE_DD_PCT}% gate. "
          f"worst week maxDD = {max(w['max_drawdown_pct'] for w in out_weeks):.2f}%.\n")

    result = {"source": "binance hourly", "gate_pct": GATE_DD_PCT, "initial_nav": INITIAL_NAV,
              "weeks": out_weeks,
              "challenger_recent_week": {"week": label, "return_pct": cm["total_return_pct"],
                                         "max_drawdown_pct": cm["max_drawdown_pct"],
                                         "breached_gate": cbreach is not None, "trades": cm["trade_count"]}}
    with open(os.path.join(_HERE, "results_real.json"), "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=True)
    return result


if __name__ == "__main__":
    main()
