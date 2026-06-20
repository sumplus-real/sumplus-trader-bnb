import pytest

from agent.ops.rpc import RpcAllDownError, RpcPool


def test_rpc_pool_fails_over_and_tracks_health():
    calls = []

    def transport(endpoint, payload, timeout):
        calls.append((endpoint, payload["method"], timeout))
        if endpoint == "https://bad":
            raise RuntimeError("down")
        return {"jsonrpc": "2.0", "id": payload["id"], "result": "0x1"}

    pool = RpcPool(["https://bad", "https://good"], timeout=1.5, transport=transport)

    result = pool.call("eth_blockNumber", [])

    assert result["result"] == "0x1"
    assert calls == [
        ("https://bad", "eth_blockNumber", 1.5),
        ("https://good", "eth_blockNumber", 1.5),
    ]
    assert pool.healthy_endpoints() == ["https://good"]
    status = pool.endpoint_status()
    assert status["https://bad"].fail_count == 1
    assert status["https://good"].latency_s is not None


def test_rpc_pool_raises_when_all_endpoints_fail():
    def transport(endpoint, payload, timeout):
        raise RuntimeError(f"{endpoint} failed")

    pool = RpcPool(["a", "b"], cooldown_s=60.0, transport=transport)

    with pytest.raises(RpcAllDownError):
        pool.call("eth_chainId", [])

    assert pool.healthy_endpoints() == []


def test_rpc_pool_rechecks_after_cooldown():
    calls = []

    def transport(endpoint, payload, timeout):
        calls.append(endpoint)
        if len(calls) == 1:
            raise RuntimeError("first probe fails")
        return {"jsonrpc": "2.0", "id": payload["id"], "result": "0x38"}

    pool = RpcPool(["https://node"], cooldown_s=0.0, transport=transport)

    with pytest.raises(RpcAllDownError):
        pool.call("eth_chainId", [])

    assert pool.call("eth_chainId", [])["result"] == "0x38"
    assert pool.healthy_endpoints() == ["https://node"]


def test_rpc_pool_treats_json_rpc_error_as_endpoint_failure():
    def transport(endpoint, payload, timeout):
        return {"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32000}}

    pool = RpcPool(["https://bad"], transport=transport)

    with pytest.raises(RpcAllDownError):
        pool.call("eth_call", [])

