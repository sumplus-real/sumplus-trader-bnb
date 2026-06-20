"""CHALLENGER strategy: the naive DCA / "always-long" baseline.

This mimics the out-of-the-box automation most contestants ship: a dumb bot
that buys a fixed notional on a fixed cadence regardless of regime, with NO
vol filter and NO drawdown control whatsoever.

We deliberately make it *plausible* (the kind of thing a reasonable person
would actually deploy) rather than adversarial: it rotates across the same
universe as the champion and spends a modest, fixed dollar amount per cadence.
It simply never looks at drawdown, momentum, or volatility -- and that single
omission is what walks it through the 6% elimination gate during the crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from champion import Intent, HOLD

# Default naive-DCA parameters.
#   notional_usd : fixed dollar buy each cadence (NOT NAV-scaled => DCA)
#   cadence_h    : hours between buys
#   universe     : rotation list (buys cycle through these)
DEFAULT_CFG = {
    "universe": ["WBNB", "BTCB", "ETH", "CAKE"],
    "notional_usd": 120.0,  # ~1.2% of a 10k starting NAV per buy
    "cadence_h": 6,  # 4 buys/day across the rotation
}


def decide(market_state: dict, portfolio_state, cfg: dict = None) -> Intent:
    """Buy a fixed notional of the next asset in the rotation, on cadence."""
    cfg = cfg or DEFAULT_CFG
    universe: List[str] = cfg["universe"]
    notional: float = cfg["notional_usd"]
    cadence: int = cfg["cadence_h"]
    hour: int = market_state["t"]

    # Only act on cadence. (hour==0 reserved: nothing to buy into yet.)
    if hour == 0 or cadence <= 0 or hour % cadence != 0:
        return HOLD

    # Rotate strictly by hour so the asset choice is deterministic and even.
    asset = universe[(hour // cadence) % len(universe)]

    # Skip if we're out of cash (naive bot doesn't manage cash -> just idle).
    if portfolio_state.cash < notional:
        return HOLD

    return Intent("buy", asset, notional, f"dca:{asset}@${notional:.0f}/{cadence}h")
