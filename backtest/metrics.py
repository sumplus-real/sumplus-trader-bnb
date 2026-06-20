"""Performance metrics for the TRACK-2 backtest. All pure functions, STDLIB ONLY.

Conventions:
    - `nav_history` : list of NAV values sampled once per hour.
    - periods_per_year for hourly sampling = 24 * 365 = 8760.
    - Sharpe is annualised as (mean/std) * sqrt(periods_per_year), risk-free=0.
      (The annualisation factor is identical for both strategies since they
      share the same horizon, so cross-strategy Sharpe comparisons are fair
      even though the absolute annualised number is window-sensitive.)
    - Calmar is PERIOD-based here: total_return_pct / max_drawdown_pct over the
      window. We deliberately do NOT annualise return for Calmar, because
      annualising a 6-week window yields absurd figures (e.g. +840%/yr) that
      obscure the actual competition outcome. Period-Calmar is the relevant
      risk-adjusted measure for a sub-annual, drawdown-gated contest.
    - All drawdown / return figures are in PERCENT.
"""

from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional, Tuple

PERIODS_PER_YEAR = 24 * 365  # hourly sampling


def _period_returns(nav_history: List[float]) -> List[float]:
    """Simple net returns r[t] = nav[t]/nav[t-1] - 1."""
    return [
        (nav_history[i] / nav_history[i - 1] - 1.0)
        for i in range(1, len(nav_history))
        if nav_history[i - 1] > 0
    ]


def total_return_pct(nav_history: List[float]) -> float:
    """(final/initial - 1) * 100."""
    if len(nav_history) < 2 or nav_history[0] <= 0:
        return 0.0
    return (nav_history[-1] / nav_history[0] - 1.0) * 100.0


def max_drawdown_pct(nav_history: List[float]) -> float:
    """Largest peak-to-trough drop on the NAV curve, in PERCENT."""
    hwm = -math.inf
    max_dd = 0.0
    for n in nav_history:
        if n > hwm:
            hwm = n
        if hwm > 0:
            dd = (hwm - n) / hwm * 100.0
            if dd > max_dd:
                max_dd = dd
    return max_dd


def sharpe(nav_history: List[float], periods_per_year: int = PERIODS_PER_YEAR) -> float:
    """Annualised Sharpe (rf=0) from period returns. 0.0 if undefined."""
    rets = _period_returns(nav_history)
    if len(rets) < 2:
        return 0.0
    mu = statistics.fmean(rets)
    sd = statistics.pstdev(rets)
    if sd <= 0:
        return 0.0
    return (mu / sd) * math.sqrt(periods_per_year)


def calmar(nav_history: List[float]) -> float:
    """Period Calmar = total_return_pct / max_drawdown_pct.

    Positive when the strategy made money; negative when it lost. Larger is
    better. Returns 0.0 when there was no drawdown.
    """
    mdd = max_drawdown_pct(nav_history)
    if mdd <= 0:
        return 0.0
    return total_return_pct(nav_history) / mdd


def first_breach_hour(drawdown_history: List[float], gate_pct: float) -> Optional[int]:
    """Hour index of the first tick where drawdown >= `gate_pct`, else None."""
    for h, dd in enumerate(drawdown_history):
        if dd >= gate_pct:
            return h
    return None


def metrics_from_nav(nav_history: List[float]) -> Dict[str, float]:
    """Core return/drawdown/risk-adjusted metrics from a NAV slice."""
    return {
        "total_return_pct": round(total_return_pct(nav_history), 4),
        "max_drawdown_pct": round(max_drawdown_pct(nav_history), 4),
        "sharpe": round(sharpe(nav_history), 4),
        "calmar": round(calmar(nav_history), 4),
    }


def all_metrics(
    portfolio, nav_history: List[float], total_hours: int
) -> Dict[str, float]:
    """Full metric bundle including trade-count and time-in-market."""
    m = metrics_from_nav(nav_history)
    m["trade_count"] = getattr(portfolio, "trade_count", 0)
    in_mkt = getattr(portfolio, "hours_in_market", 0)
    m["pct_time_in_market"] = (
        round(in_mkt / total_hours * 100.0, 4) if total_hours > 0 else 0.0
    )
    return m
