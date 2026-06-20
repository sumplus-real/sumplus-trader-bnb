"""TRACK-2 backtest orchestrator.

Runs the CHAMPION (survival-first) and CHALLENGER (naive DCA) on the SAME
deterministic synthetic price series, then prints a head-to-head comparison
table and writes `backtest/results.json`.

Reproducibility: the data seed is fixed, every RNG is seeded, and all swap
costs are identical across strategies. Running this file twice prints the
exact same numbers and produces a byte-identical results.json.

Usage:
    ../sumplus-trading-agent/.venv/bin/python backtest/run.py
"""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Tuple

# Make sibling modules importable regardless of invocation cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import champion
import challenger
from champion import Intent, DEFAULT_CFG as CHAMPION_CFG
from challenger import DEFAULT_CFG as CHALLENGER_CFG
from data import generate_synthetic_prices, ASSETS, REGIMES, REGIME_BOUNDS, regime_at
from portfolio import Portfolio, DEFAULT_FEE_BPS, DEFAULT_SLIPPAGE_BPS, new_portfolio
from metrics import all_metrics, metrics_from_nav, first_breach_hour

# ----------------------------------------------------------------- config
SEED = 20240622
HOURS = 1008  # 6 weeks of hourly bars
INITIAL_NAV = 10_000.0
MAX_TRADES_PER_HOUR = 4  # mirrors strategy.json `max_trades_per_hour`
FEE_BPS = DEFAULT_FEE_BPS
SLIP_BPS = DEFAULT_SLIPPAGE_BPS
RESULTS_PATH = os.path.join(_HERE, "results.json")


# ----------------------------------------------------------------- engine
def _execute(
    intent: Intent, portfolio: Portfolio, prices: Dict[str, float], hour: int
) -> bool:
    """Apply one Intent to the portfolio. Returns True if a trade executed."""
    if intent.action == "buy":
        spent = portfolio.buy(
            intent.asset, intent.size, prices[intent.asset], hour, FEE_BPS, SLIP_BPS
        )
        return spent > 0
    if intent.action == "sell":
        proceeds = portfolio.sell(
            intent.asset, intent.size, prices[intent.asset], FEE_BPS, SLIP_BPS
        )
        return proceeds > 0
    if intent.action == "flatten":
        fills = portfolio.flatten(prices, FEE_BPS, SLIP_BPS)
        return fills > 0
    return False  # hold


def _run_strategy(
    decide_fn, prices_per_asset: Dict[str, List[float]], hours: List[int], cfg: dict
) -> Tuple[Portfolio, List[str]]:
    """Drive one strategy across the whole series. Returns (portfolio, ledger)."""
    portfolio = new_portfolio(INITIAL_NAV)
    ledger: List[str] = []

    for h in hours:
        prices = {asset: prices_per_asset[asset][h] for asset in prices_per_asset}
        # history up to and including h (for momentum / vol)
        history = {
            asset: prices_per_asset[asset][: h + 1] for asset in prices_per_asset
        }
        market_state = {"t": h, "prices": prices, "history": history}

        # Agent loop: re-decide until HOLD or rate-limit, marking NAV once/tick.
        for _ in range(MAX_TRADES_PER_HOUR):
            dd = portfolio.current_drawdown()
            intent = decide_fn(market_state, portfolio, cfg)
            if intent.action == "hold":
                break
            executed = _execute(intent, portfolio, prices, h)
            if executed:
                ledger.append(
                    f"h={h:04d} dd={dd:4.2f}% {intent.action:7s} "
                    f"{intent.asset:5s} {intent.size:8.2f} | {intent.reason}"
                )
            # non-executed intents (e.g. out-of-cash) also break the loop
            if not executed:
                break

        portfolio.mark(prices, h)

    return portfolio, ledger


# ----------------------------------------------------------------- table
GATE_DD_PCT = 6.0  # competition elimination gate (config/strategy.json)


def _print_full_table(champ: dict, chal: dict) -> None:
    """Full-period headline metrics. Honest -- includes the challenger's
    post-elimination paper recovery (which the competition would void)."""
    sep = "+" + "-" * 46 + "+" + "-" * 13 + "+" + "-" * 13 + "+"
    print("\n" + "=" * 78)
    print(" TRACK-2 HEAD-TO-HEAD: CHAMPION vs CHALLENGER".center(78))
    print(
        " 6 weeks of hourly bars | 4 regimes | same costs (25 bps fee + 30 bps slip)".center(
            78
        )
    )
    print("=" * 78)
    print(
        "(A) FULL-PERIOD METRICS  (honest; includes challenger's post-elim paper gain)"
    )
    print(sep)
    print(f"| {'metric':<44} | {'champion':>11} | {'challenger':>11} |")
    print(sep.replace("-", "="))
    rows = [
        ("total return (%)", champ["total_return_pct"], chal["total_return_pct"]),
        ("max drawdown (%)", champ["max_drawdown_pct"], chal["max_drawdown_pct"]),
        ("Sharpe (annualised)", champ["sharpe"], chal["sharpe"]),
        ("Calmar (period: ret/maxDD)", champ["calmar"], chal["calmar"]),
        ("trade count", champ["trade_count"], chal["trade_count"]),
        ("% time in market", champ["pct_time_in_market"], chal["pct_time_in_market"]),
    ]
    for label, c, n in rows:
        flag = ""
        if label.startswith("max drawdown"):
            if n >= GATE_DD_PCT:
                flag = "  <-- breaches 6% gate"
            elif c >= 4.0:
                flag = "  <-- ladder flatten rung"
        if isinstance(c, float):
            print(f"| {label:<44} | {c:>11.4f} | {n:>11.4f} |{flag}")
        else:
            print(f"| {label:<44} | {c:>11} | {n:>11} |{flag}")
    print(sep)


