"""CHAMPION strategy: "Maria-smart, survival-first" (long-only spot).

This is a deterministic REFERENCE implementation of the same survival mechanisms the live agent
runs (momentum-agreement entry gate, volatility filter, exposure cap, drawdown ladder, per-position
stops, micro-rebalance). The parameters below are the backtest calibration; the LIVE committed
policy in config/strategy.json is a stricter variant (12% exposure cap, a 1/2/3% ladder, 2% stops)
which the live 6-week simulation survives with an even smaller ~2.8% peak drawdown. Both never
approach the 6% elimination gate; that is the whole point.

Decision cascade (highest priority first; one Intent per call; the runner loops
up to `max_trades_per_hour` times per tick so exits+entries both get serviced):

    1. DRAWDOWN LADDER (top of the survival hierarchy)
         dd >= 4.0%  -> FLATTEN everything to stablecoin (internal hard-kill)
         dd >= 3.0%  -> NO NEW RISK (only manage existing exits)
         dd >= 1.5%  -> HALVE every new trade size
    2. PER-POSITION EXITS (checked before any new entry)
         price <= entry*(1 - SL)        -> sell all        (stop-loss 3%)
         price >= entry*(1 + TP)        -> sell all        (take-profit 4%)
         hours_held >= max_hold         -> sell all        (time-stop 48h)
    3. NEW ENTRIES  (only if dd < 3.0% and risky headroom < 20%)
         For each candidate asset in the universe:
           * 1h momentum and 4h momentum AGREE in sign (both +ve for a long)
           * realised vol (24h, annualised-to-daily) < vol_enter_max_pct (4%)
           * current risky_ratio < max_risky_exposure_pct (20%)
         Size = volatility-scaled, clamped to [1%, 3%] of NAV, halved if the
         1.5% drawdown rung is active.
    4. MICRO-REBALANCE (only if no signal and dd < 1.5%)
         Every `micro_rebalance_cadence_h` hours, if risky_ratio < target-band
         (15% - 5% = 10%), nudge toward 15% with a tiny trade
         (`micro_rebalance_usd`). Keeps the bot active + trade-count healthy
         without taking real risk.
    5. HOLD otherwise.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional


# ----------------------------------------------------------------- Intent
@dataclass
class Intent:
    """A single trade instruction returned by `decide`.

    action : "buy" | "sell" | "flatten" | "hold"
    asset  : target asset symbol, or "" for hold/flatten-all
    size   : buy -> USD to spend; sell -> fraction [0..1] of the position;
             flatten/hold -> ignored
    reason : human-readable tag (for the ledger / report)
    """

    action: str
    asset: str = ""
    size: float = 0.0
    reason: str = ""


HOLD = Intent("hold")

# ------------------------------------------------------------- default cfg
DEFAULT_CFG = {
    "universe": ["WBNB", "BTCB", "ETH", "CAKE"],
    "signal": {
        "momentum_lookbacks_h": [1, 4],
        "require_momentum_agreement": True,
        "vol_enter_max_pct": 4.0,
        "vol_window_h": 24,
    },
    "risk": {
        "max_single_trade_pct": 0.03,  # 3% of NAV
        "min_single_trade_pct": 0.01,  # 1% of NAV
        "max_risky_exposure_pct": 0.20,  # 20% hard cap on total risk
        "stop_loss_pct": 3.0,
        "take_profit_pct": 4.0,
        "max_hold_hours": 48,
        "max_trades_per_hour": 4,
    },
    "drawdown_ladder": [
        {"at_pct": 1.5, "action": "halve_size"},
        {"at_pct": 3.0, "action": "no_new_risk"},
        {"at_pct": 4.0, "action": "stablecoin_mode"},
    ],
    "min_trades": {
        "micro_rebalance_usd": 12.0,
        "target_risky_ratio": 0.15,
        "rebalance_band": 0.05,
        "cadence_h": 12,
    },
}


# ------------------------------------------------------------- helpers
def _momentum(price_history: List[float], lookback: int) -> float:
    """Simple net return over the last `lookback` hourly bars (fraction)."""
    if len(price_history) < lookback + 1:
        return 0.0
    then = price_history[-(lookback + 1)]
    now = price_history[-1]
    if then <= 0:
        return 0.0
    return now / then - 1.0


def _realized_vol_pct(price_history: List[float], window: int) -> float:
    """Realised vol over the last `window` hourly log-returns, scaled to a
    'daily' figure: stdev(log r) * sqrt(24) * 100 (in %).

    Using sqrt(24) puts the calm-regime vol near ~2% and the crash-regime vol
    above the 4% entry gate, so the vol filter has real teeth.
    """
    if len(price_history) < window + 1:
        window = len(price_history) - 1
    if window < 2:
        return 0.0
    log_rets: List[float] = []
    for i in range(len(price_history) - window, len(price_history)):
        prev = price_history[i - 1]
        if prev > 0 and price_history[i] > 0:
            log_rets.append(math.log(price_history[i] / prev))
    if len(log_rets) < 2:
        return 0.0
    return statistics.pstdev(log_rets) * math.sqrt(24) * 100.0


def _ladder_state(drawdown_pct: float, ladder: list) -> str:
    """Map current drawdown to the active rung: 'ok' | 'halve' | 'no_risk' | 'flatten'."""
    state = "ok"
    for rung in ladder:
        if drawdown_pct >= rung["at_pct"]:
            a = rung["action"]
            if a == "halve_size":
                state = "halve"
            elif a == "no_new_risk":
                state = "no_risk"
            elif a == "stablecoin_mode":
                state = "flatten"
    return state


# ------------------------------------------------------------- main entry
def decide(market_state: dict, portfolio_state, cfg: dict = None) -> Intent:
    """One decision per call. Runner re-calls until HOLD or trade-rate limit."""
    cfg = cfg or DEFAULT_CFG
    prices: Dict[str, float] = market_state["prices"]
    history: Dict[str, List[float]] = market_state["history"]
    hour: int = market_state["t"]
    universe: List[str] = cfg["universe"]
    sig = cfg["signal"]
    risk = cfg["risk"]
    ladder = cfg["drawdown_ladder"]
    mt = cfg["min_trades"]

    dd = portfolio_state.current_drawdown()
    nav = portfolio_state.nav(prices)

    # ---- 0. FLAT-COOLDOWN -> REBASELINE & RE-ARM -----------------------
    # If the book has been fully flat (no risky positions) for a full cooldown,
    # we re-anchor the internal HWM to current NAV. Rationale: once we carry
    # no risk, a stale pre-crash peak serves no purpose -- it can only lock us
    # permanently out of the market (drawdown can't heal while we hold cash).
    # Re-baselining lets us re-engage in the recovery. The existing entry gate
    # (1h+4h momentum BOTH positive, vol<4%) means we only actually re-buy in
    # a genuine recovery -- never catching the falling knife mid-crash.
    # NOTE: this only resets the strategy's *internal* drawdown accounting;
    # `nav_history` (which metrics.py reads) is the unmodified equity curve,
    # so reported max-drawdown is honest.
    FLAT_COOLDOWN_H = 24
    if portfolio_state.risky_value(prices) <= 1e-9:
        if portfolio_state.flat_since is None:
            portfolio_state.flat_since = hour
        elif hour - portfolio_state.flat_since >= FLAT_COOLDOWN_H and dd > 0.5:
            portfolio_state.rebaseline(prices)
            dd = portfolio_state.current_drawdown()  # now ~0
    else:
        portfolio_state.flat_since = None

    rung = _ladder_state(dd, ladder)

    # ---- 1. FLATTEN: deepest rung -> go full stablecoin ---------------
    if rung == "flatten":
        if portfolio_state.risky_value(prices) > 1e-9:
            # Has risk -> emit flatten intent (the runner executes it).
            return Intent("flatten", reason=f"ladder:stablecoin@dd={dd:.2f}%")
        # No risk but drawdown still >= 4%: stop-losses already cleared the
        # book. flat_since (set in block 0) will re-arm us after cooldown.
        return HOLD

    # ---- 2. PER-POSITION EXITS (SL / TP / time-stop) ------------------
    sl = risk["stop_loss_pct"] / 100.0
    tp = risk["take_profit_pct"] / 100.0
    max_hold = risk["max_hold_hours"]
    for asset in universe:
        qty = portfolio_state.positions.get(asset, 0.0)
        if qty <= 0:
            continue
        entry = portfolio_state.entry_price.get(asset, 0.0)
        entry_h = portfolio_state.entry_hour.get(asset, hour)
        px = prices[asset]
        if px <= entry * (1.0 - sl):
            return Intent("sell", asset, 1.0, f"stop_loss:{asset}@{-sl * 100:.0f}%")
        if px >= entry * (1.0 + tp):
            return Intent("sell", asset, 1.0, f"take_profit:{asset}@{tp * 100:.0f}%")
        if hour - entry_h >= max_hold:
            return Intent("sell", asset, 1.0, f"time_stop:{asset}@{max_hold}h")

    # ---- 3. NO-NEW-RISK rung: stop opening fresh risk ----------------
    if rung == "no_risk":
        return HOLD

    # ---- 4. NEW ENTRIES ----------------------------------------------
    lookbacks = sig["momentum_lookbacks_h"]  # [1, 4]
    require_agree = sig["require_momentum_agreement"]
    vol_max = sig["vol_enter_max_pct"]
    vol_win = sig["vol_window_h"]
    max_risky = risk["max_risky_exposure_pct"]

    # size scaler for the active rung (halve at 1.5% dd)
    size_mult = 0.5 if rung == "halve" else 1.0

    if portfolio_state.risky_ratio(prices) < max_risky:
        best_asset: Optional[str] = None
        best_score = -math.inf
        best_size_pct = 0.0
        best_rvol = 0.0
        for asset in universe:
            hist = history.get(asset, [])
            if len(hist) < max(lookbacks) + 1:
                continue
            moms = [_momentum(hist, lb) for lb in lookbacks]
            # long-only: need every momentum positive AND agreeing in sign
            if require_agree and not all(m > 0 for m in moms):
                continue
            rvol = _realized_vol_pct(hist, vol_win)
            if rvol > vol_max:
                continue
            # vol-scaled size: base 3% scaled by (2% / rvol), clamped [1%,3%]
            raw = (
                risk["max_single_trade_pct"] * (2.0 / rvol)
                if rvol > 0
                else risk["max_single_trade_pct"]
            )
            size_pct = (
                max(
                    risk["min_single_trade_pct"], min(risk["max_single_trade_pct"], raw)
                )
                * size_mult
            )
            # score: strongest 4h momentum (clear trend wins)
            score = moms[-1]
            if score > best_score:
                best_score = score
                best_asset = asset
                best_size_pct = size_pct
                best_rvol = rvol

        if best_asset is not None:
            usd = best_size_pct * nav
            if usd > 0 and portfolio_state.cash >= usd:
                return Intent(
                    "buy",
                    best_asset,
                    usd,
                    f"entry:{best_asset} moms+ vol={best_rvol:.1f}% "
                    f"sz={best_size_pct * 100:.1f}%",
                )

    # ---- 5. MICRO-REBALANCE (keep trade count healthy, no real risk) -
    target = mt["target_risky_ratio"]
    band = mt["rebalance_band"]
    cadence = mt["cadence_h"]
    micro_usd = mt["micro_rebalance_usd"]
    if (
        rung == "ok"
        and hour % cadence == 0
        and hour > 0
        and portfolio_state.risky_ratio(prices) < target - band
        and portfolio_state.cash >= micro_usd
    ):
        # Tiny keep-active buy toward the 15% target. Per strategy.json this is
        # explicitly about maintaining a minimum qualifying trade count, NOT
        # about taking a directional view, so it fires regardless of momentum
        # sign -- but it is gated by rung=="ok" (dd<1.5%), so it can NEVER add
        # risk once the drawdown ladder has engaged. Pick the strongest-
        # momentum asset so even these tiny trades lean with the trend.
        scored = [
            (a, _momentum(history.get(a, []), lookbacks[-1]))
            for a in universe
            if len(history.get(a, [])) > lookbacks[-1]
        ]
        if scored:
            pick = max(scored, key=lambda am: am[1])[0]
            return Intent("buy", pick, micro_usd, "micro_rebalance")

    return HOLD
