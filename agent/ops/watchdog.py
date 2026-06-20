"""Async supervisor and heartbeat helpers."""
from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Awaitable, Callable


def heartbeat(path: str, ts: float) -> None:
    """Write the latest liveness timestamp."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(str(float(ts)), encoding="utf-8")
    os.replace(tmp, target)


def is_stale(path: str, max_age_s: float) -> bool:
    """Return True if heartbeat is missing, invalid, or too old."""
    try:
        ts = float(Path(path).read_text(encoding="utf-8").strip())
    except Exception:
        return True
    return (time.time() - ts) > max_age_s


async def run_with_watchdog(
    make_coro: Callable[[], Awaitable[object]],
    *,
    heartbeat_path: str,
    kill_path: str,
    max_restarts: int = 1000,
    backoff_s: float = 5.0,
) -> None:
    """Run a coroutine factory, restarting on exceptions until killed."""
    restarts = 0
    while not Path(kill_path).exists():
        heartbeat(heartbeat_path, time.time())
        try:
            await make_coro()
            heartbeat(heartbeat_path, time.time())
            return
        except asyncio.CancelledError:
            heartbeat(heartbeat_path, time.time())
            raise
        except Exception:
            restarts += 1
            heartbeat(heartbeat_path, time.time())
            if restarts > max_restarts:
                raise
            if Path(kill_path).exists():
                return
            delay = min(backoff_s * (2 ** (restarts - 1)), 60.0)
            await asyncio.sleep(delay)