def _print_competition_table(
    champ_win: dict, chal_win: dict, window_hours: int, elim_hour
) -> None:
    """Apples-to-apples risk-adjusted comparison on the window BOTH strategies
    are 'alive' = [0, challenger-elimination-hour]. After elimination a
    contestant is disqualified, so its post-elim paper numbers are void."""
    sep = "+" + "-" * 46 + "+" + "-" * 13 + "+" + "-" * 13 + "+"
    if elim_hour is None:
        print("\n(B) COMPETITION-WINDOW METRICS  (neither strategy breached 6%)")
    else:
        print(
            f"\n(B) COMPETITION-WINDOW METRICS  (both alive: hours 0..{elim_hour}, "
            f"the moment the challenger is eliminated)"
        )
    print(sep)
    print(
        f"| {'metric (over ' + str(window_hours) + '-hour window)':<44} | {'champion':>11} | {'challenger':>11} |"
    )
    print(sep.replace("-", "="))
    rows = [
        (
            "total return (%)",
            champ_win["total_return_pct"],
            chal_win["total_return_pct"],
        ),
        (
            "max drawdown (%)",
            champ_win["max_drawdown_pct"],
            chal_win["max_drawdown_pct"],
        ),
        ("Sharpe (annualised)", champ_win["sharpe"], chal_win["sharpe"]),
        ("Calmar (period: ret/maxDD)", champ_win["calmar"], chal_win["calmar"]),
    ]
    for label, c, n in rows:
        if isinstance(c, float):
            print(f"| {label:<44} | {c:>11.4f} | {n:>11.4f} |")
        else:
            print(f"| {label:<44} | {c:>11} | {n:>11} |")
    print(sep)


def _print_regime_table(per_regime: dict) -> None:
    rsep = "+" + "-" * 18 + "+" + "-" * 13 + "+" + "-" * 13 + "+"
    print("\n(C) MAX DRAWDOWN (%) BY REGIME  (continuous global HWM)")
    print(rsep)
    print(f"| {'regime':<16} | {'champion':>11} | {'challenger':>11} |")
    print(rsep.replace("-", "="))
    for name in [r[0] for r in REGIMES]:
        c = per_regime["champion"].get(name, 0.0)
        n = per_regime["challenger"].get(name, 0.0)
        flag = "  <-- eliminated" if n >= GATE_DD_PCT else ""
        print(f"| {name:<16} | {c:>11.4f} | {n:>11.4f} |{flag}")
    print(rsep)


def _print_verdict(
    champ_full, chal_full, champ_win, chal_win, champ_elim, chal_elim
) -> None:
    print("\n" + "=" * 78)
    print(" VERDICT".center(78))
    print("=" * 78)
    cdd = champ_full["max_drawdown_pct"]
    ndd = chal_full["max_drawdown_pct"]
    if champ_elim is None and chal_elim is not None:
        print(
            f"   champion  : SURVIVES the full 6 weeks. maxDD {cdd:.2f}%  "
            f"(headroom to 6% gate: {GATE_DD_PCT - cdd:.2f} pts)"
        )
        print(
            f"   challenger: ELIMINATED at hour {chal_elim} "
            f"(maxDD hit {ndd:.2f}% later in the crash). DISQUALIFIED."
        )
        print("   -> The challenger's attractive full-period paper return is a")
        print("      mirage: it is only achievable by holding through a drawdown")
        print("      the competition forbids. An eliminated bot cannot recover.")
    print(f"\n   risk-adjusted on the comparable (both-alive) window:")
    print(
        f"     Sharpe : champion {champ_win['sharpe']:6.3f}  vs  "
        f"challenger {chal_win['sharpe']:6.3f}"
    )
    print(
        f"     Calmar: champion {champ_win['calmar']:6.3f}  vs  "
        f"challenger {chal_win['calmar']:6.3f}"
    )
    if chal_elim is not None:
        chal_ret_at_elim = chal_win["total_return_pct"]
        print(
            f"   challenger realised return AT elimination: "
            f"{chal_ret_at_elim:+.2f}%  (vs champion full-period "
            f"{champ_full['total_return_pct']:+.2f}%)"
        )
    print()


