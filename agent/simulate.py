"""Drive the REAL decision pipeline over a synthetic week — honest evidence + rich demo data.

The simulator feeds a deterministic synthetic price series (with a calm uptrend, chop, a sharp
crash, and recovery) into the exact same core.tick used live: same strategy, same Maria policy,
same hash-chained receipts, same abstention ledger. It proves the committed strategy survives a
crash (the drawdown ladder engages and we never breach the 6% gate) and populates receipts.jsonl
+ abstentions.jsonl + sim_equity.jsonl so the dashboard has a full week to show.
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

from agent.policy.canonical import load_config
from agent.strategy.signals import TokenView
from agent import core
from agent.data.cmc import X402_RECEIPTS_PATH, _log_x402

ROOT = Path(__file__).resolve().parent.parent
EQUITY_PATH = ROOT / "sim_equity.jsonl"


def _views_at(series: dict[str, list], h: int, now_ts: float, cfg: dict) -> tuple[list[TokenView], float]:
    views: list[TokenView] = []
    for sym in cfg.get("universe", []):
        path = series.get(sym)
        if not path:
            continue
        price = path[h][1]
        p1 = path[h - 1][1] if h >= 1 else price
        p4 = path[h - 4][1] if h >= 4 else price
        rets = [(path[i][1] / path[i - 1][1] - 1.0) for i in range(max(1, h - 23), h + 1)]
        vol = statistics.pstdev(rets) * 100 if len(rets) > 1 else 0.0
        views.append(TokenView(
            symbol=sym, price=price,
            pct_1h=(price / p1 - 1) * 100, pct_4h=(price / p4 - 1) * 100,
            vol_24h_pct=vol, ts=now_ts,
        ))
    for q in cfg.get("quote_tokens", ["USDT", "USDC"]):
        views.append(TokenView(symbol=q, price=1.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=0.05, ts=now_ts))
    return views, now_ts


async def simulate(*, weeks: float = 1.0, step_hours: int = 2, nav0: float = 500.0,
                   seed: int = 20260622, reset: bool = True, base_ts: float | None = None) -> dict[str, Any]:
    from backtest.data import generate_synthetic_prices  # glm's regime generator

    cfg = load_config()
    base_ts = base_ts or 1750550400.0  # fixed: 2026-06-22T00:00:00Z, deterministic timestamps
    hours = int(weeks * 7 * 24)
    series = generate_synthetic_prices(seed=seed, hours=hours + 5)

    if reset:
        for p in (core.ReceiptChain().path, core.AbstentionLedger().path, EQUITY_PATH, X402_RECEIPTS_PATH):
            Path(p).unlink(missing_ok=True)

    fetch_symbols = list(cfg.get("universe", [])) + list(cfg.get("quote_tokens", ["USDT", "USDC"]))

    state: dict[str, Any] = {"nav": nav0, "stable_usd": nav0, "high_water_mark": nav0,
                             "positions": {}, "trades_this_week": 0, "last_trade_ts": 0,
                             "trades_last_hour": 0}
    max_dd = 0.0
    breached = False
    eq_lines = []
    for h in range(4, hours, step_hours):
        now_ts = base_ts + h * 3600
        # one CMC data fetch per decision cycle -> one x402 paid-data receipt (deterministic ts)
        _log_x402({"ts": now_ts, "provider": "coinmarketcap", "endpoint": "mock/quotes",
                   "symbols": fetch_symbols, "price_usdc": 0.01, "network": "base", "mode": "simulated"})
        market = _views_at(series, h, now_ts, cfg)
        price = {v.symbol.upper(): v.price for v in market[0]}
        # rate-limit context: count executes in the last hour from the receipt tail is overkill in sim;
        # approximate via last_trade_ts spacing already enforced by the strategy/policy.
        result, state = await core.tick(state=state, executor=None, cfg=cfg, now_ts=now_ts, market=market)
        nav = core.mark_nav(state, price)
        hwm = state["high_water_mark"]
        dd = (hwm - nav) / hwm * 100 if hwm > 0 else 0.0
        max_dd = max(max_dd, dd)
        if dd >= cfg["risk"]["max_drawdown_pct"]:
            breached = True
        risky_usd = sum(p["qty"] * price.get(s.upper(), p["entry_price"])
                        for s, p in (state.get("positions") or {}).items())
        from agent.strategy.signals import rank_entries
        regime = "risk_on" if rank_entries(market[0], cfg.get("signal", {})) else "risk_off"
        eq_lines.append(json.dumps({"ts": now_ts, "nav": round(nav, 2), "drawdown_pct": round(dd, 3),
                                    "risky_exposure_pct": round(risky_usd / nav * 100, 2) if nav else 0,
                                    "regime": regime, "action": result.intent_action,
                                    "verdict": result.verdict, "rung": result.ladder_rung}))
    EQUITY_PATH.write_text("\n".join(eq_lines) + "\n")

    final_nav = state["nav"]
    return {
        "weeks": weeks, "ticks": len(eq_lines),
        "nav0": nav0, "final_nav": round(final_nav, 2),
        "return_pct": round((final_nav / nav0 - 1) * 100, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "gate_pct": cfg["risk"]["max_drawdown_pct"],
        "breached_gate": breached,
        "trades": int(state.get("trades_this_week", 0)),
    }


def main() -> None:
    import sys
    weeks = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    summary = asyncio.run(simulate(weeks=weeks))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
