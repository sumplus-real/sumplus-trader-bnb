import pytest

from agent.ops.nonce import NonceGapError, NonceManager


class FakeRpc:
    def __init__(self, nonces):
        self.nonces = list(nonces)
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        nonce = self.nonces.pop(0) if self.nonces else 0
        return {"jsonrpc": "2.0", "id": 1, "result": hex(nonce)}


def test_nonce_sync_and_reserve_are_monotonic():
    rpc = FakeRpc([5])
    manager = NonceManager(rpc, "0xabc")

    manager.sync()

    assert manager.reserve() == 5
    assert manager.reserve() == 6
    assert manager.next_nonce == 7
    assert not manager.is_gapped()
    assert rpc.calls[0] == ("eth_getTransactionCount", ["0xabc", "pending"])


def test_nonce_confirmed_higher_with_lower_reserved_marks_gap():
    rpc = FakeRpc([10, 10])
    manager = NonceManager(rpc, "0xabc")
    low = manager.reserve()
    high = manager.reserve()

    manager.on_confirmed(high)

    assert low == 10
    assert high == 11
    assert manager.is_gapped()
    with pytest.raises(NonceGapError):
        manager.reserve()


def test_nonce_failed_reserved_nonce_marks_gap_fail_closed():
    rpc = FakeRpc([3, 3])
    manager = NonceManager(rpc, "0xabc")
    nonce = manager.reserve()

    manager.on_failed(nonce)

    assert manager.is_gapped()
    with pytest.raises(NonceGapError):
        manager.reserve()


def test_nonce_sync_advances_when_chain_is_ahead():
    rpc = FakeRpc([1, 4])
    manager = NonceManager(rpc, "0xabc")
    assert manager.reserve() == 1

    manager.sync()

    assert manager.next_nonce == 4

