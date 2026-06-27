"""Tests for the verifiable core: canonical hash, receipt chain, policy engine, strategy, tick."""
import asyncio

from agent.policy.canonical import policy_hash, strip_comments, committed_policy_hash
from agent.policy.receipt import ReceiptChain, verify_chain, GENESIS
from agent.policy.engine import PolicyEngine, PortfolioView, MarketView
from agent.policy.canonical import load_config
from agent.strategy.signals import TokenView, classify, rank_entries
from agent.strategy import survival
from agent.types import Decision
from agent import core


CFG = load_config()


def test_strip_comments_and_hash_stable():
    a = {"x": 1, "_c": "note", "n": {"_z": 9, "y": 2}}
    assert strip_comments(a) == {"x": 1, "n": {"y": 2}}
    # comments don't change the hash
    assert policy_hash({"x": 1, "_c": "a"}) == policy_hash({"x": 1, "_c": "different"})
    # key order doesn't change the hash
    assert policy_hash({"a": 1, "b": 2}) == policy_hash({"b": 2, "a": 1})


def test_receipt_chain_detects_tampering(tmp_path):
    ch = ReceiptChain(tmp_path / "r.jsonl")
    ph = "sha256:abc"
    for i in range(4):
        ch.append(policy_hash=ph, kind="hold", decision={"i": i}, verdict="hold",
                  reason="r", inputs_digest="d", ts=f"t{i}")
    recs = ch.read_all()
    assert verify_chain(recs, expected_policy_hash=ph)["ok"]
    recs[2]["reason"] = "TAMPERED"
    res = verify_chain(recs, expected_policy_hash=ph)
    assert not res["ok"] and res["broken_at"] == 2


def test_policy_rejects_off_whitelist_and_clamps():
    eng = PolicyEngine(CFG)
    pv = eng.check(Decision("buy", "bsc", "USDT", "DOGE", 50, 0.7, "x"),
                   PortfolioView(nav_usd=500), MarketView(data_age_s=0))
    assert pv.action == "reject" and "whitelist" in pv.reason
    big = eng.check(Decision("buy", "bsc", "USDT", "WBNB", 5000, 0.9, "x"),
                    PortfolioView(nav_usd=500, risky_exposure_pct=0.0), MarketView(data_age_s=0))
    assert big.action == "clamp" and big.final_amount_usd <= CFG["risk"]["max_single_trade_usd"]


def test_policy_stale_data_rejected():
    eng = PolicyEngine(CFG)
    pv = eng.check(Decision("buy", "bsc", "USDT", "WBNB", 10, 0.7, "x"),
                   PortfolioView(nav_usd=500), MarketView(data_age_s=99999))
    assert pv.action == "reject" and "stale" in pv.reason


def test_drawdown_ladder_blocks_new_risk():
    eng = PolicyEngine(CFG)
    # at 4% drawdown we're in stablecoin mode → a risk-increasing buy is rejected
    pv = eng.check(Decision("buy", "bsc", "USDT", "WBNB", 10, 0.7, "x"),
                   PortfolioView(nav_usd=500, drawdown_pct=4.0), MarketView(data_age_s=0))
    assert pv.action == "reject" and pv.ladder_rung == "stablecoin_mode"


def test_signal_requires_momentum_agreement():
    cfg_sig = CFG["signal"]
    agree_up = TokenView("WBNB", 600, pct_1h=0.8, pct_4h=1.4, vol_24h_pct=2.0)
    disagree = TokenView("ETH", 3500, pct_1h=-1.0, pct_4h=2.0, vol_24h_pct=2.0)
    highvol = TokenView("CAKE", 2.3, pct_1h=0.5, pct_4h=0.6, vol_24h_pct=9.0)
    assert classify(agree_up, cfg_sig).state == "risk_on"
    assert classify(disagree, cfg_sig).state == "neutral"
    assert classify(highvol, cfg_sig).state == "risk_off"


def test_strategy_enters_on_clean_uptrend():
    # ETH is a leaderboard-eligible buy target; WBNB/BTCB are no longer entered (see buy_set).
    views = [TokenView("ETH", 3000, pct_1h=0.8, pct_4h=1.4, vol_24h_pct=2.0)]
    ps = survival.PortfolioState(nav_usd=500, stable_usd=500)
    intent = survival.decide(views, ps, CFG, now_ts=1000.0)
    assert intent.action == "enter" and intent.to_token == "ETH"


def test_tick_decision_is_deterministic():
    # The decision is a pure function of inputs (the receipt HASH chains to the growing log, so
    # that legitimately differs; the decision itself must not).
    async def run():
        s = {"nav": 500.0, "stable_usd": 500.0, "high_water_mark": 500.0, "positions": {}}
        r, _ = await core.tick(state=dict(s), executor=None, now_ts=1750550400.0)
        return (r.intent_action, r.verdict, r.reason, r.decision["amount_usd"])
    assert asyncio.run(run()) == asyncio.run(run())
