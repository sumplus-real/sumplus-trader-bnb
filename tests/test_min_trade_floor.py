"""Regression test for the min-trade floor under the no_new_risk drawdown rung.

The live leaderboard only credits a swap that is "eligible token in + eligible token out".
WBNB (a BNB conversion) and BTCB (untracked) never count. So when the drawdown ladder wedges the
agent in no_new_risk, the floor must force a tiny COUNTED swap through an eligible token (ETH/CAKE),
never WBNB/BTCB, once a full compliance gap has elapsed. It must not fire before the gap (no churn).
"""
from agent.policy.canonical import load_config
from agent.strategy.signals import TokenView
from agent.strategy import survival

CFG = load_config()

# Flat tape so no entry signal fires on its own; prices let positions be valued.
VIEWS = [
    TokenView(symbol="WBNB", price=560.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
    TokenView(symbol="BTCB", price=100000.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
    TokenView(symbol="ETH", price=3000.0, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
    TokenView(symbol="CAKE", price=2.5, pct_1h=0.0, pct_4h=0.0, vol_24h_pct=1.0),
]
ELIGIBLE = {"ETH", "CAKE"}


def _ps(positions, seconds_since_last_trade, risky_exposure_pct=0.05):
    # 2.5% drawdown -> no_new_risk rung (ladder: 1% halve, 2% no_new_risk, 3% stablecoin).
    # risky_exposure_pct is a fraction (0.05 = 5%), kept below target+band so the existing
    # down-rebalance branch does not pre-empt the min-trade floor we are exercising here.
    return survival.PortfolioState(
        nav_usd=190.0, stable_usd=180.0, positions=positions,
        drawdown_pct=2.5, risky_exposure_pct=risky_exposure_pct, trades_this_week=3,
        seconds_since_last_trade=seconds_since_last_trade,
    )


def test_floor_buys_eligible_when_nothing_eligible_held():
    ps = _ps(positions={}, seconds_since_last_trade=20000.0)  # past the 1h gap
    intent = survival.decide(VIEWS, ps, CFG, now_ts=1000.0)
    assert intent.action == "rebalance"
    assert intent.from_token == "USDT" and intent.to_token in ELIGIBLE
    assert intent.amount_usd > 0.0


def test_floor_trims_eligible_when_held():
    pos = {"ETH": survival.Position(symbol="ETH", qty=0.01, entry_price=3000.0, entry_ts=995.0)}
    ps = _ps(positions=pos, seconds_since_last_trade=20000.0)
    intent = survival.decide(VIEWS, ps, CFG, now_ts=1000.0)
    assert intent.action == "rebalance"
    assert intent.from_token == "ETH" and intent.to_token == "USDT"  # a counted SELL
    assert intent.amount_usd > 0.0


def test_floor_never_touches_wbnb_or_btcb():
    # Wedged holding only the uncounted tokens: the floor must still reach for an eligible token
    # (buy ETH/CAKE), never trim WBNB or BTCB (those swaps would not count on the leaderboard).
    pos = {
        "WBNB": survival.Position(symbol="WBNB", qty=0.05, entry_price=560.0, entry_ts=995.0),
        "BTCB": survival.Position(symbol="BTCB", qty=0.0002, entry_price=100000.0, entry_ts=995.0),
    }
    ps = _ps(positions=pos, seconds_since_last_trade=20000.0, risky_exposure_pct=0.05)
    intent = survival.decide(VIEWS, ps, CFG, now_ts=1000.0)
    assert intent.action == "rebalance"
    assert intent.to_token in ELIGIBLE and intent.from_token == "USDT"
    assert intent.from_token not in {"WBNB", "BTCB"} and intent.to_token not in {"WBNB", "BTCB"}


def test_floor_does_not_churn_before_gap():
    ps = _ps(positions={}, seconds_since_last_trade=300.0)  # under both gap and interval
    intent = survival.decide(VIEWS, ps, CFG, now_ts=1000.0)
    assert intent.action == "hold"
    assert intent.abstain_reason == "drawdown_proximity"
