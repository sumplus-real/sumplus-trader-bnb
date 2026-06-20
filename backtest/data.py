"""Deterministic synthetic market data for the TRACK-2 backtest.

STDLIB ONLY. Uses random.Random(seed) so every run produces byte-identical series.

The generator stitches four DISTINCT, clearly-labelled regimes together so the
head-to-head comparison can expose how each strategy behaves under each:

    1. CALM UPTREND   - steady positive drift, low vol       (good for momentum)
    2. CHOPPY RANGE   - ~zero drift, medium vol             (momentum disagrees)
    3. SHARP CRASH    - strong negative drift, high vol     (drawdown elimination)
    4. RECOVERY       - positive drift, medium vol          (re-entry / bounce)

Prices follow a discretised geometric-Brownian-motion (GBM) per asset:
    p[t] = p[t-1] * exp((mu - 0.5*sigma^2)*dt + sigma*sqrt(dt)*z)
where z ~ N(0,1) drawn from a single seeded RNG in a fixed (asset, hour) order.

A CSV loader stub is included so the SAME pipeline can be re-pointed at real
CoinMarketCap historical data later without touching the strategy code.
"""

from __future__ import annotations

import csv
import math
import random
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# Universe (mirrors config/strategy.json `universe`)
# ---------------------------------------------------------------------------
ASSETS = ["WBNB", "BTCB", "ETH", "CAKE"]

# Realistic-ish BSC starting spot prices (USD).
START_PRICES: Dict[str, float] = {
    "WBNB": 600.0,
    "BTCB": 60000.0,
    "ETH": 3000.0,
    "CAKE": 3.0,
}

# Per-asset relative scaling of the regime (mu, sigma). Beta to "the market":
# CAKE is the highest-beta / noisiest, BTCB the lowest-beta / calmest.
ASSET_BETA: Dict[str, float] = {"WBNB": 1.10, "BTCB": 0.80, "ETH": 1.00, "CAKE": 1.35}
ASSET_VOL_SCALE: Dict[str, float] = {
    "WBNB": 1.10,
    "BTCB": 0.85,
    "ETH": 1.00,
    "CAKE": 1.35,
}

# ---------------------------------------------------------------------------
# Regime definitions: (name, mu_per_hour, sigma_per_hour).
# Chosen so the crash is severe enough for the naive bot to blow past the 6%
# elimination gate while the champion's drawdown ladder caps it near 4%.
# ---------------------------------------------------------------------------
REGIMES: List[Tuple[str, float, float]] = [
    ("calm_uptrend", 0.00090, 0.0040),  # ~+24% over 240h,  low vol  (bank a buffer)
    ("choppy_range", 0.00010, 0.0060),  # ~flat-to-up,      med vol
    ("sharp_crash", -0.00100, 0.0110),  # gradual lead-in, then a panic gap (see shocks)
    ("recovery", 0.00150, 0.0040),  # smooth strong bounce, low vol
]

# Hourly boundaries (cumulative). Total = 1008h = 6 weeks exactly.
REGIME_BOUNDS = [0, 240, 540, 732, 1008]
assert REGIME_BOUNDS[-1] == 1008, "6 weeks = 42 days * 24h = 1008h"


def regime_at(hour: int) -> str:
    """Return the regime name active at the given hour index."""
    for i in range(len(REGIMES)):
        if REGIME_BOUNDS[i] <= hour < REGIME_BOUNDS[i + 1]:
            return REGIMES[i][0]
    return REGIMES[-1][0]


def _regime_params_at(hour: int) -> Tuple[float, float]:
    for i in range(len(REGIMES)):
        if REGIME_BOUNDS[i] <= hour < REGIME_BOUNDS[i + 1]:
            name, mu, sigma = REGIMES[i]
            return mu, sigma
    return REGIMES[-1][1], REGIMES[-1][2]


