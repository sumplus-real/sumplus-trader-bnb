from agent.ops.reconcile import reconcile


def test_reconcile_ok_within_tolerance():
    result = reconcile({"USDT": 100.0}, {"USDT": 99.5}, tol_pct=1.0)

    assert result.ok
    assert result.divergences == []
    assert round(result.worst_pct, 3) == 0.5


def test_reconcile_flags_missing_and_divergent_tokens():
    result = reconcile({"USDT": 100.0, "WBNB": 1.0}, {"USDT": 80.0, "CAKE": 2.0}, tol_pct=1.0)

    assert not result.ok
    assert result.worst_pct == 100.0
    assert [d["token"] for d in result.divergences] == ["CAKE", "USDT", "WBNB"]


def test_reconcile_zero_balances_are_stable():
    result = reconcile({"USDT": 0.0}, {"USDT": 0.0}, tol_pct=1.0)

    assert result.ok
    assert result.worst_pct == 0.0

