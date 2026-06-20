"""Signals: market data -> a per-token regime read. Pure, deterministic, unit-testable.

A token is "risk_on" only when short and medium momentum AGREE in sign and realized volatility
is below the configured ceiling. Disagreement or high vol => "risk_off". This conservatism is the
whole point: we would rather miss an entry than take risk into a choppy or falling tape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TokenView:
    symbol: str
    price: float
    pct_1h: Optional[float] = None
    pct_4h: Optional[float] = None
    vol_24h_pct: Optional[float] = None      # realized volatility proxy (abs 24h move, or stdev)
    liquidity_usd: float = 0.0
    spread_bps: float = 0.0
    ts: float = 0.0                          # unix seconds of the quote
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Regime:
    symbol: str
    state: str               # risk_on | neutral | risk_off
    momentum_agree: bool
    direction: int           # +1 up, -1 down, 0 flat
    vol_pct: Optional[float]
    reason: str


def classify(view: TokenView, cfg_signal: dict[str, Any]) -> Regime:
    p1, p4 = view.pct_1h, view.pct_4h
    vol = view.vol_24h_pct
    vmax = float(cfg_signal.get("vol_enter_max_pct", 4.0))

    if p1 is None or p4 is None:
        return Regime(view.symbol, "neutral", False, 0, vol, "missing momentum data")

    s1 = (p1 > 0) - (p1 < 0)
    s4 = (p4 > 0) - (p4 < 0)
    agree = (s1 == s4) and s1 != 0

    if vol is not None and vol >= vmax:
        return Regime(view.symbol, "risk_off", agree, s1 if agree else 0, vol,
                      f"volatility {vol:.1f}% >= {vmax:.1f}% ceiling")

    if not agree:
        return Regime(view.symbol, "neutral", False, 0, vol,
                      f"momentum disagree (1h {p1:+.1f}%, 4h {p4:+.1f}%)")

    if s1 > 0:
        return Regime(view.symbol, "risk_on", True, 1, vol,
                      f"uptrend agrees (1h {p1:+.1f}%, 4h {p4:+.1f}%), vol ok")
    return Regime(view.symbol, "risk_off", True, -1, vol,
                  f"downtrend agrees (1h {p1:+.1f}%, 4h {p4:+.1f}%)")


def rank_entries(views: list[TokenView], cfg_signal: dict[str, Any]) -> list[tuple[TokenView, Regime]]:
    """Risk_on tokens, best (strongest agreeing momentum, lowest vol) first."""
    scored = []
    for v in views:
        r = classify(v, cfg_signal)
        if r.state == "risk_on":
            mom = abs(v.pct_4h or 0) + abs(v.pct_1h or 0)
            vol_pen = (v.vol_24h_pct or 0)
            scored.append((mom - vol_pen, v, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(v, r) for _, v, r in scored]
