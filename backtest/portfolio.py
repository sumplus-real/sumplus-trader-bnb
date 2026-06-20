"""Portfolio accounting for the TRACK-2 backtest.

STDLIB ONLY. Tracks cash (stablecoin) + risky positions, applies realistic
swap costs (fee + slippage), marks-to-market NAV, and maintains the
high-water-mark / running drawdown used by the drawdown ladder.

A `Portfolio` is the only mutable state the strategies see; everything else
passed into `decide(...)` is read-only market data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Default BSC spot-swap economics used throughout the backtest.
# (config/strategy.json sets `default_slippage_bps: 50` for the live agent;
#  the task spec asks for backtest defaults of 25 bps fee / 30 bps slippage,
#  which we honour here. Both strategies pay identical costs -> fair compare.)
DEFAULT_FEE_BPS = 25.0
DEFAULT_SLIPPAGE_BPS = 30.0


@dataclass
class Portfolio:
    """Cash + multi-asset position state with mark-to-market NAV tracking.

    - `cash`                : stablecoin (USDT/USDC) balance, USD.
    - `positions`           : asset -> quantity held (base units).
    - `entry_price`         : asset -> average entry price (for SL/TP).
    - `entry_hour`          : asset -> hour index at last open/add (time-stop).
    - `hwm`                 : high-water-mark of NAV (peak).
    - `nav_history`         : NAV marked at every tick (for metrics).
    - `drawdown_history`    : drawdown % at every tick.
    - `trade_count`         : executed swap counter.
    - `hours_in_market`     : tick counter where any risky position was open.
    """

    initial_cash: float
    cash: float = 0.0
    positions: Dict[str, float] = field(default_factory=dict)
    entry_price: Dict[str, float] = field(default_factory=dict)
    entry_hour: Dict[str, int] = field(default_factory=dict)
    hwm: float = 0.0
    nav_history: List[float] = field(default_factory=list)
    drawdown_history: List[float] = field(default_factory=list)
    trade_count: int = 0
    hours_in_market: int = 0
    # Hour since which the book has been fully flat (no risky positions).
    # The champion's cooldown+rebaseline policy (see champion.py) uses this:
    # once we have held NO risk for a full cooldown, we re-anchor the internal
    # HWM to current NAV so a stale pre-crash peak can't permanently lock us
    # out of the market. (Only affects the *internal* drawdown the ladder
    # sees; `nav_history` -- the equity curve metrics.py reads -- is untouched,
    # so reported max-drawdown stays honest.)
    flat_since: Optional[int] = None

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = self.initial_cash
        self.hwm = self.cash  # first HWM = starting all-cash NAV

    # ------------------------------------------------------------------ NAV
    def nav(self, prices: Dict[str, float]) -> float:
        """Mark-to-market NAV = cash + sum(position_qty * spot)."""
        risky = sum(
            qty * prices.get(asset, 0.0)
            for asset, qty in self.positions.items()
            if qty > 0
        )
        return self.cash + risky

    def risky_value(self, prices: Dict[str, float]) -> float:
        return sum(
            qty * prices.get(asset, 0.0)
            for asset, qty in self.positions.items()
            if qty > 0
        )

    def risky_ratio(self, prices: Dict[str, float]) -> float:
        nav = self.nav(prices)
        return 0.0 if nav <= 0 else self.risky_value(prices) / nav

    # -------------------------------------------------------- HWM / drawdown
    def mark(self, prices: Dict[str, float], hour: int) -> float:
        """Update HWM, append NAV + drawdown histories, return current DD %.

        Drawdown is measured peak-to-now off the high-water-mark, in PERCENT
        (so 4.0 means a 4% drawdown). This matches strategy.json's
        `drawdown_ladder` units and the 6% elimination gate.
        """
        n = self.nav(prices)
        self.nav_history.append(n)
        if n > self.hwm:
            self.hwm = n
        dd_pct = 0.0 if self.hwm <= 0 else (self.hwm - n) / self.hwm * 100.0
        self.drawdown_history.append(dd_pct)
        if self.risky_value(prices) > 1e-9:
            self.hours_in_market += 1
        return dd_pct

    def current_drawdown(self) -> float:
        return self.drawdown_history[-1] if self.drawdown_history else 0.0

    def rebaseline(self, prices: Dict[str, float]) -> None:
        """Reset the internal high-water-mark to the current NAV.

        Used by the champion's cooldown policy AFTER a 4% flatten event: we
        accept the realised loss, declare the drawdown 'resolved' from the
        strategy's POV, and restart risk-management from a fresh baseline.
        NOTE: this only affects the *internal* drawdown the ladder sees; the
        ex-post `nav_history` (used by metrics.py for max_drawdown_pct) is the
        unmodified equity curve, so reported performance drawdown is honest.
        """
        self.hwm = self.nav(prices)
        if self.drawdown_history:
            self.drawdown_history[-1] = 0.0
        self.flat_since = None  # we just re-armed; flat-tracking restarts next tick

    # ------------------------------------------------------------- execution
    def buy(
        self,
        asset: str,
        usd: float,
        price: float,
        hour: int,
        fee_bps: float = DEFAULT_FEE_BPS,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    ) -> float:
        """Spend <= `usd` USD of cash to buy `asset` at `price`.

        Buy fills at WORSE price (higher): price * (1 + slip). Fee is taken
        in cash on the gross notional. Returns USD actually spent (0 if the
        buy was skipped, e.g. insufficient cash).
        """
        if price <= 0 or usd <= 0:
            return 0.0
        gross = min(usd, self.cash)
        if gross <= 0:
            return 0.0
        fill_price = price * (1.0 + slippage_bps / 10000.0)
        fee = gross * fee_bps / 10000.0
        spend = gross  # notional we commit (fee comes out of cash too)
        # Guard: cannot spend more than cash (gross + fee combined)
        if spend + fee > self.cash:
            spend = max(0.0, self.cash - fee)
            if spend <= 0:
                return 0.0
        qty = spend / fill_price
        prev_qty = self.positions.get(asset, 0.0)
        # weighted-average entry price (only over the open, not realised PnL)
        if prev_qty > 0:
            new_qty = prev_qty + qty
            self.entry_price[asset] = (
                self.entry_price[asset] * prev_qty + fill_price * qty
            ) / new_qty
        else:
            self.entry_price[asset] = fill_price
            self.entry_hour[asset] = hour
        self.positions[asset] = prev_qty + qty
        self.cash -= spend + fee
        self.trade_count += 1
        return spend + fee

    def sell(
        self,
        asset: str,
        fraction: float,
        price: float,
        fee_bps: float = DEFAULT_FEE_BPS,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    ) -> float:
        """Sell `fraction` (0..1) of `asset` holdings at `price`.

        Sell fills at WORSE price (lower): price * (1 - slip). Fee deducted
        from proceeds. Returns USD received (0 if nothing to sell).
        """
        qty = self.positions.get(asset, 0.0)
        if qty <= 0 or price <= 0 or fraction <= 0:
            return 0.0
        fraction = min(1.0, fraction)
        sell_qty = qty * fraction
        fill_price = price * (1.0 - slippage_bps / 10000.0)
        gross = sell_qty * fill_price
        fee = gross * fee_bps / 10000.0
        proceeds = gross - fee
        self.positions[asset] = qty - sell_qty
        if self.positions[asset] <= 1e-12:
            self.positions.pop(asset, None)
            self.entry_price.pop(asset, None)
            self.entry_hour.pop(asset, None)
        self.cash += proceeds
        self.trade_count += 1
        return proceeds

    def flatten(
        self,
        prices: Dict[str, float],
        fee_bps: float = DEFAULT_FEE_BPS,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    ) -> int:
        """Liquidate EVERY open position at current prices. Returns # of fills."""
        fills = 0
        for asset in list(self.positions.keys()):
            if self.sell(asset, 1.0, prices[asset], fee_bps, slippage_bps) > 0:
                fills += 1
        return fills


def new_portfolio(initial_cash: float = 10_000.0) -> Portfolio:
    return Portfolio(initial_cash=initial_cash)
