"""Regression test for the min-trade floor under the no_new_risk drawdown rung.

When the drawdown ladder forbids new risk, the up-rebalance is gated off. A wedged agent that
holds only a small position would then sit a whole UTC day at zero qualifying swaps and drop off
the leaderboard. The floor must instead make one tiny risk-reducing trim so the committed minimum
daily trade count holds. It must NOT fire before a full compliance gap has elapsed (no churn).
"""
from agent.policy.canonical import load_config
from agent.strategy.signals import TokenView
from agent.strategy import survival

CFG = load_config()

# Flat tape so no entry signal could fire on its own; prices let positions be valued.
VIEWS = [
    TokenView(symbol="WBNB", price=560.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
    TokenView(symbol="BTCB", price=100000.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
    TokenView(symbol="ETH", price=3000.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
    TokenView(symbol="CAKE", price=2.5, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
]


def _wedged_portfolio(seconds_since_last_trade: float) -> survival.PortfolioState:
    # 2.5% drawdown -> no_new_risk rung (ladder: 1% halve, 2% no_new_risk, 3% stablecoin).
    # Holds $10 of BTCB at break-even (no stop/take-profit/time-stop exit), low overall exposure.
    pos = survival.Position(symbol="BTCB", qty=0.0001, entry_price=100000.0, entry_ts=995.0)
    return survival.PortfolioState(
        nav_usd=190.0, stable_usd=180.0, positions={"BTCB": pos},
        drawdown_pct=2.5, risky_exposure_pct=5.0, trades_this_week=3,
        seconds_since_last_trade=seconds_since_last_trade,
    )


def test_floor_trims_when_wedged_past_gap():
    ps = _wedged_portfolio(seconds_since_last_trade=20000.0)  # > 4h default gap
    intent = survival.decide(VIEWS, ps, CFG, now_ts=1000.0)
    assert intent.action == "rebalance"
    assert intent.from_token == "BTCB" and intent.to_token == "USDT"  # a SELL (risk down)
    assert intent.amount_usd > 0.0


def test_floor_does_not_churn_before_gap():
    ps = _wedged_portfolio(seconds_since_last_trade=300.0)  # well under the gap and interval
    intent = survival.decide(VIEWS, ps, CFG, now_ts=1000.0)
    assert intent.action == "hold"
    assert intent.abstain_reason == "drawdown_proximity"


def test_floor_buys_when_nothing_sellable():
    # Wedged with only cash left (no correctly-valued holding to trim): keep the daily swap
    # alive with a tiny buy of a correctly-priced token, never BTCB.
    ps = survival.PortfolioState(
        nav_usd=190.0, stable_usd=190.0, positions={},
        drawdown_pct=2.5, risky_exposure_pct=0.0, trades_this_week=3,
        seconds_since_last_trade=20000.0,
    )
    intent = survival.decide(VIEWS, ps, CFG, now_ts=1000.0)
    assert intent.action == "rebalance"
    assert intent.from_token == "USDT" and intent.to_token in {"WBNB", "ETH", "CAKE"}
    assert intent.to_token != "BTCB" and intent.amount_usd > 0.0
