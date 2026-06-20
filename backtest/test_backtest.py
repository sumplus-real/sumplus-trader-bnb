"""Pytest sanity tests for the TRACK-2 backtest.

Run with:
    ../sumplus-trading-agent/.venv/bin/pytest backtest/test_backtest.py -q
"""

import json
import os
import sys

# Make the sibling backtest modules importable regardless of pytest's rootdir
# or the caller's cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import champion  # noqa: E402
import challenger  # noqa: E402
from champion import DEFAULT_CFG as CHAMPION_CFG  # noqa: E402
from challenger import DEFAULT_CFG as CHALLENGER_CFG  # noqa: E402
from data import generate_synthetic_prices, ASSETS  # noqa: E402
from run import _run_strategy, HOURS, RESULTS_PATH  # noqa: E402
from metrics import all_metrics, first_breach_hour, max_drawdown_pct  # noqa: E402

GATE_DD_PCT = 6.0


def _run_both():
    """Run both strategies on the canonical seeded series; return both portfolios."""
    series = generate_synthetic_prices()
    ppa = {a: [p for _, p in path] for a, path in series.items()}
    hours = list(range(HOURS))
    champ_pf, _ = _run_strategy(champion.decide, ppa, hours, CHAMPION_CFG)
    chal_pf, _ = _run_strategy(challenger.decide, ppa, hours, CHALLENGER_CFG)
    return champ_pf, chal_pf


# ----------------------------------------------------------------- tests
def test_data_is_deterministic():
    """Same seed must produce byte-identical price series across calls."""
    s1 = generate_synthetic_prices(seed=20240622)
    s2 = generate_synthetic_prices(seed=20240622)
    assert set(s1) == set(s2) == set(ASSETS)
    for asset in ASSETS:
        p1 = [round(p, 10) for _, p in s1[asset]]
        p2 = [round(p, 10) for _, p in s2[asset]]
        assert p1 == p2, f"price series for {asset} differs across calls"


def test_backtest_is_deterministic():
    """The whole pipeline must be reproducible: two runs give identical metrics."""
    c1, n1 = _run_both()
    c2, n2 = _run_both()
    cm1 = all_metrics(c1, c1.nav_history, HOURS)
    cm2 = all_metrics(c2, c2.nav_history, HOURS)
    nm1 = all_metrics(n1, n1.nav_history, HOURS)
    nm2 = all_metrics(n2, n2.nav_history, HOURS)
    assert cm1 == cm2, "champion metrics differ across runs"
    assert nm1 == nm2, "challenger metrics differ across runs"
    assert c1.nav_history == c2.nav_history
    assert n1.nav_history == n2.nav_history


def test_champion_has_lower_max_drawdown_than_challenger():
    """The headline thesis: survival-first caps DD far below the naive bot."""
    champ_pf, chal_pf = _run_both()
    c_dd = max_drawdown_pct(champ_pf.nav_history)
    n_dd = max_drawdown_pct(chal_pf.nav_history)
    assert c_dd < n_dd, f"champion maxDD {c_dd} not < challenger maxDD {n_dd}"
    assert (n_dd - c_dd) > 10.0, "expected >10pt drawdown gap"


def test_champion_survives_the_gate_and_challenger_is_eliminated():
    """Champion never breaches the 6% elimination gate; challenger does."""
    champ_pf, chal_pf = _run_both()
    champ_elim = first_breach_hour(champ_pf.drawdown_history, GATE_DD_PCT)
    chal_elim = first_breach_hour(chal_pf.drawdown_history, GATE_DD_PCT)
    assert champ_elim is None, f"champion breached 6% at hour {champ_elim}"
    assert chal_elim is not None, "challenger never breached 6% (crash too weak?)"


def test_champion_keeps_drawdown_under_four_percent():
    """The ladder (1.5/3/4 rungs + per-position stops) keeps DD under ~4%."""
    champ_pf, _ = _run_both()
    c_dd = max_drawdown_pct(champ_pf.nav_history)
    assert c_dd < 4.0, f"champion maxDD {c_dd:.2f}% not under 4%"


def test_results_json_written_and_consistent():
    """run.py must have written results.json with the expected shape & verdict."""
    assert os.path.exists(RESULTS_PATH), "results.json missing; run backtest/run.py"
    with open(RESULTS_PATH) as fh:
        r = json.load(fh)
    assert r["champion_elimination_hour"] is None
    assert r["challenger_elimination_hour"] is not None
    assert (
        r["champion_full_period"]["max_drawdown_pct"]
        < r["challenger_full_period"]["max_drawdown_pct"]
    )
