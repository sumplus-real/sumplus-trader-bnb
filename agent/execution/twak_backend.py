"""TWAK execution backend — thin adapter over the Trust Wallet Agent Kit CLI.

Per the winning architecture, TWAK is kept THIN: it is the official self-custody SIGNER + the
on-chain spend fence, not the decision authority (that is Maria's policy engine, which has
already allowed/clamped the trade before we get here). This adapter just turns an approved
Decision into a `twak` swap call and reads the result.

Real execution needs the `twak` CLI installed (npm @trustwallet/cli, Node >= 22.14), a wallet
created (`twak wallet create`) and registered (`twak compete register`), and funds in it. Until
then, dry_run returns the exact command that WOULD run, so the integration is inspectable offline
and finalised by Jakob when he installs TWAK (see docs/HUMAN_STEPS.md).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from agent.execution.backend import ExecutionBackend
from agent.types import ExecutionResult

TWAK_BIN = os.environ.get("TWAK_BIN", "twak")


class TwakBackend(ExecutionBackend):
    def __init__(self, chain_default: str = "bsc", dry_run: bool | None = None):
        self.chain_default = chain_default
        # default to dry-run whenever the CLI is not on PATH, so nothing silently no-ops
        self.dry_run = (shutil.which(TWAK_BIN) is None) if dry_run is None else dry_run

    def _cmd(self, action: str, chain: str, from_token: str, to_token: str,
             amount: str, slippage_bps: int) -> list[str]:
        # Command template for the TWAK CLI swap action. Flags are finalised against `twak --help`
        # at install time; the shape (from/to/amount/chain/slippage + json) is what we encode.
        return [
            TWAK_BIN, "swap",
            "--from", from_token, "--to", to_token, "--amount", amount,
            "--chain", chain, "--slippage-bps", str(slippage_bps),
            "--quote-only" if action == "get_quote" else "--execute",
            "--json",
        ]

    def _run(self, cmd: list[str]) -> dict[str, Any]:
        if self.dry_run:
            return {"dry_run": True, "would_run": " ".join(cmd), "source": "twak"}
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if proc.returncode != 0:
            raise TwakError(proc.returncode, proc.stderr.strip() or proc.stdout.strip())
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"raw": proc.stdout.strip(), "source": "twak"}

    async def get_quote(self, chain: str, from_token: str, to_token: str, amount: str,
                        slippage_bps: int = 50) -> dict[str, Any]:
        return self._run(self._cmd("get_quote", chain or self.chain_default,
                                    from_token, to_token, amount, slippage_bps))

    async def execute_swap(self, chain: str, from_token: str, to_token: str, amount: str,
                           slippage_bps: int = 50) -> ExecutionResult:
        out = self._run(self._cmd("execute_swap", chain or self.chain_default,
                                   from_token, to_token, amount, slippage_bps))
        if out.get("dry_run"):
            return ExecutionResult(executed=False, dry_run=True, detail=out)
        return ExecutionResult(
            executed=bool(out.get("txHash") or out.get("executed")),
            dry_run=False,
            detail={"tx": out.get("txHash"), "source": "twak", **out},
        )


class TwakError(Exception):
    def __init__(self, code: int, detail: str):
        self.code = code
        self.detail = detail
        super().__init__(f"twak error {code}: {detail}")
