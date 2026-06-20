"""Local nonce reservation with chain reconciliation."""
from __future__ import annotations

from typing import Any, Optional

from agent.ops.rpc import RpcPool


class NonceError(RuntimeError):
    """Base nonce manager error."""


class NonceGapError(NonceError):
    """Raised when local nonce state is ambiguous."""


class NonceManager:
    """Reserve transaction nonces from the pending chain nonce."""

    def __init__(self, rpc: RpcPool, address: str) -> None:
        if not address:
            raise ValueError("address is required")
        self.rpc = rpc
        self.address = address
        self._next_nonce: Optional[int] = None
        self._reserved: set[int] = set()
        self._confirmed: set[int] = set()
        self._failed: set[int] = set()
        self._gapped = False

    def sync(self) -> None:
        """Refresh local state from eth_getTransactionCount(..., pending)."""
        chain_nonce = self._read_chain_nonce()
        if self._next_nonce is None:
            self._next_nonce = chain_nonce
            return

        if chain_nonce > self._next_nonce:
            self._confirmed.update(range(self._next_nonce, chain_nonce))
            self._reserved.difference_update(range(self._next_nonce, chain_nonce))
            self._next_nonce = chain_nonce

        if self._reserved and chain_nonce <= min(self._reserved) < self._next_nonce:
            self._gapped = True

    def reserve(self) -> int:
        """Return and hold the next nonce for exactly one transaction attempt."""
        if self._gapped:
            raise NonceGapError("nonce state is gapped")
        if self._next_nonce is None:
            self.sync()
        if self._next_nonce is None:
            raise NonceError("nonce state was not initialized")

        nonce = self._next_nonce
        self._reserved.add(nonce)
        self._next_nonce += 1
        return nonce

    def on_confirmed(self, nonce: int) -> None:
        """Mark a nonce confirmed and reconcile obvious gaps."""
        self._confirmed.add(nonce)
        self._reserved.discard(nonce)
        if any(open_nonce < nonce for open_nonce in self._reserved):
            self._gapped = True
        self.sync()

    def on_failed(self, nonce: int) -> None:
        """Mark a nonce failed; lower failed nonces force fail-closed gap state."""
        self._failed.add(nonce)
        self._reserved.discard(nonce)
        if self._next_nonce is None or nonce < self._next_nonce:
            self._gapped = True
        self.sync()

    def is_gapped(self) -> bool:
        """Return True when local nonce state is unsafe for new sends."""
        return self._gapped

    @property
    def next_nonce(self) -> Optional[int]:
        """Current next local nonce, exposed for diagnostics."""
        return self._next_nonce

    def _read_chain_nonce(self) -> int:
        response = self.rpc.call("eth_getTransactionCount", [self.address, "pending"])
        raw: Any = response.get("result")
        if isinstance(raw, str):
            return int(raw, 16) if raw.startswith("0x") else int(raw)
        if isinstance(raw, int):
            return raw
        raise NonceError("invalid chain nonce response")

