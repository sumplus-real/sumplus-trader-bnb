"""Pure portfolio reconciliation checks."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ReconcileResult:
    """Result of comparing internal and on-chain balances."""
    ok: bool
    divergences: list[dict]
    worst_pct: float


def reconcile(
    internal: dict[str, float],
    onchain: dict[str, float],
    tol_pct: float = 1.0,
) -> ReconcileResult:
    """Compare token balances and flag percentage divergences above tolerance."""
    divergences: list[dict] = []
    worst_pct = 0.0

    for token in sorted(set(internal) | set(onchain)):
        expected = float(internal.get(token, 0.0))
        actual = float(onchain.get(token, 0.0))
        base = max(abs(expected), abs(actual), 1e-12)
        pct = abs(actual - expected) / base * 100.0
        worst_pct = max(worst_pct, pct)
        if pct > tol_pct:
            divergences.append(
                {
                    "token": token,
                    "internal": expected,
                    "onchain": actual,
                    "pct": pct,
                }
            )

    return ReconcileResult(ok=not divergences, divergences=divergences, worst_pct=worst_pct)

