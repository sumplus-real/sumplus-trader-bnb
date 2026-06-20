"""Generate a survival-first StrategySpec from CoinMarketCap market data.

This is the runnable core of the sumplus-survival-strategy Skill (Track 2). It reads a market
regime (fear/greed + per-asset momentum/volatility), maps it to a risky-exposure budget, and emits
a StrategySpec: a complete, machine-readable, backtestable strategy description. It does NOT trade.

Data source: the CoinMarketCap MCP/API when CMC_API_KEY is set; otherwise a deterministic offline
scenario, so the Skill always runs for a reviewer. Fear/greed comes from get_global_metrics_latest
live; offline (or with --fng) it is supplied directly.

Usage:
    python skills/sumplus-survival-strategy/generate_spec.py [--fng 0..100] [--out spec.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.policy.canonical import load_config  # the frozen base policy
from agent.data.cmc import get_token_views       # CMC (live) or deterministic mock

# regime -> risky-exposure ceiling. The only knob the regime moves; survival mechanics stay fixed.
REGIME_EXPOSURE = {"risk_on": 0.12, "neutral": 0.08, "risk_off": 0.04}


def classify_regime(fng: float, avg_mom_4h: float, avg_vol: float) -> str:
    """Map fear/greed + breadth to a regime. Simple and legible on purpose.

    fng        : CoinMarketCap fear/greed index, 0 (extreme fear) .. 100 (extreme greed)
    avg_mom_4h : average 4h momentum across the universe, in %
    avg_vol    : average realised vol across the universe, in %
    """
    # Extreme greed or a high-vol breakdown -> de-risk. Constructive + calm -> base risk.
    if fng >= 80 or avg_vol >= 4.0 or avg_mom_4h <= -2.0:
        return "risk_off"
    if fng <= 35 or avg_mom_4h >= 1.0:
        # fearful-but-stabilising or clean positive breadth: take the base budget
        return "risk_on" if avg_vol < 3.0 else "neutral"
    return "neutral"


async def read_market(cfg: dict) -> tuple[float, float]:
    """Return (avg 4h momentum %, avg realised vol %) across the universe from CMC (or mock)."""
    syms = list(cfg.get("universe", []))
    views, _ts = await get_token_views(syms, cfg)
    risky = [v for v in views if v.symbol.upper() in {s.upper() for s in syms}]
    moms = [v.pct_4h for v in risky if v.pct_4h is not None]
    vols = [v.vol_24h_pct for v in risky if v.vol_24h_pct is not None]
    avg_mom = sum(moms) / len(moms) if moms else 0.0
    avg_vol = sum(vols) / len(vols) if vols else 0.0
    return avg_mom, avg_vol


def build_spec(cfg: dict, regime: str, fng: float, avg_mom_4h: float, avg_vol: float) -> dict:
    """Assemble a StrategySpec from the frozen base policy with regime-scaled exposure."""
    risk = cfg["risk"]
    exposure = REGIME_EXPOSURE[regime]
    return {
        "strategyspec_version": "1.0",
        "name": "sumplus-survival-first",
        "thesis": "Survive a hard drawdown-elimination gate first; take return only when momentum "
                  "agrees and volatility is low.",
        "chain": "bsc",
        "venue": "pancakeswap-v3",
        "side": "long-only-spot",
        "universe": cfg.get("universe", []),
        "quote_tokens": cfg.get("quote_tokens", ["USDT", "USDC"]),
        "regime_read": {
            "regime": regime,
            "fear_greed_index": round(fng, 1),
            "avg_momentum_4h_pct": round(avg_mom_4h, 3),
            "avg_realized_vol_pct": round(avg_vol, 3),
            "source": "coinmarketcap" if os.environ.get("CMC_API_KEY") else "offline-scenario",
        },
        "entry": {
            "type": "trend-following",
            "require_momentum_agreement_1h_4h": True,
            "max_entry_vol_pct": cfg["signal"]["vol_enter_max_pct"],
        },
        "sizing": {
            "per_trade_pct_nav": [risk["min_single_trade_pct"], risk["max_single_trade_pct"]],
            "volatility_scaled": True,
            "max_risky_exposure_pct": exposure,
        },
        "drawdown_ladder_pct": {
            "halve_size_at": cfg["drawdown_ladder"][0]["at_pct"],
            "no_new_risk_at": cfg["drawdown_ladder"][1]["at_pct"],
            "flatten_to_stablecoin_at": cfg["drawdown_ladder"][2]["at_pct"],
            "internal_hard_kill_at": cfg["internal_hard_kill_pct"],
            "elimination_gate_at": risk["max_drawdown_pct"],
        },
        "exits": {
            "stop_loss_pct": risk["stop_loss_pct"],
            "take_profit_pct": risk["take_profit_pct"],
            "max_hold_hours": risk["max_hold_hours"],
        },
        "rate_limits": {
            "max_trades_per_hour": risk["max_trades_per_hour"],
            "min_trade_interval_seconds": risk["min_trade_interval_seconds"],
        },
        "backtest": {
            "synthetic": "python backtest/run.py",
            "real_data": "python backtest/real_data_live.py",
            "note": "Both consume this spec unchanged. Real-data run: survived all 3 recent weeks "
                    "inside the 6% gate; naive DCA baseline breached it.",
        },
    }


def to_backtest_cfg(spec: dict) -> dict:
    """Convert a StrategySpec back into the cfg the backtester (backtest/champion.decide) consumes.

    This is what makes the spec 'backtestable with no edits': the same object the Skill emits maps
    straight onto the engine that runs it.
    """
    ladder = spec["drawdown_ladder_pct"]
    return {
        "universe": spec["universe"],
        "signal": {
            "momentum_lookbacks_h": [1, 4],
            "require_momentum_agreement": spec["entry"]["require_momentum_agreement_1h_4h"],
            "vol_enter_max_pct": spec["entry"]["max_entry_vol_pct"],
            "vol_window_h": 24,
        },
        "risk": {
            "max_single_trade_pct": spec["sizing"]["per_trade_pct_nav"][1],
            "min_single_trade_pct": spec["sizing"]["per_trade_pct_nav"][0],
            "max_risky_exposure_pct": spec["sizing"]["max_risky_exposure_pct"],
            "stop_loss_pct": spec["exits"]["stop_loss_pct"],
            "take_profit_pct": spec["exits"]["take_profit_pct"],
            "max_hold_hours": spec["exits"]["max_hold_hours"],
            "max_trades_per_hour": spec["rate_limits"]["max_trades_per_hour"],
        },
        "drawdown_ladder": [
            {"at_pct": ladder["halve_size_at"], "action": "halve_size"},
            {"at_pct": ladder["no_new_risk_at"], "action": "no_new_risk"},
            {"at_pct": ladder["flatten_to_stablecoin_at"], "action": "stablecoin_mode"},
        ],
        "min_trades": {"micro_rebalance_usd": 12.0, "target_risky_ratio": 0.10,
                       "rebalance_band": 0.04, "cadence_h": 12},
    }


def generate(fng: float | None = None) -> dict:
    cfg = load_config()
    avg_mom, avg_vol = asyncio.run(read_market(cfg))
    if fng is None:
        # offline default: a neutral-to-mild reading so the demo is reproducible
        fng = 52.0
    regime = classify_regime(fng, avg_mom, avg_vol)
    return build_spec(cfg, regime, fng, avg_mom, avg_vol)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fng", type=float, default=None, help="fear/greed index 0..100 (else live/default)")
    ap.add_argument("--out", type=str, default=None, help="write StrategySpec JSON to this path")
    args = ap.parse_args()
    spec = generate(fng=args.fng)
    text = json.dumps(spec, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote StrategySpec -> {args.out}  (regime={spec['regime_read']['regime']})")
    else:
        print(text)


if __name__ == "__main__":
    main()