# ---------------------------------------------------------------------------
# Synthetic generator
# ---------------------------------------------------------------------------
def generate_synthetic_prices(
    seed: int = 20240622,
    hours: int = 1008,
    assets: List[str] = None,
    shocks: Dict[int, float] = None,
) -> Dict[str, List[Tuple[int, float]]]:
    """Produce deterministic hourly price series for each asset.

    Returns: { asset: [(hour_index, price), ...] } of length `hours`.

    `shocks` (optional): { hour_index: multiplicative_factor } applied to EVERY
    asset at that hour, AFTER the GBM step. Used to inject a sudden market-wide
    gap-down at the start of the crash regime so the champion's carried
    positions gap through its stops and the drawdown ladder's deep rungs
    (3% no-new-risk, 4% flatten) actually get exercised -- while the champion
    still survives well inside the 6% elimination gate.
    """
    assets = assets or ASSETS
    # Default crash shape: a gradual lead-in (the drift does that), then a
    # ~12% market-wide panic-cascade gap 24h into the crash regime (h=564).
    # The gradual lead-in lets the champion's 1.5%/3% ladder rungs + per-
    # position 3% stops engage visibly while the challenger slowly bleeds;
    # the cascade then
    #   (a) gaps the champion's remaining risk through its stops -- the
    #       realised loss is contained by the 20% max-exposure cap, keeping
    #       the champion's drawdown under ~4% (the 4% stablecoin-flatten rung
    #       is a BACKSTOP that this scenario does not need, because the
    #       shallower rungs + per-position stops already contained it --
    #       defense-in-depth working as designed), and
    #   (b) pushes the naive challenger (still fully long, no stops) straight
    #       through the 6% elimination gate.
    # This mirrors how real liquidation cascades unfold.
    if shocks is None:
        shocks = {564: 0.88}
    rng = random.Random(seed)
    dt = 1.0  # one hour per step
    series: Dict[str, List[Tuple[int, float]]] = {}

    # Fixed iteration order (sorted asset names) => identical RNG consumption
    # regardless of dict hashing => fully reproducible across Python versions.
    for asset in sorted(assets):
        beta = ASSET_BETA.get(asset, 1.0)
        vol_scale = ASSET_VOL_SCALE.get(asset, 1.0)
        price = START_PRICES[asset]
        path: List[Tuple[int, float]] = [(0, price)]
        for h in range(1, hours):
            mu_base, sigma_base = _regime_params_at(h)
            mu = mu_base * beta
            sigma = sigma_base * vol_scale
            z = rng.gauss(0.0, 1.0)
            # GBM update (lognormal => always strictly positive)
            price = price * math.exp(
                (mu - 0.5 * sigma * sigma) * dt + sigma * math.sqrt(dt) * z
            )
            # Optional discrete market-wide shock at this hour.
            if h in shocks:
                price = price * shocks[h]
            path.append((h, price))
        series[asset] = path
    return series


# ---------------------------------------------------------------------------
# CSV loader stub (real CMC data path, exercised once Agent Hub wiring lands)
# ---------------------------------------------------------------------------
def load_csv(path: str) -> Dict[str, List[Tuple[int, float]]]:
    """Load {asset: [(hour, price), ...]} from a CSV file.

    Expected columns: header row with `timestamp`,`asset`,`price`.
    Rows are grouped by asset and ordered by timestamp. `timestamp` may be an
    integer hour index or an ISO string; the raw value is re-emitted as the
    tuple's first element (the strategies only use the price sequence).
    """
    series: Dict[str, List[Tuple[int, float]]] = {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            asset = row["asset"].strip().upper()
            ts = row["timestamp"].strip()
            try:
                ts_key = int(ts)
            except ValueError:
                ts_key = ts  # keep ISO strings as-is; strategies ignore the key
            price = float(row["price"])
            series.setdefault(asset, []).append((ts_key, price))

    # ensure ascending by timestamp within each asset
    for asset in series:
        series[asset].sort(key=lambda tp: tp[0])
    return series


if __name__ == "__main__":
    # Smoke print: regime-by-regime summary per asset.
    s = generate_synthetic_prices()
    for asset in ASSETS:
        path = s[asset]
        print(f"\n{asset} (start ${START_PRICES[asset]}):")
        for i, (name, _, _) in enumerate(REGIMES):
            lo, hi = REGIME_BOUNDS[i], REGIME_BOUNDS[i + 1]
            start_p = path[lo][1]
            end_p = path[min(hi, len(path) - 1)][1]
            chg = (end_p / start_p - 1) * 100
            print(
                f"  [{lo:4d}-{hi:4d}] {name:14s} {start_p:>12.4f} -> "
                f"{end_p:>12.4f}  ({chg:+6.1f}%)"
            )
