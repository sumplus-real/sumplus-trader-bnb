"""Single entrypoint: python -m agent.cli <command>

  demo      guardrail enforcement demo — allow / clamp / reject (offline, no keys)
  tick      run ONE decision through the full pipeline + print the receipt (offline)
  simulate  drive the real pipeline over a synthetic week (calm/chop/crash/recovery) [weeks]
  verify    recompute the committed policy hash + verify the receipt chain
  commit    print the commit-reveal payload + on-chain calldata (dry-run; --send to broadcast)
  web       launch the dashboard  [port]
  loop      run the live unattended loop (watchdog + persistent state)
  register  register the agent wallet as an ERC-8004 identity (needs wallet + RPC)
"""
from __future__ import annotations

import asyncio
import json
import sys


def main(argv: list[str] | None = None) -> int:
    args = (argv if argv is not None else sys.argv[1:]) or ["demo"]
    cmd = args[0]

    if cmd == "demo":
        from agent.demo.guardrail_demo import main as demo_main
        demo_main()
    elif cmd == "tick":
        from agent import core
        from agent.execution.factory import make_backend
        from agent.execution.executor import Executor
        backend = make_backend("mock")
        execu = Executor(backend, mode="mock")
        state = {"nav": 500.0, "stable_usd": 500.0, "high_water_mark": 500.0, "positions": {}}
        res, _ = asyncio.run(core.tick(state=state, executor=execu))
        print(f"intent={res.intent_action}  verdict={res.verdict}  rung={res.ladder_rung}")
        print(f"reason: {res.reason}")
        print(f"receipt: {res.receipt_hash}")
    elif cmd == "simulate":
        from agent.simulate import simulate
        weeks = float(args[1]) if len(args) > 1 else 1.0
        print(json.dumps(asyncio.run(simulate(weeks=weeks)), indent=2))
    elif cmd == "verify":
        from agent.policy.commit import verify_live
        print(json.dumps(verify_live(), indent=2))
    elif cmd == "commit":
        from agent.identity.commit_publish import publish
        print(json.dumps(publish(dry_run=("--send" not in args)), indent=2))
    elif cmd == "web":
        import uvicorn
        port = int(args[1]) if len(args) > 1 else 8800
        print(f"Open http://127.0.0.1:{port}")
        uvicorn.run("agent.web:app", host="127.0.0.1", port=port, log_level="warning")
    elif cmd == "loop":
        from agent.run_live import run
        asyncio.run(run())
    elif cmd == "register":
        from agent.identity.register_8004 import register, REGISTRY_BSC
        import os
        out = register(rpc_url=os.environ["BSC_RPC"], registry_addr=REGISTRY_BSC,
                       private_key=os.environ["AGENT_WALLET_PRIVATE_KEY"],
                       agent_domain=os.environ.get("AGENT_DOMAIN", "sumplus.xyz"))
        print(out)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
