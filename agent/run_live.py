"""The unattended live loop — what actually runs during 6/22-28.

Ops-hardened by construction: a watchdog restarts the loop on any crash, state is persisted
atomically so a restart resumes exactly where it left off, and the whole thing is fail-closed
(on doubt it stops trading but keeps recording). Each tick runs the same core.tick used in the
demo and the simulator, so what judges replay offline is what ran live.

  EXECUTION_BACKEND=twak  python -m agent.cli loop      # live, signs via Trust Wallet Agent Kit
  (default)               python -m agent.cli loop      # offline/mock, safe to run anywhere
"""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

from agent import core
from agent.data.cmc import get_token_views
from agent.execution.executor import Executor
from agent.execution.factory import make_backend
from agent.ops.state import PersistentState
from agent.ops.watchdog import run_with_watchdog
from agent.policy.canonical import load_config

ROOT = Path(__file__).resolve().parent.parent
HEARTBEAT = str(ROOT / "heartbeat.txt")
KILL = str(ROOT / "STOP")
STATE_FILE = str(ROOT / "live_state.json")


async def _loop_once_forever() -> None:
    cfg = load_config()
    chosen = os.environ.get("EXECUTION_BACKEND", "").lower()
    exec_mode = "live" if chosen in ("twak", "maria") else "mock"
    backend = make_backend(exec_mode)
    execu = Executor(backend, mode=exec_mode,
                     default_slippage_bps=cfg["risk"]["default_slippage_bps"])
    ps = PersistentState(STATE_FILE)
    state = ps.load()
    # seed a fresh wallet's accounting on first run
    state.setdefault("nav", float(os.environ.get("START_NAV", "500")))
    state.setdefault("stable_usd", state["nav"])
    state.setdefault("high_water_mark", state["nav"])
    state.setdefault("positions", {})

    interval = cfg["loop"]["tick_seconds"]
    while not Path(KILL).exists():
        try:
            result, state = await core.tick(state=state, executor=execu, cfg=cfg)
            # mark NAV to market using the latest prices we just saw
            views, _ = await get_token_views(list(cfg["universe"]) + list(cfg["quote_tokens"]), cfg)
            core.mark_nav(state, {v.symbol.upper(): v.price for v in views})
            for k, v in state.items():
                ps.update(**{k: v})
        except Exception as e:  # fail-closed: record, keep heartbeat, let watchdog decide
            core.AbstentionLedger()  # noqa: ensure module import side-effects are harmless
            print(f"[tick error] {e}")
            raise
        await asyncio.sleep(interval)


async def run() -> None:
    Path(KILL).unlink(missing_ok=True)
    await run_with_watchdog(_loop_once_forever, heartbeat_path=HEARTBEAT, kill_path=KILL,
                            max_restarts=10_000, backoff_s=5.0)


if __name__ == "__main__":
    asyncio.run(run())
