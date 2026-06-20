"""Tests for the sumplus-survival-strategy Skill (Track 2).

Validates that the Skill (a) reads a regime and maps it to the right exposure budget, (b) emits a
well-formed StrategySpec, and (c) the emitted spec is executable by the backtester with no edits.
Run: python -m pytest skills/sumplus-survival-strategy/test_skill.py -q
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "backtest"), str(ROOT / "skills" / "sumplus-survival-strategy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import generate_spec as gs


def test_regime_mapping():
    # extreme greed -> de-risk
    assert gs.classify_regime(fng=85, avg_mom_4h=1.0, avg_vol=2.0) == "risk_off"
    # high vol -> de-risk regardless of fng
    assert gs.classify_regime(fng=50, avg_mom_4h=0.5, avg_vol=4.5) == "risk_off"
    # bearish breakdown -> de-risk
    assert gs.classify_regime(fng=50, avg_mom_4h=-3.0, avg_vol=2.0) == "risk_off"
    # clean positive breadth, calm -> base risk
    assert gs.classify_regime(fng=45, avg_mom_4h=1.5, avg_vol=2.0) == "risk_on"


def test_exposure_budget_matches_regime():
    for regime, exp in gs.REGIME_EXPOSURE.items():
        assert exp == {"risk_on": 0.12, "neutral": 0.08, "risk_off": 0.04}[regime]


def test_spec_is_well_formed():
    spec = gs.generate(fng=52.0)
    for key in ("strategyspec_version", "name", "universe", "entry", "sizing",
                "drawdown_ladder_pct", "exits", "rate_limits", "backtest", "regime_read"):
        assert key in spec, f"missing {key}"
    ladder = spec["drawdown_ladder_pct"]
    # the survival invariant: every ladder rung and the hard kill sit strictly inside the gate
    assert ladder["halve_size_at"] < ladder["no_new_risk_at"] < ladder["flatten_to_stablecoin_at"]
    assert ladder["internal_hard_kill_at"] < ladder["elimination_gate_at"]
    assert ladder["elimination_gate_at"] - ladder["internal_hard_kill_at"] >= 2.0  # >=2pt buffer
    assert 0 < spec["sizing"]["max_risky_exposure_pct"] <= 0.12


def test_emitted_spec_is_executable_by_backtester():
    """The spec the Skill emits maps onto the engine and produces decisions (it is backtestable)."""
    import champion
    spec = gs.generate(fng=52.0)
    cfg = gs.to_backtest_cfg(spec)
    # synthesise a short rising price history so a long entry is at least considered
    hist = [100.0 * (1.0 + 0.002) ** i for i in range(30)]
    market_state = {"t": 29,
                    "prices": {s: hist[-1] for s in cfg["universe"]},
                    "history": {s: list(hist) for s in cfg["universe"]}}
    pf = __import__("portfolio").new_portfolio(500.0)
    intent = champion.decide(market_state, pf, cfg)
    assert intent.action in ("buy", "sell", "flatten", "hold")  # engine ran on the emitted spec


def test_risk_off_tightens_exposure():
    calm = gs.generate(fng=45.0)        # risk_on
    greedy = gs.generate(fng=88.0)      # risk_off
    assert greedy["sizing"]["max_risky_exposure_pct"] < calm["sizing"]["max_risky_exposure_pct"]
