import asyncio

from agent.ops.watchdog import heartbeat, is_stale, run_with_watchdog


def test_heartbeat_and_stale_detection(tmp_path, monkeypatch):
    path = tmp_path / "heartbeat.txt"

    monkeypatch.setattr("agent.ops.watchdog.time.time", lambda: 100.0)
    heartbeat(str(path), 95.0)

    assert not is_stale(str(path), max_age_s=10.0)
    assert is_stale(str(path), max_age_s=4.0)
    assert is_stale(str(tmp_path / "missing.txt"), max_age_s=10.0)


def test_run_with_watchdog_restarts_on_exception_without_real_sleep(tmp_path, monkeypatch):
    sleeps = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("agent.ops.watchdog.asyncio.sleep", fake_sleep)
    calls = {"n": 0}

    async def worker():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")

    asyncio.run(
        run_with_watchdog(
            worker,
            heartbeat_path=str(tmp_path / "hb"),
            kill_path=str(tmp_path / "kill"),
            backoff_s=2.0,
        )
    )

    assert calls["n"] == 2
    assert sleeps == [2.0]
    assert not is_stale(str(tmp_path / "hb"), max_age_s=60.0)


def test_run_with_watchdog_kill_file_stops(tmp_path, monkeypatch):
    async def fake_sleep(delay):
        raise AssertionError("sleep should not be called after kill")

    monkeypatch.setattr("agent.ops.watchdog.asyncio.sleep", fake_sleep)
    kill_path = tmp_path / "kill"
    calls = {"n": 0}

    async def worker():
        calls["n"] += 1
        kill_path.write_text("stop", encoding="utf-8")
        raise RuntimeError("stop requested")

    asyncio.run(
        run_with_watchdog(
            worker,
            heartbeat_path=str(tmp_path / "hb"),
            kill_path=str(kill_path),
        )
    )

    assert calls["n"] == 1