def _per_regime_drawdown(
    portfolio: Portfolio, hours: List[int], prices_per_asset: Dict[str, List[float]]
) -> Dict[str, float]:
    """Worst drawdown *observed during* each regime window.

    Uses the CONTINUOUS global high-water-mark (does NOT reset at regime
    boundaries), so a drawdown that starts late in one regime and deepens in
    the next -- exactly the uptrend->crash transition we care about -- is
    correctly attributed to the regime where it actually bottoms.
    """
    out = {name: 0.0 for name, _, _ in REGIMES}
    nav_all = portfolio.nav_history
    global_hwm = -1e18
    for i, (name, _, _) in enumerate(REGIMES):
        lo, hi = REGIME_BOUNDS[i], REGIME_BOUNDS[i + 1]
        mdd = 0.0
        for h in range(lo, min(hi, len(nav_all))):
            n = nav_all[h]
            if n > global_hwm:
                global_hwm = n
            if global_hwm > 0:
                dd = (global_hwm - n) / global_hwm * 100.0
                if dd > mdd:
                    mdd = dd
        out[name] = round(mdd, 4)
    return out


# ----------------------------------------------------------------- main
def main() -> dict:
    series = generate_synthetic_prices(seed=SEED, hours=HOURS)
    prices_per_asset = {asset: [p for _, p in path] for asset, path in series.items()}
    hours = list(range(HOURS))

    champ_pf, champ_ledger = _run_strategy(
        champion.decide, prices_per_asset, hours, CHAMPION_CFG
    )
    chal_pf, chal_ledger = _run_strategy(
        challenger.decide, prices_per_asset, hours, CHALLENGER_CFG
    )

    # ---- full-period metrics (honest, includes challenger post-elim paper gain)
    champ_full = all_metrics(champ_pf, champ_pf.nav_history, HOURS)
    chal_full = all_metrics(chal_pf, chal_pf.nav_history, HOURS)

    # ---- elimination analysis (the 6% gate is the whole point of the contest)
    champ_elim = first_breach_hour(champ_pf.drawdown_history, GATE_DD_PCT)
    chal_elim = first_breach_hour(chal_pf.drawdown_history, GATE_DD_PCT)

    # ---- competition-window metrics: both strategies alive -> apples-to-apples
    # Window ends at the FIRST elimination (whoever is disqualified first).
    # If neither breaches, the window is the full period.
    elim_hour = min([h for h in [champ_elim, chal_elim] if h is not None], default=None)
    win_end = (elim_hour + 1) if elim_hour is not None else HOURS
    champ_win = metrics_from_nav(champ_pf.nav_history[:win_end])
    chal_win = metrics_from_nav(chal_pf.nav_history[:win_end])

    champ_regime = _per_regime_drawdown(champ_pf, hours, prices_per_asset)
    chal_regime = _per_regime_drawdown(chal_pf, hours, prices_per_asset)

    _print_full_table(champ_full, chal_full)
    _print_competition_table(champ_win, chal_win, win_end, elim_hour)
    _print_regime_table({"champion": champ_regime, "challenger": chal_regime})
    _print_verdict(champ_full, chal_full, champ_win, chal_win, champ_elim, chal_elim)

    results = {
        "meta": {
            "seed": SEED,
            "hours": HOURS,
            "initial_nav": INITIAL_NAV,
            "fee_bps": FEE_BPS,
            "slippage_bps": SLIP_BPS,
            "assets": ASSETS,
            "regimes": [
                {
                    "name": n,
                    "lo": REGIME_BOUNDS[i],
                    "hi": REGIME_BOUNDS[i + 1],
                    "mu": m,
                    "sigma": s,
                }
                for i, (n, m, s) in enumerate(REGIMES)
            ],
            "elimination_gate_dd_pct": GATE_DD_PCT,
        },
        "champion_full_period": champ_full,
        "challenger_full_period": chal_full,
        "champion_elimination_hour": champ_elim,
        "challenger_elimination_hour": chal_elim,
        "competition_window_hours": win_end,
        "champion_competition_window": champ_win,
        "challenger_competition_window": chal_win,
        "per_regime_max_drawdown_pct": {
            "champion": champ_regime,
            "challenger": chal_regime,
        },
        "champion_final_nav": round(champ_pf.nav_history[-1], 4),
        "challenger_final_nav": round(chal_pf.nav_history[-1], 4),
        "champion_trade_count": len(champ_ledger),
        "challenger_trade_count": len(chal_ledger),
    }
    with open(RESULTS_PATH, "w") as fh:
        json.dump(results, fh, indent=2, sort_keys=True)
    print(f" results written -> {RESULTS_PATH}\n")
    return results


if __name__ == "__main__":
    main()
