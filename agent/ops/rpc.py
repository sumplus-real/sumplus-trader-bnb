"""Fail-closed JSON-RPC endpoint pool."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx


class RpcAllDownError(RuntimeError):
    """Raised when no RPC endpoint can serve a request."""


class RpcEndpointError(RuntimeError):
    """Raised when one endpoint returns an unusable response."""


Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


@dataclass
class EndpointStatus:
    """Health and timing for one RPC endpoint."""
    endpoint: str
    healthy: bool = True
    unhealthy_until: float = 0.0
    fail_count: int = 0
    latency_s: Optional[float] = None


class RpcPool:
    """Small synchronous JSON-RPC pool with cooldown health checks."""

    def __init__(
        self,
        endpoints: list[str],
        timeout: float = 8.0,
        *,
        cooldown_s: float = 30.0,
        transport: Optional[Transport] = None,
    ) -> None:
        if not endpoints:
            raise ValueError("at least one RPC endpoint is required")
        self.endpoints = list(endpoints)
        self.timeout = timeout
        self.cooldown_s = cooldown_s
        self._transport = transport or self._httpx_transport
        self._states = {url: EndpointStatus(endpoint=url) for url in self.endpoints}
        self._rpc_id = 0

    def call(self, method: str, params: list[Any]) -> dict[str, Any]:
        """POST a JSON-RPC call to the first currently usable endpoint."""
        payload = self._payload(method, params)
        errors: list[str] = []

        for endpoint in self._candidate_endpoints():
            started = time.monotonic()
            try:
                response = self._transport(endpoint, payload, self.timeout)
                self._validate_response(response)
            except Exception as exc:
                self._mark_failure(endpoint)
                errors.append(f"{endpoint}: {exc}")
                continue

            self._mark_success(endpoint, time.monotonic() - started)
            return response

        detail = "; ".join(errors) if errors else "all endpoints are cooling down"
        raise RpcAllDownError(detail)

    def healthy_endpoints(self) -> list[str]:
        """Return endpoints currently known to be healthy."""
        return [url for url in self.endpoints if self._states[url].healthy]

    def endpoint_status(self) -> dict[str, EndpointStatus]:
        """Return a snapshot of endpoint health for diagnostics."""
        return {url: EndpointStatus(**vars(state)) for url, state in self._states.items()}

    def _payload(self, method: str, params: list[Any]) -> dict[str, Any]:
        self._rpc_id += 1
        return {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params}

    def _candidate_endpoints(self) -> list[str]:
        now = time.monotonic()
        return [url for url in self.endpoints if self._is_available(url, now)]

    def _is_available(self, endpoint: str, now: float) -> bool:
        state = self._states[endpoint]
        if state.healthy:
            return True
        return now >= state.unhealthy_until

    def _mark_success(self, endpoint: str, latency_s: float) -> None:
        state = self._states[endpoint]
        state.healthy = True
        state.unhealthy_until = 0.0
        state.latency_s = latency_s

    def _mark_failure(self, endpoint: str) -> None:
        state = self._states[endpoint]
        state.healthy = False
        state.unhealthy_until = time.monotonic() + self.cooldown_s
        state.fail_count += 1

    @staticmethod
    def _validate_response(response: dict[str, Any]) -> None:
        if not isinstance(response, dict):
            raise RpcEndpointError("response is not a dict")
        if response.get("jsonrpc") != "2.0":
            raise RpcEndpointError("response missing jsonrpc=2.0")
        if "error" in response:
            raise RpcEndpointError(f"json-rpc error: {response['error']}")
        if "result" not in response:
            raise RpcEndpointError("response missing result")

    @staticmethod
    def _httpx_transport(endpoint: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        response = httpx.post(endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RpcEndpointError("http response JSON is not a dict")
        return data
